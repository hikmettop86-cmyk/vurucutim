"""Decision + execution layer for pipeline-triggered auto-upload."""
from __future__ import annotations

import json as _json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from sqlalchemy import select
from google.auth.transport.requests import Request


@dataclass(frozen=True)
class AutoUploadDecision:
    eligible: bool
    reason: str = ""


def should_auto_upload(*, channel, picked_score: float | None,
                       last_upload_at: datetime | None,
                       cooldown_minutes: int) -> AutoUploadDecision:
    """Return whether a freshly-rendered short should be auto-uploaded.

    Rules:
    1. channel.youtube must exist and auto_upload=True
    2. picked_score (RSS-mode) must be >= min_score_for_upload.
       picked_score=None (generator-mode) skips this check.
    3. If a prior successful upload occurred within cooldown_minutes, skip.
    """
    if channel.youtube is None or not channel.youtube.auto_upload:
        return AutoUploadDecision(False, "youtube auto_upload off")
    threshold = channel.youtube.min_score_for_upload
    if picked_score is not None and picked_score < threshold:
        return AutoUploadDecision(
            False, f"skor {picked_score:.1f} eşiğin altında ({threshold:.1f})",
        )
    if last_upload_at is not None:
        if last_upload_at.tzinfo is None:
            last_upload_at = last_upload_at.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - last_upload_at
        if delta < timedelta(minutes=cooldown_minutes):
            remaining = cooldown_minutes * 60 - delta.total_seconds()
            return AutoUploadDecision(
                False, f"global cooldown — {int(remaining)}s daha bekle",
            )
    return AutoUploadDecision(True)


from short_bot.db import get_rss_item_for_short, record_youtube_upload, shorts as _shorts_table  # noqa: E402
from short_bot.youtube.metadata_writer import generate_youtube_metadata  # noqa: E402
from short_bot.youtube.uploader import build_snippet, build_status, upload_video  # noqa: E402
from short_bot.youtube.proxy import (  # noqa: E402
    load_channel_proxy_url, build_proxied_http,
    build_proxied_requests_session, _redact_err,
)


class UploadAbortError(RuntimeError):
    """Upload aborted because proxy/network setup failed.

    Distinct from ResumableUploadError so callers can distinguish
    'API said no' from 'we never reached the API'.
    """


@dataclass(frozen=True)
class AutoUploadResult:
    video_id: str
    video_url: str


def _load_short_for_upload(eng, short_id: int):
    """Return (row, rss_source, rss_link) tuple for a short."""
    with eng.connect() as conn:
        row = conn.execute(
            select(_shorts_table).where(_shorts_table.c.id == short_id)
        ).first()
    if row is None:
        raise RuntimeError(f"short {short_id} not found")
    rss = get_rss_item_for_short(eng, short_id=short_id)
    return row, (rss.source if rss else None), (rss.link if rss else None)


def run_auto_upload(*, eng, short_id: int, channel, credentials,
                    claude_path: str = "claude",
                    model: str = "sonnet",
                    secrets_path: Path | None = None,
                    backend: str = "claude_cli",
                    api_key: str | None = None) -> AutoUploadResult:
    """Build metadata via Sonnet (best-effort) + upload + record DB row.

    secrets_path: data/secrets.yaml path. If None, no proxy lookup is attempted.

    Behavior:
      - If channel has a configured proxy: route token refresh + upload through it.
        Proxy failures raise UploadAbortError, recorded with status='proxy_failed'.
      - Otherwise: existing direct path.
    """
    row, rss_source, rss_link = _load_short_for_upload(eng, short_id)
    script = _json.loads(row.script_json or "{}")

    # Resolve proxy (if any) before any network I/O
    proxy_url = (
        load_channel_proxy_url(channel.slug, secrets_path)
        if secrets_path else None
    )
    http = build_proxied_http(proxy_url) if proxy_url else None
    session = build_proxied_requests_session(proxy_url) if proxy_url else None

    # Token refresh through proxy (only if expired) — surfaces proxy failure early
    if proxy_url and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request(session=session))
        except (requests.exceptions.ProxyError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            err = f"proxy fail (token refresh, {channel.slug}): {_redact_err(e)}"
            record_youtube_upload(
                eng, short_id=short_id, video_id=None,
                status="proxy_failed", error=err[:1000], video_url=None,
            )
            raise UploadAbortError(err) from e

    # Best-effort metadata generation
    generated = None
    try:
        meta = generate_youtube_metadata(
            channel=channel, script=script,
            rss_source=rss_source, rss_link=rss_link,
            claude_path=claude_path, model=model,
            backend=backend, api_key=api_key,
        )
        generated = {"title": meta.title, "description": meta.description, "tags": meta.tags}
    except Exception:
        pass

    yt = channel.youtube
    snippet = build_snippet(
        header_top=script.get("header_top", ""),
        header_bottom=script.get("header_bottom", ""),
        body_paragraph=script.get("body_paragraph", ""),
        handle=channel.handle, keywords=channel.keywords or [],
        category_id=yt.category_id, language=channel.language,
        generated=generated,
    )
    status = build_status(privacy_status=yt.privacy_status, ai_content=yt.ai_content)

    try:
        video_id = upload_video(
            credentials=credentials, file_path=Path(row.file_path),
            snippet=snippet, status=status, http=http,
        )
        url = f"https://youtu.be/{video_id}"
        record_youtube_upload(
            eng, short_id=short_id, video_id=video_id, status="success",
            error=None, video_url=url,
        )
        return AutoUploadResult(video_id=video_id, video_url=url)
    except Exception as e:
        # If we have a proxy and the error looks like a transport failure,
        # categorize it as proxy_failed (for UI distinction).
        is_proxy_fail = proxy_url is not None and isinstance(
            e, (requests.exceptions.ProxyError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                ConnectionError, OSError),
        )
        status_str = "proxy_failed" if is_proxy_fail else "failed"
        record_youtube_upload(
            eng, short_id=short_id, video_id=None, status=status_str,
            error=_redact_err(e)[:1000], video_url=None,
        )
        if is_proxy_fail:
            raise UploadAbortError(f"proxy fail (upload, {channel.slug}): {_redact_err(e)}") from e
        raise
