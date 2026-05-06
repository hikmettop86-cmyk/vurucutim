from pathlib import Path
from short_bot.db import (
    init_db, record_short, record_youtube_upload, get_youtube_upload_for_short,
    list_youtube_uploads_for_channel,
)


def test_record_youtube_upload_inserts_row(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    sid = record_short(eng, channel="ch", rss_item_guid="g1", title="T",
                        file_path="output/ch/x.mp4", duration_s=30,
                        script_json='{"x":1}', render_ms=4000)
    upload_id = record_youtube_upload(
        eng, short_id=sid, video_id="abc123",
        status="success", error=None, video_url="https://youtu.be/abc123",
    )
    assert upload_id > 0


def test_get_youtube_upload_returns_latest(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    sid = record_short(eng, channel="ch", rss_item_guid="g1", title="T",
                        file_path="x.mp4", duration_s=30, script_json="{}",
                        render_ms=1)
    record_youtube_upload(eng, short_id=sid, video_id=None,
                           status="failed", error="boom", video_url=None)
    record_youtube_upload(eng, short_id=sid, video_id="ok123",
                           status="success", error=None,
                           video_url="https://youtu.be/ok123")
    row = get_youtube_upload_for_short(eng, short_id=sid)
    assert row.status == "success"
    assert row.video_id == "ok123"


def test_list_youtube_uploads_for_channel_orders_recent_first(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    sid1 = record_short(eng, channel="ch", rss_item_guid="g1", title="T1",
                         file_path="x.mp4", duration_s=30,
                         script_json="{}", render_ms=1)
    sid2 = record_short(eng, channel="ch", rss_item_guid="g2", title="T2",
                         file_path="y.mp4", duration_s=30,
                         script_json="{}", render_ms=1)
    record_youtube_upload(eng, short_id=sid1, video_id="v1", status="success",
                           error=None, video_url="https://youtu.be/v1")
    record_youtube_upload(eng, short_id=sid2, video_id="v2", status="success",
                           error=None, video_url="https://youtu.be/v2")
    rows = list_youtube_uploads_for_channel(eng, "ch", limit=10)
    assert len(rows) == 2
    assert rows[0].short_id == sid2
    assert rows[1].short_id == sid1


def test_get_last_youtube_upload_at_returns_most_recent(tmp_path):
    from short_bot.db import get_last_youtube_upload_at
    eng = init_db(tmp_path / "x.sqlite")
    assert get_last_youtube_upload_at(eng) is None
    sid = record_short(eng, channel="ch", rss_item_guid="g", title="T",
                        file_path="x.mp4", duration_s=6, script_json="{}", render_ms=1)
    record_youtube_upload(eng, short_id=sid, video_id="v1",
                           status="success", error=None,
                           video_url="https://youtu.be/v1")
    ts = get_last_youtube_upload_at(eng)
    assert ts is not None


def test_get_last_youtube_upload_at_ignores_failed_rows(tmp_path):
    from short_bot.db import get_last_youtube_upload_at
    eng = init_db(tmp_path / "x.sqlite")
    sid = record_short(eng, channel="ch", rss_item_guid="g", title="T",
                        file_path="x.mp4", duration_s=6, script_json="{}", render_ms=1)
    record_youtube_upload(eng, short_id=sid, video_id=None,
                           status="failed", error="x", video_url=None)
    assert get_last_youtube_upload_at(eng) is None
