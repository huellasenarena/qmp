#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple

AUTO = "--auto" in sys.argv
DRY_RUN = "--dry-run" in sys.argv


# -----------------------------
# UI helpers
# -----------------------------

SEP = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def println(msg: str = "") -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def eprintln(msg: str = "") -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def is_exit_token(s: str) -> bool:
    s = s.strip().lower()
    return s in {"salir", "q", "quit", "exit"}


def prompt_yn(question: str, default_yes: bool = False) -> bool:
    """
    Pregunta y/N o Y/n. Acepta 'salir' en cualquier momento.
    default_yes=False -> [y/N]
    default_yes=True  -> [Y/n]
    """
    if AUTO:
        # En CI / automation: jamás bloqueamos por input()
        # Respetamos el default, así puedes controlar la lógica desde el código.
        return default_yes

    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        ans = input(f"{question} {suffix}: ").strip()
        if is_exit_token(ans):
            raise UserAbort()
        if ans == "":
            return default_yes
        if ans.lower() in {"y", "yes", "s", "si", "sí"}:
            return True
        if ans.lower() in {"n", "no"}:
            return False



class UserAbort(Exception):
    pass


# -----------------------------
# Paths / repo detection
# -----------------------------

def repo_root() -> Path:
    # Asumimos scripts/qcrear.py, subimos 1 nivel
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return repo_root() / "data"


def archivo_json_path() -> Path:
    return data_dir() / "archivo.json"


def state_dir() -> Path:
    return repo_root() / "state"


@dataclass(frozen=True)
class Preflight:
    repo: Path
    archivo_json: Path
    ok_repo: bool
    ok_archivo_json: bool


def run_preflight() -> Preflight:
    r = repo_root()
    aj = archivo_json_path()
    ok_repo = r.exists()
    ok_archivo_json = aj.exists()

    return Preflight(
        repo=r,
        archivo_json=aj,
        ok_repo=ok_repo,
        ok_archivo_json=ok_archivo_json,
    )


# -----------------------------
# Date helpers
# -----------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_yyyy_mm_dd(s: str) -> date:
    if not DATE_RE.match(s):
        raise ValueError("Formato inválido, usa YYYY-MM-DD.")
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)


def load_archivo_json() -> dict:
    p = archivo_json_path()
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def date_exists_in_archivo(archivo: dict, target: str) -> bool:
    """
    True si existe un objeto con {"date": target} en cualquier parte del JSON.
    Tolerante a estructura: busca recursivamente.
    """
    found = False

    def walk(obj):
        nonlocal found
        if found:
            return
        if isinstance(obj, dict):
            if obj.get("date") == target:
                found = True
                return
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for it in obj:
                walk(it)

    walk(archivo)
    return found


def get_next_date_from_archivo(archivo: dict) -> Optional[str]:
    """
    Intenta inferir NEXT_DATE:
    - Si hay entradas con 'date', tomar el máximo y +1 día.
    - Si la estructura es distinta, devolvemos None.

    Esto es scaffold: lo refinamos cuando integremos tu schema exacto.
    """
    dates: list[date] = []
    # Buscamos cualquier campo 'date' al nivel de items en listas comunes
    # (muy tolerante).
    def walk(obj):
        if isinstance(obj, dict):
            if "date" in obj and isinstance(obj["date"], str) and DATE_RE.match(obj["date"]):
                try:
                    dates.append(parse_yyyy_mm_dd(obj["date"]))
                except Exception:
                    pass
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for it in obj:
                walk(it)

    walk(archivo)

    if not dates:
        return None

    last = max(dates)
    nxt = last.toordinal() + 1
    return date.fromordinal(nxt).isoformat()

def txt_path_for_date(target: str) -> Path:
    y, m, _ = target.split("-")
    return data_dir() / "textos" / y / m / f"{target}.txt"


def txt_exists_for_date(target: str) -> bool:
    return txt_path_for_date(target).exists()


def choose_target_date(argv: list[str]) -> str:
    if len(argv) >= 2:
        # argv[0] es el script
        s = argv[1].strip()
        if is_exit_token(s):
            raise UserAbort()
        _ = parse_yyyy_mm_dd(s)  # valida
        return s

    # no date provided: propose NEXT_DATE from archivo.json
    archivo = load_archivo_json()
    nxt = get_next_date_from_archivo(archivo)

    if nxt is None:
        # fallback: hoy (pero NO asumimos zona horaria aquí; solo scaffold)
        today = date.today().isoformat()
        use = prompt_yn(f"[qcrear] No pude inferir NEXT_DATE. ¿Usar hoy ({today})?", default_yes=False)
        if not use:
            raise UserAbort()
        return today

    # Mensaje correcto según exista o no el build output (.txt)
    if txt_exists_for_date(nxt):
        msg = f"[qcrear] El archivo {txt_path_for_date(nxt)} ya existe. ¿Continuar preparación para {nxt}?"
    else:
        msg = f"[qcrear] ¿Crear entrada para {nxt}?"

    ok = prompt_yn(msg, default_yes=True)

    if not ok:
        raise UserAbort()
    return nxt
import subprocess
import hashlib

def run_py_json(script_relpath: str, args: list[str]) -> dict:
    """
    Ejecuta un script python del repo y parsea stdout como JSON.
    Aborta con error claro si el script falla o si stdout no es JSON.
    """
    script_path = repo_root() / script_relpath
    if not script_path.exists():
        raise RuntimeError(f"No encuentro {script_relpath} en el repo.")

    cmd = [sys.executable, str(script_path), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        msg = stderr or stdout or f"Exit code {proc.returncode}"
        raise RuntimeError(f"Falló {script_relpath}: {msg}")

    out = (proc.stdout or "").strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(f"{script_relpath} no devolvió JSON válido. Stdout:\n{out}")
def normalize_text_for_hash(s: str) -> str:
    # Normalización estable: newlines + espacios finales + trimming
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in s.split("\n")]
    # quitar vacíos extremos
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()
    return "\n".join(lines)

def docs_fingerprint(poem: str, poem_citado: str, texto: str) -> str:
    payload = "\n\n---\n\n".join([
        normalize_text_for_hash(poem),
        normalize_text_for_hash(poem_citado),
        normalize_text_for_hash(texto),
    ])
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{h}"

def extract_section(txt: str, header: str) -> str:
    """
    Extrae el contenido debajo de un header exacto ('# POEMA', etc.)
    hasta el siguiente header '# ' o EOF.
    """
    txt = txt.replace("\r\n", "\n").replace("\r", "\n")
    lines = txt.split("\n")

    try:
        start = lines.index(header) + 1
    except ValueError:
        return ""

    out = []
    for ln in lines[start:]:
        if ln.startswith("# "):
            break
        out.append(ln)
    return "\n".join(out)

def txt_fingerprint_from_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    poema = extract_section(raw, "# POEMA")
    citado = extract_section(raw, "# POEMA_CITADO")
    texto = extract_section(raw, "# TEXTO")

    # si falta alguna sección, no confiamos
    if normalize_text_for_hash(poema) == "" or normalize_text_for_hash(citado) == "" or normalize_text_for_hash(texto) == "":
        return None

    return docs_fingerprint(poema, citado, texto)


def load_pending_keywords() -> Optional[dict]:
    p = state_dir() / "pending_keywords.txt"
    if not p.exists():
        return None

    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"pending_keywords.txt inválido: {e}")

    if not isinstance(obj, dict):
        raise RuntimeError("pending_keywords.txt inválido: debe ser JSON objeto.")

    # Si está vacío como placeholder, lo tratamos como "no hay pending"
    if obj.get("date", "") == "" and obj.get("keywords", []) == []:
        return None

    # Validación estructural
    if "date" not in obj or "keywords" not in obj:
        raise RuntimeError("pending_keywords.txt inválido: falta 'date' o 'keywords'.")

    if not isinstance(obj["date"], str) or not DATE_RE.match(obj["date"]):
        raise RuntimeError("pending_keywords.txt inválido: 'date' debe ser YYYY-MM-DD.")

    if not isinstance(obj["keywords"], list):
        raise RuntimeError("pending_keywords.txt inválido: 'keywords' debe ser lista.")

    # Si existe pero está vacío (con fecha), es válido pero no publicable
    if len(obj["keywords"]) == 0:
        return obj

    # Validar items: {"word": str, "weight": int}
    for i, kw in enumerate(obj["keywords"]):
        if not isinstance(kw, dict) or "word" not in kw or "weight" not in kw:
            raise RuntimeError(f"pending_keywords.txt inválido: keyword #{i} mal formado.")
        if not isinstance(kw["word"], str) or kw["word"].strip() == "":
            raise RuntimeError(f"pending_keywords.txt inválido: keyword #{i} 'word' vacío.")
        if not isinstance(kw["weight"], int) or kw["weight"] not in (1, 2, 3):
            raise RuntimeError(f"pending_keywords.txt inválido: keyword #{i} 'weight' debe ser 1/2/3.")

    return obj

def write_pending_keywords(
    target: str,
    keywords: list[dict],
    docs_fp: str,
) -> None:
    p = state_dir() / "pending_keywords.txt"
    payload = {
        "date": target,
        "docs_fingerprint": docs_fp,
        "keywords": keywords,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

def top_keywords_preview(obj: dict, n: int = 10) -> list[tuple[str,int]]:
    kws = obj.get("keywords") or []
    pairs = [(k["word"], k["weight"]) for k in kws]
    # ordenar por peso desc, luego alfabético
    pairs.sort(key=lambda x: (-x[1], x[0].lower()))
    return pairs[:n]

def preview_block(name: str, text: str, n: int = 10) -> None:
    lines = normalize_text_for_hash(text).splitlines()
    println(f"— {name} (primeras {min(n, len(lines))} líneas de {len(lines)})")
    for ln in lines[:n]:
        println(f"  {ln}")
    println("")

def render_txt(
    target: str,
    my_poem_title: str,
    poeta: str,
    poem_title: str,
    book_title: str,
    poema: str,
    poema_citado: str,
    texto: str,
) -> str:
    """
    Genera el archivo YYYY-MM-DD.txt completo como build output.
    Metadatos son opcionales pero siempre presentes.
    Los 3 escritos son obligatorios y ya fueron validados antes.
    """
    # Ojo: mantenemos los keys estilo máquina (como tu template actual).
    # Si luego quieres volver a "Poeta:"/"Título:" humano, lo ajustamos.
    parts = []
    parts.append(f"FECHA: {target}")
    parts.append(f"MY_POEM_TITLE: {my_poem_title}".rstrip())
    parts.append(f"POETA: {poeta}".rstrip())
    parts.append(f"POEM_TITLE: {poem_title}".rstrip())
    parts.append(f"BOOK_TITLE: {book_title}".rstrip())
    parts.append("")  # línea en blanco

    parts.append("# POEMA")
    parts.append(normalize_text_for_hash(poema))
    parts.append("")

    parts.append("# POEMA_CITADO")
    parts.append(normalize_text_for_hash(poema_citado))
    parts.append("")

    parts.append("# TEXTO")
    parts.append(normalize_text_for_hash(texto))
    parts.append("")

    return "\n".join(parts)

def write_txt_atomic(path: Path, content: str) -> None:
    """
    Escritura atómica: escribe a temp y luego renombra.
    No deja .bak permanente.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)

def generate_keywords_from_txt(txt_path: Path) -> list[dict]:
    """
    Llama al generador de keywords existente y devuelve la lista
    en formato [{"word": str, "weight": int}, ...]
    """
    script = repo_root() / "qmp" / "gen_keywords.py"
    if not script.exists():
        raise RuntimeError("No encuentro qmp/gen_keywords.py para generar keywords.")

    cmd = [sys.executable, str(script), str(txt_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    if proc.returncode != 0:
        raise RuntimeError(f"Falló generación de keywords:\n{proc.stderr or proc.stdout}")

    try:
        obj = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("gen_keywords.py no devolvió JSON válido.")

        # gen_keywords.py devuelve {"keywords":[...]}
    if isinstance(obj, dict) and "keywords" in obj:
        obj = obj["keywords"]

    if not isinstance(obj, list) or len(obj) == 0:
        raise RuntimeError("gen_keywords.py devolvió keywords vacías o inválidas.")

    # Validar formato
    for i, kw in enumerate(obj):
        if not isinstance(kw, dict):
            raise RuntimeError(f"Keyword #{i} inválida.")
        if "word" not in kw or "weight" not in kw:
            raise RuntimeError(f"Keyword #{i} mal formada.")
        if kw["weight"] not in (1, 2, 3):
            raise RuntimeError(f"Keyword #{i} tiene weight inválido.")

    return obj

def find_script(*relpaths: str) -> Path:
    for rp in relpaths:
        p = repo_root() / rp
        if p.exists():
            return p
    raise RuntimeError(f"No encuentro script. Probé: {', '.join(relpaths)}")

def run_validate_and_normalize_txt(date_str: str, txt_path: Path) -> None:
    """
    Valida y normaliza metadata/headers del .txt (idempotente).
    Si cambia formateo, reescribe el archivo.
    """
    script = find_script("qmp/validate_entry.py", "scripts/validate_entry.py", "validate_entry.py")
    cmd = [sys.executable, str(script), "--mode", "normalize", date_str, str(txt_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "validate_entry.py falló")

    try:
        payload = json.loads(proc.stdout)
    except Exception:
        raise RuntimeError("validate_entry.py no devolvió JSON válido")

    if payload.get("changed_formatting"):
        txt_path.write_text(payload["normalized_text"], encoding="utf-8")

def run_merge_pending(
    txt_path: Path,
    archivo_path: Path,
    pending_kw_path: Path,
    pending_entry_path: Path,
    apply_keywords: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    Ejecuta merge_pending.py y devuelve el STATUS_JSON como dict.
    """
    script = find_script("qmp/merge_pending.py", "scripts/merge_pending.py", "merge_pending.py")
    cmd = [
        sys.executable, str(script),
        str(txt_path),
        "--archivo", str(archivo_path),
        "--pending-kw", str(pending_kw_path),
        "--pending-entry", str(pending_entry_path),
    ]
    if apply_keywords:
        cmd.append("--apply-keywords")
    if dry_run:
        cmd.append("--dry-run")

    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        raise RuntimeError(out.strip() or "merge_pending.py falló")

    status_line = None
    for line in out.splitlines():
        if line.startswith("STATUS_JSON="):
            status_line = line.split("=", 1)[1].strip()
            break
    if not status_line:
        raise RuntimeError("merge_pending.py no emitió STATUS_JSON=")

    return json.loads(status_line)

def apply_pending_entry_into_archivo(date_str: str, pending_entry_path: Path, archivo_path: Path) -> None:
    """
    Inserta/reemplaza entry por fecha en archivo.json y ordena desc por date.
    """
    pending = json.loads(pending_entry_path.read_text(encoding="utf-8"))
    if not isinstance(pending, dict) or pending.get("date") != date_str:
        raise RuntimeError("pending_entry.json inválido o fecha no coincide")

    data = json.loads(archivo_path.read_text(encoding="utf-8"))
    entries = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise RuntimeError("archivo.json inválido: raíz no es lista ni {'entries': [...]}")

    entries = [e for e in entries if isinstance(e, dict) and e.get("date") != date_str]
    entries.append(pending)
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)

    # Mantener formato histórico (lista) como en qmp_publish.sh
    archivo_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def git(cmd: list[str]) -> str:
    proc = subprocess.run(["git", *cmd], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip() or f"git {' '.join(cmd)} falló")
    return (proc.stdout or "").strip()

def ensure_on_branch(expected: str) -> None:
    cur = git(["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if cur != expected:
        raise RuntimeError(f"Branch actual: {cur} (esperado: {expected})")

def clear_pending_keywords_placeholder() -> None:
    p = state_dir() / "pending_keywords.txt"
    p.write_text('{\n  "date": "",\n  "keywords": []\n}\n', encoding="utf-8")


# -----------------------------
# Main
# -----------------------------

def main() -> int:
    try:
        println(SEP)
        println(" qcrear")
        println(SEP)

        # -----------------------------
        # Preflight
        # -----------------------------
        pf = run_preflight()
        if not pf.ok_repo:
            eprintln("[qcrear] ERROR: No encuentro el repo root.")
            return 1

        println(f"✅ repo: {pf.repo}")
        if pf.ok_archivo_json:
            println(f"✅ archivo.json: {pf.archivo_json}")
        else:
            eprintln(f"❌ archivo.json no existe: {pf.archivo_json}")
            return 1

        # -----------------------------
        # Fecha objetivo
        # -----------------------------
        target = choose_target_date(sys.argv)

        # Si ya existe en archivo.json, qcrear no hace nada.
        archivo = load_archivo_json()
        if date_exists_in_archivo(archivo, target):
            println("")
            println(f"[qcrear] Ya existe una entrada publicada para {target}.")
            println("[qcrear] Usa qcambiar si quieres modificarla.")
            return 0

        txt_path = txt_path_for_date(target)
        println("")
        if txt_path.exists():
            println(f"[qcrear] Continuar preparación: {target} (txt existe)")
        else:
            println(f"[qcrear] Crear entrada: {target} (txt no existe)")

        # -----------------------------
        # Pull robusto Google Docs
        # -----------------------------
        println("")
        println(SEP)
        println(f" Pull Google Docs — {target}")
        println(SEP)

        poem_obj = run_py_json("scripts/gdocs_pull_poem_by_date.py", ["--date", target])
        analysis_obj = run_py_json("scripts/gdocs_pull_analysis_by_date.py", ["--date", target])

        my_poem_title = (poem_obj.get("title") or "").strip()   # opcional
        poem_text = (poem_obj.get("poem") or "")
        poeta = (analysis_obj.get("poet") or "").strip()        # opcional
        poem_title = (analysis_obj.get("poem_title") or "").strip()  # opcional
        book_title = (analysis_obj.get("book_title") or "").strip()  # opcional
        poema_citado = (analysis_obj.get("poem_citado") or "")
        texto = (analysis_obj.get("analysis") or "")

        # Validación fuerte: 3 escritos obligatorios
        if normalize_text_for_hash(poem_text) == "":
            raise RuntimeError("ERROR: # POEMA está vacío (Google Docs). Corrige en el doc de POEMAS.")
        if normalize_text_for_hash(poema_citado) == "":
            raise RuntimeError("ERROR: # POEMA_CITADO está vacío (Google Docs). Corrige en el doc de ESCRITOS.")
        if normalize_text_for_hash(texto) == "":
            raise RuntimeError("ERROR: # TEXTO está vacío (Google Docs). Corrige en el doc de ESCRITOS (Versión final).")

        fp = docs_fingerprint(poem_text, poema_citado, texto)

        # -----------------------------
        # Resumen
        # -----------------------------
        println("✅ Pull OK + validación OK")
        println("")
        println("Resumen (metadatos opcionales):")
        println(f"  MY_POEM_TITLE: {my_poem_title or '(vacío)'}")
        println(f"  POETA:         {poeta or '(vacío)'}")
        println(f"  POEM_TITLE:    {poem_title or '(vacío)'}")
        println(f"  BOOK_TITLE:    {book_title or '(vacío)'}")
        println("")
        println("Escritos (obligatorios):")
        println(f"  # POEMA:        {len(normalize_text_for_hash(poem_text).splitlines())} líneas")
        println(f"  # POEMA_CITADO: {len(normalize_text_for_hash(poema_citado).splitlines())} líneas")
        println(f"  # TEXTO:        {len(normalize_text_for_hash(texto).splitlines())} líneas")
        println("")
        println(f"docs_fingerprint: {fp}")

        # -----------------------------
        # Preview (una sola vez)
        # -----------------------------
        println("")
        want_preview = prompt_yn("[qcrear] ¿Ver preview de los 3 escritos?", default_yes=False)
        if want_preview:
            println("")
            println(SEP)
            println(" Preview (Google Docs)")
            println(SEP)
            preview_block("# POEMA", poem_text, n=10)
            preview_block("# POEMA_CITADO", poema_citado, n=10)
            preview_block("# TEXTO", texto, n=10)

        # -----------------------------
        # Decidir si hay que generar/reescribir txt
        # -----------------------------
        existing_txt_fp = txt_fingerprint_from_file(txt_path) if txt_path.exists() else None
        txt_matches_docs = (txt_path.exists() and existing_txt_fp == fp)

        if txt_matches_docs:
            println(f"[qcrear] ✅ El archivo ya coincide con Google Docs: {txt_path}")
            # No preguntamos confirmación ni regeneración.
        else:
            # Solo si NO coincide, pedimos confirmación y (si quieres) generamos el build output
            ok = prompt_yn("[qcrear] ¿Confirmas que esto se ve correcto?", default_yes=False)
            if not ok:
                raise UserAbort()

            println("")
            if txt_path.exists():
                overwrite = prompt_yn(
                    f"[qcrear] El archivo existe pero NO coincide con Google Docs. ¿Regenerarlo (sobrescribir)?",
                    default_yes=False
                )
                if overwrite:
                    content = render_txt(
                        target=target,
                        my_poem_title=my_poem_title,
                        poeta=poeta,
                        poem_title=poem_title,
                        book_title=book_title,
                        poema=poem_text,
                        poema_citado=poema_citado,
                        texto=texto,
                    )
                    write_txt_atomic(txt_path, content)
                    println(f"[qcrear] ✅ Generado: {txt_path}")
                else:
                    println("[qcrear] OK. No regeneré el .txt.")
            else:
                content = render_txt(
                    target=target,
                    my_poem_title=my_poem_title,
                    poeta=poeta,
                    poem_title=poem_title,
                    book_title=book_title,
                    poema=poem_text,
                    poema_citado=poema_citado,
                    texto=texto,
                )
                write_txt_atomic(txt_path, content)
                println(f"[qcrear] ✅ Generado: {txt_path}")

        # Asegurar que hay txt (si el usuario no lo generó y no existía, no seguimos)
        if not txt_path.exists():
            println("[qcrear] No existe .txt local. Termino aquí (sin keywords).")
            return 0

        # -----------------------------
        # Keywords (no automático)
        # -----------------------------
        println("")
        println(SEP)
        println(" Keywords")
        println(SEP)

        pending = load_pending_keywords()
        keywords = None

        # Si hay pending vigente (ultra-robusto), ofrecer usarla
        if pending:
            pdate = pending.get("date", "")
            pkws = pending.get("keywords") or []
            pfk = (pending.get("docs_fingerprint") or "").strip()

            if pdate == target and pfk == fp and pkws:
                println("[qcrear] Keywords pendientes válidas y vigentes.")
                preview = top_keywords_preview(pending, n=10)
                println("Top keywords:")
                for w, wt in preview:
                    println(f"  - {w} ({wt})")

                use_existing = prompt_yn("[qcrear] ¿Usar estas keywords?", default_yes=True)
                if use_existing:
                    keywords = pkws
                    write_pending_keywords(target, keywords, fp)
                    println("[qcrear] ✅ pending_keywords.txt confirmado.")

        # Si no usamos pending, preguntar si quieres generar
        if keywords is None:
            gen_now = prompt_yn("[qcrear] No hay keywords vigentes. ¿Generar keywords ahora?", default_yes=True)
            if not gen_now:
                println("[qcrear] OK. No generé keywords. (No es posible publicar sin keywords.)")
                return 0

            println("[qcrear] Generando keywords desde el .txt…")
            keywords = generate_keywords_from_txt(txt_path)

            # Preview ordenado
            pairs = [(k["word"], k["weight"]) for k in keywords]
            pairs.sort(key=lambda x: (-x[1], x[0].lower()))
            println("Top keywords (nuevas):")
            for w, wt in pairs[:10]:
                println(f"  - {w} ({wt})")

            ok_kw = prompt_yn("[qcrear] ¿Confirmas estas keywords?", default_yes=True)
            if not ok_kw:
                raise UserAbort()

            write_pending_keywords(target, keywords, fp)
            println("[qcrear] ✅ pending_keywords.txt actualizado.")

            print("")
            if DRY_RUN:
                println("[qcrear] DRY RUN: Todo listo, pero NO publicaré (sin archivo.json, sin commit, sin push).")
                return 0

            publish_now = prompt_yn("[qcrear] Todo listo. ¿Publicar ahora (archivo.json + commit + push)?", default_yes=True)
            if not publish_now:
                println("[qcrear] OK. No publiqué. Puedes volver a ejecutar qcrear cuando quieras.")
                return 0


        # -----------------------------
        # Publish gate (ultra-robusto)
        # -----------------------------
        archivo_path = repo_root() / "data" / "archivo.json"
        pending_kw_path = state_dir() / "pending_keywords.txt"
        pending_entry_path = state_dir() / "pending_entry.json"
        # Seguridad: publicar solo desde el branch actual (sin suposiciones)
        branch = git(["rev-parse", "--abbrev-ref", "HEAD"]).strip()

        if branch != "main":
            println("")
            println(f"[qcrear] ⚠️  Estás en el branch '{branch}', no en 'main'.")
            println("[qcrear] Esto publicará los cambios en ESTE branch.")
            ok_branch = prompt_yn(
                f"[qcrear] ¿Publicar de todos modos en '{branch}'?",
                default_yes=False
            )
            if not ok_branch:
                println("[qcrear] OK. Publicación cancelada.")
                return 0

        println(f"[qcrear] Publicando desde branch: {branch}")



        # 2) Validar keywords vigentes (obligatorio para publicar)
        pending = load_pending_keywords()
        if not pending:
            raise RuntimeError("No hay pending_keywords vigentes. No se puede publicar.")
        if (pending.get("date") or "").strip() != target:
            raise RuntimeError("pending_keywords date != target. No se puede publicar.")
        if not (pending.get("keywords") or []):
            raise RuntimeError("pending_keywords está vacío. No se puede publicar.")
        if (pending.get("docs_fingerprint") or "").strip() != fp:
            raise RuntimeError("pending_keywords fingerprint NO coincide con Google Docs. No se puede publicar.")

        # 3) Validar + normalizar .txt (idempotente)
        run_validate_and_normalize_txt(target, txt_path)

        # 4) merge_pending (aplica keywords -> pending_entry.json + status)
        status = run_merge_pending(
            txt_path=txt_path,
            archivo_path=archivo_path,
            pending_kw_path=pending_kw_path,
            pending_entry_path=pending_entry_path,
            apply_keywords=True,
            dry_run=False,
        )

        exists_before = bool(status.get("exists_before"))
        content_changed = bool(status.get("content_changed"))
        keywords_changed = bool(status.get("keywords_changed"))

        # Si no hay cambios y ya existía: no hacemos commit
        if exists_before and (not content_changed) and (not keywords_changed):
            println("ℹ️  No cambió texto ni keywords → no hay commit.")
            return 0

        # 5) Construir commit message
        label = (status.get("my_poem_title") or "").strip() or (status.get("my_poem_snippet") or "").strip() or target
        if not exists_before:
            msg_type = "entrada"
        else:
            if content_changed and keywords_changed:
                msg_type = "edicion texto + keywords"
            elif content_changed:
                msg_type = "edicion de metadatos/escritos"
            else:
                msg_type = "edicion de palabras clave"

        msg = f"{msg_type} {target} — {label}"

        println("")
        println(f"[qcrear] Fecha:  {target}")
        println(f"[qcrear] Commit: {msg}")
        if DRY_RUN:
            println("[qcrear] DRY RUN: llegué al gate final, pero NO haré commit/push.")
            return 0

        confirm = prompt_yn("[qcrear] ¿Confirmar publish (commit + push)?", default_yes=True)
        if not confirm:
            println("[qcrear] OK. Cancelado. No se publicó nada.")
            return 0

        # 6) Aplicar pending_entry.json dentro de archivo.json
        apply_pending_entry_into_archivo(target, pending_entry_path, archivo_path)

        # 7) Git add/commit/push
        git(["add", str(archivo_path), str(txt_path), str(pending_entry_path)])
        git(["commit", "-m", msg])
        git(["push"])

        println(f"✅ Publicado: {msg}")

        # 8) Cleanup: limpiar pending_keywords (placeholder)
        clear_pending_keywords_placeholder()

        # limpiar pending_entry.json también
        pending_entry_path.write_text("{}", encoding="utf-8")

        return 0

    except UserAbort:
        println("[qcrear] Abortado por el usuario. No se hizo ningún cambio.")
        return 0
    except KeyboardInterrupt:
        println("\n[qcrear] Abortado (Ctrl-C). No se hizo ningún cambio.")
        return 130
    except Exception as e:
        eprintln(f"[qcrear] ERROR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
