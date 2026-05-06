from datetime import date, datetime, timezone, timedelta
from short_bot.db import (
    init_db, record_short, record_youtube_upload,
    upsert_video_stats, get_video_stats_for_short,
    upsert_channel_stats, get_channel_stats_history,
    incr_quota, get_quota_used_today,
)


def test_upsert_video_stats_inserts_then_updates(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    sid = record_short(eng, channel="ch", rss_item_guid=None, title="T",
                        file_path="x.mp4", duration_s=6, script_json="{}", render_ms=1)
    record_youtube_upload(eng, short_id=sid, video_id="V1",
                           status="success", error=None,
                           video_url="https://youtu.be/V1")
    today = date.today()
    upsert_video_stats(
        eng, video_id="V1", snapshot_date=today,
        views=100, likes=5, comments=1,
        watch_time_min=12.5, avg_view_duration_s=20.0,
    )
    rows = get_video_stats_for_short(eng, short_id=sid, days=30)
    assert len(rows) == 1
    assert rows[0].views == 100

    upsert_video_stats(
        eng, video_id="V1", snapshot_date=today,
        views=150, likes=8, comments=2,
        watch_time_min=20.0, avg_view_duration_s=25.0,
    )
    rows = get_video_stats_for_short(eng, short_id=sid, days=30)
    assert len(rows) == 1
    assert rows[0].views == 150


def test_upsert_channel_stats_records_history(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    today = date.today()
    yesterday = today - timedelta(days=1)
    upsert_channel_stats(eng, channel="ch", snapshot_date=yesterday,
                          subscribers=100, total_views=1000)
    upsert_channel_stats(eng, channel="ch", snapshot_date=today,
                          subscribers=110, total_views=1200)
    rows = get_channel_stats_history(eng, channel="ch", days=7)
    assert len(rows) == 2
    assert rows[0].subscribers == 110


def test_quota_tracker(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    assert get_quota_used_today(eng, channel="ch") == 0
    incr_quota(eng, channel="ch", units=5)
    incr_quota(eng, channel="ch", units=3)
    assert get_quota_used_today(eng, channel="ch") == 8
    assert get_quota_used_today(eng, channel="other") == 0
