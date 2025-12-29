#!/usr/bin/env python3
import argparse
import json
import re
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVO_JSON = REPO_ROOT / "archivo.json"
PENDING_ENTRY = REPO_ROOT / "scripts" / "pending_entry.json"
PENDING_KEYWORDS = REPO_ROOT / "scripts" / "pending_keywords.txt"

def normalize_kw(s: str) -> str:
    s = s.strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s)
    return s

def load_entries() -> list:
    data = json.loads(ARCHIVO_JSON.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("archivo.json debe ser una lista.")
    return data

def save_entries(entries: list) -> None:
    entries = sorted(entries, key=lambda e: e.get("date", ""), reverse=True)
    ARCHIVO_JSON.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def parse_keywords_payload(text: str) -> list:
    """
    Acepta:
    - Array JSON: [ {...}, ... ]
    - Objeto JSON: { "keywords": [ ... ] }
    - Fragmento JSON: "keywords": [ ... ]  (lo envolvemos)
    """
    s = text.strip()
    if not s:
        raise ValueError("pending_keywords.txt está vacío.")

    # Permitir fragmento '"keywords": [...]'
    if s.startswith('"keywords"') or s.startswith("'keywords'") or s.startswith("keywords"):
        s = "{ " + s
        if not s.rstrip().endswith("}"):
            s = s + " }"

    obj = json.loads(s)
    if isinstance(obj, list):
        kws = obj
    elif isinstance(obj, dict) and isinstance(obj.get("keywords"), list):
        kws = obj["keywords"]
    else:
        raise ValueError('pending_keywords.txt debe ser JSON: [...] o {"keywords":[...]} o el fragmento "keywords": [...]')

    out = []
    seen = set()
    for it in kws:
        if not isinstance(it, dict):
            continue
        word = it.get("word") or it.get("k") or ""
        weight = it.get("weight") or it.get("w") or 1

        try:
            weight = int(weight)
        except Exception:
            weight = 1
        weight = 3 if weight >= 3 else (2 if weight == 2 else 1)

        word = normalize_kw(str(word))
        if not word or word in seen:
            continue
        seen.add(word)
        out.append({"word": word, "weight": weight})

    return out[:30]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", "--dry", "-n", action="store_true", help="No escribe archivo.json (solo valida y actualiza pending_entry.json).")
    ap.add_argument("--new-only", action="store_true", help="Falla si ya existe una entrada con la misma date.")
    args = ap.parse_args()

    if not PENDING_ENTRY.exists():
        raise FileNotFoundError(f"No encuentro {PENDING_ENTRY}. Primero corre make_pending_entry.py")
    if not PENDING_KEYWORDS.exists():
        raise FileNotFoundError(f"No encuentro {PENDING_KEYWORDS}. Pega ahí el JSON de keywords con pesos.")

    entry = json.loads(PENDING_ENTRY.read_text(encoding="utf-8"))
    entry_date = (entry.get("date") or "").strip()
    if not entry_date:
        raise ValueError("pending_entry.json no tiene 'date'")

    kw_text = PENDING_KEYWORDS.read_text(encoding="utf-8").strip()
    entry["keywords"] = parse_keywords_payload(kw_text)

    # Guardar pending_entry.json actualizado (sí incluso en dry-run; es útil para commit msg / inspección)
    PENDING_ENTRY.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    entries = load_entries()
    exists = any(e.get("date") == entry_date for e in entries)

    if exists and args.new_only:
        raise ValueError(f"Ya existe una entrada con date={entry_date} en archivo.json (new-only).")

    action = "update" if exists else "new"

    if args.dry_run:
        # No tocamos archivo.json, pero reportamos la acción
        print(f"ACTION={action}")
        print(f"OK (dry-run): entrada {entry_date} lista ({len(entry.get('keywords', []))} keywords).")
        return

    # UPSERT: si existe, reemplaza; si no, añade
    entries = [e for e in entries if e.get("date") != entry_date]
    entries.append(entry)
    save_entries(entries)

    print(f"ACTION={action}")
    print(f"OK: {'reemplazada' if exists else 'añadida'} entrada {entry_date} con {len(entry.get('keywords', []))} keywords.")

if __name__ == "__main__":
    main()
