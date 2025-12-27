#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from typing import Dict, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVO_JSON = REPO_ROOT / "archivo.json"
PENDING_ENTRY = REPO_ROOT / "scripts" / "pending_entry.json"

SECTION_HEADERS = ["POEMA", "POEMA_CITADO", "TEXTO"]

# Metadatos opcionales (si un día quieres añadirlos arriba del txt)
META_ALIASES = {
    "FECHA": "date",
    "POETA": "poet",
    "POEM_TITLE": "poem_title",
    "BOOK_TITLE": "book_title",
    "MY_POEM_TITLE": "my_poem_title",
    "MY_POEM_SNIPPET": "my_poem_snippet",
    "POEM_SNIPPET": "poem_snippet",
}

def parse_txt(txt_path: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
    raw = txt_path.read_text(encoding="utf-8").replace("\r\n", "\n")

    # meta: líneas "CLAVE: valor" antes del primer header "# ..."
    meta: Dict[str, str] = {}
    first_header_pos = len(raw)
    for h in SECTION_HEADERS:
        m = re.search(rf"(?m)^\s*#\s*{re.escape(h)}\s*$", raw)
        if m:
            first_header_pos = min(first_header_pos, m.start())

    meta_block = raw[:first_header_pos]
    for line in meta_block.splitlines():
        m = re.match(r"^\s*([A-Za-zÁÉÍÓÚÑ_]+)\s*:\s*(.*?)\s*$", line)
        if not m:
            continue
        k = m.group(1).strip().upper()
        v = m.group(2).strip()
        if not v:
            continue
        if k in META_ALIASES:
            meta[META_ALIASES[k]] = v

    # sections: texto entre headers "# NAME" y el siguiente header
    sections: Dict[str, str] = {}
    header_re = r"(?m)^\s*#\s*(POEMA|POEMA_CITADO|TEXTO)\s*$"
    matches = list(re.finditer(header_re, raw))
    for i, m in enumerate(matches):
        name = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        sections[name] = raw[start:end].strip()

    # fecha: si no está en meta, intenta sacarla del nombre del archivo YYYY-MM-DD
    if "date" not in meta:
        m = re.search(r"\d{4}-\d{2}-\d{2}", txt_path.name)
        if m:
            meta["date"] = m.group(0)

    # snippet de TU poema:
    # - si tú lo das explícitamente (MY_POEM_SNIPPET: ...), se usa
    # - si NO hay título (MY_POEM_TITLE vacío), entonces autogeneramos snippet desde # POEMA
    # - si SÍ hay título, NO autogeneramos snippet (lo dejamos vacío)
    if "my_poem_snippet" not in meta:
        title = (meta.get("my_poem_title") or "").strip()
        if not title:
            for line in sections.get("POEMA", "").splitlines():
                line = line.strip()
                if line:
                    meta["my_poem_snippet"] = line
                    break
        else:
            meta["my_poem_snippet"] = ""



    return meta, sections

def load_archivo() -> list:
    if not ARCHIVO_JSON.exists():
        raise FileNotFoundError(f"No encuentro {ARCHIVO_JSON}")
    data = json.loads(ARCHIVO_JSON.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("archivo.json debe ser una LISTA de entradas.")
    return data

def build_entry(meta: dict, txt_relpath: str) -> dict:
    date = (meta.get("date") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise ValueError(
            "Fecha inválida o ausente. Nombra el archivo como YYYY-MM-DD.txt "
            "o añade 'FECHA: YYYY-MM-DD' arriba."
        )

    entry = {
        "date": date,
        "month": date[:7],
        "file": txt_relpath,
        "my_poem_title": (meta.get("my_poem_title") or "").strip(),
        "my_poem_snippet": (meta.get("my_poem_snippet") or "").strip(),
        "analysis": {
            "poet": (meta.get("poet") or "").strip(),
            "poem_title": (meta.get("poem_title") or "").strip(),
            "poem_snippet": (meta.get("poem_snippet") or "").strip(),  # puede quedar ""
            "book_title": (meta.get("book_title") or "").strip(),
        },
        "keywords": []  # vacío a propósito
    }
    return entry

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("txt", help="Ruta al .txt (ej: textos/2025-12-25.txt)")
    args = ap.parse_args()

    txt_path = (REPO_ROOT / args.txt).resolve()
    if not txt_path.exists():
        raise FileNotFoundError(f"No existe: {txt_path}")

    meta, sections = parse_txt(txt_path)

    # Validación mínima: que exista análisis
    if not sections.get("TEXTO", "").strip():
        raise ValueError("No encuentro contenido bajo '# TEXTO' (tu análisis).")

    txt_relpath = str(txt_path.relative_to(REPO_ROOT)).replace("\\", "/")
    entry = build_entry(meta, txt_relpath)

    # Evita duplicar por fecha
    entries = load_archivo()
    if any(e.get("date") == entry["date"] for e in entries):
        print(f"⚠️  Nota: ya existe date={entry['date']} en archivo.json. Voy a generar pending_entry.json igual.")


    PENDING_ENTRY.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK: creado {PENDING_ENTRY}")
    print("Siguiente: pega las keywords (JSON con pesos) en scripts/pending_keywords.txt")
    print("y corre: python3 scripts/merge_pending.py")

if __name__ == "__main__":
    main()
