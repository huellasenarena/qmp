#!/usr/bin/env bash
set -euo pipefail

# Python resolver (portable: Codespaces + macOS)
PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
  else
    echo "[q] No encuentro python/python3 en PATH" >&2
    exit 1
  fi
fi


DRY=0
APPLY_KW=0
DATE=""

for arg in "$@"; do
  case "$arg" in
    --dry-run|--dry|-n) DRY=1 ;;
    --kw) APPLY_KW=1 ;;
    *)
      # aceptar fecha o path que contenga YYYY-MM-DD
      if [[ -z "${DATE}" ]]; then
        if [[ "$arg" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
          DATE="$arg"
        elif [[ "$arg" =~ ([0-9]{4}-[0-9]{2}-[0-9]{2})\.txt$ ]]; then
          DATE="${BASH_REMATCH[1]}"
        elif [[ "$arg" =~ ([0-9]{4}-[0-9]{2}-[0-9]{2})$ ]]; then
          DATE="${BASH_REMATCH[1]}"
        else
          # si no matchea nada, lo ignoramos (para tolerar wrappers raros)
          :
        fi
      fi
      ;;
  esac
done

if [[ -z "${DATE}" ]]; then
  echo "Uso: q [--kw] [--dry-run] YYYY-MM-DD" >&2
  exit 1
fi
if ! [[ "${DATE}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "[q] Fecha inválida: ${DATE} (usa YYYY-MM-DD)" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO"

TXT="textos/${DATE}.txt"
ARCHIVO="archivo.json"
PENDING_KW="scripts/pending_keywords.txt"

if [[ ! -f "$TXT" ]]; then
  echo "[q] No encuentro ${TXT}. (Usa qd primero)" >&2
  exit 1
fi
if [[ ! -f "$ARCHIVO" ]]; then
  echo "[q] No encuentro ${ARCHIVO}" >&2
  exit 1
fi

OUT_JSON="$("$PYTHON" - "$DATE" "$TXT" "$ARCHIVO" "$PENDING_KW" "$APPLY_KW" <<'PY'

import json, sys, re
from pathlib import Path

date = sys.argv[1]
txt_path = Path(sys.argv[2])
archivo_path = Path(sys.argv[3])
pending_kw_path = Path(sys.argv[4])
apply_kw = int(sys.argv[5]) == 1

def load_entries(p: Path):
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        return data["entries"]
    raise SystemExit("archivo.json debe ser array root (o compat: {entries:[...]})")

def dump_entries(entries):
    return json.dumps(entries, ensure_ascii=False, indent=2) + "\n"

def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s
    return ""

def first_n_words(text: str, n: int) -> str:
    w = re.findall(r"\S+", text.strip())
    return " ".join(w[:n])

def shortest_snippet_rule(text: str) -> str:
    # 6 palabras vs primera línea (lo más corto)
    a = first_n_words(text, 6)
    b = first_nonempty_line(text)
    if not a and not b:
        return ""
    if not a:
        return b
    if not b:
        return a
    wa = len(re.findall(r"\S+", a))
    wb = len(re.findall(r"\S+", b))
    if wa != wb:
        return a if wa < wb else b
    return a if len(a) <= len(b) else b


def split_sections(raw: str):
    # Captura # POEMA / # POEMA_CITADO / # TEXTO y también deja "prefacio" (metadatos libres) antes del primer header
    sec = {"_PREFACE":"", "POEMA":"", "POEMA_CITADO":"", "TEXTO":""}
    current = "_PREFACE"
    out_lines = []
    def flush(name):
        sec[name] = "\n".join(out_lines).strip("\n")

    for line in raw.splitlines():
        m = re.match(r"^\s*#\s*(POEMA_CITADO|POEMA|TEXTO)\s*$", line.strip())
        if m:
            flush(current)
            out_lines[:] = []
            current = m.group(1)
            continue
        out_lines.append(line)
    flush(current)
    return sec

def parse_metadata(preface: str):
    """
    Metadatos: buscamos claves tipo:
      titulo: ...
      title: ...
      my_poem_title: ...
      poet: ...
      poema_citado_titulo: ... (tolerante)
      poem_title: ...
      book_title: ...
    Soporta 'clave: valor' al inicio del archivo (antes de # POEMA).
    """
    meta = {}
    for line in preface.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip().lower()
        v = v.strip()
        if not v:
            continue
        # normalizaciones útiles
        if k in ("titulo", "título", "title", "my_poem_title"):
            meta["my_poem_title"] = v
        elif k in ("poeta", "poet"):
            meta["poet"] = v
        elif k in ("poema_citado", "poema citado", "poem_title", "poem title", "titulo_poema_citado", "título_poema_citado"):
            meta["analysis_poem_title"] = v
        elif k in ("libro", "book", "book_title", "book title", "titulo_libro", "título_libro"):
            meta["book_title"] = v
    return meta

raw = txt_path.read_text(encoding="utf-8")
sections = split_sections(raw)
meta = parse_metadata(sections.get("_PREFACE",""))

my_body = sections.get("POEMA","").strip("\n")
cited_body = sections.get("POEMA_CITADO","").strip("\n")

my_title = meta.get("my_poem_title","") or ""
my_snippet = "" if my_title else shortest_snippet_rule(my_body)


analysis_poet = meta.get("poet","") or ""
analysis_poem_title = meta.get("analysis_poem_title","") or ""
analysis_book_title = meta.get("book_title","") or ""

# snippet de citado sólo si NO hay título (y nunca se usa para el commit)
cited_snippet = "" if analysis_poem_title else words_snippet(cited_body, 15)

month = date[:7]
entry_base = {
  "date": date,
  "month": month,
  "file": f"textos/{date}.txt",
  "my_poem_title": my_title,
  "my_poem_snippet": my_snippet,
  "analysis": {
    "poet": analysis_poet,
    "poem_title": analysis_poem_title,
    "poem_snippet": cited_snippet,
    "book_title": analysis_book_title
  },
  "keywords": []
}

entries = load_entries(archivo_path)
existing = next((e for e in entries if isinstance(e, dict) and e.get("date")==date), None)
is_new = existing is None

old_keywords = []
if existing and isinstance(existing.get("keywords"), list):
    old_keywords = existing["keywords"]

kw_changed = False
new_keywords = old_keywords[:]  # por defecto: NO tocar

if apply_kw:
    if not pending_kw_path.exists():
        raise SystemExit("pending_keywords.txt no existe")
    pending = json.loads(pending_kw_path.read_text(encoding="utf-8"))
    kws = pending.get("keywords") if isinstance(pending, dict) else None
    if not isinstance(kws, list) or len(kws) == 0:
        raise SystemExit("pending_keywords.txt está vacío: aborta")
    new_keywords = kws
    kw_changed = (new_keywords != old_keywords)

# regla: q (sin --kw) no puede crear entrada sin keywords existentes
if (not apply_kw) and is_new and len(old_keywords)==0:
    raise SystemExit("Entrada nueva sin keywords existentes: usa q --kw (o genera keywords primero)")

entry = entry_base
entry["keywords"] = new_keywords

def strip_kw(e):
    if not isinstance(e, dict): return None
    e2 = json.loads(json.dumps(e, ensure_ascii=False))
    e2["keywords"] = []
    return e2

meta_changed = True
if existing:
    meta_changed = (strip_kw(existing) != strip_kw(entry))

# Reemplazar entrada y ordenar
new_entries = [e for e in entries if not (isinstance(e, dict) and e.get("date")==date)]
new_entries.append(entry)
new_entries.sort(key=lambda e: (e.get("date","") if isinstance(e, dict) else ""), reverse=True)

new_json = dump_entries(new_entries)
old_json = dump_entries(entries)

if new_json != old_json:
    archivo_path.write_text(new_json, encoding="utf-8")

title_or_snip = entry.get("my_poem_title") or entry.get("my_poem_snippet") or ""

commit_type = ""
if is_new:
    commit_type = "entrada"
else:
    if apply_kw:
        if kw_changed and meta_changed:
            commit_type = "edicion texto + keywords"
        elif kw_changed and (not meta_changed):
            commit_type = "edicion de palabras clave"
        else:
            commit_type = ""
    else:
        if meta_changed:
            commit_type = "edicion de metadatos/escritos"
        else:
            commit_type = ""

print(json.dumps({
  "is_new": is_new,
  "meta_changed": meta_changed,
  "kw_changed": kw_changed,
  "commit_type": commit_type,
  "title_or_snip": title_or_snip,
}, ensure_ascii=False))
PY
)"

COMMIT_TYPE="$("$PYTHON" -c 'import json,sys; print(json.loads(sys.stdin.read()).get("commit_type",""))' <<<"$OUT_JSON")"
TITLE_OR_SNIP="$("$PYTHON" -c 'import json,sys; print(json.loads(sys.stdin.read()).get("title_or_snip",""))' <<<"$OUT_JSON")"

MSG_BASE="${DATE} — ${TITLE_OR_SNIP}"

# stage SOLO publicado (nunca pending)
git add "$ARCHIVO" "$TXT"

# si no hay nada staged, no hay commit (verdadero de verdad)
if git diff --cached --quiet; then
  echo "ℹ️  No cambió texto ni keywords → no hay commit."
  exit 0
fi

# detectar si cambió el txt (texto) además de keywords
STAGED_NAMES="$(git diff --cached --name-only || true)"
TXT_CHANGED=0
if echo "$STAGED_NAMES" | grep -qx "$TXT"; then
  TXT_CHANGED=1
fi

# decidir tipo commit según contrato
if [[ "$COMMIT_TYPE" == "entrada" ]]; then
  FINAL_TYPE="entrada"
else
  if [[ "$APPLY_KW" -eq 1 ]]; then
    if [[ "$TXT_CHANGED" -eq 1 ]]; then
      FINAL_TYPE="edicion texto + keywords"
    else
      FINAL_TYPE="edicion de palabras clave"
    fi
  else
    FINAL_TYPE="edicion de metadatos/escritos"
  fi
fi

MSG="${FINAL_TYPE} ${MSG_BASE}"


if [[ "$DRY" -eq 1 ]]; then
  echo "[DRY RUN] Commit: $MSG"
  git diff --cached
  exit 0
fi

git commit -m "$MSG"
git push
echo "✅ Publicado: $MSG"
