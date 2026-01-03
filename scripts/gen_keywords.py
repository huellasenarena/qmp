#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
import sys
import unicodedata
from openai import OpenAI

DEFAULT_INPUT_FILE = "test_file.txt"
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
MAX_KEYWORDS = 30

INSTRUCTIONS = """
Genera keywords (max 30) para una entrada con tres bloques: POEMA, POEMA_CITADO y TEXTO.

Prioridad semántica:
- POEMA manda (núcleo soberano, aunque sea breve).
- POEMA_CITADO = resonancia.
- TEXTO = lente; NO puede imponer conceptos que no estén ya en el POEMA (directa o metafóricamente).

Formato: SOLO este JSON
{"keywords":[{"word":"...","weight":3},{"word":"...","weight":2},{"word":"...","weight":1}]}

Reglas:
- minúsculas; sin acentos.
- NO snake_case, NO underscores; usa palabras o frases con espacios.
- evita genéricos tipo: poema, metafora, tema, texto.
- weight 3: núcleo conceptual (anclado en POEMA)
- weight 2: dinámicas, procesos, tensiones
- weight 1: campo semántico, figuras concretas
- coherencia con corpus: cuerpo, poder, violencia, animalidad, lenguaje, identidad, norma, deseo, incertidumbre.
""".strip()

KEYWORDS_SCHEMA = {
    "name": "keywords_schema",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "keywords": {
                "type": "array",
                "minItems": 16,
                "maxItems": MAX_KEYWORDS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "word": {"type": "string", "minLength": 1, "maxLength": 80},
                        "weight": {"type": "integer", "enum": [1, 2, 3]},
                    },
                    "required": ["word", "weight"],
                },
            }
        },
        "required": ["keywords"],
    },
}

def strip_leading_metadata(raw: str) -> str:
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s == "":
            i += 1
            continue
        if s.startswith("#"):
            break
        if ":" in s:
            key = s.split(":", 1)[0].strip()
            if key and key.replace("_", "").isupper():
                i += 1
                continue
        break
    return "\n".join(lines[i:]).lstrip("\n")

def strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))

def normalize_word(w: str) -> str:
    w = " ".join(w.strip().lower().split())
    w = w.replace("_", " ")
    w = strip_accents(w)
    w = re.sub(r"[.,;:]+$", "", w).strip()
    return w

def extract_output_text(resp) -> str:
    """
    Prefer resp.output_text (SDK helper). Fallback to traversing resp.output blocks.
    """
    ot = getattr(resp, "output_text", None)
    if isinstance(ot, str) and ot.strip():
        return ot.strip()

    parts = []
    output = getattr(resp, "output", None)
    if output:
        for item in output:
            content = getattr(item, "content", None)
            if not content:
                continue
            for c in content:
                # different SDK versions name these slightly differently
                ctype = getattr(c, "type", None)
                text = getattr(c, "text", None)
                if isinstance(text, str) and text.strip():
                    parts.append(text)
    return "\n".join(parts).strip()

def print_usage(resp):
    u = getattr(resp, "usage", None)
    if not u:
        return
    msg = (
        f"input_tokens={getattr(u,'input_tokens',None)} "
        f"output_tokens={getattr(u,'output_tokens',None)} "
        f"total_tokens={getattr(u,'total_tokens',None)}"
    )
    details = getattr(u, "input_tokens_details", None)
    if details and hasattr(details, "cached_tokens"):
        msg += f" cached_tokens={details.cached_tokens}"
    print(msg, file=sys.stderr)

def main() -> int:
    in_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INPUT_FILE
    out_path = sys.argv[2] if len(sys.argv) > 2 else None

    with open(in_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    text = strip_leading_metadata(raw_text).strip()

    client = OpenAI()
    resp = client.responses.create(
        model=DEFAULT_MODEL,
        reasoning={"effort": "low"},
        max_output_tokens=1000,
        input=[
            {"role": "system", "content": "Responde SOLO con JSON válido según el schema. Sin explicaciones."},
            {"role": "user", "content": INSTRUCTIONS + "\n\n---\n\nTEXTO COMPLETO:\n" + text},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": KEYWORDS_SCHEMA["name"],
                "schema": KEYWORDS_SCHEMA["schema"],
                "strict": True,
            }
        },
    )

    print_usage(resp)

    out_text = extract_output_text(resp)
    if not out_text:
        # Debug minimal: show what the API returned structurally
        print("ERROR: respuesta sin texto. Dump de resp.output (resumido):", file=sys.stderr)
        try:
            print(json.dumps(resp.model_dump(), ensure_ascii=False)[:2000], file=sys.stderr)
        except Exception:
            print(str(resp)[:2000], file=sys.stderr)
        return 1

    try:
        data = json.loads(out_text)
    except json.JSONDecodeError:
        print("ERROR: el modelo no devolvió JSON válido. Primera parte del output:", file=sys.stderr)
        print(out_text[:400], file=sys.stderr)
        return 1

    # normalize + dedupe
    seen = set()
    cleaned = []
    for kw in data["keywords"]:
        word = normalize_word(kw["word"])
        if not word or word in seen:
            continue
        seen.add(word)
        cleaned.append({"word": word, "weight": int(kw["weight"])})

    out = {"keywords": cleaned[:MAX_KEYWORDS]}

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
