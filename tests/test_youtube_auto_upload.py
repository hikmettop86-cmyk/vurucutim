from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest

from short_bot.youtube.auto_upload import should_auto_upload, AutoUploadDecision


def _channel(auto=True, min_score=8.0):
    c = MagicMock()
    c.youtube = MagicMock(auto_upload=auto, min_score_for_upload=min_score)
    return c


def test_decline_when_youtube_block_missing():
    c = MagicMock(); c.youtube = None
    d = should_auto_upload(channel=c, picked_score=10.0,
                            last_upload_at=None, cooldown_minutes=5)
    assert d.eligible is False


def test_decline_when_auto_upload_off():
    d = should_auto_upload(channel=_channel(auto=False), picked_score=10.0,
                            last_upload_at=None, cooldown_minutes=5)
    assert d.eligible is False


def test_decline_when_score_below_threshold():
    d = should_auto_upload(channel=_channel(min_score=8.0), picked_score=7.5,
                            last_upload_at=None, cooldown_minutes=5)
    assert d.eligible is False
    assert "skor" in d.reason.lower() or "score" in d.reason.lower()


def test_accept_when_score_meets_threshold():
    d = should_auto_upload(channel=_channel(min_score=8.0), picked_score=8.0,
                            last_upload_at=None, cooldown_minutes=5)
    assert d.eligible is True


def test_score_threshold_zero_means_no_filter():
    d = should_auto_upload(channel=_channel(min_score=0.0), picked_score=0.5,
                            last_upload_at=None, cooldown_minutes=5)
    assert d.eligible is True


def test_decline_during_cooldown():
    last = datetime.now(timezone.utc) - timedelta(minutes=2)
    d = should_auto_upload(channel=_channel(min_score=8.0), picked_score=9.0,
                            last_upload_at=last, cooldown_minutes=5)
    assert d.eligible is False
    assert "cooldown" in d.reason.lower() or "soğuma" in d.reason.lower() or "bekle" in d.reason.lower()


def test_accept_after_cooldown():
    last = datetime.now(timezone.utc) - timedelta(minutes=10)
    d = should_auto_upload(channel=_channel(min_score=8.0), picked_score=9.0,
                            last_upload_at=last, cooldown_minutes=5)
    assert d.eligible is True


def test_generator_mode_no_score_always_eligible_when_auto_on():
    d = should_auto_upload(channel=_channel(min_score=8.0), picked_score=None,
                            last_upload_at=None, cooldown_minutes=5)
    assert d.eligible is True


def test_run_auto_upload_uploads_and_records(tmp_path):
    """Happy path: run_auto_upload calls metadata writer, uploader, records DB."""
    from short_bot.youtube.auto_upload import run_auto_upload
    from short_bot.db import init_db, record_short, get_youtube_upload_for_short
    from short_bot.youtube.metadata_writer import YoutubeMetadata

    eng = init_db(tmp_path / "x.sqlite")
    mp4 = tmp_path / "v.mp4"; mp4.write_bytes(b"\x00")
    sid = record_short(eng, channel="ch", rss_item_guid=None, title="T",
                        file_path=str(mp4), duration_s=6,
                        script_json='{"header_top":"A","header_bottom":"B",'
                                     '"photo_overlay":"X","body_paragraph":"yyyyyyyyyyyyyyyyyyyy",'
                                     '"highlights":[],"category":"x","mood":"neutral"}',
                        render_ms=1)
    fake_meta = YoutubeMetadata(title="auto", description="ok ok ok ok ok", tags=["s"])
    fake_creds = MagicMock(); fake_creds.expired = False

    cfg = MagicMock()
    cfg.handle = "@x"; cfg.keywords = []; cfg.language = "tr"
    cfg.youtube = MagicMock(category_id="24", privacy_status="public", ai_content=True)

    with patch("short_bot.youtube.auto_upload.generate_youtube_metadata",
                return_value=fake_meta), \
         patch("short_bot.youtube.auto_upload.upload_video", return_value="VID"):
        result = run_auto_upload(
            eng=eng, short_id=sid, channel=cfg, credentials=fake_creds,
            claude_path="claude", model="haiku",
        )
    assert result.video_id == "VID"
    row = get_youtube_upload_for_short(eng, short_id=sid)
    assert row.status == "success"


def test_run_auto_upload_records_failure(tmp_path):
    from short_bot.youtube.auto_upload import run_auto_upload
    from short_bot.db import init_db, record_short, get_youtube_upload_for_short

    eng = init_db(tmp_path / "x.sqlite")
    mp4 = tmp_path / "v.mp4"; mp4.write_bytes(b"\x00")
    sid = record_short(eng, channel="ch", rss_item_guid=None, title="T",
                        file_path=str(mp4), duration_s=6,
                        script_json='{"header_top":"A","header_bottom":"B",'
                                     '"photo_overlay":"X","body_paragraph":"yyyyyyyyyyyyyyyyyyyy",'
                                     '"highlights":[],"category":"x","mood":"neutral"}',
                        render_ms=1)
    cfg = MagicMock()
    cfg.handle = "@x"; cfg.keywords = []; cfg.language = "tr"
    cfg.youtube = MagicMock(category_id="24", privacy_status="public", ai_content=True)

    with patch("short_bot.youtube.auto_upload.generate_youtube_metadata",
                side_effect=RuntimeError("sonnet fail")), \
         patch("short_bot.youtube.auto_upload.upload_video",
                side_effect=RuntimeError("upload fail")):
        with pytest.raises(RuntimeError):
            run_auto_upload(
                eng=eng, short_id=sid, channel=cfg,
                credentials=MagicMock(), claude_path="claude", model="haiku",
            )
    row = get_youtube_upload_for_short(eng, short_id=sid)
    assert row.status == "failed"
    assert "upload fail" in (row.error or "")
