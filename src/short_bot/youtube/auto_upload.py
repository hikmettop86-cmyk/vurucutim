"""Decision + execution layer for pipeline-triggered auto-upload."""
from __future__ import annotations

import json as _json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select


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


@dataclass(frozen=True)
class AutoUploadResult:
    video_id: str
    video_url: str


def run_auto_upload(*, eng, short_id: int, channel, credentials,
                    claude_path: str = "claude",
                    model: str = "sonnet") -> AutoUploadResult:
    """Build metadata via Sonnet (best-effort) + upload + record DB row.

    Re-raises on upload failure after recording status='failed'. Sonnet failure
    silently falls back to bare snippet (upload still proceeds).
    """
    with eng.connect() as conn:
        row = conn.execute(
            select(_shorts_table).where(_shorts_table.c.id == short_id)
        ).first()
    if row is None:
        raise RuntimeError(f"short {short_id} not found")
    script = _json.loads(row.script_json or "{}")

    rss = get_rss_item_for_short(eng, short_id=short_id)
    rss_source = rss.source if rss else None
    rss_link = rss.link if rss else None

    generated = None
    try:
        meta = generate_youtube_metadata(
            channel=channel, script=script,
            rss_source=rss_source, rss_link=rss_link,
            claude_path=claude_path, model=model,
        )
        generated = {"title": meta.title, "description": meta.description, "tags": meta.tags}
    except Exception:
        pass  # fall back to bare snippet

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
            snippet=snippet, status=status,
        )
        url = f"https://youtu.be/{video_id}"
        record_youtube_upload(
            eng, short_id=short_id, video_id=video_id, status="success",
            error=None, video_url=url,
        )
        return AutoUploadResult(video_id=video_id, video_url=url)
    except Exception as e:
        record_youtube_upload(
            eng, short_id=short_id, video_id=None, status="failed",
            error=str(e)[:1000], video_url=None,
        )
        raise
