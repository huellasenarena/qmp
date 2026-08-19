#!/usr/bin/env python3
"""
ia_sections.py — Extrae las secciones de transparencia IA del texto de análisis.

Flujo: el autor escribe en iA Writer y, DESPUÉS de su análisis (la "Versión
final"), añade dos marcadores que viajan como texto plano por todo el pipeline
(Atajo → Apps Script → Google Docs → pull), sin que nada los interprete:

    <análisis publicado…>

    ## Borrador final
    <mi versión antes de las correcciones>

    ## Conversación con IA
    https://claude.ai/share/xxxxxxxx

split_ia_markers() recibe el texto de análisis tal cual lo devuelve el pull y lo
parte en (texto_limpio, borrador, conversacion). Si no hay marcadores, devuelve
el texto intacto y dos cadenas vacías.
"""
from __future__ import annotations

import re
from typing import Tuple

# Marcadores tolerantes: 1-3 '#', acentos y sufijos opcionales, sin importar
# mayúsculas. Aceptan tanto "## Borrador final" como "# Borrador", etc.
BORRADOR_MARK = re.compile(r"^\s*#{1,3}\s*borrador(\s+final)?\s*$", re.IGNORECASE)
CONV_MARK = re.compile(r"^\s*#{1,3}\s*conversaci[oó]n(\s+con\s+ia)?\s*$", re.IGNORECASE)


def split_ia_markers(texto: str) -> Tuple[str, str, str]:
    """Devuelve (texto_limpio, borrador, conversacion).

    - texto_limpio: el análisis publicado (todo lo previo al primer marcador).
    - borrador: contenido entre '## Borrador final' y '## Conversación con IA'.
    - conversacion: contenido tras '## Conversación con IA' (normalmente un link).

    Si falta algún marcador, su sección sale vacía; validate_entry.py se encarga
    de exigir que sea todo-o-nada.
    """
    lines = (texto or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")

    bi = None
    ci = None
    for i, ln in enumerate(lines):
        if bi is None and BORRADOR_MARK.match(ln):
            bi = i
        elif ci is None and CONV_MARK.match(ln):
            ci = i

    if bi is None and ci is None:
        return (texto or "").strip(), "", ""

    marker_idxs = [x for x in (bi, ci) if x is not None]
    first = min(marker_idxs)
    clean = "\n".join(lines[:first]).strip()

    borrador = ""
    if bi is not None:
        end = ci if (ci is not None and ci > bi) else len(lines)
        borrador = "\n".join(lines[bi + 1:end]).strip()

    conversacion = ""
    if ci is not None:
        conversacion = "\n".join(lines[ci + 1:]).strip()

    return clean, borrador, conversacion
