#!/usr/bin/env bash
set -e

mkdir -p ~/.config/qmp
chmod 700 ~/.config/qmp

echo "$GDOCS_JSON" > ~/.config/qmp/gdocs.json
echo "$GOOGLE_OAUTH_CLIENT_JSON" > ~/.config/qmp/google_oauth_client.json
echo "$GOOGLE_TOKEN_JSON" > ~/.config/qmp/google_token.json

chmod 600 ~/.config/qmp/*.json

echo "✅ Configuración de Google Docs lista"
