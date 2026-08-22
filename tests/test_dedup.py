from datetime import datetime

from short_bot.db import init_db, mark_processed
from short_bot.dedup import filter_new
from short_bot.models import NewsItem


def _item(guid: str, title: str) -> NewsItem:
    return NewsItem(guid=guid, title=title, link="http://x", source=None,
                    pub_date=None, thumb_url=None, description=None)


def test_filter_new_keeps_unseen(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    items = [_item("g1", "Faiz indirimi"), _item("g2", "Dolar rekoru")]
    out = filter_new(eng, items, "ch", fuzzy_threshold=0.85)
    assert {i.guid for i in out} == {"g1", "g2"}


def test_filter_new_drops_seen_guid(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, "g1", "Faiz indirimi", "ch")
    items = [_item("g1", "Faiz indirimi"), _item("g2", "Dolar rekoru")]
    out = filter_new(eng, items, "ch", fuzzy_threshold=0.85)
    assert [i.guid for i in out] == ["g2"]


def test_filter_new_drops_fuzzy_match(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, "g_old", "Merkez Bankası faizi 250 baz puan indirdi", "ch")
    items = [_item("g_new", "Merkez Bankası faizi 250 baz puan indirmiş")]
    out = filter_new(eng, items, "ch", fuzzy_threshold=0.85)
    assert out == []


def test_filter_new_isolated_per_channel(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, "g1", "Faiz", "ch_a")
    items = [_item("g1", "Faiz")]
    out = filter_new(eng, items, "ch_b", fuzzy_threshold=0.85)
    assert len(out) == 1
