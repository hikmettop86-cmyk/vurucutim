# Saga Sınırı Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aynı öznenin (kişi/kulüp) son N günde tekrar tekrar video olmasını, puanına kademeli ve tabansız ceza vererek frenle.

**Architecture:** `category_quota_per_day` ile birebir aynı iskelet, ayrı eksende. Puanlayıcı LLM her adaya bir `subject` atar; `_apply_saga_penalty` o öznenin son N gündeki üretim sayısıyla orantılı ceza uygular; ceza `min_score` tabanı TANIMAZ, yani aday elenebilir ve koşu boş geçebilir. Üretilen video `script_json["subject"]` ile sayaca katkı verir.

**Tech Stack:** Python 3.14, Pydantic v2, SQLAlchemy Core, pytest.

**Spec:** `docs/superpowers/specs/2026-08-18-saga-siniri-design.md`

---

## Çalışma ortamı — worktree KULLANMA

Bu repoda ayrı worktree açmak işi bozar: `.gitignore:37` kanal YAML'larını,
`:72` `tests/` dizinini engelliyor ama repoda zaten takipli test var. Yeni
worktree `config/settings.yaml`, kanal YAML'ları ve testlerin bir kısmı eksik
açılır. **Doğrudan `D:\short` ana ağacında, `feature/electron-installer`
dalında çalış.**

Yeni test dosyaları `git add -f` gerektirir (`tests/` gitignore'da).

Testleri çalıştırma: `cd D:\short; python -m pytest <yol> -v`

---

## Dosya haritası

| dosya | sorumluluk |
|---|---|
| `src/short_bot/topic_taxonomy.py` | `normalize_subject`, `subject_matches` — anahtar biçimi ve eşleşme kuralı |
| `src/short_bot/models.py` | `ScoredItem.subject` (seçim anı), `Script.subject` (kalıcı kayıt) |
| `src/short_bot/scorer.py` | LLM'den özne isteme + `apply_saga_penalty` saf fonksiyonu |
| `src/short_bot/db.py` | `count_recent_subjects` — pencere ve silme kuralı |
| `src/short_bot/config.py` | `saga_penalty_per_repeat`, `saga_window_days` |
| `src/short_bot/pipeline.py` | `_apply_saga_penalty` sarmalayıcı + 2 kalıcılık noktası |
| `config/channels/galatasaray.yaml` | özelliği yalnız bu kanalda aç |
| `tests/test_saga_subject.py` | YENİ — taxonomy + scorer + db birim testleri |
| `tests/test_pipeline_saga_penalty.py` | YENİ — boru hattı entegrasyonu |

---

## Task 1: Özne anahtarı — normalize ve eşleştir

**Files:**
- Modify: `src/short_bot/topic_taxonomy.py` (dosya sonuna ekle)
- Test: `tests/test_saga_subject.py` (yeni)

- [ ] **Step 1: Write the failing test**

`tests/test_saga_subject.py` oluştur:

```python
"""Saga sınırı: özne anahtarının biçimi ve eşleşme kuralı."""
from __future__ import annotations

from short_bot.topic_taxonomy import normalize_subject, subject_matches


def test_normalize_folds_turkish_dotted_i():
    """"İ".lower() görünmez birleşik nokta üretir; iki ayrı kovaya bölerdi."""
    assert normalize_subject("İCARDİ") == "icardi"


def test_normalize_does_not_apply_turkish_i_rule():
    """Kanallar çok dilli: "I"→"ı" İspanyolca özneleri bozardı."""
    assert normalize_subject("INTER") == "inter"


def test_normalize_collapses_whitespace():
    assert normalize_subject("  aleksey   batrakov ") == "aleksey batrakov"


def test_normalize_empty_returns_empty_not_placeholder():
    """Bilinmeyen özne 'sayma' demek; kategorideki '?' kovası burada YANLIŞ."""
    assert normalize_subject("") == ""
    assert normalize_subject(None) == ""


def test_matches_identical():
    assert subject_matches("batrakov", "batrakov") is True


def test_matches_short_key_inside_longer_one():
    """LLM bir gün soyadı, ertesi gün tam ad yazarsa sayaç bölünmemeli."""
    assert subject_matches("batrakov", "aleksey batrakov") is True
    assert subject_matches("aleksey batrakov", "batrakov") is True


def test_does_not_match_mere_substring_of_a_word():
    """'sara' ile 'sarabia' AYRI kişi — harf içermesi yetmez, kelime olmalı."""
    assert subject_matches("sara", "sarabia") is False


def test_does_not_match_on_short_tokens():
    """2-3 harflik anahtar rastgele eşleşme üretir."""
    assert subject_matches("ns", "ns transfer") is False


def test_empty_never_matches():
    assert subject_matches("", "batrakov") is False
    assert subject_matches("batrakov", "") is False


def test_disjoint_subjects_do_not_match():
    assert subject_matches("leao", "osimhen") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\short; python -m pytest tests/test_saga_subject.py -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_subject'`

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/topic_taxonomy.py` dosyasının SONUNA ekle:

```python
# Özne (saga) anahtarları için en kısa anlamlı kelime uzunluğu. Bunun altındaki
# kelimelerde alt-küme eşleşmesi rastgele birleştirme üretir ("ns" her yere uyar).
_SUBJECT_MIN_TOKEN = 4


def normalize_subject(raw: str | None) -> str:
    """Saga öznesini (kişi/kulüp) karşılaştırılabilir tek biçime indir.

    `normalize_category` ile aynı katlama, TEK farkla: boş girdi BOŞ döner,
    `"?"` değil. Bilinmeyen kategori "bilinmeyen kovasında topla" demektir;
    bilinmeyen özne ise "bu videoyu hiç sayma" demektir — ikisini aynı yer
    tutucuya bağlamak, öznesiz videoları tek bir dev sagaya toplar ve o
    sahte saga bütün üretimi kilitlerdi.
    """
    if not isinstance(raw, str):
        return ""
    # "İ".lower() → "i" + U+0307 (görünmez birleşik nokta). "I" → "ı" YAPILMAZ:
    # kanallar çok dilli, Türkçe kuralı İspanyolca/Almanca özneleri bozar.
    text = raw.replace("İ", "i").lower()
    return " ".join(text.split())


def subject_matches(a: str, b: str) -> bool:
    """İki özne anahtarı aynı sagaya mı işaret ediyor.

    LLM bir koşuda "batrakov", diğerinde "aleksey batrakov" yazabilir; bunlar
    ayrı kova sayılırsa sayaç hiç dolmaz ve özellik sessizce işlevsiz kalır.
    Bu yüzden KELİME KÜMESİ alt-kümeliğine bakılır.

    Ham alt-dize (`a in b`) yerine kelime kümesi kullanmanın sebebi:
    "sara" ham alt-dize kuralıyla "sarabia"ya uyardı ve iki ayrı futbolcuyu
    birleştirirdi. Kelime kümesi bu yanlış birleşmeyi yapmaz.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = set(a.split()), set(b.split())
    kisa, uzun = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if not kisa or kisa == uzun:
        return False
    if any(len(t) < _SUBJECT_MIN_TOKEN for t in kisa):
        return False
    return kisa < uzun
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:\short; python -m pytest tests/test_saga_subject.py -v`
Expected: PASS — 10 passed

- [ ] **Step 5: Commit**

```bash
cd D:\short
git add -f src/short_bot/topic_taxonomy.py tests/test_saga_subject.py
git commit -m "feat(saga): özne anahtarı normalizasyonu ve kelime-kümesi eşleşmesi"
```

---

## Task 2: Model alanları

**Files:**
- Modify: `src/short_bot/models.py:33` (ScoredItem), `src/short_bot/models.py:72` civarı (Script)
- Test: `tests/test_saga_subject.py` (ekle)

- [ ] **Step 1: Write the failing test**

`tests/test_saga_subject.py` dosyasının SONUNA ekle:

```python
from datetime import datetime

from short_bot.models import NewsItem, ScoredItem, Script


def test_scored_item_subject_defaults_empty():
    item = NewsItem(guid="g", title="t", link="l", source="s",
                    pub_date=datetime(2026, 8, 18), thumb_url=None, description=None)
    assert ScoredItem(item=item, score=8.0, reasoning="").subject == ""


def test_scored_item_carries_subject():
    item = NewsItem(guid="g", title="t", link="l", source="s",
                    pub_date=datetime(2026, 8, 18), thumb_url=None, description=None)
    s = ScoredItem(item=item, score=8.0, reasoning="", subject="batrakov")
    assert s.subject == "batrakov"


def _script(**kw) -> Script:
    base = dict(header_top="UST", header_bottom="ALT", photo_overlay="foto",
                body_paragraph="Bu bir gövde metnidir, yeterince uzun.",
                category="transfer-gelen", mood="neutral")
    base.update(kw)
    return Script(**base)


def test_script_subject_defaults_empty_and_round_trips():
    """subject script_json'a yazılır; sayaç oradan okur."""
    import json
    assert _script().subject == ""
    dumped = json.loads(_script(subject="batrakov").model_dump_json())
    assert dumped["subject"] == "batrakov"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\short; python -m pytest tests/test_saga_subject.py -v -k subject_defaults`
Expected: FAIL — `TypeError: ScoredItem.__init__() got an unexpected keyword argument 'subject'` (veya `AttributeError`)

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/models.py` — `ScoredItem` içinde, `category` satırının ALTINA:

```python
    # subject: haberin merkezindeki kişi/kulüp (saga anahtarı). Kategoriyle aynı
    # sebeple SEÇİM ANINDA gerekiyor: aynı hikâyenin kaçıncı videosu olduğunu
    # bilmeden puanı düşürülemez. Kanal saga cezasını açmadıysa boş kalır.
    subject: str = ""
```

`src/short_bot/models.py` — `Script` sınıfında, `body_paragraph_tr` alanının ALTINA:

```python
    # subject: saga sayacının anahtarı. Senaryo yazarı LLM'i bunu ÜRETMEZ —
    # seçilen adayın (ScoredItem.subject) değeri kaydetmeden hemen önce
    # taşınır. Aksan temizleyici validator'a BAĞLANMAZ: anahtar eşleşme için
    # kullanılıyor, görsel metin değil.
    subject: str = Field(default="", max_length=40)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:\short; python -m pytest tests/test_saga_subject.py -v`
Expected: PASS — 14 passed

- [ ] **Step 5: Commit**

```bash
cd D:\short
git add -f src/short_bot/models.py tests/test_saga_subject.py
git commit -m "feat(saga): ScoredItem.subject ve Script.subject alanları"
```

---

## Task 3: Ceza fonksiyonu (tabansız)

**Files:**
- Modify: `src/short_bot/scorer.py` (dosya sonu, `apply_category_quota`'nın ALTINA)
- Test: `tests/test_saga_subject.py` (ekle)

- [ ] **Step 1: Write the failing test**

`tests/test_saga_subject.py` dosyasının SONUNA ekle:

```python
from short_bot.scorer import apply_saga_penalty


def _si(guid, score, subject):
    item = NewsItem(guid=guid, title=guid, link="l", source="s",
                    pub_date=datetime(2026, 8, 18), thumb_url=None, description=None)
    return ScoredItem(item=item, score=score, reasoning="", subject=subject)


def test_penalty_scales_with_repeat_count():
    scored = [_si("g", 9.0, "batrakov")]
    out = apply_saga_penalty(scored, produced={"batrakov": 3}, step=1.0)
    assert out[0].score == 6.0


def test_first_appearance_is_free():
    scored = [_si("g", 9.0, "batrakov")]
    out = apply_saga_penalty(scored, produced={}, step=1.0)
    assert out[0].score == 9.0


def test_penalty_has_NO_min_score_floor():
    """Kotadan ayrılan nokta: saga cezası adayı eşiğin ALTINA itebilir.

    Gerekçe ölçüm: üretilenin %42'si zaten yayına çıkmıyor, yani boş geçmek
    yüklenmeyecek zayıf video üretmekten ucuz.
    """
    scored = [_si("g", 9.0, "batrakov")]
    out = apply_saga_penalty(scored, produced={"batrakov": 5}, step=1.0)
    assert out[0].score == 4.0        # 6.0'lık min_score'un ALTINDA


def test_penalty_never_goes_below_zero():
    scored = [_si("g", 2.0, "batrakov")]
    out = apply_saga_penalty(scored, produced={"batrakov": 9}, step=1.0)
    assert out[0].score == 0.0


def test_empty_subject_is_never_penalised():
    scored = [_si("g", 9.0, "")]
    out = apply_saga_penalty(scored, produced={"batrakov": 5}, step=1.0)
    assert out[0].score == 9.0


def test_step_zero_is_passthrough():
    """Kapalı kanallarda (varsayılan) hiçbir puan değişmez."""
    scored = [_si("g", 9.0, "batrakov")]
    out = apply_saga_penalty(scored, produced={"batrakov": 5}, step=0.0)
    assert out[0].score == 9.0


def test_counts_across_matching_key_variants():
    """'batrakov' ve 'aleksey batrakov' AYNI sagadır; sayı toplanır."""
    scored = [_si("g", 9.0, "batrakov")]
    out = apply_saga_penalty(
        scored, produced={"batrakov": 1, "aleksey batrakov": 2}, step=1.0)
    assert out[0].score == 6.0


def test_unrelated_subject_untouched():
    scored = [_si("g", 9.0, "osimhen")]
    out = apply_saga_penalty(scored, produced={"batrakov": 5}, step=1.0)
    assert out[0].score == 9.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\short; python -m pytest tests/test_saga_subject.py -v -k saga_penalty`
Expected: FAIL — `ImportError: cannot import name 'apply_saga_penalty'`

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/scorer.py` — import satırını güncelle (satır 11):

```python
from short_bot.topic_taxonomy import normalize_category, subject_matches
```

Dosyanın SONUNA (`apply_category_quota`'nın altına) ekle:

```python
def saga_repeat_count(subject: str, produced: dict[str, int]) -> int:
    """`subject` ile aynı sagaya işaret eden üretilmiş video sayısı.

    Anahtar biçimi koşudan koşuya oynayabildiği için düz sözlük araması
    yetmez; `subject_matches` kelime-kümesi kuralını uygular.
    """
    if not subject:
        return 0
    return sum(n for key, n in produced.items() if subject_matches(subject, key))


def apply_saga_penalty(
    scored: list[ScoredItem],
    *,
    produced: dict[str, int],
    step: float,
) -> list[ScoredItem]:
    """Aynı öznenin tekrarında puanı kademeli düşür. TABAN YOK.

    `apply_category_quota`'dan AYRILAN NOKTA budur: kota `floor` alır ve
    cezanın adayı `min_score` altına itmesini engeller, çünkü kota SIRALAMA
    aracıdır. Saga sınırı ise VETO aracıdır — aynı hikâyenin altıncı videosu
    hiç çıkmamalıdır, zayıf bir alternatifle yer değiştirmesi bile gerekmez.

    Ölçüm gerekçesi (2026-08-18, 29 gün): üretilen 292 videonun yalnız 168'i
    yüklendi. Boş geçen bir koşu, yüklenmeyecek bir videodan ucuzdur.

    `produced`: son pencerede özne başına üretilen video sayısı
                (`db.count_recent_subjects`).
    `step`:     tekrar başına düşülecek puan. 0.0 = özellik kapalı.
    """
    if not step:
        return scored
    out: list[ScoredItem] = []
    for s in scored:
        n = saga_repeat_count(s.subject, produced)
        if n:
            out.append(replace(s, score=max(0.0, s.score - step * n)))
        else:
            out.append(s)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:\short; python -m pytest tests/test_saga_subject.py -v`
Expected: PASS — 22 passed

- [ ] **Step 5: Commit**

```bash
cd D:\short
git add -f src/short_bot/scorer.py tests/test_saga_subject.py
git commit -m "feat(saga): kademeli ceza — kotanın aksine min_score tabanı yok"
```

---

## Task 4: Sayaç — `count_recent_subjects`

**Files:**
- Modify: `src/short_bot/db.py` (`count_recent_categories`'ın hemen ALTINA, satır 563 sonrası)
- Test: `tests/test_saga_subject.py` (ekle)

- [ ] **Step 1: Write the failing test**

`tests/test_saga_subject.py` dosyasının SONUNA ekle:

```python
import json as _json
from datetime import timezone

from sqlalchemy import update

from short_bot.db import (
    count_recent_subjects, init_db, record_short, record_youtube_upload, shorts,
)


def _rec(eng, subject, **kw):
    return record_short(
        eng, channel="gs", rss_item_guid=kw.get("guid", subject),
        title=subject, file_path="x.mp4", duration_s=6,
        script_json=_json.dumps({"subject": subject}), render_ms=1)


def _sil(eng, short_id):
    """deleted_at'i doğrudan yaz.

    `db.py`'de soft-delete yardımcısı YOK — silme web katmanında ORM ile
    yapılıyor (`web/models.py`). Test tabloyu doğrudan güncelliyor.
    """
    with eng.begin() as conn:
        conn.execute(update(shorts).where(shorts.c.id == short_id)
                     .values(deleted_at=datetime.now(timezone.utc)))


def test_counts_produced_subjects(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _rec(eng, "batrakov", guid="a")
    _rec(eng, "batrakov", guid="b")
    _rec(eng, "leao", guid="c")
    assert count_recent_subjects(eng, "gs", days=14) == {"batrakov": 2, "leao": 1}


def test_normalises_keys_while_counting(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _rec(eng, "Batrakov", guid="a")
    _rec(eng, "  batrakov ", guid="b")
    assert count_recent_subjects(eng, "gs", days=14) == {"batrakov": 2}


def test_ignores_records_without_subject(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    record_short(eng, channel="gs", rss_item_guid="a", title="t",
                 file_path="x.mp4", duration_s=6,
                 script_json=_json.dumps({"category": "transfer-gelen"}),
                 render_ms=1)
    assert count_recent_subjects(eng, "gs", days=14) == {}


def test_other_channels_are_not_counted(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    record_short(eng, channel="fb", rss_item_guid="a", title="t",
                 file_path="x.mp4", duration_s=6,
                 script_json=_json.dumps({"subject": "batrakov"}), render_ms=1)
    assert count_recent_subjects(eng, "gs", days=14) == {}


def test_deleted_without_upload_is_not_counted(tmp_path):
    """Operatör akışı: beğenmezse doğrudan siler. Reddedilen video sayılmaz."""
    eng = init_db(tmp_path / "x.sqlite")
    sid = _rec(eng, "batrakov", guid="a")
    _sil(eng, sid)
    assert count_recent_subjects(eng, "gs", days=14) == {}


def test_uploaded_then_deleted_IS_counted(tmp_path):
    """Beğenirse YÜKLER ve listeden siler — izleyici gördü, sayılmalı."""
    eng = init_db(tmp_path / "x.sqlite")
    sid = _rec(eng, "batrakov", guid="a")
    record_youtube_upload(eng, short_id=sid, video_id="v1", status="success",
                          error=None, video_url="u")
    _sil(eng, sid)
    assert count_recent_subjects(eng, "gs", days=14) == {"batrakov": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\short; python -m pytest tests/test_saga_subject.py -v -k count_recent_subjects`
Expected: FAIL — `ImportError: cannot import name 'count_recent_subjects'`

İmzalar doğrulandı (2026-08-18):
`record_youtube_upload(eng, *, short_id, video_id, status, error, video_url)`,
`record_short(eng, *, channel, rss_item_guid, title, file_path, duration_s, script_json, render_ms)`.

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/db.py` — `count_recent_categories`'ın döndüğü satırın (563) ALTINA:

```python
def count_recent_subjects(
    eng: Engine, channel: str, *, days: int = 14,
) -> dict[str, int]:
    """Son `days` günde bu kanalda hangi özneden kaç video üretildi.

    Saga cezasının girdisi. `count_recent_categories` ile AYNI join'i kullanır
    ve bu bilinçlidir: "silinmiş" ile "reddedilmiş" aynı şey değil. Operatör
    beğendiği videoyu YÜKLEYİP listeden siliyor; yalnız `deleted_at`'e bakan
    bir filtre, yayınlanmış videoları saymayıp sayacı fiilen öldürürdü.
    Sayılan: yayınlanan + henüz karar verilmemiş. Sayılmayan: yüklenmeden
    silinmiş (operatörün reddettiği).
    """
    import json as _json
    from short_bot.topic_taxonomy import normalize_subject

    cutoff = _utcnow() - timedelta(days=days)
    counts: dict[str, int] = {}
    with eng.connect() as conn:
        rows = conn.execute(
            select(shorts.c.script_json)
            .select_from(
                shorts.outerjoin(youtube_uploads,
                                 youtube_uploads.c.short_id == shorts.c.id)
            )
            .where(shorts.c.channel == channel)
            .where(shorts.c.created_at >= cutoff)
            .where(~(shorts.c.deleted_at.is_not(None)
                     & youtube_uploads.c.id.is_(None)))
        ).all()
    for (script_json,) in rows:
        try:
            raw = (_json.loads(script_json or "{}") or {}).get("subject")
        except (TypeError, ValueError):
            raw = None
        if not raw:
            continue
        key = normalize_subject(raw)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:\short; python -m pytest tests/test_saga_subject.py -v`
Expected: PASS — 28 passed

- [ ] **Step 5: Commit**

```bash
cd D:\short
git add -f src/short_bot/db.py tests/test_saga_subject.py
git commit -m "feat(saga): count_recent_subjects — kota sayacıyla aynı silme kuralı"
```

---

## Task 5: Config alanları

**Files:**
- Modify: `src/short_bot/config.py:349` civarı (alanlar), `:519` civarı (load), `:567` civarı (save)
- Test: `tests/test_saga_subject.py` (ekle)

- [ ] **Step 1: Write the failing test**

`tests/test_saga_subject.py` dosyasının SONUNA ekle:

```python
from short_bot.config import load_channel, save_channel


def test_saga_fields_default_to_disabled(tmp_path):
    """Varsayılan 0.0 — mevcut kanalların hiçbiri etkilenmez."""
    from dataclasses import replace as _replace

    from short_bot.config import ChannelConfig
    cfg = ChannelConfig(
        slug="gs", name="GS", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, template="stadium",
        colors={"primary": "#fff"}, handle="@x", output_dir="out",
        enabled=True, language="tr",
    )
    assert cfg.saga_penalty_per_repeat == 0.0
    assert cfg.saga_window_days == 14
    assert _replace(cfg, saga_penalty_per_repeat=1.0).saga_penalty_per_repeat == 1.0


def test_saga_fields_round_trip_through_yaml(tmp_path):
    from dataclasses import replace as _replace

    from short_bot.config import ChannelConfig
    cfg = ChannelConfig(
        slug="gs", name="GS", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, template="stadium",
        colors={"primary": "#fff"}, handle="@x", output_dir="out",
        enabled=True, language="tr",
    )
    p = tmp_path / "gs.yaml"
    save_channel(p, _replace(cfg, saga_penalty_per_repeat=1.0, saga_window_days=10))
    back = load_channel(p)
    assert back.saga_penalty_per_repeat == 1.0
    assert back.saga_window_days == 10


def test_disabled_channel_yaml_stays_clean(tmp_path):
    """Kapalıyken YAML'a anahtar YAZILMAZ — mevcut dosyalar kirlenmesin."""
    from short_bot.config import ChannelConfig
    cfg = ChannelConfig(
        slug="gs", name="GS", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, template="stadium",
        colors={"primary": "#fff"}, handle="@x", output_dir="out",
        enabled=True, language="tr",
    )
    p = tmp_path / "gs.yaml"
    save_channel(p, cfg)
    assert "saga_penalty_per_repeat" not in p.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\short; python -m pytest tests/test_saga_subject.py -v -k saga_fields`
Expected: FAIL — `AttributeError: 'ChannelConfig' object has no attribute 'saga_penalty_per_repeat'`

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/config.py` — `category_quota_per_day` alanının (satır 349) hemen ALTINA:

```python
    # saga_penalty_per_repeat: aynı ÖZNENİN (kişi/kulüp) her tekrarında puandan
    # düşülecek miktar. 0.0 = kapalı (varsayılan, tüm mevcut kanallar).
    # Kategori kotasından farkı: bu cezanın min_score tabanı YOKTUR, aday
    # elenebilir ve koşu boş geçebilir. Bkz. scorer.apply_saga_penalty.
    saga_penalty_per_repeat: float = 0.0
    # Sayım penceresi. dedup.filter_new'ün lookback_days'iyle hizalı tutuldu:
    # ayrışırlarsa "dedup'tan düştü ama saga sayacında hâlâ var" gibi
    # açıklanması zor bir aralık doğar.
    saga_window_days: int = 14
```

`src/short_bot/config.py` — `load_channel` içinde, `category_quota_per_day=...` satırının (519) ALTINA:

```python
        saga_penalty_per_repeat=float(data.get("saga_penalty_per_repeat") or 0.0),
        saga_window_days=int(data.get("saga_window_days") or 14),
```

`src/short_bot/config.py` — `save_channel` içinde, `category_quota_per_day` bloğunun (567) ALTINA:

```python
    if cfg.saga_penalty_per_repeat:
        data["saga_penalty_per_repeat"] = cfg.saga_penalty_per_repeat
        data["saga_window_days"] = cfg.saga_window_days
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:\short; python -m pytest tests/test_saga_subject.py -v`
Expected: PASS — 31 passed

- [ ] **Step 5: Commit**

```bash
cd D:\short
git add -f src/short_bot/config.py tests/test_saga_subject.py
git commit -m "feat(saga): saga_penalty_per_repeat + saga_window_days config alanları"
```

---

## Task 6: Puanlayıcıdan özne isteme

**Files:**
- Modify: `src/short_bot/scorer.py:22` (`_ItemScore`), `:158-164` (prompt), `:225-228` (ScoredItem kurulumu)
- Test: `tests/test_saga_subject.py` (ekle)

- [ ] **Step 1: Write the failing test**

`tests/test_saga_subject.py` dosyasının SONUNA ekle:

```python
from short_bot.scorer import build_scoring_prompt


def _ch(**kw):
    from dataclasses import replace as _replace

    from short_bot.config import ChannelConfig
    base = ChannelConfig(
        slug="gs", name="Aslan Gündem", keywords=["Galatasaray"], rss_locale="hl=tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, template="stadium",
        colors={"primary": "#fff"}, handle="@x", output_dir="out",
        enabled=True, language="tr",
    )
    return _replace(base, **kw)


def _items():
    return [NewsItem(guid="g1", title="Batrakov geldi", link="l", source="s",
                     pub_date=datetime(2026, 8, 18), thumb_url=None, description=None)]


def test_prompt_asks_for_subject_when_saga_enabled():
    p = build_scoring_prompt(_items(), channel=_ch(saga_penalty_per_repeat=1.0))
    assert '"subject"' in p


def test_prompt_stays_unchanged_when_saga_disabled():
    """Kapalı kanalların prompt'u hiç değişmemeli."""
    p = build_scoring_prompt(_items(), channel=_ch())
    assert "subject" not in p


def test_prompt_forbids_the_channel_subject_as_key():
    """Her haberde 'Galatasaray' geçiyor; anahtar olarak işe yaramaz."""
    p = build_scoring_prompt(_items(), channel=_ch(saga_penalty_per_repeat=1.0))
    assert "Aslan Gündem" in p or "Galatasaray" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\short; python -m pytest tests/test_saga_subject.py -v -k prompt`
Expected: FAIL — `test_prompt_asks_for_subject_when_saga_enabled` FAILED, `'"subject"' in p` yanlış

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/scorer.py` — `_ItemScore` içine, `category` alanının ALTINA:

```python
    # Yalnız kanal saga cezasını açtığında istenir; aksi halde boş.
    subject: str = Field(default="", max_length=40)
```

`src/short_bot/scorer.py` — `build_scoring_prompt` içinde, `if channel.categories:` bloğunun (158-164) hemen ALTINA:

```python
    # Saga anahtarı: aynı hikâyenin kaçıncı videosu olduğunu seçim anında
    # bilmek gerekiyor. Yalnız özellik açıkken sorulur — kapalı kanalların
    # prompt'u bit bit aynı kalsın.
    if channel.saga_penalty_per_repeat:
        base = base + (
            "\n\nAyrıca her başlığa haberin MERKEZİNDEKİ özneyi ata: transferi "
            f"ya da haberi yapılan KİŞİ veya KULÜP. \"{channel.name}\" ve "
            f"\"{keywords_str}\" içindeki kanal öznesini ASLA yazma — her "
            "haberde geçtiği için anahtar olarak işe yaramaz.\n"
            "Kişide YALNIZ SOYADI yaz (\"batrakov\", \"leao\"), kulüpte kısa "
            "ad (\"milan\"). Küçük harf, tek kelime tercih et. Aynı kişi her "
            "koşuda AYNI yazılmalı. Merkezde belirgin bir özne yoksa boş bırak.\n"
            'JSON alanı: "subject": "<soyadı veya kısa kulüp adı>"'
        )
```

`src/short_bot/scorer.py` — `score_items` içinde ScoredItem kurulumunu (225-228) değiştir:

```python
            out.append(ScoredItem(item=item, score=s.score,
                                  reasoning=s.reasoning,
                                  category=normalize_category(s.category)
                                           if s.category else "",
                                  subject=normalize_subject(s.subject)))
```

Import satırını güncelle (satır 11):

```python
from short_bot.topic_taxonomy import (
    normalize_category, normalize_subject, subject_matches,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:\short; python -m pytest tests/test_saga_subject.py -v`
Expected: PASS — 34 passed

- [ ] **Step 5: Commit**

```bash
cd D:\short
git add -f src/short_bot/scorer.py tests/test_saga_subject.py
git commit -m "feat(saga): puanlayıcı seçim anında özne atıyor"
```

---

## Task 7: Boru hattına bağla

**Files:**
- Modify: `src/short_bot/pipeline.py:149` sonrası (yeni sarmalayıcı), `:1032-1034` (çağrı yeri), `:1794` (`_run_feed` çağrı yeri)
- Test: `tests/test_pipeline_saga_penalty.py` (yeni)

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline_saga_penalty.py` oluştur:

```python
"""Boru hattının saga cezasını seçim öncesi uygulaması."""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime

from short_bot.config import ChannelConfig
from short_bot.db import init_db, record_short
from short_bot.models import NewsItem, ScoredItem
from short_bot.pipeline import _apply_saga_penalty


def _channel(**kw) -> ChannelConfig:
    base = ChannelConfig(
        slug="gs", name="GS", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, template="stadium",
        colors={"primary": "#fff"}, handle="@x", output_dir="out",
        enabled=True, language="tr",
    )
    return replace(base, **kw)


def _scored(guid, score, subject):
    item = NewsItem(guid=guid, title=guid, link="l", source="s",
                    pub_date=datetime(2026, 8, 18), thumb_url=None, description=None)
    return ScoredItem(item=item, score=score, reasoning="", subject=subject)


def _produce(eng, subject, n):
    for i in range(n):
        record_short(eng, channel="gs", rss_item_guid=f"{subject}-{i}",
                     title=f"{subject}-{i}", file_path="x.mp4", duration_s=6,
                     script_json=json.dumps({"subject": subject}), render_ms=1)


def test_saturated_saga_loses_to_a_fresh_one(tmp_path):
    """Asıl amaç: Batrakov'un 4. videosu yerine başka hikâye seçilsin."""
    eng = init_db(tmp_path / "x.sqlite")
    _produce(eng, "batrakov", 3)
    ch = _channel(saga_penalty_per_repeat=1.0)

    scored = [_scored("g1", 9.0, "batrakov"), _scored("g2", 7.0, "osimhen")]
    out = _apply_saga_penalty(scored, channel=ch, eng=eng,
                              log=logging.getLogger("t"))

    best = max(out, key=lambda s: s.score)
    assert best.item.guid == "g2"
    assert best.subject == "osimhen"


def test_penalty_can_push_below_min_score(tmp_path):
    """Kotadan ayrılan davranış: aday tamamen elenebilir."""
    eng = init_db(tmp_path / "x.sqlite")
    _produce(eng, "batrakov", 5)
    ch = _channel(saga_penalty_per_repeat=1.0)

    out = _apply_saga_penalty([_scored("g1", 9.0, "batrakov")],
                              channel=ch, eng=eng, log=logging.getLogger("t"))
    assert out[0].score == 4.0
    assert out[0].score < ch.min_score


def test_disabled_channel_is_passthrough(tmp_path):
    """Varsayılan 0.0 — diğer tüm kanallar bit bit aynı davranır."""
    eng = init_db(tmp_path / "x.sqlite")
    _produce(eng, "batrakov", 5)
    scored = [_scored("g1", 9.0, "batrakov")]

    out = _apply_saga_penalty(scored, channel=_channel(), eng=eng,
                              log=logging.getLogger("t"))
    assert out == scored


def test_window_excludes_nothing_when_recent(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _produce(eng, "batrakov", 2)
    ch = _channel(saga_penalty_per_repeat=0.5, saga_window_days=14)

    out = _apply_saga_penalty([_scored("g1", 9.0, "batrakov")],
                              channel=ch, eng=eng, log=logging.getLogger("t"))
    assert out[0].score == 8.0


def test_logs_the_reason(tmp_path, caplog):
    """Günlükte 'neden cezalandı' okunabilir olmalı."""
    eng = init_db(tmp_path / "x.sqlite")
    _produce(eng, "batrakov", 3)
    ch = _channel(saga_penalty_per_repeat=1.0)
    log = logging.getLogger("saga-test")

    with caplog.at_level(logging.INFO, logger="saga-test"):
        _apply_saga_penalty([_scored("g1", 9.0, "batrakov")],
                            channel=ch, eng=eng, log=log)
    assert "batrakov" in caplog.text
    assert "saga" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\short; python -m pytest tests/test_pipeline_saga_penalty.py -v`
Expected: FAIL — `ImportError: cannot import name '_apply_saga_penalty' from 'short_bot.pipeline'`

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/pipeline.py` — `_apply_category_quota`'nın (149'da biter) hemen ALTINA:

```python
def _apply_saga_penalty(
    scored: list[ScoredItem],
    *,
    channel: ChannelConfig,
    eng,
    log: logging.Logger,
) -> list[ScoredItem]:
    """Aynı öznenin tekrarında aday puanını kademeli düşür.

    Kategori kotasından SONRA çalışır ve bu sıra bilinçlidir: kota puanı
    min_score'a sabitler, saga cezası onu tabanın ALTINA indirebilir. Kota
    konu çeşitliliği aracıdır, saga sınırı tekrar vetosudur; çatışırlarsa
    veto kazanmalıdır.

    Cezası 0.0 olan kanallarda (varsayılan) hiçbir etkisi yok.
    """
    if not channel.saga_penalty_per_repeat:
        return scored
    from short_bot.db import count_recent_subjects
    from short_bot.scorer import apply_saga_penalty, saga_repeat_count

    produced = count_recent_subjects(eng, channel.slug,
                                     days=channel.saga_window_days)
    out = apply_saga_penalty(scored, produced=produced,
                             step=channel.saga_penalty_per_repeat)
    for before, after in zip(scored, out):
        if after.score < before.score:
            n = saga_repeat_count(before.subject, produced)
            log.info(f"  [saga] '{before.subject}' son "
                     f"{channel.saga_window_days}g'de {n} kez geçti → "
                     f"puan {before.score:.1f}→{after.score:.1f}")
    return out
```

`src/short_bot/pipeline.py` — `_run_rss` içinde, satır 1032'yi şu iki satırla değiştir:

```python
    scored = _apply_category_quota(scored, channel=channel, eng=eng, log=log)
    scored = _apply_saga_penalty(scored, channel=channel, eng=eng, log=log)
```

`src/short_bot/pipeline.py` — `_run_feed` içinde, satır 1794'ü şu iki satırla değiştir:

```python
    scored = _apply_category_quota(scored, channel=channel, eng=eng, log=log)
    scored = _apply_saga_penalty(scored, channel=channel, eng=eng, log=log)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:\short; python -m pytest tests/test_pipeline_saga_penalty.py tests/test_pipeline_category_quota.py -v`
Expected: PASS — saga 5 passed, kota testleri de hâlâ passed

- [ ] **Step 5: Commit**

```bash
cd D:\short
git add -f src/short_bot/pipeline.py tests/test_pipeline_saga_penalty.py
git commit -m "feat(saga): boru hattı kotadan sonra saga cezasını uyguluyor"
```

---

## Task 8: Özneyi kalıcı yaz (iki nokta)

**Files:**
- Modify: `src/short_bot/pipeline.py:726-731` (`_produce_from_item` imzası), `:904-908` (kayıt), `:1300-1305` (kayıt), `:1811-1815` (çağrı)
- Test: `tests/test_pipeline_saga_penalty.py` (ekle)

**Neden iki nokta:** `_run_rss` kendi `record_short`'unu çağırıyor (1300),
`_run_feed` ise `_produce_from_item` üzerinden (908). Birini atlamak, o yoldan
üretilen videoların sayaçta kör satır bırakmasına yol açar — `pipeline.py:743-745`
aynı hatanın daha önce dedup'ta yaşandığını kaydediyor.

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline_saga_penalty.py` dosyasının SONUNA ekle:

```python
from short_bot.models import Script


def _script(**kw) -> Script:
    base = dict(header_top="UST", header_bottom="ALT", photo_overlay="foto",
                body_paragraph="Bu bir gövde metnidir, yeterince uzun.",
                category="transfer-gelen", mood="neutral")
    base.update(kw)
    return Script(**base)


def test_subject_survives_into_the_counter(tmp_path):
    """Uçtan uca: seçilen adayın öznesi script_json'a yazılıp sayaca dönmeli."""
    from short_bot.db import count_recent_subjects

    eng = init_db(tmp_path / "x.sqlite")
    script = _script().model_copy(update={"subject": "batrakov"})
    record_short(eng, channel="gs", rss_item_guid="a", title="t",
                 file_path="x.mp4", duration_s=6,
                 script_json=script.model_dump_json(), render_ms=1)

    assert count_recent_subjects(eng, "gs", days=14) == {"batrakov": 1}


def test_produce_from_item_accepts_subject_kwarg():
    """_run_feed öznesini bu parametreyle taşıyor; imza kaybolursa sessizce
    kör satır yazılır."""
    import inspect

    from short_bot.pipeline import _produce_from_item
    assert "subject" in inspect.signature(_produce_from_item).parameters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\short; python -m pytest tests/test_pipeline_saga_penalty.py -v -k subject`
Expected: FAIL — `test_produce_from_item_accepts_subject_kwarg` AssertionError

- [ ] **Step 3: Write minimal implementation**

`src/short_bot/pipeline.py` — `_produce_from_item` imzasına (729 civarı) ekle:

```python
    score: float | None = None,
    subject: str = "",
    defer_upload: bool = False,
```

`src/short_bot/pipeline.py` — satır 904-908'i değiştir:

```python
    # Saga sayacının anahtarı: senaryo yazarı üretmez, seçilen adaydan taşınır.
    short_id = record_short(
        eng, channel=channel.slug, rss_item_guid=item.guid,
        title=script.header_top + " " + script.header_bottom,
        file_path=str(out_path), duration_s=channel.duration_s,
        script_json=script.model_copy(update={"subject": subject}).model_dump_json(),
        render_ms=render_ms)
```

`src/short_bot/pipeline.py` — satır 1300-1305'i değiştir:

```python
    short_id = record_short(eng,
        channel=channel.slug, rss_item_guid=picked.item.guid,
        title=script.header_top + " " + script.header_bottom,
        file_path=str(out_path), duration_s=channel.duration_s,
        script_json=script.model_copy(
            update={"subject": picked.subject}).model_dump_json(),
        render_ms=render_ms,
    )
```

`src/short_bot/pipeline.py` — satır 1811-1815'teki `_run_feed` çağrısına ekle:

```python
    res = _produce_from_item(
        item=chosen.item, channel=channel, eng=eng, settings=settings,
        log=log, music_root=music_root, templates_dir=templates_dir,
        cache_dir=cache_dir, run_id=run_id, score=chosen.score,
        subject=chosen.subject,
        defer_upload=defer_upload)
```

Satır 636'daki çağrı (panelden elle SEÇİLEN haber) DEĞİŞMEZ: orada puanlayıcı
hiç çalışmıyor, dolayısıyla özne yok. Varsayılan `""` ile geçer ve sayaca
katkı vermez — bilinçli, çünkü elle seçilen tek seferlik videolar sagayı
temsil etmiyor.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:\short; python -m pytest tests/test_pipeline_saga_penalty.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
cd D:\short
git add -f src/short_bot/pipeline.py tests/test_pipeline_saga_penalty.py
git commit -m "feat(saga): özne script_json'a yazılıyor — her iki üretim yolunda"
```

---

## Task 9: Kanalda aç ve tüm paketi doğrula

**Files:**
- Modify: `config/channels/galatasaray.yaml`

- [ ] **Step 1: Kanalı aç**

`config/channels/galatasaray.yaml` — `category_quota_per_day` bloğunun ALTINA:

```yaml
# Saga sınırı: aynı ÖZNENİN (kişi/kulüp) tekrarında puan kademeli düşer.
# Ölçüm (2026-08-18, 29 gün): Batrakov 15 günde 4 kez, Gabriel Sara 29 günde
# 14 kez yayınlanmış. Mevcut dedup tek haber düzeyinde çalışıp gelen haberin
# %53'ünü eliyor ama sagayı görmüyor.
# Kategori kotasından farkı: bu cezanın min_score tabanı YOK, aday elenebilir
# ve koşu boş geçebilir. Gerekçe: üretilen 292 videonun yalnız 168'i yüklendi,
# yani boş geçmek yüklenmeyecek video üretmekten ucuz.
# 1.0 ÖLÇÜLMÜŞ DEĞİL — ilk tahmin. Bir hafta izlenip ayarlanacak.
saga_penalty_per_repeat: 1.0
saga_window_days: 14
```

- [ ] **Step 2: Config'in yüklendiğini doğrula**

Run:
```bash
cd D:\short
python -c "from pathlib import Path; from short_bot.config import load_channel; c=load_channel(Path('config/channels/galatasaray.yaml')); print(c.saga_penalty_per_repeat, c.saga_window_days)"
```
Expected: `1.0 14`

- [ ] **Step 3: Başka kanalın etkilenmediğini doğrula**

Run:
```bash
cd D:\short
python -c "from pathlib import Path; from short_bot.config import load_channel; c=load_channel(Path('config/channels/fenerbahce.yaml')); print(c.saga_penalty_per_repeat)"
```
Expected: `0.0`

- [ ] **Step 4: Tüm test paketini çalıştır**

Run: `cd D:\short; python -m pytest -q`
Expected: Bilinen taban 2 hata dışında hepsi geçer —
`tests/test_narration_style_rules.py::test_curated_prompt_carries_the_rule_for_japanese`
ve `tests/test_web_voice_ui.py::test_voices_endpoint_returns_list` ortam
kaynaklı (eksik `config/channels/yasashisa.yaml`, ElevenLabs bağımlılığı).
Bunlar DIŞINDA yeni hata varsa gerileme demektir — düzelt.

Paket ~23 dakika sürüyor; arka planda çalıştır.

- [ ] **Step 5: Commit**

```bash
cd D:\short
git add -f config/channels/galatasaray.yaml
git commit -m "feat(saga): Aslan Gündem'de saga sınırı açıldı (step=1.0, 14 gün)"
```

---

## Uygulama sonrası — canlı doğrulama

Plan bittiğinde özellik ÇALIŞIYOR ama etkisi 14 günde ısınır (eski
`script_json` kayıtlarında `subject` yok → sayım 0 → ceza yok).

İlk koşudan sonra bakılacak:

```bash
cd D:\short
python -c "import sqlite3,json; c=sqlite3.connect(r'data/short_bot.sqlite'); print([json.loads(r[0]).get('subject') for r in c.execute(\"select script_json from shorts where channel='galatasaray' order by created_at desc limit 5\")])"
```

Beklenen: son videoların öznesi dolu (`batrakov`, `leao`, …). Hepsi boşsa LLM
alanı üretmiyordur → prompt'u sertleştir.

Bir hafta sonra `step` ayarı: `[saga]` satırlarını say. Hiç yoksa çok gevşek,
her koşuda varsa çok sert.

```bash
cd D:\short
grep -rc "\[saga\]" logs/runs/*galatasaray.log | grep -v ":0"
```
