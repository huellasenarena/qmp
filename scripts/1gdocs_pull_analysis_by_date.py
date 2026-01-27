#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import List, Optional, Tuple

from googleapiclient.discovery import build

from _gdocs_auth import get_creds, load_config

# Analyses doc contract (per-entry):
# - Date line is a paragraph with style HEADER_1, exactly YYMMDD (e.g. 260121)
# - Optional metadata lines (order-independent), usually near the top:
#     Poeta: <...>
#     Título: <...>
#     Libro: <...>
# - Poema citado = text after metadata until the first of:
#     - a paragraph starting with "Mi análisis" / "Mi ensayo" (case-insensitive)
#     - the "Versión final" heading (HEADING_2)
#     - end of entry block
# - Versión final = text after "Versión final" (HEADING_2) until end of entry block
#
# IMPORTANT: NO horizontal-line dependency.

DATE_RE = re.compile(r"^\s*(\d{6})\s*$")
FINAL_RE = re.compile(r"^\s*versi[oó]n\s+final\s*:?\s*$", re.IGNORECASE)

def first_six_digits(s: str) -> str:
    """Extrae los primeros 6 dígitos de un string (ignorando NBSP y signos)."""
    s = (s or "").replace("\u00a0", " ").strip()
    digits = re.sub(r"\D+", "", s)
    return digits[:6]


def is_date_title_line(text: str, target_yymmdd: str) -> bool:
    """True si el párrafo (estilo HEADER_1) contiene la fecha YYMMDD, aunque tenga texto extra."""
    return first_six_digits(text) == target_yymmdd

META_POETA_RE = re.compile(r"^\s*poeta\s*:\s*(.*)\s*$", re.IGNORECASE)
META_TITULO_RE = re.compile(r"^\s*t[íi]tulo\s*:\s*(.*)\s*$", re.IGNORECASE)
META_LIBRO_RE = re.compile(r"^\s*libro\s*:\s*(.*)\s*$", re.IGNORECASE)

STOP_ANALISIS_RE = re.compile(r"^\s*mi\s+an[áa]lisis\s*:?.*$", re.IGNORECASE)
STOP_ENSAYO_RE = re.compile(r"^\s*mi\s+ensayo\s*:?.*$", re.IGNORECASE)


class FormatError(RuntimeError):
    pass


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


def yyyymmdd_to_yymmdd(date_str: str) -> str:
    # YYYY-MM-DD -> YYMMDD
    return date_str[2:4] + date_str[5:7] + date_str[8:10]


def find_date_block(content: list, yymmdd: str) -> Tuple[int, int]:
    start_i = None
    for i, item in enumerate(content):
        if paragraph_style(item) != "HEADING_1":
            continue
        txt = paragraph_text_no_strike(item).strip()
        if is_date_title_line(txt, yymmdd):
            start_i = i
            break
    if start_i is None:
        raise FormatError(f"No encontré la fecha {yymmdd} (estilo TITLE 1).")

    end_i = len(content)
    for j in range(start_i + 1, len(content)):
        it = content[j]
        if paragraph_style(it) == "HEADING_1":
            t = paragraph_text_no_strike(it).strip()
            if is_date_title_line(t, yymmdd) or (len(first_six_digits(t)) == 6 and first_six_digits(t) != ""):
                end_i = j
                break
    return start_i, end_i


def _clean_lines(lines: List[str]) -> str:
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()
    return "\n".join(lines).strip()


def pull_entry(doc_id: str, tab_title: str, yymmdd: str) -> dict:
    service = build("docs", "v1", credentials=get_creds())
    doc = service.documents().get(documentId=doc_id, includeTabsContent=True).execute()
    tab = get_tab_by_title(doc, tab_title)
    content = (tab.get("documentTab", {}).get("body", {}).get("content")) or []

    start_i, end_i = find_date_block(content, yymmdd)
    block = content[start_i:end_i]

    warnings: List[str] = []

    # Find "Versión final" anchor (HEADING_2)
    anchors = []
    for k, item in enumerate(block):
        if paragraph_style(item) != "HEADING_2":
            continue
        txt = paragraph_text_no_strike(item).strip()
        if FINAL_RE.match(txt):
            anchors.append(k)

    if len(anchors) != 1:
        raise FormatError(
            f"Formato inválido en {yymmdd}: esperaba exactamente 1 'Versión final' (HEADING_2), encontré {len(anchors)}."
        )
    a = anchors[0]

    # --- metadata + poem_citado from block[1:a]
    poet = ""
    poem_title = ""
    book_title = ""

    # soporte multi-línea para Título:
    poem_title_lines: List[str] = []
    collecting_title = False


    poem_lines: List[str] = []
    seen_poem_body = False

    for item in block[1:a]:  # skip date line
        if not item.get("paragraph"):
            continue

        txt = paragraph_text_no_strike(item)
        s = txt.strip()

        if STOP_ANALISIS_RE.match(s) or STOP_ENSAYO_RE.match(s):
            break

        m = META_POETA_RE.match(s)
        if m:
            poet = m.group(1).strip()
            continue
        m = META_TITULO_RE.match(s)
        if m:
            first = m.group(1).strip()
            poem_title_lines = [first] if first else []
            collecting_title = True
            continue

        m = META_LIBRO_RE.match(s)
        if m:
            book_title = m.group(1).strip()
            continue

        # Continuación del título en líneas siguientes (multi-línea)
        # Regla: si acabamos de ver "Título:" y aún no empezó el cuerpo del poema citado,
        # tomamos líneas no vacías que no sean otro metadata.
        if collecting_title and not seen_poem_body:
            if s == "":
                collecting_title = False
                continue

            # Si parece otro metadata, paramos
            if META_POETA_RE.match(s) or META_LIBRO_RE.match(s) or META_TITULO_RE.match(s):
                collecting_title = False
                # no hacemos continue: dejamos que el loop lo procese normalmente
            else:
                poem_title_lines.append(s)
                continue

        if s == "" and not seen_poem_body:
            continue

        seen_poem_body = True
        poem_lines.append(txt.rstrip())

    poem_citado = _clean_lines(poem_lines)

    # --- analysis after anchor until end of block
    analysis_lines: List[str] = []
    for item in block[a + 1 :]:
        if item.get("paragraph"):
            analysis_lines.append(paragraph_text_no_strike(item).rstrip())
    analysis = _clean_lines(analysis_lines)
    if not analysis:
        raise FormatError(f"Formato inválido en {yymmdd}: 'Versión final' está vacía (después de limpiar tachado).")

    poem_title = "/".join([t.strip() for t in poem_title_lines if t.strip()])

    return {
        "poet": poet,
        "poem_title": poem_title,
        "book_title": book_title,
        "poem_citado": poem_citado,
        "analysis": analysis,
        "warnings": warnings,
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
        print("ERROR: missing analyses_doc_id in config")
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


def yyyymmdd_to_yymmdd(date_str: str) -> str:
    return date_str[2:4] + date_str[5:7] + date_str[8:10]


if __name__ == "__main__":
    raise SystemExit(main())