# Trend Dikeyi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `content_source: trends` kanalları "ülkenin en çok aradığı her şey" yerine tanımlı bir DİKEY üretsin, böylece YouTube Shorts algoritması kanalı tek bir izleyici kitlesiyle eşleştirebilsin.

**Architecture:** Google Trends her trendi zaten sınıflandırıyor (`TrendingEntry.category_ids`) ama alan `NewsItem`'a taşınmıyor. Alanı taşıyıp kanal YAML'ına bir `trends_vertical` adı ekliyoruz; ad, kategori kümesine çevriliyor ve süzme **önbellek okuma anında** yapılıyor (önbellek bölge başına paylaşıldığı için filtre asla önbelleğe yazılmaz). Kapı prompt'u dikeyi öğreniyor, dikey aç kalırsa koşu sessizce genişlemek yerine boş bitiyor.

**Tech Stack:** Python 3, dataclasses, pytest, Flask + Jinja2 (panel), PyYAML.

**Spec:** `docs/superpowers/specs/2026-08-21-trend-dikey-design.md`

---

## Dosya haritası

| Dosya | Sorumluluk |
|---|---|
| `src/short_bot/trends/verticals.py` | **YENİ** — dikey adı ↔ Google kategori kümesi haritası, eşleşme kuralı |
| `src/short_bot/models.py` | `NewsItem.trend_categories` alanı |
| `src/short_bot/trends/trending_now.py` | kategoriyi üretimde ve önbellekte taşı; süzmeyi okumaya al |
| `src/short_bot/config.py` | `trends_vertical` + `trends_min_candidates` alanları, doğrulama, YAML gidiş-dönüşü |
| `src/short_bot/pipeline.py` | dikeyi `fetch_trending_items`'a geçir, arz tabanı alarmı |
| `src/short_bot/scorer.py` | kapı prompt'una dikey bloğu |
| `src/short_bot/web/routes/channel_edit.py` | genel düzenleme formunda dikey |
| `src/short_bot/web/routes/yorum.py` | yorum formatı formunda dikey |
| `src/short_bot/web/templates/channels/edit.html.j2` | dikey seçici |
| `src/short_bot/web/templates/channels/edit_yorum.html.j2` | dikey seçici |
| `src/short_bot/web/templates/channels/new_yorum.html.j2` | dikey seçici |
| `config/channels/*.yaml` | üç kanalın dikey + hacim tabanı ataması |

---

### Task 1: Dikey haritası

**Files:**
- Create: `src/short_bot/trends/verticals.py`
- Test: `tests/test_trends_verticals.py`

- [ ] **Step 1: Write the failing test**

`tests/test_trends_verticals.py`:

```python
"""Trend dikeyleri — Google kategori kimliklerinin okunabilir kümeleri."""
from __future__ import annotations

import pytest


def test_para_dikeyi_is_finans_ve_alisverisi_kapsar():
    from short_bot.trends.verticals import categories_for
    assert categories_for("para") == frozenset({3, 16})


def test_spor_dikeyi_tek_kategori():
    from short_bot.trends.verticals import categories_for
    assert categories_for("spor") == frozenset({17})


def test_dikeysiz_kanal_sinirsiz():
    from short_bot.trends.verticals import categories_for, matches
    assert categories_for(None) is None
    assert matches((17,), None) is True
    assert matches((), None) is True


def test_coklu_kategoride_herhangi_biri_yeter():
    # 'sucuk' gerçek veride [3, 5] etiketli (İş&Finans + Yeme-İçme).
    # Tek-kategori kuralı olsaydı para dikeyinden düşerdi.
    from short_bot.trends.verticals import matches
    assert matches((3, 5), "para") is True


def test_eslesmeyen_trend_elenir():
    from short_bot.trends.verticals import matches
    assert matches((17,), "para") is False


def test_kategorisiz_trend_dikeyde_kalamaz():
    # RSS yedeğinden gelen haberde kategori YOK; dikey kanalda kullanılamaz.
    from short_bot.trends.verticals import matches
    assert matches((), "para") is False


def test_bilinmeyen_dikey_hata_verir():
    from short_bot.trends.verticals import categories_for
    with pytest.raises(KeyError):
        categories_for("futbol")


def test_buyuk_harf_ve_bosluk_tolere_edilir():
    from short_bot.trends.verticals import categories_for
    assert categories_for("  Para  ") == frozenset({3, 16})


def test_her_dikeyin_etiketi_var():
    from short_bot.trends.verticals import VERTICALS, VERTICAL_LABELS
    assert set(VERTICALS) == set(VERTICAL_LABELS)


def test_her_kategori_kimliginin_adi_var():
    from short_bot.trends.verticals import CATEGORY_NAMES, VERTICALS
    for cats in VERTICALS.values():
        for c in cats:
            assert c in CATEGORY_NAMES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trends_verticals.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'short_bot.trends.verticals'`

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/trends/verticals.py`:

```python
"""Trend DİKEYLERİ — Google Trends kategori kimliklerinin okunabilir kümeleri.

Google her trendi kendisi sınıflandırıyor (``TrendingEntry.category_ids``).
Kanal YAML'ında ham kimlik listesi TUTULMAZ: okunmaz, ve harita değişirse her
kanal dosyası bozulur. Kanal bir DİKEY adı yazar, karşılığı burada durur.

Harita 2026-08-21'de ampirik çıkarıldı (2090 trend, altı bölge; kategori başına
en yüksek hacimli terimlerden). Google'ın alfabetik 19'luk listesiyle birebir
DEĞİL: 20 (Hava & Afet) o listede yok, 12 hiç görülmedi.
"""
from __future__ import annotations

CATEGORY_NAMES: dict[int, str] = {
    1: "Otomotiv",
    2: "Güzellik & Moda",
    3: "İş & Finans",
    4: "Eğlence",
    5: "Yeme-İçme",
    6: "Oyun",
    7: "Sağlık",
    8: "Hobi & Boş zaman",
    9: "İş & Eğitim",
    10: "Hukuk & Devlet",
    11: "Diğer / yerel olay",
    13: "Hayvan",
    14: "Siyaset",
    15: "Bilim",
    16: "Alışveriş",
    17: "Spor",
    18: "Teknoloji",
    19: "Seyahat",
    20: "Hava & Afet",
}

# Siyaset (14) BİLEREK hiçbir dikeyde yok: altı bölgede de günde 1-11 trend
# veriyor (eşik ~8) ve kutuplaştırıcı. Dikey olarak kurulamaz.
VERTICALS: dict[str, frozenset[int]] = {
    "spor": frozenset({17}),
    "para": frozenset({3, 16}),
    "magazin": frozenset({4, 2}),
    "adalet": frozenset({10}),
    "olay": frozenset({11, 20}),
    "teknoloji": frozenset({18, 15, 6}),
}

VERTICAL_LABELS: dict[str, str] = {
    "spor": "Spor — lig, maç, transfer, milli takım",
    "para": "Para — ekonomi, zam, faiz, şirket, alışveriş",
    "magazin": "Magazin — ünlü, dizi, film, moda",
    "adalet": "Adalet — dava, gözaltı, kurum, resmi karar",
    "olay": "Olay — yerel haber, kaza, deprem, hava",
    "teknoloji": "Teknoloji — teknoloji, bilim, oyun",
}


def categories_for(vertical: str | None) -> frozenset[int] | None:
    """Dikey adının kategori kümesi. None/boş → None (süzme yok).

    Bilinmeyen ad KeyError fırlatır: sessizce "süzme yok"a düşmek, ayarı açık
    sanılıp kapalı çalışan bir kanal demektir (bkz. saga sınırı vakası).
    """
    if not vertical:
        return None
    return VERTICALS[str(vertical).strip().lower()]


def matches(categories, vertical: str | None) -> bool:
    """Bu trend o dikeye giriyor mu?

    ÇOKLU kategoride HERHANGİ biri yeterlidir: gerçek veride 'sucuk' [3, 5]
    etiketli ve para dikeyinde kalmalı.

    Kategorisi olmayan trend (RSS yedeği) dikeyi olan kanala GİREMEZ — hangi
    dikeye ait olduğu bilinmiyor, tahmin etmek "her şey"e geri dönüştür.
    """
    want = categories_for(vertical)
    if want is None:
        return True
    return bool(want & set(categories or ()))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_trends_verticals.py -q`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/trends/verticals.py tests/test_trends_verticals.py
git commit -m "feat(trends): dikey haritası — Google kategori kimliklerinin okunabilir kümeleri"
```

---

### Task 2: `NewsItem.trend_categories` — üretim ve önbellek

**Files:**
- Modify: `src/short_bot/models.py` (`NewsItem`, `trend_articles` alanından sonra)
- Modify: `src/short_bot/trends/trending_now.py:203` (`trending_as_news_items`), `:249` (`_item_to_dict`), `:262` (`_item_from_dict`)
- Test: `tests/test_trends_categories.py`

- [ ] **Step 1: Write the failing test**

`tests/test_trends_categories.py`:

```python
"""NewsItem.trend_categories — Google'ın kendi sınıflandırması üretimde ve
önbellekte hayatta kalmalı. Alan taşınmazsa dikey kapısı sessizce boş çalışır."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"


def _entry(**kw):
    from short_bot.trends.trending_now import TrendingEntry
    base = dict(term="altın", volume=100000, growth_pct=200,
                started_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
                category_ids=(3,), breakdown=("altın fiyatları",), news_ids=(1,))
    base.update(kw)
    return TrendingEntry(**base)


def _article(**kw):
    from short_bot.trends.trending_now import TrendingArticle
    base = dict(title="Altın rekor kırdı", url="https://x.test/1",
                source="Test", published_at=None, image_url=None)
    base.update(kw)
    return TrendingArticle(**base)


def test_kategori_news_iteme_tasinir():
    from short_bot.trends.trending_now import trending_as_news_items
    items = trending_as_news_items([_entry(category_ids=(3, 16))], {0: [_article()]})
    assert items[0].trend_categories == (3, 16)


def test_rss_kaynagi_bos_kategoriyle_gelir():
    from short_bot.models import NewsItem
    i = NewsItem(guid="g", title="t", link="l", source=None, pub_date=None,
                 thumb_url=None, description=None)
    assert i.trend_categories == ()


def test_onbellek_gidis_donusunde_korunur():
    from short_bot.trends.trending_now import _item_from_dict, _item_to_dict, trending_as_news_items
    items = trending_as_news_items([_entry(category_ids=(3, 16))], {0: [_article()]})
    geri = _item_from_dict(_item_to_dict(items[0]))
    assert geri.trend_categories == (3, 16)


def test_eski_onbellek_dosyasi_kirilmaz():
    # trend_categories alanı olmayan (bu değişiklikten önce yazılmış) kayıt.
    from short_bot.trends.trending_now import _item_from_dict
    geri = _item_from_dict({"guid": "g", "title": "t", "link": "l",
                            "trend_volume": 5000})
    assert geri.trend_categories == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trends_categories.py -q`
Expected: FAIL — `AttributeError: 'NewsItem' object has no attribute 'trend_categories'`

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/models.py` — `trend_articles` satırının hemen ardına ekle:

```python
    # trend_categories: Google Trends'in KENDİ sınıflandırması (17=Spor,
    # 3=İş&Finans, 4=Eğlence…). Dikey kapısı buna dayanır, ek AI maliyeti yok
    # (bkz. trends/verticals.py). RSS/feed/curated kaynaklarında boş kalır.
    trend_categories: tuple[int, ...] = ()
```

`src/short_bot/trends/trending_now.py` — `trending_as_news_items` içindeki
`NewsItem(...)` çağrısına, `trend_articles=` satırının ardına:

```python
            trend_categories=tuple(e.category_ids),
```

`_item_to_dict` sözlüğüne, `"trend_articles"` satırının ardına:

```python
        "trend_categories": list(i.trend_categories),
```

`_item_from_dict` çağrısına, `trend_articles=` satırının ardına:

```python
        trend_categories=tuple(int(x) for x in (d.get("trend_categories") or ())),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_trends_categories.py tests/test_trends_trending_now.py -q`
Expected: PASS (yeni 4 test + mevcut trending_now testleri bozulmamış)

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/models.py src/short_bot/trends/trending_now.py tests/test_trends_categories.py
git commit -m "feat(trends): kategori kimlikleri NewsItem'a ve önbelleğe taşındı"
```

---

### Task 3: `trends_vertical` + `trends_min_candidates` kanal ayarları

**Files:**
- Modify: `src/short_bot/config.py` (`ChannelConfig` alanları, `_trends_intent` yanına yeni doğrulayıcı, `load_channel`, `save_channel`)
- Test: `tests/test_config_trends_vertical.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config_trends_vertical.py`:

```python
"""trends_vertical / trends_min_candidates — YAML gidiş-dönüşü ve doğrulama."""
from __future__ import annotations

import pytest
import yaml


def _yaz(tmp_path, **extra):
    data = {
        "slug": "test-dikey", "name": "Test", "keywords": ["a"], "language": "tr",
        "schedule_cron": "0 9 * * *", "duration_s": 6, "min_score": 6.0,
        "max_candidates_per_run": 10, "max_age_hours": 24, "template": "flas",
        "colors": {"primary": "#fff", "accent": "#000", "bg_gradient": ["#111", "#222"]},
        "handle": "@t", "output_dir": "output/t", "content_source": "trends",
    }
    data.update(extra)
    p = tmp_path / "test-dikey.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def test_varsayilan_dikey_yok(tmp_path):
    from short_bot.config import load_channel
    cfg = load_channel(_yaz(tmp_path))
    assert cfg.trends_vertical is None
    assert cfg.trends_min_candidates == 4


def test_dikey_okunur(tmp_path):
    from short_bot.config import load_channel
    cfg = load_channel(_yaz(tmp_path, trends_vertical="para"))
    assert cfg.trends_vertical == "para"


def test_gecersiz_dikey_sessizce_dusmez(tmp_path):
    from short_bot.config import load_channel
    with pytest.raises(ValueError, match="trends_vertical"):
        load_channel(_yaz(tmp_path, trends_vertical="futbol"))


def test_dikey_kaydedilince_yamlda_kalir(tmp_path):
    from short_bot.config import load_channel, save_channel
    p = _yaz(tmp_path, trends_vertical="adalet", trends_min_candidates=6)
    cfg = load_channel(p)
    out = tmp_path / "kayit.yaml"
    save_channel(out, cfg)
    geri = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert geri["trends_vertical"] == "adalet"
    assert geri["trends_min_candidates"] == 6


def test_dikeysiz_kanal_yamlda_alan_yazmaz(tmp_path):
    from short_bot.config import load_channel, save_channel
    cfg = load_channel(_yaz(tmp_path))
    out = tmp_path / "kayit.yaml"
    save_channel(out, cfg)
    geri = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert "trends_vertical" not in geri
    assert "trends_min_candidates" not in geri
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_trends_vertical.py -q`
Expected: FAIL — `AttributeError: 'ChannelConfig' object has no attribute 'trends_vertical'`

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/config.py` — `trends_intent` alan tanımının hemen ardına:

```python
    # trends_vertical: kanalın DİKEYİ (bkz. trends/verticals.py). Trend havuzu
    # tanımı gereği "her şey"dir; hacim sıralı seçim onu ülkenin en kalabalık
    # konusuna (ölçüldü: TR hacminin %64'ü spor) sürükler ve Shorts algoritması
    # kanalı tek bir kitleyle eşleştiremez. Dikey, havuzu kanalın kimliğine
    # daraltır. None = eski davranış, süzme yok.
    trends_vertical: str | None = None
    # trends_min_candidates: dikey süzgecinden sonra bu sayının altında aday
    # kalırsa koşu boş biter. Havuzu SESSİZCE genişletmek yasak — tam da
    # düzeltilen sorunu geri getirir ve görünmez yapar.
    trends_min_candidates: int = 4
```

`_trends_intent` fonksiyonunun hemen ardına:

```python
def _trends_vertical(raw, slug: str) -> str | None:
    """trends_vertical'ı doğrula. Yazım hatası SESSİZCE None'a düşmemeli:
    kanal dikeyli sanılıp 'her şey' üreten bir kanal en kötüsüdür
    (bkz. _trends_intent'teki aynı gerekçe)."""
    if raw in (None, ""):
        return None
    from short_bot.trends.verticals import VERTICALS
    val = str(raw).strip().lower()
    if val not in VERTICALS:
        raise ValueError(
            f"channel {slug!r}: trends_vertical {raw!r} geçersiz — "
            f"{', '.join(sorted(VERTICALS))} olmalı")
    return val
```

`load_channel` içindeki `trends_intent=` satırının ardına:

```python
        trends_vertical=_trends_vertical(data.get("trends_vertical"), slug),
        trends_min_candidates=int(data.get("trends_min_candidates") or 4),
```

`save_channel` içindeki `trends_intent` bloğunun ardına:

```python
    if cfg.trends_vertical:
        data["trends_vertical"] = cfg.trends_vertical
    if cfg.trends_min_candidates != 4:
        data["trends_min_candidates"] = cfg.trends_min_candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config_trends_vertical.py tests/test_config_trends.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/config.py tests/test_config_trends_vertical.py
git commit -m "feat(config): trends_vertical + trends_min_candidates kanal ayarları"
```

---

### Task 4: Süzme önbelleğe yazılmaz — okuma anında uygulanır

Bu görev bir HATA da düzeltir: `min_volume` bugün çekim anında uygulanıp
önbelleğe yazılıyor, ama önbellek **bölge** başınadır. Tabanı 5000 olan kanal
önbelleği doldurunca tabanı 1000 olan kanal 30 dk boyunca aç kalıyor. Task 9'da
kanallara farklı tabanlar verileceği için bu hata canlıya çıkmadan kapanmalı.

**Files:**
- Modify: `src/short_bot/trends/trending_now.py:375` (`fetch_trending_items`)
- Test: `tests/test_trends_cache_filters.py`

- [ ] **Step 1: Write the failing test**

`tests/test_trends_cache_filters.py`:

```python
"""Önbellek BÖLGE başınadır, kanal başına değil: hacim tabanı ve dikey kanal
ayarıdır ve önbelleğe SIZMAMALI."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _entry(term, volume, cats, nid):
    from short_bot.trends.trending_now import TrendingEntry
    return TrendingEntry(term=term, volume=volume, growth_pct=0,
                         started_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
                         category_ids=cats, breakdown=(), news_ids=(nid,))


def _article(title, url):
    from short_bot.trends.trending_now import TrendingArticle
    return TrendingArticle(title=title, url=url, source="S",
                           published_at=None, image_url=None)


@pytest.fixture
def sahte_api(monkeypatch):
    """Üç trend: spor/yüksek, para/orta, para/düşük."""
    entries = [
        _entry("galatasaray", 100000, (17,), 1),
        _entry("altın", 5000, (3,), 2),
        _entry("mevduat faizi", 1500, (3,), 3),
    ]
    arts = {0: [_article("GS kazandı", "https://x.test/1")],
            1: [_article("Altın rekor", "https://x.test/2")],
            2: [_article("Faiz güncellendi", "https://x.test/3")]}
    cagri = {"n": 0}

    def fake_now(region, *, language, hours=24, timeout_s=15):
        cagri["n"] += 1
        return entries

    def fake_arts(picked, *, language, region, timeout_s=15):
        idx = {e.term: i for i, e in enumerate(entries)}
        return {i: arts[idx[e.term]] for i, e in enumerate(picked)}

    monkeypatch.setattr("short_bot.trends.trending_now.fetch_trending_now", fake_now)
    monkeypatch.setattr("short_bot.trends.trending_now.fetch_trending_articles", fake_arts)
    return cagri


def test_dikey_havuzu_daraltir(tmp_path, sahte_api):
    from short_bot.trends.trending_now import fetch_trending_items
    items = fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                 min_volume=1000, vertical="para")
    assert [i.title for i in items] == ["Altın rekor", "Faiz güncellendi"]


def test_onbellek_dikeyden_etkilenmez(tmp_path, sahte_api):
    """Para kanalı önbelleği doldurur; spor kanalı AYNI önbellekten kendi
    adaylarını görmeli — filtre önbelleğe yazılsaydı boş dönerdi."""
    from short_bot.trends.trending_now import fetch_trending_items
    fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                         min_volume=1000, vertical="para")
    items = fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                 min_volume=1000, vertical="spor")
    assert [i.title for i in items] == ["GS kazandı"]
    assert sahte_api["n"] == 1          # ikinci çağrı önbellekten geldi


def test_onbellek_hacim_tabanindan_etkilenmez(tmp_path, sahte_api):
    """Tabanı 5000 olan kanal önbelleği doldurur; tabanı 1000 olan kanal
    yine de düşük hacimli adayını görmeli."""
    from short_bot.trends.trending_now import fetch_trending_items
    fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                         min_volume=5000, vertical="para")
    items = fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                 min_volume=1000, vertical="para")
    assert len(items) == 2
    assert sahte_api["n"] == 1


def test_dikeysiz_kanal_hepsini_alir(tmp_path, sahte_api):
    from short_bot.trends.trending_now import fetch_trending_items
    items = fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                 min_volume=1000)
    assert len(items) == 3


def test_dikeyli_kanalda_rss_yedegi_kullanilmaz(tmp_path, monkeypatch, caplog):
    """RSS yedeğinde kategori YOK. Dikeyli kanala vermek 'her şey'e dönmektir."""
    import logging

    def patla(region, *, language, hours=24, timeout_s=15):
        raise RuntimeError("API down")

    rss_cagrildi = {"n": 0}

    def fake_rss(region, *, timeout_s=10):
        rss_cagrildi["n"] += 1
        return []

    monkeypatch.setattr("short_bot.trends.trending_now.fetch_trending_now", patla)
    monkeypatch.setattr("short_bot.trends.trending_now._rss_fallback", fake_rss)
    from short_bot.trends.trending_now import fetch_trending_items
    with caplog.at_level(logging.INFO):
        items = fetch_trending_items("TR", language="tr", cache_dir=tmp_path,
                                     min_volume=1000, vertical="para")
    assert items == []
    assert rss_cagrildi["n"] == 0
    assert "RSS yedeği" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trends_cache_filters.py -q`
Expected: FAIL — `TypeError: fetch_trending_items() got an unexpected keyword argument 'vertical'`

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/trends/trending_now.py` — `fetch_trending_items`'ın hemen üstüne
yardımcıyı ekle:

```python
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
```

`fetch_trending_items`'ı şu gövdeyle değiştir (imza + üç blok değişiyor):

```python
def fetch_trending_items(
    region: str,
    *,
    language: str,
    cache_dir: Path,
    max_age_minutes: float = 30.0,
    min_volume: int = 1000,
    vertical: str | None = None,
    max_entries: int = 200,
    timeout_s: int = 15,
    log: logging.Logger | None = None,
) -> list[NewsItem]:
    """Pipeline'ın çağırdığı tek giriş. Sıra: taze önbellek → API → RSS yedeği →
    bayat önbellek → []. Hiçbir durumda hata fırlatmaz.

    Önbellek HAM doldurulur (hacim tabanı ve dikey uygulanmadan); kanal
    süzgeçleri okuma anında `_apply_channel_filters` ile geçilir. Bkz. oradaki
    gerekçe.

    ``max_entries`` 40 değil 200: dikey dar olduğunda hacme göre kesilmiş ilk
    40'ta o dikeyden neredeyse hiçbir şey kalmıyor (TR hacminin %64'ü spor).
    Bu sayı aynı zamanda `fetch_trending_articles`'ın alt-çağrı sayısıdır ama
    hepsi TEK HTTP isteğinde gider ve önbellek 30 dk tutar.

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
        return picked

    items: list[NewsItem] = []
    try:
        entries = fetch_trending_now(region, language=language, timeout_s=timeout_s)
        picked_entries = sorted(
            (e for e in entries if e.news_ids),
            key=lambda e: e.volume, reverse=True,
        )[:max_entries]
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
        return out

    if vertical:
        log.info("  [trending_now] RSS yedeği dikeyli kanalda KULLANILMAZ "
                 "(kategori bilgisi yok) → aday yok")
    else:
        fallback = [i for i in _rss_fallback(region) if i.trend_volume >= min_volume]
        if fallback:
            fallback.sort(key=lambda i: i.trend_volume, reverse=True)
            log.info(f"  [trending_now] RSS yedeği → {len(fallback)} haber")
            return fallback
    if cached is not None and cached[1]:
        picked = _apply_channel_filters(cached[1], min_volume=min_volume,
                                        vertical=vertical)
        log.info(f"  [trending_now] bayat önbellek ({cached[0]:.0f} dk) → "
                 f"{len(picked)} aday")
        return picked
    log.info("  [trending_now] hiçbir kaynaktan veri yok")
    return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_trends_cache_filters.py tests/test_trends_trending_now.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/trends/trending_now.py tests/test_trends_cache_filters.py
git commit -m "fix(trends): kanal süzgeçleri önbelleğe sızmıyor + dikey süzgeci"
```

---

### Task 5: Pipeline dikeyi geçirir, arz tabanı alarmı verir

**Files:**
- Modify: `src/short_bot/pipeline.py` (`_run_rss` içindeki `is_trends` dalı, ~satır 1083-1090; ve dosyaya saf yardımcı)
- Test: `tests/test_pipeline_trends_vertical.py`

Kararı saf bir yardımcıya çıkarıyoruz (`_vertical_starved`): `_run_rss` DB, ağ ve
dosya sistemi ister, uçtan uca test edilemez — karar mantığı ayrı durunca
gerçekten test edilebilir.

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline_trends_vertical.py`:

```python
"""Dikeyi olan kanalın havuzu aç kalırsa koşu boş biter — SESSİZCE genişlemez."""
from __future__ import annotations

import inspect

from short_bot.config import ChannelConfig


def _kanal(**kw):
    base = dict(
        slug="t", name="Test", keywords=[], language="tr",
        schedule_cron="0 9 * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, max_age_hours=24, template="flas",
        colors={"primary": "#fff", "accent": "#000", "bg_gradient": ["#1", "#2"]},
        handle="@t", output_dir="o", content_source="trends",
    )
    base.update(kw)
    return ChannelConfig(**base)


def test_dikeysiz_kanal_asla_ac_sayilmaz():
    """Dikey yoksa bu kapı hiç çalışmamalı: eski davranış bit bit aynı kalır."""
    from short_bot.pipeline import _vertical_starved
    assert _vertical_starved([], _kanal()) is False


def test_esigin_altinda_ac_sayilir():
    from short_bot.pipeline import _vertical_starved
    kanal = _kanal(trends_vertical="para", trends_min_candidates=4)
    assert _vertical_starved([1, 2, 3], kanal) is True


def test_esikte_ac_sayilmaz():
    from short_bot.pipeline import _vertical_starved
    kanal = _kanal(trends_vertical="para", trends_min_candidates=4)
    assert _vertical_starved([1, 2, 3, 4], kanal) is False


def test_pipeline_dikeyi_fetche_gecirir():
    """Dikey `fetch_trending_items`'a verilmezse süzgeç hiç çalışmaz ve
    kanal ayarı açık sanılıp kapalı çalışır."""
    from short_bot import pipeline
    src = inspect.getsource(pipeline._run_rss)
    assert "vertical=channel.trends_vertical" in src


def test_havuz_genisletme_kodu_yok():
    """Dikeyi düşürüp yeniden çekmek düzeltilen sorunu geri getirir."""
    from short_bot import pipeline
    src = inspect.getsource(pipeline._run_rss)
    assert "_vertical_starved" in src
    assert "vertical=None" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline_trends_vertical.py -q`
Expected: FAIL — `ImportError: cannot import name '_vertical_starved' from 'short_bot.pipeline'`

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/pipeline.py` — `_ticker_items_for_trends` fonksiyonunun hemen
ardına saf yardımcıyı ekle:

```python
def _vertical_starved(items, channel) -> bool:
    """Dikey süzgecinden yeterli aday çıkmadı mı?

    Yalnız dikeyi OLAN kanalda anlamlıdır: dikeysiz kanalda eski davranış bit
    bit korunur. True dönerse koşu boş biter — havuz GENİŞLETİLMEZ.
    """
    if not getattr(channel, "trends_vertical", None):
        return False
    return len(items) < channel.trends_min_candidates
```

Ardından `_run_rss` içindeki trends bloğunu değiştir:

```python
    if is_trends:
        region = (channel.trends_region or trend_region_for(channel.language)).upper()
        dikey = channel.trends_vertical
        log.info(f"[1/8] fetch_trending_now region={region}"
                 f"{f' dikey={dikey}' if dikey else ''}")
        items = fetch_trending_items(
            region, language=channel.language,
            cache_dir=Path(cache_dir) / "trends",
            min_volume=channel.trends_min_volume,
            vertical=channel.trends_vertical, log=log)
        if _vertical_starved(items, channel):
            # HAVUZ GENİŞLETİLMEZ. Dikeyi düşürüp yeniden çekmek, düzeltilen
            # sorunu geri getirir ve üstelik görünmez yapar: kanal "bugün de
            # üretti" der ama kimliği dışında bir video yayınlamış olur.
            log.warning(
                f"  [dikey] '{dikey}' aç kaldı: {len(items)} aday < "
                f"{channel.trends_min_candidates} → koşu boş bitiyor")
            finish_run(eng, run_id, status="no_candidates", short_id=None, error=None)
            return RunResult(run_id=run_id, status="no_candidates",
                             short_path=None, error=None)
    else:
        log.info("[1/8] fetch_rss")
        items = fetch_rss(channel.keywords, channel.rss_locale)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline_trends_vertical.py tests/test_pipeline_trends.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/pipeline.py tests/test_pipeline_trends_vertical.py tests/test_pipeline_trends.py
git commit -m "feat(pipeline): dikey süzgeci + arz tabanı alarmı (sessiz genişleme yok)"
```

---

### Task 6: `trend_categories` puanlama zincirinde hayatta kalır (regresyon kalkanı)

Saga sınırı işinde trend boost `ScoredItem`'ı yeniden kurup yeni alanı
düşürüyordu. Bugün `pipeline._apply_trend_boost` `replace` kullanıyor ve
`scorer.score_items` orijinal `NewsItem`'ı taşıyor — yani alan **hayatta
kalmalı**. Bu görev o davranışı kilitler.

**Files:**
- Test: `tests/test_trends_categories.py` (mevcut dosyaya ekleme)

- [ ] **Step 1: Write the failing test**

`tests/test_trends_categories.py` sonuna ekle:

```python
def test_kategori_puanlama_zincirinde_dusmez():
    """ScoredItem'ı yeniden kuran her adım NewsItem'ı OLDUĞU GİBİ taşımalı."""
    from dataclasses import replace

    from short_bot.models import NewsItem, ScoredItem

    item = NewsItem(guid="g", title="t", link="l", source=None, pub_date=None,
                    thumb_url=None, description=None, trend_volume=5000,
                    trend_categories=(3, 16))
    s = ScoredItem(item=item, score=8.0, reasoning="", category="", subject="")
    # trend boost / kota / saga hepsi bu kalıbı kullanır
    boosted = replace(s, score=9.0)
    assert boosted.item.trend_categories == (3, 16)
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `python -m pytest tests/test_trends_categories.py::test_kategori_puanlama_zincirinde_dusmez -q`
Expected: PASS (davranış zaten doğru). FAIL alırsan `ScoredItem` alan adları
değişmiştir — `src/short_bot/scorer.py` içindeki `ScoredItem` tanımına bakıp
testi gerçek alanlarla düzelt, üretim kodunu değiştirme.

- [ ] **Step 3: Commit**

```bash
git add tests/test_trends_categories.py
git commit -m "test(trends): kategori alanı puanlama zincirinde düşmüyor (regresyon kalkanı)"
```

---

### Task 7: Kapı prompt'u dikeyi öğrenir

Bugünkü kapı (`scorer.py:138`) "hisse fiyatı/grafik, döviz/altın kuru sorgusu"nu
0-3 verip eliyor. **Para** dikeyinde bu, kanalın tam da yaşadığı şeyi eler.

**Files:**
- Modify: `src/short_bot/scorer.py` (`_TREND_PROMPT_TEMPLATES` sözlüğünün ardına yeni sabit; `is_trends` dalında prompt birleştirme)
- Test: `tests/test_scorer_vertical_gate.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scorer_vertical_gate.py`:

```python
"""Kapı prompt'u kanalın dikeyini bilmeli."""
from __future__ import annotations

from short_bot.config import ChannelConfig


def _kanal(**kw):
    base = dict(
        slug="t", name="Test", keywords=[], language="tr",
        schedule_cron="0 9 * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, max_age_hours=24, template="flas",
        colors={"primary": "#fff", "accent": "#000", "bg_gradient": ["#1", "#2"]},
        handle="@t", output_dir="o", content_source="trends",
    )
    base.update(kw)
    return ChannelConfig(**base)


def _items():
    from short_bot.models import NewsItem
    return [NewsItem(guid="g1", title="Altın rekor kırdı", link="l", source=None,
                     pub_date=None, thumb_url=None, description=None,
                     trend_volume=100000, trend_categories=(3,))]


def test_dikeysiz_prompt_degismez():
    from short_bot.scorer import build_scoring_prompt
    p = build_scoring_prompt(_items(), channel=_kanal())
    assert "BU KANALIN DİKEYİ" not in p


def test_para_dikeyinde_fiyat_hareketi_olay_sayilir():
    from short_bot.scorer import build_scoring_prompt
    p = build_scoring_prompt(_items(), channel=_kanal(trends_vertical="para"))
    assert "BU KANALIN DİKEYİ" in p
    assert "Para" in p
    # Varsayılan kapı altın kuru sorgusunu eliyor; para dikeyinde HAREKETİN
    # NEDENİ olay sayılmalı.
    assert "neden" in p.lower()


def test_adalet_dikeyi_prompta_yazilir():
    from short_bot.scorer import build_scoring_prompt
    p = build_scoring_prompt(_items(), channel=_kanal(trends_vertical="adalet"))
    assert "BU KANALIN DİKEYİ" in p
    assert "Adalet" in p


def test_ingilizce_kanalda_dikey_blogu_ingilizce():
    from short_bot.scorer import build_scoring_prompt
    p = build_scoring_prompt(_items(), channel=_kanal(language="en", trends_vertical="para"))
    assert "THIS CHANNEL'S VERTICAL" in p
```

Prompt'u kuran fonksiyon `scorer.build_scoring_prompt(items, *, channel=None,
performance_insights=None)` (`src/short_bot/scorer.py:226`).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scorer_vertical_gate.py -q`
Expected: FAIL — `assert 'BU KANALIN DİKEYİ' in p`

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/scorer.py` — `_TREND_PROMPT_TEMPLATES` sözlüğünün kapanışının
hemen ardına:

```python
# Dikey bloğu: havuz zaten dikeye süzülmüş olarak geliyor (bkz.
# trends/verticals.py), ama kapı bunu BİLMEZSE varsayılan "fayda araması"
# listesini uygular ve para kanalında altın hareketini eler. Blok, o dikeyde
# neyin hikâye sayıldığını söyler.
#
# Diller mevcut şablonlarla aynı: tr/en/de; başka dil en'e düşer.
_VERTICAL_GATE: dict[str, dict[str, str]] = {
    "tr": {
        "_bas": "\n\nBU KANALIN DİKEYİ: {label}\nHavuz zaten bu dikeye süzüldü; sen yalnız olay var mı ona bak.\n",
        "para": "Bu dikeyde fiyat/kur/faiz HAREKETİNİN NEDENİ bir olaydır (rekor, karar, zam, iflas, satın alma) — 7-10 ver. Yalnız 'kaç TL / ne kadar' sorgusu olaydır DEĞİL — 0-3 ver.",
        "spor": "Bu dikeyde skor, transfer, sakatlık, ayrılık, ceza ve resmi açıklama olaydır. 'Maç hangi kanalda / saat kaçta' olay değildir.",
        "magazin": "Bu dikeyde ayrılık, evlilik, dava, itiraf, kadro/yayın kararı ve vefat olaydır. 'Kimdir / kaç yaşında / nereli' olay değildir.",
        "adalet": "Bu dikeyde gözaltı, iddianame, duruşma kararı, ceza, tahliye ve resmi kurum kararı olaydır. Dava dosyası özeti ya da 'X kimdir' olay değildir.",
        "olay": "Bu dikeyde kaza, yangın, deprem, sel, kurtarma ve resmi uyarı olaydır. Hava durumu tahmini sorgusu olay değildir.",
        "teknoloji": "Bu dikeyde duyuru, çıkış, kapanma, ihlal, satın alma ve rekor olaydır. 'Fiyatı ne kadar / nasıl indirilir' olay değildir.",
    },
    "en": {
        "_bas": "\n\nTHIS CHANNEL'S VERTICAL: {label}\nThe pool is already filtered to this vertical; you only judge whether there is an event.\n",
        "para": "Here, the REASON behind a price/rate move is an event (record, decision, hike, bankruptcy, acquisition) — score 7-10. A bare 'how much is it' lookup is NOT an event — score 0-3.",
        "spor": "Here, scores, transfers, injuries, exits, bans and official statements are events. 'What channel / what time is the match' is not.",
        "magazin": "Here, splits, marriages, lawsuits, confessions, casting/airing decisions and deaths are events. 'Who is X / how old' is not.",
        "adalet": "Here, arrests, indictments, rulings, sentences, releases and official decisions are events. A case summary or 'who is X' is not.",
        "olay": "Here, crashes, fires, earthquakes, floods, rescues and official warnings are events. A weather forecast lookup is not.",
        "teknoloji": "Here, announcements, launches, shutdowns, breaches, acquisitions and records are events. 'How much does it cost / how to download' is not.",
    },
    "de": {
        "_bas": "\n\nDIE VERTIKALE DIESES KANALS: {label}\nDer Pool ist bereits auf diese Vertikale gefiltert; du beurteilst nur, ob ein Ereignis vorliegt.\n",
        "para": "Hier ist der GRUND einer Preis-/Kurs-/Zinsbewegung ein Ereignis (Rekord, Beschluss, Erhöhung, Insolvenz, Übernahme) — 7-10. Eine reine 'Wie viel kostet' Abfrage ist KEIN Ereignis — 0-3.",
        "spor": "Hier sind Ergebnisse, Transfers, Verletzungen, Abgänge, Sperren und offizielle Erklärungen Ereignisse. 'Welcher Sender / wann' nicht.",
        "magazin": "Hier sind Trennungen, Hochzeiten, Klagen, Geständnisse, Besetzungs-/Sendeentscheidungen und Todesfälle Ereignisse. 'Wer ist X / wie alt' nicht.",
        "adalet": "Hier sind Festnahmen, Anklagen, Urteile, Strafen, Freilassungen und Behördenentscheidungen Ereignisse. Eine Fallzusammenfassung nicht.",
        "olay": "Hier sind Unfälle, Brände, Erdbeben, Überschwemmungen, Rettungen und amtliche Warnungen Ereignisse. Eine Wettervorhersage nicht.",
        "teknoloji": "Hier sind Ankündigungen, Starts, Abschaltungen, Datenlecks, Übernahmen und Rekorde Ereignisse. 'Wie teuer / wie herunterladen' nicht.",
    },
}


def _vertical_gate_block(vertical: str | None, language: str) -> str:
    """Kapı prompt'una eklenecek dikey bloğu. Dikey yoksa boş dize."""
    if not vertical:
        return ""
    from short_bot.trends.verticals import VERTICAL_LABELS
    lang = (language or "tr").split("-")[0].lower()
    table = _VERTICAL_GATE.get(lang) or _VERTICAL_GATE["en"]
    label = VERTICAL_LABELS.get(vertical, vertical)
    out = table["_bas"].format(label=label)
    note = table.get(vertical)
    return out + note if note else out
```

Prompt kurulan yerde, `is_trends` dalındaki `base = template.format(...)`
satırının hemen ardına:

```python
    if is_trends:
        base = base + _vertical_gate_block(
            getattr(channel, "trends_vertical", None), channel.language)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scorer_vertical_gate.py tests/test_scorer_trends.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/scorer.py tests/test_scorer_vertical_gate.py
git commit -m "feat(scorer): kapı prompt'u dikeyi biliyor — para kanalında fiyat hareketi olay"
```

---

### Task 8: Panelde dikey seçici

**Files:**
- Modify: `src/short_bot/web/routes/channel_edit.py` (`guncel` sözlüğü, ~satır 540)
- Modify: `src/short_bot/web/routes/yorum.py` (`edit_save`'in `guncel` sözlüğü ~satır 270; `new_create`; `new_form`/`edit_form` render bağlamı)
- Modify: `src/short_bot/web/templates/channels/edit.html.j2` (~satır 895, `trends_intent` seçicisinin yanına)
- Modify: `src/short_bot/web/templates/channels/edit_yorum.html.j2` (~satır 48)
- Modify: `src/short_bot/web/templates/channels/new_yorum.html.j2` (~satır 45)
- Test: `tests/test_web_channel_edit_vertical.py`

- [ ] **Step 1: Write the failing test**

`tests/test_web_channel_edit_vertical.py`:

```python
"""Panel kaydı dikeyi DÜŞÜRMEMELİ — izin listesine eklenmeyen alan sessizce
varsayılana döner (bkz. panel DNA palet tuzağı, trends kaynağı tuzağı)."""
from __future__ import annotations

import inspect


def test_genel_duzenleme_dikeyi_kaydeder():
    from short_bot.web.routes import channel_edit
    src = inspect.getsource(channel_edit)
    assert "trends_vertical" in src


def test_yorum_duzenleme_dikeyi_kaydeder():
    from short_bot.web.routes import yorum
    src = inspect.getsource(yorum)
    assert "trends_vertical" in src


def test_yorum_kurulumu_dikeyi_kaydeder():
    from short_bot.web.routes import yorum
    src = inspect.getsource(yorum.new_create)
    assert "trends_vertical" in src


def test_sablonlarda_dikey_secici_var():
    from pathlib import Path
    kok = Path("src/short_bot/web/templates/channels")
    for ad in ("edit.html.j2", "edit_yorum.html.j2", "new_yorum.html.j2"):
        metin = (kok / ad).read_text(encoding="utf-8")
        assert 'name="trends_vertical"' in metin, ad
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web_channel_edit_vertical.py -q`
Expected: FAIL — dört testin hepsi

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/web/routes/channel_edit.py` — `guncel` sözlüğünde
`trends_intent=` satırının ardına:

```python
        trends_vertical=(_dikey_from_form(cfg.trends_vertical)
                         if new_content_source == "trends" else None),
```

Aynı dosyada, `edit_save`/POST fonksiyonunun üstüne yardımcıyı ekle:

```python
def _dikey_from_form(default: str | None) -> str | None:
    """Formdan dikey. Alan formda YOKSA eski değer korunur (başka bir kartın
    POST'u dikeyi sessizce silmesin — panel DNA palet tuzağının aynısı)."""
    if "trends_vertical" not in request.form:
        return default
    raw = (request.form.get("trends_vertical") or "").strip().lower()
    return raw or None
```

`src/short_bot/web/routes/yorum.py` — dosyanın üstündeki `REGIONS` tanımının
ardına:

```python
from short_bot.trends.verticals import VERTICAL_LABELS

VERTICALS = sorted(VERTICAL_LABELS.items())
```

`_region_from_form`'un ardına:

```python
def _dikey_from_form(default: str | None) -> str | None:
    if "trends_vertical" not in request.form:
        return default
    return (request.form.get("trends_vertical") or "").strip().lower() or None
```

`edit_save`'in `guncel` sözlüğünde `trends_intent=` satırının ardına:

```python
        trends_vertical=_dikey_from_form(c.trends_vertical),
```

`new_create` içinde `ChannelConfig`/`dataclasses.replace` kurulurken
`trends_intent` ile aynı yere:

```python
        trends_vertical=_dikey_from_form(None),
```

`new_form` ve `edit_form` render çağrılarına `verticals=VERTICALS` bağlamını
ekle (her iki `render_template(...)` çağrısına).

Üç şablona da aynı seçiciyi ekle. `edit_yorum.html.j2` ve `new_yorum.html.j2`
için (`verticals` bağlamı var):

```jinja
<label class="block">
  <span class="text-sm text-claude-muted">Dikey (kanalın kimliği)</span>
  <select name="trends_vertical"
          class="mt-1 w-full bg-white border border-claude-border rounded-lg px-3 py-2 text-sm">
    <option value="">— dikey yok (tüm havuz) —</option>
    {% for code, label in verticals %}
    <option value="{{ code }}" {% if c is defined and c.trends_vertical == code %}selected{% endif %}>{{ label }}</option>
    {% endfor %}
  </select>
  <span class="text-xs text-claude-muted">Havuz bu dikeye süzülür; aday sayısı eşiğin altına düşerse koşu boş biter.</span>
</label>
```

`edit.html.j2` de aynı bloğu kullanır ama bu şablonda `verticals` bağlamı yok.
`src/short_bot/web/routes/channel_edit.py:97` içindeki `render_template(
"channels/edit.html.j2", c=cfg, ...)` çağrısına şu satırı ekle:

```python
                           verticals=sorted(VERTICAL_LABELS.items()),
```

ve dosyanın import bloğuna:

```python
from short_bot.trends.verticals import VERTICAL_LABELS
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_web_channel_edit_vertical.py tests/test_web_channel_edit_trends.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/web/routes/channel_edit.py src/short_bot/web/routes/yorum.py src/short_bot/web/templates/channels/edit.html.j2 src/short_bot/web/templates/channels/edit_yorum.html.j2 src/short_bot/web/templates/channels/new_yorum.html.j2 tests/test_web_channel_edit_vertical.py
git commit -m "feat(panel): dikey seçici — genel düzenleme, yorum kurulumu ve düzenlemesi"
```

---

### Task 9: Kanal atamaları

**Files:**
- Modify: `config/channels/gundem-yorum.yaml`
- Modify: `config/channels/deutschland-klartext.yaml`
- Modify: `config/channels/weltgeschehen-aktuell.yaml`

- [ ] **Step 1: `gundem-yorum` — para dikeyi**

`config/channels/gundem-yorum.yaml` içinde `trends_min_volume: 5000` satırını
`trends_min_volume: 1000` yap ve hemen ardına ekle:

```yaml
trends_vertical: para
```

Gerekçe (ölçüm 2026-08-21): TR'de `para` dikeyi taban 5000'de günde 4 aday
veriyor — eşiğin (≈8) altı. Taban 1000'de 13 aday.

- [ ] **Step 2: `deutschland-klartext` — adalet dikeyi**

`trends_min_volume: 10000` → `trends_min_volume: 2000`, ardına:

```yaml
trends_vertical: adalet
```

Ayrıca `voice.persona` içindeki hüküm cümlesini kaldır: devam eden davada
"net bir hüküm verirsin" hukuki risk. Persona "aktarır + bağlam verir + soru
sorar"a çekilir (`narration_writer` içindeki varsayılan sabite DOKUNMA).

- [ ] **Step 3: `weltgeschehen-aktuell` — magazin dikeyi**

`trends_min_volume: 5000` → `trends_min_volume: 2000`, ardına:

```yaml
trends_vertical: magazin
```

Gerekçe: aynı bölgede (DE) ikinci trend kanalı; ayrı dikey olmazsa iki kanal
aynı olayı anlatır.

- [ ] **Step 4: Üç kanalın da yüklendiğini doğrula**

Run:
```bash
python -c "
from pathlib import Path
from short_bot.config import load_channel
for s in ('gundem-yorum','deutschland-klartext','weltgeschehen-aktuell'):
    c = load_channel(Path('config/channels')/f'{s}.yaml')
    print(s, '| dikey:', c.trends_vertical, '| taban:', c.trends_min_volume,
          '| min aday:', c.trends_min_candidates)
"
```
Expected:
```
gundem-yorum | dikey: para | taban: 1000 | min aday: 4
deutschland-klartext | dikey: adalet | taban: 2000 | min aday: 4
weltgeschehen-aktuell | dikey: magazin | taban: 2000 | min aday: 4
```

- [ ] **Step 5: Canlı arz doğrulaması (gerçek API)**

Run:
```bash
python -c "
from pathlib import Path
from short_bot.trends.trending_now import fetch_trending_items
for region, dikey in (('TR','para'), ('DE','adalet'), ('DE','magazin')):
    lang = {'TR':'tr','DE':'de'}[region]
    items = fetch_trending_items(region, language=lang,
                                 cache_dir=Path('data/cache/trends'),
                                 min_volume=1000 if region=='TR' else 2000,
                                 vertical=dikey)
    print(f'{region}/{dikey}: {len(items)} aday')
    for i in items[:3]: print('   ', i.trend_volume, i.title[:60])
"
```
Expected: her satırda **4 veya daha fazla** aday. Daha az çıkarsa dikey o
bölgede aç demektir — spec §5'teki ikinci adayla değiştir ve gerekçeyi
`docs/superpowers/specs/2026-08-21-trend-dikey-design.md` §5'e işle.

- [ ] **Step 6: Tüm testleri koştur**

Run: `python -m pytest tests/ -q`
Expected: PASS (mevcut testlerde kırılma yok)

- [ ] **Step 7: Commit**

```bash
git add -f config/channels/gundem-yorum.yaml config/channels/deutschland-klartext.yaml config/channels/weltgeschehen-aktuell.yaml
git commit -m "feat(kanallar): dikey atamaları — gundem-yorum=para, klartext=adalet, weltgeschehen=magazin"
```

Not: `config/channels/*.yaml` bazı kanallarda gitignore'da — `git status` ile
kontrol et, gerekiyorsa `-f` kullan (mevcut gelenek).

---

## Temizlik

- [ ] `scratch_trends_raw.json` proje kökünden silinir (ölçüm ham verisi, repoya girmez).

```bash
rm -f scratch_trends_raw.json
```
