#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional


# Asegura que `scripts/` esté en sys.path para poder importar qcommon.py
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from qcommon import (
    SEP,
    UserAbort,
    apply_pending_entry_into_archivo,
    archivo_json_path,
    data_dir,
    docs_fingerprint,
    eprintln,
    find_entry_by_date,
    git,
    load_archivo_json,
    open_in_editor,
    parse_yyyy_mm_dd,
    println,
    prompt_choice,
    prompt_yn,
    repo_root,
    run_preflight,
    run_py_json,
    state_dir,
    txt_fingerprint_from_file,
    write_text_atomic,
)



# -----------------------------
# Repo-specific helpers (thin)
# -----------------------------

def txt_path_for_date(date_str: str) -> Path:
    # usa el mismo layout que qcrear (YYYY/MM/YYYY-MM-DD.txt)
    y, m, _ = date_str.split("-")
    return data_dir() / "textos" / y / m / f"{date_str}.txt"


def render_txt(date_str: str, pulled: dict) -> str:
    """
    Debe coincidir con el formato de qcrear.py, porque validate_entry.py lo exige.
    """
    poema = (pulled.get("poema") or "").rstrip()
    citado = (pulled.get("poema_citado") or "").rstrip()
    texto = (pulled.get("texto") or "").rstrip()

    my_poem_title = (pulled.get("MY_POEM_TITLE") or "").strip()
    poeta = (pulled.get("POETA") or "").strip()
    poem_title = (pulled.get("POEM_TITLE") or "").strip()
    book_title = (pulled.get("BOOK_TITLE") or "").strip()

    def norm(s: str) -> str:
        # sin importar qcommon aquí: equivalente a qcrear (trim líneas, etc.)
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        lines = [ln.rstrip() for ln in s.split("\n")]
        while lines and lines[0].strip() == "":
            lines.pop(0)
        while lines and lines[-1].strip() == "":
            lines.pop()
        return "\n".join(lines)

    parts = []
    parts.append(f"FECHA: {date_str}")
    parts.append(f"MY_POEM_TITLE: {my_poem_title}".rstrip())
    parts.append(f"POETA: {poeta}".rstrip())
    parts.append(f"POEM_TITLE: {poem_title}".rstrip())
    parts.append(f"BOOK_TITLE: {book_title}".rstrip())
    parts.append("")

    parts.append("# POEMA")
    parts.append(norm(poema))
    parts.append("")

    parts.append("# POEMA_CITADO")
    parts.append(norm(citado))
    parts.append("")

    parts.append("# TEXTO")
    parts.append(norm(texto))
    parts.append("")

    return "\n".join(parts)


def preview_sections(pulled: dict, n_lines: int = 18) -> None:
    def head(s: str) -> str:
        lines = s.splitlines()
        return "\n".join(lines[:n_lines])

    # ---- NEW: metadata preview
    meta_pairs = []
    for k in ["MY_POEM_TITLE", "POEM_TITLE", "POET", "BOOK_TITLE"]:
        v = (pulled.get(k) or "").strip()
        if v:
            meta_pairs.append((k, v))

    println(SEP)
    if meta_pairs:
        println("[qcambiar] PREVIEW — METADATA")
        for k, v in meta_pairs:
            println(f"{k}: {v}")
        println("")

    println("[qcambiar] PREVIEW — POEMA")
    println(head(pulled.get("poema", "")))
    println("")
    println("[qcambiar] PREVIEW — POEMA_CITADO")
    println(head(pulled.get("poema_citado", "")))
    println("")
    println("[qcambiar] PREVIEW — TEXTO")
    println(head(pulled.get("texto", "")))
    println(SEP)


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
    if obj.get("date", "") == "" and obj.get("keywords", []) == []:
        return None
    return obj


def clear_pending_keywords_placeholder() -> None:
    p = state_dir() / "pending_keywords.txt"
    p.write_text(json.dumps({"date": "", "docs_fingerprint": "", "keywords": []}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_keywords_payload(obj: object) -> list[dict]:
    """
    Acepta:
    - lista de {"keyword": str, "weight": int}
    - dict {"keywords": [...]}
    Devuelve lista validada.
    """
    if isinstance(obj, dict) and "keywords" in obj:
        obj = obj["keywords"]
    if not isinstance(obj, list):
        raise RuntimeError("keywords inválidas: se esperaba lista o {'keywords': [...]}")
    out: list[dict] = []
    for it in obj:
        if not isinstance(it, dict):
            continue
        kw = (it.get("word") or it.get("keyword") or it.get("kw") or "").strip()
        w = it.get("weight")
        if not kw:
            continue
        try:
            w_int = int(w)
        except Exception:
            continue
        out.append({"word": kw, "weight": w_int})
    if not out:
        raise RuntimeError("keywords inválidas: lista vacía tras validar.")
    return out


def show_keywords_top(kw_list: list[dict], top: int = 10) -> None:
    sorted_kw = sorted(kw_list, key=lambda x: (-int(x.get("weight", 0)), x.get("keyword", "")))
    println("[qcambiar] Keywords (top):")
    for it in sorted_kw[:top]:
        println(f"  - {it['keyword']} ({it['weight']})")
    println(f"[qcambiar] Total keywords: {len(sorted_kw)}")


def generate_keywords_from_txt(txt_path: Path) -> list[dict]:
    # usa gen_keywords.py (ajusta el path si en tu repo vive en otro lugar)
    # en qcrear ya tienes lógica tolerante; replicamos aquí
    res = run_py_json("qmp/gen_keywords.py", [str(txt_path)])
    return normalize_keywords_payload(res)


def write_pending_keywords(date_str: str, fp: str, kw_list: list[dict]) -> None:
    p = state_dir() / "pending_keywords.txt"
    payload = {"date": date_str, "docs_fingerprint": fp, "keywords": kw_list}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_validate_and_normalize_txt(date_str: str, txt_path: Path) -> None:
    # normaliza (idempotente) antes de merge/publicar
    _ = run_py_json("qmp/validate_entry.py", ["--mode", "normalize", date_str, str(txt_path)])


def run_merge_pending(
    txt_path: Path,
    archivo_path: Path,
    pending_kw_path: Path,
    pending_entry_path: Path,
    apply_keywords: bool,
    dry_run: bool,
) -> dict:
    # merge_pending.py usage:
    #   merge_pending.py --archivo ARCHIVO --pending-kw PENDING_KW --pending-entry PENDING_ENTRY [--apply-keywords] [--dry-run] txt_path
    args = [
        "--archivo", str(archivo_path),
        "--pending-kw", str(pending_kw_path),
        "--pending-entry", str(pending_entry_path),
    ]
    if apply_keywords:
        args.append("--apply-keywords")
    if dry_run:
        args.append("--dry-run")

    # txt_path es posicional
    args.append(str(txt_path))

    return run_py_json("qmp/merge_pending.py", args)


def normalize_pulled_payload(pulled: dict) -> dict:
    """
    Normaliza keys devueltas por gdocs_pull_* al contrato interno:
      - poema
      - poema_citado
      - texto
    y algunos metadatos opcionales.
    """
    out = dict(pulled)

    # Texto principal
    if "poema" not in out and "poem" in out:
        out["poema"] = out.get("poem", "")
    if "texto" not in out and "analysis" in out:
        out["texto"] = out.get("analysis", "")

    # Poema citado
    # (ya viene como 'poem_citado' en tu analysis pull)
    if "poema_citado" not in out and "poem_citado" in out:
        out["poema_citado"] = out.get("poem_citado", "")

    # Metadatos (opcional; tu render_txt los usa si existen)
    # Título de MI poema: si viene 'title' del poem pull
    if "MY_POEM_TITLE" not in out and "title" in out:
        out["MY_POEM_TITLE"] = out.get("title", "")

    # Metas de análisis
    if "POEM_TITLE" not in out and "poem_title" in out:
        out["POEM_TITLE"] = out.get("poem_title", "")
    if "POETA" not in out and "poet" in out:
        out["POETA"] = out.get("poet", "")
    if "BOOK_TITLE" not in out and "book_title" in out:
        out["BOOK_TITLE"] = out.get("book_title", "")

    return out


def main(argv: list[str]) -> int:
    try:
        println(SEP)

        pf = run_preflight()
        if not pf.ok_repo or not pf.ok_archivo_json:
            raise RuntimeError("Preflight falló: no encuentro repo o data/archivo.json")

        if len(argv) < 2:
            println("Uso: qcambiar YYYY-MM-DD.")
            return 1

        target = argv[1].strip()
        _ = parse_yyyy_mm_dd(target)  # valida formato

        archivo = load_archivo_json()
        entry = find_entry_by_date(archivo, target)
        if not entry:
            println(f"[qcambiar] No existe una entrada publicada para {target}. Usa 'qcrear {target}'.")
            return 0

        println(f"[qcambiar] OK: entrada publicada encontrada para {target}.")

        # 3) Menú
        println("")
        change_poem = prompt_yn("[qcambiar] ¿Quieres cambiar el POEMA?", default_yes=False, prefix="[qcambiar] ")
        change_text = prompt_yn("[qcambiar] ¿Quieres cambiar el ANÁLISIS/TEXTO?", default_yes=False, prefix="[qcambiar] ")
        change_kw = prompt_yn("[qcambiar] ¿Quieres cambiar las KEYWORDS?", default_yes=False, prefix="[qcambiar] ")

        if not (change_poem or change_text or change_kw):
            println("[qcambiar] No hay cambios seleccionados. Saliendo.")
            return 0

        # Si se tocó texto, forzamos pasar por keywords (aunque luego sea 'n')
        touched_text = change_poem or change_text

        # 4) Pull desde Google Docs (solo lo seleccionado)
        pulled: dict = {}
        if change_poem:
            poem_obj = run_py_json(
                "scripts/gdocs_pull_poem_by_date.py",
                ["--date", target],
            )
            println(f"[qcambiar] poem pull keys: {sorted(poem_obj.keys())}")


            # esperamos keys: poema, poema_citado, MY_POEM_TITLE...
            pulled.update(poem_obj)

        if change_text:
            text_obj = run_py_json(
                "scripts/gdocs_pull_analysis_by_date.py",
                ["--date", target],
            )
            println(f"[qcambiar] analysis pull keys: {sorted(text_obj.keys())}")


            pulled.update(text_obj)
        pulled = normalize_pulled_payload(pulled)

        # Validaciones mínimas si tocamos texto
        # Validaciones mínimas si tocamos texto
        fp: Optional[str] = None
        if touched_text:
            poema = (pulled.get("poema") or "").strip()
            citado = (pulled.get("poema_citado") or "").strip()
            texto = (pulled.get("texto") or "").strip()

            missing = []
            if not poema:
                missing.append("poema (key 'poema')")
            if not citado:
                missing.append("poema_citado (key 'poema_citado')")
            if not texto:
                missing.append("texto (key 'texto')")

            if missing:
                # Diagnóstico adicional: qué keys devolvió pulled
                keys = sorted(list(pulled.keys()))
                msg = (
                    "Pull incompleto.\n"
                    f"Faltan secciones: {', '.join(missing)}\n"
                    f"Keys recibidas: {keys}\n"
                    "Tip: revisa si gdocs_pull_* devolvió nombres distintos (p.ej. 'POEMA' vs 'poema')."
                )
                raise RuntimeError(msg)

            fp = docs_fingerprint(poema, citado, texto)
            println(f"[qcambiar] docs_fingerprint: {fp}")

            println("")
            if prompt_yn("[qcambiar] ¿Ver preview de los 3 escritos?", default_yes=False, prefix="[qcambiar] "):
                preview_sections(pulled)

            println("")
            ok = prompt_yn("[qcambiar] ¿Confirmas que el contenido se ve correcto?", default_yes=False, prefix="[qcambiar] ")
            if not ok:
                println("[qcambiar] OK. Cancelado. No se escribió nada.")
                return 0

            # 7) regenerar txt
            txt_path = txt_path_for_date(target)
            txt_content = render_txt(target, pulled)
            write_text_atomic(txt_path, txt_content)
            println(f"[qcambiar] ✅ Escribí build output: {txt_path}")

        else:
            txt_path = txt_path_for_date(target)
            if not txt_path.exists():
                raise RuntimeError(f"No existe el .txt local para {target}: {txt_path}. (¿Necesitas qcrear?)")

        # 8) Keywords
        did_change_keywords = False
        if touched_text:
            println("")
            println("[qcambiar] Keywords: como cambiaste texto, vamos a revisar keywords ahora.")
            if prompt_yn("[qcambiar] ¿Ver keywords actuales en terminal?", default_yes=False, prefix="[qcambiar] "):
                cur_kw = entry.get("keywords") or []
                try:
                    cur_kw_norm = normalize_keywords_payload({"keywords": cur_kw} if isinstance(cur_kw, list) else cur_kw)
                    show_keywords_top(cur_kw_norm)
                except Exception:
                    println("[qcambiar] (No pude parsear keywords actuales del archivo.json con el schema esperado.)")

            mode = prompt_choice("[qcambiar] ¿Cómo quieres cambiar keywords? (r=regenerar / e=editar / n=no cambiar)", ["r", "e", "n"], default="n")

            if mode == "n":
                println("[qcambiar] Elegiste no cambiar keywords.")
                # guardrail: texto cambió pero keywords no
                println("[qcambiar] ⚠️  Cambiaste el texto pero dejaste keywords iguales.")
                cont = prompt_yn("[qcambiar] ¿Continuar de todos modos?", default_yes=False, prefix="[qcambiar] ")
                if not cont:
                    println("[qcambiar] OK. Cancelado.")
                    return 0

            elif mode == "r":
                println("[qcambiar] Generando keywords...")
                kw_list = generate_keywords_from_txt(txt_path)
                show_keywords_top(kw_list)
                if prompt_yn("[qcambiar] ¿Guardar estas keywords?", default_yes=False, prefix="[qcambiar] "):
                    assert fp is not None
                    write_pending_keywords(target, fp, kw_list)
                    did_change_keywords = True
                    println("[qcambiar] ✅ pending_keywords.txt actualizado.")
                else:
                    println("[qcambiar] OK. No guardé keywords.")
                    cont = prompt_yn("[qcambiar] No se puede publicar sin guardar keywords nuevas. ¿Cancelar?", default_yes=True, prefix="[qcambiar] ")
                    if cont:
                        return 0

            else:  # mode == "e"
                # Editar keywords actuales (si no hay, arrancar vacío)
                cur_kw_raw = entry.get("keywords") or []
                try:
                    cur_kw_list = normalize_keywords_payload({"keywords": cur_kw_raw})
                except Exception:
                    cur_kw_list = []

                edit_path = state_dir() / "kw_edit.json"
                edit_payload = {"keywords": cur_kw_list}
                edit_path.write_text(json.dumps(edit_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

                open_in_editor(edit_path, prefix="[qcambiar] ")

                edited_obj = json.loads(edit_path.read_text(encoding="utf-8"))
                kw_list = normalize_keywords_payload(edited_obj)
                show_keywords_top(kw_list)
                if prompt_yn("[qcambiar] ¿Aplicar estas keywords editadas?", default_yes=False, prefix="[qcambiar] "):
                    assert fp is not None
                    write_pending_keywords(target, fp, kw_list)
                    did_change_keywords = True
                    println("[qcambiar] ✅ pending_keywords.txt actualizado.")
                else:
                    println("[qcambiar] OK. No apliqué keywords editadas.")
                    cont = prompt_yn("[qcambiar] Como cambiaste texto, esto puede dejar incoherencia. ¿Cancelar?", default_yes=True, prefix="[qcambiar] ")
                    if cont:
                        return 0

        elif change_kw:
            # solo keywords, sin texto
            println("")
            if prompt_yn("[qcambiar] ¿Ver keywords actuales en terminal?", default_yes=False, prefix="[qcambiar] "):
                cur_kw_raw = entry.get("keywords") or []
                try:
                    cur_kw_list = normalize_keywords_payload({"keywords": cur_kw_raw})
                    show_keywords_top(cur_kw_list)
                except Exception:
                    println("[qcambiar] (No pude parsear keywords actuales del archivo.json con el schema esperado.)")

            mode = prompt_choice("[qcambiar] ¿Cómo quieres cambiar keywords? (r=regenerar / e=editar / n=cancelar)", ["r", "e", "n"], default="n")
            if mode == "n":
                println("[qcambiar] OK. Cancelado.")
                return 0

            if mode == "r":
                println("[qcambiar] Generando keywords desde el .txt local...")
                kw_list = generate_keywords_from_txt(txt_path)
                show_keywords_top(kw_list)
                if prompt_yn("[qcambiar] ¿Guardar estas keywords?", default_yes=False, prefix="[qcambiar] "):
                    # sin texto tocado, fingerprint del txt local si se puede
                    fp2 = txt_fingerprint_from_file(txt_path) or ""
                    write_pending_keywords(target, fp2, kw_list)
                    did_change_keywords = True
                    println("[qcambiar] ✅ pending_keywords.txt actualizado.")
                else:
                    println("[qcambiar] OK. No guardé keywords.")
                    return 0
            else:
                cur_kw_raw = entry.get("keywords") or []
                try:
                    cur_kw_list = normalize_keywords_payload({"keywords": cur_kw_raw})
                except Exception:
                    cur_kw_list = []
                edit_path = state_dir() / "kw_edit.json"
                edit_path.write_text(json.dumps({"keywords": cur_kw_list}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                open_in_editor(edit_path, prefix="[qcambiar] ")
                edited_obj = json.loads(edit_path.read_text(encoding="utf-8"))
                kw_list = normalize_keywords_payload(edited_obj)
                show_keywords_top(kw_list)
                if prompt_yn("[qcambiar] ¿Aplicar estas keywords editadas?", default_yes=False, prefix="[qcambiar] "):
                    fp2 = txt_fingerprint_from_file(txt_path) or ""
                    write_pending_keywords(target, fp2, kw_list)
                    did_change_keywords = True
                    println("[qcambiar] ✅ pending_keywords.txt actualizado.")
                else:
                    println("[qcambiar] OK. No apliqué keywords.")
                    return 0

        # 9) Estado
        println("")
        println("[qcambiar] Resumen:")
        println(f"  - poema cambiado:     {change_poem}")
        println(f"  - texto cambiado:     {change_text}")
        println(f"  - keywords cambiadas: {did_change_keywords}")

        # 10) Publish gate
        println("")
        if not prompt_yn("[qcambiar] ¿Hacer commit + push ahora?", default_yes=False, prefix="[qcambiar] "):
            println("[qcambiar] OK. No publiqué. Puedes volver a ejecutar qcambiar cuando quieras.")
            return 0

        branch = git(["rev-parse", "--abbrev-ref", "HEAD"]).strip()
        if branch != "main":
            println("")
            println(f"[qcambiar] ⚠️  Estás en el branch '{branch}', no en 'main'.")
            println("[qcambiar] Esto publicará los cambios en ESTE branch.")
            if not prompt_yn(f"[qcambiar] ¿Publicar de todos modos en '{branch}'?", default_yes=False, prefix="[qcambiar] "):
                println("[qcambiar] OK. Publicación cancelada.")
                return 0

        archivo_path = archivo_json_path()
        pending_kw_path = state_dir() / "pending_keywords.txt"
        pending_entry_path = state_dir() / "pending_entry.json"

        # Validación + normalización del txt
        run_validate_and_normalize_txt(target, txt_path)

        # merge_pending (aplica keywords si hay pending guardado y corresponde)
        pending = load_pending_keywords()
        apply_kw = bool(pending and (pending.get("date") == target) and (pending.get("keywords") or []))

        status = run_merge_pending(
            txt_path=txt_path,
            archivo_path=archivo_path,
            pending_kw_path=pending_kw_path,
            pending_entry_path=pending_entry_path,
            apply_keywords=apply_kw,
            dry_run=False,
        )

        exists_before = bool(status.get("exists_before", True))
        content_changed = bool(status.get("content_changed", True))
        keywords_changed = bool(status.get("keywords_changed", apply_kw))

        if exists_before and (not content_changed) and (not keywords_changed):
            println("ℹ️  No cambió texto ni keywords → no hay commit.")
            return 0

        # Commit msg (contrato)
        msg = f"{'keywords' if (not content_changed and keywords_changed) else 'edicion'} {target}"

        println("")
        println(f"[qcambiar] Fecha:  {target}")
        println(f"[qcambiar] Commit: {msg}")
        if not prompt_yn("[qcambiar] ¿Confirmar publish (commit + push)?", default_yes=False, prefix="[qcambiar] "):
            println("[qcambiar] OK. Cancelado. No se publicó nada.")
            return 0

        apply_pending_entry_into_archivo(target, pending_entry_path, archivo_path)

        git(["add", str(archivo_path), str(txt_path), str(pending_entry_path)])
        git(["commit", "-m", msg])
        git(["push"])

        println(f"✅ Publicado: {msg}")

        # Cleanup
        clear_pending_keywords_placeholder()
        pending_entry_path.write_text("{}", encoding="utf-8")

        return 0

    except UserAbort:
        println("[qcambiar] OK. Salí sin cambios.")
        return 0
    except Exception as e:
        eprintln(f"[qcambiar] ERROR: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
