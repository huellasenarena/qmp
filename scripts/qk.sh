#!/usr/bin/env bash
set -euo pipefail

DATE="${1:-$(date +%F)}"

if ! [[ "${DATE}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "[qk] Fecha inválida: ${DATE} (usa YYYY-MM-DD)" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

IN_FILE="${ROOT_DIR}/textos/${DATE}.txt"
OUT_FILE="${ROOT_DIR}/scripts/pending_keywords.txt"
PY_SCRIPT="${ROOT_DIR}/scripts/gen_keywords.py"

BACKUP_DIR="${ROOT_DIR}/scripts/keywords_backups"
BACKUP_PATH="${BACKUP_DIR}/${DATE}.json"

if [[ ! -f "${IN_FILE}" ]]; then
  echo "[qk] No existe: ${IN_FILE}" >&2
  exit 1
fi

if [[ ! -f "${PY_SCRIPT}" ]]; then
  echo "[qk] No existe: ${PY_SCRIPT}" >&2
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "[qk] Falta OPENAI_API_KEY en el entorno." >&2
  echo "     Ejemplo: export OPENAI_API_KEY='...'" >&2
  exit 1
fi

python3 "${PY_SCRIPT}" "${IN_FILE}" "${OUT_FILE}"

mkdir -p "${BACKUP_DIR}"
cp "${OUT_FILE}" "${BACKUP_PATH}"

echo "[qk] Revisa/edita: ${OUT_FILE}"
echo "[qk] Backup: ${BACKUP_PATH}"
