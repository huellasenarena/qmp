#!/usr/bin/env bash
set -euo pipefail

# Quick daily setup:
# - create textos/YYYY-MM-DD.txt from template if missing
# - open that txt + scripts/pending_keywords.txt in your editor

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

DATE="${1:-$(date +%F)}"
TXT="textos/${DATE}.txt"
TEMPLATE="textos/templateTEXT.txt"
KW="scripts/pending_keywords.txt"

# Create daily txt if missing
if [[ ! -f "$TXT" ]]; then
  if [[ ! -f "$TEMPLATE" ]]; then
    echo "Error: no encuentro plantilla $TEMPLATE"
    exit 1
  fi
  cp "$TEMPLATE" "$TXT"
  echo "OK: creado $TXT desde plantilla"
else
  echo "OK: ya existe $TXT"
fi

# Ensure keywords file exists (don’t overwrite)
if [[ ! -f "$KW" ]]; then
  : > "$KW"
  echo "OK: creado $KW"
fi

# Choose editor command:
# Sublime: "subl"
# VS Code: "code"
EDITOR_CMD="${EDITOR_CMD:-subl}"

FILES=("$TXT" "$KW")

EXISTS="$(python3 - "$DATE" <<'PY'
import json, sys
date = sys.argv[1]
try:
    data = json.load(open("archivo.json", "r", encoding="utf-8"))
    print("1" if any(e.get("date") == date for e in data) else "0")
except Exception:
    print("0")
PY
)"

if [[ "$EXISTS" == "1" ]]; then
  FILES+=("archivo.json")
fi


"$EDITOR_CMD" "${FILES[@]}"

