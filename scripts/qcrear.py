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
        println("[qcrear] Responde y/n, o escribe 'salir'.")


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

    ok = prompt_yn(f"[qcrear] ¿Crear entrada para {nxt}?", default_yes=True)
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

# -----------------------------
# Main
# -----------------------------

def main() -> int:
    try:
        println(SEP)
        println(" qcrear (scaffold)")
        println(SEP)

        pf = run_preflight()
        if not pf.ok_repo:
            eprintln("[qcrear] ERROR: No encuentro el repo root.")
            return 1

        # mostrar preflight bonito
        println(f"✅ repo: {pf.repo}")
        if pf.ok_archivo_json:
            println(f"✅ archivo.json: {pf.archivo_json}")
        else:
            eprintln(f"❌ archivo.json no existe: {pf.archivo_json}")
            return 1

        target = choose_target_date(sys.argv)

        # Si ya existe en archivo.json, qcrear no hace nada.
        archivo = load_archivo_json()
        if date_exists_in_archivo(archivo, target):
            println("")
            println(f"[qcrear] Ya existe una entrada publicada para {target}.")
            println("[qcrear] Usa qcambiar si quieres modificarla.")
            return 0

        println("")
        if txt_exists_for_date(target):
            println(f"[qcrear] Continuar preparación: {target} (txt ya existe)")
        else:
            println(f"[qcrear] Crear entrada: {target} (txt no existe)")


        # Pull robusto (poema + análisis). No preguntamos "¿hacer pull?".
        println("")
        println(SEP)
        println(f" Pull Google Docs — {target}")
        println(SEP)

        poem_obj = run_py_json(
            "scripts/gdocs_pull_poem_by_date.py",
            ["--date", target],
        )
        analysis_obj = run_py_json(
            "scripts/gdocs_pull_analysis_by_date.py",
            ["--date", target],
        )

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

        # Resumen bonito
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

        # Preview opcional (bonito) + confirmación fuerte
        println("")
        want_preview = prompt_yn("[qcrear] ¿Ver preview de los 3 escritos?", default_yes=True)
        if want_preview:
            println("")
            println(SEP)
            println(" Preview (Google Docs)")
            println(SEP)
            preview_block("# POEMA", poem_text, n=10)
            preview_block("# POEMA_CITADO", poema_citado, n=10)
            preview_block("# TEXTO", texto, n=10)

        ok = prompt_yn("[qcrear] ¿Confirmas que esto se ve correcto?", default_yes=False)
        if not ok:
            raise UserAbort()

        # Generar/reescribir <fecha>.txt ANTES de keywords (build output)
        txt_path = txt_path_for_date(target)  # o usa tu helper único si lo fusionaste
        println("")
        if txt_path.exists():
            overwrite = prompt_yn(f"[qcrear] Ya existe {txt_path}. ¿Regenerarlo desde Google Docs (sobrescribir)?", default_yes=False)
            if not overwrite:
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
            
        println("")
        println(SEP)
        println(" Keywords (estado)")
        println(SEP)
        pending = load_pending_keywords()

        if pending is None:
            println("")
            println("[qcrear] No hay pending_keywords.txt.")
            println("[qcrear] (Aún no implementado) Siguiente paso: generar keywords y guardarlas.")
        else:
            println("")
            pdate = pending.get("date", "")
            pkws = pending.get("keywords") or []
            pf = (pending.get("docs_fingerprint") or "").strip()

            println(f"[qcrear] pending_keywords.txt encontrado (date={pdate}, keywords={len(pkws)}).")

            # Ultra-robusto: si falta docs_fingerprint o no coincide, no es publicable.
            if pdate != target:
                println("[qcrear] pending_keywords NO corresponde a esta fecha.")
            elif len(pkws) == 0:
                println("[qcrear] pending_keywords está vacío (no se puede publicar).")
            elif not pf:
                println("[qcrear] pending_keywords no tiene docs_fingerprint (no publicable en modo ultra-robusto).")
            elif pf != fp:
                println("[qcrear] pending_keywords está desfasado: fingerprint no coincide con Google Docs.")
            else:
                println("[qcrear] ✅ pending_keywords válido y vigente (ultra-robusto).")
                preview = top_keywords_preview(pending, n=10)
                println("Top keywords:")
                for w, wt in preview:
                    println(f"  - {w} ({wt})")
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
