from datetime import datetime, timezone

import pytest

from short_bot.db import (
    init_db, add_feed, list_feeds, get_feed, delete_feed, set_feed_meta,
)


def test_init_creates_feeds_table(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    with eng.connect() as conn:
        from sqlalchemy import text
        rows = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )).fetchall()
    assert "feeds" in {r[0] for r in rows}


def test_add_and_list_feed(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    fid = add_feed(eng, url="https://site.com/rss", title="Site Spor")
    assert fid > 0
    feeds = list_feeds(eng)
    assert len(feeds) == 1
    assert feeds[0].url == "https://site.com/rss"
    assert feeds[0].title == "Site Spor"
    assert feeds[0].enabled == 1


def test_add_feed_duplicate_url_raises(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    add_feed(eng, url="https://site.com/rss", title="A")
    with pytest.raises(Exception):
        add_feed(eng, url="https://site.com/rss", title="B")


def test_get_feed(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    fid = add_feed(eng, url="https://site.com/rss", title="T")
    row = get_feed(eng, fid)
    assert row is not None and row.url == "https://site.com/rss"
    assert get_feed(eng, 9999) is None


def test_delete_feed(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    fid = add_feed(eng, url="https://site.com/rss", title="T")
    delete_feed(eng, fid)
    assert list_feeds(eng) == []


def test_list_feeds_enabled_only(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _ = add_feed(eng, url="https://a.com/rss", title="A")
    f2 = add_feed(eng, url="https://b.com/rss", title="B")
    set_feed_meta(eng, f2, enabled=0)
    assert len(list_feeds(eng)) == 2
    assert len(list_feeds(eng, enabled_only=True)) == 1


def test_set_feed_meta_updates_fetch_state(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    fid = add_feed(eng, url="https://site.com/rss", title="T")
    now = datetime.now(timezone.utc)
    set_feed_meta(eng, fid, last_fetched_at=now, last_error="boom")
    row = get_feed(eng, fid)
    assert row.last_error == "boom"
    assert row.last_fetched_at is not None


def test_set_feed_meta_clears_error_with_empty_string(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    fid = add_feed(eng, url="https://site.com/rss", title="T")
    set_feed_meta(eng, fid, last_error="boom")
    assert get_feed(eng, fid).last_error == "boom"
    set_feed_meta(eng, fid, last_error="")   # "" None değil → yazılır, hatayı temizler
    assert get_feed(eng, fid).last_error == ""
