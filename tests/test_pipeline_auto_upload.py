"""Pipeline post-render hook auto-upload integration."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.config import ChannelConfig, YoutubeChannelConfig


def _channel(auto=True, min_score=8.0, slug="t"):
    return ChannelConfig(
        slug=slug, name="T", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="*", duration_s=6, min_score=6.0,
        max_candidates_per_run=1, template="newscast",
        colors={"primary": "#000", "accent": "#111", "bg_gradient": ["#000", "#111"]},
        handle="@t", output_dir="out", enabled=True,
 language="tr",
        dna=None, script_model=None, content_source="rss", generator=None,
        youtube=YoutubeChannelConfig(
            auto_upload=auto, min_score_for_upload=min_score,
        ),
    )


def test_maybe_auto_upload_skipped_when_credentials_missing(tmp_path):
    """No token → log skip, don't crash."""
    from short_bot.pipeline import _maybe_auto_upload
    log = MagicMock()
    _maybe_auto_upload(
        eng=MagicMock(), short_id=1, channel=_channel(auto=True),
        picked_score=9.0, log=log,
        yt_creds_root=tmp_path / "no-such-dir",
        claude_path="claude", model="haiku", cooldown_minutes=5,
    )
    assert any("youtube" in str(c).lower() or "yt" in str(c).lower() or "auto-upload" in str(c).lower()
               for c in log.info.call_args_list + log.warning.call_args_list)


def test_maybe_auto_upload_invokes_run_when_eligible(tmp_path):
    from short_bot.pipeline import _maybe_auto_upload
    yt_root = tmp_path / "yt_creds"
    (yt_root / "t").mkdir(parents=True)
    (yt_root / "t" / "token.json").write_text("{}")
    log = MagicMock()
    fake_creds = MagicMock(); fake_creds.expired = False
    with patch("short_bot.pipeline._yt_auth.load_credentials",
                return_value=fake_creds), \
         patch("short_bot.pipeline.get_last_youtube_upload_at",
                return_value=None), \
         patch("short_bot.pipeline.run_auto_upload") as mrun:
        from short_bot.youtube.auto_upload import AutoUploadResult
        mrun.return_value = AutoUploadResult(video_id="V", video_url="https://youtu.be/V")
        _maybe_auto_upload(
            eng=MagicMock(), short_id=42, channel=_channel(auto=True, min_score=8.0),
            picked_score=9.0, log=log,
            yt_creds_root=yt_root,
            claude_path="claude", model="haiku", cooldown_minutes=5,
        )
    mrun.assert_called_once()


def test_maybe_auto_upload_skipped_when_score_below(tmp_path):
    from short_bot.pipeline import _maybe_auto_upload
    yt_root = tmp_path / "yt_creds"
    (yt_root / "t").mkdir(parents=True)
    (yt_root / "t" / "token.json").write_text("{}")
    log = MagicMock()
    fake_creds = MagicMock(); fake_creds.expired = False
    with patch("short_bot.pipeline._yt_auth.load_credentials",
                return_value=fake_creds), \
         patch("short_bot.pipeline.get_last_youtube_upload_at",
                return_value=None), \
         patch("short_bot.pipeline.run_auto_upload") as mrun:
        _maybe_auto_upload(
            eng=MagicMock(), short_id=1,
            channel=_channel(auto=True, min_score=9.0),
            picked_score=7.5, log=log,
            yt_creds_root=yt_root,
            claude_path="claude", model="haiku", cooldown_minutes=5,
        )
    mrun.assert_not_called()


def test_maybe_auto_upload_skipped_during_cooldown(tmp_path):
    from short_bot.pipeline import _maybe_auto_upload
    yt_root = tmp_path / "yt_creds"
    (yt_root / "t").mkdir(parents=True)
    (yt_root / "t" / "token.json").write_text("{}")
    log = MagicMock()
    fake_creds = MagicMock(); fake_creds.expired = False
    last = datetime.now(timezone.utc) - timedelta(minutes=2)
    with patch("short_bot.pipeline._yt_auth.load_credentials",
                return_value=fake_creds), \
         patch("short_bot.pipeline.get_last_youtube_upload_at",
                return_value=last), \
         patch("short_bot.pipeline.run_auto_upload") as mrun:
        _maybe_auto_upload(
            eng=MagicMock(), short_id=1,
            channel=_channel(auto=True, min_score=0.0),
            picked_score=10.0, log=log,
            yt_creds_root=yt_root,
            claude_path="claude", model="haiku", cooldown_minutes=5,
        )
    mrun.assert_not_called()


def test_maybe_auto_upload_swallows_run_exception(tmp_path):
    """Upload exception logged but does NOT propagate (pipeline run still success)."""
    from short_bot.pipeline import _maybe_auto_upload
    yt_root = tmp_path / "yt_creds"
    (yt_root / "t").mkdir(parents=True)
    (yt_root / "t" / "token.json").write_text("{}")
    log = MagicMock()
    fake_creds = MagicMock(); fake_creds.expired = False
    with patch("short_bot.pipeline._yt_auth.load_credentials",
                return_value=fake_creds), \
         patch("short_bot.pipeline.get_last_youtube_upload_at", return_value=None), \
         patch("short_bot.pipeline.run_auto_upload",
                side_effect=RuntimeError("youtube quota exceeded")):
        # Should NOT raise
        _maybe_auto_upload(
            eng=MagicMock(), short_id=1, channel=_channel(auto=True),
            picked_score=10.0, log=log,
            yt_creds_root=yt_root,
            claude_path="claude", model="haiku", cooldown_minutes=5,
        )
    assert log.warning.called or log.exception.called or log.error.called
