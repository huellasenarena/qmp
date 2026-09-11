#!/usr/bin/env python3
"""
ia_sections.py — Extrae las secciones de transparencia IA del texto de análisis.

Flujo: el autor escribe en iA Writer y, DESPUÉS de su análisis (la "Versión
final"), añade dos marcadores que viajan como texto plano por todo el pipeline
(Atajo → Apps Script → Google Docs → pull), sin que nada los interprete:

    <análisis publicado…>

    ## Borrador final
    <mi versión antes de las correcciones>

    ## Gusto
    3

    ## Conversación con IA
    https://claude.ai/share/xxxxxxxx

split_ia_markers() recibe el texto de análisis tal cual lo devuelve el pull y lo
parte en (texto_limpio, borrador, gusto, conversacion). Si no hay marcadores,
devuelve el texto intacto y las secciones vacías.

El orden de los marcadores en el original da igual: cada uno se corta hasta el
siguiente que aparezca. Al escribir el .txt siempre salen en el orden canónico
(BORRADOR, GUSTO, CONVERSACION), que es el que exige validate_entry.py.
"""
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

# Marcadores tolerantes: 1-3 '#', acentos y sufijos opcionales, sin importar
# mayúsculas. Aceptan tanto "## Borrador final" como "# Borrador", etc.
BORRADOR_MARK = re.compile(r"^\s*#{1,3}\s*borrador(\s+final)?\s*$", re.IGNORECASE)
CONV_MARK = re.compile(r"^\s*#{1,3}\s*conversaci[oó]n(\s+con\s+ia)?\s*$", re.IGNORECASE)
GUSTO_MARK = re.compile(r"^\s*#{1,3}\s*gusto\s*$", re.IGNORECASE)

# Orden en que se escriben al .txt, pase lo que pase en el original.
ORDEN_CANONICO = ("BORRADOR", "GUSTO", "CONVERSACION")


def split_ia_markers(texto: str) -> Tuple[str, str, Optional[str], str]:
    """Devuelve (texto_limpio, borrador, gusto, conversacion).

    - texto_limpio: el análisis publicado (todo lo previo al primer marcador).
    - borrador: la versión del autor antes de las correcciones.
    - gusto: la nota del poema citado. Es None cuando el marcador NO aparece, y
      una cadena (posiblemente vacía) cuando aparece: hay que distinguirlos
      porque la sección se escribe en el .txt aunque venga vacía — los días sin
      poema en texto llevan '# GUSTO' sin nada dentro.
    - conversacion: normalmente un link a claude.ai.

    Cada sección llega hasta el siguiente marcador que aparezca, así que da
    igual en qué orden los haya escrito el autor.
    """
    lines = (texto or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # Primera aparición de cada marcador
    encontrados: Dict[str, int] = {}
    for i, ln in enumerate(lines):
        if "BORRADOR" not in encontrados and BORRADOR_MARK.match(ln):
            encontrados["BORRADOR"] = i
        elif "GUSTO" not in encontrados and GUSTO_MARK.match(ln):
            encontrados["GUSTO"] = i
        elif "CONVERSACION" not in encontrados and CONV_MARK.match(ln):
            encontrados["CONVERSACION"] = i

    if not encontrados:
        return (texto or "").strip(), "", None, ""

    # Por posición en el texto, no por el orden canónico
    por_posicion = sorted(encontrados.items(), key=lambda kv: kv[1])
    clean = "\n".join(lines[: por_posicion[0][1]]).strip()

    trozos: Dict[str, str] = {}
    for n, (nombre, i) in enumerate(por_posicion):
        fin = por_posicion[n + 1][1] if n + 1 < len(por_posicion) else len(lines)
        trozos[nombre] = "\n".join(lines[i + 1:fin]).strip()

    return (
        clean,
        trozos.get("BORRADOR", ""),
        trozos.get("GUSTO"),          # None si el marcador no estaba
        trozos.get("CONVERSACION", ""),
    )
