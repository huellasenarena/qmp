#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from datetime import date
from typing import Optional, Dict, Any, List

from googleapiclient.discovery import build

from _gdocs_auth import get_creds, load_config


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def first_six_digits(s: str) -> str:
    s = (s or "").replace("\u00a0", " ")
    for ch in ("\u200b", "\ufeff", "\u2060"):
        s = s.replace(ch, "")
    import re as _re
    digits = _re.sub(r"\D+", "", s)
    return digits[:6]

def yymmdd_to_date(yymmdd: str) -> date:
    # "260226" → date(2026, 2, 26)
    yy, mm, dd = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    return date(2000 + yy, mm, dd)

def extract_text(el: Dict[str, Any]) -> str:
    # Extract plain text from a paragraph element (textRun)
    tr = el.get("textRun")
    if not tr:
        return ""
    return tr.get("content", "")


def normalize_heading_text(paragraph: Dict[str, Any]) -> str:
    els = paragraph.get("elements", []) or []
    txt = "".join(extract_text(e) for e in els)
    return txt.strip()


def find_limit_date(doc: Dict[str, Any]) -> date:
    content = (doc.get("body", {}) or {}).get("content", []) or []
    last_heading_raw: Optional[str] = None
    last_heading_date: Optional[date] = None

    for block in content:
        para = block.get("paragraph")
        if not para:
            continue
        pstyle = (para.get("paragraphStyle", {}) or {})
        if pstyle.get("namedStyleType") != "HEADING_1":
            continue

        heading_text = normalize_heading_text(para)
        last_heading_raw = heading_text

        digits = first_six_digits(heading_text)
        if len(digits) == 6:
            try:
                last_heading_date = yymmdd_to_date(digits)
            except Exception:
                pass

    if last_heading_raw is None:
        raise SystemExit("[limit-date] ERROR: no encontré ningún HEADING_1 en el documento/tab.")

    if last_heading_date is None:
        raise SystemExit(
            f"[limit-date] ERROR: el ÚLTIMO HEADING_1 no tiene fecha YYMMDD válida: {last_heading_raw!r}"
        )

    return last_heading_date


def get_tab_doc(service, doc_id: str, tab_title: str) -> Dict[str, Any]:
    doc = service.documents().get(documentId=doc_id, includeTabsContent=True).execute()
    tabs = doc.get("tabs", []) or []
    for t in tabs:
        props = (t.get("tabProperties", {}) or {})
        if props.get("title") == tab_title:
            # The content for this tab is inside documentTab
            dt = (t.get("documentTab", {}) or {})
            # documentTab itself is shaped like a document; it has body/content
            return dt
    raise SystemExit(f"[limit-date] ERROR: no encontré tab con título exacto: {tab_title!r}")


def main() -> int:
    cfg = load_config()
    doc_id = cfg["poems_doc_id"]
    tab_title = cfg["poems_tab_title"]

    service = build("docs", "v1", credentials=get_creds())

    tab_doc = get_tab_doc(service, doc_id, tab_title)
    limit = find_limit_date(tab_doc)

    print(f"DOC_LIMIT_DATE={limit.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
