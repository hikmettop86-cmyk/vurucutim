"""Google Trends "Trending Now" iç API istemcisi (batchexecute).

Resmi RSS ucu (google_daily.py) yalnız 10 trend ve "200+" biçiminde kaba hacim
veriyor. trends.google.com/trending sayfasının kendi kullandığı uç nokta ise
24 saatlik tam listeyi (TR'de ~180 trend) sayısal hacim, artış yüzdesi, arama
dökümü ve haber kimlikleriyle döndürüyor.

İki rpc:
- i0OFE  → trend listesi. Yük: [null, null, GEO, 0, lang, hours, 1]
- w4opAf → TEK trendin en çok 3 haberi. Yük: [[[news_id, lang, GEO], ...]]
  Kimlikler birden çok trendden gelse bile yalnız ilk trendin haberleri döner;
  bu yüzden her trend için ayrı alt çağrı yapılır. batchexecute tek HTTP
  isteğinde çoklu rpc kabul eder: alt çağrının 4. elemanı istek kimliği,
  yanıt parçasının [6]. elemanı aynı kimlik. 25 alt çağrı ~1,2 sn.

Yanıt biçimi: ilk satır ")]}'" (anti-XSSI), sonrası tek JSON dizisi; her parça
["wrb.fr", rpc_adı, "<iç JSON metni>", null, null, null, istek_kimliği].

API resmi değil. Bu modül HİÇBİR durumda hata fırlatmaz: ayrıştırıcılar boş
döner, fetch_trending_items RSS yedeğine düşer.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from short_bot.models import NewsItem

logger = logging.getLogger(__name__)

_URL = "https://trends.google.com/_/TrendsUi/data/batchexecute"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 short-bot/0.1")
_HEADERS = {
    "User-Agent": _UA,
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
}
_RPC_TRENDS = "i0OFE"
_RPC_ARTICLES = "w4opAf"


@dataclass(frozen=True)
class TrendingEntry:
    term: str
    volume: int                     # arama hacmi (50000 gibi)
    growth_pct: int                 # artış yüzdesi (1000 = %1.000)
    started_at: datetime | None     # trendin başlangıcı (UTC)
    category_ids: tuple[int, ...]   # Google kategori kimlikleri (17=spor, 11=siyaset…)
    breakdown: tuple[str, ...]      # ilişkili aramalar ("istanbul deprem", …)
    news_ids: tuple[int, ...]       # w4opAf için haber kimlikleri


@dataclass(frozen=True)
class TrendingArticle:
    title: str
    url: str
    source: str
    published_at: datetime | None
    image_url: str | None


# --- ayrıştırma ---------------------------------------------------------------

def _rpc_parts(text: str, rpc: str) -> list[tuple[str | None, object]]:
    """batchexecute yanıtındaki `rpc` parçalarını (istek_kimliği, iç_yük) olarak ver.
    Bozuk metinde boş liste."""
    _, _, rest = text.partition("\n")
    try:
        outer = json.loads(rest)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(outer, list):
        return []
    out: list[tuple[str | None, object]] = []
    for part in outer:
        if (not isinstance(part, list) or len(part) < 3
                or part[0] != "wrb.fr" or part[1] != rpc):
            continue
        req_id = part[6] if len(part) > 6 and isinstance(part[6], str) else None
        try:
            payload = json.loads(part[2]) if part[2] else None
        except (json.JSONDecodeError, TypeError):
            payload = None
        out.append((req_id, payload))
    return out


def _ts(val) -> datetime | None:
    """[1787160000] biçimindeki zaman damgasını UTC datetime'a çevir."""
    try:
        return datetime.fromtimestamp(int(val[0]), tz=timezone.utc)
    except (TypeError, ValueError, IndexError, OSError):
        return None


def parse_trending_response(text: str) -> list[TrendingEntry]:
    entries: list[TrendingEntry] = []
    for _, payload in _rpc_parts(text, _RPC_TRENDS):
        rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else None
        for row in rows or []:
            try:
                entries.append(TrendingEntry(
                    term=str(row[0]).strip(),
                    volume=int(row[6] or 0),
                    growth_pct=int(row[8] or 0),
                    started_at=_ts(row[3]),
                    category_ids=tuple(int(c) for c in (row[10] or [])),
                    breakdown=tuple(str(k) for k in (row[9] or [])),
                    news_ids=tuple(int(n[0]) for n in (row[11] or [])),
                ))
            except (IndexError, TypeError, ValueError) as e:
                logger.debug(f"trending_now: satır atlandı ({e}): {str(row)[:120]}")
    return entries


def parse_articles_response(text: str) -> dict[int, list[TrendingArticle]]:
    """istek_kimliği (trend indeksi) → haberler. Haberi olmayan alt çağrı boş liste."""
    out: dict[int, list[TrendingArticle]] = {}
    for req_id, payload in _rpc_parts(text, _RPC_ARTICLES):
        try:
            idx = int(req_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        rows = payload[0] if isinstance(payload, list) and payload else None
        arts: list[TrendingArticle] = []
        for a in rows or []:
            try:
                arts.append(TrendingArticle(
                    title=str(a[0]).strip(),
                    url=str(a[1]),
                    source=str(a[2] or ""),
                    published_at=_ts(a[3]),
                    image_url=(str(a[4]) if len(a) > 4 and a[4] else None),
                ))
            except (IndexError, TypeError) as e:
                logger.debug(f"trending_now: haber atlandı ({e}): {str(a)[:120]}")
        out[idx] = arts
    return out
