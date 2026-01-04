#!/usr/bin/env bash
set -euo pipefail

DATE="${1:-}"
if [[ -z "$DATE" ]]; then
  echo "Uso: qd YYYY-MM-DD" >&2
  exit 1
fi
if ! [[ "$DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "[qd] Fecha inválida: $DATE (usa YYYY-MM-DD)" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"

TXT="$REPO/textos/${DATE}.txt"
TEMPLATE="$REPO/textos/templateTEXT.txt"
ARCHIVO="$REPO/archivo.json"
PENDING="$REPO/scripts/pending_keywords.txt"
PULL="$REPO/scripts/pull_keywords.py"

# crear txt si no existe
if [[ ! -f "$TXT" ]]; then
  if [[ ! -f "$TEMPLATE" ]]; then
    echo "[qd] No encuentro template: $TEMPLATE" >&2
    exit 1
  fi
  cp "$TEMPLATE" "$TXT"
fi

# restaurar pending_keywords.txt desde archivo.json SI la entrada existe
# (sin jq: archivo.json puede ser array root o {entries:[...]})
if [[ -f "$ARCHIVO" && -f "$PULL" ]]; then
  # si no existe la entrada, pull_keywords.py falla y qd sigue (NO toca pending)
  python3 "$PULL" "$DATE" "$PENDING" >/dev/null 2>&1 || true
fi

# elegir editor
if [[ -n "${EDITOR_CMD:-}" ]]; then
  CMD=("$EDITOR_CMD")
elif [[ -n "${EDITOR:-}" ]]; then
  CMD=("$EDITOR")
elif command -v subl >/dev/null 2>&1; then
  CMD=(subl)
elif command -v code >/dev/null 2>&1; then
  CMD=(code)
else
  echo "[qd] No encuentro editor. Define EDITOR_CMD o EDITOR." >&2
  exit 1
fi

# abrir archivos (orden: txt primero)
if [[ "${CMD[0]}" == "subl" ]]; then
  "${CMD[@]}" -a "$TXT" "$PENDING" "$ARCHIVO"
elif [[ "${CMD[0]}" == "code" ]]; then
  "${CMD[@]}" -r "$TXT" "$PENDING" "$ARCHIVO"
else
  "${CMD[@]}" "$TXT" "$PENDING" "$ARCHIVO"
fi
