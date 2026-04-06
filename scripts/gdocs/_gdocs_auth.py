from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict

from google.auth.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


SCOPES = ["https://www.googleapis.com/auth/documents.readonly"]

CLIENT_SECRETS = Path("~/.config/qmp/google_oauth_client.json").expanduser()
TOKEN_PATH = Path("~/.config/qmp/google_token.json").expanduser()
CONFIG_PATH = Path("~/.config/qmp/gdocs.json").expanduser()

def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"No encuentro config: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def get_creds() -> Credentials:
    sa_keyfile = os.environ.get("QMP_GDOCS_SA_KEYFILE")
    if sa_keyfile:
        key_path = Path(sa_keyfile).expanduser()
        if not key_path.exists():
            raise FileNotFoundError(f"No encuentro service account keyfile: {key_path}")
        return service_account.Credentials.from_service_account_file(
            str(key_path),
            scopes=SCOPES,
        )

    if not CLIENT_SECRETS.exists():
        raise FileNotFoundError(f"No encuentro OAuth client JSON: {CLIENT_SECRETS}")

    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return creds