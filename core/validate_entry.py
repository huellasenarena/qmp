#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date as dt
from pathlib import Path
from typing import Dict, Tuple

SECTION_ORDER = ["POEMA", "POEMA_CITADO", "TEXTO"]
META_KEYS = ["FECHA", "MY_POEM_TITLE", "POETA", "POEM_TITLE", "BOOK_TITLE"]

HDR_RE = re.compile(r"(?m)^\s*#\s*(POEMA|POEMA_CITADO|TEXTO)\s*$")
META_LINE_RE = re.compile(r"^\s*([A-Z_]+)\s*:\s*(.*)\s*$")

# Secciones opcionales de transparencia IA. Van DESPUÉS de # TEXTO y se
# conservan VERBATIM (su contenido puede tener líneas que empiezan con '#',
# blank lines significativas, etc.). CONVERSACION debe ir al final.
EXTRA_HDR_RE = re.compile(r"(?m)^\s*#\s*(BORRADOR|CONVERSACION)\s*$")


def _split_extras(body: str) -> Tuple[str, str]:
    """Separa el cuerpo en (core, extras). 'core' es lo previo al primer
    encabezado de transparencia (# BORRADOR / # CONVERSACION); 'extras' es
    ese encabezado y todo lo que sigue, sin tocar."""
    m = EXTRA_HDR_RE.search(body)
    if not m:
        return body, ""
    return body[: m.start()], body[m.start():]


def _extract_extras(extras: str) -> Dict[str, str]:
    """Devuelve {BORRADOR: ..., CONVERSACION: ...} con el contenido de cada
    sección de transparencia presente en el bloque extras."""
    out: Dict[str, str] = {}
    mb = re.search(r"(?m)^\s*#\s*BORRADOR\s*$", extras)
    mc = re.search(r"(?m)^\s*#\s*CONVERSACION\s*$", extras)
    if mb:
        end = mc.start() if mc else len(extras)
        out["BORRADOR"] = extras[mb.end():end].strip()
    if mc:
        out["CONVERSACION"] = extras[mc.end():].strip()
    return out


@dataclass
class Parsed:
    meta_raw: Dict[str, str]
    sections: Dict[str, str]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_meta_and_rest(raw: str) -> Tuple[Dict[str, str], str]:
    lines = raw.splitlines()
    meta: Dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            # metadata ends at first blank line after keys block
            break
        m = META_LINE_RE.match(line)
        if not m:
            break
        k = m.group(1).strip()
        v = m.group(2)
        meta[k] = v
        i += 1

    rest = "\n".join(lines[i:])
    return meta, rest


def _extract_sections(body: str) -> Dict[str, str]:
    matches = list(HDR_RE.finditer(body))
    out: Dict[str, str] = {}
    for idx, m in enumerate(matches):
        name = m.group(1)
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        out[name] = body[start:end]
    return out


def _is_real_iso_date(s: str) -> bool:
    try:
        dt.fromisoformat(s)
        return True
    except Exception:
        return False


def parse_and_validate(date_str: str, txt_path: Path) -> Parsed:
    raw = _read(txt_path)

    meta, body = _parse_meta_and_rest(raw)

    # required meta keys exist
    for k in META_KEYS:
        if k not in meta:
            raise SystemExit(f"Falta metadato requerido: {k}:")

    # FECHA required and must match
    file_fecha = meta.get("FECHA", "").strip()
    if not file_fecha:
        raise SystemExit("FECHA: está vacío")
    if not _is_real_iso_date(file_fecha):
        raise SystemExit(f"FECHA inválida (no existe): {file_fecha}")
    if file_fecha != date_str:
        raise SystemExit(f"FECHA ({file_fecha}) no coincide con la fecha pedida ({date_str})")
    if txt_path.stem != date_str:
        raise SystemExit(f"Nombre de archivo ({txt_path.stem}) no coincide con FECHA ({date_str})")

    # Separar secciones de transparencia IA (opcionales) antes de extraer las
    # secciones obligatorias, para que # TEXTO no las absorba.
    core_body, extras = _split_extras(body)

    # Secciones de transparencia IA: cada una es INDEPENDIENTE y OPCIONAL.
    # Casos válidos: ninguna (entradas antiguas), sólo # CONVERSACION (el caso
    # normal: un link a claude.ai), sólo # BORRADOR, o ambas. Si está presente,
    # una sección no puede estar vacía; y si están las dos, CONVERSACION va
    # última (se lee verbatim hasta el final del archivo).
    if extras.strip():
        # El orden se comprueba ANTES que el vacío: si CONVERSACION va primero
        # se traga el resto del archivo (se lee verbatim) y # BORRADOR saldría
        # vacío, con un mensaje engañoso.
        mb = re.search(r"(?m)^\s*#\s*BORRADOR\s*$", extras)
        mc = re.search(r"(?m)^\s*#\s*CONVERSACION\s*$", extras)
        if mb and mc and mb.start() > mc.start():
            raise SystemExit("Orden inválido: # BORRADOR debe ir antes de # CONVERSACION")
        ex = _extract_extras(extras)
        for name in ("BORRADOR", "CONVERSACION"):
            if name in ex and not ex[name].strip():
                raise SystemExit(f"Sección vacía: # {name}")

    # sections
    sections = _extract_sections(core_body)
    for name in SECTION_ORDER:
        if name not in sections:
            raise SystemExit(f"Falta sección: # {name}")

    # order check
    positions = {name: body.find(f"# {name}") for name in SECTION_ORDER}
    if not (positions["POEMA"] != -1 and positions["POEMA_CITADO"] != -1 and positions["TEXTO"] != -1):
        raise SystemExit("Headers no encontrados (error interno)")
    if not (positions["POEMA"] < positions["POEMA_CITADO"] < positions["TEXTO"]):
        raise SystemExit("Orden inválido: debe ser # POEMA, luego # POEMA_CITADO, luego # TEXTO")

    # content non-empty (strip only whitespace/newlines)
    for name in SECTION_ORDER:
        content = sections.get(name, "")
        if not content.strip():
            raise SystemExit(f"Sección vacía: # {name}")

    return Parsed(meta_raw=meta, sections=sections)


def normalize_text(date_str: str, txt_path: Path) -> Tuple[str, bool]:
    """
    Normalize ONLY:
      - metadata lines: 'KEY: value' with single space after colon, keys in fixed order
      - ensure exactly one blank line:
          - after metadata block
          - before each header
          - after each header
    NEVER modifies section content except trimming leading/trailing blank lines of each section.
    """
    raw = _read(txt_path)
    meta, body = _parse_meta_and_rest(raw)
    core_body, extras = _split_extras(body)
    sections = _extract_sections(core_body)

    # Keep metadata values, but normalize FECHA to exact date_str
    meta2 = {k: meta.get(k, "") for k in META_KEYS}
    meta2["FECHA"] = date_str

    # Normalize metadata lines
    meta_lines = [f"{k}: {meta2.get(k,'').strip()}" for k in META_KEYS]
    # IMPORTANT: allow empty optional values (prints "KEY: ")
    meta_block = "\n".join(meta_lines).rstrip()

    def clean_section(s: str) -> str:
        # trim only outer whitespace lines; keep internal formatting untouched
        return s.strip("\n").rstrip()  # keep internal newlines/spaces

    poema = clean_section(sections["POEMA"])
    citado = clean_section(sections["POEMA_CITADO"])
    texto = clean_section(sections["TEXTO"])

    parts = []
    parts.append(meta_block)
    parts.append("")  # one blank line after metadata

    def add_section(name: str, content: str):
        # one blank line before header is already ensured by join logic
        parts.append(f"# {name}")
        parts.append("")  # one blank line after header
        parts.append(content)

    add_section("POEMA", poema)
    parts.append("")  # one blank line between sections
    add_section("POEMA_CITADO", citado)
    parts.append("")
    add_section("TEXTO", texto)

    # Secciones de transparencia IA: se anexan VERBATIM (solo se recortan
    # blank lines exteriores), separadas por una línea en blanco.
    extras_clean = extras.strip("\n").rstrip()
    if extras_clean:
        parts.append("")
        parts.append(extras_clean)

    normalized = "\n".join(parts).rstrip() + "\n"
    changed = (normalized != raw)
    return normalized, changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["validate", "normalize"], required=True)
    ap.add_argument("date", help="YYYY-MM-DD")
    ap.add_argument("txt_path", help="textos/YYYY-MM-DD.txt")
    args = ap.parse_args()

    date_str = args.date.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        raise SystemExit(f"Fecha inválida: {date_str} (usa YYYY-MM-DD)")
    if not _is_real_iso_date(date_str):
        raise SystemExit(f"Fecha inválida (no existe): {date_str}")

    txt_path = Path(args.txt_path)
    if not txt_path.exists():
        raise SystemExit(f"No existe: {txt_path}")

    # validate always first
    parse_and_validate(date_str, txt_path)

    if args.mode == "validate":
        print(json.dumps({"ok": True}, ensure_ascii=False))
        return 0

    normalized, changed = normalize_text(date_str, txt_path)
    payload = {"ok": True, "changed_formatting": changed, "normalized_text": normalized}
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
