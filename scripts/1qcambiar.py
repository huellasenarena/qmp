#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Tuple, List

# Ensure scripts/ is importable
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from qcommon import (
    println,
    eprintln,
    UserAbort,
    prompt_yn,
    prompt_choice,
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


# -----------------------------
# Local helpers (NO qcommon deps)
# -----------------------------

def txt_path_for_date_local(date_str: str) -> Path:
    # data/textos/YYYY/MM/YYYY-MM-DD.txt
    y, m, _d = date_str.split("-")
    return Path(__file__).resolve().parent.parent / "data" / "textos" / y / m / f"{date_str}.txt"


def git_file_has_diff(path: Path) -> bool:
    # True if file differs from HEAD (or is untracked)
    if not path.exists():
        return False
    # untracked?
    proc = subprocess.run(["git", "ls-files", "--error-unmatch", str(path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        # not tracked -> treat as diff
        return True
    proc2 = subprocess.run(["git", "diff", "--quiet", "--", str(path)])
    return proc2.returncode != 0

def parse_metadata_from_txt(raw: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip()
            # solo las keys que nos importan
            if k in {"MY_POEM_TITLE", "POETA", "POEM_TITLE", "BOOK_TITLE"}:
                out[k] = v
        # paramos cuando llegamos a secciones
        if line in {"# POEMA", "# POEMA_CITADO", "# TEXTO"}:
            break
    return out

def read_current_parts(txt_path: Path) -> Dict[str, str]:
    if not txt_path.exists():
        return {"poema": "", "poema_citado": "", "texto": ""}
    raw = txt_path.read_text(encoding="utf-8")
    return {
        "poema": extract_section(raw, "# POEMA"),
        "poema_citado": extract_section(raw, "# POEMA_CITADO"),
        "texto": extract_section(raw, "# TEXTO"),
    }


def normalize_pulled_payload_local(pulled: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mapea payloads de gdocs_pull_* a keys internas:
      poem -> poema
      analysis -> texto
      poem_citado -> poema_citado
      title -> MY_POEM_TITLE
      poet -> POETA
      poem_title -> POEM_TITLE
      book_title -> BOOK_TITLE
    Mantiene otras keys si ya vienen normalizadas.
    """
    out = dict(pulled or {})

    # poem pull
    if "poem" in out and "poema" not in out:
        out["poema"] = out.get("poem", "")
    if "title" in out and "MY_POEM_TITLE" not in out:
        out["MY_POEM_TITLE"] = out.get("title", "")

    # analysis pull
    if "analysis" in out and "texto" not in out:
        out["texto"] = out.get("analysis", "")
    # ya viene como poem_citado en tu script
    if "poem_citado" in out and "poema_citado" not in out:
        out["poema_citado"] = out.get("poem_citado", "")

    # metadata
    if "poet" in out and "POETA" not in out:
        out["POETA"] = out.get("poet", "")
    if "poem_title" in out and "POEM_TITLE" not in out:
        out["POEM_TITLE"] = out.get("poem_title", "")
    if "book_title" in out and "BOOK_TITLE" not in out:
        out["BOOK_TITLE"] = out.get("book_title", "")

    # clean strings
    for k, v in list(out.items()):
        if isinstance(v, str):
            out[k] = v.replace("\r\n", "\n").replace("\r", "\n")

    return out


def render_txt(date_str: str, payload: Dict[str, Any]) -> str:
    # EXACT format expected by your pipeline
    lines: List[str] = []
    lines.append(f"FECHA: {date_str}")

    # MY_POEM_TITLE can be blank; keep line for consistency if present
    my_title = (payload.get("MY_POEM_TITLE") or "").strip()
    if my_title:
        lines.append(f"MY_POEM_TITLE: {my_title}")

    poeta = (payload.get("POETA") or "").strip()
    if poeta:
        lines.append(f"POETA: {poeta}")
    poem_title = (payload.get("POEM_TITLE") or "").strip()
    if poem_title:
        lines.append(f"POEM_TITLE: {poem_title}")
    book_title = (payload.get("BOOK_TITLE") or "").strip()
    if book_title:
        lines.append(f"BOOK_TITLE: {book_title}")

    lines.append("")  # blank line

    lines.append("# POEMA")
    lines.append((payload.get("poema") or "").rstrip())
    lines.append("")

    lines.append("# POEMA_CITADO")
    # poem_citado can be empty; that's OK
    lines.append((payload.get("poema_citado") or "").rstrip())
    lines.append("")

    lines.append("# TEXTO")
    lines.append((payload.get("texto") or "").rstrip())
    lines.append("")

    # normalize trailing spaces
    return "\n".join(lines).replace("\r\n", "\n").replace("\r", "\n")


def preview_payload(date_str: str, payload: Dict[str, Any]) -> None:
    println(SEP)
    println("[qcambiar] PREVIEW — METADATA")
    for k in ["MY_POEM_TITLE", "POETA", "POEM_TITLE", "BOOK_TITLE"]:
        v = (payload.get(k) or "").strip()
        if v:
            println(f"{k}: {v}")
    println("")
    println("[qcambiar] PREVIEW — POEMA")
    println((payload.get("poema") or "").strip())
    println("")
    println("[qcambiar] PREVIEW — POEMA_CITADO")
    println((payload.get("poema_citado") or "").strip())
    println("")
    println("[qcambiar] PREVIEW — TEXTO")
    println((payload.get("texto") or "").strip())
    println(SEP)


def compute_diff_flags(
    date_str: str,
    current_parts: Dict[str, str],
    current_meta: Dict[str, str],
    pulled: Dict[str, Any],
) -> Tuple[bool, bool, List[str]]:

    """
    Returns (P_changed, A_changed, report_lines).
    P_changed: POEMA or MY_POEM_TITLE differs
    A_changed: any of (TEXTO, POEMA_CITADO, POETA, POEM_TITLE, BOOK_TITLE) differs
    report_lines: UX list of section diffs.
    """
    report: List[str] = []

    # sections
    cur_poema = current_parts.get("poema", "")
    cur_citado = current_parts.get("poema_citado", "")
    cur_texto = current_parts.get("texto", "")

    new_poema = pulled.get("poema", "")
    new_citado = pulled.get("poema_citado", "")
    new_texto = pulled.get("texto", "")

    poem_changed = normalize_text_for_hash(cur_poema) != normalize_text_for_hash(new_poema)
    citado_changed = normalize_text_for_hash(cur_citado) != normalize_text_for_hash(new_citado)
    texto_changed = normalize_text_for_hash(cur_texto) != normalize_text_for_hash(new_texto)

    report.append(f"  - POEMA: {'CAMBIÓ' if poem_changed else 'sin cambios'}")
    report.append(f"  - POEMA_CITADO: {'CAMBIÓ' if citado_changed else 'sin cambios'}")
    report.append(f"  - TEXTO: {'CAMBIÓ' if texto_changed else 'sin cambios'}")

    # metadata comparisons: compare against archivo.json entry (published truth)
    def meta_diff(key: str) -> bool:
        cur = str(current_meta.get(key, "") or "")
        new = str(pulled.get(key, "") or "")
        return normalize_text_for_hash(cur) != normalize_text_for_hash(new)

    my_title_changed = meta_diff("MY_POEM_TITLE")
    poeta_changed = meta_diff("POETA")
    poem_title_changed = meta_diff("POEM_TITLE")
    book_title_changed = meta_diff("BOOK_TITLE")

    report.append(f"  - MY_POEM_TITLE: {'CAMBIÓ' if my_title_changed else 'sin cambios'}")
    report.append(f"  - POETA: {'CAMBIÓ' if poeta_changed else 'sin cambios'}")
    report.append(f"  - POEM_TITLE: {'CAMBIÓ' if poem_title_changed else 'sin cambios'}")
    report.append(f"  - BOOK_TITLE: {'CAMBIÓ' if book_title_changed else 'sin cambios'}")

    P = poem_changed or my_title_changed
    A = citado_changed or texto_changed or poeta_changed or poem_title_changed or book_title_changed
    return P, A, report


def build_commit_message(date_str: str, P: bool, A: bool, K: bool) -> str:
    # All combinations, with spaces
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


def main() -> int:
    try:
        run_preflight()

        if len(sys.argv) != 2:
            eprintln("Uso: qcambiar YYYY-MM-DD")
            return 1

        date_str = sys.argv[1]
        # validates format
        parse_yyyy_mm_dd(date_str)

        archivo = load_archivo_json()
        entry = find_entry_by_date(archivo, date_str)
        if not entry:
            eprintln(f"[qcambiar] No existe entrada publicada para {date_str}. Usa qcrear.")
            return 1

        println(SEP)
        println("[qcambiar] OK: entrada publicada encontrada para " + date_str + ".")
        println("")
        println("[qcambiar] Haciendo pull desde Google Docs para comparar…")

        poem_pull = run_py_json("scripts/gdocs_pull_poem_by_date.py", ["--date", date_str])
        analysis_pull = run_py_json("scripts/gdocs_pull_analysis_by_date.py", ["--date", date_str])

        pulled_raw: Dict[str, Any] = {}
        pulled_raw.update(poem_pull or {})
        pulled_raw.update(analysis_pull or {})
        pulled = normalize_pulled_payload_local(pulled_raw)

        txt_path = txt_path_for_date_local(date_str)
        current_parts = read_current_parts(txt_path)
        current_txt = txt_path.read_text(encoding="utf-8") if txt_path.exists() else ""
        current_meta = parse_metadata_from_txt(current_txt)

        P_changed, A_changed, report_lines = compute_diff_flags(date_str, current_parts, current_meta, pulled)
        P_for_msg = P_changed
        A_for_msg = A_changed


        # If no GDocs changes, allow publish if local txt differs (previous commit failed)
        if not P_changed and not A_changed:
            if git_file_has_diff(txt_path):
                println("")
                println("[qcambiar] Google Docs coincide, pero hay cambios locales pendientes en el .txt.")
                if not prompt_yn("[qcambiar] ¿Quieres publicar (commit + push) estos cambios locales?", default_yes=False):
                    println("[qcambiar] OK. No se publicó nada.")
                    return 0
                # no re-render; go to publish pipeline
                txt_changed = True
                K_changed = False
                P_for_msg = False
                A_for_msg = False
            else:
                println("")
                println("[qcambiar] Google Docs coincide con publicado y no hay cambios locales pendientes.")
                txt_changed = False   # importante: inicializar para el resumen/commit gate
                # NO return: seguimos a keywords

        else:
            println("")
            println("[qcambiar] ⚠️ Cambios detectados (Google Docs ≠ publicado):")
            for ln in report_lines:
                println(ln)

            if not prompt_yn("[qcambiar] ¿Aplicar estas actualizaciones?", default_yes=False):
                println("[qcambiar] OK. No se aplicaron cambios.")
                return 0

            # Build final payload: start from current (published file), then overlay pulled fully
            # (Because you chose "apply updates", we apply everything that differs.)
            final_payload: Dict[str, Any] = {}
            # metadata: take pulled values (they represent GDocs truth)
            for k in ["MY_POEM_TITLE", "POETA", "POEM_TITLE", "BOOK_TITLE"]:
                if k in pulled:
                    final_payload[k] = pulled.get(k, "")
                else:
                    final_payload[k] = entry.get(k, "")

            # sections: use pulled
            final_payload["poema"] = pulled.get("poema", current_parts.get("poema", ""))
            final_payload["poema_citado"] = pulled.get("poema_citado", current_parts.get("poema_citado", ""))
            final_payload["texto"] = pulled.get("texto", current_parts.get("texto", ""))

            if prompt_yn("[qcambiar] ¿Ver preview del contenido final?", default_yes=True):
                preview_payload(date_str, final_payload)

            if not prompt_yn("[qcambiar] ¿Confirmas que el contenido se ve correcto?", default_yes=False):
                println("[qcambiar] OK. Cancelado.")
                return 0

            # Write txt
            txt_content = render_txt(date_str, final_payload)
            write_text_atomic(txt_path, txt_content)
            println(f"[qcambiar] ✅ Escribí build output: {txt_path}")

            # After write: real change detection via git diff
            txt_changed = git_file_has_diff(txt_path)

            # Compute P/A for commit message based on what differed vs published
            P_for_msg = P_changed
            A_for_msg = A_changed
            K_changed = False

        # Keywords flow (solo preguntar si el .txt cambió)
        # -----------------------------
        # Keywords flow (siempre visible)
        # -----------------------------
        from shutil import copyfile

        repo = Path(__file__).resolve().parent.parent
        cur_kw = repo / "state" / "current_keywords.txt"
        pend_kw = repo / "state" / "pending_keywords.txt"
        gen_path = repo / "qmp" / "gen_keywords.py"

        def show_keywords(label: str) -> None:
            if cur_kw.exists() and cur_kw.read_text(encoding="utf-8").strip():
                println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                println(f"[qcambiar] KEYWORDS ({label})")
                println(cur_kw.read_text(encoding="utf-8").strip())
                println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            else:
                println("[qcambiar] (No hay state/current_keywords.txt con contenido.)")

        # 1) Opción de ver keywords actuales (siempre)
        println("")
        if prompt_yn("[qcambiar] ¿Ver keywords actuales?", default_yes=False):
            show_keywords("current_keywords.txt")

        # 2) Preguntar si quieres cambiarlas (aunque no haya cambios de texto)
        K_changed = False
        if prompt_yn("[qcambiar] ¿Quieres actualizar keywords?", default_yes=False):
            if not gen_path.exists():
                raise RuntimeError("No encuentro qmp/gen_keywords.py en el repo.")

            # Ejecutar gen_keywords con firmas comunes (sin asumir demasiado)
            tried = []
            ok = False
            last = None
            for argv in (
                [sys.executable, str(gen_path), date_str],
                [sys.executable, str(gen_path), "--date", date_str],
                [sys.executable, str(gen_path), date_str, str(txt_path)],
                [sys.executable, str(gen_path), "--date", date_str, "--txt", str(txt_path)],
                [sys.executable, str(gen_path), str(txt_path)],
            ):
                tried.append(" ".join(argv))
                last = subprocess.run(argv, capture_output=True, text=True)
                if last.returncode == 0:
                    ok = True
                    break

            if not ok:
                raise RuntimeError(
                    "No pude ejecutar qmp/gen_keywords.py con ninguna firma conocida.\n\n"
                    + "\n".join(tried)
                    + "\n\nSTDERR:\n"
                    + ((last.stderr or "").strip() if last else "")
                    + "\n\nSTDOUT:\n"
                    + ((last.stdout or "").strip() if last else "")
                )

            # Promover current -> pending
            if not cur_kw.exists() or cur_kw.read_text(encoding="utf-8").strip() == "":
                raise RuntimeError(
                    "qmp/gen_keywords.py terminó sin error, pero state/current_keywords.txt está vacío o no existe."
                )

            copyfile(cur_kw, pend_kw)
            K_changed = True
            println("[qcambiar] ✅ Keywords actualizadas (current_keywords.txt → pending_keywords.txt).")

            # 3) Si las cambiaste, opción de verlas otra vez
            if prompt_yn("[qcambiar] ¿Ver keywords nuevas?", default_yes=False):
                show_keywords("current_keywords.txt (post-update)")

        # Decide commit message
        commit_msg = build_commit_message(date_str, P_for_msg, A_for_msg, K_changed)

        println("")
        println("[qcambiar] Resumen (resultado):")
        println(f"  - cambios detectados en texto:    {txt_changed}")
        println(f"  - cambios detectados en keywords: {K_changed}")

        if not txt_changed and not K_changed:
            println("ℹ️  No hay nada que publicar.")
            return 0

        println("")
        if not prompt_yn("[qcambiar] ¿Hacer commit + push ahora?", default_yes=False):
            println("[qcambiar] OK. No se publicó nada.")
            return 0

        # Guardrail: branch warning if not main
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

        # Run merge_pending to update archivo.json etc.
        # NOTE: this relies on your repo's merge_pending.py interface.
        # dry-run first is optional; we go straight to apply.
        mp_args = [
            "--archivo", str((Path(__file__).resolve().parent.parent / "data" / "archivo.json")),
            "--pending-kw", str((Path(__file__).resolve().parent.parent / "state" / "pending_keywords.txt")),
            "--pending-entry", str((Path(__file__).resolve().parent.parent / "state" / "pending_entry.json")),
        ]
        if K_changed:
            mp_args.append("--apply-keywords")
        mp_args.append(str(txt_path))

        _status = run_py_json("qmp/merge_pending.py", mp_args)

        # Stage + commit + push
        git(["add", str(txt_path)])
        git(["add", "data/archivo.json"])
        # stage state files too (merge_pending writes pending_entry.json)
        git(["add", "state/pending_entry.json"])
        git(["add", "state/pending_keywords.txt"])

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
