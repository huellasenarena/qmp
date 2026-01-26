#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -r requirements.txt

# ------------------------------------------------------------
# Codespaces: materializar Google config desde env vars (secrets)
# No toca nada en local si esas vars no existen.
# ------------------------------------------------------------
if [ -n "${CODESPACES:-}" ] || [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
  if [ -n "${GDOCS_JSON:-}" ] && [ -n "${GOOGLE_OAUTH_CLIENT_JSON:-}" ] && [ -n "${GOOGLE_TOKEN_JSON:-}" ]; then
    mkdir -p ~/.config/qmp
    chmod 700 ~/.config/qmp

    python3 - <<'PY'
import os, pathlib
out = pathlib.Path.home()/".config"/"qmp"
pairs = {
  "gdocs.json": "GDOCS_JSON",
  "google_oauth_client.json": "GOOGLE_OAUTH_CLIENT_JSON",
  "google_token.json": "GOOGLE_TOKEN_JSON",
}
for fname, env in pairs.items():
    (out/fname).write_text(os.environ[env])
print("[bootstrap] wrote Google config to", out)
PY

    chmod 600 ~/.config/qmp/*.json
  else
    echo "[bootstrap] codespaces: env vars missing; skipping Google config"
  fi
fi

echo "[bootstrap] OK"
