"""short_bot.trends.trending_now — Google Trends 'Trending Now' iç API istemcisi.

Fikstürler 2026-08-20'de gerçek API'den kaydedildi (bkz. spec)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def trends_text() -> str:
    return (FIX / "trending_now_tr.txt").read_text(encoding="utf-8")


@pytest.fixture
def articles_text() -> str:
    return (FIX / "trending_articles_tr.txt").read_text(encoding="utf-8")


# --- parse_trending_response --------------------------------------------------

def test_parse_trending_reads_all_rows(trends_text):
    from short_bot.trends.trending_now import parse_trending_response
    entries = parse_trending_response(trends_text)
    assert len(entries) == 181
    first = entries[0]
    assert first.term == "şener üşümezsoy"
    assert first.volume == 100000
    assert first.growth_pct == 1000
    assert first.started_at == datetime.fromtimestamp(1787160000, tz=timezone.utc)
    assert first.category_ids == (20,)
    assert first.breakdown[:3] == ("şener üşümezsoy", "son dakika", "istanbul deprem")
    assert len(first.news_ids) == 24 and first.news_ids[0] == 4775113814


def test_parse_trending_skips_malformed_row():
    from short_bot.trends.trending_now import parse_trending_response
    rows = [["iyi", None, "TR", [1787160000], None, None, 5000, None, 300,
             ["iyi", "iyi haber"], [17], [[1, "tr", "TR"]], "iyi"],
            ["bozuk"]]
    inner = json.dumps([None, rows])
    text = ")]}'\n\n" + json.dumps([["wrb.fr", "i0OFE", inner, None, None, None, "generic"]])
    entries = parse_trending_response(text)
    assert [e.term for e in entries] == ["iyi"]


def test_parse_trending_returns_empty_on_garbage():
    from short_bot.trends.trending_now import parse_trending_response
    assert parse_trending_response("<html>503</html>") == []
    assert parse_trending_response(")]}'\n\n[]") == []


# --- parse_articles_response --------------------------------------------------

def test_parse_articles_keys_by_request_id(articles_text):
    from short_bot.trends.trending_now import parse_articles_response
    by_idx = parse_articles_response(articles_text)
    assert set(by_idx) == set(range(25))
    a0 = by_idx[0][0]
    assert a0.title.startswith("İstanbul'da geceden sabaha deprem")
    assert a0.url.startswith("https://www.ntv.com.tr/")
    assert a0.source == "NTV Haber"
    assert a0.published_at == datetime.fromtimestamp(1787204331, tz=timezone.utc)
    assert a0.image_url and a0.image_url.startswith("https://encrypted-tbn")
    assert by_idx[1][0].title.startswith("AJet")
    # Haberi dönmeyen alt çağrılar boş liste (safran, playstation)
    assert by_idx[13] == [] and by_idx[24] == []


def test_parse_articles_returns_empty_on_garbage():
    from short_bot.trends.trending_now import parse_articles_response
    assert parse_articles_response("nope") == {}
