"""Per-channel YouTube OAuth — token persistence + refresh.

Each channel has its own Google Cloud project. Files live under
``data/youtube_credentials/<slug>/``:
  - client_secrets.json   (user-provided, OAuth client config)
  - token.json            (auto-managed, access + refresh token)
  - channel_info.json     (auto-managed, snapshot of YT channel metadata)
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
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


def load_credentials(
    root: Path, slug: str, *, proxy_session=None,
) -> Credentials | None:
    """Load + auto-refresh credentials for the channel. Returns None if missing.

    proxy_session: optional requests.Session (from build_proxied_requests_session)
    used when token refresh hits Google's OAuth endpoint. Lets us route the
    refresh through the same proxy as the upload.
    """
    token_path = credentials_dir(root, slug) / "token.json"
    if not token_path.is_file():
        return None
    info = json.loads(token_path.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(info, scopes=info.get("scopes", SCOPES))
    if creds.expired and creds.refresh_token:
        request = Request(session=proxy_session) if proxy_session else Request()
        creds.refresh(request)
        save_credentials(root, slug, creds)
    return creds


def delete_credentials(root: Path, slug: str) -> None:
    """Remove token.json (channel_info.json kept for history)."""
    token_path = credentials_dir(root, slug) / "token.json"
    if token_path.exists():
        token_path.unlink()


def purge_credentials(root: Path, slug: str) -> None:
    """Hard reset — delete the entire per-channel credentials directory
    (token.json + channel_info.json + client_secrets.json + anything else).

    Use when the user wants to start over (revoked OAuth app, switched
    Google project, accidental wrong account)."""
    d = credentials_dir(root, slug)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def build_flow(root: Path, slug: str, *, redirect_uri: str) -> Flow:
    """Construct an OAuth Flow from this channel's client_secrets.json."""
    secrets_path = credentials_dir(root, slug) / "client_secrets.json"
    if not secrets_path.is_file():
        raise FileNotFoundError(
            f"client_secrets.json not found at {secrets_path}. "
            "Download from Google Cloud Console and place it there."
        )
    return Flow.from_client_secrets_file(
        str(secrets_path), scopes=SCOPES, redirect_uri=redirect_uri,
    )


def fetch_and_save_channel_info(
    root: Path, slug: str, creds: Credentials, *, http=None,
) -> dict:
    """Call channels().list(mine=True), persist response as channel_info.json.

    http: optional proxied httplib2.Http. When given, wrapped in AuthorizedHttp
    and passed to build(http=...). When None, credentials= is passed (no proxy).
    """
    if http is not None:
        youtube = build("youtube", "v3", http=AuthorizedHttp(creds, http=http))
    else:
        youtube = build("youtube", "v3", credentials=creds)
    resp = youtube.channels().list(
        part="snippet,statistics", mine=True,
    ).execute()
    items = resp.get("items", [])
    if not items:
        raise RuntimeError("YouTube channels().list returned no items for this account")
    info = items[0]
    d = credentials_dir(root, slug)
    d.mkdir(parents=True, exist_ok=True)
    (d / "channel_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    from short_bot.youtube.avatar import fetch_and_cache_avatar
    fetch_and_cache_avatar(root, slug, info)
    return info


def load_channel_info(root: Path, slug: str) -> dict | None:
    p = credentials_dir(root, slug) / "channel_info.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
