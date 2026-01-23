#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional


# -----------------------------
# JSON helpers
# -----------------------------
def _atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_archivo(path: Path) -> Tuple[Any, List[Dict[str, Any]]]:
    """
    Supports:
      - archivo.json as {"entries":[...], ...metadata}
      - archivo.json as [...]
    Returns:
      (data_root, entries_list_of_dicts)
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("entries", []) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise SystemExit("archivo.json inválido: 'entries' no es una lista (o el root no es lista).")

    out: List[Dict[str, Any]] = []
    for e in entries:
        if isinstance(e, dict):
            out.append(e)
    return raw, out


# -----------------------------
# Keyword normalization
# -----------------------------
def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def norm_word(s: str) -> str:
    s = strip_accents(s).lower().strip()
    s = " ".join(s.split())
    return s


def normalize_keywords(payload: Any) -> List[Dict[str, Any]]:
    """
    Accepts:
      - list[{"word":..., "weight":...}]
      - {"keywords":[...]}
      - {"date":"YYYY-MM-DD","keywords":[...]}
    Returns stable, deduped, sorted list (desc weight, asc word).
    """
    if payload is None:
        raw = []
    elif isinstance(payload, dict):
        raw = payload.get("keywords", [])
    else:
        raw = payload

    if not isinstance(raw, list):
        raw = []

    best: Dict[str, int] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        w = norm_word(str(item.get("word", "")))
        if not w:
            continue
        try:
            weight = int(item.get("weight", 1))
        except Exception:
            weight = 1
        weight = max(1, min(3, weight))
        best[w] = max(best.get(w, 0), weight)

    out = [{"word": w, "weight": best[w]} for w in best]
    out.sort(key=lambda d: (-d["weight"], d["word"]))
    return out


def keywords_equal(a: Any, b: Any) -> bool:
    return normalize_keywords(a) == normalize_keywords(b)


# -----------------------------
# Build entry from .txt via make_pending_entry.py
# -----------------------------
def build_entry_from_txt(txt_path: Path, pending_entry_out: Path) -> Dict[str, Any]:
    script = Path(__file__).resolve().parent / "make_pending_entry.py"
    if not script.exists():
        raise SystemExit("No existe qmp/make_pending_entry.py (necesario para parsear el .txt).")

    pending_entry_out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, str(script), str(txt_path), "--out", str(pending_entry_out)]
    subprocess.check_call(cmd)

    entry = json.loads(pending_entry_out.read_text(encoding="utf-8"))
    if not isinstance(entry, dict) or not entry.get("date"):
        raise SystemExit("pending_entry.json inválido: make_pending_entry.py no devolvió un entry correcto.")
    # defensive: no queremos secciones internas en archivo.json
    entry.pop("sections", None)
    return entry


# -----------------------------
# Merge logic
# -----------------------------
def upsert_entry(entries: List[Dict[str, Any]], entry: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int, bool]:
    """
    Replace entry with same date if exists, else append.
    Returns: (new_entries, index, existed_before)
    """
    date = entry.get("date")
    if not date:
        raise SystemExit("Entry inválido: falta 'date'.")

    for i, e in enumerate(entries):
        if e.get("date") == date:
            new_entries = list(entries)
            new_entries[i] = entry
            return new_entries, i, True

    new_entries = list(entries) + [entry]
    return new_entries, len(new_entries) - 1, False


def without_keywords(e: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(e)
    d.pop("keywords", None)
    return d


# -----------------------------
# CLI
# -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("txt_path", type=Path, help="Path al .txt (textos/YYYY-MM-DD.txt)")
    ap.add_argument("--archivo", required=True, type=Path, help="Path a data/archivo.json")
    ap.add_argument("--pending-kw", required=True, type=Path, help="Path a state/pending_keywords.txt")
    ap.add_argument("--pending-entry", required=True, type=Path, help="Path a state/pending_entry.json")
    ap.add_argument("--apply-keywords", action="store_true", help="Aplicar keywords desde pending_keywords")
    ap.add_argument("--dry-run", action="store_true", help="No escribe archivo.json (pero sí emite STATUS_JSON)")
    ap.add_argument("--sort-by-date", action="store_true", help="Ordenar entries por date antes de escribir")
    args = ap.parse_args()

    txt_path: Path = args.txt_path
    archivo: Path = args.archivo
    pending_kw_path: Path = args.pending_kw
    pending_entry_path: Path = args.pending_entry
    APPLY_KW: bool = bool(args.apply_keywords)
    DRY_RUN: bool = bool(args.dry_run)

    if not txt_path.exists():
        raise SystemExit(f"No existe: {txt_path}")
    if not archivo.exists():
        raise SystemExit(f"Falta archivo.json: {archivo}")

    data_root, entries = load_archivo(archivo)

    # Build entry from .txt (source of truth for structure)
    entry = build_entry_from_txt(txt_path, pending_entry_path)
    date = entry["date"]

    # Find old entry (for change detection / preserving keywords)
    old_entry = next((e for e in entries if e.get("date") == date), None)

    applied_keywords = False
    if APPLY_KW:
        if not pending_kw_path.exists():
            raise SystemExit(f"Falta pending_keywords: {pending_kw_path} (necesario para --apply-keywords)")
        pending_payload = json.loads(pending_kw_path.read_text(encoding="utf-8"))

        # If pending payload includes a date, enforce it matches
        if isinstance(pending_payload, dict) and pending_payload.get("date"):
            if str(pending_payload["date"]) != str(date):
                raise SystemExit(
                    f"pending_keywords date mismatch: pending={pending_payload['date']} != entry={date}"
                )

        entry["keywords"] = normalize_keywords(pending_payload)
        applied_keywords = True
    else:
        # Preserve published keywords unless user explicitly applies new ones
        entry["keywords"] = old_entry.get("keywords", []) if old_entry else []

    # Contract: new entry must not be published without keywords
    # (if you ever want to allow it, remove this block)
    if old_entry is None and not entry.get("keywords"):
        raise SystemExit("Entrada nueva sin keywords. Genera keywords (qk / q --kw) o usa --apply-keywords.")

    # Change detection
    exists_before = old_entry is not None
    content_changed = True if old_entry is None else (without_keywords(old_entry) != without_keywords(entry))
    keywords_changed = True if old_entry is None else (not keywords_equal(old_entry.get("keywords", []), entry.get("keywords", [])))

    # Always rewrite pending_entry.json with final keywords (useful for debugging / pipeline)
    _atomic_write_json(pending_entry_path, entry)

    # Merge into entries
    new_entries, idx, existed = upsert_entry(entries, entry)

    if args.sort_by_date:
        new_entries.sort(key=lambda e: e.get("date", ""))  # assumes YYYY-MM-DD

    # Rebuild archivo root
    if isinstance(data_root, dict):
        out_root = dict(data_root)
        out_root["entries"] = new_entries
    else:
        out_root = new_entries

    archivo_written = False
    if not DRY_RUN:
        _atomic_write_json(archivo, out_root)
        archivo_written = True

    status = {
        "dry_run": DRY_RUN,
        "date": date,
        "exists_before": exists_before,
        "entry_index": idx,
        "content_changed": bool(content_changed),
        "keywords_changed": bool(keywords_changed),
        "applied_keywords": bool(applied_keywords),
        "archivo_written": bool(archivo_written),
        # for commit message / UI
        "my_poem_title": entry.get("my_poem_title", "") or "",
        "my_poem_snippet": entry.get("my_poem_snippet", "") or "",
    }

    print("STATUS_JSON=" + json.dumps(status, ensure_ascii=False))


if __name__ == "__main__":
    main()
