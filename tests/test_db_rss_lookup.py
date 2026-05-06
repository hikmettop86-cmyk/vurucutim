from datetime import datetime, timezone
from short_bot.db import (
    init_db, record_short, record_rss_item, get_rss_item_for_short,
)


def test_returns_rss_item_when_guid_matches(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    record_rss_item(
        eng, guid="g1", channel="ch", title="Manşet", link="https://example.com/x",
        source="Reuters", pub_date=datetime.now(timezone.utc), thumb_url=None,
        score=8.0, status="selected",
    )
    sid = record_short(
        eng, channel="ch", rss_item_guid="g1", title="T",
        file_path="x.mp4", duration_s=6, script_json="{}", render_ms=1,
    )
    row = get_rss_item_for_short(eng, short_id=sid)
    assert row is not None
    assert row.source == "Reuters"
    assert row.link == "https://example.com/x"
    assert row.title == "Manşet"


def test_returns_none_when_no_rss_guid(tmp_path):
    """Generator-mode shorts have rss_item_guid=None — no source available."""
    eng = init_db(tmp_path / "x.sqlite")
    sid = record_short(
        eng, channel="ch", rss_item_guid=None, title="T",
        file_path="x.mp4", duration_s=6, script_json="{}", render_ms=1,
    )
    assert get_rss_item_for_short(eng, short_id=sid) is None


def test_returns_none_when_guid_not_in_rss_items(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    sid = record_short(
        eng, channel="ch", rss_item_guid="missing", title="T",
        file_path="x.mp4", duration_s=6, script_json="{}", render_ms=1,
    )
    assert get_rss_item_for_short(eng, short_id=sid) is None


def test_returns_none_when_short_not_found(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    assert get_rss_item_for_short(eng, short_id=99999) is None
