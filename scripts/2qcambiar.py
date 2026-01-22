#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure scripts/ is importable
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from qcommon import (  # type: ignore
    println,
    eprintln,
    UserAbort,
    prompt_yn,
    run_preflight,
    parse_yyyy_mm_dd,
    load_archivo_json,
    find_entry_by_date,
    extract_section,
    normalize_text_for_hash,
    run_py_json,
    write_text_atomic,
    git,
)

SEP = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
DATE_KEYS = ["MY_POEM_TITLE", "POETA", "POEM_TITLE", "BOOK_TITLE"]
SECTION_KEYS = ["poema", "poema_citado", "texto"]


# -----------------------------
# Paths / IO helpers
# -----------------------------

def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def state_dir() -> Path:
    return repo_root() / "state"


def archivo_path() -> Path:
    return repo_root() / "data" / "archivo.json"


def pending_kw_path() -> Path:
    return state_dir() / "pending_keywords.txt"


def pending_entry_path() -> Path:
    return state_dir() / "pending_entry.json"


def txt_path_for_date(date_str: str) -> Path:
    y, m, _d = date_str.split("-")
    return repo_root() / "data" / "textos" / y / m / f"{date_str}.txt"


def _norm_newlines(s: str) -> str:
    return (s or "").replace("\r\n", "\n").replace("\r", "\n")


def _clean_section_for_write(s: str) -> str:
    # Preserve content, only normalize newlines and trim trailing whitespace at end
    return _norm_newlines(s).rstrip()


def git_status_porcelain() -> List[str]:
    proc = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    out = (proc.stdout or "").splitlines()
    return [ln.rstrip("\n") for ln in out if ln.strip()]


def git_file_has_diff(path: Path) -> bool:
    if not path.exists():
        return False
    proc = subprocess.run(["git", "ls-files", "--error-unmatch", str(path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return True  # untracked
    proc2 = subprocess.run(["git", "diff", "--quiet", "--", str(path)])
    return proc2.returncode != 0


def parse_metadata_from_txt(raw: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in _norm_newlines(raw).splitlines():
        line = line.strip()
        if not line:
            continue
        if line in {"# POEMA", "# POEMA_CITADO", "# TEXTO"}:
            break
        if line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip()
            if k in set(DATE_KEYS):
                out[k] = v
    return out


def read_current_payload(date_str: str, txt_path: Path) -> Dict[str, Any]:
    if not txt_path.exists():
        return {"date": date_str, **{k: "" for k in DATE_KEYS}, **{k: "" for k in SECTION_KEYS}}
    raw = txt_path.read_text(encoding="utf-8")
    meta = parse_metadata_from_txt(raw)
    return {
        "date": date_str,
        "MY_POEM_TITLE": meta.get("MY_POEM_TITLE", ""),
        "POETA": meta.get("POETA", ""),
        "POEM_TITLE": meta.get("POEM_TITLE", ""),
        "BOOK_TITLE": meta.get("BOOK_TITLE", ""),
        "poema": extract_section(raw, "# POEMA"),
        "poema_citado": extract_section(raw, "# POEMA_CITADO"),
        "texto": extract_section(raw, "# TEXTO"),
    }


def normalize_pulled_payload(pulled: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(pulled or {})
    # poem pull
    if "poem" in out and "poema" not in out:
        out["poema"] = out.get("poem", "")
    if "title" in out and "MY_POEM_TITLE" not in out:
        out["MY_POEM_TITLE"] = out.get("title", "")
    # analysis pull
    if "analysis" in out and "texto" not in out:
        out["texto"] = out.get("analysis", "")
    if "poem_citado" in out and "poema_citado" not in out:
        out["poema_citado"] = out.get("poem_citado", "")
    # metadata
    if "poet" in out and "POETA" not in out:
        out["POETA"] = out.get("poet", "")
    if "poem_title" in out and "POEM_TITLE" not in out:
        out["POEM_TITLE"] = out.get("poem_title", "")
    if "book_title" in out and "BOOK_TITLE" not in out:
        out["BOOK_TITLE"] = out.get("book_title", "")

    # normalize line endings
    for k, v in list(out.items()):
        if isinstance(v, str):
            out[k] = _norm_newlines(v)
    return out


# -----------------------------
# Fingerprints (same spirit as qcrear)
# -----------------------------

def docs_fingerprint(poem: str, poem_citado: str, texto: str) -> str:
    payload = "\n\n---\n\n".join([
        normalize_text_for_hash(poem),
        normalize_text_for_hash(poem_citado),
        normalize_text_for_hash(texto),
    ])
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{h}"


def txt_fingerprint_from_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    poema = extract_section(raw, "# POEMA")
    citado = extract_section(raw, "# POEMA_CITADO")
    texto = extract_section(raw, "# TEXTO")
    # Permitimos secciones vacías (en algunos casos poem_citado podría ser vacío).
    return docs_fingerprint(poema, citado, texto)


# -----------------------------
# pending_keywords (schema)
# -----------------------------

def load_pending_keywords() -> Optional[dict]:
    p = pending_kw_path()
    if not p.exists():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if "date" not in obj or "keywords" not in obj:
        return None
    # placeholder?
    if str(obj.get("date", "")).strip() == "" and obj.get("keywords", []) == []:
        return None
    return obj


def pending_keywords_for_date(obj: Optional[dict], date_str: str) -> bool:
    return bool(obj) and str(obj.get("date", "")).strip() == date_str and isinstance(obj.get("keywords", None), list)


def write_pending_keywords(target: str, keywords: list[dict], docs_fp: str) -> None:
    payload = {
        "date": target,
        "docs_fingerprint": docs_fp,
        "keywords": keywords,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    pending_kw_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def reset_pending_files() -> None:
    # Igual espíritu que qcrear: dejar placeholder limpio tras publish
    pending_kw_path().write_text(
        json.dumps({"date": "", "docs_fingerprint": "", "keywords": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    pending_entry_path().write_text("{}", encoding="utf-8")


def keywords_from_archivo_entry(entry: Dict[str, Any]) -> List[Tuple[str, int]]:
    kws = entry.get("keywords") or []
    pairs: List[Tuple[str, int]] = []
    for kw in kws:
        if not isinstance(kw, dict):
            continue
        w = kw.get("word") or kw.get("keyword") or kw.get("kw") or ""
        wt = kw.get("weight")
        if isinstance(w, str) and w.strip() and isinstance(wt, int):
            pairs.append((w.strip(), wt))
    pairs.sort(key=lambda x: (-x[1], x[0].lower()))
    return pairs


def keywords_from_pending_obj(obj: dict) -> List[Tuple[str, int]]:
    kws = obj.get("keywords") or []
    pairs: List[Tuple[str, int]] = []
    for kw in kws:
        if isinstance(kw, dict) and isinstance(kw.get("word"), str) and isinstance(kw.get("weight"), int):
            pairs.append((kw["word"], kw["weight"]))
    pairs.sort(key=lambda x: (-x[1], x[0].lower()))
    return pairs


def print_keywords_preview(title: str, pairs: List[Tuple[str, int]], n: int = 20) -> None:
    println(SEP)
    println(f"[qcambiar] KEYWORDS — {title}")
    if not pairs:
        println("(vacío)")
    else:
        for w, wt in pairs[:n]:
            println(f"- {w} ({wt})")
        if len(pairs) > n:
            println(f"... (+{len(pairs)-n} más)")
    println(SEP)


def generate_keywords_from_txt(txt_path: Path) -> list[dict]:
    script = repo_root() / "qmp" / "gen_keywords.py"
    if not script.exists():
        raise RuntimeError("No encuentro qmp/gen_keywords.py para generar keywords.")

    # IMPORTANT: usamos el txt_path (no date) para evitar “fecha equivocada”
    cmd = [sys.executable, str(script), str(txt_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Falló generación de keywords:\n{proc.stderr or proc.stdout}")

    try:
        obj = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("gen_keywords.py no devolvió JSON válido.")

    if isinstance(obj, dict) and "keywords" in obj:
        obj = obj["keywords"]

    if not isinstance(obj, list) or len(obj) == 0:
        raise RuntimeError("gen_keywords.py devolvió keywords vacías o inválidas.")

    out: List[dict] = []
    for i, kw in enumerate(obj):
        if not isinstance(kw, dict):
            raise RuntimeError(f"Keyword #{i} inválida.")
        word = kw.get("word") or kw.get("keyword") or kw.get("kw")
        weight = kw.get("weight")
        if not isinstance(word, str) or word.strip() == "":
            raise RuntimeError(f"Keyword #{i} mal formada (word).")
        if not isinstance(weight, int) or weight not in (1, 2, 3):
            raise RuntimeError(f"Keyword #{i} mal formada (weight).")
        out.append({"word": word.strip(), "weight": weight})
    return out


# -----------------------------
# Render / preview / diffs
# -----------------------------

def render_txt(target: str, payload: Dict[str, Any]) -> str:
    parts: List[str] = []
    parts.append(f"FECHA: {target}")

    # metadata (si vacío, lo dejamos igual como línea vacía; consistente)
    parts.append(f"MY_POEM_TITLE: {_clean_section_for_write(payload.get('MY_POEM_TITLE',''))}")
    parts.append(f"POETA: {_clean_section_for_write(payload.get('POETA',''))}")
    parts.append(f"POEM_TITLE: {_clean_section_for_write(payload.get('POEM_TITLE',''))}")
    parts.append(f"BOOK_TITLE: {_clean_section_for_write(payload.get('BOOK_TITLE',''))}")
    parts.append("")

    parts.append("# POEMA")
    parts.append(_clean_section_for_write(payload.get("poema", "")))
    parts.append("")

    parts.append("# POEMA_CITADO")
    parts.append(_clean_section_for_write(payload.get("poema_citado", "")))
    parts.append("")

    parts.append("# TEXTO")
    parts.append(_clean_section_for_write(payload.get("texto", "")))
    parts.append("")
    return "\n".join(parts)


def preview_payload(label: str, payload: Dict[str, Any], n_lines: int = 12) -> None:
    println(SEP)
    println(f"[qcambiar] PREVIEW — {label}")
    println("METADATA:")
    for k in DATE_KEYS:
        println(f"  {k}: {(payload.get(k) or '').strip()}")
    println("")
    for sec, header in [("poema", "POEMA"), ("poema_citado", "POEMA_CITADO"), ("texto", "TEXTO")]:
        txt = _norm_newlines(payload.get(sec, "") or "")
        lines = txt.splitlines()
        println(f"{header} (primeras {min(n_lines,len(lines))} de {len(lines)}):")
        for ln in lines[:n_lines]:
            println(f"  {ln}")
        println("")
    println(SEP)


def compute_diff_report(current: Dict[str, Any], pulled: Dict[str, Any]) -> Tuple[bool, bool, List[str]]:
    report: List[str] = []

    poem_changed = normalize_text_for_hash(current.get("poema", "")) != normalize_text_for_hash(pulled.get("poema", ""))
    citado_changed = normalize_text_for_hash(current.get("poema_citado", "")) != normalize_text_for_hash(pulled.get("poema_citado", ""))
    texto_changed = normalize_text_for_hash(current.get("texto", "")) != normalize_text_for_hash(pulled.get("texto", ""))

    report.append(f"  - POEMA: {'CAMBIÓ' if poem_changed else 'sin cambios'}")
    report.append(f"  - POEMA_CITADO: {'CAMBIÓ' if citado_changed else 'sin cambios'}")
    report.append(f"  - TEXTO: {'CAMBIÓ' if texto_changed else 'sin cambios'}")

    my_title_changed = normalize_text_for_hash(current.get("MY_POEM_TITLE", "")) != normalize_text_for_hash(pulled.get("MY_POEM_TITLE", ""))
    poeta_changed = normalize_text_for_hash(current.get("POETA", "")) != normalize_text_for_hash(pulled.get("POETA", ""))
    poem_title_changed = normalize_text_for_hash(current.get("POEM_TITLE", "")) != normalize_text_for_hash(pulled.get("POEM_TITLE", ""))
    book_title_changed = normalize_text_for_hash(current.get("BOOK_TITLE", "")) != normalize_text_for_hash(pulled.get("BOOK_TITLE", ""))

    report.append(f"  - MY_POEM_TITLE: {'CAMBIÓ' if my_title_changed else 'sin cambios'}")
    report.append(f"  - POETA: {'CAMBIÓ' if poeta_changed else 'sin cambios'}")
    report.append(f"  - POEM_TITLE: {'CAMBIÓ' if poem_title_changed else 'sin cambios'}")
    report.append(f"  - BOOK_TITLE: {'CAMBIÓ' if book_title_changed else 'sin cambios'}")

    P = poem_changed or my_title_changed
    A = citado_changed or texto_changed or poeta_changed or poem_title_changed or book_title_changed
    return P, A, report


def build_commit_message(date_str: str, P: bool, A: bool, K: bool) -> str:
    if K and not P and not A:
        return f"keywords {date_str}"
    parts: List[str] = []
    if P:
        parts.append("poema")
    if A:
        parts.append("análisis")
    if K:
        parts.append("keywords")
    if not parts:
        return f"edicion {date_str}"
    return f"cambio de {' + '.join(parts)} {date_str}"


def warn_or_block_dirty_repo(allowed_paths: List[Path]) -> None:
    """
    No más error “molesto”: si hay cambios fuera del publish, avisamos y preguntamos.
    Además: comparamos repo-relative (git status) vs allowed relativo.
    """
    root = repo_root().resolve()

    allowed = set()
    for p in allowed_paths:
        try:
            rel = p.resolve().relative_to(root)
            allowed.add(rel.as_posix())
        except Exception:
            allowed.add(str(p).replace("\\", "/").lstrip("./"))

    bad: List[str] = []
    for ln in git_status_porcelain():
        path = ln[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        path = path.replace("\\", "/").lstrip("./")
        if path not in allowed:
            bad.append(path)

    if bad:
        println("")
        println("[qcambiar] ⚠️  Tu repo tiene cambios NO relacionados con este publish:")
        for p in bad[:20]:
            println(f"  - {p}")
        if len(bad) > 20:
            println(f"  ... (+{len(bad)-20} más)")
        if not prompt_yn("[qcambiar] ¿Continuar y publicar solo los archivos del publish?", default_yes=False):
            raise RuntimeError("Cancelado por repo sucio (cambios no relacionados).")


def main() -> int:
    try:
        run_preflight()

        if len(sys.argv) != 2:
            eprintln("Uso: qcambiar YYYY-MM-DD")
            return 1

        date_str = sys.argv[1]
        parse_yyyy_mm_dd(date_str)

        archivo = load_archivo_json()
        entry = find_entry_by_date(archivo, date_str)
        if not entry:
            eprintln(f"[qcambiar] No existe entrada publicada para {date_str}. Usa qcrear.")
            return 1

        txt_path = txt_path_for_date(date_str)
        current_payload = read_current_payload(date_str, txt_path)
        existing_fp = txt_fingerprint_from_file(txt_path)

        println(SEP)
        println(f"[qcambiar] OK: entrada publicada encontrada para {date_str}.")
        println("")
        println("[qcambiar] Haciendo pull desde Google Docs para comparar…")

        poem_pull = run_py_json("scripts/gdocs_pull_poem_by_date.py", ["--date", date_str])
        analysis_pull = run_py_json("scripts/gdocs_pull_analysis_by_date.py", ["--date", date_str])

        pulled_raw: Dict[str, Any] = {}
        pulled_raw.update(poem_pull or {})
        pulled_raw.update(analysis_pull or {})
        pulled = normalize_pulled_payload(pulled_raw)

        for k in DATE_KEYS + SECTION_KEYS:
            pulled.setdefault(k, "")

        P_changed, A_changed, report_lines = compute_diff_report(current_payload, pulled)
        P_for_msg = P_changed
        A_for_msg = A_changed

        # Mensaje INMEDIATO después del pull
        println("")
        if P_changed or A_changed:
            println("[qcambiar] ⚠️ Cambios detectados (Google Docs ≠ publicado):")
            for ln in report_lines:
                println(ln)
        else:
            println("[qcambiar] ✅ Google Docs coincide con el .txt publicado (sin diferencias).")

        # Preview opcional (publicado)
        println("")
        if prompt_yn("[qcambiar] ¿Ver preview del .txt publicado?", default_yes=False):
            preview_payload("PUBLICADO (.txt)", current_payload)

        txt_changed = False

        # Aplicación de cambios SOLO si hay diferencias
        if P_changed or A_changed:
            println("")
            if prompt_yn("[qcambiar] ¿Aplicar estos cambios al .txt publicado?", default_yes=False):
                final_payload = dict(current_payload)
                for k in DATE_KEYS + SECTION_KEYS:
                    final_payload[k] = pulled.get(k, "")

                if prompt_yn("[qcambiar] ¿Ver preview del contenido FINAL a escribir?", default_yes=True):
                    preview_payload("FINAL (a escribir)", final_payload)

                if not prompt_yn("[qcambiar] ¿Confirmas que el contenido se ve correcto?", default_yes=False):
                    println("[qcambiar] OK. Cancelado.")
                    return 0

                new_txt = render_txt(date_str, final_payload)
                write_text_atomic(txt_path, new_txt)
                println(f"[qcambiar] ✅ Escribí build output: {txt_path}")

                new_fp = txt_fingerprint_from_file(txt_path)
                txt_changed = (
                    (existing_fp is None and new_fp is not None)
                    or (existing_fp != new_fp)
                    or git_file_has_diff(txt_path)
                )
            else:
                println("[qcambiar] OK. No se aplicaron cambios de texto.")

        # -----------------------------
        # Keywords flow (siempre)
        # -----------------------------
        pending_obj = load_pending_keywords()

        println("")
        if prompt_yn("[qcambiar] ¿Ver keywords?", default_yes=False):
            if pending_keywords_for_date(pending_obj, date_str):
                print_keywords_preview("PENDIENTES (state/pending_keywords.txt)", keywords_from_pending_obj(pending_obj))
            else:
                print_keywords_preview("PUBLICADAS (data/archivo.json)", keywords_from_archivo_entry(entry))

        apply_keywords = False
        regenerated = False

        # Si ya hay pending para esa fecha, damos opción de aplicarlas
        if pending_keywords_for_date(pending_obj, date_str):
            apply_keywords = prompt_yn(
                "[qcambiar] Detecté keywords pendientes para esta fecha. ¿Publicarlas en este publish?",
                default_yes=True,
            )

        # Regenerar
        if prompt_yn("[qcambiar] ¿Quieres regenerar keywords?", default_yes=False):
            if pending_obj and (pending_obj.get("date") or pending_obj.get("keywords")):
                if not prompt_yn("[qcambiar] Ya hay pending_keywords.txt con contenido. ¿Reemplazarlo?", default_yes=False):
                    println("[qcambiar] OK. No regeneré keywords.")
                else:
                    kws = generate_keywords_from_txt(txt_path)
                    fp = txt_fingerprint_from_file(txt_path) or docs_fingerprint(
                        current_payload.get("poema", ""),
                        current_payload.get("poema_citado", ""),
                        current_payload.get("texto", ""),
                    )
                    write_pending_keywords(date_str, kws, fp)
                    pending_obj = load_pending_keywords()
                    regenerated = True
                    apply_keywords = True
                    println("[qcambiar] ✅ Regeneré keywords → pending_keywords.txt actualizado.")
            else:
                kws = generate_keywords_from_txt(txt_path)
                fp = txt_fingerprint_from_file(txt_path) or docs_fingerprint(
                    current_payload.get("poema", ""),
                    current_payload.get("poema_citado", ""),
                    current_payload.get("texto", ""),
                )
                write_pending_keywords(date_str, kws, fp)
                pending_obj = load_pending_keywords()
                regenerated = True
                apply_keywords = True
                println("[qcambiar] ✅ Regeneré keywords → pending_keywords.txt actualizado.")

            if regenerated and prompt_yn("[qcambiar] ¿Ver keywords nuevas?", default_yes=False):
                if pending_keywords_for_date(pending_obj, date_str):
                    print_keywords_preview("PENDIENTES (post-update)", keywords_from_pending_obj(pending_obj))
                else:
                    println("[qcambiar] (No encontré pending_keywords para esta fecha.)")

        K_changed = bool(apply_keywords)
        commit_msg = build_commit_message(date_str, P_for_msg, A_for_msg, K_changed)

        println("")
        println("[qcambiar] Resumen (resultado):")
        println(f"  - cambios detectados/aplicados en texto: {txt_changed}")
        println(f"  - aplicar keywords:                     {K_changed}")

        if not txt_changed and not K_changed:
            println("ℹ️  No hay nada que publicar.")
            return 0

        println("")
        if not prompt_yn("[qcambiar] ¿Hacer commit + push ahora?", default_yes=False):
            println("[qcambiar] OK. No se publicó nada.")
            return 0

        branch = git(["rev-parse", "--abbrev-ref", "HEAD"])
        if branch != "main":
            println(f"[qcambiar] ⚠️  Estás en branch '{branch}', no en main.")
            if not prompt_yn("[qcambiar] ¿Continuar de todos modos?", default_yes=False):
                println("[qcambiar] OK. Cancelado.")
                return 0

        println("")
        println(f"[qcambiar] Fecha:  {date_str}")
        println(f"[qcambiar] Commit: {commit_msg}")
        if not prompt_yn("[qcambiar] ¿Confirmar publish (commit + push)?", default_yes=False):
            println("[qcambiar] OK. No se publicó nada.")
            return 0

        # Avisar si repo sucio (pero no bloquear con error molesto)
        allowed = [txt_path, archivo_path(), pending_entry_path(), pending_kw_path()]
        warn_or_block_dirty_repo(allowed)

        # merge_pending (actualiza archivo.json + pending_entry.json; keywords opcional)
        mp_args = [
            "--archivo", str(archivo_path()),
            "--pending-kw", str(pending_kw_path()),
            "--pending-entry", str(pending_entry_path()),
        ]
        if K_changed:
            mp_args.append("--apply-keywords")
        mp_args.append(str(txt_path))

        _status = run_py_json("qmp/merge_pending.py", mp_args)

        # Cleanup staging files ANTES del commit (como qcrear)
        reset_pending_files()

        # Stage + commit + push
        git(["add", str(txt_path)])
        git(["add", str(archivo_path())])
        git(["add", str(pending_entry_path())])
        git(["add", str(pending_kw_path())])

        git(["commit", "-m", commit_msg])
        git(["push", "origin", branch])

        println(f"✅ Publicado: {commit_msg}")
        return 0

    except UserAbort:
        println("[qcambiar] OK. Abortado.")
        return 0
    except Exception as e:
        eprintln(f"[qcambiar] ERROR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
