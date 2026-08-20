"""Yorum formatı için ek kaynak gövdeleri: trendin 2./3. makalesi."""
from __future__ import annotations

from short_bot.models import NewsItem


def _item(extra):
    return NewsItem(guid="https://a/1", title="t", link="https://a/1", source="A", pub_date=None,
                    thumb_url=None, description=None, extra_links=tuple(extra))


def test_extra_source_bodies_extracts_each_and_skips_failures(monkeypatch):
    from short_bot import pipeline
    calls = []

    def _extract(url):
        calls.append(url)
        if "b" in url:
            return None
        return ("gövde " * 500).strip()          # 3000 karakter → 1500'e kırpılır
    monkeypatch.setattr(pipeline, "extract_article", _extract)
    monkeypatch.setattr(pipeline, "_is_google_news_url", lambda u: False)
    out = pipeline._extra_source_bodies(_item(["https://b/2", "https://c/3"]), log=None)
    assert calls == ["https://b/2", "https://c/3"]
    assert len(out) == 1 and out[0][0] == "https://c/3" and len(out[0][1]) <= 1500


def test_extra_source_bodies_empty_without_links(monkeypatch):
    from short_bot import pipeline
    monkeypatch.setattr(pipeline, "extract_article", lambda u: (_ for _ in ()).throw(AssertionError("çağrılmamalı")))
    assert pipeline._extra_source_bodies(_item([]), log=None) == []
