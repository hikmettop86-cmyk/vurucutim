# Merak Mimarisi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Görüntü-önce reel senaryosunu 3-aday yarışma + merak yargıcı + doktor hattından geçirip, kurguyu (reveal saklama, açık-soru çipi, tırmanan tempo) merak-farkındalı yapmak.

**Architecture:** Yeni `reel_curiosity.py` modülü 3 merak iskeletiyle paralel aday üretir, rubrik tabanlı yargıç kazananı seçer, doktor yalnız şikâyetleri düzeltir. `ReelNarration`'a `open_question/reveal_beat/clip_order` alanları eklenir; `reel.py` permütasyonu klipler üzerine uygular, overlay'e soru çipi, pacing'e tepeye-doğru rampa girer. `curiosity_pipeline=False` → bugünkü tek-çağrı akış birebir.

**Tech Stack:** Python 3.14, pydantic v2, mevcut `run_json` (OpenRouter/Sonnet 5), Jinja2 overlay, pytest.

**Spec:** `docs/superpowers/specs/2026-07-16-merak-mimarisi-design.md`

**Kurallar (repo):** ASCII Türkçe commit mesajı, Co-Authored-By YOK. Yeni test dosyaları `git add -f` ister (tests/ gitignore'da). Üretim doğrulamasını cron pencereleriyle (örn. :29) çakıştırma.

---

### Task 1: `reel_curiosity.py` — iskeletler + rubrik

**Files:**
- Create: `src/short_bot/reel_curiosity.py`
- Test: `tests/test_reel_curiosity.py` (yeni — `git add -f`)

- [ ] **Step 1.0: Rubrik araştırma denemesi (zaman kutulu, ~10dk)**

`config/channels/mahalle-vahsisi.yaml` içindeki `reference_channels` kanallarının en çok izlenen 3-5 shorts transkriptini çekmeyi dene (repoda `yt_outliers`/YouTube Data API altyapısı; `data/secrets.yaml` youtube_api_key). Transkript gelirse: hook-soru biçimleri, bilgi sızma noktaları, beat-sonu kancaları, tepe zamanlamasını çıkar ve Step 3'teki RUBRIC metnini bulgularla ZENGİNLEŞTİR (madde ekle/örnek değiştir). Erişilemezse Step 3'teki rubrik (DiscoverNow DNA belgesi + ilk-ilke) aynen kullanılır — modül docstring'ine hangi yoldan geldiği yazılır.

- [ ] **Step 1.1: Failing test yaz**

```python
# tests/test_reel_curiosity.py
"""Merak mimarisi: 3 aday senaryo -> rubrik yargici -> doktor (spec 2026-07-16)."""


def test_iskeletler_uc_farkli_strateji():
    from short_bot.reel_curiosity import CURIOSITY_SKELETONS
    assert len(CURIOSITY_SKELETONS) == 3
    etiketler = [e for e, _ in CURIOSITY_SKELETONS]
    assert len(set(etiketler)) == 3
    talimatlar = " ".join(t for _, t in CURIOSITY_SKELETONS).lower()
    # üç strateji: gizem-önce / tırmanan bahis / sahte çözüm+twist
    assert "sona sakla" in talimatlar or "cevabı en son" in talimatlar
    assert "daha büyük" in talimatlar          # tırmanış
    assert "ters köşe" in talimatlar or "twist" in talimatlar


def test_rubrik_kritik_maddeleri_iceriyor():
    from short_bot.reel_curiosity import RUBRIC
    low = RUBRIC.lower()
    for kavram in ("açık döngü", "sızıntı", "kanca", "tırman", "ödeme",
                   "görüntü", "mizah"):
        assert kavram in low, f"rubrikte eksik kavram: {kavram}"
```

- [ ] **Step 1.2: Testi koş, düştüğünü gör**

Run: `python -m pytest tests/test_reel_curiosity.py -q`
Expected: FAIL — `ModuleNotFoundError: short_bot.reel_curiosity`

- [ ] **Step 1.3: Modülü yaz (iskeletler + rubrik)**

```python
# src/short_bot/reel_curiosity.py
"""MERAK MİMARİSİ: 3 aday senaryo -> rubrik yargıcı -> doktor turu.

Kullanıcı teşhisi (2026-07-16): videolar komik ama SÜRÜKLEYİCİ değil — hook
durdurmuyor, beat'ler arası 'sonra ne olacak?' çekişi yok, tepe 'vay be'
dedirtmiyor. Tek taslağı cilalamak sıkıcı taslağı cilalamaya mahkûm; ÇEŞİTLİLİK
+ SEÇİM iterasyonu yener: her adaya farklı merak iskeleti dayatılır, rubrik
tabanlı yargıç kazananı seçer, doktor yalnız somut şikâyetleri düzeltir.

Rubrik kaynağı: DiscoverNow mizah DNA analizi (manuel araştırma tarihçesi) +
anlatı ilk-ilkeleri (bilgi-boşluğu kuramı). Transkript tabanlı doğrulama
eklendiyse docstring'in sonuna işlenir.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# Her adaya BİR iskelet dayatılır — üç aday üç farklı merak stratejisi dener.
CURIOSITY_SKELETONS: list[tuple[str, str]] = [
    ("GİZEM-ÖNCE",
     "Hook somut ve spesifik bir SORU/GİZEM açar ('Bu balık neden herkesi "
     "korkutuyor?' değil — 'Şu masum surat var ya, az sonra yapacağı şeye "
     "inanamayacaksın' tadında, SAHNEYE bağlı). Cevabı EN SONA SAKLA: her beat "
     "cevaba bir adım yaklaştırır ama YENİ bir mini-soru da açar. Cevap "
     "reveal beat'inden önce ASLA sızmaz."),
    ("TIRMANAN BAHİS",
     "Her beat bir öncekinden DAHA BÜYÜK bir iddia/tehlike/absürtlük kurar — "
     "'bu daha bir şey değil...' merdiveni. İzleyici her basamakta 'bundan "
     "büyüğü olamaz' der, sen bir üstünü koyarsın. Tepe = en büyük basamak; "
     "erken zirve YASAK (sonrası düşüş hissi verir)."),
    ("SAHTE ÇÖZÜM + TWIST",
     "İzleyiciye cevabı aldığını HİSSETTİR (bir beat sahte-çözüm gibi kapanır), "
     "sonra tepe onu TERS KÖŞE yapar — gerçek asıl o an açığa çıkar. Sahte "
     "çözüm inandırıcı olmalı; twist kliplerde GERÇEKTEN görünen bir şeyden "
     "doğmalı, uydurma olay YASAK."),
]

# Yargıcın puanlama rubriği. Kaynak: DiscoverNow DNA + anlatı ilk-ilkeleri.
RUBRIC = """PUANLAMA RUBRİĞİ (her aday için her maddeye 0-10):
1. AÇIK DÖNGÜ: hook somut/spesifik bir soru-gizem açıyor mu (jenerik 'bakın ne
   olacak' = 2 puan altı)? Cevap reveal beat'inden önce SIZINTI yapıyor mu?
   (sızıntı varsa bu madde en fazla 3)
2. BEAT-SONU KANCASI: her beat'in SON cümlesi sonraki beat'i merak ettiriyor mu
   (yeni mini-soru, tehdit, iddia)? Merakı SIFIRLAYAN (kapanan) beat sayısı kadar
   puan kır.
3. TIRMANIŞ: beat'ler yükseliyor mu — her biri öncekinden daha büyük
   iddia/tehlike/absürtlük? Düz sıralama (yer değiştirse fark etmez) = 4 altı.
4. ÖDEME: tepe, hook'un açtığı soruyu GERÇEKTEN cevaplıyor mu ve cevap
   beklenenden İYİ mi (ters köşe/abartı)? Vaat ödenmiyorsa aday DİSKALİFİYE.
5. MİZAH YOĞUNLUĞU: benzetme/replik/patlama-cümle sıklığı; boş geçiş cümlesi
   ('bak şimdi', 'işin sırrı') başına puan kır.
6. GÖRÜNTÜ SADAKATİ: her beat kendi klibinin TARİFİNDE olan şeyi mi anlatıyor?
   Tarif dışı somut olay uyduran aday DİSKALİFİYE.
7. KLİŞE: yasak açılışlar ('Ula', 'bak hele', 'biliyor muydunuz') ya da
   birbirinin aynısı kalıplar varsa puan kır."""
```

- [ ] **Step 1.4: Testi koş, geçtiğini gör**

Run: `python -m pytest tests/test_reel_curiosity.py -q`
Expected: 2 passed

- [ ] **Step 1.5: Commit**

```bash
git add src/short_bot/reel_curiosity.py
git add -f tests/test_reel_curiosity.py
git commit -m "feat(curiosity): merak iskeletleri + yargic rubrigi (yarisma hattinin temeli)"
```

---

### Task 2: Şema alanları — `open_question` / `reveal_beat` / `clip_order`

**Files:**
- Modify: `src/short_bot/reel_models.py` (ReelNarration gövdesi; `title` alanının yanına)
- Test: `tests/test_reel_models.py` (mevcut — normal `git add`)

- [ ] **Step 2.1: Failing test yaz** (`tests/test_reel_models.py` sonuna ekle)

```python
def test_merak_alanlari_varsayilan_ve_dogrulama():
    # Merak mimarisi (spec 2026-07-16): hepsi varsayılan-boş → geriye uyum.
    n = _narr()
    assert n.open_question == ""
    assert n.reveal_beat == -1
    assert n.clip_order == []
    # open_question kırpılır, reddedilmez (comment/cover_title dersi)
    n2 = _narr(open_question="Bu balık neden herkesi korkutuyor acaba " * 4)
    assert 0 < len(n2.open_question) <= 48
    # reveal_beat aralığa kelepçelenir (3 beat -> 0..2)
    assert _narr(reveal_beat=7).reveal_beat == 2
    assert _narr(reveal_beat=1).reveal_beat == 1


def test_clip_order_permutasyon_degilse_bosalir():
    # Geçersiz clip_order üretimi DÜŞÜREMEZ — kimlik sırasına (boş) düşer.
    assert _narr(clip_order=[0, 1, 2]).clip_order == [0, 1, 2]
    assert _narr(clip_order=[0, 0, 1]).clip_order == []     # tekrar → geçersiz
    assert _narr(clip_order=[0, 1]).clip_order == []        # eksik → geçersiz
    assert _narr(clip_order=[0, 1, 5]).clip_order == []     # aralık dışı → geçersiz
```

- [ ] **Step 2.2: Testi koş** — Expected: FAIL (`open_question` alanı yok)

- [ ] **Step 2.3: Alanları ekle** (`reel_models.py`, ReelNarration içinde `title` alanının hemen altına)

```python
    # --- MERAK MİMARİSİ (spec 2026-07-16) — hepsi varsayılan-boş (geriye uyum) ---
    # Hook'un açtığı merak sorusu; ekranda küçük çip olarak asılı kalır ve reveal
    # anında 'cevaplandı'ya döner. Kırpılır, reddedilmez (comment dersi).
    open_question: str = Field(default="", max_length=200)
    # Cevabın ödendiği beat (0-tabanlı). -1 = belirtilmedi → peak_beat kullanılır.
    reveal_beat: int = -1
    # Adayın klipleri DRAMATURJİYE göre dizmesi: beat i, orijinal kliplerden
    # clip_order[i]'yi anlatır. Permütasyon değilse boşaltılır (kimlik sırası).
    clip_order: list[int] = Field(default_factory=list)

    @field_validator("open_question", mode="before")
    @classmethod
    def _oq_kirp(cls, v):
        if not isinstance(v, str):
            return ""
        v = strip_non_turkish_diacritics(v).strip()
        return v[:48].rstrip() if len(v) > 48 else v

    @model_validator(mode="after")
    def _merak_alanlarini_kelepcele(self):
        n = len(self.beats)
        if self.reveal_beat >= n:
            object.__setattr__(self, "reveal_beat", n - 1)
        if self.reveal_beat < -1:
            object.__setattr__(self, "reveal_beat", -1)
        co = list(self.clip_order or [])
        if co and sorted(co) != list(range(n)):
            object.__setattr__(self, "clip_order", [])   # permütasyon değil → kimlik
        return self
```

`model_validator` importunu dosyanın başındaki pydantic importuna ekle (`from pydantic import BaseModel, Field, field_validator, model_validator` benzeri — mevcut satırı genişlet). NOT: ReelNarration'da zaten `model_validator` kullanılıyorsa mevcut sonrasına ayrı validator olarak ekle, birleştirme.

- [ ] **Step 2.4: Testi koş** — `python -m pytest tests/test_reel_models.py -q` → hepsi PASS

- [ ] **Step 2.5: Commit**

```bash
git add src/short_bot/reel_models.py tests/test_reel_models.py
git commit -m "feat(curiosity): ReelNarration merak alanlari (open_question/reveal_beat/clip_order, hepsi fail-open)"
```

---

### Task 3: `reel_narration` refaktörü — `_fd_prompt` + `_pin_queries` çıkar

Amaç: aday üretimi aynı prompt+persona bileşimini kullanabilsin; davranış BİREBİR.

**Files:**
- Modify: `src/short_bot/reel_narration.py` (`write_footage_driven_narration` gövdesi)
- Test: mevcut `tests/test_footage_driven.py` (değişiklik yok — yeşil kalmalı)

- [ ] **Step 3.1: Refaktör** — `write_footage_driven_narration` içindeki prompt bileşimi ve pinleme iki yardımcıya taşınır:

```python
def _fd_prompt(topic: str, clip_descriptions: list[str], *, channel,
               seed: int = 0) -> str:
    """Görüntü-önce senaryo prompt'u + persona + maskot (tek bileşim noktası)."""
    reel = getattr(channel, "reel", None)
    prompt = build_footage_driven_prompt(topic, clip_descriptions, channel=channel)
    persona = load_persona(getattr(reel, "persona", ""), language=channel.language)
    if persona:
        prompt += "\n\n" + persona_block(persona, seed=seed)
        from short_bot.persona import mascot_block
        mblok = mascot_block(getattr(reel, "mascot_name", ""),
                             getattr(reel, "mascot_animal", ""),
                             getattr(reel, "mascot_trait", ""))
        if mblok:
            prompt += "\n\n" + mblok
    return prompt


def _pin_queries(n, clip_queries: list[str], topic: str) -> "ReelNarration":
    """visual_query'leri GERÇEK footage sorgularına sabitle (LLM'inkini yok say)."""
    from short_bot.reel_models import ReelBeat, ReelNarration
    beats = []
    for i, b in enumerate(n.beats):
        q = (clip_queries[i] if i < len(clip_queries)
             else (clip_queries[-1] if clip_queries else "")) or b.visual_query or topic
        beats.append(ReelBeat(text=b.text, visual_query=q, keyword=b.keyword))
    return ReelNarration(
        hook=n.hook, beats=beats, close=n.close, mood=n.mood,
        hook_visual=(clip_queries[0] if clip_queries else n.hook_visual),
        close_visual=(clip_queries[-1] if clip_queries else n.close_visual),
        cover_title=n.cover_title, title=n.title, comment=n.comment,
        open_loop=n.open_loop, peak_beat=n.peak_beat,
        open_question=getattr(n, "open_question", ""),
        reveal_beat=getattr(n, "reveal_beat", -1),
        clip_order=list(getattr(n, "clip_order", []) or []))
```

`write_footage_driven_narration` gövdesi bu ikisini çağırır (guard'lar — `reel is None`, boş tarif — aynen başta kalır):

```python
    prompt = _fd_prompt(topic, clip_descriptions, channel=channel, seed=seed)
    from short_bot.reel_models import FDDraftNarration
    n = run_json(prompt, FDDraftNarration, claude_path=claude_path, model=model,
                 backend=backend, api_key=api_key, retries=3)
    return _pin_queries(n, clip_queries, topic)
```

- [ ] **Step 3.2: Mevcut testler yeşil mi** — `python -m pytest tests/test_footage_driven.py tests/test_reel_footage_driven.py -q` → hepsi PASS (davranış birebir kanıtı)

- [ ] **Step 3.3: Commit**

```bash
git add src/short_bot/reel_narration.py
git commit -m "refactor(reel): _fd_prompt + _pin_queries cikarildi (aday uretimi paylasacak; davranis birebir)"
```

---

### Task 4: `write_candidates` — 3 paralel aday

**Files:**
- Modify: `src/short_bot/reel_curiosity.py`
- Test: `tests/test_reel_curiosity.py`

- [ ] **Step 4.1: Failing test yaz**

```python
def _fake_draft(hook="hook cümlesi burada", oq="Bu tip neden korkutuyor?"):
    from short_bot.reel_models import FDDraftNarration
    return FDDraftNarration.model_validate({
        "hook": hook, "cover_title": "MANŞET",
        "beats": [{"text": "beat sıfır metni burada", "visual_query": "", "keyword": "K0"},
                  {"text": "beat bir metni burada", "visual_query": "", "keyword": "K1"},
                  {"text": "beat iki metni burada", "visual_query": "", "keyword": "K2"}],
        "close": "hook cümlesi kapanış", "mood": "upbeat",
        "open_question": oq, "reveal_beat": 2, "clip_order": [1, 0, 2]})


def _kanal():
    from types import SimpleNamespace
    reel = SimpleNamespace(target_duration_s=(45, 60), persona="vahsi_mizah",
                           mascot_name="", mascot_animal="", mascot_trait="")
    return SimpleNamespace(reel=reel, language="tr")


def test_write_candidates_uc_iskelet_uc_prompt():
    from short_bot.reel_curiosity import CURIOSITY_SKELETONS, write_candidates
    promptlar = []

    def inv(p, schema):
        promptlar.append(p)
        return _fake_draft()

    adaylar = write_candidates("kartal", ["a", "b", "c"], channel=_kanal(),
                               seed=3, invoke=inv)
    assert len(adaylar) == 3
    assert len(promptlar) == 3
    for (etiket, _), p in zip(CURIOSITY_SKELETONS, sorted(promptlar,
            key=lambda x: [e for e, _ in CURIOSITY_SKELETONS
                           if e in x][0] if any(e in x for e, _ in CURIOSITY_SKELETONS) else "")):
        pass  # her promptta bir iskelet etiketi olmalı:
    for p in promptlar:
        assert sum(1 for e, _ in CURIOSITY_SKELETONS if e in p) == 1
    # merak alanları prompt'ta isteniyor
    assert all('"open_question"' in p and '"reveal_beat"' in p
               and '"clip_order"' in p for p in promptlar)


def test_write_candidates_coken_aday_dusurulur():
    from short_bot.reel_curiosity import write_candidates
    sayac = {"n": 0}

    def inv(p, schema):
        sayac["n"] += 1
        if sayac["n"] == 2:
            raise RuntimeError("LLM down")
        return _fake_draft()

    adaylar = write_candidates("kartal", ["a", "b", "c"], channel=_kanal(),
                               seed=0, invoke=inv)
    assert len(adaylar) == 2          # çöken düştü, kalanlar yaşıyor
```

- [ ] **Step 4.2: Testi koş** — Expected: FAIL (`write_candidates` yok)

- [ ] **Step 4.3: Implement** (`reel_curiosity.py` sonuna)

```python
# Aday prompt'una eklenen merak yönergesi + iskelet + yeni JSON alanları.
_CANDIDATE_ADDENDUM = """
=== MERAK MİMARİSİ (BU ADAYIN İSKELETİ: {etiket}) ===
{talimat}

EK ÇIKTI ALANLARI (JSON'a ekle — hepsi ZORUNLU):
  "open_question": hook'un açtığı merak sorusu, İZLEYİCİ DİLİYLE, EN FAZLA 45
    karakter (ekranda küçük çip olarak asılı kalacak; kısa + spesifik).
  "reveal_beat": cevabın GERÇEKTEN ödendiği beat'in indeksi (0-tabanlı).
    0 OLAMAZ (cevap hook'ta ödenmez) — genelde son ya da sondan bir önceki beat.
  "clip_order": beat'leri hangi kliplere yazdığın — beat i, KLİP clip_order[i]'yi
    anlatır. Her klip TAM BİR KEZ kullanılır (permütasyon). DRAMATURJİ SENİN
    ELİNDE: en çarpıcı klibi reveal beat'ine koy; clip_order[0] (hook'ta da
    görünecek klip) FRAGMAN olmalı, cevabı GÖSTEREN klip ASLA olmamalı.
NOT: 'Beat i klip i'yi anlatır' kuralı bu modda ŞÖYLE değişir: beat i,
clip_order[i] numaralı KLİBİN tarifini anlatır. Tarifte olmayan olay uydurmak
yine YASAK."""


def write_candidates(topic: str, clip_descriptions: list[str], *, channel,
                     seed: int = 0, invoke) -> list:
    """3 iskeletle 3 paralel aday. Çöken aday düşürülür (fail-open).

    ``invoke``: (prompt, schema) -> FDDraftNarration (test enjeksiyonu / gerçek LLM).
    """
    from short_bot.reel_models import FDDraftNarration
    from short_bot.reel_narration import _fd_prompt
    base = _fd_prompt(topic, clip_descriptions, channel=channel, seed=seed)

    def _one(i):
        etiket, talimat = CURIOSITY_SKELETONS[i]
        p = base + _CANDIDATE_ADDENDUM.format(etiket=etiket, talimat=talimat)
        try:
            return invoke(p, FDDraftNarration)
        except Exception as e:  # noqa: BLE001 — tek aday yarışı düşürmesin
            log.warning(f"  merak[aday {etiket}]: üretim çöktü ({e}) → düşürüldü")
            return None

    with ThreadPoolExecutor(max_workers=3) as ex:
        sonuclar = list(ex.map(_one, range(len(CURIOSITY_SKELETONS))))
    return [s for s in sonuclar if s is not None]
```

- [ ] **Step 4.4: Testi koş** — `python -m pytest tests/test_reel_curiosity.py -q` → PASS

- [ ] **Step 4.5: Commit**

```bash
git add src/short_bot/reel_curiosity.py tests/test_reel_curiosity.py
git commit -m "feat(curiosity): write_candidates — 3 iskeletle paralel aday uretimi (fail-open)"
```

---

### Task 5: `judge_scripts` — rubrik yargıcı

**Files:**
- Modify: `src/short_bot/reel_curiosity.py`
- Test: `tests/test_reel_curiosity.py`

- [ ] **Step 5.1: Failing test yaz**

```python
def test_judge_kazanani_secer_ve_sikayetleri_dondurur():
    from short_bot.reel_curiosity import JudgeVerdict, judge_scripts
    adaylar = [_fake_draft(hook=f"hook varyant {i} burada") for i in range(3)]
    yakalanan = {}

    def inv(p, schema):
        yakalanan["p"] = p
        return JudgeVerdict(winner=1, scores=[4, 8, 6],
                            complaints=["beat 2 cevabı erken sızdırıyor"])

    kazanan, verdict = judge_scripts(adaylar, topic="kartal", invoke=inv)
    assert kazanan is adaylar[1]
    assert verdict.complaints
    p = yakalanan["p"]
    assert "RUBRİĞ" in p or "RUBRIK" in p.upper()  # rubrik promptta
    assert "hook varyant 0" in p and "hook varyant 2" in p  # adaylar promptta


def test_judge_cokerse_ilk_aday(caplog):
    from short_bot.reel_curiosity import judge_scripts
    adaylar = [_fake_draft(), _fake_draft()]

    def patlar(p, s):
        raise RuntimeError("down")

    kazanan, verdict = judge_scripts(adaylar, topic="x", invoke=patlar)
    assert kazanan is adaylar[0]
    assert verdict is None


def test_judge_gecersiz_winner_kelepcelenir():
    from short_bot.reel_curiosity import JudgeVerdict, judge_scripts
    adaylar = [_fake_draft(), _fake_draft()]

    def inv(p, s):
        return JudgeVerdict(winner=9, scores=[5, 5], complaints=[])

    kazanan, _ = judge_scripts(adaylar, topic="x", invoke=inv)
    assert kazanan is adaylar[0]      # aralık dışı → ilk aday
```

- [ ] **Step 5.2: Testi koş** — Expected: FAIL

- [ ] **Step 5.3: Implement**

```python
class JudgeVerdict(BaseModel):
    winner: int = Field(ge=0)
    scores: list[int] = Field(default_factory=list)      # aday başına toplam merak puanı
    complaints: list[str] = Field(default_factory=list, max_length=8)


def judge_scripts(candidates: list, *, topic: str, invoke):
    """Rubrikle yargıla → (kazanan_aday, verdict|None). Çökerse ilk aday (fail-open)."""
    if len(candidates) == 1:
        return candidates[0], None
    bolumler = []
    for i, c in enumerate(candidates):
        beats = "\n".join(f"    beat {j}: {b.text}" for j, b in enumerate(c.beats))
        bolumler.append(
            f"--- ADAY {i} ---\nhook: {c.hook}\nopen_question: {c.open_question}\n"
            f"reveal_beat: {c.reveal_beat}\n{beats}\nclose: {c.close}")
    prompt = (
        f"Konu: {topic}\n\nAşağıda aynı konu için yazılmış {len(candidates)} kısa "
        f"video senaryosu adayı var:\n\n" + "\n\n".join(bolumler) +
        f"\n\n{RUBRIC}\n\n"
        "GÖREV: Her adayı rubrikle puanla, EN SÜRÜKLEYİCİ olanı seç. Kazanan için "
        "EN FAZLA 5 SOMUT şikâyet yaz (hangi beat, ne sorun, nasıl düzelir) — "
        "doktor turu yalnız bunları düzeltecek. Genel laf ('daha iyi olabilir') "
        "yazma; işaret et.\n"
        'SADECE JSON: {"winner": <indeks>, "scores": [aday başına 0-70 toplam], '
        '"complaints": ["...", ...]}')
    try:
        v = invoke(prompt, JudgeVerdict)
    except Exception as e:  # noqa: BLE001 — yargıç çökerse yarışma iptal, ilk aday
        log.warning(f"  merak[yargıç]: çöktü ({e}) → ilk aday kullanılıyor")
        return candidates[0], None
    if not (0 <= v.winner < len(candidates)):
        return candidates[0], v
    log.info(f"  merak[yargıç]: kazanan aday {v.winner} "
             f"(puanlar={v.scores}) şikâyet={len(v.complaints)}")
    return candidates[v.winner], v
```

- [ ] **Step 5.4: Testi koş** → PASS. **Step 5.5: Commit**

```bash
git add src/short_bot/reel_curiosity.py tests/test_reel_curiosity.py
git commit -m "feat(curiosity): judge_scripts — rubrik yargici (fail-open: cokerse ilk aday)"
```

---

### Task 6: `doctor_pass` — yalnız şikâyetleri düzelt

**Files:**
- Modify: `src/short_bot/reel_curiosity.py`
- Test: `tests/test_reel_curiosity.py`

- [ ] **Step 6.1: Failing test yaz**

```python
def test_doctor_sikayetleri_promptlar_ve_sonucu_dondurur():
    from short_bot.reel_curiosity import doctor_pass
    kazanan = _fake_draft()
    duzeltilmis = _fake_draft(hook="düzeltilmiş hook cümlesi burada")
    yakalanan = {}

    def inv(p, schema):
        yakalanan["p"] = p
        return duzeltilmis

    out = doctor_pass(kazanan, ["beat 2 cevabı erken sızdırıyor"],
                      topic="kartal", invoke=inv)
    assert out is duzeltilmis
    assert "erken sızdırıyor" in yakalanan["p"]       # şikâyet promptta
    assert "beat sıfır metni burada" in yakalanan["p"]  # orijinal senaryo promptta


def test_doctor_beat_sayisi_degisirse_kazanan_kalir():
    from short_bot.reel_models import FDDraftNarration
    from short_bot.reel_curiosity import doctor_pass
    kazanan = _fake_draft()
    bozuk = FDDraftNarration.model_validate({
        "hook": "hook cümlesi burada", "beats": [
            {"text": "tek beat kaldı ama dört beat lazımdı", "visual_query": "", "keyword": "K"},
            {"text": "iki beat kaldı ama dört beat lazımdı", "visual_query": "", "keyword": "K"},
            {"text": "üç beat kaldı ama dört beat lazımdı", "visual_query": "", "keyword": "K"},
            {"text": "dört beat oldu ama kazanan üç beatti", "visual_query": "", "keyword": "K"}],
        "close": "kapanış cümlesi burada", "mood": "upbeat"})

    out = doctor_pass(kazanan, ["x"], topic="k", invoke=lambda p, s: bozuk)
    assert out is kazanan             # klip bağı bozulamaz


def test_doctor_sikayet_yoksa_dokunmaz():
    from short_bot.reel_curiosity import doctor_pass
    kazanan = _fake_draft()
    out = doctor_pass(kazanan, [], topic="k",
                      invoke=lambda p, s: (_ for _ in ()).throw(AssertionError("çağrılmamalı")))
    assert out is kazanan
```

- [ ] **Step 6.2: Testi koş** — FAIL. **Step 6.3: Implement**

```python
def doctor_pass(winner, complaints: list[str], *, topic: str, invoke):
    """Kazananı YALNIZ yargıç şikâyetlerini düzelterek yeniden yazdır.

    Beat sayısı değişirse (klip bağı bozulur) ya da çağrı çökerse kazanan
    olduğu gibi kalır (fail-open)."""
    if not complaints:
        return winner
    from short_bot.reel_models import FDDraftNarration
    mevcut = winner.model_dump_json()
    liste = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(complaints))
    prompt = (
        f"Konu: {topic}\n\nAşağıdaki kısa video senaryosu bir yarışmayı kazandı "
        f"ama yargıcın SOMUT şikâyetleri var. YALNIZ bu şikâyetleri düzelt — "
        f"beat SAYISI, clip_order, konuşulmayan alanlar ve genel yapı AYNEN "
        f"kalsın. İyi olan cümleleri değiştirme.\n\nSENARYO (JSON):\n{mevcut}\n\n"
        f"ŞİKÂYETLER:\n{liste}\n\nDüzeltilmiş senaryoyu AYNI ŞEMADA, SADECE JSON "
        f"olarak döndür.")
    try:
        out = invoke(prompt, FDDraftNarration)
    except Exception as e:  # noqa: BLE001
        log.warning(f"  merak[doktor]: çöktü ({e}) → kazanan olduğu gibi")
        return winner
    if len(out.beats) != len(winner.beats):
        log.warning("  merak[doktor]: beat sayısını değiştirdi → kazanan olduğu gibi")
        return winner
    return out
```

- [ ] **Step 6.4: Testi koş** → PASS. **Step 6.5: Commit**

```bash
git add src/short_bot/reel_curiosity.py tests/test_reel_curiosity.py
git commit -m "feat(curiosity): doctor_pass — yalniz yargic sikayetlerini duzeltir (beat bagi korunur)"
```

---

### Task 7: `write_curious_narration` — orkestratör

**Files:**
- Modify: `src/short_bot/reel_curiosity.py`
- Test: `tests/test_reel_curiosity.py`

- [ ] **Step 7.1: Failing test yaz**

```python
def test_orkestrator_zincir_ve_permutasyon():
    from short_bot.reel_curiosity import JudgeVerdict, write_curious_narration
    cagri = {"aday": 0, "yargic": 0, "doktor": 0}

    def inv(p, schema):
        from short_bot.reel_models import FDDraftNarration
        if schema is JudgeVerdict:
            cagri["yargic"] += 1
            return JudgeVerdict(winner=0, scores=[7], complaints=["beat 1 kancasız"])
        if "ŞİKÂYETLER" in p:
            cagri["doktor"] += 1
            return _fake_draft(hook="doktor düzeltti bu hook cümlesini")
        cagri["aday"] += 1
        return _fake_draft()

    narr, perm = write_curious_narration(
        "kartal", ["tarif a", "tarif b", "tarif c"],
        ["eagle soaring", "eagle diving", "eagle landing"],
        channel=_kanal(), seed=1, invoke=inv)
    assert cagri == {"aday": 3, "yargic": 1, "doktor": 1}
    assert narr.hook == "doktor düzeltti bu hook cümlesini"
    # _fake_draft clip_order=[1,0,2] → permütasyon dönüyor ve sorgular ona göre pinli
    assert perm == [1, 0, 2]
    assert [b.visual_query for b in narr.beats] == \
        ["eagle diving", "eagle soaring", "eagle landing"]
    assert narr.hook_visual == "eagle diving"
    from short_bot.reel_models import ReelNarration
    assert type(narr) is ReelNarration          # dönüş KATI şema


def test_orkestrator_tum_adaylar_cokerse_tek_cagri_yola_duser(monkeypatch):
    import short_bot.reel_curiosity as RC
    from short_bot.reel_models import ReelNarration, ReelBeat

    def tek_cagri(topic, descs, queries, **kw):
        return ReelNarration(
            hook="tek çağrı hook cümlesi", beats=[
                ReelBeat(text="beat sıfır metni burada", visual_query=queries[0], keyword="A"),
                ReelBeat(text="beat bir metni burada", visual_query=queries[1], keyword="B"),
                ReelBeat(text="beat iki metni burada", visual_query=queries[2], keyword="C")],
            close="tek çağrı kapanış cümlesi", mood="upbeat")

    monkeypatch.setattr(RC, "_fallback_single", tek_cagri)

    def hep_patlar(p, s):
        raise RuntimeError("down")

    narr, perm = RC.write_curious_narration(
        "kartal", ["a", "b", "c"], ["q0", "q1", "q2"],
        channel=_kanal(), seed=0, invoke=hep_patlar)
    assert narr.hook == "tek çağrı hook cümlesi"
    assert perm == [0, 1, 2]                     # kimlik permütasyonu
```

- [ ] **Step 7.2: Testi koş** — FAIL. **Step 7.3: Implement**

```python
def _fallback_single(topic, clip_descriptions, clip_queries, **kw):
    """Tüm adaylar çökerse: mevcut tek-çağrı yol (davranış = curiosity kapalı)."""
    from short_bot.reel_narration import write_footage_driven_narration
    return write_footage_driven_narration(topic, clip_descriptions, clip_queries, **kw)


def write_curious_narration(topic: str, clip_descriptions: list[str],
                            clip_queries: list[str], *, channel, seed: int = 0,
                            claude_path: str = "claude", model: str = "default",
                            backend: str = "claude_cli", api_key: str | None = None,
                            invoke=None):
    """Yarışma hattı: 3 aday → yargıç → doktor → pinleme.

    Döner ``(ReelNarration, perm)`` — ``perm`` beat→orijinal-klip permütasyonu
    (çağıran fd_clips/descs/queries'i bununla yeniden dizer; kimlik = değişiklik yok).
    """
    from short_bot.claude_cli import run_json
    from short_bot.reel_narration import _pin_queries
    inv = invoke or (lambda p, s: run_json(
        p, s, claude_path=claude_path, model=model, backend=backend,
        api_key=api_key, retries=2))

    adaylar = write_candidates(topic, clip_descriptions, channel=channel,
                               seed=seed, invoke=inv)
    if not adaylar:
        log.warning("  merak: TÜM adaylar çöktü → tek-çağrı yola düşülüyor")
        n = _fallback_single(topic, clip_descriptions, clip_queries,
                             channel=channel, seed=seed, claude_path=claude_path,
                             model=model, backend=backend, api_key=api_key)
        return n, list(range(len(clip_queries)))

    kazanan, verdict = judge_scripts(adaylar, topic=topic, invoke=inv)
    if verdict is not None and verdict.complaints:
        kazanan = doctor_pass(kazanan, verdict.complaints, topic=topic, invoke=inv)

    n_beats = len(kazanan.beats)
    perm = list(kazanan.clip_order) if len(kazanan.clip_order) == n_beats \
        else list(range(n_beats))
    # Sorgular permütasyona göre pinlenir: beat i ↔ orijinal klip perm[i].
    permuted_queries = [clip_queries[j] if j < len(clip_queries) else clip_queries[-1]
                        for j in perm] if clip_queries else []
    narr = _pin_queries(kazanan, permuted_queries, topic)
    return narr, perm
```

- [ ] **Step 7.4: Testi koş** → PASS. **Step 7.5: Commit**

```bash
git add src/short_bot/reel_curiosity.py tests/test_reel_curiosity.py
git commit -m "feat(curiosity): write_curious_narration orkestratoru — aday>yargic>doktor>pinleme, cok katmanli fail-open"
```

---

### Task 8: Config bayrağı + ReelDeps + produce kablolaması

**Files:**
- Modify: `src/short_bot/config.py` (ReelConfig, `footage_discovery` alanının yanına; `to_channel_data` serileştirme)
- Modify: `src/short_bot/reel.py` (ReelDeps + Dal A)
- Test: `tests/test_config_reel.py` (mevcut), `tests/test_reel_footage_driven.py` (mevcut)

- [ ] **Step 8.1: Failing testler**

`tests/test_config_reel.py` sonuna:

```python
def test_curiosity_pipeline_varsayilan_acik_ve_serilesir():
    from short_bot.config import ReelConfig
    r = ReelConfig(enabled=True, voice_id="v")
    assert r.curiosity_pipeline is True
```

`tests/test_reel_footage_driven.py` sonuna:

```python
def test_curiosity_acikken_yarisma_hatti_cagrilir(tmp_path, monkeypatch):
    import short_bot.reel as R
    monkeypatch.setattr(R, "_describe_clip", lambda c, **k: f"a chimpanzee {c.name}")
    calls = []
    deps = _fd_deps(calls, tmp_path)

    def fake_curious(topic, descs, queries, **kw):
        calls.append("merak-hatti")
        return _fd_narr(), [0, 1, 2]

    deps = replace(deps, write_curious_narration=fake_curious)  # dataclasses.replace
    out = produce_reel_video(
        topic="şempanze kavgası", channel=_FDChannel(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg",
        vision_call=object(), deps=deps)
    assert "merak-hatti" in calls
    assert "gorunti-once-narr" not in calls     # tek-çağrı yol ÇAĞRILMADI


def test_curiosity_kapaliyken_eski_tek_cagri(tmp_path, monkeypatch):
    import short_bot.reel as R
    from short_bot.config import ReelConfig
    monkeypatch.setattr(R, "_describe_clip", lambda c, **k: f"a chimpanzee {c.name}")

    class _Kapali(_FDChannel):
        reel = ReelConfig(enabled=True, voice_id="v1", target_duration_s=(45, 60),
                          persona="vahsi_mizah", footage_driven=True,
                          curiosity_pipeline=False)

    calls = []
    deps = replace(_fd_deps(calls, tmp_path),
                   write_curious_narration=lambda *a, **k: (_ for _ in ()).throw(
                       AssertionError("kapalıyken çağrılmamalı")))
    produce_reel_video(
        topic="şempanze kavgası", channel=_Kapali(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg",
        vision_call=object(), deps=deps)
    assert "gorunti-once-narr" in calls
```

Dosya başına `from dataclasses import replace` importunu ekle.

- [ ] **Step 8.2: Testleri koş** — FAIL. **Step 8.3: Implement**

`config.py` (ReelConfig, `footage_discovery` alanının hemen altına):

```python
    # MERAK MİMARİSİ (spec 2026-07-16): 3 aday senaryo → rubrik yargıcı → doktor.
    # Yalnız footage_driven=True iken etkin. Kapatılırsa tek-çağrı akış birebir.
    curiosity_pipeline: bool = True
```

`to_channel_data` içine (footage_discovery satırının yanına):

```python
            "curiosity_pipeline": cfg.reel.curiosity_pipeline,
```

`reel.py` ReelDeps (write_footage_driven_narration'ın yanına):

```python
    write_curious_narration: Callable = _write_curious
```

import bloğuna:

```python
from short_bot.reel_curiosity import write_curious_narration as _write_curious
```

Dal A (mevcut `if footage_driven:` senaryo dalı — tek-çağrı satırı `else`'e iner, mevcut hâli BOZULMADAN):

```python
    if footage_driven:
        if getattr(reel, "curiosity_pipeline", True):
            narration, _fd_perm = d.write_curious_narration(
                topic, fd_descs, fd_queries, channel=channel,
                claude_path=llm_claude_path, model=llm_model,
                backend=llm_backend, api_key=llm_api_key, seed=seed)
            if _fd_perm != list(range(len(_fd_perm))):
                # Beat i ↔ orijinal klip perm[i] → klipler dramaturji sırasına dizilir.
                fd_clips = [fd_clips[j] for j in _fd_perm]
                fd_descs = [fd_descs[j] for j in _fd_perm]
                fd_queries = [fd_queries[j] for j in _fd_perm]
        else:
            narration = d.write_footage_driven_narration(
                topic, fd_descs, fd_queries, channel=channel,
                claude_path=llm_claude_path, model=llm_model,
                backend=llm_backend, api_key=llm_api_key, seed=seed)
```

DİKKAT: `_fd_perm` uzunluğu `len(fd_clips)`ten kısaysa (beat<klip, teorik) permütasyonu uygulamadan önce `len(_fd_perm) == len(fd_clips)` kontrolü ekle; değilse permütasyonu atla (kimlik).

- [ ] **Step 8.4: Testleri koş** — `python -m pytest tests/test_config_reel.py tests/test_reel_footage_driven.py -q` → PASS

- [ ] **Step 8.5: Commit**

```bash
git add src/short_bot/config.py src/short_bot/reel.py
git add -f tests/test_config_reel.py tests/test_reel_footage_driven.py
git commit -m "feat(curiosity): config bayragi + produce kablolamasi (kapaliyken tek-cagri birebir)"
```

---

### Task 9: Tırmanan tempo — `plan_subcuts(peak_s=...)`

**Files:**
- Modify: `src/short_bot/reel_pacing.py`
- Modify: `src/short_bot/reel.py` (plan_subcuts çağrısı)
- Test: `tests/test_reel_pacing_density.py` (mevcut dosyaya ekle)

- [ ] **Step 9.1: Failing test yaz** (`tests/test_reel_pacing_density.py` sonuna)

```python
def test_peak_s_verilince_tempo_tepeye_dogru_sikisir():
    # Merak mimarisi: alt-kesim süresi hook→tepe kademeli kısalır (~1.25x→0.75x),
    # tepe sonrası rahatlar. MIN_SUBCUT_S tabanı korunur.
    from short_bot.reel_models import TimedWord
    from short_bot.reel_pacing import plan_subcuts
    words = [TimedWord(word=f"w{i}", start_s=i * 0.3, end_s=i * 0.3 + 0.25, seg=0)
             for i in range(200)]
    spans = [(0.0, 20.0), (20.0, 40.0), (40.0, 60.0)]
    ramp = plan_subcuts(spans, words, "medium", peak_s=40.0)
    duz = plan_subcuts(spans, words, "medium")
    d_ramp = [(b - a) for (_s, a, b) in ramp]
    d_duz = [(b - a) for (_s, a, b) in duz]
    # tepe öncesi son çeyrek (30-40s) ortalaması, açılış çeyreğinden KISA
    def ort(ds, cuts, lo, hi):
        v = [(b - a) for (_s, a, b) in cuts if lo <= a < hi]
        return sum(v) / max(1, len(v))
    assert ort(None, ramp, 30, 40) < ort(None, ramp, 0, 10)
    assert all(d >= 1.2 - 1e-9 for d in d_ramp)     # MIN_SUBCUT_S tabanı
    # peak_s verilmeyince davranış birebir eski (regresyon)
    assert d_duz == [(b - a) for (_s, a, b) in plan_subcuts(spans, words, "medium", peak_s=None)]
```

- [ ] **Step 9.2: Testi koş** — FAIL (peak_s parametresi yok)

- [ ] **Step 9.3: Implement** (`reel_pacing.py`)

```python
def _ramp_factor(t: float, peak_s: float | None) -> float:
    """Merak rampası: hedef alt-kesim süresi çarpanı. peak_s yoksa 1.0 (eski davranış).
    Hook'ta 1.25 (geniş nefes) → tepeye 0.75 (sıkışan kesim) → tepe sonrası 1.1."""
    if not peak_s or peak_s <= 0:
        return 1.0
    if t <= peak_s:
        return 1.25 - 0.5 * (t / peak_s)
    return 1.1
```

`plan_subcuts` imzası `def plan_subcuts(seg_spans, words, pacing: str = "medium", peak_s: float | None = None)` olur; iç döngüde `target` kullanımı şuna döner:

```python
        while True:
            hedef_simdi = target * _ramp_factor(cursor, peak_s)
            want = cursor + hedef_simdi
            if b - want < MIN_SUBCUT_S:
                break
            cands = [s for s in starts
                     if s - cursor >= MIN_SUBCUT_S and b - s >= MIN_SUBCUT_S]
            if not cands:
                break
            pick = min(cands, key=lambda s: abs(s - want))
            if pick - cursor > hi * _ramp_factor(cursor, peak_s) + 1.0:
                break
            cut_at.append(pick)
            cursor = pick
```

`reel.py`'de plan_subcuts çağrısı (fast_cuts dalı):

```python
    _peak_ramp_s = None
    if footage_driven and getattr(reel, "curiosity_pipeline", True):
        _ps = narration.peak_segment()
        if 0 <= _ps < len(timeline.seg_spans):
            _peak_ramp_s = timeline.seg_spans[_ps][1]
    if getattr(reel, "fast_cuts", True):
        subcuts = plan_subcuts(timeline.seg_spans, timeline.words,
                               profile.cut_pacing, peak_s=_peak_ramp_s)
```

- [ ] **Step 9.4: Testi koş** — `python -m pytest tests/test_reel_pacing_density.py tests/test_reel_markers_subcut.py -q` → PASS

- [ ] **Step 9.5: Commit**

```bash
git add src/short_bot/reel_pacing.py src/short_bot/reel.py
git add -f tests/test_reel_pacing_density.py
git commit -m "feat(curiosity): tirmanan tempo — alt-kesim suresi tepeye dogru kisalir (peak_s yoksa birebir eski)"
```

---

### Task 10: Açık soru çipi — overlay

**Files:**
- Modify: `templates/reel_overlay.html.j2`
- Modify: `src/short_bot/reel_render.py` (build_reel_overlay_html paramları)
- Test: `tests/test_reel_overlay_question.py` (yeni — `git add -f`)

- [ ] **Step 10.1: Failing test yaz**

```python
# tests/test_reel_overlay_question.py
"""Açık soru çipi: hook'un açtığı merak sorusu ekranda asılı kalır,
reveal anında 'cevaplandı'ya döner (merak mimarisi, spec 2026-07-16)."""
from short_bot.reel_models import ReelBeat, ReelNarration, TimedWord, build_reel_timeline
from short_bot.reel_render import build_reel_overlay_html


def _tl():
    n = ReelNarration(
        hook="Bu tip neden herkesi korkutuyor?",
        beats=[ReelBeat(text="Beat bir cumlesi burada", visual_query="q0", keyword="A"),
               ReelBeat(text="Beat iki cumlesi burada", visual_query="q1", keyword="B"),
               ReelBeat(text="Beat uc cumlesi burada", visual_query="q2", keyword="C")],
        close="Kapanis cumlesi korkutuyor iste", mood="upbeat")
    words = n.full_text().split()
    asr = [TimedWord(word=w, start_s=i * .4, end_s=i * .4 + .35, seg=-1)
           for i, w in enumerate(words)]
    return build_reel_timeline(n, asr, duration_s=len(words) * .4)


def test_soru_verilince_cip_render_edilir():
    html = build_reel_overlay_html(_tl(), question_text="Neden herkes korkuyor?",
                                   reveal_at_s=12.0)
    assert 'id="qchip"' in html
    assert "Neden herkes korkuyor?" in html
    assert "QREVEAL=12.000" in html or "12.000" in html


def test_soru_yoksa_cip_DOM_da_yok():
    html = build_reel_overlay_html(_tl())
    assert 'id="qchip"' not in html


def test_cip_kare_dedup_imzasina_dahil():
    html = build_reel_overlay_html(_tl(), question_text="Soru?", reveal_at_s=8.0)
    i = html.index("window.__sig")
    assert "QCHIP" in html[i:]        # imza çipin durumunu içeriyor
```

- [ ] **Step 10.2: Testi koş** — FAIL. **Step 10.3: Implement**

`reel_render.py` — `build_reel_overlay_html` imzasına (badge'in yanına):

```python
    question_text: str = "",       # açık-soru çipi metni ("" = çip yok)
    reveal_at_s: float | None = None,   # cevabın ödendiği saniye (çip ✓'ya döner)
```

`tpl.render(...)` çağrısına:

```python
        question_text=(question_text or "").strip()[:48],
        reveal_at=f"{(reveal_at_s or 0.0):.3f}",
```

`templates/reel_overlay.html.j2`:

CSS ("beğeni/abone çipleri kaldırıldı" yorumunun olduğu boş banda — y ~1060):

```css
/* AÇIK SORU ÇİPİ (merak mimarisi): hook'un açtığı soru asılı kalır, reveal
   anında 'cevaplandı'ya döner. Eski cta bandında (y ~1060-1120, boşalmıştı). */
#qchip{position:absolute;bottom:810px;left:50%;transform:translateX(-50%);
  background:rgba(0,0,0,.72);color:#fff;font-weight:800;font-size:34px;
  padding:10px 26px;border-radius:999px;white-space:nowrap;display:none;
  max-width:960px;overflow:hidden;border:3px solid {{ highlight_color }}}
#qchip.on{display:block}
#qchip.done{background:{{ highlight_color }};color:{{ chip_text }};
  border-color:rgba(0,0,0,.4)}
```

Markup (handle satırının yanına):

```html
{% if question_text %}<div id="qchip">🤔 {{ question_text }}</div>{% endif %}
```

JS — sabitler (`const LEAD=...` satırının yanına):

```js
const QREVEAL={{ reveal_at }};
const QCHIP=document.getElementById('qchip');
```

`__seek` içine (BADGE toggle'ının yanına):

```js
  if(QCHIP){
    // 1.2sn'de belirir (hook pop'u ezmesin), reveal+2.5sn'de kaybolur.
    QCHIP.classList.toggle('on', t>=1.2 && t<QREVEAL+2.5);
    QCHIP.classList.toggle('done', QREVEAL>0 && t>=QREVEAL);   // ✓ cevaplandı
  }
```

`__sig` içine (BADGE imza satırının yanına):

```js
  s+='|'+(QCHIP?QCHIP.className:'');
```

- [ ] **Step 10.4: Testi koş** — `python -m pytest tests/test_reel_overlay_question.py tests/test_reel_badge.py tests/test_reel_safe_zone.py -q` → PASS (safe-zone: çip y 1060-1120 bandında, izin verilen 90-1440 içinde)

- [ ] **Step 10.5: Commit**

```bash
git add templates/reel_overlay.html.j2 src/short_bot/reel_render.py
git add -f tests/test_reel_overlay_question.py
git commit -m "feat(curiosity): acik soru cipi — soru asili kalir, reveal aninda cevaplandi'ya doner"
```

---

### Task 11: Reveal korkuluğu + render kablolaması (produce içinde)

**Files:**
- Modify: `src/short_bot/reel.py` (peak hesabından sonra, render çağrısından önce)
- Test: `tests/test_reel_footage_driven.py`

- [ ] **Step 11.1: Failing test yaz** (`tests/test_reel_footage_driven.py` sonuna)

```python
def test_soru_cipi_render_cagrisina_gecer_ve_reveal_klipten_hesaplanir(tmp_path, monkeypatch):
    import short_bot.reel as R
    monkeypatch.setattr(R, "_describe_clip", lambda c, **k: f"a chimpanzee {c.name}")
    calls = []
    deps = _fd_deps(calls, tmp_path)

    def fake_curious(topic, descs, queries, **kw):
        n = _fd_narr()
        # merak alanlarını doldur (pydantic copy — frozen değil)
        n2 = n.model_copy(update={"open_question": "Kim kazanacak dersin?",
                                  "reveal_beat": 2, "peak_beat": 1})
        return n2, [0, 1, 2]

    rec = {}
    deps = replace(deps, write_curious_narration=fake_curious,
                   render_reel_overlay_frames=lambda tl, out, **kw: (
                       rec.update(kw), 900)[1])
    produce_reel_video(
        topic="şempanze", channel=_FDChannel(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg",
        vision_call=object(), deps=deps)
    assert rec["question_text"] == "Kim kazanacak dersin?"
    assert rec["reveal_at_s"] and rec["reveal_at_s"] > 0


def test_reveal_beat_sifir_kelepcelenir(tmp_path, monkeypatch):
    # reveal_beat=0 → payoff hook klibiyle aynı → sızıntı. peak_beat'e (>=1) itilir.
    import short_bot.reel as R
    monkeypatch.setattr(R, "_describe_clip", lambda c, **k: f"a chimpanzee {c.name}")
    calls = []

    def fake_curious(topic, descs, queries, **kw):
        n = _fd_narr().model_copy(update={"open_question": "Soru bu mu?",
                                          "reveal_beat": 0, "peak_beat": 0})
        return n, [0, 1, 2]

    rec = {}
    deps = replace(_fd_deps(calls, tmp_path), write_curious_narration=fake_curious,
                   render_reel_overlay_frames=lambda tl, out, **kw: (
                       rec.update(kw), 900)[1])
    produce_reel_video(
        topic="şempanze", channel=_FDChannel(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg",
        vision_call=object(), deps=deps)
    # reveal segmenti en az beat 1 (segment 2) → reveal_at_s hook'tan sonra
    assert rec["reveal_at_s"] > 0
```

- [ ] **Step 11.2: Testi koş** — FAIL. **Step 11.3: Implement** (`reel.py`, peak hesabının olduğu blokta)

```python
    # AÇIK SORU ÇİPİ + REVEAL KORKULUĞU (merak mimarisi). reveal_beat=0 sızıntıdır
    # (payoff hook klibiyle aynı) → en az 1'e, yoksa peak_beat'e itilir.
    _question_text = ""
    _reveal_at_s = None
    if footage_driven and getattr(narration, "open_question", "").strip():
        rb = narration.reveal_beat if narration.reveal_beat >= 0 else narration.peak_beat
        rb = max(1, min(rb, len(narration.beats) - 1))
        reveal_seg = rb + 1                      # segment 0 = hook
        if 0 <= reveal_seg < len(timeline.seg_spans):
            _question_text = narration.open_question
            _reveal_at_s = timeline.seg_spans[reveal_seg][0]
            log.info(f"  merak: soru çipi '{_question_text}' → reveal @ "
                     f"{_reveal_at_s:.1f}s (beat {rb})")
```

Render çağrısına (badge'in yanına):

```python
        question_text=_question_text,
        reveal_at_s=_reveal_at_s,
```

- [ ] **Step 11.4: Testi koş** — `python -m pytest tests/test_reel_footage_driven.py -q` → PASS

- [ ] **Step 11.5: Commit**

```bash
git add src/short_bot/reel.py
git add -f tests/test_reel_footage_driven.py
git commit -m "feat(curiosity): soru cipi render kablolamasi + reveal_beat=0 sizinti korkulugu"
```

---

### Task 12: Regresyon + gerçek üretim doğrulaması

- [ ] **Step 12.1: Geniş regresyon**

Run: `python -m pytest tests/test_reel_curiosity.py tests/test_reel_models.py tests/test_footage_driven.py tests/test_reel_footage_driven.py tests/test_footage_discovery.py tests/test_config_reel.py tests/test_reel_pacing_density.py tests/test_reel_overlay_question.py tests/test_reel_badge.py tests/test_web_reel_edit.py -q`
Expected: hepsi PASS.

Sonra ağır süit: `python -m pytest tests/test_reel.py -q` → 24+ PASS (motor akışı byte-identical kanıtı; curiosity kapalıyken).

- [ ] **Step 12.2: Gerçek üretim** (cron pencerelerinden kaçın — :29 civarı BAŞLATMA)

Scratchpad'deki `kesif_kosu.py` deseniyle mahalle-vahsisi koşusu. Log'da doğrula:
- `merak[yargıç]: kazanan aday N (puanlar=...)` satırı var
- `merak: soru çipi '...' → reveal @ Xs` satırı var

- [ ] **Step 12.3: Kare doğrulaması**

`ffmpeg -i <video> -vf "fps=1,scale=110:-1,tile=9x8" frames.png` → görsel kontrol:
- Soru çipi hook'tan itibaren görünüyor, reveal anında renk değiştiriyor, sonra kayboluyor
- Payoff klibi hook'ta GÖRÜNMÜYOR
- `freezedetect` → donma yok
- Senaryoda beat-sonu kancaları kulakla/okumayla hissediliyor

- [ ] **Step 12.4: Bellek güncelle + son commit**

`vahsi-mizah-persona.md` hafızasına merak mimarisi bölümü ekle (commit hash'leriyle); kalan pürüzler varsa "Diğer açık" listesine yaz.

---

## Self-review notları

- Spec kapsama: iskelet+rubrik (T1), şema (T2), adaylar/yargıç/doktor (T4-6), orkestratör+fail-open (T7), bayrak+kablo (T8), tempo (T9), çip (T10), reveal korkuluğu (T11), üretim doğrulaması (T12). Araştırma T1-Step 0'da zaman kutulu.
- Tip tutarlılığı: `write_curious_narration` → `(ReelNarration, list[int])`; ReelDeps girişi `write_curious_narration`; testlerde `dataclasses.replace` ile enjeksiyon.
- `FDDraftNarration` merak alanlarını `ReelNarration`'dan miras alır (T2 alanları ReelNarration'a eklendiği için FDDraft otomatik kapsar).
