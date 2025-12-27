#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   scripts/qmp_publish.sh [--dry-run|--dry|-n] textos/YYYY-MM-DD.txt ["mensaje commit opcional"]

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "--dry" || "${1:-}" == "-n" ]]; then
  DRY_RUN=1
  shift
fi

TXT_PATH="${1:-}"
COMMIT_MSG="${2:-}"

# Repo root basado en la ubicación del script (funciona desde cualquier directorio)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Validación: debe existir .git
if [[ ! -d ".git" ]]; then
  echo "Error: $REPO_ROOT no parece ser un repo git (no hay .git)."
  exit 1
fi


if [[ -z "$TXT_PATH" ]]; then
  echo "Uso: scripts/qmp_publish.sh [--dry-run] textos/YYYY-MM-DD.txt \"Mensaje opcional\""
  exit 2
fi

if [[ ! -f "$TXT_PATH" ]]; then
  echo "Error: no existe $TXT_PATH"
  exit 1
fi

[[ -f "archivo.json" ]] || { echo "Error: falta archivo.json en el root del repo"; exit 1; }
[[ -f "scripts/make_pending_entry.py" ]] || { echo "Error: falta scripts/make_pending_entry.py"; exit 1; }
[[ -f "scripts/merge_pending.py" ]] || { echo "Error: falta scripts/merge_pending.py"; exit 1; }
[[ -f "scripts/pending_keywords.txt" ]] || { echo "Error: falta scripts/pending_keywords.txt"; exit 1; }

if ! grep -qE '^\s*#\s*TEXTO\s*$' "$TXT_PATH"; then
  echo "Error: $TXT_PATH no contiene el header '# TEXTO'."
  exit 1
fi

echo "→ Generando pending_entry.json desde $TXT_PATH"
python3 scripts/make_pending_entry.py "$TXT_PATH"

[[ -f "scripts/pending_entry.json" ]] || { echo "Error: no se generó scripts/pending_entry.json"; exit 1; }

ENTRY_DATE="$(python3 - <<'PY'
import json
d=json.load(open("scripts/pending_entry.json","r",encoding="utf-8"))
print((d.get("date") or "").strip())
PY
)"
if [[ -z "$ENTRY_DATE" ]]; then
  echo "Error: pending_entry.json no tiene 'date'."
  exit 1
fi

EXISTS="$(python3 - "$ENTRY_DATE" <<'PY'
import json, sys
entry_date = sys.argv[1]
d = json.load(open("archivo.json","r",encoding="utf-8"))
print("1" if any(e.get("date")==entry_date for e in d) else "0")
PY
)"

OVERWRITE=0
if [[ "$EXISTS" == "1" ]]; then
  echo "⚠️  Ya existe una entrada con date=$ENTRY_DATE en archivo.json."
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY RUN: no sobreescribo automáticamente."
    OVERWRITE=0
    echo "DRY RUN: paro aquí (no corro merge_pending.py) porque el merge fallaría por entrada duplicada."
    echo "Tip: para probar el merge en dry-run, usa una fecha nueva, o corre en modo real y elige overwrite."
    exit 0

  else
    read -r -p "¿Quieres sobreescribir esa entrada? (y/N) " ans
    if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
      OVERWRITE=1
    else
      echo "Ok, no hago nada."
      exit 0
    fi
  fi
fi

if [[ "$OVERWRITE" == "1" ]]; then
  echo "→ Eliminando entrada existente date=$ENTRY_DATE (overwrite)"
  python3 - "$ENTRY_DATE" <<'PY'
import json, sys
entry_date=sys.argv[1]
p="archivo.json"
d=json.load(open(p,"r",encoding="utf-8"))
d=[e for e in d if e.get("date")!=entry_date]
open(p,"w",encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
PY
fi

echo "→ Merge keywords + append a archivo.json"
python3 scripts/merge_pending.py

echo "→ Validando JSON..."
python3 -m json.tool archivo.json >/dev/null

KW_COUNT="$(python3 - <<'PY'
import json
d=json.load(open("scripts/pending_entry.json","r",encoding="utf-8"))
print(len(d.get("keywords",[]) or []))
PY
)"
if [[ "$KW_COUNT" -lt 10 ]]; then
  echo "Error: keywords muy pocas (${KW_COUNT}). No hago commit/push."
  exit 1
fi

if [[ -z "$COMMIT_MSG" ]]; then
  TITLE="$(python3 - <<'PY'
import json
try:
    d=json.load(open("scripts/pending_entry.json","r",encoding="utf-8"))
    t=(d.get("my_poem_title") or "").strip()
    if not t:
        t=(d.get("my_poem_snippet") or "").strip()
    t=" ".join(t.split())
    print(t)
except Exception:
    print("")
PY
)"
  TITLE="${TITLE:0:80}"
  if [[ -n "$TITLE" ]]; then
    COMMIT_MSG="Entrada ${ENTRY_DATE} — ${TITLE}"
  else
    COMMIT_MSG="Entrada ${ENTRY_DATE}"
  fi
fi

echo "→ Git status"
git status --porcelain || true

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY RUN: no hago commit ni push."
  echo "Mensaje commit sería: $COMMIT_MSG"
  exit 0
fi

if [[ -z "$(git status --porcelain)" ]]; then
  echo "No hay cambios para commitear. Salgo."
  exit 0
fi

echo "→ Git add/commit/push"
git add archivo.json "$TXT_PATH" scripts/pending_entry.json scripts/pending_keywords.txt || true
git commit -m "$COMMIT_MSG"
git push

echo "✅ Listo: publicado."
