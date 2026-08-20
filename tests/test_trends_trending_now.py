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
    assert len(first.news_ids) == 22 and first.news_ids[0] == 4775113814


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


# --- HTTP çağrıları -----------------------------------------------------------

class _Resp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_fetch_trending_now_posts_expected_payload(trends_text, monkeypatch):
    from short_bot.trends import trending_now as tn
    seen = {}

    def _post(url, data=None, headers=None, timeout=None):
        seen["url"] = url; seen["data"] = data; seen["timeout"] = timeout
        return _Resp(trends_text)
    monkeypatch.setattr(tn.requests, "post", _post)

    entries = tn.fetch_trending_now("tr", language="tr", hours=24, timeout_s=9)
    assert len(entries) == 181
    assert seen["url"].endswith("/batchexecute")
    assert seen["timeout"] == 9
    calls = json.loads(seen["data"]["f.req"])
    assert calls[0][0][0] == "i0OFE"
    assert json.loads(calls[0][0][1]) == [None, None, "TR", 0, "tr", 24, 1]


def test_fetch_trending_articles_one_subcall_per_entry(articles_text, monkeypatch):
    from short_bot.trends import trending_now as tn
    seen = {}

    def _post(url, data=None, headers=None, timeout=None):
        seen["data"] = data
        return _Resp(articles_text)
    monkeypatch.setattr(tn.requests, "post", _post)

    entries = [
        tn.TrendingEntry("a", 5000, 100, None, (), (), (11, 12)),
        tn.TrendingEntry("habersiz", 5000, 100, None, (), (), ()),
        tn.TrendingEntry("b", 2000, 100, None, (), (), (21,)),
    ]
    by_idx = tn.fetch_trending_articles(entries, language="tr", region="tr")
    calls = json.loads(seen["data"]["f.req"])[0]
    # haberi olmayan giriş için alt çağrı YOK; kimlik = giriş indeksi
    assert [c[3] for c in calls] == ["0", "2"]
    assert json.loads(calls[0][1]) == [[[11, "tr", "TR"], [12, "tr", "TR"]]]
    assert 0 in by_idx


def test_fetch_trending_articles_no_request_when_nothing_to_ask(monkeypatch):
    from short_bot.trends import trending_now as tn

    def _boom(*a, **k):
        raise AssertionError("HTTP çağrısı yapılmamalıydı")
    monkeypatch.setattr(tn.requests, "post", _boom)
    assert tn.fetch_trending_articles([], language="tr", region="TR") == {}


def test_fetch_trending_now_raises_on_http_error(monkeypatch):
    from short_bot.trends import trending_now as tn
    monkeypatch.setattr(tn.requests, "post",
                        lambda *a, **k: _Resp("rate limited", status=429))
    with pytest.raises(requests.HTTPError):
        tn.fetch_trending_now("TR", language="tr")


# --- NewsItem dönüşümü --------------------------------------------------------

def _entry(term, volume, news_ids=(1,), breakdown=(), started=None, pct=500):
    from short_bot.trends.trending_now import TrendingEntry
    return TrendingEntry(term, volume, pct, started, (), tuple(breakdown), tuple(news_ids))


def _art(title, url, source="Kaynak", image="https://img/x.jpg"):
    from short_bot.trends.trending_now import TrendingArticle
    return TrendingArticle(title, url, source, None, image)


def test_as_news_items_uses_first_article_and_sorts_by_volume():
    from short_bot.trends.trending_now import trending_as_news_items
    started = datetime(2026, 8, 19, 17, 20, tzinfo=timezone.utc)
    entries = [
        _entry("ajet", 20000, breakdown=("ajet", "ajet bilet"), started=started, pct=200),
        _entry("şener üşümezsoy", 100000, breakdown=("şener üşümezsoy", "istanbul deprem")),
    ]
    arts = {
        0: [_art("AJet'ten 55 liraya bilet", "https://ntv/ajet"),
            _art("AJet 29 dolar", "https://aa/ajet")],
        1: [_art("Marmara 8 saatte 36 kez sallandı", "https://milliyet/deprem")],
    }
    items = trending_as_news_items(entries, arts)
    assert [i.trend_volume for i in items] == [100000, 20000]
    ajet = items[1]
    assert ajet.guid == "https://ntv/ajet" and ajet.link == "https://ntv/ajet"
    assert ajet.title == "AJet'ten 55 liraya bilet"
    assert ajet.source == "Kaynak"
    assert ajet.thumb_url == "https://img/x.jpg"
    assert ajet.pub_date == started
    assert "20.000" in ajet.description and "%200" in ajet.description
    assert "ajet bilet" in ajet.description
    assert "AJet 29 dolar" in ajet.description   # diğer başlık bağlam olarak


def test_as_news_items_drops_entries_without_articles_or_below_min_volume():
    from short_bot.trends.trending_now import trending_as_news_items
    entries = [_entry("habersiz", 50000), _entry("küçük", 500), _entry("iyi", 5000)]
    arts = {0: [], 2: [_art("İyi haber", "https://x/iyi")]}
    items = trending_as_news_items(entries, arts, min_volume=1000)
    assert [i.guid for i in items] == ["https://x/iyi"]


def test_as_news_items_merges_same_article_keeping_highest_volume():
    from short_bot.trends.trending_now import trending_as_news_items
    entries = [_entry("atletico madrid", 5000), _entry("atletico madrid - malaga", 10000)]
    arts = {0: [_art("Atletico sezona galibiyetle başladı", "https://x/atleti")],
            1: [_art("Atletico sezona galibiyetle başladı", "https://x/atleti")]}
    items = trending_as_news_items(entries, arts)
    assert len(items) == 1
    assert items[0].trend_volume == 10000
