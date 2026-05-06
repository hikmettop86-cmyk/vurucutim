"""Decision + execution layer for pipeline-triggered auto-upload."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


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
