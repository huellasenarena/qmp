#!/usr/bin/env bash
set -euo pipefail

# qcrear.sh — wrapper para qcrear.py
# Uso:
#   ./scripts/qcrear.sh [YYYY-MM-DD]

# Ir a la raíz del repo (asumiendo que este script vive en scripts/)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

cd "$REPO_ROOT"

# Preferir QMP_REPO si existe y es consistente
if [[ -n "${QMP_REPO:-}" ]]; then
  # Normalizar path
  QMP_REPO_ABS="$(cd -- "$QMP_REPO" >/dev/null 2>&1 && pwd || true)"
  if [[ -n "$QMP_REPO_ABS" && "$QMP_REPO_ABS" != "$REPO_ROOT" ]]; then
    echo "[qcrear] WARN: QMP_REPO=$QMP_REPO_ABS no coincide con repo actual: $REPO_ROOT"
    echo "[qcrear]       Continuo usando el repo actual."
  fi
fi

# Activar venv si existe
if [[ -f ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
else
  # fallback: python3 del sistema (scaffold). Más adelante haremos esto hard-fail si quieres.
  PY="$(command -v python3 || true)"
  if [[ -z "$PY" ]]; then
    echo "[qcrear] ERROR: No encuentro python3 ni .venv/bin/python"
    exit 1
  fi
fi

exec "$PY" "scripts/qcrear.py" "$@"
