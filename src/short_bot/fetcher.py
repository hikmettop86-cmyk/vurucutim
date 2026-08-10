"""Google News RSS fetcher."""
from __future__ import annotations

import time
from datetime import datetime
from itertools import zip_longest
from urllib.parse import quote_plus

import feedparser
import requests
from dateutil import parser as dateparser

from short_bot.models import NewsItem
from short_bot.locale import RSS_LOCALES

_BASE_URL = "https://news.google.com/rss/search"


def build_rss_url(keywords: list[str], locale: str) -> str:
    if not keywords:
        raise ValueError("keywords boş olamaz")
    q = "+OR+".join(quote_plus(k) for k in keywords)
    return f"{_BASE_URL}?q={q}&{locale}"


def fetch_rss(
    keywords: list[str],
    locale: str,
    *,
    max_retries: int = 3,
    backoff: float = 1.0,
    timeout: int = 15,
) -> list[NewsItem]:
    """Her anahtar için AYRI sorgu at, sonuçları guid'e göre tekilleştir.

    Anahtarları `+OR+` ile tek sorguda birleştirmek havuzu genişletmiyor,
    daraltıyor: ölçümde q=galatasaray 110 sonuç verirken aynı sorguya 3 terim
    daha OR'lanınca 100'e düştü. Buna karşılık "Galatasaray Şampiyonlar Ligi"
    AYRI sorgu olarak atıldığında dönen 99 haberin 91'i ana havuzda yoktu.
    Kanal tek anahtar kullanıyorsa (mevcut tüm kanallar) davranış değişmez —
    tek sorgu, aynı URL.

    Sonuçlar anahtarlar arasında DÖNÜŞÜMLÜ diziliyor. Ardışık ekleme, aşağı
    akıştaki `new_items[:max_candidates_per_run]` penceresini tamamen ilk
    anahtara bırakıyordu: gerçek koşuda 96 taze haberin penceresine giren 10
    haberin 10'u da "galatasaray" sorgusundandı ve kanalın en iyi
    kategorilerini beslemek için eklenen anahtarlar hiç puanlanmadı.
    """
    if not keywords:
        raise ValueError("keywords boş olamaz")

    per_key = [
        _fetch_query(build_rss_url([k], locale),
                     max_retries=max_retries, backoff=backoff, timeout=timeout)
        for k in keywords
    ]
    merged: dict[str, NewsItem] = {}
    for sira in zip_longest(*per_key):
        for item in sira:
            # İlk gören kazanır: aynı haber birden çok sorgudan dönebilir.
            if item is not None:
                merged.setdefault(item.guid, item)
    return list(merged.values())


def _fetch_query(
    url: str, *, max_retries: int, backoff: float, timeout: int,
) -> list[NewsItem]:
    """Tek sorgu + retry. Kalıcı hatada [] döner (diğer anahtarlar sürsün)."""
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "short-bot/0.1"})
            r.raise_for_status()
            return _parse_feed(r.content)
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(backoff * (2 ** attempt))
    return []


def fetch_feed_url(
    url: str,
    *,
    max_retries: int = 3,
    backoff: float = 1.0,
    timeout: int = 15,
) -> list[NewsItem]:
    """Fetch and parse ANY RSS/Atom feed URL into NewsItems.

    Same request+retry skeleton as fetch_rss, but takes a ready URL instead
    of building a Google News query. Reuses _parse_feed. Returns [] on
    persistent failure (caller decides how to surface it)."""
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": "short-bot/0.1"})
            r.raise_for_status()
            return _parse_feed(r.content)
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(backoff * (2 ** attempt))
    return []


def _parse_feed(raw: bytes) -> list[NewsItem]:
    parsed = feedparser.parse(raw)
    items: list[NewsItem] = []
    for e in parsed.entries:
        thumb = None
        if "media_thumbnail" in e and e.media_thumbnail:
            thumb = e.media_thumbnail[0].get("url")
        elif "media_content" in e and e.media_content:
            thumb = e.media_content[0].get("url")

        pub = None
        if e.get("published"):
            try:
                pub = dateparser.parse(e.published)
            except (ValueError, TypeError):
                pub = None

        title = e.get("title", "").strip()
        # Google News appends " - Source" to title; split off
        source = None
        if " - " in title:
            head, _, tail = title.rpartition(" - ")
            title = head.strip()
            source = tail.strip()
        if e.get("source"):
            try:
                source = e.source.get("title") or source
            except AttributeError:
                pass

        items.append(NewsItem(
            guid=e.get("id") or e.get("guid") or e.get("link", ""),
            title=title,
            link=e.get("link", ""),
            source=source,
            pub_date=pub,
            thumb_url=thumb,
            description=e.get("summary"),
        ))
    return items


def build_rss_url_for_language(keywords: list[str], language: str) -> str:
    """Convenience: build the RSS URL using the locale for `language`."""
    return build_rss_url(keywords, RSS_LOCALES[language])
