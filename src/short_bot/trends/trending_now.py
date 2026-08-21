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


# --- HTTP ---------------------------------------------------------------------

def _post(calls: list[list], timeout_s: int) -> str:
    """Birden çok rpc alt çağrısını tek batchexecute isteğinde gönder.
    HTTP hatasında requests.HTTPError fırlatır (çağıran yedeğe düşer)."""
    r = requests.post(_URL, data={"f.req": json.dumps([calls])},
                      headers=_HEADERS, timeout=timeout_s)
    r.raise_for_status()
    return r.text


def fetch_trending_now(
    region: str, *, language: str, hours: int = 24, timeout_s: int = 15,
) -> list[TrendingEntry]:
    """Bölgenin son `hours` saatlik trend listesi. Ağ/HTTP hatası fırlatır."""
    payload = json.dumps([None, None, region.upper(), 0, language, hours, 1])
    text = _post([[_RPC_TRENDS, payload, None, "generic"]], timeout_s)
    return parse_trending_response(text)


def fetch_trending_articles(
    entries: list[TrendingEntry], *, language: str, region: str,
    timeout_s: int = 15,
) -> dict[int, list[TrendingArticle]]:
    """Her giriş için ayrı w4opAf alt çağrısı, hepsi tek istekte.
    Anahtar = `entries` içindeki indeks. Haber kimliği olmayan giriş atlanır."""
    calls: list[list] = []
    for idx, e in enumerate(entries):
        if not e.news_ids:
            continue
        payload = json.dumps([[[nid, language, region.upper()] for nid in e.news_ids]])
        calls.append([_RPC_ARTICLES, payload, None, str(idx)])
    if not calls:
        return {}
    return parse_articles_response(_post(calls, timeout_s))


# --- NewsItem dönüşümü --------------------------------------------------------

def _fmt_int(n: int) -> str:
    """50000 → '50.000' (Türkçe/Avrupa binlik ayracı; dilden bağımsız okunur)."""
    return f"{n:,}".replace(",", ".")


def _describe(e: TrendingEntry, other_titles: list[str]) -> str:
    """Puanlayıcı ve senaryo yazarının gördüğü bağlam satırı. Dil-nötr etiketler."""
    head = f"Google Trends · {_fmt_int(e.volume)} arama"
    if e.growth_pct:
        head += f" · +%{_fmt_int(e.growth_pct)}"
    parts = [head]
    if e.breakdown:
        parts.append(", ".join(e.breakdown[:6]))
    if other_titles:
        parts.append(" | ".join(t for t in other_titles[:2] if t))
    return " · ".join(parts)


def trending_as_news_items(
    entries: list[TrendingEntry],
    articles_by_index: dict[int, list[TrendingArticle]],
    *,
    min_volume: int = 1000,
) -> list[NewsItem]:
    """Her trende TEK NewsItem: ilk haberin URL'si guid/link, başlığı title.

    - Haberi olmayan ya da `min_volume` altındaki trend elenir (hikâye yok).
    - Aynı haberi paylaşan iki trend ('atletico madrid' / 'atletico madrid -
      malaga') tek kalemde birleşir; yüksek hacimli olan kalır.
    - Çıktı hacme göre azalan sıralı — pipeline'daki `[:max_candidates_per_run]`
      kesimi bu sayede 'en çok aranan ilk N'i puanlatır.
    """
    best: dict[str, NewsItem] = {}
    for idx, e in enumerate(entries):
        if e.volume < min_volume:
            continue
        arts = articles_by_index.get(idx) or []
        if not arts:
            continue
        first = arts[0]
        if not first.url or not first.title:
            continue
        item = NewsItem(
            guid=first.url,
            title=first.title,
            link=first.url,
            source=first.source or None,
            pub_date=e.started_at,
            thumb_url=first.image_url,
            description=_describe(e, [a.title for a in arts[1:]]),
            trend_volume=e.volume,
            extra_links=tuple(a.url for a in arts[1:3] if a.url and a.url != first.url),
            trend_growth_pct=e.growth_pct,
            trend_related=tuple(e.breakdown[:6]),
            trend_articles=tuple((a.source or "", a.title) for a in arts[1:3] if a.title),
            trend_categories=tuple(e.category_ids),
        )
        prev = best.get(item.guid)
        if prev is None or item.trend_volume > prev.trend_volume:
            best[item.guid] = item
    return sorted(best.values(), key=lambda i: i.trend_volume, reverse=True)


# --- önbellek -----------------------------------------------------------------

def _item_to_dict(i: NewsItem) -> dict:
    return {
        "guid": i.guid, "title": i.title, "link": i.link, "source": i.source,
        "pub_date": i.pub_date.isoformat() if i.pub_date else None,
        "thumb_url": i.thumb_url, "description": i.description,
        "trend_volume": i.trend_volume,
        "extra_links": list(i.extra_links),
        "trend_growth_pct": i.trend_growth_pct,
        "trend_related": list(i.trend_related),
        "trend_articles": [list(x) for x in i.trend_articles],
        "trend_categories": list(i.trend_categories),
    }


def _item_from_dict(d: dict) -> NewsItem:
    pd = d.get("pub_date")
    return NewsItem(
        guid=d["guid"], title=d["title"], link=d["link"], source=d.get("source"),
        pub_date=datetime.fromisoformat(pd) if pd else None,
        thumb_url=d.get("thumb_url"), description=d.get("description"),
        trend_volume=int(d.get("trend_volume") or 0),
        extra_links=tuple(d.get("extra_links") or ()),
        trend_growth_pct=int(d.get("trend_growth_pct") or 0),
        trend_related=tuple(d.get("trend_related") or ()),
        trend_articles=tuple(tuple(x) for x in (d.get("trend_articles") or ())),
        trend_categories=tuple(int(x) for x in (d.get("trend_categories") or ())),
    )


def _save_cache(path: Path, region: str, items: list[NewsItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "region": region.upper(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "items": [_item_to_dict(i) for i in items],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_cache(path: Path) -> tuple[float, list[NewsItem]] | None:
    """(yaş_dakika, items) ya da None. Bozuk dosya yok sayılır."""
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(raw["fetched_at"])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        items = [_item_from_dict(d) for d in raw.get("items", [])]
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.warning(f"trending_now önbellek okunamadı ({path.name}): {e}")
        return None
    age = (datetime.now(timezone.utc) - fetched).total_seconds() / 60.0
    return age, items


# --- RSS yedeği ---------------------------------------------------------------

_RSS_URL = "https://trends.google.com/trending/rss"
_RSS_NS = {"ht": "https://trends.google.com/trending/rss"}


def _traffic_to_int(raw: str | None) -> int:
    """'200+' → 200, '1.000+' → 1000, '2K+' → 2000. Okunamazsa 0."""
    s = (raw or "").strip().upper().replace("+", "").replace(".", "").replace(",", "")
    mult = 1
    if s.endswith("K"):
        mult, s = 1000, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000, s[:-1]
    try:
        return int(float(s)) * mult
    except ValueError:
        return 0


def _rss_fallback(region: str, *, timeout_s: int = 10) -> list[NewsItem]:
    """Resmi RSS ucu: ~10 trend, her birinin ilk haberi. Hata → []."""
    from xml.etree import ElementTree as ET
    try:
        r = requests.get(f"{_RSS_URL}?geo={region.upper()}", timeout=timeout_s,
                         headers={"User-Agent": _UA})
        if r.status_code != 200:
            logger.warning(f"trending_now RSS yedeği HTTP {r.status_code}")
            return []
        root = ET.fromstring(r.text)
    except (requests.RequestException, ET.ParseError) as e:
        logger.warning(f"trending_now RSS yedeği başarısız: {e}")
        return []
    out: list[NewsItem] = []
    for it in root.iter("item"):
        term = (it.findtext("title") or "").strip()
        news = it.findall("ht:news_item", _RSS_NS)
        if not term or not news:
            continue
        first = news[0]
        url = (first.findtext("ht:news_item_url", namespaces=_RSS_NS) or "").strip()
        title = (first.findtext("ht:news_item_title", namespaces=_RSS_NS) or "").strip()
        if not url or not title:
            continue
        volume = _traffic_to_int(it.findtext("ht:approx_traffic", namespaces=_RSS_NS))
        others = [(n.findtext("ht:news_item_title", namespaces=_RSS_NS) or "").strip()
                  for n in news[1:3]]
        entry = TrendingEntry(term=term, volume=volume, growth_pct=0, started_at=None,
                              category_ids=(), breakdown=(term,), news_ids=())
        others_src = [(n.findtext("ht:news_item_source", namespaces=_RSS_NS) or "",
                       (n.findtext("ht:news_item_title", namespaces=_RSS_NS) or "").strip())
                      for n in news[1:3]]
        out.append(NewsItem(
            guid=url, title=title, link=url,
            source=(first.findtext("ht:news_item_source", namespaces=_RSS_NS) or None),
            pub_date=None,
            thumb_url=(first.findtext("ht:news_item_picture", namespaces=_RSS_NS)
                       or it.findtext("ht:picture", namespaces=_RSS_NS) or None),
            description=_describe(entry, others),
            trend_volume=volume,
            trend_related=(term,),
            trend_articles=tuple((s, t) for s, t in others_src if t),
            extra_links=tuple(
                (n.findtext("ht:news_item_url", namespaces=_RSS_NS) or "").strip()
                for n in news[1:3]
                if (n.findtext("ht:news_item_url", namespaces=_RSS_NS) or "").strip()),
        ))
    return out


# --- dış yüz ------------------------------------------------------------------

# Önbelleğe kaç trend yazılacağı ÇAĞIRANIN ayarı DEĞİLDİR: önbellek bölge
# başına paylaşılır, çağıran küçültürse diğer tüketici aç kalır. Masa 60 satır
# gösteriyor diye boru hattının havuzu 60'a inemez.
#
# 200: dar dikey hacme göre kesilmiş ilk 40'ta görünmüyordu (TR hacminin %64'ü
# spor). Aynı sayı fetch_trending_articles'ın alt-çağrı sayısı ama hepsi tek
# HTTP isteğinde gider ve önbellek 30 dk tutar.
_FETCH_MAX_ENTRIES = 200


def _apply_channel_filters(
    items: list[NewsItem], *, min_volume: int, vertical: str | None,
) -> list[NewsItem]:
    """Kanal ayarlarını OKUMA anında uygula.

    Önbellek dosyası bölge başınadır (``trending_now_<region>.json``), kanal
    başına değil. Süzgeci çekim anında uygularsak, aynı bölgede koşan ikinci
    kanal 30 dk boyunca birincinin süzülmüş listesini görür: dikeyi farklıysa
    boş, tabanı düşükse eksik. Bu yüzden önbellek HAM dolar, süzme burada
    yapılır.
    """
    from short_bot.trends.verticals import matches
    return [i for i in items
            if i.trend_volume >= min_volume
            and matches(i.trend_categories, vertical)]


def fetch_trending_items(
    region: str,
    *,
    language: str,
    cache_dir: Path,
    max_age_minutes: float = 30.0,
    min_volume: int = 1000,
    vertical: str | None = None,
    limit: int | None = None,
    timeout_s: int = 15,
    log: logging.Logger | None = None,
) -> list[NewsItem]:
    """Pipeline'ın çağırdığı tek giriş. Sıra: taze önbellek → API → RSS yedeği →
    bayat önbellek → []. Hiçbir durumda hata fırlatmaz.

    Önbellek HAM doldurulur (hacim tabanı ve dikey uygulanmadan); kanal
    süzgeçleri okuma anında ``_apply_channel_filters`` ile geçilir — bkz.
    oradaki gerekçe.

    ``limit`` çağıranın KAÇ SATIR istediğidir (masa 60 gösterir) ve süzgeçten
    SONRA uygulanır; önbelleğe yazılan havuzu KÜÇÜLTMEZ — bkz.
    ``_FETCH_MAX_ENTRIES``.

    Yedek (RSS) sonucu önbelleğe YAZILMAZ: bir sonraki koşu API'yi yeniden
    denesin. Dikeyi olan kanalda RSS yedeği HİÇ kullanılmaz — RSS'te kategori
    bilgisi yok, vermek "her şey"e geri dönmek olur.
    """
    log = log or logger
    region = region.upper()
    path = Path(cache_dir) / f"trending_now_{region.lower()}.json"
    cached = _load_cache(path)
    if cached is not None and cached[0] < max_age_minutes and cached[1]:
        picked = _apply_channel_filters(cached[1], min_volume=min_volume,
                                        vertical=vertical)
        log.info(f"  [trending_now] önbellek ({cached[0]:.0f} dk) → "
                 f"{len(cached[1])} haber / {len(picked)} süzgeç sonrası")
        return picked[:limit] if limit else picked

    items: list[NewsItem] = []
    try:
        entries = fetch_trending_now(region, language=language, timeout_s=timeout_s)
        picked_entries = sorted(
            (e for e in entries if e.news_ids),
            key=lambda e: e.volume, reverse=True,
        )[:_FETCH_MAX_ENTRIES]
        arts = fetch_trending_articles(picked_entries, language=language,
                                       region=region,
                                       timeout_s=timeout_s) if picked_entries else {}
        items = trending_as_news_items(picked_entries, arts, min_volume=0)
        log.info(f"  [trending_now] region={region} {len(entries)} trend / "
                 f"{len(picked_entries)} haberli / {len(items)} haber")
    except Exception as e:  # noqa: BLE001 — ağ, HTTP, biçim: hepsi yedeğe düşer
        log.warning(f"  [trending_now] API başarısız ({type(e).__name__}: "
                    f"{str(e)[:200]}) → RSS yedeği")
        items = []

    if items:
        _save_cache(path, region, items)
        out = _apply_channel_filters(items, min_volume=min_volume, vertical=vertical)
        log.info(f"  [trending_now] süzgeç sonrası {len(out)} aday"
                 f"{f' (dikey={vertical})' if vertical else ''}")
        return out[:limit] if limit else out

    if vertical:
        log.info("  [trending_now] RSS yedeği dikeyli kanalda KULLANILMAZ "
                 "(kategori bilgisi yok) → aday yok")
    else:
        fallback = [i for i in _rss_fallback(region) if i.trend_volume >= min_volume]
        if fallback:
            fallback.sort(key=lambda i: i.trend_volume, reverse=True)
            log.info(f"  [trending_now] RSS yedeği → {len(fallback)} haber")
            return fallback[:limit] if limit else fallback
    if cached is not None and cached[1]:
        picked = _apply_channel_filters(cached[1], min_volume=min_volume,
                                        vertical=vertical)
        log.info(f"  [trending_now] bayat önbellek ({cached[0]:.0f} dk) → "
                 f"{len(picked)} aday")
        return picked[:limit] if limit else picked
    log.info("  [trending_now] hiçbir kaynaktan veri yok")
    return []
