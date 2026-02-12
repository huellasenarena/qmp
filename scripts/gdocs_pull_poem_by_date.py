#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import List, Optional, Tuple

from googleapiclient.discovery import build

from _gdocs_auth import get_creds, load_config

# Nuevo contrato (Poemas):
# - La fecha está en HEADING_1 (o TITLE legacy) y comienza con YYMMDD
#   (puede tener texto extra: "260214 - orquídea").
# - Las entradas nuevas están al final del documento.
# - Si existe una línea que empieza con "Título:", ese es el título.
#   Si no existe, no hay título.

DATE_STYLE_TYPES = {"HEADING_1", "TITLE"}

META_TITLE_RE = re.compile(r"^\s*T[íi]tulo\s*:\s*(.*)\s*$", re.IGNORECASE)


def yyyymmdd_to_yymmdd(date_str: str) -> str:
    return date_str[2:4] + date_str[5:7] + date_str[8:10]


def first_six_digits(s: str) -> str:
    s = (s or "").replace("\u00a0", " ")
    # eliminar invisibles comunes
    for ch in ("\u200b", "\ufeff", "\u2060"):
        s = s.replace(ch, "")
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
        content = tr.get("content", "")
        style = tr.get("textStyle") or {}
        if style.get("strikethrough") is True:
            continue
        parts.append(content)
    return "".join(parts).rstrip("\n")


def split_logical_lines(text: str) -> List[str]:
    # Normaliza separadores internos (Shift+Enter suele llegar como \n)
    if text is None:
        return []
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    # algunos clientes usan VT
    t = t.replace("\u000b", "\n")
    return t.split("\n")


def find_block(content: list, target_yymmdd: str) -> Tuple[int, int]:
    # Buscar desde el final el HEADING_1 que empiece con esa fecha
    start_i: Optional[int] = None
    for i in range(len(content) - 1, -1, -1):
        it = content[i]
        if (paragraph_style(it) or "") not in DATE_STYLE_TYPES:
            continue
        h = paragraph_text_no_strike(it).strip()
        if first_six_digits(h) == target_yymmdd:
            start_i = i
            break
    if start_i is None:
        return (-1, -1)

    end_i = len(content)
    for j in range(start_i + 1, len(content)):
        it = content[j]
        if (paragraph_style(it) or "") in DATE_STYLE_TYPES:
            h = paragraph_text_no_strike(it).strip()
            if len(first_six_digits(h)) == 6:
                end_i = j
                break
    return (start_i, end_i)


def pull_poem(doc_id: str, tab_title: str, yymmdd: str) -> Tuple[str, str]:
    service = build("docs", "v1", credentials=get_creds())
    doc = service.documents().get(documentId=doc_id, includeTabsContent=True).execute()
    tab = get_tab_by_title(doc, tab_title)
    content = (tab.get("documentTab", {}).get("body", {}).get("content")) or []

    start_i, end_i = find_block(content, yymmdd)
    if start_i < 0:
        return ("", "")

    block = content[start_i + 1 : end_i]  # excluye el heading de fecha

    title = ""
    poem_lines: List[str] = []

    # 1) Detectar "Título:" en la primera(s) línea(s) del bloque
    consumed_first_title_line = False
    for idx, item in enumerate(block):
        if not item.get("paragraph"):
            continue

        raw = paragraph_text_no_strike(item)
        logical = split_logical_lines(raw)

        # Si todavía no hemos encontrado título, intentamos solo en el primer contenido real
        # (cualquier línea lógica que empiece con "Título:")
        found_title_here = False
        for line in logical:
            m = META_TITLE_RE.match(line)
            if (not consumed_first_title_line) and m:
                title = (m.group(1) or "").strip()
                consumed_first_title_line = True
                found_title_here = True
                # Si había más texto en ese párrafo después de "Título:", lo ignoramos.
                continue
            if found_title_here:
                # Si este párrafo era la línea del título, ignoramos el resto de líneas lógicas
                # para evitar que el título se meta en el poema.
                continue

            poem_lines.append(line)

    # limpieza suave (sin depender de qcrear)
    # quitar NBSP / invisibles
    cleaned: List[str] = []
    for ln in poem_lines:
        x = (ln or "").replace("\u00a0", " ")
        for ch in ("\u200b", "\ufeff", "\u2060"):
            x = x.replace(ch, "")
        cleaned.append(x.rstrip())

    # quitar vacíos extremos
    while cleaned and cleaned[0].strip() == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1].strip() == "":
        cleaned.pop()

    poem = "\n".join(cleaned).rstrip() + ("\n" if cleaned else "")
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

    print(json.dumps({"title": title, "poem": poem}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
