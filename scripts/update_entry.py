#!/usr/bin/env python3
"""
update_entry.py — Re-pull y actualiza una entrada ya publicada desde Google Docs.

Uso:
    python scripts/update_entry.py --date YYYY-MM-DD [--regen-keywords] [--dry-run]

Flags:
    --regen-keywords  Regenera keywords con OpenAI (por defecto: conserva las existentes)
    --dry-run         Ejecuta todo pero NO hace commit ni push
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ──────────────────────────────────────────
# Paths
# ──────────────────────────────────────────

def data_dir() -> Path:
    return REPO_ROOT / "data"

def state_dir() -> Path:
    return REPO_ROOT / "state"

def txt_path_for_date(date: str) -> Path:
    y, m, _ = date.split("-")
    return data_dir() / "textos" / y / m / f"{date}.txt"

def archivo_json_path() -> Path:
    return data_dir() / "archivo.json"

def _find_script(*relpaths: str) -> Path:
    for rp in relpaths:
        p = REPO_ROOT / rp
        if p.exists():
            return p
    raise RuntimeError(f"No encontré el script. Probé: {', '.join(relpaths)}")


# ──────────────────────────────────────────
# Subprocess helpers
# ──────────────────────────────────────────

def run_py_json(script_relpath: str, args: list[str]) -> dict:
    """Ejecuta un script Python del repo y parsea su stdout como JSON."""
    script = REPO_ROOT / script_relpath
    cmd = [sys.executable, str(script), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{script_relpath} falló (exit {proc.returncode}):\n"
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{script_relpath} no devolvió JSON válido: {e}\nStdout: {proc.stdout[:400]}")

def git(cmd: list[str]) -> str:
    proc = subprocess.run(["git", *cmd], capture_output=True, text=True, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(cmd)} falló:\n{(proc.stderr or proc.stdout or '').strip()}"
        )
    return proc.stdout.strip()


# ──────────────────────────────────────────
# Text helpers — idénticos a qcrear.py para
# que los fingerprints sean compatibles
# ──────────────────────────────────────────

def normalize_text_for_hash(s: str) -> str:
    if s is None:
        s = ""
    s = s.replace("\u00a0", " ")
    for ch in ("\u200b", "\ufeff", "\u2060"):
        s = s.replace(ch, "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in s.split("\n")]
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
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

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
    """Genera el contenido del archivo YYYY-MM-DD.txt."""
    parts = [
        f"FECHA: {target}",
        f"MY_POEM_TITLE: {my_poem_title}".rstrip(),
        f"POETA: {poeta}".rstrip(),
        f"POEM_TITLE: {poem_title}".rstrip(),
        f"BOOK_TITLE: {book_title}".rstrip(),
        "",
        "# POEMA",
        normalize_text_for_hash(poema),
        "",
        "# POEMA_CITADO",
        normalize_text_for_hash(poema_citado),
        "",
        "# TEXTO",
        normalize_text_for_hash(texto),
        "",
    ]
    return "\n".join(parts)

def write_txt_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# ──────────────────────────────────────────
# Keywords
# ──────────────────────────────────────────

def load_existing_keywords(date: str) -> list[dict]:
    """Carga las keywords actuales de archivo.json para la fecha dada."""
    data = json.loads(archivo_json_path().read_text(encoding="utf-8"))
    entries = data.get("entries", data) if isinstance(data, dict) else data
    entry = next((e for e in entries if isinstance(e, dict) and e.get("date") == date), None)
    if entry is None:
        return []
    return entry.get("keywords", [])

def generate_keywords(txt_path: Path) -> list[dict]:
    """Llama a gen_keywords.py y devuelve la lista de keywords."""
    script = _find_script("core/gen_keywords.py")
    proc = subprocess.run(
        [sys.executable, str(script), str(txt_path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gen_keywords.py falló:\n{(proc.stderr or proc.stdout or '').strip()}")
    obj = json.loads(proc.stdout)
    kws = obj.get("keywords", obj) if isinstance(obj, dict) else obj
    if not isinstance(kws, list) or not kws:
        raise RuntimeError("gen_keywords.py devolvió keywords vacías.")
    return kws

def write_pending_keywords(date: str, keywords: list[dict], fp: str) -> None:
    payload = {
        "date": date,
        "docs_fingerprint": fp,
        "keywords": keywords,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    p = state_dir() / "pending_keywords.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ──────────────────────────────────────────
# merge_pending
# ──────────────────────────────────────────

def run_merge_pending(txt_path: Path, apply_keywords: bool = True, dry_run: bool = False) -> dict:
    script = _find_script("core/merge_pending.py")
    cmd = [
        sys.executable, str(script),
        str(txt_path),
        "--archivo",       str(archivo_json_path()),
        "--pending-kw",    str(state_dir() / "pending_keywords.txt"),
        "--pending-entry", str(state_dir() / "pending_entry.json"),
        "--sort-by-date",
    ]
    if apply_keywords:
        cmd.append("--apply-keywords")
    if dry_run:
        cmd.append("--dry-run")

    proc = subprocess.run(cmd, capture_output=True, text=True)
    combined = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        raise RuntimeError(combined.strip() or "merge_pending.py falló")

    for line in combined.splitlines():
        if line.startswith("STATUS_JSON="):
            return json.loads(line.split("=", 1)[1])
    raise RuntimeError("merge_pending.py no emitió STATUS_JSON=")


# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Re-pull y actualiza una entrada desde Google Docs")
    ap.add_argument("--date", required=True, help="Fecha a actualizar (YYYY-MM-DD)")
    ap.add_argument("--regen-keywords", action="store_true",
                    help="Regenera keywords con OpenAI (por defecto: conserva las existentes)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Simula todo sin hacer commit ni push")
    args = ap.parse_args()

    date = args.date.strip()
    if not DATE_RE.fullmatch(date):
        print(f"[update] ERROR: fecha inválida: {date!r}  (usa YYYY-MM-DD)", file=sys.stderr)
        return 1

    print(f"[update] ── Actualizando entrada: {date} ──")

    # 1. Pull desde Google Docs
    print("[update] Descargando desde Google Docs...")
    poem_obj     = run_py_json("scripts/gdocs/gdocs_pull_poem_by_date.py",     ["--date", date])
    analysis_obj = run_py_json("scripts/gdocs/gdocs_pull_analysis_by_date.py", ["--date", date])

    my_poem_title = (poem_obj.get("title")           or "").strip()
    poem_text     = (poem_obj.get("poem")            or "")
    poeta         = (analysis_obj.get("poet")        or "").strip()
    poem_title    = (analysis_obj.get("poem_title")  or "").strip()
    book_title    = (analysis_obj.get("book_title")  or "").strip()
    poema_citado  = (analysis_obj.get("poem_citado") or "")
    texto         = (analysis_obj.get("analysis")    or "")

    if not normalize_text_for_hash(poem_text):
        print(f"[update] ERROR: # POEMA está vacío en Google Docs para {date}", file=sys.stderr)
        return 1

    n_poem   = len(normalize_text_for_hash(poem_text).splitlines())
    n_citado = len(normalize_text_for_hash(poema_citado).splitlines())
    n_texto  = len(normalize_text_for_hash(texto).splitlines())
    print(f"[update] Pull OK — POEMA: {n_poem} líneas | POEMA_CITADO: {n_citado} | TEXTO: {n_texto}")

    # 2. Fingerprint del contenido descargado
    fp = docs_fingerprint(poem_text, poema_citado, texto)
    print(f"[update] fingerprint: {fp}")

    # 3. Escribir .txt (sobrescribe si existe)
    txt_path = txt_path_for_date(date)
    content  = render_txt(date, my_poem_title, poeta, poem_title, book_title,
                          poem_text, poema_citado, texto)
    old_txt = txt_path.read_text(encoding="utf-8") if txt_path.exists() else None
    txt_changed = old_txt != content
    if not args.dry_run:
        write_txt_atomic(txt_path, content)
    print(f"[update] .txt {'(dry-run, no escrito)' if args.dry_run else f'escrito: {txt_path}'}")

    # 4. Keywords: preservar o regenerar
    if args.regen_keywords:
        print("[update] Regenerando keywords desde OpenAI...")
        keywords = generate_keywords(txt_path)
        print(f"[update] {len(keywords)} keywords generadas")
    else:
        keywords = load_existing_keywords(date)
        if keywords:
            print(f"[update] Preservando {len(keywords)} keywords existentes")
        else:
            print("[update] No hay keywords existentes — generando nuevas con OpenAI...")
            keywords = generate_keywords(txt_path)
            print(f"[update] {len(keywords)} keywords generadas")

    if not args.dry_run:
        write_pending_keywords(date, keywords, fp)

    # 5. Merge en archivo.json
    status = run_merge_pending(txt_path, apply_keywords=True, dry_run=args.dry_run)
    content_changed  = bool(status.get("content_changed"))
    keywords_changed = bool(status.get("keywords_changed"))
    print(f"[update] content_changed={content_changed}  keywords_changed={keywords_changed}  txt_changed={txt_changed}")

    if not content_changed and not keywords_changed and not txt_changed:
        print("[update] Sin cambios detectados. Nada que commitear.")
        return 0

    if args.dry_run:
        print("[update] DRY RUN completo — no se hizo commit ni push.")
        return 0

    # 6. Commit y push
    label      = (my_poem_title or status.get("my_poem_snippet") or date).strip()
    commit_msg = f"update {date} — {label}"

    pending_entry_path = state_dir() / "pending_entry.json"
    git(["add", str(archivo_json_path()), str(txt_path), str(pending_entry_path)])
    git(["commit", "-m", commit_msg])
    git(["push"])
    print(f"[update] ✅ Publicado: {commit_msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
