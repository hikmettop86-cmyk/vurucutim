from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from short_bot.youtube.stats_refresh import refresh_channel_stats


def test_refresh_writes_video_and_channel_rows(tmp_path):
    from short_bot.db import init_db, record_short, record_youtube_upload
    from short_bot.db import get_channel_stats_history, get_video_stats_for_short
    eng = init_db(tmp_path / "x.sqlite")
    sid = record_short(eng, channel="ch", rss_item_guid=None, title="T",
                        file_path="x.mp4", duration_s=6, script_json="{}", render_ms=1)
    record_youtube_upload(eng, short_id=sid, video_id="V1",
                           status="success", error=None,
                           video_url="https://youtu.be/V1")

    yt_root = tmp_path / "yt"; (yt_root / "ch").mkdir(parents=True)
    (yt_root / "ch" / "token.json").write_text("{}")

    with patch("short_bot.youtube.stats_refresh._yt_auth.load_credentials") as mload, \
         patch("short_bot.youtube.stats_refresh.fetch_video_stats_batch",
                return_value={"V1": {"views": 100, "likes": 5, "comments": 1}}), \
         patch("short_bot.youtube.stats_refresh.fetch_video_analytics",
                return_value={"V1": {"watch_time_min": 12.5,
                                      "avg_view_duration_s": 8.0,
                                      "views_in_window": 50,
                                      "subscribers_gained": 4,
                                      "avg_view_percentage": 133.0}}), \
         patch("short_bot.youtube.stats_refresh.fetch_channel_stats",
                return_value={"channel_id": "UC1",
                               "subscribers": 1500, "total_views": 50000}):
        mload.return_value = MagicMock(expired=False)
        result = refresh_channel_stats(
            eng=eng, channel_slug="ch", yt_creds_root=yt_root,
            video_lookback_days=30,
        )
    assert result.video_count == 1
    assert result.channel_updated is True

    chan_rows = get_channel_stats_history(eng, channel="ch", days=7)
    assert chan_rows[0].subscribers == 1500

    vid_rows = get_video_stats_for_short(eng, short_id=sid, days=30)
    assert vid_rows[0].views == 100
    assert vid_rows[0].watch_time_min == 12.5
    assert vid_rows[0].subscribers_gained == 4       # dönüşüm görünürlüğü
    assert vid_rows[0].avg_view_percentage == 133.0


def test_refresh_skips_when_no_credentials(tmp_path):
    from short_bot.db import init_db
    eng = init_db(tmp_path / "x.sqlite")
    yt_root = tmp_path / "yt"
    with patch("short_bot.youtube.stats_refresh._yt_auth.load_credentials",
                return_value=None):
        result = refresh_channel_stats(
            eng=eng, channel_slug="ch", yt_creds_root=yt_root,
            video_lookback_days=30,
        )
    assert result.video_count == 0
    assert result.channel_updated is False
    assert "credentials" in result.skipped_reason.lower()


def test_refresh_skips_when_no_recent_videos(tmp_path):
    """No uploaded videos — only channel stats refreshed."""
    from short_bot.db import init_db
    eng = init_db(tmp_path / "x.sqlite")
    yt_root = tmp_path / "yt"; (yt_root / "ch").mkdir(parents=True)
    (yt_root / "ch" / "token.json").write_text("{}")
    with patch("short_bot.youtube.stats_refresh._yt_auth.load_credentials") as mload, \
         patch("short_bot.youtube.stats_refresh.fetch_channel_stats",
                return_value={"channel_id": "UC1", "subscribers": 100, "total_views": 1000}):
        mload.return_value = MagicMock(expired=False)
        result = refresh_channel_stats(
            eng=eng, channel_slug="ch", yt_creds_root=yt_root,
            video_lookback_days=30,
        )
    assert result.video_count == 0
    assert result.channel_updated is True


def test_refresh_increments_quota(tmp_path):
    from short_bot.db import init_db, record_short, record_youtube_upload, get_quota_used_today
    eng = init_db(tmp_path / "x.sqlite")
    sid = record_short(eng, channel="ch", rss_item_guid=None, title="T",
                        file_path="x.mp4", duration_s=6, script_json="{}", render_ms=1)
    record_youtube_upload(eng, short_id=sid, video_id="V1",
                           status="success", error=None,
                           video_url="https://youtu.be/V1")
    yt_root = tmp_path / "yt"; (yt_root / "ch").mkdir(parents=True)
    (yt_root / "ch" / "token.json").write_text("{}")
    with patch("short_bot.youtube.stats_refresh._yt_auth.load_credentials",
                return_value=MagicMock(expired=False)), \
         patch("short_bot.youtube.stats_refresh.fetch_video_stats_batch",
                return_value={"V1": {"views": 1, "likes": 0, "comments": 0}}), \
         patch("short_bot.youtube.stats_refresh.fetch_video_analytics",
                return_value={}), \
         patch("short_bot.youtube.stats_refresh.fetch_channel_stats",
                return_value={"channel_id": "UC1", "subscribers": 1, "total_views": 1}):
        refresh_channel_stats(
            eng=eng, channel_slug="ch", yt_creds_root=yt_root,
            video_lookback_days=30,
        )
    used = get_quota_used_today(eng, channel="ch")
    assert used >= 5
