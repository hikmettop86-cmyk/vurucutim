# Autopilot (Otomatik Üretim + Zamanlı Yükleme) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kanal başına günde N video, insan-benzeri yayın saatlerinde; üretim yüklemeden saatler önce koşar, yayın anı YouTube'un `publishAt`'iyle (ya da slot anında canlı yüklemeyle) kesinleşir.

**Architecture:** Üretim ve yükleme birbirinden ayrılır. `publish_slots` tablosu tek doğruluk kaynağıdır. Saf `autopilot.py` bütün zamanlama mantığını (taban saatler + rastgele yürüyüş jitter) tutar — DB'ye, saate, ağa dokunmaz. `autopilot_runner.py` durum makinesini yürütür ve bütün yan etkileri enjekte edilen `AutopilotDeps` üzerinden yapar. Scheduler yalnız iki cron bağlar.

**Tech Stack:** Python 3.14, SQLAlchemy Core, pydantic v2, APScheduler, zoneinfo, pytest.

**Spec:** `docs/superpowers/specs/2026-07-14-otomatik-uretim-ve-yukleme-tasarim.md`

---

## Dosya Yapısı

| Dosya | Sorumluluk |
|---|---|
| `src/short_bot/autopilot.py` | **YENİ.** Saf zamanlama: taban saatler, jitter rastgele yürüyüşü, slot planı, `produce_at`, `due`/`stale` kararları. DB yok, saat yok, ağ yok. |
| `src/short_bot/autopilot_runner.py` | **YENİ.** Durum makinesi. Yan etkiler `AutopilotDeps` ile enjekte edilir → APScheduler/ağ olmadan test edilir. |
| `src/short_bot/db.py` | `publish_slots` tablosu + yardımcılar. |
| `src/short_bot/config.py` | `AutopilotConfig` + `ChannelConfig.autopilot` + YAML yükle/kaydet. |
| `src/short_bot/pipeline.py` | `RunResult.short_id`; `run_pipeline(defer_upload=...)` → **çifte yükleme** engeli. |
| `src/short_bot/youtube/auto_upload.py` | `run_auto_upload(publish_at=...)` → gizli + zamanlı yükleme. |
| `src/short_bot/web/scheduler.py` | Autopilot açık kanalın cron'u **kaydedilmez** (çifte üretim engeli) + iki yeni cron. |
| `src/short_bot/web/routes/autopilot.py` | **YENİ.** Panel: slotlar, aç/kapat. |
| `src/short_bot/web/templates/autopilot.html.j2` | **YENİ.** |
| `src/short_bot/web/routes/series.py` | "Bu bölümü şimdi üret" düğmesi. |

**Neden iki modül:** `autopilot.py` saf olduğu için jitter/slot mantığı saniyeler içinde, yüzlerce senaryoyla test edilir. `autopilot_runner.py` ise yalnız *sıralama* ve *durum geçişi* mantığıdır; onun testleri de sahte deps ile anında koşar. Zamanlama hatasının sessizce üretime sızmasının önündeki tek gerçek engel budur.

---

### Task 1: Saf zamanlama modülü — `autopilot.py`

**Files:**
- Create: `src/short_bot/autopilot.py`
- Test: `tests/test_autopilot.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_autopilot.py
"""Autopilot zamanlaması: insan ritmi, çakışmasız, deterministik.

SESSİZ BOZULMA RİSKİ: yanlış bir slot saati hata vermez — sadece video yanlış
saatte (ya da hiç) yayınlanır. O yüzden bu modülün her kuralı ölçülüyor.
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from short_bot.autopilot import (LIVE_GRACE_MIN, MIN_SLOT_GAP_MIN, Slot,
                                 base_minutes, is_stale, next_jitter, plan_day,
                                 produce_at, slot_is_due)

TR = ZoneInfo("Europe/Istanbul")


class _Cfg:
    daily_count = 3
    active_hours = (10, 22)
    jitter_minutes = 15
    jitter_step = 6
    produce_lead_hours = 3


# --- TABAN SAATLER ---------------------------------------------------------

def test_taban_saatler_blok_ORTALARINA_oturur():
    """Uçlara koyarsak jitter aktif saatlerden TAŞAR. Ortaya koyunca taşma
    yapısal olarak imkânsız."""
    assert base_minutes((10, 22), 3) == [12 * 60, 16 * 60, 20 * 60]


def test_taban_saatler_sirali_ve_aktif_saatler_icinde():
    for n in (1, 2, 3, 5, 8):
        b = base_minutes((9, 23), n)
        assert len(b) == n
        assert b == sorted(b)
        assert all(9 * 60 <= x < 23 * 60 for x in b)


def test_tek_slot_ORTAYA_oturur():
    assert base_minutes((10, 22), 1) == [16 * 60]


# --- JITTER: RASTGELE YÜRÜYÜŞ ----------------------------------------------

def test_jitter_deterministik():
    a = next_jitter(0, channel="k", slot_index=0, date_str="2026-07-14",
                    step_max=6, jitter_max=15)
    b = next_jitter(0, channel="k", slot_index=0, date_str="2026-07-14",
                    step_max=6, jitter_max=15)
    assert a == b


def test_jitter_ADIM_sinirini_asmaz():
    """Bir günde 40 dakika kayan bir hesap 'insan' değildir."""
    j = 0
    for d in range(1, 60):
        yeni = next_jitter(j, channel="k", slot_index=0,
                           date_str=f"2026-07-{d:02d}" if d < 32 else f"2026-08-{d-31:02d}",
                           step_max=6, jitter_max=15)
        assert abs(yeni - j) <= 6, f"adım {yeni - j} > 6"
        j = yeni


def test_jitter_TAVANI_asmaz():
    j = 0
    for d in range(1, 29):
        j = next_jitter(j, channel="k", slot_index=0, date_str=f"2026-07-{d:02d}",
                        step_max=6, jitter_max=15)
        assert -15 <= j <= 15


def test_jitter_GERCEKTEN_degisir():
    """Sabit kalan bir jitter = her gün aynı dakika = otomasyon parmak izi."""
    j, gorulen = 0, set()
    for d in range(1, 29):
        j = next_jitter(j, channel="k", slot_index=0, date_str=f"2026-07-{d:02d}",
                        step_max=6, jitter_max=15)
        gorulen.add(j)
    assert len(gorulen) >= 5, f"jitter yeterince gezinmiyor: {sorted(gorulen)}"


def test_farkli_kanal_farkli_yuruyus():
    a = next_jitter(0, channel="a", slot_index=0, date_str="2026-07-14",
                    step_max=6, jitter_max=15)
    b = next_jitter(0, channel="b", slot_index=0, date_str="2026-07-14",
                    step_max=6, jitter_max=15)
    c = next_jitter(0, channel="c", slot_index=0, date_str="2026-07-14",
                    step_max=6, jitter_max=15)
    assert len({a, b, c}) > 1


# --- GÜN PLANI -------------------------------------------------------------

def test_plan_deterministik():
    a = plan_day("k", date(2026, 7, 14), cfg=_Cfg(), prev_jitters={}, tz=TR)
    b = plan_day("k", date(2026, 7, 14), cfg=_Cfg(), prev_jitters={}, tz=TR)
    assert a == b, "uygulama yeniden başlayınca slot KAYMAMALI"


def test_slotlar_AKTIF_SAATLER_icinde():
    class _Wide(_Cfg):
        daily_count = 8
        jitter_minutes = 90       # kasten aşırı
    for d in range(1, 15):
        for s in plan_day("k", date(2026, 7, d), cfg=_Wide(), prev_jitters={}, tz=TR):
            yerel = s.slot_at_utc.astimezone(TR)
            assert 10 <= yerel.hour < 22, f"{yerel} aktif saatler dışında"


def test_slotlar_CAKISMAZ():
    class _Tight(_Cfg):
        daily_count = 8
        jitter_minutes = 60
    s = plan_day("k", date(2026, 7, 14), cfg=_Tight(), prev_jitters={}, tz=TR)
    for a, b in zip(s, s[1:]):
        fark = (b.slot_at_utc - a.slot_at_utc).total_seconds() / 60
        assert fark >= MIN_SLOT_GAP_MIN, f"slotlar {fark:.0f}dk arayla — çakışıyor"


def test_slotlar_SIRALI():
    s = plan_day("k", date(2026, 7, 14), cfg=_Cfg(), prev_jitters={}, tz=TR)
    assert [x.slot_index for x in s] == [0, 1, 2]
    assert s == sorted(s, key=lambda x: x.slot_at_utc)


def test_jitter_ONCEKI_GUNDEN_yuruyor():
    """Kullanıcının tarifi: 13:00 → 13:10 → 13:04 → 13:00. Düz rastgelelik DEĞİL."""
    gun1 = plan_day("k", date(2026, 7, 14), cfg=_Cfg(), prev_jitters={}, tz=TR)
    onceki = {s.slot_index: s.jitter_min for s in gun1}
    gun2 = plan_day("k", date(2026, 7, 15), cfg=_Cfg(), prev_jitters=onceki, tz=TR)
    for a, b in zip(gun1, gun2):
        assert abs(b.jitter_min - a.jitter_min) <= _Cfg.jitter_step


def test_kaydedilen_jitter_HAM_deger():
    """Kırpılmış (aktif saat/çakışma) değer kaydedilirse yürüyüş YANLI olur ve
    jitter zamanla bir uca yapışır."""
    class _Wide(_Cfg):
        daily_count = 8
        jitter_minutes = 90
    for s in plan_day("k", date(2026, 7, 14), cfg=_Wide(), prev_jitters={}, tz=TR):
        assert -90 <= s.jitter_min <= 90


def test_dst_gecisinde_cokmez():
    """TR'de DST yok ama kod başka saat dilimlerinde de koşabilmeli."""
    berlin = ZoneInfo("Europe/Berlin")
    s = plan_day("k", date(2026, 3, 29), cfg=_Cfg(), prev_jitters={}, tz=berlin)
    assert len(s) == 3
    assert all(x.slot_at_utc.tzinfo is timezone.utc for x in s)


# --- ÜRETİM / DURUM KARARLARI ----------------------------------------------

def test_produce_at_lead_kadar_once():
    slot = datetime(2026, 7, 14, 13, 4, tzinfo=timezone.utc)
    assert produce_at(slot, 3) == datetime(2026, 7, 14, 10, 4, tzinfo=timezone.utc)


def test_slot_due_ancak_lead_gelince():
    slot = datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
    assert not slot_is_due(slot, datetime(2026, 7, 14, 9, 59, tzinfo=timezone.utc), 3)
    assert slot_is_due(slot, datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc), 3)
    assert slot_is_due(slot, datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc), 3)


def test_slot_gecmisse_STALE():
    """Uygulama kapalıydı → slot kaçtı. GEÇ YÜKLEME YOK."""
    slot = datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
    assert not is_stale(slot, datetime(2026, 7, 14, 12, 59, tzinfo=timezone.utc))
    assert is_stale(slot, datetime(2026, 7, 14, 13, 1, tzinfo=timezone.utc))


def test_sabitler_makul():
    assert 15 <= MIN_SLOT_GAP_MIN <= 60
    assert 5 <= LIVE_GRACE_MIN <= 30
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_autopilot.py -q`
Expected: `ModuleNotFoundError: No module named 'short_bot.autopilot'`

- [ ] **Step 3: Implement**

```python
# src/short_bot/autopilot.py
"""Autopilot zamanlaması — SAF. DB yok, saat yok, ağ yok, LLM yok.

NEDEN SAF: yanlış bir slot saati HATA VERMEZ. Video yanlış saatte yayınlanır ya da
hiç yayınlanmaz — ve bunu ancak günler sonra fark edersin. Bütün zamanlama mantığını
yan etkisiz bir modülde toplamak, onu yüzlerce senaryoyla saniyeler içinde
sınayabilmenin tek yolu.

İNSAN RİTMİ = RASTGELE YÜRÜYÜŞ, DÜZ RASTGELELİK DEĞİL.
Her gün 10:00-22:00 arasında rastgele bir an seçmek ritmi TAMAMEN yok eder; izleyici
alışkanlık kuramaz. İnsan ise bir taban etrafında SÜRÜKLENİR:
  13:00 → 13:10 → 13:04 → 13:00
Bunu bir taban + sınırlı adımlı, sınırlı genlikli bir rastgele yürüyüşle modelliyoruz.
Yürüyüş DETERMİNİSTİK (sha1) — aynı gün iki kez planlanırsa slot kaymaz.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, time, timedelta, timezone

# İki slot bu kadar yakınsa "insan" değil. Çakışan yayınlar hesabı ele verir.
MIN_SLOT_GAP_MIN = 30
# live_upload modunda uygulama slot anında kapalıysa bu kadar gecikmeye izin ver.
# Fazlası GEÇ YÜKLEME olur — ritmi bozar, hedefi ıskalar.
LIVE_GRACE_MIN = 15


@dataclass(frozen=True, order=True)
class Slot:
    slot_index: int
    slot_at_utc: datetime
    jitter_min: int          # HAM sapma — ertesi günün yürüyüşü buradan devam eder


def base_minutes(active_hours: tuple[int, int], daily_count: int) -> list[int]:
    """Taban saatler (yerel gün içinde dakika). Aktif saatler N eşit bloğa bölünür ve
    slot her bloğun ORTASINA oturur.

    ORTAYA oturtmak keyfi değil: uçlara koyarsak (10:00 ve 22:00) jitter aktif
    saatlerden TAŞAR ve kırpılmak zorunda kalır — kırpma da jitter'ı bir uca yapıştırır.
    Blok ortası, jitter'a her iki yönde yer bırakır.
    """
    lo, hi = active_hours
    n = max(1, int(daily_count))
    blok = (hi - lo) * 60 / n
    return [int(lo * 60 + blok * (i + 0.5)) for i in range(n)]


def _step(channel: str, slot_index: int, date_str: str, step_max: int) -> int:
    """Bugünkü adım — DETERMİNİSTİK. Aynı (kanal, slot, gün) → aynı adım."""
    h = int(hashlib.sha1(
        f"{channel}:{slot_index}:{date_str}".encode("utf-8")).hexdigest(), 16)
    return (h % (2 * step_max + 1)) - step_max


def next_jitter(prev: int, *, channel: str, slot_index: int, date_str: str,
                step_max: int, jitter_max: int) -> int:
    """Rastgele yürüyüş: dünkü sapma ± adım, genlik tavanına sıkıştırılır."""
    j = prev + _step(channel, slot_index, date_str, step_max)
    return max(-jitter_max, min(jitter_max, j))


def plan_day(channel: str, date_local: _date, *, cfg, prev_jitters: dict[int, int],
             tz) -> list[Slot]:
    """O günün slotları.

    ``prev_jitters``: {slot_index: dünkü HAM sapma}. Yoksa 0'dan başlar.

    İKİ KORUMA (aksi hâlde sessizce bozulur):
      1. Slot aktif saatlerin DIŞINA çıkamaz.
      2. İki slot arası en az MIN_SLOT_GAP_MIN kalır.
    Ama KAYDEDİLEN jitter HAM değerdir: kırpılmış değeri kaydedersek yürüyüş
    yanlı hâle gelir ve jitter zamanla bir uca yapışır (ritim yine ölür).
    """
    lo, hi = cfg.active_hours
    bases = base_minutes((lo, hi), cfg.daily_count)
    out: list[Slot] = []
    onceki_dk: int | None = None
    for i, taban in enumerate(bases):
        ham = next_jitter(int(prev_jitters.get(i, 0)), channel=channel, slot_index=i,
                          date_str=date_local.isoformat(),
                          step_max=cfg.jitter_step, jitter_max=cfg.jitter_minutes)
        dk = taban + ham
        dk = max(lo * 60, min(hi * 60 - 1, dk))                 # aktif saatler
        if onceki_dk is not None and dk - onceki_dk < MIN_SLOT_GAP_MIN:
            dk = min(hi * 60 - 1, onceki_dk + MIN_SLOT_GAP_MIN)  # çakışma
        onceki_dk = dk
        yerel = datetime.combine(date_local, time(0, 0), tzinfo=tz) + timedelta(minutes=dk)
        out.append(Slot(slot_index=i,
                        slot_at_utc=yerel.astimezone(timezone.utc),
                        jitter_min=ham))
    return out


def produce_at(slot_at_utc: datetime, lead_hours: int) -> datetime:
    """Üretimin BAŞLAMASI gereken an."""
    return slot_at_utc - timedelta(hours=int(lead_hours))


def slot_is_due(slot_at_utc: datetime, now_utc: datetime, lead_hours: int) -> bool:
    return produce_at(slot_at_utc, lead_hours) <= now_utc


def is_stale(slot_at_utc: datetime, now_utc: datetime) -> bool:
    """Slot anı geçti ve hâlâ üretilmedi → kaçtı. GEÇ YÜKLEME YOK."""
    return now_utc > slot_at_utc
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_autopilot.py -q`
Expected: PASS (18 test)

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/autopilot.py
git commit -m "feat(autopilot): saf zamanlama — taban saatler + rastgele yuruyus jitter"
```

---

### Task 2: Config — `AutopilotConfig`

**Files:**
- Modify: `src/short_bot/config.py`
- Test: `tests/test_autopilot_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_autopilot_config.py
"""Autopilot ayarları. VARSAYILAN KAPALI: açık gelen bir otomasyon, kullanıcının
istemediği videoları yayınlar."""
import pytest
from pydantic import ValidationError

from short_bot.autopilot import MIN_SLOT_GAP_MIN
from short_bot.config import AutopilotConfig, load_channel, save_channel

_YAML = """slug: k
name: Kanal
keywords: [x]
language: tr
schedule_cron: "0 10 * * *"
duration_s: 40
min_score: 7.0
max_candidates_per_run: 3
max_age_hours: 24
template: stat-hero
colors: {primary: '#000', accent: '#fff', bg_gradient: ['#000', '#111']}
handle: '@k'
output_dir: output/k
enabled: true
content_source: generator
generator: {topic: 'ilginc bilgiler'}
"""


def test_varsayilan_KAPALI():
    assert AutopilotConfig().enabled is False


def test_varsayilanlar_makul():
    c = AutopilotConfig()
    assert c.daily_count == 3
    assert c.active_hours == (10, 22)
    assert c.timezone == "Europe/Istanbul"
    assert c.publish_mode == "publish_at"
    assert c.produce_lead_hours >= 1


def test_ters_aktif_saat_REDDEDILIR():
    with pytest.raises(ValidationError):
        AutopilotConfig(active_hours=(22, 10))


def test_slotlar_SIGMIYORSA_reddedilir():
    """12 slot / 2 saat → slotlar 10 dakika arayla. Bu 'insan' değil ve
    MIN_SLOT_GAP_MIN korumasi hepsini üst üste iterdi."""
    with pytest.raises(ValidationError):
        AutopilotConfig(active_hours=(10, 12), daily_count=12)


def test_sigan_yapilandirma_kabul():
    c = AutopilotConfig(active_hours=(10, 22), daily_count=6)
    assert (22 - 10) * 60 / 6 >= MIN_SLOT_GAP_MIN


def test_gecersiz_saat_dilimi_REDDEDILIR():
    with pytest.raises(ValidationError):
        AutopilotConfig(timezone="Mars/Olympus")


def test_yaml_yoksa_autopilot_None(tmp_path):
    p = tmp_path / "k.yaml"; p.write_text(_YAML, encoding="utf-8")
    assert load_channel(p).autopilot is None


def test_yaml_gidis_donus(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text(_YAML + "autopilot:\n  enabled: true\n  daily_count: 2\n"
                         "  publish_mode: live_upload\n", encoding="utf-8")
    cfg = load_channel(p)
    assert cfg.autopilot.enabled is True
    assert cfg.autopilot.daily_count == 2
    assert cfg.autopilot.publish_mode == "live_upload"

    save_channel(p, cfg)
    tekrar = load_channel(p)
    assert tekrar.autopilot == cfg.autopilot, "kaydet→yükle ayarı KAYBETMEMELİ"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_autopilot_config.py -q`
Expected: `ImportError: cannot import name 'AutopilotConfig'`

- [ ] **Step 3: Implement**

`src/short_bot/config.py` — `BgVideoConfig` sınıfının hemen üstüne ekle:

```python
class AutopilotConfig(BaseModel):
    """Otomatik üretim + zamanlı yükleme (bkz. autopilot.py).

    VARSAYILAN KAPALI ve bu kasıtlı: açık gelen bir otomasyon, kullanıcının hiç
    istemediği videoları hiç istemediği saatlerde yayınlar. Kapalıyken hiçbir
    davranış değişmez (mevcut cron + anında yükleme aynen sürer).
    """
    enabled: bool = False
    daily_count: int = Field(default=3, ge=1, le=12)
    active_hours: tuple[int, int] = (10, 22)
    timezone: str = "Europe/Istanbul"
    jitter_minutes: int = Field(default=15, ge=0, le=120)
    jitter_step: int = Field(default=6, ge=1, le=60)
    produce_lead_hours: int = Field(default=1, ge=1, le=12)
    publish_mode: Literal["publish_at", "live_upload"] = "publish_at"
    max_attempts: int = Field(default=3, ge=1, le=5)

    @field_validator("timezone")
    @classmethod
    def _tz_gecerli(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"geçersiz saat dilimi: {v!r}") from e
        return v

    @model_validator(mode="after")
    def _tutarli(self):
        lo, hi = self.active_hours
        if not (0 <= lo < hi <= 24):
            raise ValueError("active_hours [başlangıç, bitiş] ve başlangıç < bitiş olmalı")
        # Slotlar SIĞMALI: sığmazsa MIN_SLOT_GAP_MIN koruması hepsini üst üste iter
        # ve son slotlar aktif saatlerin dışına taşar. Sessiz bozulma — baştan reddet.
        from short_bot.autopilot import MIN_SLOT_GAP_MIN
        if (hi - lo) * 60 / self.daily_count < MIN_SLOT_GAP_MIN:
            raise ValueError(
                f"{self.daily_count} slot {hi - lo} saate sığmaz "
                f"(slot başına en az {MIN_SLOT_GAP_MIN} dk gerekir)")
        return self
```

`produce_lead_hours` varsayılanı **1** — spec 3 diyordu ama kullanıcı `daily_count`
düşükken 3 saatlik lead ilk slotu geçmişe düşürebilir; 1 saat güvenli varsayılan,
panelden artırılır.

`ChannelConfig` dataclass'ına alan ekle (satır ~253, `bg_video`'nun yanına):

```python
    autopilot: "AutopilotConfig | None" = None
```

`load_channel` içinde (satır ~373, `bg_video` bloğunun yanına):

```python
    autopilot_data = data.get("autopilot")
    autopilot = (AutopilotConfig.model_validate(autopilot_data)
                 if autopilot_data else None)
```

ve `ChannelConfig(...)` çağrısına `autopilot=autopilot,` ekle.

`save_channel` içinde (`"bg_video"` yazıldığı yerin yanına):

```python
    if cfg.autopilot is not None:
        out["autopilot"] = cfg.autopilot.model_dump()
```

> `save_channel`'ın gerçek yapısını okuyup aynı desene uy — `youtube`/`reel` blokları
> nasıl yazılıyorsa `autopilot` da öyle yazılmalı.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_autopilot_config.py tests/test_config.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/config.py
git commit -m "feat(autopilot): AutopilotConfig (varsayilan KAPALI) + YAML yukle/kaydet"
```

---

### Task 3: DB — `publish_slots`

**Files:**
- Modify: `src/short_bot/db.py`
- Test: `tests/test_db_slots.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db_slots.py
"""Slot tablosu: sistemin TEK doğruluk kaynağı.

'Bugün ne üretilecek, ne zaman yayınlanacak, hangisi patladı' — hepsinin cevabı
burada. Planlama İDEMPOTENT olmak zorunda: uygulama her açılışta planlayıcıyı
koşturuyor; kopya slot = kopya video.
"""
from datetime import date, datetime, timedelta, timezone

from short_bot.db import (init_db, plan_slots, slot_bump_attempt, slot_set_status,
                          slots_for_date, slots_in_range, prev_day_jitters)

UTC = timezone.utc


def _slot(i, hour):
    return {"slot_index": i,
            "slot_at_utc": datetime(2026, 7, 14, hour, 0, tzinfo=UTC),
            "jitter_min": i * 2}


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def test_plan_ve_oku(tmp_path):
    eng = _eng(tmp_path)
    n = plan_slots(eng, "k", "2026-07-14", [_slot(0, 10), _slot(1, 14)])
    assert n == 2
    s = slots_for_date(eng, "k", "2026-07-14")
    assert [x["slot_index"] for x in s] == [0, 1]
    assert all(x["status"] == "planned" for x in s)
    assert s[0]["attempts"] == 0


def test_planlama_IDEMPOTENT(tmp_path):
    """Uygulama her açılışta planlar. Kopya slot = KOPYA VİDEO."""
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-14", [_slot(0, 10), _slot(1, 14)])
    eklenen = plan_slots(eng, "k", "2026-07-14", [_slot(0, 10), _slot(1, 14)])
    assert eklenen == 0, "aynı gün ikinci kez planlandı → kopya slot"
    assert len(slots_for_date(eng, "k", "2026-07-14")) == 2


def test_planlama_MEVCUT_slotu_EZMEZ(tmp_path):
    """Üretilmiş bir slot yeniden planlanırsa durumu sıfırlanır ve video İKİ KEZ
    üretilir. Planlama var olanı asla ellememelidir."""
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-14", [_slot(0, 10)])
    sid = slots_for_date(eng, "k", "2026-07-14")[0]["id"]
    slot_set_status(eng, sid, "published", short_id=7)

    plan_slots(eng, "k", "2026-07-14", [_slot(0, 10)])
    s = slots_for_date(eng, "k", "2026-07-14")[0]
    assert s["status"] == "published", "planlama üretilmiş slotu sıfırladı"
    assert s["short_id"] == 7


def test_kanallar_karismaz(tmp_path):
    eng = _eng(tmp_path)
    plan_slots(eng, "a", "2026-07-14", [_slot(0, 10)])
    plan_slots(eng, "b", "2026-07-14", [_slot(0, 10)])
    assert len(slots_for_date(eng, "a", "2026-07-14")) == 1
    assert len(slots_for_date(eng, "b", "2026-07-14")) == 1


def test_durum_ve_alanlar_yazilir(tmp_path):
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-14", [_slot(0, 10)])
    sid = slots_for_date(eng, "k", "2026-07-14")[0]["id"]

    slot_set_status(eng, sid, "producing")
    assert slots_for_date(eng, "k", "2026-07-14")[0]["status"] == "producing"

    slot_set_status(eng, sid, "produced", short_id=3, run_id=9)
    s = slots_for_date(eng, "k", "2026-07-14")[0]
    assert s["status"] == "produced" and s["short_id"] == 3 and s["run_id"] == 9
    assert s["produced_at"] is not None

    slot_set_status(eng, sid, "scheduled")
    assert slots_for_date(eng, "k", "2026-07-14")[0]["uploaded_at"] is not None

    slot_set_status(eng, sid, "failed", error="ai33 patladi")
    s = slots_for_date(eng, "k", "2026-07-14")[0]
    assert s["status"] == "failed" and "ai33" in s["error"]


def test_attempt_sayaci(tmp_path):
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-14", [_slot(0, 10)])
    sid = slots_for_date(eng, "k", "2026-07-14")[0]["id"]
    assert slot_bump_attempt(eng, sid) == 1
    assert slot_bump_attempt(eng, sid) == 2
    assert slots_for_date(eng, "k", "2026-07-14")[0]["attempts"] == 2


def test_onceki_gunun_jitterlari(tmp_path):
    """Rastgele yürüyüş dünkü sapmadan devam eder — okunamazsa ritim sıfırlanır."""
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-13", [
        {"slot_index": 0, "slot_at_utc": datetime(2026, 7, 13, 10, tzinfo=UTC),
         "jitter_min": 7},
        {"slot_index": 1, "slot_at_utc": datetime(2026, 7, 13, 14, tzinfo=UTC),
         "jitter_min": -4}])
    assert prev_day_jitters(eng, "k", date(2026, 7, 14)) == {0: 7, 1: -4}


def test_onceki_gun_yoksa_bos(tmp_path):
    assert prev_day_jitters(_eng(tmp_path), "k", date(2026, 7, 14)) == {}


def test_aralik_sorgusu(tmp_path):
    eng = _eng(tmp_path)
    plan_slots(eng, "k", "2026-07-14", [_slot(0, 10)])
    plan_slots(eng, "k", "2026-07-15", [_slot(0, 10)])
    plan_slots(eng, "k", "2026-07-16", [_slot(0, 10)])
    r = slots_in_range(eng, "k", "2026-07-14", "2026-07-15")
    assert {x["slot_local_date"] for x in r} == {"2026-07-14", "2026-07-15"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_db_slots.py -q`
Expected: `ImportError: cannot import name 'plan_slots'`

- [ ] **Step 3: Implement**

`src/short_bot/db.py` — üstteki import satırına `UniqueConstraint` ekle:

```python
from sqlalchemy import (Column, DateTime, Engine, Float, ForeignKey, Integer,
                        MetaData, String, Table, Text, UniqueConstraint, select)
```
> Mevcut import satırını oku ve yalnız `UniqueConstraint`'i ekle.

`series_arcs` tablosunun hemen altına:

```python
# AUTOPILOT SLOTLARI (bkz. autopilot.py). Sistemin TEK doğruluk kaynağı: "bugün ne
# üretilecek, ne zaman yayınlanacak, hangisi patladı" sorularının cevabı burada.
#
# UNIQUE (channel, slot_local_date, slot_index) HAYATİ: planlayıcı hem gece cron'unda
# hem UYGULAMA AÇILIŞINDA koşuyor. Kısıt olmasa aynı gün iki kez planlanır → KOPYA
# SLOT → aynı slot için iki video üretilip ikisi de yüklenir.
publish_slots = Table(
    "publish_slots", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False, index=True),
    Column("slot_local_date", String, nullable=False),   # kanalın YEREL günü
    Column("slot_index", Integer, nullable=False),
    Column("slot_at_utc", DateTime, nullable=False),
    Column("jitter_min", Integer, default=0, nullable=False),   # HAM sapma
    # planned → producing → produced → scheduled → published
    #                    ↘ failed        ↘ skipped
    Column("status", String, default="planned", nullable=False),
    Column("short_id", Integer, ForeignKey("shorts.id")),
    Column("run_id", Integer, ForeignKey("runs.id")),
    Column("attempts", Integer, default=0, nullable=False),
    Column("produced_at", DateTime),
    Column("uploaded_at", DateTime),
    Column("error", Text),
    Column("created_at", DateTime, default=_utcnow, nullable=False),
    UniqueConstraint("channel", "slot_local_date", "slot_index", name="uq_publish_slot"),
)
```

Yardımcılar (`record_episode`'un yakınına):

```python
# --- AUTOPILOT SLOTLARI ----------------------------------------------------

def _slot_dict(row) -> dict:
    return {"id": row.id, "channel": row.channel,
            "slot_local_date": row.slot_local_date, "slot_index": row.slot_index,
            "slot_at_utc": row.slot_at_utc, "jitter_min": row.jitter_min,
            "status": row.status, "short_id": row.short_id, "run_id": row.run_id,
            "attempts": row.attempts, "produced_at": row.produced_at,
            "uploaded_at": row.uploaded_at, "error": row.error}


def plan_slots(eng: Engine, channel: str, slot_local_date: str,
               slots: list[dict]) -> int:
    """Slotları yaz. VAR OLANI ASLA EZMEZ — eklenen slot sayısını döndürür.

    Planlayıcı gece cron'unda VE uygulama açılışında koşuyor. Var olan bir slotu
    ezmek, üretilmiş/yüklenmiş bir slotu 'planned'a döndürür → aynı video ikinci
    kez üretilir ve ikinci kez yüklenir. Sessiz, geri dönüşü olmayan bozulma.
    """
    eklenen = 0
    with eng.begin() as conn:
        mevcut = {r[0] for r in conn.execute(
            select(publish_slots.c.slot_index)
            .where(publish_slots.c.channel == channel)
            .where(publish_slots.c.slot_local_date == slot_local_date)).all()}
        for s in slots:
            i = int(s["slot_index"])
            if i in mevcut:
                continue
            conn.execute(publish_slots.insert().values(
                channel=channel, slot_local_date=slot_local_date, slot_index=i,
                slot_at_utc=s["slot_at_utc"], jitter_min=int(s.get("jitter_min", 0)),
                status="planned", attempts=0))
            eklenen += 1
    return eklenen


def slots_for_date(eng: Engine, channel: str, slot_local_date: str) -> list[dict]:
    with eng.connect() as conn:
        rows = conn.execute(
            select(publish_slots).where(publish_slots.c.channel == channel)
            .where(publish_slots.c.slot_local_date == slot_local_date)
            .order_by(publish_slots.c.slot_index)).all()
    return [_slot_dict(r) for r in rows]


def slots_in_range(eng: Engine, channel: str, d1: str, d2: str) -> list[dict]:
    with eng.connect() as conn:
        rows = conn.execute(
            select(publish_slots).where(publish_slots.c.channel == channel)
            .where(publish_slots.c.slot_local_date >= d1)
            .where(publish_slots.c.slot_local_date <= d2)
            .order_by(publish_slots.c.slot_local_date,
                      publish_slots.c.slot_index)).all()
    return [_slot_dict(r) for r in rows]


def open_slots(eng: Engine, channel: str) -> list[dict]:
    """Henüz sonuçlanmamış slotlar (tick bunlarla ilgilenir)."""
    with eng.connect() as conn:
        rows = conn.execute(
            select(publish_slots).where(publish_slots.c.channel == channel)
            .where(publish_slots.c.status.in_(
                ("planned", "producing", "produced", "scheduled")))
            .order_by(publish_slots.c.slot_at_utc)).all()
    return [_slot_dict(r) for r in rows]


def slot_set_status(eng: Engine, slot_id: int, status: str, *,
                    short_id: int | None = None, run_id: int | None = None,
                    error: str | None = None) -> None:
    vals: dict = {"status": status}
    if short_id is not None:
        vals["short_id"] = int(short_id)
    if run_id is not None:
        vals["run_id"] = int(run_id)
    if error is not None:
        vals["error"] = str(error)[:1000]
    if status == "produced":
        vals["produced_at"] = _utcnow()
    if status in ("scheduled", "published"):
        vals["uploaded_at"] = _utcnow()
    with eng.begin() as conn:
        conn.execute(publish_slots.update()
                     .where(publish_slots.c.id == int(slot_id)).values(**vals))


def slot_bump_attempt(eng: Engine, slot_id: int) -> int:
    """Deneme sayacını artır, YENİ değeri döndür."""
    with eng.begin() as conn:
        row = conn.execute(select(publish_slots.c.attempts)
                           .where(publish_slots.c.id == int(slot_id))).first()
        yeni = int(row[0] or 0) + 1 if row else 1
        conn.execute(publish_slots.update()
                     .where(publish_slots.c.id == int(slot_id))
                     .values(attempts=yeni))
    return yeni


def prev_day_jitters(eng: Engine, channel: str, date_local) -> dict[int, int]:
    """Dünkü HAM sapmalar — rastgele yürüyüş buradan devam eder.

    Okunamazsa yürüyüş her gün 0'dan başlar ve slotlar tabana yapışır: ritim ölür.
    """
    from datetime import timedelta as _td
    dun = (date_local - _td(days=1)).isoformat()
    with eng.connect() as conn:
        rows = conn.execute(
            select(publish_slots.c.slot_index, publish_slots.c.jitter_min)
            .where(publish_slots.c.channel == channel)
            .where(publish_slots.c.slot_local_date == dun)).all()
    return {int(r[0]): int(r[1]) for r in rows}
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_db_slots.py -q`
Expected: PASS (9 test)

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/db.py
git commit -m "feat(autopilot): publish_slots tablosu + idempotent planlama"
```

---

### Task 4: Pipeline — `defer_upload` + `RunResult.short_id`

**ÇAKIŞMA 2:** autopilot üretimlerinde `_maybe_auto_upload` çağrılmamalı. Yoksa video
**iki kez** yüklenir: biri pipeline tarafından anında (public), biri autopilot
tarafından zamanlı. Sessiz, geri dönüşü olmayan.

**Files:**
- Modify: `src/short_bot/pipeline.py`
- Test: `tests/test_pipeline_defer_upload.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pipeline_defer_upload.py
"""ÇİFTE YÜKLEME ENGELİ.

Autopilot videoyu KENDİ yükleyecek (gizli + publishAt). Pipeline aynı videoyu bir de
anında (public) yüklerse kanalda İKİ video olur ve zamanlama tamamen çöker.
Hata vermez — sadece yanlış davranır. O yüzden ölçüyoruz.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from short_bot.pipeline import run_pipeline
from tests.test_pipeline_series import _channel, _result, _settings   # yeniden kullan


def _kos(cfg, tmp_path, db, *, defer):
    cagrildi = []
    logs = tmp_path / "logs"; logs.mkdir(exist_ok=True)

    def _sahte_reel(**kw):
        Path(kw["out_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kw["out_path"]).write_bytes(b"mp4")
        return Path(kw["out_path"])

    with patch("short_bot.pipeline.generate_quote",
               return_value=_result("Bir konu basligi buraya")), \
         patch("short_bot.pipeline._reel_produce_or_none", side_effect=_sahte_reel), \
         patch("short_bot.pipeline._maybe_auto_upload",
               side_effect=lambda **kw: cagrildi.append(kw)):
        r = run_pipeline(channel=cfg, settings=_settings(), db_path=db,
                         music_root=tmp_path, templates_dir=tmp_path,
                         cache_dir=tmp_path / "c", lock_dir=tmp_path / "l",
                         logs_dir=logs, trigger="test", defer_upload=defer)
    return r, cagrildi


def test_defer_upload_ACIKKEN_yukleme_CAGRILMAZ(tmp_path):
    cfg = _channel(tmp_path)
    cfg.reel.series_enabled = False
    r, cagrildi = _kos(cfg, tmp_path, tmp_path / "db.sqlite", defer=True)
    assert r.status == "success"
    assert cagrildi == [], "defer_upload=True iken pipeline yükledi → ÇİFTE YÜKLEME"


def test_defer_upload_KAPALIYKEN_eski_davranis(tmp_path):
    cfg = _channel(tmp_path)
    cfg.reel.series_enabled = False
    r, cagrildi = _kos(cfg, tmp_path, tmp_path / "db.sqlite", defer=False)
    assert r.status == "success"
    assert len(cagrildi) == 1, "geriye uyum kırıldı — normal koşu artık yüklemiyor"


def test_RunResult_short_id_tasir(tmp_path):
    """Autopilot slotu short_id'ye bağlamak zorunda — yoksa hangi videoyu
    yükleyeceğini bilemez."""
    cfg = _channel(tmp_path)
    cfg.reel.series_enabled = False
    r, _ = _kos(cfg, tmp_path, tmp_path / "db.sqlite", defer=True)
    assert r.short_id is not None and r.short_id > 0


def test_basarisiz_kosuda_short_id_None(tmp_path):
    cfg = _channel(tmp_path)
    cfg.reel.series_enabled = False
    logs = tmp_path / "logs"; logs.mkdir()
    with patch("short_bot.pipeline.generate_quote",
               return_value=_result("Bir konu basligi buraya")), \
         patch("short_bot.pipeline._reel_produce_or_none",
               side_effect=RuntimeError("patladi")):
        r = run_pipeline(channel=cfg, settings=_settings(),
                         db_path=tmp_path / "db.sqlite",
                         music_root=tmp_path, templates_dir=tmp_path,
                         cache_dir=tmp_path / "c", lock_dir=tmp_path / "l",
                         logs_dir=logs, trigger="test", defer_upload=True)
    assert r.status == "failed"
    assert r.short_id is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_pipeline_defer_upload.py -q`
Expected: `TypeError: run_pipeline() got an unexpected keyword argument 'defer_upload'`

- [ ] **Step 3: Implement**

`RunResult`'a alan ekle:

```python
@dataclass
class RunResult:
    run_id: int
    status: str           # 'success' | 'failed' | 'no_candidates' | 'cancelled'
    short_path: Path | None
    error: str | None
    # AUTOPILOT: slot hangi videoya bağlanacak? Yükleme üretimden AYRI koştuğu için
    # yolu değil KİMLİĞİ taşımak zorundayız (upload short_id ile çalışıyor).
    short_id: int | None = None
```

`_maybe_auto_upload`'a erken çıkış ekle (fonksiyonun ilk satırı):

```python
def _maybe_auto_upload(*, eng, short_id: int, channel, picked_score: float | None,
                       log, yt_creds_root: Path, claude_path: str,
                       model: str, cooldown_minutes: int = 5,
                       secrets_path: Path | None = None,
                       backend: str = "claude_cli",
                       api_key: str | None = None,
                       defer: bool = False) -> None:
    """Post-render hook: if channel opts in, evaluate gates + run upload.

    ``defer=True`` (autopilot): YÜKLEME BURADA YAPILMAZ. Autopilot videoyu kendi
    yükleyecek — gizli + publishAt ile, planlanmış slot saatine. Burada da yüklersek
    kanalda İKİ video olur (biri anında public, biri zamanlı) ve zamanlama çöker.
    """
    if defer:
        log.info("[YT] auto-upload ERTELENDİ — autopilot slot saatine yükleyecek")
        return
    if channel.youtube is None or not channel.youtube.auto_upload:
        return
    ...
```

`run_pipeline` imzasına ekle:

```python
def run_pipeline(
    *,
    channel: ChannelConfig,
    settings: Settings,
    db_path: Path,
    music_root: Path,
    templates_dir: Path,
    cache_dir: Path,
    logs_dir: Path,
    lock_dir: Path | None = None,
    trigger: str = "cli",
    preselected_item=None,
    forced_topic: str | None = None,
    defer_upload: bool = False,   # AUTOPILOT: yüklemeyi autopilot yapacak
) -> RunResult:
```

ve iç fonksiyonlara ilet. `_run_generator`, `_run_feed`, `_run_rss` (hepsinin
imzasına `defer_upload: bool = False` ekle) ve **dört** `_maybe_auto_upload(...)`
çağrısının hepsine `defer=defer_upload,` ekle.

Her başarılı `RunResult(...)` dönüşüne `short_id=short_id,` ekle. Dört yer:
- reel başarı (satır ~1423)
- klasik generator başarı
- feed başarı
- rss başarı

> `grep -n "return RunResult" src/short_bot/pipeline.py` ile hepsini bul; `status="success"`
> olanlara `short_id=short_id` ekle, ötekiler `None` kalsın (varsayılan).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pipeline_defer_upload.py tests/test_pipeline_series.py tests/test_pipeline_generator.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/pipeline.py
git commit -m "feat(autopilot): pipeline defer_upload + RunResult.short_id (cifte yukleme engeli)"
```

---

### Task 5: Scheduler — autopilot açık kanalın cron'u kaydedilmez

**ÇAKIŞMA 1:** Otomasyon açıkken kanalın `schedule_cron`'u da koşarsa günde 3 yerine
6 video üretilir. Hata vermez.

**Files:**
- Modify: `src/short_bot/web/scheduler.py`
- Test: `tests/test_scheduler_autopilot.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scheduler_autopilot.py
"""ÇİFTE ÜRETİM ENGELİ.

Autopilot kendi slot'larından üretiyor. Kanalın schedule_cron'u da koşarsa günde
3 yerine 6 video çıkar — ve bu hiçbir hata vermez.
"""
from short_bot.web.scheduler import channel_cron_enabled


class _AP:
    def __init__(self, enabled):
        self.enabled = enabled


class _Ch:
    def __init__(self, cron="0 10 * * *", autopilot=None, enabled=True):
        self.slug = "k"
        self.schedule_cron = cron
        self.autopilot = autopilot
        self.enabled = enabled


def test_autopilot_KAPALIYKEN_cron_kaydedilir():
    assert channel_cron_enabled(_Ch()) is True
    assert channel_cron_enabled(_Ch(autopilot=_AP(False))) is True


def test_autopilot_ACIKKEN_cron_KAYDEDILMEZ():
    assert channel_cron_enabled(_Ch(autopilot=_AP(True))) is False


def test_cron_bos_ise_kaydedilmez():
    assert channel_cron_enabled(_Ch(cron="")) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_scheduler_autopilot.py -q`
Expected: `ImportError: cannot import name 'channel_cron_enabled'`

- [ ] **Step 3: Implement**

`src/short_bot/web/scheduler.py` — `init_scheduler`'ın ÜSTÜNE (modül düzeyinde):

```python
def channel_cron_enabled(cfg) -> bool:
    """Kanalın schedule_cron'u kaydedilmeli mi?

    AUTOPILOT AÇIKSA HAYIR. Autopilot kendi slot'larından üretiyor; cron da koşarsa
    günde 3 yerine 6 video çıkar. Bu çifte üretim HİÇBİR HATA VERMEZ — yalnız kotayı
    ve kredileri yakar, üstelik slot'suz videolar anında (public) yüklenir ve
    zamanlamayı bozar.
    """
    if not getattr(cfg, "schedule_cron", ""):
        return False
    ap = getattr(cfg, "autopilot", None)
    return not (ap is not None and ap.enabled)
```

`_reload_jobs` içindeki döngüyü değiştir:

```python
        for cfg in list_channels(cfg_dir / "channels", enabled_only=True):
            if not channel_cron_enabled(cfg):
                continue
            try:
                trigger = CronTrigger.from_crontab(cfg.schedule_cron)
            except ValueError:
                continue  # invalid cron, skip
            scheduler.add_job(...)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_scheduler_autopilot.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/web/scheduler.py
git commit -m "feat(autopilot): autopilot acikken kanal cron'u kaydedilmez (cifte uretim engeli)"
```

---

### Task 6: Yükleyici — `publish_at` desteği

**Files:**
- Modify: `src/short_bot/youtube/auto_upload.py`
- Test: `tests/test_youtube_publish_at.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_youtube_publish_at.py
"""Zamanlı yükleme: gizli + publishAt.

YouTube'un kuralı: publishAt YALNIZ privacyStatus=private iken geçerlidir. Public bir
videoya publishAt vermek sessizce yok sayılır → video ANINDA yayınlanır ve bütün
zamanlama çöker.
"""
from datetime import datetime, timezone

from short_bot.youtube.uploader import build_status


def test_publish_at_verilince_GIZLI_olur():
    s = build_status(privacy_status="public", ai_content=True,
                     publish_at="2026-07-14T13:04:00Z")
    assert s["privacyStatus"] == "private", "publishAt public iken YOK SAYILIR"
    assert s["publishAt"] == "2026-07-14T13:04:00Z"


def test_publish_at_yoksa_eski_davranis():
    s = build_status(privacy_status="public", ai_content=True)
    assert s["privacyStatus"] == "public"
    assert "publishAt" not in s


def test_run_auto_upload_publish_at_i_GECIRIR(monkeypatch, tmp_path):
    """Katman geçirmezse publishAt hiç uygulanmaz ve video anında yayınlanır."""
    import short_bot.youtube.auto_upload as A

    gorulen = {}

    class _Row:
        id = 1
        file_path = str(tmp_path / "v.mp4")
        script_json = "{}"
        channel = "k"

    monkeypatch.setattr(A, "_load_short_for_upload",
                        lambda eng, short_id: (_Row(), None, None))
    monkeypatch.setattr(A, "generate_youtube_metadata",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("skip")))
    monkeypatch.setattr(A, "upload_video",
                        lambda **kw: gorulen.update(status=kw["status"]) or "VID")
    monkeypatch.setattr(A, "record_youtube_upload", lambda *a, **kw: None)
    monkeypatch.setattr(A, "load_channel_proxy_url", lambda *a, **kw: None)

    class _YT:
        privacy_status = "public"; ai_content = True; category_id = "24"

    class _Ch:
        slug = "k"; handle = "@k"; keywords = []; language = "tr"; youtube = _YT()

    (tmp_path / "v.mp4").write_bytes(b"x")
    A.run_auto_upload(eng=None, short_id=1, channel=_Ch(), credentials=None,
                      publish_at="2026-07-14T13:04:00Z")
    assert gorulen["status"]["privacyStatus"] == "private"
    assert gorulen["status"]["publishAt"] == "2026-07-14T13:04:00Z"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_youtube_publish_at.py -q`
Expected: `TypeError: run_auto_upload() got an unexpected keyword argument 'publish_at'`
(`build_status` testleri zaten geçecek — o katman hazır.)

- [ ] **Step 3: Implement**

`src/short_bot/youtube/auto_upload.py` — `run_auto_upload` imzasına ekle:

```python
def run_auto_upload(*, eng, short_id: int, channel, credentials,
                    claude_path: str = "claude",
                    model: str = "sonnet",
                    secrets_path: Path | None = None,
                    backend: str = "claude_cli",
                    api_key: str | None = None,
                    publish_at: str | None = None) -> AutoUploadResult:
    """...

    ``publish_at`` (RFC3339, ör. "2026-07-14T13:04:00Z"): verilirse video GİZLİ
    yüklenir ve YouTube tam o anda yayınlar (bkz. uploader.build_status — publishAt
    yalnız private iken geçerlidir; public bir videoda SESSİZCE yok sayılır ve video
    anında yayınlanır).
    """
```

ve `build_status` çağrısını değiştir:

```python
    status = build_status(privacy_status=yt.privacy_status, ai_content=yt.ai_content,
                          publish_at=publish_at)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_youtube_publish_at.py tests/test_youtube_uploader.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/youtube/auto_upload.py
git commit -m "feat(autopilot): run_auto_upload publish_at (gizli + zamanli yayin)"
```

---

### Task 7: Durum makinesi — `autopilot_runner.py`

**Files:**
- Create: `src/short_bot/autopilot_runner.py`
- Test: `tests/test_autopilot_runner.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_autopilot_runner.py
"""Autopilot durum makinesi — bütün sessiz bozulma senaryoları burada.

Yan etkiler AutopilotDeps ile enjekte edilir: APScheduler yok, ağ yok, LLM yok.
Testler saniyeler içinde koşar ve her geçişi ölçer.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from short_bot.autopilot import LIVE_GRACE_MIN
from short_bot.autopilot_runner import AutopilotDeps, plan_channel, tick
from short_bot.db import init_db, plan_slots, slots_for_date

UTC = timezone.utc


class _AP:
    enabled = True
    daily_count = 2
    active_hours = (10, 22)
    timezone = "Europe/Istanbul"
    jitter_minutes = 15
    jitter_step = 6
    produce_lead_hours = 3
    publish_mode = "publish_at"
    max_attempts = 3


class _Ch:
    slug = "k"
    enabled = True
    autopilot = _AP()


class _Res:
    def __init__(self, status="success", short_id=1, run_id=1, error=None):
        self.status = status; self.short_id = short_id
        self.run_id = run_id; self.error = error


def _deps(now, *, produce=None, sched=None, live=None, arc=None):
    cagri = {"produce": [], "sched": [], "live": [], "arc": []}

    def _p(cfg):
        cagri["produce"].append(cfg.slug)
        return (produce or _Res)()

    def _s(short_id, cfg, publish_at):
        cagri["sched"].append((short_id, publish_at))
        return (sched or (lambda: "https://youtu.be/X"))()

    def _l(short_id, cfg):
        cagri["live"].append(short_id)
        return (live or (lambda: "https://youtu.be/Y"))()

    def _a(cfg):
        cagri["arc"].append(cfg.slug)
        return (arc or (lambda: None))()

    return AutopilotDeps(produce=_p, upload_scheduled=_s, upload_live=_l,
                         ensure_arc=_a, now=lambda: now), cagri


def _slot(eng, hour, minute=0, index=0, d="2026-07-14"):
    plan_slots(eng, "k", d, [{"slot_index": index,
                              "slot_at_utc": datetime(2026, 7, 14, hour, minute,
                                                      tzinfo=UTC),
                              "jitter_min": 0}])
    return slots_for_date(eng, "k", d)[index]


# --- PLANLAMA --------------------------------------------------------------

def test_plan_bugun_ve_yarini_yazar(tmp_path):
    eng = init_db(tmp_path / "db.sqlite")
    n = plan_channel(eng, _Ch(), today_local=date(2026, 7, 14), days=2)
    assert n == 4          # 2 slot × 2 gün
    assert len(slots_for_date(eng, "k", "2026-07-14")) == 2
    assert len(slots_for_date(eng, "k", "2026-07-15")) == 2


def test_plan_IDEMPOTENT(tmp_path):
    eng = init_db(tmp_path / "db.sqlite")
    plan_channel(eng, _Ch(), today_local=date(2026, 7, 14), days=2)
    assert plan_channel(eng, _Ch(), today_local=date(2026, 7, 14), days=2) == 0


def test_autopilot_kapali_kanal_planlanmaz(tmp_path):
    class _Off(_Ch):
        class autopilot(_AP):
            enabled = False
    eng = init_db(tmp_path / "db.sqlite")
    assert plan_channel(eng, _Off(), today_local=date(2026, 7, 14), days=2) == 0


# --- ÜRETİM ----------------------------------------------------------------

def test_lead_gelmeden_URETILMEZ(tmp_path):
    eng = init_db(tmp_path / "db.sqlite")
    _slot(eng, 13)                                    # slot 13:00, lead 3sa → 10:00
    d, c = _deps(datetime(2026, 7, 14, 9, 30, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert c["produce"] == []
    assert slots_for_date(eng, "k", "2026-07-14")[0]["status"] == "planned"


def test_lead_gelince_URETILIR(tmp_path):
    eng = init_db(tmp_path / "db.sqlite")
    _slot(eng, 13)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert c["produce"] == ["k"]
    s = slots_for_date(eng, "k", "2026-07-14")[0]
    assert s["status"] == "scheduled"     # publish_at modu → hemen zamanlı yüklenir
    assert s["short_id"] == 1


def test_uretim_patlarsa_ATTEMPT_artar_ve_TEKRAR_denenir(tmp_path):
    eng = init_db(tmp_path / "db.sqlite")
    _slot(eng, 13)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC),
                 produce=lambda: _Res(status="failed", short_id=None,
                                      error="ai33 patladi"))
    tick(eng, _Ch(), d)
    s = slots_for_date(eng, "k", "2026-07-14")[0]
    assert s["attempts"] == 1
    assert s["status"] == "planned", "tekrar denenebilmeli"

    tick(eng, _Ch(), d)
    assert slots_for_date(eng, "k", "2026-07-14")[0]["attempts"] == 2


def test_MAX_ATTEMPT_sonra_FAILED(tmp_path):
    eng = init_db(tmp_path / "db.sqlite")
    _slot(eng, 13)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC),
                 produce=lambda: _Res(status="failed", short_id=None, error="x"))
    for _ in range(3):
        tick(eng, _Ch(), d)
    s = slots_for_date(eng, "k", "2026-07-14")[0]
    assert s["status"] == "failed"
    assert s["attempts"] == 3

    tick(eng, _Ch(), d)
    assert len(c["produce"]) == 3, "failed slot yeniden üretilmeye çalışıldı"


def test_slot_gecmisse_SKIPPED_ve_URETILMEZ(tmp_path):
    """Uygulama kapalıydı. GEÇ YÜKLEME YOK — 22:00'de yayınlanan gündüz videosu
    hedefi zaten ıskalar."""
    eng = init_db(tmp_path / "db.sqlite")
    _slot(eng, 13)
    d, c = _deps(datetime(2026, 7, 14, 13, 30, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert c["produce"] == []
    assert slots_for_date(eng, "k", "2026-07-14")[0]["status"] == "skipped"


# --- YÜKLEME: publish_at MODU ----------------------------------------------

def test_publish_at_modunda_HEMEN_gizli_yuklenir(tmp_path):
    eng = init_db(tmp_path / "db.sqlite")
    _slot(eng, 13)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert len(c["sched"]) == 1
    short_id, publish_at = c["sched"][0]
    assert short_id == 1
    assert publish_at.startswith("2026-07-14T13:00")
    assert publish_at.endswith("Z"), "RFC3339 UTC olmalı"


def test_publish_at_GECMISE_zamanlanamaz(tmp_path):
    """Üretim bitti ama slot anı geçti → publishAt geçersiz. FAILED."""
    eng = init_db(tmp_path / "db.sqlite")
    s = _slot(eng, 13)
    from short_bot.db import slot_set_status
    slot_set_status(eng, s["id"], "produced", short_id=1, run_id=1)
    d, c = _deps(datetime(2026, 7, 14, 13, 30, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert c["sched"] == []
    assert slots_for_date(eng, "k", "2026-07-14")[0]["status"] == "failed"


def test_yukleme_patlarsa_PRODUCED_ta_kalir_ve_tekrar_denenir(tmp_path):
    eng = init_db(tmp_path / "db.sqlite")
    _slot(eng, 13)

    def _patla():
        raise RuntimeError("yt 503")

    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC), sched=_patla)
    tick(eng, _Ch(), d)
    assert slots_for_date(eng, "k", "2026-07-14")[0]["status"] == "produced"

    d2, c2 = _deps(datetime(2026, 7, 14, 10, 10, tzinfo=UTC))
    tick(eng, _Ch(), d2)
    assert slots_for_date(eng, "k", "2026-07-14")[0]["status"] == "scheduled"


def test_slot_gecince_SCHEDULED_yayinlandi_sayilir(tmp_path):
    eng = init_db(tmp_path / "db.sqlite")
    s = _slot(eng, 13)
    from short_bot.db import slot_set_status
    slot_set_status(eng, s["id"], "scheduled", short_id=1)
    d, c = _deps(datetime(2026, 7, 14, 13, 5, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert slots_for_date(eng, "k", "2026-07-14")[0]["status"] == "published"


# --- YÜKLEME: live_upload MODU ---------------------------------------------

class _Live(_Ch):
    class autopilot(_AP):
        publish_mode = "live_upload"


def test_live_modda_slot_ANINDAN_ONCE_yuklenmez(tmp_path):
    eng = init_db(tmp_path / "db.sqlite")
    _slot(eng, 13)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC))
    tick(eng, _Live(), d)
    assert c["produce"] == ["k"]
    assert c["live"] == [], "slot saatinden ÖNCE yükledi"
    assert slots_for_date(eng, "k", "2026-07-14")[0]["status"] == "produced"


def test_live_modda_slot_ANINDA_yuklenir(tmp_path):
    eng = init_db(tmp_path / "db.sqlite")
    s = _slot(eng, 13)
    from short_bot.db import slot_set_status
    slot_set_status(eng, s["id"], "produced", short_id=1, run_id=1)
    d, c = _deps(datetime(2026, 7, 14, 13, 1, tzinfo=UTC))
    tick(eng, _Live(), d)
    assert c["live"] == [1]
    assert slots_for_date(eng, "k", "2026-07-14")[0]["status"] == "published"


def test_live_modda_GRACE_disinda_FAILED(tmp_path):
    """Uygulama slot anında kapalıydı ve çok geç açıldı. GEÇ YÜKLEME YOK."""
    eng = init_db(tmp_path / "db.sqlite")
    s = _slot(eng, 13)
    from short_bot.db import slot_set_status
    slot_set_status(eng, s["id"], "produced", short_id=1, run_id=1)
    gec = datetime(2026, 7, 14, 13, LIVE_GRACE_MIN + 5, tzinfo=UTC)
    d, c = _deps(gec)
    tick(eng, _Live(), d)
    assert c["live"] == []
    assert slots_for_date(eng, "k", "2026-07-14")[0]["status"] == "failed"


# --- ARK YENİLEME ----------------------------------------------------------

def test_uretimden_ONCE_ark_saglanir(tmp_path):
    """Ark bitmişse yeni ark planlanıp oto-onaylanmalı — ÜRETİMDEN ÖNCE, yoksa o
    bölüm bankadan tek konu olarak çıkar ve seri delinir."""
    eng = init_db(tmp_path / "db.sqlite")
    _slot(eng, 13)
    d, c = _deps(datetime(2026, 7, 14, 10, 1, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert c["arc"] == ["k"]


def test_uretilecek_slot_yoksa_ark_da_cagrilmaz(tmp_path):
    """Boşuna LLM çağrısı yakmayalım."""
    eng = init_db(tmp_path / "db.sqlite")
    _slot(eng, 13)
    d, c = _deps(datetime(2026, 7, 14, 9, 0, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert c["arc"] == []


# --- AYNI ANDA TEK ÜRETİM --------------------------------------------------

def test_tick_bir_seferde_TEK_slot_uretir(tmp_path):
    """İki slot aynı anda due olsa bile tek tick tek üretim başlatır: pipeline
    kanal başına kilitli ve üretim ~15 dk sürüyor. İkincisi sonraki tick'te."""
    eng = init_db(tmp_path / "db.sqlite")
    plan_slots(eng, "k", "2026-07-14", [
        {"slot_index": 0, "slot_at_utc": datetime(2026, 7, 14, 13, tzinfo=UTC),
         "jitter_min": 0},
        {"slot_index": 1, "slot_at_utc": datetime(2026, 7, 14, 14, tzinfo=UTC),
         "jitter_min": 0}])
    d, c = _deps(datetime(2026, 7, 14, 11, 30, tzinfo=UTC))
    tick(eng, _Ch(), d)
    assert len(c["produce"]) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_autopilot_runner.py -q`
Expected: `ModuleNotFoundError: No module named 'short_bot.autopilot_runner'`

- [ ] **Step 3: Implement**

```python
# src/short_bot/autopilot_runner.py
"""Autopilot durum makinesi.

YAN ETKİLER ENJEKTE EDİLİR (AutopilotDeps): üretim, yükleme, ark planlama ve SAAT
dışarıdan gelir. Böylece bütün durum geçişleri APScheduler'sız, ağsız, LLM'siz test
edilir — ve zamanlama hatası üretime sızmadan yakalanır.

SESSİZ BOZULMA ALANLARI (hepsinin testi var):
  • Slot anı geçmişken publishAt vermek → YouTube reddetmez, ANINDA yayınlar
  • Yükleme patlayınca slot'u 'scheduled' işaretlemek → video hiç yüklenmemiş olur
  • max_attempts'i saymamak → sonsuza kadar üretim denemesi, kredi yakar
  • Aynı tick'te iki üretim başlatmak → pipeline kilidi ikinciyi 'failed' sayar
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from short_bot.autopilot import (LIVE_GRACE_MIN, is_stale, plan_day, slot_is_due)
from short_bot.db import (open_slots, plan_slots, prev_day_jitters,
                          slot_bump_attempt, slot_set_status)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutopilotDeps:
    produce: Callable          # (cfg) -> RunResult
    upload_scheduled: Callable  # (short_id, cfg, publish_at: str) -> url
    upload_live: Callable       # (short_id, cfg) -> url
    ensure_arc: Callable        # (cfg) -> None   — ark bitmişse yenisini planla+onayla
    now: Callable               # () -> datetime (UTC)


def _tz(cfg) -> ZoneInfo:
    return ZoneInfo(cfg.autopilot.timezone)


def _rfc3339(dt: datetime) -> str:
    """YouTube publishAt biçimi. Z sonekiyle UTC."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan_channel(eng, cfg, *, today_local: _date, days: int = 2) -> int:
    """Bugünden itibaren ``days`` günün slotlarını yaz. İDEMPOTENT.

    Uygulama açılışında da koşar: gece cron'u kaçtıysa (uygulama kapalıydı) gün
    tamamen boş geçerdi.
    """
    ap = getattr(cfg, "autopilot", None)
    if ap is None or not ap.enabled or not getattr(cfg, "enabled", True):
        return 0
    tz = _tz(cfg)
    toplam = 0
    for k in range(max(1, days)):
        gun = today_local + timedelta(days=k)
        slots = plan_day(cfg.slug, gun, cfg=ap,
                         prev_jitters=prev_day_jitters(eng, cfg.slug, gun), tz=tz)
        toplam += plan_slots(eng, cfg.slug, gun.isoformat(), [
            {"slot_index": s.slot_index, "slot_at_utc": s.slot_at_utc,
             "jitter_min": s.jitter_min} for s in slots])
    return toplam


def _as_utc(dt: datetime) -> datetime:
    """SQLite naive datetime döndürüyor — UTC varsay (yazarken UTC yazıyoruz)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def tick(eng, cfg, deps: AutopilotDeps) -> dict:
    """Bir tur: kaçanları işaretle → üret → yükle. Sayaç döndürür."""
    ap = getattr(cfg, "autopilot", None)
    if ap is None or not ap.enabled:
        return {}
    now = deps.now()
    sayac = {"skipped": 0, "produced": 0, "failed": 0,
             "scheduled": 0, "published": 0}

    slots = open_slots(eng, cfg.slug)

    # 1) KAÇANLAR: slot anı geçmiş ama hâlâ üretilmemiş → GEÇ YÜKLEME YOK.
    for s in slots:
        if s["status"] in ("planned", "producing") and \
                is_stale(_as_utc(s["slot_at_utc"]), now):
            slot_set_status(eng, s["id"], "skipped",
                            error="slot anı geçti (uygulama kapalıydı)")
            sayac["skipped"] += 1
            log.info(f"[autopilot] {cfg.slug} slot {s['slot_index']} KAÇTI")

    # 2) YÜKLEME (üretimden ÖNCE: üretim 15 dk sürüyor, bekleyen yükleme gecikmesin)
    for s in open_slots(eng, cfg.slug):
        if s["status"] != "produced" or not s["short_id"]:
            continue
        slot_at = _as_utc(s["slot_at_utc"])
        if ap.publish_mode == "publish_at":
            if now >= slot_at:
                # publishAt GEÇMİŞE zamanlanamaz — YouTube bunu reddetmez, videoyu
                # ANINDA yayınlar. Ritim çöker; slotu düşür.
                slot_set_status(eng, s["id"], "failed",
                                error="slot anı geçti, publishAt geçersiz")
                sayac["failed"] += 1
                continue
            try:
                url = deps.upload_scheduled(s["short_id"], cfg, _rfc3339(slot_at))
                slot_set_status(eng, s["id"], "scheduled")
                sayac["scheduled"] += 1
                log.info(f"[autopilot] {cfg.slug} slot {s['slot_index']} "
                         f"zamanlandı → {_rfc3339(slot_at)} ({url})")
            except Exception as e:   # noqa: BLE001 — 'produced'ta kalır, tekrar denenir
                log.warning(f"[autopilot] {cfg.slug} zamanlı yükleme hatası: {e}")
        else:   # live_upload
            if now < slot_at:
                continue
            if now > slot_at + timedelta(minutes=LIVE_GRACE_MIN):
                slot_set_status(eng, s["id"], "failed",
                                error=f"slot anı {LIVE_GRACE_MIN}dk'dan fazla geçti")
                sayac["failed"] += 1
                continue
            try:
                url = deps.upload_live(s["short_id"], cfg)
                slot_set_status(eng, s["id"], "published")
                sayac["published"] += 1
                log.info(f"[autopilot] {cfg.slug} slot {s['slot_index']} "
                         f"canlı yüklendi ({url})")
            except Exception as e:   # noqa: BLE001
                log.warning(f"[autopilot] {cfg.slug} canlı yükleme hatası: {e}")

    # 3) ZAMANLANMIŞ + slot anı geçti → YouTube yayınladı
    for s in open_slots(eng, cfg.slug):
        if s["status"] == "scheduled" and now >= _as_utc(s["slot_at_utc"]):
            slot_set_status(eng, s["id"], "published")
            sayac["published"] += 1

    # 4) ÜRETİM — TEK slot. Pipeline kanal başına KİLİTLİ ve üretim ~15 dk sürüyor;
    #    ikinci üretimi aynı tick'te başlatmak onu 'lock busy' → failed yapardı.
    due = [s for s in open_slots(eng, cfg.slug)
           if s["status"] == "planned"
           and slot_is_due(_as_utc(s["slot_at_utc"]), now, ap.produce_lead_hours)]
    if not due:
        return sayac
    s = due[0]

    # ARK: üretimden ÖNCE. Ark bitmişse yeni ark planlanıp oto-onaylanmalı, yoksa
    # bu bölüm bankadan TEK KONU olarak çıkar ve seri delinir.
    try:
        deps.ensure_arc(cfg)
    except Exception as e:   # noqa: BLE001 — ark KOZMETİK değil ama üretimi durdurmasın
        log.warning(f"[autopilot] {cfg.slug} ark sağlanamadı ({e})")

    slot_set_status(eng, s["id"], "producing")
    n = slot_bump_attempt(eng, s["id"])
    log.info(f"[autopilot] {cfg.slug} slot {s['slot_index']} üretiliyor "
             f"(deneme {n}/{ap.max_attempts})")
    try:
        res = deps.produce(cfg)
    except Exception as e:   # noqa: BLE001
        res = None
        hata = str(e)
    else:
        hata = res.error or "üretim başarısız"

    if res is not None and res.status == "success" and res.short_id:
        slot_set_status(eng, s["id"], "produced",
                        short_id=res.short_id, run_id=getattr(res, "run_id", None))
        sayac["produced"] += 1
        # Aynı tick'te yükle: publish_at modunda beklemenin anlamı yok.
        return {**sayac, **tick(eng, cfg, deps)} if ap.publish_mode == "publish_at" \
            else sayac

    if n >= ap.max_attempts:
        slot_set_status(eng, s["id"], "failed", error=hata)
        sayac["failed"] += 1
        log.warning(f"[autopilot] {cfg.slug} slot {s['slot_index']} "
                    f"{n} denemede üretilemedi → slot boş geçecek")
    else:
        slot_set_status(eng, s["id"], "planned", error=hata)
    return sayac
```

> **Dikkat — özyineleme:** başarılı üretimden sonra `publish_at` modunda `tick`
> kendini bir kez daha çağırır (yeni `produced` slotu hemen yüklesin diye). O turda
> `planned` + due slot kalmadığı için ikinci özyineleme olmaz. Testte
> `test_lead_gelince_URETILIR` bunu doğruluyor (`status == "scheduled"`).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_autopilot_runner.py -q`
Expected: PASS (17 test)

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/autopilot_runner.py
git commit -m "feat(autopilot): durum makinesi (uretim -> zamanli/canli yukleme, kacan slot, max attempt)"
```

---

### Task 8: Ark oto-planla + oto-onayla

**Files:**
- Create: `src/short_bot/autopilot_arc.py`
- Test: `tests/test_autopilot_arc.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_autopilot_arc.py
"""Ark oto-yenileme.

Günde 3 video üreten bir kanalda 3 bölümlük ark BİR GÜNDE biter. Ertesi gün onaylı
ark kalmazsa sistem bankadan tek konu üretmeye düşer ve SERİ DURUR.

Kullanıcının kararı: otomatik planla + otomatik ONAYLA. Ama kullanıcının kendi
bekleyen taslağı varsa DOKUNMA — onun incelemesini ezmek güveni yıkar.
"""
from short_bot.autopilot_arc import ensure_arc
from short_bot.db import (active_arc, approve_arc, create_arc, draft_arc, init_db,
                          insert_bank_topics)


class _Reel:
    enabled = True
    series_enabled = True
    arc_mode = "planned"
    series_arc_length = 3


class _Ch:
    slug = "k"
    name = "Kanal"
    reel = _Reel()
    generator = None


_PLAN = [{"topic": "Bir konu", "promise": ""},
         {"topic": "Iki konu", "promise": "vaat"}]


def _fake_plan(monkeypatch, plan=None):
    import short_bot.autopilot_arc as A

    class _E:
        def __init__(self, t, p): self.topic = t; self.promise = p

    class _P:
        title = "Yeni Ark"
        episodes = [_E(e["topic"], e["promise"]) for e in (plan or _PLAN)]

    monkeypatch.setattr(A, "plan_arc", lambda *a, **kw: _P())
    return A


def test_aktif_ark_varsa_DOKUNMAZ(tmp_path, monkeypatch):
    _fake_plan(monkeypatch)
    eng = init_db(tmp_path / "db.sqlite")
    aid = create_arc(eng, "k", title="Mevcut", seed_topic="t", plan=_PLAN)
    approve_arc(eng, aid)
    ensure_arc(eng, _Ch(), llm_call=object())
    assert active_arc(eng, "k")["id"] == aid


def test_KULLANICININ_taslagi_varsa_OTO_ONAYLAMAZ(tmp_path, monkeypatch):
    """Kullanıcının incelemesini ezmek güveni yıkar."""
    _fake_plan(monkeypatch)
    eng = init_db(tmp_path / "db.sqlite")
    aid = create_arc(eng, "k", title="Kullanicinin taslagi", seed_topic="t", plan=_PLAN)
    ensure_arc(eng, _Ch(), llm_call=object())
    assert active_arc(eng, "k") is None, "kullanıcının taslağı oto-onaylandı"
    assert draft_arc(eng, "k")["id"] == aid


def test_ark_yoksa_PLANLAR_ve_ONAYLAR(tmp_path, monkeypatch):
    _fake_plan(monkeypatch)
    eng = init_db(tmp_path / "db.sqlite")
    insert_bank_topics(eng, "k", [{"topic": "Bankadaki konu", "views": 1, "subs": 1}])
    ensure_arc(eng, _Ch(), llm_call=object())
    a = active_arc(eng, "k")
    assert a is not None, "ark planlanmadı"
    assert a["title"] == "Yeni Ark"
    assert a["status"] == "active", "ark oto-onaylanmadı → seri durur"


def test_banka_bossa_COKMEZ(tmp_path, monkeypatch):
    """Tohum yoksa ark kurulamaz — ama üretim yine koşmalı (LLM konu üretir)."""
    _fake_plan(monkeypatch)
    eng = init_db(tmp_path / "db.sqlite")
    ensure_arc(eng, _Ch(), llm_call=object())
    assert active_arc(eng, "k") is None


def test_LLM_patlarsa_COKMEZ(tmp_path, monkeypatch):
    import short_bot.autopilot_arc as A
    monkeypatch.setattr(A, "plan_arc", lambda *a, **kw: None)
    eng = init_db(tmp_path / "db.sqlite")
    insert_bank_topics(eng, "k", [{"topic": "Bankadaki konu", "views": 1, "subs": 1}])
    ensure_arc(eng, _Ch(), llm_call=object())
    assert active_arc(eng, "k") is None


def test_zincir_modunda_DOKUNMAZ(tmp_path, monkeypatch):
    _fake_plan(monkeypatch)

    class _C(_Ch):
        class reel(_Reel):
            arc_mode = "chain"
    eng = init_db(tmp_path / "db.sqlite")
    insert_bank_topics(eng, "k", [{"topic": "Bankadaki konu", "views": 1, "subs": 1}])
    ensure_arc(eng, _C(), llm_call=object())
    assert active_arc(eng, "k") is None


def test_seri_kapaliysa_DOKUNMAZ(tmp_path, monkeypatch):
    _fake_plan(monkeypatch)

    class _C(_Ch):
        class reel(_Reel):
            series_enabled = False
    eng = init_db(tmp_path / "db.sqlite")
    insert_bank_topics(eng, "k", [{"topic": "Bankadaki konu", "views": 1, "subs": 1}])
    ensure_arc(eng, _C(), llm_call=object())
    assert active_arc(eng, "k") is None


def test_tohum_bankadan_DUSER(tmp_path, monkeypatch):
    """Aynı tohumdan iki ark planlanmasın."""
    from short_bot.db import all_bank_topics
    _fake_plan(monkeypatch)
    eng = init_db(tmp_path / "db.sqlite")
    insert_bank_topics(eng, "k", [{"topic": "Bankadaki konu", "views": 1, "subs": 1}])
    ensure_arc(eng, _Ch(), llm_call=object())
    assert all_bank_topics(eng, "k")[0]["status"] == "used"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_autopilot_arc.py -q`
Expected: `ModuleNotFoundError: No module named 'short_bot.autopilot_arc'`

- [ ] **Step 3: Implement**

```python
# src/short_bot/autopilot_arc.py
"""Ark oto-yenileme (autopilot).

Günde 3 video üreten bir kanalda 3 bölümlük ark BİR GÜNDE biter. Ertesi gün onaylı
ark kalmazsa sistem bankadan tek konu üretmeye düşer ve SERİ DURUR — yani Faz 3'ün
bütün abone mekanizması çalışmaz hâle gelir.

Kullanıcının kararı: otomatik planla + otomatik ONAYLA.

TEK İSTİSNA: kullanıcının kendi BEKLEYEN TASLAĞI varsa dokunma. Onun incelemesini
ezip kendi arkımızı üretime almak, kullanıcının onay mekanizmasına duyduğu güveni
yıkar — ve bir daha panele bakmaz.
"""
from __future__ import annotations

import logging

from short_bot.db import (active_arc, active_bank_topics, approve_arc, create_arc,
                          draft_arc, mark_bank_topic_used)
from short_bot.reel_arc import plan_arc

log = logging.getLogger(__name__)


def ensure_arc(eng, cfg, *, llm_call) -> bool:
    """Onaylı ark yoksa bankadan tohum al, ark planla ve OTO-ONAYLA.

    Dönüş: yeni ark üretime alındıysa True.
    Hiçbir hâlde ÇÖKMEZ — ark kurulamazsa üretim yine koşar (LLM konu üretir).
    """
    reel = getattr(cfg, "reel", None)
    if reel is None or not reel.enabled or not reel.series_enabled:
        return False
    if getattr(reel, "arc_mode", "chain") != "planned":
        return False
    if active_arc(eng, cfg.slug) is not None:
        return False
    if draft_arc(eng, cfg.slug) is not None:
        log.info(f"[autopilot] {cfg.slug}: kullanıcının taslağı onay bekliyor → "
                 f"oto-onay YOK (seri bu bölümde ilerlemeyecek)")
        return False

    aktifler = active_bank_topics(eng, cfg.slug, limit=1)
    if not aktifler:
        log.warning(f"[autopilot] {cfg.slug}: konu bankası boş → ark planlanamadı")
        return False
    tohum, bank_id = aktifler[0]["topic"], aktifler[0]["id"]

    if llm_call is None:
        log.warning(f"[autopilot] {cfg.slug}: LLM yok → ark planlanamadı")
        return False

    plan = plan_arc(tohum, channel=cfg, n=reel.series_arc_length, llm_call=llm_call)
    if plan is None:
        log.warning(f"[autopilot] {cfg.slug}: ark planlanamadı (LLM)")
        return False

    arc_id = create_arc(eng, cfg.slug, title=plan.title, seed_topic=tohum,
                        plan=[{"topic": e.topic, "promise": e.promise}
                              for e in plan.episodes])
    approve_arc(eng, arc_id)      # OTO-ONAY: kullanıcı tam otomasyon seçti
    mark_bank_topic_used(eng, bank_id)   # aynı tohumdan iki ark planlanmasın
    log.info(f"[autopilot] {cfg.slug}: yeni ark '{plan.title}' "
             f"({len(plan.episodes)} bölüm) oto-onaylandı")
    return True
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_autopilot_arc.py -q`
Expected: PASS (8 test)

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/autopilot_arc.py
git commit -m "feat(autopilot): ark oto-planla + oto-onayla (kullanicinin taslagina dokunmaz)"
```

---

### Task 9: Scheduler — iki cron bağla

**Files:**
- Modify: `src/short_bot/web/scheduler.py`
- Test: `tests/test_scheduler_autopilot_jobs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scheduler_autopilot_jobs.py
"""Autopilot cron'ları KAYITLI mı? Kayıtlı değilse hiçbir şey olmaz — ve bu
sessizdir: panelde slotlar planlı görünür, ama kimse üretmez."""
from short_bot.web import create_app

_CH = """slug: k
name: Kanal
keywords: [x]
language: tr
schedule_cron: "0 10 * * *"
duration_s: 40
min_score: 7.0
max_candidates_per_run: 3
max_age_hours: 24
template: stat-hero
colors: {primary: '#000', accent: '#fff', bg_gradient: ['#000', '#111']}
handle: '@k'
output_dir: output/k
enabled: true
content_source: generator
generator: {topic: 'ilginc bilgiler'}
autopilot:
  enabled: true
  daily_count: 2
"""


def _app(tmp_path, yaml_text=_CH, scheduler=True):
    cfg = tmp_path / "config"; (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8")
    (cfg / "channels" / "k.yaml").write_text(yaml_text, encoding="utf-8")
    return create_app(config_dir=cfg, db_path=tmp_path / "db.sqlite",
                      templates_dir=tmp_path / "t", music_root=tmp_path,
                      cache_dir=tmp_path, lock_dir=tmp_path, logs_dir=tmp_path,
                      output_root=tmp_path, secrets_path=tmp_path / "s.yaml",
                      scheduler=scheduler)


def test_autopilot_cronlari_kayitli(tmp_path):
    app = _app(tmp_path)
    ids = {j.id for j in app.scheduler.get_jobs()}
    assert "_autopilot_plan" in ids
    assert "_autopilot_tick" in ids
    app.scheduler.shutdown(wait=False)


def test_autopilot_acik_kanalin_CRON_u_kayitli_DEGIL(tmp_path):
    """ÇİFTE ÜRETİM ENGELİ — scheduler seviyesinde."""
    app = _app(tmp_path)
    ids = {j.id for j in app.scheduler.get_jobs()}
    assert "k" not in ids, "autopilot açıkken kanal cron'u da kayıtlı → çifte üretim"
    app.scheduler.shutdown(wait=False)


def test_autopilot_kapali_kanalin_cronu_KAYITLI(tmp_path):
    app = _app(tmp_path, _CH.replace("enabled: true\n  daily_count", 
                                     "enabled: false\n  daily_count"))
    ids = {j.id for j in app.scheduler.get_jobs()}
    assert "k" in ids, "geriye uyum kırıldı — normal kanal cron'u kaybolmuş"
    app.scheduler.shutdown(wait=False)


def test_acilista_slotlar_planlanir(tmp_path):
    """Gece cron'u kaçtıysa (uygulama kapalıydı) gün tamamen boş geçerdi."""
    from short_bot.db import init_db, slots_in_range
    app = _app(tmp_path)
    eng = init_db(tmp_path / "db.sqlite")
    s = slots_in_range(eng, "k", "2000-01-01", "2999-12-31")
    assert len(s) >= 2, "açılışta slot planlanmadı"
    app.scheduler.shutdown(wait=False)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_scheduler_autopilot_jobs.py -q`
Expected: FAIL — `_autopilot_plan` iş kimliği yok

- [ ] **Step 3: Implement**

`src/short_bot/web/scheduler.py` — `init_scheduler` içine, `_weekly_topic_bank_refresh`
kaydından sonra:

```python
    # --- AUTOPILOT --------------------------------------------------------
    def _autopilot_channels():
        cfg_dir = app.config["SHORTBOT_CONFIG_DIR"]
        for cfg in list_channels(cfg_dir / "channels", enabled_only=True):
            ap = getattr(cfg, "autopilot", None)
            if ap is not None and ap.enabled:
                yield cfg

    def _autopilot_plan():
        """Bugünün + yarının slotlarını yaz. İDEMPOTENT.

        Hem gece cron'unda hem UYGULAMA AÇILIŞINDA koşar: uygulama kapalıysa gece
        cron'u kaçar ve o gün tamamen boş geçerdi.
        """
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo
        from short_bot.autopilot_runner import plan_channel
        try:
            eng = init_db(app.config["SHORTBOT_DB_PATH"])
            for cfg in _autopilot_channels():
                try:
                    bugun = _dt.now(ZoneInfo(cfg.autopilot.timezone)).date()
                    n = plan_channel(eng, cfg, today_local=bugun, days=2)
                    if n:
                        _LOG.info(f"[autopilot] {cfg.slug}: +{n} slot planlandı")
                except Exception as e:  # noqa: BLE001
                    _LOG.warning(f"[autopilot] {cfg.slug} planlama hatası: {e}")
        except Exception as e:  # noqa: BLE001 — cron ÇÖKMEMELİ
            _LOG.warning(f"[autopilot] planlama işi başarısız: {e}")

    def _autopilot_tick():
        from short_bot.autopilot_runner import tick
        from short_bot.web.autopilot_deps import build_deps
        try:
            eng = init_db(app.config["SHORTBOT_DB_PATH"])
            for cfg in _autopilot_channels():
                try:
                    tick(eng, cfg, build_deps(app, cfg))
                except Exception as e:  # noqa: BLE001
                    _LOG.warning(f"[autopilot] {cfg.slug} tick hatası: {e}")
        except Exception as e:  # noqa: BLE001 — cron ÇÖKMEMELİ
            _LOG.warning(f"[autopilot] tick işi başarısız: {e}")

    scheduler.add_job(_autopilot_plan, trigger=CronTrigger(hour=3, minute=30),
                      id="_autopilot_plan", replace_existing=True)
    scheduler.add_job(_autopilot_tick, "interval", minutes=5,
                      id="_autopilot_tick", replace_existing=True)
    # AÇILIŞTA da planla (gece cron'u kaçmış olabilir)
    _autopilot_plan()
```

- [ ] **Step 4: `build_deps` — gerçek yan etkiler**

```python
# src/short_bot/web/autopilot_deps.py
"""Autopilot'un GERÇEK yan etkileri. Runner bunları enjekte alır; testler sahte
verir. Ağ, LLM, APScheduler yalnız burada."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from short_bot.autopilot_runner import AutopilotDeps
from short_bot.config import resolve_ai_call
from short_bot.pipeline import run_pipeline
from short_bot.youtube import auth as _yt_auth
from short_bot.youtube.auto_upload import run_auto_upload


def _secrets(app) -> dict:
    try:
        sp = app.config["SHORTBOT_SECRETS_PATH"]
        return (yaml.safe_load(sp.read_text(encoding="utf-8")) if sp.exists() else {}) or {}
    except Exception:
        return {}


def _llm(app):
    try:
        return resolve_ai_call(app.config["SHORTBOT_SETTINGS"], _secrets(app), "default")
    except Exception:
        return None


def _creds(app, cfg):
    root = Path(app.config["SHORTBOT_DB_PATH"]).parent / "youtube_credentials"
    return _yt_auth.load_credentials(root.resolve(), cfg.slug)


def build_deps(app, cfg) -> AutopilotDeps:
    def _produce(channel):
        # defer_upload=True ŞART: yüklemeyi AUTOPILOT yapacak (slot saatine).
        # Pipeline da yüklerse kanalda İKİ video olur.
        return run_pipeline(
            channel=channel, settings=app.config["SHORTBOT_SETTINGS"],
            db_path=app.config["SHORTBOT_DB_PATH"],
            music_root=app.config["SHORTBOT_MUSIC_ROOT"],
            templates_dir=app.config["SHORTBOT_TEMPLATES_DIR"],
            cache_dir=app.config["SHORTBOT_CACHE_DIR"],
            lock_dir=app.config["SHORTBOT_LOCK_DIR"],
            logs_dir=app.config["SHORTBOT_LOGS_DIR"],
            trigger="autopilot", defer_upload=True)

    def _upload(short_id, channel, publish_at=None):
        from short_bot.db import init_db
        eng = init_db(app.config["SHORTBOT_DB_PATH"])
        creds = _creds(app, channel)
        if creds is None:
            raise RuntimeError("YouTube kanalı bağlanmamış (token.json yok)")
        call = _llm(app)
        r = run_auto_upload(
            eng=eng, short_id=short_id, channel=channel, credentials=creds,
            claude_path=(call.claude_path if call else "claude"),
            model=(call.model if call else "sonnet"),
            backend=(call.backend if call else "claude_cli"),
            api_key=(call.api_key if call else None),
            secrets_path=app.config["SHORTBOT_SECRETS_PATH"],
            publish_at=publish_at)
        return r.video_url

    def _ensure_arc(channel):
        from short_bot.autopilot_arc import ensure_arc
        from short_bot.db import init_db
        ensure_arc(init_db(app.config["SHORTBOT_DB_PATH"]), channel,
                   llm_call=_llm(app))

    return AutopilotDeps(
        produce=_produce,
        upload_scheduled=lambda sid, ch, pa: _upload(sid, ch, publish_at=pa),
        upload_live=lambda sid, ch: _upload(sid, ch, publish_at=None),
        ensure_arc=_ensure_arc,
        now=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_scheduler_autopilot_jobs.py tests/test_scheduler_autopilot.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/web/scheduler.py src/short_bot/web/autopilot_deps.py
git commit -m "feat(autopilot): scheduler cron'lari + gercek yan etkiler (build_deps)"
```

---

### Task 10: Panel — slotlar görünür olsun

**Files:**
- Create: `src/short_bot/web/routes/autopilot.py`
- Create: `src/short_bot/web/templates/autopilot.html.j2`
- Modify: `src/short_bot/web/routes/__init__.py`
- Modify: `src/short_bot/web/templates/_partials/channel_card_reel.html.j2`
- Modify: `src/short_bot/web/routes/series.py` ("Bu bölümü şimdi üret")
- Modify: `src/short_bot/web/templates/series.html.j2`
- Test: `tests/test_web_autopilot.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_autopilot.py
"""Otomasyon GÖRÜNÜR olmalı. Görünmeyen bir otomasyon, güvenilemeyen bir otomasyondur.

Kullanıcı tek bakışta görmeli: bugün kaç video, hangi saatlerde, hangisi patladı.
"""
from datetime import datetime, timedelta, timezone

import pytest

from short_bot.db import init_db, plan_slots, slot_set_status, slots_for_date
from short_bot.web import create_app

UTC = timezone.utc

_CH = """slug: k
name: Kanal
keywords: [x]
language: tr
schedule_cron: "0 10 * * *"
duration_s: 40
min_score: 7.0
max_candidates_per_run: 3
max_age_hours: 24
template: stat-hero
colors: {primary: '#000', accent: '#fff', bg_gradient: ['#000', '#111']}
handle: '@k'
output_dir: output/k
enabled: true
content_source: generator
generator: {topic: 'ilginc bilgiler'}
reel: {enabled: true, voice_id: v1}
"""
_ACIK = _CH + "autopilot:\n  enabled: true\n  daily_count: 2\n"


def _app(tmp_path, yaml_text=_CH):
    cfg = tmp_path / "config"; (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8")
    (cfg / "channels" / "k.yaml").write_text(yaml_text, encoding="utf-8")
    db = tmp_path / "db.sqlite"; init_db(db)
    app = create_app(config_dir=cfg, db_path=db, templates_dir=tmp_path / "t",
                     music_root=tmp_path, cache_dir=tmp_path, lock_dir=tmp_path,
                     logs_dir=tmp_path, output_root=tmp_path,
                     secrets_path=tmp_path / "s.yaml", scheduler=False)
    return app, db


def test_kapaliyken_ACIKLAMA_ve_ACMA_dugmesi(tmp_path):
    a, _ = _app(tmp_path)
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "Otomasyon kapalı" in body
    assert "/autopilot/enable" in body


def test_ACMA_dugmesi_YAMLa_yazar(tmp_path):
    from short_bot.config import load_channel
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/k/autopilot/enable")
    assert r.status_code in (200, 302)
    cfg = load_channel(a.config["SHORTBOT_CONFIG_DIR"] / "channels" / "k.yaml")
    assert cfg.autopilot is not None and cfg.autopilot.enabled is True


def test_KAPATMA_dugmesi(tmp_path):
    from short_bot.config import load_channel
    a, _ = _app(tmp_path, _ACIK)
    a.test_client().post("/channels/k/autopilot/disable")
    cfg = load_channel(a.config["SHORTBOT_CONFIG_DIR"] / "channels" / "k.yaml")
    assert cfg.autopilot.enabled is False


def test_slotlar_SAATLERIYLE_gorunur(tmp_path):
    a, db = _app(tmp_path, _ACIK)
    eng = init_db(db)
    from datetime import date
    bugun = date.today().isoformat()
    plan_slots(eng, "k", bugun, [
        {"slot_index": 0, "slot_at_utc": datetime.now(UTC) + timedelta(hours=2),
         "jitter_min": 3}])
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "planlandı" in body or "planned" in body


def test_BASARISIZ_slot_gorunur(tmp_path):
    a, db = _app(tmp_path, _ACIK)
    eng = init_db(db)
    from datetime import date
    bugun = date.today().isoformat()
    plan_slots(eng, "k", bugun, [
        {"slot_index": 0, "slot_at_utc": datetime.now(UTC), "jitter_min": 0}])
    sid = slots_for_date(eng, "k", bugun)[0]["id"]
    slot_set_status(eng, sid, "failed", error="ai33 patladi")

    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "başarısız" in body.lower() or "failed" in body
    assert "ai33 patladi" in body, "hata metni gizlenmemeli"


def test_kanal_kartinda_otomasyon_baglantisi(tmp_path):
    a, _ = _app(tmp_path)
    body = a.test_client().get("/channels").data.decode("utf-8")
    assert "/autopilot" in body


def test_seri_sayfasinda_SIMDI_URET_dugmesi(tmp_path):
    """Kullanıcının şikâyeti: 'üret diye bir buton yok'."""
    a, db = _app(tmp_path, _CH + "\n")
    # seri açık bir kanal gerekiyor
    p = a.config["SHORTBOT_CONFIG_DIR"] / "channels" / "k.yaml"
    p.write_text(_CH.replace("reel: {enabled: true, voice_id: v1}",
                             "reel:\n  enabled: true\n  voice_id: v1\n"
                             "  series_enabled: true\n  series_title: Seri\n"),
                 encoding="utf-8")
    body = a.test_client().get("/channels/k/series").data.decode("utf-8")
    assert "/series/produce-now" in body
    assert "şimdi üret" in body.lower()


def test_olmayan_kanal_404(tmp_path):
    a, _ = _app(tmp_path)
    assert a.test_client().get("/channels/yok/autopilot").status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_web_autopilot.py -q`
Expected: 404 (rota yok)

- [ ] **Step 3: Implement — rota**

```python
# src/short_bot/web/routes/autopilot.py
"""Otomasyon paneli: slotlar GÖRÜNÜR olsun.

Görünmeyen bir otomasyon, güvenilemeyen bir otomasyondur. Kullanıcı tek bakışta
görmeli: bugün kaç video, hangi saatlerde, hangisi patladı ve NEDEN.
"""
from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, url_for)

from short_bot.config import AutopilotConfig, load_channel, save_channel
from short_bot.db import init_db, slots_in_range

bp = Blueprint("autopilot", __name__)


def _load_cfg(slug: str):
    path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not path.exists():
        abort(404)
    return load_channel(path)


def _save(cfg, slug: str, ap: AutopilotConfig) -> None:
    path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    save_channel(path, dataclasses.replace(cfg, autopilot=ap))


@bp.get("/channels/<slug>/autopilot")
def page(slug):
    cfg = _load_cfg(slug)
    ap = getattr(cfg, "autopilot", None)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])

    tz = ZoneInfo(ap.timezone) if ap else ZoneInfo("Europe/Istanbul")
    bugun = datetime.now(tz).date()
    yarin = bugun + timedelta(days=1)
    rows = slots_in_range(eng, slug, bugun.isoformat(), yarin.isoformat())

    def _yerel(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz)

    gunler = {}
    for r in rows:
        r["local_time"] = _yerel(r["slot_at_utc"])
        gunler.setdefault(r["slot_local_date"], []).append(r)

    bugunku = gunler.get(bugun.isoformat(), [])
    ozet = {
        "toplam": len(bugunku),
        "published": sum(1 for x in bugunku if x["status"] == "published"),
        "scheduled": sum(1 for x in bugunku if x["status"] == "scheduled"),
        "failed": sum(1 for x in bugunku if x["status"] in ("failed", "skipped")),
    }
    return render_template("autopilot.html.j2", slug=slug, channel=cfg,
                           enabled=bool(ap and ap.enabled), ap=ap,
                           today=bugun.isoformat(), tomorrow=yarin.isoformat(),
                           days=gunler, summary=ozet, tz=str(tz))


@bp.post("/channels/<slug>/autopilot/enable")
def enable(slug):
    """Otomasyonu aç. Slotlar bir sonraki tick'te planlanır (5 dk içinde)."""
    cfg = _load_cfg(slug)
    ap = getattr(cfg, "autopilot", None) or AutopilotConfig()
    _save(cfg, slug, ap.model_copy(update={"enabled": True}))
    flash("Otomasyon açıldı. Slotlar birkaç dakika içinde planlanacak. "
          "Kanalın normal cron'u artık koşmayacak (çifte üretim olmasın diye).",
          "success")
    return redirect(url_for("autopilot.page", slug=slug))


@bp.post("/channels/<slug>/autopilot/disable")
def disable(slug):
    cfg = _load_cfg(slug)
    ap = getattr(cfg, "autopilot", None) or AutopilotConfig()
    _save(cfg, slug, ap.model_copy(update={"enabled": False}))
    flash("Otomasyon kapatıldı. Kanalın normal cron'u yeniden devreye girdi.", "info")
    return redirect(url_for("autopilot.page", slug=slug))
```

`src/short_bot/web/routes/__init__.py` — import ve register ekle:

```python
        topic_bank, series, autopilot,
    )
    ...
    app.register_blueprint(series.bp)
    app.register_blueprint(autopilot.bp)
```

- [ ] **Step 4: Implement — şablon**

```jinja
{# src/short_bot/web/templates/autopilot.html.j2 #}
{% extends "base.html.j2" %}
{% block title %}Otomasyon — {{ channel.name }}{% endblock %}

{% macro durum(s) %}
  {% if s == 'planned' %}<span class="text-claude-muted">planlandı</span>
  {% elif s == 'producing' %}<span class="text-claude-accent">üretiliyor…</span>
  {% elif s == 'produced' %}<span class="text-claude-accent">üretildi, yükleniyor</span>
  {% elif s == 'scheduled' %}<span class="text-claude-accent font-semibold">yayına zamanlandı</span>
  {% elif s == 'published' %}<span class="text-green-600 font-semibold">yayında</span>
  {% elif s == 'failed' %}<span class="text-red-500 font-semibold">başarısız</span>
  {% elif s == 'skipped' %}<span class="text-red-500">kaçtı</span>
  {% endif %}
{% endmacro %}

{% block content %}
<div class="max-w-5xl mx-auto p-6">
  <div class="flex items-start justify-between gap-4 mb-6">
    <div>
      <h1 class="text-2xl font-bold text-claude-text">Otomasyon</h1>
      <p class="text-sm text-claude-muted mt-1">
        {{ channel.name }}
        {% if enabled %}· günde {{ ap.daily_count }} video
        · {{ ap.active_hours[0] }}:00–{{ ap.active_hours[1] }}:00 ({{ tz }})
        · {{ 'YouTube zamanlar' if ap.publish_mode == 'publish_at' else 'uygulama yükler' }}
        {% endif %}
      </p>
    </div>
    {% if enabled %}
    <form method="post" action="/channels/{{ slug }}/autopilot/disable"
          onsubmit="return confirm('Otomasyon kapatılsın mı? Planlı slotlar üretilmeyecek.')">
      <button class="px-4 py-2 rounded-lg bg-white border border-claude-border
                     text-sm font-semibold text-claude-muted hover:text-red-500">
        Kapat</button>
    </form>
    {% endif %}
  </div>

  {% with messages = get_flashed_messages() %}
    {% for m in messages %}
      <div class="mb-4 px-4 py-3 rounded-lg bg-claude-surface border border-claude-border
                  text-sm text-claude-text">{{ m }}</div>
    {% endfor %}
  {% endwith %}

  {% if not enabled %}
    <div class="rounded-xl border border-dashed border-claude-border bg-claude-surface
                px-6 py-10 text-center">
      <p class="text-claude-text font-medium text-lg">Otomasyon kapalı</p>
      <p class="text-sm text-claude-muted mt-3 max-w-xl mx-auto leading-relaxed">
        Bu kanal şu an <b>cron'a</b> bağlı: cron ateşlenir, video üretilir ve
        <b>üretim biter bitmez</b> yüklenir. Yani yayın saati üretim süresine bağlı
        ve her gün aynı dakikaya düşer.
      </p>
      <div class="mt-5 max-w-lg mx-auto text-left text-sm text-claude-muted space-y-2">
        <p>• Günde <b>N video</b>, aktif saatlere yayılmış slotlarda.</p>
        <p>• Yayın saatleri <b>insan gibi</b> gezinir (13:00 → 13:10 → 13:04),
          düz rastgele değil — ritim korunur.</p>
        <p>• Üretim yayından <b>saatler önce</b> koşar; video gizli yüklenir ve
          YouTube tam slot anında yayınlar.</p>
        <p>• Kanalın cron'u <b>devre dışı kalır</b> (çifte üretim olmasın diye).</p>
      </div>
      <form method="post" action="/channels/{{ slug }}/autopilot/enable" class="mt-6">
        <button class="px-5 py-2.5 rounded-lg bg-claude-accent text-white
                       text-sm font-semibold hover:opacity-90">
          Otomasyonu aç</button>
      </form>
    </div>
  {% else %}
    <div class="grid grid-cols-4 gap-3 mb-6">
      {% for etiket, deger, renk in [
          ('Bugün', summary.toplam, 'text-claude-text'),
          ('Yayında', summary.published, 'text-green-600'),
          ('Zamanlandı', summary.scheduled, 'text-claude-accent'),
          ('Başarısız', summary.failed, 'text-red-500')] %}
      <div class="rounded-xl border border-claude-border bg-white p-4 text-center">
        <div class="text-2xl font-bold {{ renk }}">{{ deger }}</div>
        <div class="text-xs text-claude-muted mt-1">{{ etiket }}</div>
      </div>
      {% endfor %}
    </div>

    {% for gun, baslik in [(today, 'Bugün'), (tomorrow, 'Yarın')] %}
    <h2 class="text-sm font-semibold text-claude-muted uppercase tracking-wide mb-3">
      {{ baslik }} <span class="normal-case font-normal">({{ gun }})</span></h2>
    {% if days.get(gun) %}
      <div class="space-y-2 mb-6">
      {% for s in days[gun] %}
        <div class="rounded-xl border border-claude-border bg-white p-4
                    flex items-center gap-4">
          <div class="w-20 font-mono text-lg font-bold text-claude-text">
            {{ s.local_time.strftime('%H:%M') if s.local_time else '—' }}</div>
          <div class="flex-1 min-w-0">
            <div class="text-sm">{{ durum(s.status) }}</div>
            {% if s.error %}
            <p class="text-xs text-red-500 mt-1">{{ s.error }}</p>
            {% endif %}
            {% if s.attempts > 1 %}
            <p class="text-xs text-claude-muted mt-1">{{ s.attempts }} deneme</p>
            {% endif %}
          </div>
          {% if s.short_id %}
          <a href="/shorts/{{ s.short_id }}"
             class="text-xs text-claude-muted hover:text-claude-accent flex-shrink-0">
            videoyu aç →</a>
          {% endif %}
        </div>
      {% endfor %}
      </div>
    {% else %}
      <div class="rounded-xl border border-dashed border-claude-border
                  bg-claude-surface px-4 py-6 text-center text-sm text-claude-muted mb-6">
        Slot yok — planlayıcı birkaç dakika içinde yazacak.
      </div>
    {% endif %}
    {% endfor %}
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 5: Implement — kanal kartı + "şimdi üret"**

`_partials/channel_card_reel.html.j2` — 📚 Seri bağlantısının yanına:

```jinja
      {% if c.reel %}
      <a href="/channels/{{ c.slug }}/autopilot"
         class="px-2 py-1 rounded text-xs {% if c.autopilot and c.autopilot.enabled %}text-claude-accent hover:bg-claude-accent-soft{% else %}text-claude-muted hover:bg-claude-surface-alt{% endif %}"
         title="{% if c.autopilot and c.autopilot.enabled %}Otomasyon açık — slotlar{% else %}Otomasyon kapalı — açmak için tıkla{% endif %}">⚙️ Otomasyon</a>
      {% endif %}
```

`web/routes/series.py` — yeni rota:

```python
@bp.post("/channels/<slug>/series/produce-now")
def produce_now(slug):
    """Sıradaki bölümü SLOT BEKLEMEDEN üret. Kullanıcının şikâyeti: 'üret diye bir
    buton yok' — otomasyonun ne zaman üreteceğini beklemek zorunda kalmasın."""
    from short_bot.web.runs import launch_pipeline
    cfg = _load_cfg(slug)
    launch_pipeline(
        channel=cfg, settings=current_app.config["SHORTBOT_SETTINGS"],
        db_path=current_app.config["SHORTBOT_DB_PATH"],
        music_root=current_app.config["SHORTBOT_MUSIC_ROOT"],
        templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
        cache_dir=current_app.config["SHORTBOT_CACHE_DIR"],
        lock_dir=current_app.config["SHORTBOT_LOCK_DIR"],
        logs_dir=current_app.config["SHORTBOT_LOGS_DIR"],
        trigger="manual")
    flash("Bölüm üretimi başladı (arka planda, ~10 dk). Akış sayfasından izle.",
          "success")
    return redirect(url_for("series.page", slug=slug))
```

`series.html.j2` — "SIRADAKİ" kutusundaki düğme sütununa:

```jinja
          <form method="post" action="/channels/{{ slug }}/series/produce-now"
                onsubmit="return confirm('Bu bölüm şimdi üretilsin mi? (~10 dk)')">
            <button class="w-full px-4 py-2 rounded-lg bg-claude-accent text-white
                           text-sm font-semibold hover:opacity-90 whitespace-nowrap">
              Şimdi üret</button>
          </form>
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_web_autopilot.py tests/test_web_series.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/short_bot/web/
git commit -m "feat(autopilot): panel (slotlar, ac/kapat) + seri 'simdi uret' dugmesi"
```

---

### Task 11: Tam takım + uçtan uca doğrulama

- [ ] **Step 1: Tam test takımı**

Run: `python -m pytest -q`
Expected: TÜMÜ PASS (önceki 1865 + yeni ~70)

- [ ] **Step 2: Gerçek kanalda uçtan uca**

`bilim-tarihinin-sok-anlari` kanalında:
1. Panelden otomasyonu aç (`daily_count: 2`, `produce_lead_hours: 1`).
2. Paneli yeniden başlat → açılışta slotlar planlanır.
3. `/channels/bilim-tarihinin-sok-anlari/autopilot` → bugünün 2 slotu saatleriyle
   görünmeli, ikisi de "planlandı".
4. DB'den doğrula: iki günün slotları yazılmış, saatler aktif saatler içinde,
   aralarında ≥30 dk var.
5. `_reload_jobs`'un kanal cron'unu KAYDETMEDİĞİNİ doğrula (çifte üretim yok):
   ```python
   ids = {j.id for j in app.scheduler.get_jobs()}
   assert "bilim-tarihinin-sok-anlari" not in ids
   ```
6. Ertesi günün slotlarını da yazdır ve jitter'ın **yürüdüğünü** göster
   (gün-1 sapmaları ≠ gün-2 sapmaları, fark ≤ `jitter_step`).

- [ ] **Step 3: Commit**

```bash
git add -A src/ templates/
git commit -m "feat(autopilot): otomatik uretim + zamanli yukleme (uctan uca dogrulandi)"
```

---

## Self-Review — spec kapsamı

| Spec bölümü | Task |
|---|---|
| §2 üretim/yükleme ayrımı | 4 (defer_upload), 7 (durum makinesi) |
| §3 rastgele yürüyüş jitter | 1 |
| §3 aktif saat + çakışma koruması | 1 |
| §4 `publish_slots` + durum makinesi | 3, 7 |
| §5 saf `autopilot.py` | 1 |
| §6 iki cron + açılışta planlama | 9 |
| §6.3 ark oto-yenileme | 8 |
| §7.1 cron çakışması | 5 |
| §7.2 çifte yükleme | 4 |
| §7.3 geç yükleme yok | 7 |
| §8 config (varsayılan kapalı) | 2 |
| §9 panel | 10 |
| §10 hata tablosu | 7 (hepsinin testi var) |
| §11 test planı | 1,3,4,5,6,7,8,9,10 |
| §12 kapsam dışı | — (yapılmadı, bilerek) |

**Boşluk yok.** `publish_at` katman geçirme (spec'te örtük) Task 6 olarak eklendi.
