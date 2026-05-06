"""Per-channel YouTube OAuth — token persistence + refresh.

Each channel has its own Google Cloud project. Files live under
``data/youtube_credentials/<slug>/``:
  - client_secrets.json   (user-provided, OAuth client config)
  - token.json            (auto-managed, access + refresh token)
  - channel_info.json     (auto-managed, snapshot of YT channel metadata)
"""
from __future__ import annotations

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def credentials_dir(root: Path, slug: str) -> Path:
    return Path(root) / slug


def has_credentials(root: Path, slug: str) -> bool:
    return (credentials_dir(root, slug) / "token.json").is_file()


def save_credentials(root: Path, slug: str, creds: Credentials) -> Path:
    d = credentials_dir(root, slug)
    d.mkdir(parents=True, exist_ok=True)
    token_path = d / "token.json"
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return token_path


def load_credentials(root: Path, slug: str) -> Credentials | None:
    """Load + auto-refresh credentials for the channel. Returns None if missing."""
    token_path = credentials_dir(root, slug) / "token.json"
    if not token_path.is_file():
        return None
    info = json.loads(token_path.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(info, scopes=info.get("scopes", SCOPES))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(root, slug, creds)
    return creds


def delete_credentials(root: Path, slug: str) -> None:
    """Remove token.json (channel_info.json kept for history)."""
    token_path = credentials_dir(root, slug) / "token.json"
    if token_path.exists():
        token_path.unlink()
