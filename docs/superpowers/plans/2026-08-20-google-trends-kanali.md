# Google Trends gündem kanalı — uygulama planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Hedef:** Google Trends "Trending Now" listesindeki (bölge seçilebilir) en çok aranan haberlerden, mevcut 6 saniyelik kart hattıyla short üreten yeni `content_source: trends` kaynağı ve `gundem` kanalı.

**Mimari:** `trends/trending_now.py` iç `batchexecute` API'sinden trendleri + her trendin haberlerini tek HTTP isteğiyle çeker, `NewsItem` listesine çevirir (hacim sıralı, `trend_volume` alanı). `_run_rss` `[1/8]` adımında kaynağa göre dallanır; puanlayıcı trend kanalında "hikâyesiz fayda araması" eleyen ayrı prompt kullanır; seçim `select_by_volume` ile eşiği geçenlerden en yüksek hacimli. Geri kalan 7 adım (dedup, senaryo, görsel, render, yükleme, öğrenme) dokunulmadan çalışır.

**Teknoloji:** Python 3.14, `requests`, `xml.etree` (RSS yedeği), dataclass, pytest (`python -m pytest`), Flask panel (Jinja2), YAML kanal config.

Spec: `docs/superpowers/specs/2026-08-20-google-trends-kanali-design.md`
Fikstürler (gerçek API yanıtı, 2026-08-20 kaydı): `tests/fixtures/trending_now_tr.txt` (181 trend), `tests/fixtures/trending_articles_tr.txt` (25 alt çağrı, kimlik `"0"`…`"24"`, `"13"` ve `"24"` boş).

---

## Dosya haritası

| dosya | sorumluluk |
|---|---|
| `src/short_bot/models.py` (değişir) | `NewsItem.trend_volume: int = 0` |
| `src/short_bot/trends/trending_now.py` (yeni) | batchexecute istemcisi, ayrıştırıcılar, NewsItem dönüşümü, önbellek, RSS yedeği |
| `src/short_bot/scorer.py` (değişir) | `_TREND_PROMPT_TEMPLATES`, `build_scoring_prompt` dallanması, `select_by_volume` |
| `src/short_bot/config.py` (değişir) | `trends_region` alanı, `content_source` izin listesi, yükle/kaydet |
| `src/short_bot/pipeline.py` (değişir) | `[1/8]` kaynak dallanması, hacimli seçim, log |
| `src/short_bot/web/routes/channel_edit.py` (değişir) | izin listesi + `trends_region` taşıma |
| `src/short_bot/web/templates/channels/edit.html.j2` (değişir) | radyo seçeneği + bölge seçici |
| `config/channels/gundem.yaml` (yeni) | kanal |
| `tests/test_trends_trending_now.py`, `tests/test_scorer_trends.py`, `tests/test_pipeline_trends.py`, `tests/test_config_trends.py`, `tests/test_web_channel_edit_trends.py` (yeni) | testler |

Not: `docs/superpowers` gitignore'da ama takipli; plan/spec eklerken `git add -f`.

---

### Task 1: `NewsItem.trend_volume`

**Files:**
- Modify: `src/short_bot/models.py:14-21`
- Test: `tests/test_models.py`

- [ ] **Step 1: Başarısız testi yaz** — `tests/test_models.py` sonuna ekle:

```python
def test_news_item_trend_volume_defaults_to_zero():
    from short_bot.models import NewsItem
    item = NewsItem(guid="g", title="t", link="l", source=None,
                    pub_date=None, thumb_url=None, description=None)
    assert item.trend_volume == 0


def test_news_item_trend_volume_is_carried():
    from short_bot.models import NewsItem
    item = NewsItem(guid="g", title="t", link="l", source=None,
                    pub_date=None, thumb_url=None, description=None,
                    trend_volume=50000)
    assert item.trend_volume == 50000
```

- [ ] **Step 2: Başarısız olduğunu gör**

Run: `python -m pytest tests/test_models.py -q -k trend_volume`
Expected: FAIL — `AttributeError: 'NewsItem' object has no attribute 'trend_volume'` ve `TypeError: unexpected keyword argument 'trend_volume'`

- [ ] **Step 3: Alanı ekle** — `src/short_bot/models.py` `NewsItem`:

```python
@dataclass(frozen=True)
class NewsItem:
    guid: str
    title: str
    link: str
    source: str | None
    pub_date: datetime | None
    thumb_url: str | None
    description: str | None
    # trend_volume: Google Trends kaynağında arama hacmi (50000 gibi). Seçim
    # sırası bu alana dayanır (hacim sıralı + AI kapısı). RSS/feed kaynaklarında
    # 0 kalır; varsayılanlı olduğu için mevcut kurucular kırılmaz.
    trend_volume: int = 0
```

- [ ] **Step 4: Testler geçsin**

Run: `python -m pytest tests/test_models.py tests/test_dedup.py tests/test_pipeline.py -q`
Expected: hepsi PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/models.py tests/test_models.py
git commit -m "feat(trends): NewsItem.trend_volume alanı (varsayılan 0)"
```

---

### Task 2: Ayrıştırıcılar — `parse_trending_response`, `parse_articles_response`

**Files:**
- Create: `src/short_bot/trends/trending_now.py`
- Test: `tests/test_trends_trending_now.py`

- [ ] **Step 1: Başarısız testleri yaz** — `tests/test_trends_trending_now.py`:

```python
"""short_bot.trends.trending_now — Google Trends 'Trending Now' iç API istemcisi.

Fikstürler 2026-08-20'de gerçek API'den kaydedildi (bkz. spec)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

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
    import json
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
```

- [ ] **Step 2: Başarısız olduğunu gör**

Run: `python -m pytest tests/test_trends_trending_now.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'short_bot.trends.trending_now'`

- [ ] **Step 3: Modülü ayrıştırıcılarla oluştur** — `src/short_bot/trends/trending_now.py`:

```python
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
```

- [ ] **Step 4: Testler geçsin**

Run: `python -m pytest tests/test_trends_trending_now.py -q`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/trends/trending_now.py tests/test_trends_trending_now.py
git commit -m "feat(trends): Trending Now batchexecute yanıt ayrıştırıcıları"
```

---

### Task 3: HTTP çağrıları — `fetch_trending_now`, `fetch_trending_articles`

**Files:**
- Modify: `src/short_bot/trends/trending_now.py`
- Test: `tests/test_trends_trending_now.py`

- [ ] **Step 1: Başarısız testleri yaz** — dosyanın sonuna ekle:

```python
# --- HTTP çağrıları -----------------------------------------------------------

class _Resp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_fetch_trending_now_posts_expected_payload(trends_text, monkeypatch):
    import requests as _rq
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
```

Dosyanın başına `import json` ve `import requests` ekle.

- [ ] **Step 2: Başarısız olduğunu gör**

Run: `python -m pytest tests/test_trends_trending_now.py -q`
Expected: 4 FAIL — `AttributeError: module ... has no attribute 'fetch_trending_now'`

- [ ] **Step 3: Çağrıları ekle** — `trending_now.py`, ayrıştırıcıların altına:

```python
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
```

- [ ] **Step 4: Testler geçsin**

Run: `python -m pytest tests/test_trends_trending_now.py -q`
Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/trends/trending_now.py tests/test_trends_trending_now.py
git commit -m "feat(trends): trend listesi + haberler tek batchexecute isteğiyle"
```

---

### Task 4: `trending_as_news_items`

**Files:**
- Modify: `src/short_bot/trends/trending_now.py`
- Test: `tests/test_trends_trending_now.py`

- [ ] **Step 1: Başarısız testleri yaz** — sona ekle:

```python
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
```

- [ ] **Step 2: Başarısız olduğunu gör**

Run: `python -m pytest tests/test_trends_trending_now.py -q -k as_news_items`
Expected: 3 FAIL — `ImportError: cannot import name 'trending_as_news_items'`

- [ ] **Step 3: Dönüşümü ekle** — `trending_now.py` sonuna:

```python
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
        )
        prev = best.get(item.guid)
        if prev is None or item.trend_volume > prev.trend_volume:
            best[item.guid] = item
    return sorted(best.values(), key=lambda i: i.trend_volume, reverse=True)
```

- [ ] **Step 4: Testler geçsin**

Run: `python -m pytest tests/test_trends_trending_now.py -q`
Expected: 12 PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/trends/trending_now.py tests/test_trends_trending_now.py
git commit -m "feat(trends): trendleri hacim sıralı NewsItem listesine çevir"
```

---

### Task 5: Dış yüz — `fetch_trending_items` (önbellek + RSS yedeği)

**Files:**
- Modify: `src/short_bot/trends/trending_now.py`
- Test: `tests/test_trends_trending_now.py`

- [ ] **Step 1: Başarısız testleri yaz** — sona ekle:

```python
# --- fetch_trending_items: önbellek + yedek -----------------------------------

def _rss_xml(rows):
    """rows: (term, traffic, news_title, url, source, picture)"""
    items = ""
    for term, traffic, nt, url, src, pic in rows:
        items += (
            f"<item><title>{term}</title><ht:approx_traffic>{traffic}</ht:approx_traffic>"
            f"<pubDate>Thu, 20 Aug 2026 00:20:00 -0700</pubDate>"
            f"<ht:picture>{pic}</ht:picture>"
            f"<ht:news_item><ht:news_item_title>{nt}</ht:news_item_title>"
            f"<ht:news_item_url>{url}</ht:news_item_url>"
            f"<ht:news_item_source>{src}</ht:news_item_source>"
            f"<ht:news_item_picture>{pic}</ht:news_item_picture></ht:news_item></item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0">'
            f'<channel>{items}</channel></rss>')


def test_fetch_items_happy_path_writes_cache(trends_text, articles_text, tmp_path, monkeypatch):
    from short_bot.trends import trending_now as tn
    calls = []

    def _post(url, data=None, headers=None, timeout=None):
        rpc = json.loads(data["f.req"])[0][0][0]
        calls.append(rpc)
        return _Resp(trends_text if rpc == "i0OFE" else articles_text)
    monkeypatch.setattr(tn.requests, "post", _post)

    items = tn.fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                    max_entries=25)
    assert calls == ["i0OFE", "w4opAf"]
    assert items and items[0].trend_volume == 100000
    assert items == sorted(items, key=lambda i: i.trend_volume, reverse=True)
    assert (tmp_path / "trending_now_tr.json").exists()


def test_fetch_items_uses_fresh_cache_without_network(tmp_path, monkeypatch):
    from short_bot.trends import trending_now as tn
    cached = [tn.NewsItem(guid="https://x/1", title="Önbellek", link="https://x/1",
                          source="S", pub_date=None, thumb_url=None,
                          description="d", trend_volume=7000)]
    tn._save_cache(tmp_path / "trending_now_tr.json", "TR", cached)

    def _boom(*a, **k):
        raise AssertionError("ağ çağrısı olmamalı")
    monkeypatch.setattr(tn.requests, "post", _boom)

    items = tn.fetch_trending_items("TR", language="tr", cache_dir=tmp_path)
    assert [i.guid for i in items] == ["https://x/1"]
    assert items[0].trend_volume == 7000


def test_fetch_items_falls_back_to_rss_when_api_fails(tmp_path, monkeypatch):
    from short_bot.trends import trending_now as tn
    monkeypatch.setattr(tn.requests, "post",
                        lambda *a, **k: _Resp("down", status=503))
    xml = _rss_xml([("izzet özilhan", "200+", "Ünlü iş insanı kaza yaptı",
                     "https://sozcu/kaza", "Sözcü", "https://img/1.jpg"),
                    ("armutlu", "1000+", "Baba kız İmralı'ya sürüklendi",
                     "https://sozcu/armutlu", "Sözcü", "https://img/2.jpg")])
    monkeypatch.setattr(tn.requests, "get", lambda *a, **k: _Resp(xml))

    items = tn.fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                    min_volume=100)
    assert [i.trend_volume for i in items] == [1000, 200]
    assert items[0].guid == "https://sozcu/armutlu"
    assert items[0].title == "Baba kız İmralı'ya sürüklendi"
    assert items[0].thumb_url == "https://img/2.jpg"
    assert "Google Trends" in items[0].description
    # yedek veri önbelleğe YAZILMAZ (bir sonraki koşu API'yi yeniden denesin)
    assert not (tmp_path / "trending_now_tr.json").exists()


def test_fetch_items_returns_stale_cache_when_everything_fails(tmp_path, monkeypatch):
    from short_bot.trends import trending_now as tn
    cached = [tn.NewsItem(guid="https://x/eski", title="Eski", link="https://x/eski",
                          source=None, pub_date=None, thumb_url=None,
                          description=None, trend_volume=3000)]
    tn._save_cache(tmp_path / "trending_now_tr.json", "TR", cached)
    monkeypatch.setattr(tn.requests, "post", lambda *a, **k: _Resp("x", status=500))
    monkeypatch.setattr(tn.requests, "get", lambda *a, **k: _Resp("x", status=500))

    items = tn.fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                    max_age_minutes=0)   # önbellek bayat sayılsın
    assert [i.guid for i in items] == ["https://x/eski"]


def test_fetch_items_returns_empty_when_no_source_and_no_cache(tmp_path, monkeypatch):
    from short_bot.trends import trending_now as tn
    monkeypatch.setattr(tn.requests, "post", lambda *a, **k: _Resp("x", status=500))
    monkeypatch.setattr(tn.requests, "get", lambda *a, **k: _Resp("x", status=500))
    assert tn.fetch_trending_items("TR", language="tr", cache_dir=tmp_path) == []
```

- [ ] **Step 2: Başarısız olduğunu gör**

Run: `python -m pytest tests/test_trends_trending_now.py -q -k fetch_items`
Expected: 5 FAIL — `AttributeError: ... has no attribute 'fetch_trending_items'` / `_save_cache`

- [ ] **Step 3: Dış yüzü ekle** — `trending_now.py` sonuna:

```python
# --- önbellek -----------------------------------------------------------------

def _item_to_dict(i: NewsItem) -> dict:
    return {
        "guid": i.guid, "title": i.title, "link": i.link, "source": i.source,
        "pub_date": i.pub_date.isoformat() if i.pub_date else None,
        "thumb_url": i.thumb_url, "description": i.description,
        "trend_volume": i.trend_volume,
    }


def _item_from_dict(d: dict) -> NewsItem:
    pd = d.get("pub_date")
    return NewsItem(
        guid=d["guid"], title=d["title"], link=d["link"], source=d.get("source"),
        pub_date=datetime.fromisoformat(pd) if pd else None,
        thumb_url=d.get("thumb_url"), description=d.get("description"),
        trend_volume=int(d.get("trend_volume") or 0),
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
        out.append(NewsItem(
            guid=url, title=title, link=url,
            source=(first.findtext("ht:news_item_source", namespaces=_RSS_NS) or None),
            pub_date=None,
            thumb_url=(first.findtext("ht:news_item_picture", namespaces=_RSS_NS)
                       or it.findtext("ht:picture", namespaces=_RSS_NS) or None),
            description=_describe(entry, others),
            trend_volume=volume,
        ))
    return out


# --- dış yüz ------------------------------------------------------------------

def fetch_trending_items(
    region: str,
    *,
    language: str,
    cache_dir: Path,
    max_age_minutes: float = 30.0,
    min_volume: int = 1000,
    max_entries: int = 40,
    timeout_s: int = 15,
    log: logging.Logger | None = None,
) -> list[NewsItem]:
    """Pipeline'ın çağırdığı tek giriş. Sıra: taze önbellek → API → RSS yedeği →
    bayat önbellek → []. Hiçbir durumda hata fırlatmaz.

    Yedek (RSS) sonucu önbelleğe YAZILMAZ: bir sonraki koşu API'yi yeniden
    denesin; aksi hâlde 30 dk boyunca 10 trendlik zayıf listeye kilitlenir.
    """
    log = log or logger
    region = region.upper()
    path = Path(cache_dir) / f"trending_now_{region.lower()}.json"
    cached = _load_cache(path)
    if cached is not None and cached[0] < max_age_minutes and cached[1]:
        log.info(f"  [trending_now] önbellek ({cached[0]:.0f} dk) → {len(cached[1])} haber")
        return cached[1]

    items: list[NewsItem] = []
    try:
        entries = fetch_trending_now(region, language=language, timeout_s=timeout_s)
        picked = sorted(
            (e for e in entries if e.volume >= min_volume and e.news_ids),
            key=lambda e: e.volume, reverse=True,
        )[:max_entries]
        arts = fetch_trending_articles(picked, language=language, region=region,
                                       timeout_s=timeout_s) if picked else {}
        items = trending_as_news_items(picked, arts, min_volume=min_volume)
        log.info(f"  [trending_now] region={region} {len(entries)} trend / "
                 f"{len(picked)} hacim≥{min_volume} / {len(items)} haberli")
    except Exception as e:  # noqa: BLE001 — ağ, HTTP, biçim: hepsi yedeğe düşer
        log.warning(f"  [trending_now] API başarısız ({type(e).__name__}: "
                    f"{str(e)[:200]}) → RSS yedeği")
        items = []

    if items:
        _save_cache(path, region, items)
        return items

    fallback = [i for i in _rss_fallback(region) if i.trend_volume >= min_volume]
    if fallback:
        fallback.sort(key=lambda i: i.trend_volume, reverse=True)
        log.info(f"  [trending_now] RSS yedeği → {len(fallback)} haber")
        return fallback
    if cached is not None and cached[1]:
        log.info(f"  [trending_now] bayat önbellek ({cached[0]:.0f} dk) → {len(cached[1])} haber")
        return cached[1]
    log.info("  [trending_now] hiçbir kaynaktan veri yok")
    return []
```

- [ ] **Step 4: Testler geçsin**

Run: `python -m pytest tests/test_trends_trending_now.py -q`
Expected: 17 PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/trends/trending_now.py tests/test_trends_trending_now.py
git commit -m "feat(trends): fetch_trending_items — önbellek, RSS yedeği, bayat önbellek"
```

---

### Task 6: Config — `trends_region` + `content_source: trends`

**Files:**
- Modify: `src/short_bot/config.py:358-361` (alan), `:443-447` (izin), `:530-540` (yükle), `:586-587` (kaydet)
- Test: `tests/test_config_trends.py`

- [ ] **Step 1: Başarısız testleri yaz** — `tests/test_config_trends.py`:

```python
"""content_source: trends + trends_region yükle/kaydet."""
from __future__ import annotations

import pytest
import yaml

from short_bot.config import load_channel, save_channel

_BASE = """\
slug: gundem
name: Gündem
keywords: []
language: tr
schedule_cron: 0 */2 * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 25
template: broadcast
colors:
  primary: '#ed1c2e'
  accent: '#ffea1c'
  bg_gradient: ['#2a3a5e', '#0a1428']
handle: '@gundem'
output_dir: output/gundem
enabled: true
"""


def _write(tmp_path, extra: str):
    p = tmp_path / "gundem.yaml"
    p.write_text(_BASE + extra, encoding="utf-8")
    return p


def test_trends_source_loads_without_keywords(tmp_path):
    cfg = load_channel(_write(tmp_path, "content_source: trends\ntrends_region: TR\n"))
    assert cfg.content_source == "trends"
    assert cfg.trends_region == "TR"
    assert cfg.keywords == []


def test_trends_region_defaults_to_none_and_is_uppercased(tmp_path):
    cfg = load_channel(_write(tmp_path, "content_source: trends\n"))
    assert cfg.trends_region is None
    cfg2 = load_channel(_write(tmp_path, "content_source: trends\ntrends_region: de\n"))
    assert cfg2.trends_region == "DE"


def test_invalid_trends_region_rejected(tmp_path):
    with pytest.raises(ValueError, match="trends_region"):
        load_channel(_write(tmp_path, "content_source: trends\ntrends_region: Almanya\n"))


def test_rss_source_still_requires_keywords(tmp_path):
    with pytest.raises(ValueError, match="keywords"):
        load_channel(_write(tmp_path, ""))


def test_save_roundtrip_keeps_trends_fields(tmp_path):
    p = _write(tmp_path, "content_source: trends\ntrends_region: DE\n")
    cfg = load_channel(p)
    out = tmp_path / "out.yaml"
    save_channel(out, cfg)
    raw = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert raw["content_source"] == "trends"
    assert raw["trends_region"] == "DE"
    assert load_channel(out).trends_region == "DE"


def test_save_omits_trends_region_when_unset(tmp_path):
    cfg = load_channel(_write(tmp_path, "content_source: trends\n"))
    out = tmp_path / "out.yaml"
    save_channel(out, cfg)
    assert "trends_region" not in yaml.safe_load(out.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Başarısız olduğunu gör**

Run: `python -m pytest tests/test_config_trends.py -q`
Expected: FAIL — `ValueError: content_source must be 'rss', 'generator', 'feed' or 'curated', got 'trends'`

- [ ] **Step 3: Config'i güncelle** — `src/short_bot/config.py`:

(a) `ChannelConfig` içinde `saga_window_days: int = 14` satırının hemen altına:

```python
    # trends_region: content_source="trends" kanalında Google Trends bölgesi
    # (ISO 3166-1 alpha-2: TR, DE, ES…). None ise dilden türetilir
    # (locale.trend_region_for). Dil ile bölge bağımsız: language=de +
    # trends_region=AT Avusturya gündemini Almanca anlatır.
    trends_region: str | None = None
```

(b) `content_source: Literal["rss", "generator", "feed", "curated"] = "rss"` →

```python
    content_source: Literal["rss", "generator", "feed", "curated", "trends"] = "rss"
```

(c) `load_channel` izin kontrolü:

```python
    content_source = data.get("content_source", "rss")
    if content_source not in ("rss", "generator", "feed", "curated", "trends"):
        raise ValueError(
            f"content_source must be 'rss', 'generator', 'feed', 'curated' or 'trends', "
            f"got {content_source!r}"
        )

    trends_region_raw = data.get("trends_region")
    trends_region: str | None = None
    if trends_region_raw:
        trends_region = str(trends_region_raw).strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", trends_region):
            raise ValueError(
                f"channel {slug!r}: trends_region must be a 2-letter ISO region "
                f"code (TR, DE, ES…), got {trends_region_raw!r}"
            )
```

`re` modülü dosyada import edilmiş mi kontrol et (`SLUG_RE` var, muhtemelen `import re` mevcut); yoksa en üste ekle.

(d) `return ChannelConfig(` içinde `saga_window_days=...` satırının altına:

```python
        trends_region=trends_region,
```

(e) `save_channel` içinde `if cfg.content_source != "rss":` bloğunun altına:

```python
    if cfg.trends_region:
        data["trends_region"] = cfg.trends_region
```

- [ ] **Step 4: Testler geçsin**

Run: `python -m pytest tests/test_config_trends.py tests/test_config.py tests/test_config_feed.py -q`
Expected: hepsi PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/config.py tests/test_config_trends.py
git commit -m "feat(trends): content_source=trends ve trends_region kanal ayarı"
```

---

### Task 7: Scorer — trend promptu + `select_by_volume`

**Files:**
- Modify: `src/short_bot/scorer.py:33-131` (şablonlar), `:133-189` (`build_scoring_prompt`), `:292-295` (seçim)
- Test: `tests/test_scorer_trends.py`

- [ ] **Step 1: Başarısız testleri yaz** — `tests/test_scorer_trends.py`:

```python
"""Trend kanalı: puanlayıcı kapısı ve hacimli seçim."""
from __future__ import annotations

from short_bot.models import NewsItem, ScoredItem


def _channel(content_source="trends", language="tr", keywords=None):
    from short_bot.config import ChannelConfig
    return ChannelConfig(
        slug="gundem", name="Gündem", keywords=keywords or [],
        rss_locale="hl=tr&gl=TR&ceid=TR:tr", schedule_cron="0 */2 * * *",
        duration_s=6, min_score=6.0, max_candidates_per_run=25,
        template="broadcast", colors={"primary": "#fff", "accent": "#000",
                                        "bg_gradient": ["#111", "#222"]},
        handle="@g", output_dir="out", enabled=True, language=language,
        content_source=content_source,
    )


def _item(guid, title, desc=None, volume=0):
    return NewsItem(guid=guid, title=title, link=guid, source=None, pub_date=None,
                    thumb_url=None, description=desc, trend_volume=volume)


# --- prompt -------------------------------------------------------------------

def test_trend_prompt_has_no_center_rule_and_lists_volume():
    from short_bot.scorer import build_scoring_prompt
    items = [_item("https://x/1", "Marmara 8 saatte 36 kez sallandı",
                   desc="Google Trends · 100.000 arama · +%1.000 · istanbul deprem",
                   volume=100000)]
    p = build_scoring_prompt(items, channel=_channel())
    assert "MERKEZ KURALI" not in p
    assert "KONU DIŞI" not in p
    assert "hava durumu" in p            # fayda-araması kapısı açıkça sayılıyor
    assert "100.000 arama" in p          # description satırda
    assert "guid=https://x/1" in p
    assert '"scores"' in p               # JSON sözleşmesi aynı


def test_trend_prompt_follows_channel_language():
    from short_bot.scorer import build_scoring_prompt
    items = [_item("g", "Tornado trifft Mannheim")]
    p_de = build_scoring_prompt(items, channel=_channel(language="de"))
    assert "Wetter" in p_de and "MERKEZ KURALI" not in p_de
    p_es = build_scoring_prompt(items, channel=_channel(language="es"))
    assert "weather" in p_es             # paket yoksa İngilizce


def test_rss_prompt_unchanged_for_non_trend_channels():
    from short_bot.scorer import build_scoring_prompt
    items = [_item("g", "Galatasaray kazandı")]
    p = build_scoring_prompt(items, channel=_channel(content_source="rss",
                                                      keywords=["galatasaray"]))
    assert "MERKEZ KURALI" in p


def test_trend_prompt_still_appends_category_and_saga_blocks():
    from dataclasses import replace
    from short_bot.scorer import build_scoring_prompt
    ch = replace(_channel(), categories=["spor", "ekonomi"], saga_penalty_per_repeat=1.0)
    p = build_scoring_prompt([_item("g", "x")], channel=ch)
    assert '"category"' in p and '"subject"' in p


# --- select_by_volume ---------------------------------------------------------

def _scored(guid, score, volume):
    return ScoredItem(item=_item(guid, guid, volume=volume), score=score, reasoning="")


def test_select_by_volume_prefers_volume_among_passing():
    from short_bot.scorer import select_by_volume
    scored = [_scored("dusuk_hacim_yuksek_puan", 9.5, 2000),
              _scored("yuksek_hacim", 7.0, 100000),
              _scored("elenen", 3.0, 500000)]
    out = select_by_volume(scored, min_score=6.0, n=3)
    assert [s.item.guid for s in out] == ["yuksek_hacim", "dusuk_hacim_yuksek_puan"]


def test_select_by_volume_ties_broken_by_score_and_respects_n():
    from short_bot.scorer import select_by_volume
    scored = [_scored("a", 6.5, 5000), _scored("b", 8.0, 5000), _scored("c", 7.0, 1000)]
    out = select_by_volume(scored, min_score=6.0, n=2)
    assert [s.item.guid for s in out] == ["b", "a"]


def test_select_by_volume_empty_when_none_pass():
    from short_bot.scorer import select_by_volume
    assert select_by_volume([_scored("a", 5.9, 99999)], min_score=6.0) == []
```

- [ ] **Step 2: Başarısız olduğunu gör**

Run: `python -m pytest tests/test_scorer_trends.py -q`
Expected: FAIL — prompt testlerinde `assert "MERKEZ KURALI" not in p` düşer; `ImportError: cannot import name 'select_by_volume'`

- [ ] **Step 3: Scorer'ı güncelle** — `src/short_bot/scorer.py`:

(a) `_PROMPT_TEMPLATES` sözlüğünün kapanışından sonra yeni sözlük:

```python
# Trend kanalı (content_source="trends"): kanalın ÖZNESİ yok, her konu uygun.
# Merkez kuralı uygulanmaz. Kapı tek şeyi eler: arkasında anlatılacak OLAY
# olmayan "fayda araması" (hava durumu, hisse fiyatı, maç hangi kanalda, TV
# program, sınav sonucu sorgusu). Sıralamayı puan DEĞİL arama hacmi yapar
# (select_by_volume); puan yalnız min_score eşiğinde kapı görevi görür.
_TREND_PROMPT_TEMPLATES = {
    "tr": """Sen bir YouTube Shorts gündem kanalının editörüsün. Kanal ülkenin o an
EN ÇOK ARANAN konularını 6 saniyelik tek kartta verir: manşet + 3-4 cümle gövde
+ fotoğraf. Aşağıdaki başlıklar Google Trends'ten geldi; her satırda arama
hacmi ve ilişkili aramalar var.

KANAL: {channel_name}

Her başlığı "bu bir OLAY mı, yoksa sadece bir ARAMA mı?" sorusuyla 0-10 puanla:
- 9-10: Net, anlatılabilir olay; tek kartta özetlenir (deprem uyarısı, kaza,
  zam kararı, transfer teklifi, resmi açıklama, skor + sonuç, gözaltı)
- 7-8: Olay var, biraz bağlam gerekir ama 3-4 cümleye sığar
- 4-6: Olay zayıf, yerel ya da yalnız bir kesimi ilgilendiriyor
- 0-3: FAYDA ARAMASI — arkasında haber yok: hava durumu, hisse fiyatı/grafik,
  döviz/altın kuru sorgusu, "maç hangi kanalda / saat kaçta", TV program ya da
  "son bölüm izle", "ne kadar kazandı / kimdir" (olay yok), sınav sonucu ve
  başvuru tarihi sorguları, ürün/kampanya fiyatı

Başlık ilgi çekici olsa bile OLAY yoksa 0-3 ver; izleyici 6 saniyede "ne oldu?"
sorusunun cevabını almalı. Arama hacmi yüksek diye puanı YÜKSELTME — hacmi
sistem ayrıca kullanıyor, sen yalnız olay var mı yok mu ona bak.

Başlıklar:
{listing}

SADECE şu JSON formatında yanıtla, başka metin yazma:
{{"scores": [{{"guid": "<aynısı>", "score": <0-10>, "reasoning": "<≤200 char, neden bu puan>"}}, ...]}}""",

    "en": """You are the editor of a YouTube Shorts trending-news channel. The channel
turns the country's MOST-SEARCHED topics of the moment into a single 6-second
card: headline + 3-4 sentence body + photo. The headlines below come from
Google Trends; each line carries search volume and related queries.

CHANNEL: {channel_name}

Score each headline 0-10 by asking "is this an EVENT, or just a SEARCH?":
- 9-10: Clear, tellable event that fits one card (earthquake warning, crash,
  pay-rise decision, transfer bid, official statement, score + outcome, arrest)
- 7-8: An event, needs a little context but fits 3-4 sentences
- 4-6: Weak, local, or relevant to a narrow group only
- 0-3: UTILITY SEARCH — no story behind it: weather, stock price/chart,
  currency/gold rate lookup, "what channel / what time is the match", TV
  schedule or "watch latest episode", "how much did X earn / who is X" with no
  event, exam results and application dates, product/deal prices

Even if the headline is catchy, score 0-3 when there is no EVENT; the viewer
must get "what happened?" answered in 6 seconds. Do NOT raise the score for
high search volume — the system uses volume separately; you only judge
whether there is an event.

Headlines:
{listing}

Reply ONLY in this JSON format, no other text:
{{"scores": [{{"guid": "<same>", "score": <0-10>, "reasoning": "<≤200 char, why this score>"}}, ...]}}""",

    "de": """Du bist Redakteur eines YouTube-Shorts-Kanals für aktuelle Trends. Der
Kanal macht aus den MEISTGESUCHTEN Themen des Landes eine einzige 6-Sekunden-
Karte: Schlagzeile + 3-4 Sätze + Foto. Die Schlagzeilen unten stammen aus
Google Trends; jede Zeile trägt Suchvolumen und verwandte Suchanfragen.

KANAL: {channel_name}

Bewerte jede Schlagzeile von 0-10 mit der Frage "ist das ein EREIGNIS oder nur
eine SUCHE?":
- 9-10: Klares, erzählbares Ereignis, passt auf eine Karte (Erdbebenwarnung,
  Unfall, Lohnentscheidung, Transferangebot, offizielle Erklärung, Ergebnis +
  Folge, Festnahme)
- 7-8: Ereignis vorhanden, braucht etwas Kontext, passt aber in 3-4 Sätze
- 4-6: Schwaches, lokales oder nur für eine kleine Gruppe relevantes Ereignis
- 0-3: NUTZSUCHE — keine Geschichte dahinter: Wetter, Aktienkurs/Chart,
  Wechselkurs/Goldpreis, "welcher Sender / wann läuft das Spiel", TV-Programm
  oder "letzte Folge ansehen", "wie viel hat X verdient / wer ist X" ohne
  Ereignis, Prüfungsergebnisse und Bewerbungsfristen, Produkt-/Angebotspreise

Auch bei reizvoller Schlagzeile: ohne EREIGNIS 0-3. Der Zuschauer muss in 6
Sekunden "was ist passiert?" beantwortet bekommen. Erhöhe die Bewertung NICHT
wegen hohen Suchvolumens — das System nutzt das Volumen separat; du beurteilst
nur, ob ein Ereignis vorliegt.

Schlagzeilen:
{listing}

Antworte NUR in diesem JSON-Format, kein anderer Text:
{{"scores": [{{"guid": "<gleich>", "score": <0-10>, "reasoning": "<≤200 char, warum>"}}, ...]}}""",
}
```

(b) `build_scoring_prompt` içinde `listing = ...` ve `template = ...` satırlarını değiştir:

```python
def build_scoring_prompt(
    items: list[NewsItem],
    *,
    channel: "ChannelConfig | None" = None,
    performance_insights: dict | None = None,
) -> str:
    is_trends = channel is not None and channel.content_source == "trends"
    if is_trends:
        # Trend satırında bağlam (hacim + ilişkili aramalar) description'da
        # taşınıyor; model "ajet" gibi tek başına anlamsız terimi böyle çözer.
        listing = "\n".join(
            f"- guid={i.guid} | {i.title}" + (f" — {i.description}" if i.description else "")
            for i in items)
    else:
        listing = "\n".join(f"- guid={i.guid} | {i.title}" for i in items)
    if channel is None:
        ...  # mevcut geriye-uyum bloğu AYNEN kalır
    if is_trends:
        template = _TREND_PROMPT_TEMPLATES.get(channel.language, _TREND_PROMPT_TEMPLATES["en"])
    else:
        template = _PROMPT_TEMPLATES.get(channel.language, _PROMPT_TEMPLATES["en"])
    keywords_str = ", ".join(channel.keywords) if channel.keywords else "(no keywords)"
    base = template.format(
        channel_name=channel.name,
        keywords=keywords_str,
        listing=listing,
    )
    ...  # kategori / saga / insights ekleri AYNEN kalır
```

(`_TREND_PROMPT_TEMPLATES` şablonlarında `{keywords}` yok; `str.format` fazladan anahtarı yok sayar, sorun değil.)

(c) `select_top` fonksiyonunun hemen altına:

```python
def select_by_volume(
    scored: list[ScoredItem], min_score: float, n: int = 1,
) -> list[ScoredItem]:
    """Trend kanalı seçimi: min_score eşiğini geçenler arasından en yüksek
    ARAMA HACMİ (item.trend_volume) önce, eşitlikte puan. Puan burada sıra
    değil KAPI — 'hikâyesiz fayda araması' eşiğin altında kalıp elenir,
    kalanları ülkenin ne aradığı sıralar."""
    above = [s for s in scored if s.score >= min_score]
    above.sort(key=lambda s: (s.item.trend_volume, s.score), reverse=True)
    return above[:n]
```

- [ ] **Step 4: Testler geçsin**

Run: `python -m pytest tests/test_scorer_trends.py tests/test_scorer.py tests/test_scorer_insights_injection.py tests/test_saga_subject.py -q`
Expected: hepsi PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/scorer.py tests/test_scorer_trends.py
git commit -m "feat(trends): trend kanalı için olay/arama kapısı promptu ve hacimli seçim"
```

---

### Task 8: Pipeline — kaynak dallanması + hacimli seçim

**Files:**
- Modify: `src/short_bot/pipeline.py:30-32` (import), `:989-991` (fetch), `:1094-1095` (seçim), `:1135-1136` (log)
- Test: `tests/test_pipeline_trends.py`

- [ ] **Step 1: Başarısız testleri yaz** — `tests/test_pipeline_trends.py`:

```python
"""content_source=trends kanalı _run_rss içinden: fetch_rss yerine
fetch_trending_items, select_top yerine hacimli seçim."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from short_bot.db import init_db
from short_bot.models import NewsItem, ScoredItem


def _channel(tmp_path, *, region=None, language="tr"):
    from short_bot.config import ChannelConfig
    return ChannelConfig(
        slug="gundem", name="Gündem", keywords=[],
        rss_locale="hl=tr&gl=TR&ceid=TR:tr", schedule_cron="0 */2 * * *",
        duration_s=6, min_score=6.0, max_candidates_per_run=25,
        template="broadcast", colors={"primary": "#fff", "accent": "#000",
                                        "bg_gradient": ["#111", "#222"]},
        handle="@g", output_dir=str(tmp_path / "out"), enabled=True,
        language=language, content_source="trends", trends_region=region,
    )


def _settings():
    from short_bot.config import Settings
    return Settings(
        ffmpeg_path="ffmpeg", claude_cli_path="claude",
        playwright_browser="chromium", web_host="127.0.0.1", web_port=5005,
        fuzzy_dedup_threshold=0.85, log_level="INFO",
        claude_models={"default": "haiku", "script": "haiku", "dna": "opus"})


def _item(guid, title, volume):
    return NewsItem(guid=guid, title=title, link=guid, source="S",
                    pub_date=datetime.now(timezone.utc), thumb_url=None,
                    description="Google Trends · …", trend_volume=volume)


def _wire(monkeypatch, pipeline, items, scores: dict[str, float]):
    """Ağ ve üretimi kes; seçilen adayı yakala."""
    seen = {}

    def _fake_fetch_trending(region, **kw):
        seen["region"] = region; seen["language"] = kw.get("language")
        seen["cache_dir"] = kw.get("cache_dir")
        return items

    def _no_rss(*a, **k):
        raise AssertionError("trend kanalında fetch_rss çağrılmamalı")

    monkeypatch.setattr(pipeline, "fetch_trending_items", _fake_fetch_trending)
    monkeypatch.setattr(pipeline, "fetch_rss", _no_rss)
    monkeypatch.setattr(pipeline, "filter_new", lambda eng, items, slug, **k: items)
    monkeypatch.setattr(pipeline, "score_items",
                        lambda items, **k: [ScoredItem(item=i, score=scores[i.guid],
                                                        reasoning="") for i in items])
    monkeypatch.setattr(pipeline, "_apply_trend_boost",
                        lambda scored, **k: scored)
    # Aday döngüsünün ilk adımı: google-news çözümleme + extract. İlk adayda
    # dururuz — seçim sırası bu noktada bellidir.
    monkeypatch.setattr(pipeline, "_is_google_news_url", lambda url: False)

    def _stop(url):
        seen["picked_url"] = url
        raise RuntimeError("dur")
    monkeypatch.setattr(pipeline, "extract_article", _stop)
    return seen


def test_trends_channel_fetches_trends_and_picks_highest_volume(tmp_path, monkeypatch):
    from short_bot import pipeline
    eng = init_db(tmp_path / "x.sqlite")
    ch = _channel(tmp_path)
    items = [_item("https://x/yuksek-puan", "İlginç ama küçük", 2000),
             _item("https://x/deprem", "Marmara sallandı", 100000),
             _item("https://x/hava", "Trabzon hava durumu", 500000)]
    seen = _wire(monkeypatch, pipeline, items,
                 {"https://x/yuksek-puan": 9.5, "https://x/deprem": 7.5, "https://x/hava": 2.0})

    try:
        pipeline._run_rss(channel=ch, run_id=1, log=MagicMock(), eng=eng,
                          settings=_settings(), music_root=tmp_path,
                          templates_dir=Path("templates"), cache_dir=tmp_path)
    except RuntimeError:
        pass
    assert seen["region"] == "TR"                  # dilden türetildi
    assert seen["language"] == "tr"
    assert Path(seen["cache_dir"]) == tmp_path / "trends"
    assert seen["picked_url"] == "https://x/deprem"   # eşiği geçenlerden en yüksek hacim


def test_trends_region_override_wins_over_language(tmp_path, monkeypatch):
    from short_bot import pipeline
    eng = init_db(tmp_path / "x.sqlite")
    ch = _channel(tmp_path, region="AT", language="de")
    items = [_item("https://x/a", "Tornado", 50000)]
    seen = _wire(monkeypatch, pipeline, items, {"https://x/a": 8.0})
    try:
        pipeline._run_rss(channel=ch, run_id=1, log=MagicMock(), eng=eng,
                          settings=_settings(), music_root=tmp_path,
                          templates_dir=Path("templates"), cache_dir=tmp_path)
    except RuntimeError:
        pass
    assert seen["region"] == "AT"


def test_trends_channel_no_candidates_when_all_gated(tmp_path, monkeypatch):
    from short_bot import pipeline
    eng = init_db(tmp_path / "x.sqlite")
    ch = _channel(tmp_path)
    items = [_item("https://x/hava", "Hava durumu", 500000)]
    _wire(monkeypatch, pipeline, items, {"https://x/hava": 2.0})
    res = pipeline._run_rss(channel=ch, run_id=1, log=MagicMock(), eng=eng,
                            settings=_settings(), music_root=tmp_path,
                            templates_dir=Path("templates"), cache_dir=tmp_path)
    assert res.status == "no_candidates"


def test_trends_channel_empty_source_is_no_candidates(tmp_path, monkeypatch):
    from short_bot import pipeline
    eng = init_db(tmp_path / "x.sqlite")
    ch = _channel(tmp_path)
    _wire(monkeypatch, pipeline, [], {})
    res = pipeline._run_rss(channel=ch, run_id=1, log=MagicMock(), eng=eng,
                            settings=_settings(), music_root=tmp_path,
                            templates_dir=Path("templates"), cache_dir=tmp_path)
    assert res.status == "no_candidates"
```

- [ ] **Step 2: Başarısız olduğunu gör**

Run: `python -m pytest tests/test_pipeline_trends.py -q`
Expected: FAIL — `AttributeError: module 'short_bot.pipeline' has no attribute 'fetch_trending_items'`

- [ ] **Step 3: Pipeline'ı güncelle** — `src/short_bot/pipeline.py`:

(a) import satırları:

```python
from short_bot.fetcher import fetch_rss, fetch_feed_url
from short_bot.trends.trending_now import fetch_trending_items
from short_bot.dedup import filter_new
from short_bot.scorer import score_items, select_top, select_newest_above, select_by_volume
from short_bot.locale import ui_labels_for, trend_region_for
```

(`from short_bot.locale import ui_labels_for` satırını bul ve `trend_region_for` ekle; ayrıca `_apply_trend_boost` içindeki yerel `from short_bot.locale import trend_region_for` importu kalabilir.)

(b) `_run_rss` başı:

```python
    """Existing 8-stage RSS pipeline body, extracted verbatim. Returns RunResult.

    content_source="trends" de bu gövdeyi kullanır: yalnız [1/8] kaynağı ve
    seçim kuralı farklıdır (hacim sıralı + AI kapısı), kalan 7 adım ortak."""
    is_trends = channel.content_source == "trends"
    if is_trends:
        region = (channel.trends_region or trend_region_for(channel.language)).upper()
        log.info(f"[1/8] fetch_trending_now region={region}")
        items = fetch_trending_items(
            region, language=channel.language,
            cache_dir=Path(cache_dir) / "trends", log=log)
    else:
        log.info("[1/8] fetch_rss")
        items = fetch_rss(channel.keywords, channel.rss_locale)
    log.info(f"  → {len(items)} items")
```

(c) seçim:

```python
    if is_trends:
        # Puan kapı, hacim sıra: ülkenin en çok aradığı OLAY önce.
        top_n_candidates = select_by_volume(scored, min_score=channel.min_score,
                                            n=_IMAGE_RETRY_MAX)
    else:
        top_n_candidates = select_top(scored, min_score=channel.min_score,
                                      n=_IMAGE_RETRY_MAX)
```

(d) aday log satırı:

```python
    for attempt, candidate in enumerate(top_n_candidates, 1):
        vol = (f" volume={candidate.item.trend_volume}" if is_trends else "")
        log.info(f"[4-6/8] candidate {attempt}/{len(top_n_candidates)} "
                 f"score={candidate.score:.1f}{vol} | {candidate.item.title[:80]}")
```

- [ ] **Step 4: Testler geçsin**

Run: `python -m pytest tests/test_pipeline_trends.py tests/test_pipeline.py tests/test_pipeline_feed.py tests/test_pipeline_trend_boost.py tests/test_pipeline_saga_penalty.py tests/test_pipeline_category_quota.py -q`
Expected: hepsi PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/pipeline.py tests/test_pipeline_trends.py
git commit -m "feat(trends): _run_rss trend kaynağını çekip hacme göre seçiyor"
```

---

### Task 9: Panel — kaynak seçeneği + bölge seçici

**Files:**
- Modify: `src/short_bot/web/routes/channel_edit.py:456-458`, `:491` civarı
- Modify: `src/short_bot/web/templates/channels/edit.html.j2:1076-1085`
- Test: `tests/test_web_channel_edit_trends.py`

- [ ] **Step 1: Başarısız testleri yaz** — `tests/test_web_channel_edit_trends.py`:

```python
"""Kanal düzenleme: content_source=trends + trends_region formdan YAML'a."""
from __future__ import annotations

import pytest
import yaml

from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8",
    )
    (cfg_dir / "channels" / "demo.yaml").write_text("""\
slug: demo
name: Demo
keywords: [x]
language: tr
schedule_cron: 0 * * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors:
  primary: '#c81e1e'
  accent: '#ffea3b'
  bg_gradient: ['#000000', '#111111']
handle: '@demo'
output_dir: output/demo
enabled: true
""", encoding="utf-8")
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=tmp_path / "data" / "secrets.yaml",
                      scheduler=False)


def _base_post() -> dict:
    return {"schedule_cron": "0 * * * *", "duration_s": "6", "min_score": "6.0",
            "max_candidates_per_run": "5", "handle": "@demo", "enabled": "1"}


def _yaml(tmp_path):
    return yaml.safe_load(
        (tmp_path / "config" / "channels" / "demo.yaml").read_text(encoding="utf-8"))


def test_edit_page_offers_trends_source_and_region(app):
    body = app.test_client().get("/channels/demo/edit").data.decode("utf-8")
    assert 'name="content_source" value="trends"' in body
    assert 'name="trends_region"' in body
    assert 'value="DE"' in body


def test_post_trends_source_with_region_writes_yaml(app, tmp_path):
    form = _base_post()
    form["content_source"] = "trends"
    form["trends_region"] = "DE"
    resp = app.test_client().post("/channels/demo/edit", data=form)
    assert resp.status_code in (200, 302)
    raw = _yaml(tmp_path)
    assert raw["content_source"] == "trends"
    assert raw["trends_region"] == "DE"


def test_post_trends_source_with_empty_region_omits_field(app, tmp_path):
    form = _base_post()
    form["content_source"] = "trends"
    form["trends_region"] = ""
    app.test_client().post("/channels/demo/edit", data=form)
    raw = _yaml(tmp_path)
    assert raw["content_source"] == "trends"
    assert "trends_region" not in raw


def test_post_invalid_region_is_rejected_and_keeps_old(app, tmp_path):
    form = _base_post()
    form["content_source"] = "trends"
    form["trends_region"] = "Almanya"
    resp = app.test_client().post("/channels/demo/edit", data=form,
                                  follow_redirects=True)
    assert resp.status_code == 200
    raw = _yaml(tmp_path)
    assert raw.get("content_source", "rss") == "rss"   # kayıt yapılmadı


def test_post_rss_keeps_no_trends_region(app, tmp_path):
    form = _base_post()
    form["content_source"] = "rss"
    form["keywords"] = "x"
    form["trends_region"] = "DE"          # kaynak rss ise bölge yok sayılır
    app.test_client().post("/channels/demo/edit", data=form)
    raw = _yaml(tmp_path)
    assert "trends_region" not in raw
```

- [ ] **Step 2: Başarısız olduğunu gör**

Run: `python -m pytest tests/test_web_channel_edit_trends.py -q`
Expected: FAIL — sayfada `value="trends"` yok; POST sonrası YAML'da `content_source` yok

- [ ] **Step 3a: Rota** — `src/short_bot/web/routes/channel_edit.py`, `new_content_source` bloğunu değiştir:

```python
    new_content_source = request.form.get("content_source", cfg.content_source)
    if new_content_source not in ("rss", "generator", "feed", "trends"):
        new_content_source = cfg.content_source
    auto_feed_ids = [int(x) for x in request.form.getlist("auto_feed_ids")
                     if x.strip().isdigit()]
    if new_content_source == "feed" and not auto_feed_ids:
        flash("Feed modu için en az bir feed seçmelisin.", "error")
        return redirect(url_for("channel_edit.edit", slug=slug))
    # trends_region yalnız trends kaynağında anlamlı; formdan gelmezse eski
    # değer korunur (başka bir kartın POST'u bölgeyi sessizce silmesin).
    new_trends_region = cfg.trends_region
    if new_content_source == "trends":
        if "trends_region" in request.form:
            raw_region = request.form.get("trends_region", "").strip().upper()
            if raw_region and not re.fullmatch(r"[A-Z]{2}", raw_region):
                flash("Trend bölgesi iki harfli ISO kodu olmalı (TR, DE, ES…).", "error")
                return redirect(url_for("channel_edit.edit", slug=slug))
            new_trends_region = raw_region or None
    else:
        new_trends_region = None
```

Dosyanın başında `import re` yoksa ekle. `ChannelConfig(` kurucusunda `content_source=new_content_source,` satırının altına:

```python
        trends_region=new_trends_region,
```

- [ ] **Step 3b: Şablon** — `edit.html.j2` "İçerik Kaynağı" kartında `feed` radyosundan sonra, `<div class="mt-2">` (feed listesi) öncesine:

```html
        <label class="flex items-center gap-2 text-sm">
          <input type="radio" name="content_source" value="trends"
            {% if c.content_source == 'trends' %}checked{% endif %}>
          Google Trends (ülkenin en çok arananları)
        </label>
        <div class="ml-6 flex items-center gap-2 text-xs">
          <span class="text-claude-muted uppercase">Bölge</span>
          {% set _regions = [('', 'Dilden türet'), ('TR', 'TR · Türkiye'), ('DE', 'DE · Almanya'),
                             ('ES', 'ES · İspanya'), ('US', 'US · ABD'), ('FR', 'FR · Fransa'),
                             ('JP', 'JP · Japonya'), ('GB', 'GB · Birleşik Krallık'),
                             ('AT', 'AT · Avusturya'), ('MX', 'MX · Meksika')] %}
          <select name="trends_region"
                  class="bg-claude-surface border border-claude-border px-2 py-1 rounded-lg text-sm text-claude-text">
            {% for code, label in _regions %}
            <option value="{{ code }}" {% if (c.trends_region or '') == code %}selected{% endif %}>{{ label }}</option>
            {% endfor %}
            {% if c.trends_region and c.trends_region not in _regions|map(attribute=0)|list %}
            <option value="{{ c.trends_region }}" selected>{{ c.trends_region }}</option>
            {% endif %}
          </select>
          <span class="text-claude-subtle">Dilden bağımsız: language=de + AT → Avusturya gündemi Almanca.</span>
        </div>
```

Kartın başlığındaki yorumu da güncelle: `{# ── Card: İçerik Kaynağı (rss / feed / trends) ── #}`.

- [ ] **Step 4: Testler geçsin**

Run: `python -m pytest tests/test_web_channel_edit_trends.py tests/test_web_channel_edit_trend_boost.py -q`
Expected: hepsi PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/web/routes/channel_edit.py src/short_bot/web/templates/channels/edit.html.j2 tests/test_web_channel_edit_trends.py
git commit -m "feat(trends): panelde Google Trends kaynağı ve bölge seçici"
```

---

### Task 10: `gundem` kanalı

**Files:**
- Create: `config/channels/gundem.yaml`
- Test: `tests/test_config_trends.py` (gerçek dosyayı yükleyen test)

- [ ] **Step 1: Başarısız testi yaz** — `tests/test_config_trends.py` sonuna:

```python
def test_repo_gundem_channel_loads():
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "config" / "channels" / "gundem.yaml"
    if not p.exists():
        pytest.skip("config/channels takipsiz olabilir (worktree)")
    cfg = load_channel(p)
    assert cfg.content_source == "trends"
    assert cfg.trends_region == "TR"
    assert cfg.schedule_cron == "0 */2 * * *"
    assert cfg.trend_boost is None or cfg.trend_boost.enabled is False
    assert cfg.dna is not None and cfg.dna.archetype == cfg.template == "broadcast"
    assert cfg.youtube is not None and cfg.youtube.auto_upload is False
```

- [ ] **Step 2: Başarısız olduğunu gör**

Run: `python -m pytest tests/test_config_trends.py::test_repo_gundem_channel_loads -q`
Expected: SKIP (dosya yok) — dosya oluşturulunca gerçek sonuç alınır

- [ ] **Step 3: Kanalı yaz** — `config/channels/gundem.yaml`:

```yaml
slug: gundem
name: Gündem
# keywords trend kaynağında SORGU DEĞİL: persona/DNA üretimi ve senaryo
# promptlarının kanalı tarif etmesi için kısa betimleyici.
keywords:
- Türkiye gündemi
- son dakika
language: tr
# Kaynak: Google Trends "Trending Now" (trends/trending_now.py). Bölge dilden
# bağımsız; Almanya kanalı için language: de + trends_region: DE yeter.
content_source: trends
trends_region: TR
# Trend ömrü kısa (çoğu 6-12 saatte sönüyor): 2 saatlik adım sıcakken yakalar,
# 24 saatlik listede 1000+ hacimli ~70 trend bunu rahat besler (ölçüm 2026-08-20).
schedule_cron: 0 */2 * * *
duration_s: 6
# Puan burada SIRA değil KAPI: eşiği geçenlerden en yüksek arama hacmi seçilir.
# 6.0 = "olay var, 3-4 cümleye sığar" (bkz. scorer._TREND_PROMPT_TEMPLATES).
min_score: 6.0
# Hacim sıralı ilk 25 trend puanlanır.
max_candidates_per_run: 25
max_age_hours: 24
template: broadcast
colors:
  primary: '#d11a2a'
  accent: '#ffd60a'
  bg_gradient:
  - '#0b1220'
  - '#1b2a4a'
handle: '@gundem'
output_dir: output/gundem
enabled: true
youtube:
  auto_upload: false
  ai_content: false
  category_id: '25'
  privacy_status: public
  min_score_for_upload: 6.0
  cron_preset: every_2h
bg_video:
  enabled: true
  scale: 0.88
  blur_px: 30
  dim: 0.25
# Kaynak zaten trend; ikinci kez trend puanı eklemek anlamsız.
trend_boost:
  enabled: false
bg_image_blur: 8
dna:
  archetype: broadcast
  palette:
    primary: '#d11a2a'
    accent: '#ffd60a'
    bg_gradient:
    - '#0b1220'
    - '#1b2a4a'
    body_bg:
    - '#0b1220'
    - '#101a30'
    text_main: '#ffffff'
    text_muted: '#c9d3e6'
    header_top_color: ''
    header_bottom_color: ''
  fonts:
    headline: Roboto Condensed
    body: Inter
    google_imports:
    - Roboto+Condensed:wght@700
    - Inter:wght@400;600;800
    size_headline_top: null
    size_headline_bottom: null
  tone:
    voice: hızlı, net, tarafsız, güvenilir
    style: son dakika bülteni; ilk cümlede ne olduğu, sonra kim/nerede/ne zaman
    forbidden:
    - taraf tutan yorum
    - küfür ve hakaret
    - panik yaratan abartı
    - doğrulanmamış iddiayı kesin gibi yazmak
    - '"BOMBA" ve "ŞOK" gibi yıpranmış manşet klişeleri'
    - her manşeti ünlemle bitirmek
    - uzun teknik analiz
    sentence_max_words: 14
    paragraph_sentences:
    - 3
    - 4
    body_max_chars: 280
    headline_style_hint: 'Kısa, net manşet: özne + ne oldu (örn. ''MARMARA 8 SAATTE 36 KEZ SALLANDI'')'
  banner_shape: flat
  highlight_style: bg-flat
  chip_style: rounded
  category_icon: 📰
  search_query_template: '{header_top} {header_bottom} Türkiye haber'
  persona_summary: Türkiye'nin o an en çok aradığı konuyu 6 saniyede, tarafsız ve
    net anlatan gündem kanalı. Manşet ne olduğunu söyler, gövde üç cümlede bağlamı
    verir; abartı ve yorum yok.
  custom_css: ''
  ui_badge: SON DAKİKA
  animation_style: none
```

- [ ] **Step 4: Test geçsin + DNA smoke**

Run: `python -m pytest tests/test_config_trends.py -q`
Expected: PASS (skip değil)

Run: `python -m short_bot list --config-dir config`
Expected: listede `gundem` görünür, hata yok

- [ ] **Step 5: Commit**

```bash
git add config/channels/gundem.yaml tests/test_config_trends.py
git commit -m "feat(trends): gundem kanalı — Türkiye Google Trends, 2 saatte 1, yükleme kapalı"
```

(`config/channels` bazı worktree'lerde takipsiz olabilir — hafıza notu; `git status` "ignored" diyorsa `git add -f`.)

---

### Task 11: Tam test + gerçek koşu

**Files:** yok (doğrulama)

- [ ] **Step 1: Tüm testler**

Run: `python -m pytest -q -x --ignore=tests/test_reel_render.py 2>&1 | tail -5`
Expected: `N passed` (başarısız yok). Reel render testleri ffmpeg/playwright gerektiriyorsa zaten atlanır; başka bir başarısızlık bu işe ait değilse notla geç.

- [ ] **Step 2: Gerçek API ile kanal koşusu (yükleme kapalı)**

Run: `python -m short_bot run --channel gundem --max 1 2>&1 | tee _gundem_run.log | tail -40`
Expected log sırası:
```
[1/8] fetch_trending_now region=TR
  [trending_now] region=TR 1xx trend / 25 hacim≥1000 / 2x haberli
  → 2x items
[2/8] dedup
[3/8] score_items
[4-6/8] candidate 1/3 score=7.x volume=xxxxx | <haber başlığı>
...
=== success short_id=N ===
```
Kontrol: seçilen aday eşiği geçenler arasında EN YÜKSEK hacimli mi (log satırları `volume=` ile); "hava durumu / hisse" türü başlık 6.0 altında kaldı mı (`below_threshold` kayıtları `rss_items` tablosunda — panelden bakılabilir).

- [ ] **Step 3: Çıktıyı gözle**

`output/gundem/` altındaki en yeni mp4'ün ilk karesini incele: `ffmpeg -y -i <mp4> -frames:v 1 <scratchpad>/gundem_frame.png` → Read ile bak. Manşet/gövde okunaklı, "SON DAKİKA" rozeti ve fotoğraf yerinde olmalı. Metin taşıyorsa overflow katmanı zaten kırpar; kırmızı/altın renkler arka planda kaybolmuyorsa tamam.

- [ ] **Step 4: Önbellek doğrulaması**

Run: `python -m short_bot run --channel gundem --max 1 2>&1 | grep trending_now`
Expected: `[trending_now] önbellek (N dk) → 2x haber` — ikinci koşu API'ye gitmez. (Aynı haber dedup'tan dolayı `no_candidates` ya da sıradaki hacimli trend üretilir; ikisi de doğru.)

- [ ] **Step 5: Commit (log dosyası hariç)**

Kod değişikliği yoksa commit gerekmez. `_gundem_run.log` diğer `_*.log`'lar gibi takipsiz kalır.

---

## Self-review

- **Spec kapsamı:** §1 modül → Task 2-5; §2 model/config → Task 1, 6; §3 pipeline → Task 8; §4 puanlayıcı → Task 7; §5 kanal → Task 10; §6 panel → Task 9; §7 hata tablosu → Task 5 (API/RSS/önbellek) + Task 6 (geçersiz bölge) + Task 8 (boş kaynak → no_candidates); §8 test → her task + Task 11 gerçek koşu.
- **Tip tutarlılığı:** `fetch_trending_items(region, *, language, cache_dir, max_age_minutes, min_volume, max_entries, timeout_s, log)` Task 5'te tanımlı, Task 8 `region, language=, cache_dir=, log=` ile çağırıyor; `select_by_volume(scored, min_score, n)` Task 7 ↔ Task 8; `trends_region` Task 6 ↔ 8 ↔ 9; `_save_cache(path, region, items)` Task 5 testleriyle aynı imza.
- **Spec'ten sapma (bilinçli):** spec'te `keywords: []` yazıyordu; kanal YAML'ında DNA/persona üretimi için iki betimleyici anahtar var — trend kaynağında sorgu olarak kullanılmıyor (Task 10 yorumu). `TrendingEntry.active` alanı düşürüldü: API `1` bayrağıyla yalnız etkin trendleri döndürüyor (181/181), alan bilgi taşımıyordu.
