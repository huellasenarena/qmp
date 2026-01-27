#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from typing import List, Optional, Tuple

from googleapiclient.discovery import build

from _gdocs_auth import get_creds, load_config

# Heading TITLE:
#   260121
#   260121 (en un aeropuerto)
HEADING_RE = re.compile(r"^\s*(\d{6})\s*(?:\((.*?)\))?\s*$")
HR_FALLBACK_RE = re.compile(r"^\s*[─]{10,}\s*$")  # por si el separador fuera texto

def yymmdd(date_str: str) -> str:
    y, m, d = date_str.split("-")
    return y[2:] + m + d  # "260116"

def first_six_digits(s: str) -> str:
    s = (s or "").replace("\u00a0", " ").strip()
    digits = re.sub(r"\D+", "", s)
    return digits[:6]


def get_tab_by_title(doc: dict, tab_title: str) -> dict:
    tabs = doc.get("tabs") or []
    wanted = tab_title.strip().lower()
    for t in tabs:
        title = (t.get("tabProperties", {}).get("title") or "").strip().lower()
        if title == wanted:
            return t
    available = [t.get("tabProperties", {}).get("title") for t in tabs]
    raise KeyError(f"No encontré el tab {tab_title!r}. Tabs disponibles: {available!r}")

def is_horizontal_rule(item: dict) -> bool:
    return "horizontalRule" in item

def paragraph_style(item: dict) -> Optional[str]:
    para = item.get("paragraph")
    if not para:
        return None
    return (para.get("paragraphStyle") or {}).get("namedStyleType")

def paragraph_text_no_strike(item: dict) -> str:
    """Concatena textRuns excluyendo los tachados."""
    para = item.get("paragraph")
    if not para:
        return ""
    parts: List[str] = []
    for elem in para.get("elements", []):
        tr = elem.get("textRun")
        if not tr:
            continue
        content = tr.get("content", "")
        style = tr.get("textStyle") or {}
        if style.get("strikethrough") is True:
            continue
        parts.append(content)
    return "".join(parts).rstrip("\n")

def extract_heading(item: dict) -> str:
    return paragraph_text_no_strike(item).strip()

def yyyymmdd_to_yymmdd(date_str: str) -> str:
    # input: YYYY-MM-DD
    return date_str[2:4] + date_str[5:7] + date_str[8:10]

def pull_poem(doc_id: str, tab_title: str, yymmdd: str) -> Tuple[Optional[str], str]:
    service = build("docs", "v1", credentials=get_creds())
    doc = service.documents().get(documentId=doc_id, includeTabsContent=True).execute()
    tab = get_tab_by_title(doc, tab_title)
    content = (tab.get("documentTab", {}).get("body", {}).get("content")) or []

    # 1) encontrar heading
    start_i = None
    title = None
    for i, item in enumerate(content):
        if paragraph_style(item) != "HEADING_1":
            continue
        h = extract_heading(item)
        m = HEADING_RE.match(h)
        if m and m.group(1) == yymmdd:
            start_i = i
            title = (m.group(2) or "").strip() or None
            break

    if start_i is None:
        return (None, "")

    # 2) recolectar poema hasta HR o siguiente heading-fecha
    poem_lines: List[str] = []
    i = start_i + 1

    while i < len(content):
        item = content[i]

        if is_horizontal_rule(item):
            break

        if paragraph_style(item) == "HEADING_1":
            h = extract_heading(item)
            if HEADING_RE.match(h):
                break

        if item.get("paragraph"):
            line = paragraph_text_no_strike(item)
            # si el separador fuera texto (no horizontalRule), córtalo también
            if HR_FALLBACK_RE.match(line):
                break
            poem_lines.append(line)

        i += 1

    # limpieza suave
    while poem_lines and poem_lines[0].strip() == "":
        poem_lines.pop(0)
    while poem_lines and poem_lines[-1].strip() == "":
        poem_lines.pop()



    def norm(s: str) -> str:
        return " ".join(s.strip().split()).lower()

    # Si el poema empieza con el título, quítalo del POEM.
    # Soporta títulos multi-línea codificados como "línea1/línea2/..."
    if title:
        title_lines = [t.strip() for t in title.split("/") if t.strip()]
        if title_lines and len(poem_lines) >= len(title_lines):
            ok = True
            for j, tl in enumerate(title_lines):
                if norm(poem_lines[j]) != norm(tl):
                    ok = False
                    break
            if ok:
                # remover todas las líneas del título
                for _ in range(len(title_lines)):
                    poem_lines.pop(0)
                # limpiar líneas vacías iniciales extra
                while poem_lines and poem_lines[0].strip() == "":
                    poem_lines.pop(0)

            
    poem = "\n".join(poem_lines).rstrip() + ("\n" if poem_lines else "")
    return (title, poem)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--tab", default=None)
    ap.add_argument("--doc", default=None)
    args = ap.parse_args()

    cfg = load_config()
    doc_id = args.doc or cfg.get("poems_doc_id")
    tab_title = args.tab or cfg.get("poems_tab_title") or "Poemas finales"
    if not doc_id:
        print("ERROR: missing poems_doc_id in config")
        return 2

    yymmdd = yyyymmdd_to_yymmdd(args.date)

    title, poem = pull_poem(doc_id, tab_title, yymmdd)

    # salida “parseable” por shell sin jq: 2 bloques delimitados
    # TITLE:
    # <title or empty>
    # POEM:
    # <poem...>
    import json

    print(json.dumps({
        "title": title or "",
        "poem": poem
    }, ensure_ascii=False))


    return 0

if __name__ == "__main__":
    raise SystemExit(main())