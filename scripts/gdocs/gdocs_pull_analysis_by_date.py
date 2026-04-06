#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import List, Optional, Tuple

from googleapiclient.discovery import build

from _gdocs_auth import get_creds, load_config

# Nuevo contrato (Escritos / análisis):
# - La fecha está en HEADING_1 (o TITLE legacy) y comienza con YYMMDD
#   (puede tener texto extra: "260214 - BdS AIICl").
# - Debajo de la fecha hay metadatos (Poeta, Libro, Título) en cualquier orden.
# - SIEMPRE existe un "Versión final" en HEADING_2.
# - El bloque ENTRE metadatos y "Versión final" es el "poema citado".
#   Si ese bloque está vacío => significa "modo PDF" (lo decide qcrear).
# - El bloque DESPUÉS de "Versión final" es el texto de análisis.
#   Puede estar vacío si quieres usar PDF.

DATE_STYLE_TYPES = {"HEADING_1", "TITLE"}

FINAL_RE = re.compile(r"^\s*versi[oó]n\s+final\s*:?.*$", re.IGNORECASE)
META_POETA_RE = re.compile(r"^\s*poeta\s*:\s*(.*)\s*$", re.IGNORECASE)
META_LIBRO_RE = re.compile(r"^\s*libro\s*:\s*(.*)\s*$", re.IGNORECASE)
META_TITULO_RE = re.compile(r"^\s*t[íi]tulo\s*:\s*(.*)\s*$", re.IGNORECASE)


class FormatError(RuntimeError):
    pass


def yyyymmdd_to_yymmdd(date_str: str) -> str:
    return date_str[2:4] + date_str[5:7] + date_str[8:10]


def strip_invisibles(s: str) -> str:
    if s is None:
        return ""
    s = s.replace("\u00a0", " ")
    for ch in ("\u200b", "\ufeff", "\u2060"):
        s = s.replace(ch, "")
    return s


def first_six_digits(s: str) -> str:
    s = strip_invisibles(s)
    digits = re.sub(r"\D+", "", s)
    return digits[:6]


def split_logical_lines(text: str) -> List[str]:
    """Divide un texto en 'líneas' aunque el párrafo tenga Shift+Enter."""
    text = strip_invisibles(text)
    # Google Docs puede devolver \n o \u000b (vertical tab) dependiendo del caso
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u000b", "\n").replace("\v", "\n")
    return text.split("\n")


def get_tab_by_title(doc: dict, tab_title: str) -> dict:
    tabs = doc.get("tabs") or []
    wanted = tab_title.strip().lower()
    for t in tabs:
        title = (t.get("tabProperties", {}).get("title") or "").strip().lower()
        if title == wanted:
            return t
    available = [t.get("tabProperties", {}).get("title") for t in tabs]
    raise KeyError(f"No encontré el tab {tab_title!r}. Tabs disponibles: {available!r}")


def paragraph_style(item: dict) -> Optional[str]:
    para = item.get("paragraph")
    if not para:
        return None
    return (para.get("paragraphStyle") or {}).get("namedStyleType")


def paragraph_text_no_strike(item: dict) -> str:
    para = item.get("paragraph")
    if not para:
        return ""
    parts: List[str] = []
    for elem in para.get("elements", []):
        tr = elem.get("textRun")
        if not tr:
            continue
        style = tr.get("textStyle") or {}
        if style.get("strikethrough") is True:
            continue
        parts.append(tr.get("content", ""))
    return "".join(parts).rstrip("\n")


def find_date_block(content: list, yymmdd: str) -> Tuple[int, int]:
    """Encuentra el bloque de la entrada: desde el Heading 1 de la fecha hasta el próximo Heading 1."""
    start_i = None
    # buscamos desde el final porque las entradas nuevas están al final
    for i in range(len(content) - 1, -1, -1):
        it = content[i]
        if (paragraph_style(it) or "") not in DATE_STYLE_TYPES:
            continue
        txt = strip_invisibles(paragraph_text_no_strike(it)).strip()
        if first_six_digits(txt) == yymmdd:
            start_i = i
            break

    if start_i is None:
        raise FormatError(f"No encontré la fecha {yymmdd} (HEADING_1).")

    end_i = len(content)
    for j in range(start_i + 1, len(content)):
        it = content[j]
        if (paragraph_style(it) or "") in DATE_STYLE_TYPES:
            txt = strip_invisibles(paragraph_text_no_strike(it)).strip()
            if len(first_six_digits(txt)) == 6:
                end_i = j
                break

    return start_i, end_i


def clean_block_text(lines: List[str]) -> str:
    # rstrip + remove empty extremes
    lines = [strip_invisibles(ln).rstrip() for ln in lines]
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()
    return "\n".join(lines)


def pull_entry(doc_id: str, tab_title: str, yymmdd: str) -> dict:
    service = build("docs", "v1", credentials=get_creds())
    doc = service.documents().get(documentId=doc_id, includeTabsContent=True).execute()
    tab = get_tab_by_title(doc, tab_title)
    content = (tab.get("documentTab", {}).get("body", {}).get("content")) or []

    start_i, end_i = find_date_block(content, yymmdd)
    block = content[start_i:end_i]

    # localizar "Versión final" (HEADING_2) - obligatorio
    anchors = []
    for k, it in enumerate(block):
        if paragraph_style(it) != "HEADING_2":
            continue
        txt = strip_invisibles(paragraph_text_no_strike(it)).strip()
        if FINAL_RE.match(txt):
            anchors.append(k)

    if len(anchors) != 1:
        raise FormatError(
            f"Formato inválido en {yymmdd}: esperaba exactamente 1 'Versión final' (HEADING_2), encontré {len(anchors)}."
        )

    a = anchors[0]

    # parsear metadatos + poema citado (todo lo que NO sea metadato) antes del anchor
    poet = ""
    poem_title = ""
    book_title = ""

    cited_lines: List[str] = []

    for it in block[1:a]:  # saltar Heading 1
        if not it.get("paragraph"):
            continue
        raw = paragraph_text_no_strike(it)
        # un mismo párrafo puede tener varias líneas (Shift+Enter)
        for ln in split_logical_lines(raw):
            s = ln.strip()
            m = META_POETA_RE.match(s)
            if m:
                poet = m.group(1).strip()
                continue
            m = META_LIBRO_RE.match(s)
            if m:
                book_title = m.group(1).strip()
                continue
            m = META_TITULO_RE.match(s)
            if m:
                poem_title = m.group(1).strip()
                continue
            # no es metadato => parte del poema citado
            cited_lines.append(ln)

    poem_citado = clean_block_text(cited_lines)

    # texto después de "Versión final" (puede estar vacío para PDF)
    analysis_lines: List[str] = []
    for it in block[a + 1 :]:
        if not it.get("paragraph"):
            continue
        raw = paragraph_text_no_strike(it)
        for ln in split_logical_lines(raw):
            analysis_lines.append(ln)

    analysis = clean_block_text(analysis_lines)

    return {
        "poet": poet,
        "poem_title": poem_title,
        "book_title": book_title,
        "poem_citado": poem_citado,
        "analysis": analysis,
        "warnings": [],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--tab", default=None)
    ap.add_argument("--doc", default=None)
    args = ap.parse_args()

    cfg = load_config()
    doc_id = args.doc or cfg.get("analyses_doc_id")
    tab_title = args.tab or cfg.get("analyses_tab_title") or "Escritos"
    if not doc_id:
        print("ERROR: missing analyses_doc_id in config", file=sys.stderr)
        return 2

    yymmdd = yyyymmdd_to_yymmdd(args.date)

    try:
        obj = pull_entry(doc_id, tab_title, yymmdd)
    except FormatError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3
    except KeyError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 4

    print(json.dumps(obj, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
