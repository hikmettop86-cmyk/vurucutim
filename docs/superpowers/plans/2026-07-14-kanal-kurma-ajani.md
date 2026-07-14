# Kanal Kurma Ajanı — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kullanıcı bir cümle söylesin ("Almanca bira bahçesi kanalı"), sistem kanalı kursun.

**Architecture:** Ajan bir ORKESTRATÖR — niş bulucu, dil paketi, DNA, konu bankası zaten var. Tek gerçek yeni parça **ses seçimi** (hedef dilde konuşan anlatıcı). `build_plan` hiçbir dosya yazmaz; kullanıcı planı (niş + kanıt, isim, ses ve NEDEN, kimlik, 3 gerçek örnek konu) görüp "Kur"a basar, `apply_plan` yazar.

**Tech Stack:** Python 3.14, pydantic v2, Flask + HTMX, pytest, ai33 `/v3/voices`, Sonnet 5 (Claude CLI → OpenRouter).

**Spec:** `docs/superpowers/specs/2026-07-14-kanal-kurma-ajani-design.md`

**Dal:** `feature/electron-installer`. YAYINLANMAYACAK.

---

## Değişmez kurallar

1. Her görevin sonunda `python -m pytest tests/ -q` koşar ve HEPSİ geçer (şu an 2201).
2. `tests/` gitignore'da → `git add -f tests/<dosya>`. `docs/superpowers/` de öyle.
3. **Sessiz düşme yasak.** Hedef dilde ses yoksa `RuntimeError` — İngilizce sese düşmek YASAK.
4. **Uydurma kanıt yasak.** YouTube ölçümü yoksa `evidence=""`; panel "kanıt yok" der.
5. Commit mesajını dosyaya yazıp `git commit -F <dosya>` (PowerShell here-string kesme işaretinde kırılıyor).

---

## Dosya haritası

| Dosya | Sorumluluk | Durum |
|---|---|---|
| `src/short_bot/voice_picker.py` | Hedef dilde ses listesi + LLM ile anlatıcı seçimi | **YENİ** |
| `src/short_bot/channel_agent.py` | `ChannelPlan` + `build_plan` (yazmaz) + `apply_plan` (yazar) | **YENİ** |
| `src/short_bot/web/routes/channel_agent.py` | `/channels/agent` rotaları (iş kuyruğu + HTMX poll) | **YENİ** |
| `src/short_bot/web/templates/channel_agent.html.j2` | Giriş + niş kartları + plan ekranı | **YENİ** |
| `src/short_bot/web/routes/__init__.py` | Blueprint kaydı | Değişir |
| `src/short_bot/web/templates/base.html.j2` | Menüye "Ajan" linki | Değişir |

---

## Task 1: Ses seçici

**Files:**
- Create: `src/short_bot/voice_picker.py`
- Test: `tests/test_voice_picker.py` (yeni)

- [ ] **Step 1: Testi yaz**

`tests/test_voice_picker.py`:

```python
"""Hedef dilde konuşan ANLATICI sesi seç.

ÖLÇÜLDÜ (ai33 /v3/voices, 5 sayfa): 605 ses.
    en=365  hi=38  es=34  vi=22  pt=20  de=18  ko=15  fr=15  ja=12  it=10  tr=8

İki şey kritik:
  • SAYFALAMA ŞART. Varsayılan sayfa çoğunlukla İngilizce; Almanca sesler ileriki
    sayfalarda. İlk sayfada durursan "Almanca ses yok" dersin — ama var.
  • SEÇİM ÖNEMSİZ DEĞİL. Almanca seslerden biri "Mark - Sales Executive", biri
    "Daniel - Teacher, explainer-in-chief". Faceless ilginç-bilgi kanalına ikincisi
    uyar; "ilk erkek sesi al" kuralı bunu bilemez.
"""
import pytest

from short_bot.voice_picker import VoiceChoice, pick_voice, voices_for

DE = [
    {"voice_id": "elevenlabs_a", "name": "Mark - Sales Executive",
     "description": "Energetic sales pitch voice", "language": "de",
     "gender": "male", "accent": "german"},
    {"voice_id": "elevenlabs_b", "name": "Daniel - Teacher, explainer-in-chief",
     "description": "Calm narrator, explains complex topics clearly", "language": "de",
     "gender": "male", "accent": "german"},
]
EN = [{"voice_id": "elevenlabs_x", "name": "Bella", "description": "warm",
       "language": "en", "gender": "female", "accent": "american"}]


def _sayfali(sayfalar):
    """Sahte ai33 list_voices: sayfa sayfa döndürür, sonra boş."""
    def _f(*, api_key, provider="elevenlabs", search="", page=1, page_size=100,
           session=None, base_url=None):
        return sayfalar[page - 1] if page <= len(sayfalar) else []
    return _f


# --- LİSTELEME -------------------------------------------------------------

def test_HEDEF_DILDEKI_sesler_donerr(monkeypatch):
    import short_bot.voice_picker as VP
    monkeypatch.setattr(VP, "list_voices", _sayfali([EN + DE]))
    out = voices_for("de", api_key="K")
    assert [v["voice_id"] for v in out] == ["elevenlabs_a", "elevenlabs_b"]


def test_SAYFALAMA_ilk_sayfada_DURMAZ(monkeypatch):
    """GERÇEK TUZAK: 605 ses var ve ilk sayfa çoğunlukla İngilizce. İlk sayfada
    durursan 'Almanca ses yok' dersin — ama var."""
    import short_bot.voice_picker as VP
    monkeypatch.setattr(VP, "list_voices", _sayfali([EN, EN, DE]))
    out = voices_for("de", api_key="K")
    assert len(out) == 2, "sayfalama yapılmadı → Almanca sesler kaçtı"


def test_SES_YOKSA_hata_INGILIZCEYE_DUSMEZ(monkeypatch):
    """SESSİZ BOZULMA YASAĞI: Almanca kanal İngiliz aksanıyla okur ve bunu hiçbir şey
    söylemez. Kanalı bozuk kurmaktansa kurmamak yeğdir."""
    import short_bot.voice_picker as VP
    monkeypatch.setattr(VP, "list_voices", _sayfali([EN]))
    with pytest.raises(RuntimeError, match="ses"):
        voices_for("de", api_key="K")


def test_API_ANAHTARI_YOKSA_hata():
    with pytest.raises(RuntimeError, match="ai33"):
        voices_for("de", api_key="")


# --- SEÇİM -----------------------------------------------------------------

def _llm(voice_id, reason="anlatıcı tonu"):
    def _f(prompt, schema, **kw):
        _f.prompt = prompt
        return schema.model_validate({"voice_id": voice_id, "reason": reason})
    _f.prompt = ""
    return _f


def test_LLM_nise_uygun_ANLATICIYI_secer():
    llm = _llm("elevenlabs_b", "açıklayıcı anlatıcı, bilgi formatına uyar")
    c = pick_voice("de", "bira bahçesi kültürü", voices=DE, llm=llm)
    assert isinstance(c, VoiceChoice)
    assert c.voice_id == "elevenlabs_b"
    assert c.name.startswith("Daniel")
    assert "anlatıcı" in c.reason


def test_ses_ACIKLAMALARI_PROMPTA_girer():
    """Model 'Sales Executive' ile 'Teacher'ı ayırt edebilmeli."""
    llm = _llm("elevenlabs_b")
    pick_voice("de", "bira", voices=DE, llm=llm)
    p = llm.prompt
    assert "Sales Executive" in p and "Teacher" in p
    assert "ANLATICI" in p          # ne aradığımızı söylüyoruz


def test_LLM_YOKSA_ilk_ses_DURUST_gerekce():
    """Ses seçimi kanalı BOZMAZ, yalnız iyileştirir — burada durmaya gerek yok."""
    c = pick_voice("de", "bira", voices=DE, llm=None)
    assert c.voice_id == "elevenlabs_a"
    assert "seçemedi" in c.reason


def test_LLM_UYDURMA_id_verirse_ilk_ses():
    """Model listede olmayan bir voice_id uydurabilir — kabul etmeyiz."""
    c = pick_voice("de", "bira", voices=DE, llm=_llm("elevenlabs_UYDURMA"))
    assert c.voice_id == "elevenlabs_a"
    assert "listede yok" in c.reason


def test_LLM_PATLARSA_ilk_ses():
    def _patla(*a, **kw):
        raise RuntimeError("sonnet yok")
    c = pick_voice("de", "bira", voices=DE, llm=_patla)
    assert c.voice_id == "elevenlabs_a"


def test_BOS_ses_listesi_hata():
    with pytest.raises(RuntimeError):
        pick_voice("de", "bira", voices=[], llm=None)
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_voice_picker.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'short_bot.voice_picker'`

- [ ] **Step 3: `voice_picker.py`'yi yaz**

```python
"""Hedef dilde konuşan ANLATICI sesi seç.

ÖLÇÜLDÜ (ai33 /v3/voices): 605 ses.
    en=365  hi=38  es=34  vi=22  pt=20  de=18  ko=15  fr=15  ja=12  it=10  tr=8

SAYFALAMA ŞART: varsayılan sayfa çoğunlukla İngilizce; Almanca sesler ileriki
sayfalarda. İlk sayfada durursan "Almanca ses yok" dersin — ama var.

SEÇİM ÖNEMSİZ DEĞİL: Almanca seslerden biri "Mark - Sales Executive", biri
"Daniel - Teacher, explainer-in-chief". Faceless ilginç-bilgi kanalına ikincisi uyar;
"ilk erkek sesi al" kuralı bunu bilemez. O yüzden seçimi LLM yapar.

HEDEF DİLDE SES YOKSA RuntimeError. İngilizce sese sessizce düşmek YASAK: Almanca
kanal İngiliz aksanıyla okur ve bunu hiçbir şey söylemez.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

from short_bot.locale import LANGUAGE_NAMES
from short_bot.tts.ai33_client import list_voices

log = logging.getLogger(__name__)

_MAX_PAGES = 8       # 8 × 100 = 800 ses; kütüphane bugün 605
_PAGE_SIZE = 100


class VoiceChoice(BaseModel):
    voice_id: str
    name: str
    reason: str      # NEDEN bu ses — kullanıcı planda görecek


def voices_for(language: str, *, api_key: str, session=None) -> list[dict]:
    """ai33 kütüphanesinden HEDEF DİLDE konuşan sesler.

    Hedef dilde ses yoksa RuntimeError — İngilizceye DÜŞMEZ.
    """
    if not api_key:
        raise RuntimeError("ai33 API anahtarı yok — Ayarlar'dan ekleyin "
                           "(ses olmadan reel kanalı kurulamaz).")

    hepsi: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        sayfa = list_voices(api_key=api_key, provider="elevenlabs",
                            page=page, page_size=_PAGE_SIZE, session=session)
        if not sayfa:
            break
        hepsi.extend(sayfa)

    out = [v for v in hepsi
           if str(v.get("language") or "").lower() == language.lower()]
    if not out:
        ad = LANGUAGE_NAMES.get(language, language)
        raise RuntimeError(
            f"ai33 kütüphanesinde {ad} konuşan ses bulunamadı ({len(hepsi)} ses "
            f"tarandı). İngilizce bir sese düşmüyoruz — {ad} kanal İngiliz aksanıyla "
            f"okur ve bunu hiçbir şey söylemez. Sesi elle seçin.")
    log.info(f"[ses] {len(hepsi)} sesten {len(out)} tanesi {language}")
    return out


class _Pick(BaseModel):
    voice_id: str
    reason: str = ""


def _prompt(language: str, niche: str, voices: list[dict]) -> str:
    ad = LANGUAGE_NAMES.get(language, language)
    liste = "\n".join(
        f'- {v["voice_id"]} | {v.get("name", "")} | {v.get("gender", "")} | '
        f'{v.get("accent", "")} | {(v.get("description") or "")[:160]}'
        for v in voices)
    return f"""Bir YouTube Shorts kanalı için ANLATICI sesi seç.

KANALIN NİŞİ: {niche}
DİL: {ad}
FORMAT: 40 saniyelik faceless "ilginç bilgi" shorts — stok görüntü + seslendirme.
İzleyici yüzü görmez; SES kanalın kimliğidir.

NE ARIYORUZ: net, güven veren, MERAK UYANDIRAN bir ANLATICI. Konuyu açıklayan, hikâye
anlatan bir ton. Satış/reklam tonu, aşırı enerjik sunucu tonu ya da yapay/robotik ses
UYMAZ — izleyici 3 saniyede kaydırır.

SESLER (voice_id | ad | cinsiyet | aksan | açıklama):
{liste}

SADECE JSON: {{"voice_id": "<listeden BİREBİR bir voice_id>",
  "reason": "<{ad} değil, TÜRKÇE tek cümle: neden bu ses>"}}"""


def pick_voice(language: str, niche: str, *, voices: list[dict], llm) -> VoiceChoice:
    """Nişe en uygun ANLATICI sesi. LLM yoksa/patlarsa ilk ses + DÜRÜST gerekçe.

    Ses seçimi kanalı BOZMAZ, yalnız iyileştirir — burada durmaya gerek yok.
    (Hedef dilde ses OLMAMASI ise bozar; onu voices_for RuntimeError ile yakalıyor.)
    """
    if not voices:
        raise RuntimeError("ses listesi boş — seçilecek ses yok")

    ilk = voices[0]

    def _fallback(sebep: str) -> VoiceChoice:
        return VoiceChoice(voice_id=ilk["voice_id"],
                           name=str(ilk.get("name") or ilk["voice_id"]),
                           reason=sebep)

    if llm is None:
        return _fallback("model seçemedi (LLM yok) — listedeki ilk uygun ses")

    try:
        p = llm(_prompt(language, niche, voices), _Pick)
    except Exception as e:   # noqa: BLE001 — ses seçimi kanalı bozmaz
        log.warning(f"[ses] seçim başarısız ({e}) → ilk uygun ses")
        return _fallback(f"model seçemedi ({e}) — listedeki ilk uygun ses")

    esles = {v["voice_id"]: v for v in voices}
    v = esles.get((p.voice_id or "").strip())
    if v is None:
        # Model uydurma id verdi — kabul etmeyiz.
        log.warning(f"[ses] model listede olmayan id verdi ({p.voice_id!r}) → ilk ses")
        return _fallback("model listede yok bir ses önerdi — listedeki ilk uygun ses")

    return VoiceChoice(voice_id=v["voice_id"],
                       name=str(v.get("name") or v["voice_id"]),
                       reason=(p.reason or "").strip() or "modelin seçimi")
```

- [ ] **Step 4: Testi koş**

Run: `python -m pytest tests/test_voice_picker.py -q`
Expected: PASS (10 test)

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/voice_picker.py
git add -f tests/test_voice_picker.py
git commit -m "feat(agent): ses secici - hedef dilde konusan anlaticiyi LLM secer"
```

---

## Task 2: Kanal planı — `build_plan`

**Files:**
- Create: `src/short_bot/channel_agent.py`
- Test: `tests/test_channel_agent.py` (yeni)

- [ ] **Step 1: Testi yaz**

`tests/test_channel_agent.py`:

```python
"""Kanal planı: kullanıcı GÖRMEDEN hiçbir şey yazılmaz.

build_plan HİÇBİR DOSYA YAZMAZ (dil paketi hariç — o dile ait, kanala değil).
Kullanıcı planı görüp "Kur"a basar; apply_plan yazar.
"""
import pytest

from short_bot.channel_agent import ChannelPlan, apply_plan, build_plan


class _Settings:
    claude_cli_path = "claude"
    openrouter_models = {"script": "anthropic/claude-sonnet-5", "dna": "opus"}
    ai_backend = "openrouter"
    claude_models = {"dna": "opus", "default": "haiku"}


def _llm(**cevaplar):
    """Sahte Sonnet: şemaya göre farklı cevap döndürür."""
    def _f(prompt, schema, **kw):
        ad = schema.__name__
        if ad == "_Pick":                     # voice_picker
            return schema.model_validate(cevaplar.get("voice", {
                "voice_id": "elevenlabs_de1", "reason": "anlatıcı tonu"}))
        if ad == "_Name":                     # kanal adı
            return schema.model_validate(cevaplar.get("name", {"name": "Bierwissen"}))
        if ad == "_Verdicts":
            n = len(cevaplar.get("topics", {}).get("topics", []))
            return schema.model_validate({"verdicts": [
                {"index": i, "solid": True} for i in range(n)]})
        if ad == "_Proposed":
            return schema.model_validate(cevaplar.get("topics", {"topics": [
                {"topic": "Bier braucht neun Monate im Keller", "source_title": "",
                 "views": 0, "subs": 0, "hook_pattern": ""}]}))
        raise AssertionError(f"beklenmeyen şema: {ad}")
    return _f


DE_VOICES = [{"voice_id": "elevenlabs_de1", "name": "Daniel - Teacher",
              "description": "calm narrator", "language": "de", "gender": "male",
              "accent": "german"}]


@pytest.fixture
def _sahte(monkeypatch, tmp_path):
    """Dış dünyayı kes: ses listesi, DNA."""
    import short_bot.channel_agent as CA
    from short_bot.dna import DnaSpec

    monkeypatch.setattr(CA, "voices_for", lambda lang, **kw: DE_VOICES)
    monkeypatch.setattr(CA, "generate_dna", lambda **kw: DnaSpec(archetype="stat-hero"))
    return tmp_path


def test_plan_TUM_ALANLARI_doldurur(_sahte):
    p = build_plan("bira bahcesi kulturu ve bira uretimi", language="de",
                   channels_dir=_sahte, ai33_key="K", settings=_Settings(),
                   secrets={}, llm=_llm(), evidence="8 outlier; en iyi 175x")
    assert isinstance(p, ChannelPlan)
    assert p.language == "de"
    assert p.name == "Bierwissen"
    assert p.slug == "bierwissen"
    assert p.voice.voice_id == "elevenlabs_de1"
    assert p.voice.reason                      # NEDEN mutlaka dolu
    assert p.dna.archetype == "stat-hero"
    assert p.evidence == "8 outlier; en iyi 175x"
    assert p.sample_topics == ["Bier braucht neun Monate im Keller"]


def test_plan_HICBIR_DOSYA_YAZMAZ(_sahte):
    build_plan("bira", language="de", channels_dir=_sahte, ai33_key="K",
               settings=_Settings(), secrets={}, llm=_llm())
    assert list(_sahte.glob("*.yaml")) == [], "build_plan kanal YAML'ı yazdı"


def test_KANIT_YOKSA_UYDURMAZ(_sahte):
    """YouTube ölçümü yoksa evidence BOŞ kalır — panel 'kanıt yok' der."""
    p = build_plan("bira", language="de", channels_dir=_sahte, ai33_key="K",
                   settings=_Settings(), secrets={}, llm=_llm())
    assert p.evidence == ""


def test_SLUG_cakismasi_cozulur(_sahte):
    (_sahte / "bierwissen.yaml").write_text("x", encoding="utf-8")
    p = build_plan("bira", language="de", channels_dir=_sahte, ai33_key="K",
                   settings=_Settings(), secrets={}, llm=_llm())
    assert p.slug == "bierwissen-2"


def test_ORNEK_KONULAR_DOGRULAMA_kapisindan_gecer(_sahte):
    """Planda gösterilen konular GERÇEK — propose + verify'den geçmiş."""
    llm = _llm(topics={"topics": [
        {"topic": "Saglam konu bir", "source_title": "", "views": 0, "subs": 0,
         "hook_pattern": ""},
        {"topic": "Saglam konu iki", "source_title": "", "views": 0, "subs": 0,
         "hook_pattern": ""}]})
    p = build_plan("bira", language="de", channels_dir=_sahte, ai33_key="K",
                   settings=_Settings(), secrets={}, llm=llm)
    assert p.sample_topics == ["Saglam konu bir", "Saglam konu iki"]


def test_ORNEK_KONU_URETILEMEZSE_plan_YINE_kurulur(_sahte, monkeypatch):
    """Konu üretimi patlarsa kanal yine kurulabilmeli — banka sonra dolar."""
    import short_bot.channel_agent as CA

    def _patla(*a, **kw):
        raise RuntimeError("sonnet yok")

    monkeypatch.setattr(CA, "propose_topics", _patla)
    p = build_plan("bira", language="de", channels_dir=_sahte, ai33_key="K",
                   settings=_Settings(), secrets={}, llm=_llm())
    assert p.sample_topics == []
    assert p.slug                              # plan yine kuruldu


def test_HEDEF_DILDE_SES_YOKSA_plan_KURULMAZ(_sahte, monkeypatch):
    """SESSİZ BOZULMA YASAĞI: kanalı bozuk kurmaktansa kurmamak yeğdir."""
    import short_bot.channel_agent as CA

    def _yok(lang, **kw):
        raise RuntimeError("Almanca konuşan ses bulunamadı")

    monkeypatch.setattr(CA, "voices_for", _yok)
    with pytest.raises(RuntimeError, match="ses"):
        build_plan("bira", language="de", channels_dir=_sahte, ai33_key="K",
                   settings=_Settings(), secrets={}, llm=_llm())
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_channel_agent.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'short_bot.channel_agent'`

- [ ] **Step 3: `channel_agent.py`'yi yaz (build_plan kısmı)**

```python
"""Kanal kurma ajanı: bir cümleden çalışan bir kanala.

Ajan bir ORKESTRATÖRDÜR — niş bulucu, dil paketi, DNA ve konu bankası zaten var.
Tek gerçek yeni parça ses seçimi (voice_picker).

İKİ AŞAMA, ve ayrım kasıtlı:
    build_plan  → HİÇBİR ŞEY YAZMAZ. Kullanıcı planı görür.
    apply_plan  → YAML'ı yazar, konu bankasını tohumlar.

Neden: ajan yanlış ses seçer, ismi tutmaz ya da niş kaymışsa, kullanıcı bunu KANAL
KURULMADAN görmeli. Kurulmuş bir kanalı geri almak (YAML sil, banka temizle, CSS sil)
kullanıcının işi olmamalı.

DİL PAKETİ İSTİSNA: o dile aittir, kanala değil. build_plan onu üretir (yoksa) çünkü
paket olmadan planın "3 örnek konu"su bile hedef dilde doğrulanamaz — ve paket bir kez
üretilip her Almanca kanalda kullanılır.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel

from short_bot.dna import DnaSpec, generate_dna
from short_bot.lang_pack import load_pack
from short_bot.locale import LANGUAGE_NAMES
from short_bot.topic_propose import propose_topics, verify_topics
from short_bot.voice_picker import VoiceChoice, pick_voice, voices_for

log = logging.getLogger(__name__)

SAMPLE_TOPIC_COUNT = 3
DEFAULT_HIGHLIGHT = "#38bdf8"

# Türkçe harfleri slug'a çevirmek: unicodedata tek başına 'ı'yı düşürüyor.
_TR_MAP = str.maketrans({"ı": "i", "İ": "I", "ş": "s", "Ş": "S", "ğ": "g",
                         "Ğ": "G", "ç": "c", "Ç": "C", "ö": "o", "Ö": "O",
                         "ü": "u", "Ü": "U", "ß": "ss", "ä": "a", "Ä": "A"})


class ChannelPlan(BaseModel):
    language: str
    niche: str                    # generator.topic olacak
    evidence: str = ""            # YouTube ölçümü YOKSA BOŞ — uydurma kanıt yazmayız
    name: str
    slug: str
    voice: VoiceChoice
    dna: DnaSpec
    highlight_color: str = DEFAULT_HIGHLIGHT
    sample_topics: list[str] = []


class _Name(BaseModel):
    name: str


def _slugify(name: str) -> str:
    name = name.translate(_TR_MAP)
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return name or "channel"


def _unique_slug(base: str, channels_dir: Path) -> str:
    slug, n = base, 2
    while (Path(channels_dir) / f"{slug}.yaml").exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _pick_name(niche: str, language: str, llm) -> str:
    """Hedef dilde kısa, akılda kalır bir kanal adı."""
    if llm is None:
        return niche.split()[0][:24].title() or "Kanal"
    ad = LANGUAGE_NAMES.get(language, language)
    try:
        v = llm(f"""Bir YouTube Shorts kanalına AD ver.

NİŞ: {niche}
DİL: {ad}

KURALLAR:
- Ad {ad} dilinde olmalı (izleyici o dili konuşuyor).
- KISA: 1-3 kelime, en fazla 24 karakter.
- Akılda kalır, telaffuz edilebilir, nişi çağrıştırsın.
- "Shorts", "Channel", "Kanal" gibi jenerik kelimeler KULLANMA.

SADECE JSON: {{"name": "<ad>"}}""", _Name)
        ad_out = (v.name or "").strip()[:40]
        return ad_out or niche.split()[0][:24].title()
    except Exception as e:   # noqa: BLE001 — isim kanalı bozmaz
        log.warning(f"[ajan] isim üretilemedi ({e}) → nişten türetiliyor")
        return niche.split()[0][:24].title() or "Kanal"


def _ensure_lang_pack(language: str, *, settings, secrets) -> None:
    """Dil paketi yoksa ÜRET. Paket olmadan hedef dilde hiçbir şey doğru çalışmaz."""
    try:
        load_pack(language)
        return
    except RuntimeError:
        pass

    from short_bot.lang_pack import pack_path
    from short_bot.lang_pack_gen import generate_pack

    ad = LANGUAGE_NAMES.get(language, language)
    log.info(f"[ajan] {ad} dil paketi yok → üretiliyor (Sonnet 5)")
    pack = generate_pack(
        language,
        claude_path=getattr(settings, "claude_cli_path", "claude"),
        openrouter_model=getattr(settings, "openrouter_models", {}).get(
            "script", "anthropic/claude-sonnet-5"),
        openrouter_key=(secrets or {}).get("openrouter_api_key"))
    hedef = pack_path(language, user=True)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(pack.model_dump_json(indent=2) + "\n", encoding="utf-8")
    load_pack.cache_clear()
    log.info(f"[ajan] {ad} dil paketi üretildi → {hedef}")


def _sample_topics(niche: str, language: str, llm) -> list[str]:
    """3 GERÇEK konu: propose + doğrulama kapısı. Patlarsa boş liste (plan yine kurulur)."""
    try:
        onerilen = propose_topics(niche, language=language, evidence=[], existing=[],
                                  count=SAMPLE_TOPIC_COUNT, llm=llm)
        yargilar = verify_topics([t.topic for t in onerilen], language=language, llm=llm)
        return [t.topic for t, y in zip(onerilen, yargilar) if y.solid]
    except Exception as e:   # noqa: BLE001 — örnek konu kanalı bozmaz, banka sonra dolar
        log.warning(f"[ajan] örnek konu üretilemedi ({e}) → plan konusuz sunuluyor")
        return []


def build_plan(niche: str, *, language: str, channels_dir, ai33_key: str,
               settings, secrets: dict, llm=None, dna_call=None,
               evidence: str = "") -> ChannelPlan:
    """Kanal planı kur. HİÇBİR DOSYA YAZMAZ (dil paketi hariç — bkz. modül docstring'i).

    ``evidence``: niş bulucunun YouTube ölçümü. YOKSA BOŞ KALIR — uydurma kanıt yazmayız.
    """
    niche = (niche or "").strip()
    if len(niche) < 10:
        raise ValueError("niş en az 10 karakter olmalı")

    # 1) DİL PAKETİ — olmadan hedef dilde hiçbir şey doğru çalışmaz.
    _ensure_lang_pack(language, settings=settings, secrets=secrets)

    # 2) SES — hedef dilde ses YOKSA burada dururuz (İngilizceye DÜŞMEYİZ).
    voices = voices_for(language, api_key=ai33_key)
    voice = pick_voice(language, niche, voices=voices, llm=llm)

    # 3) İSİM + SLUG
    name = _pick_name(niche, language, llm)
    slug = _unique_slug(_slugify(name), channels_dir)

    # 4) KİMLİK (DNA) — kimlik olmadan kanal kurulmaz.
    if dna_call is None:
        from short_bot.config import resolve_ai_call
        dna_call = resolve_ai_call(settings, secrets or {}, "dna")
    dna = generate_dna(name=name, keywords=[], language=language,
                       topic_hint=niche, target_audience="",
                       claude_path=dna_call.claude_path, model=dna_call.model,
                       backend=dna_call.backend, api_key=dna_call.api_key)

    # 5) ÖRNEK KONULAR — gerçekten üretilir ve doğrulama kapısından geçer.
    ornek = _sample_topics(niche, language, llm)

    return ChannelPlan(language=language, niche=niche, evidence=evidence,
                       name=name, slug=slug, voice=voice, dna=dna,
                       sample_topics=ornek)
```

- [ ] **Step 4: Testi koş**

Run: `python -m pytest tests/test_channel_agent.py -q`
Expected: PASS (7 test — `apply_plan` testleri Task 3'te)

> **Uygulayıcıya not:** Test dosyası `apply_plan`'ı import ediyor ama Task 2'de o yok.
> Import'u Task 3'e kadar yorum satırı yap ya da `apply_plan`'ı Task 3'te ekle ve testi
> o zaman genişlet. **Basit yol:** Task 2'nin testinde `apply_plan` import'unu kaldır,
> Task 3'te geri ekle.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/channel_agent.py
git add -f tests/test_channel_agent.py
git commit -m "feat(agent): build_plan - kullanici gormeden hicbir sey yazilmaz"
```

---

## Task 3: `apply_plan` — kanalı kur

**Files:**
- Modify: `src/short_bot/channel_agent.py`
- Test: `tests/test_channel_agent.py` (genişletilir)

- [ ] **Step 1: Testi yaz**

`tests/test_channel_agent.py` sonuna:

```python
# --- apply_plan: PLANI GERÇEĞE ÇEVİR ---------------------------------------

def _plan(_sahte, llm=None):
    return build_plan("bira bahcesi kulturu", language="de", channels_dir=_sahte,
                      ai33_key="K", settings=_Settings(), secrets={},
                      llm=llm or _llm())


def test_apply_KANAL_YAMLINI_yazar(_sahte, tmp_path):
    from short_bot.config import load_channel
    p = _plan(_sahte)
    slug = apply_plan(p, channels_dir=_sahte, templates_dir=tmp_path / "t",
                      db_path=tmp_path / "db.sqlite", settings=_Settings(),
                      secrets={}, llm=_llm())
    assert slug == p.slug
    cfg = load_channel(_sahte / f"{slug}.yaml")
    assert cfg.language == "de"
    assert cfg.reel.voice_id == "elevenlabs_de1"
    assert cfg.generator.topic == "bira bahcesi kulturu"
    assert cfg.template == "stat-hero"
    assert cfg.enabled is True


def test_apply_AUTOPILOT_ACMAZ(_sahte, tmp_path):
    """YouTube'a otomatik yükleme BÜYÜK bir taahhüt — kullanıcı bilinçli açar."""
    from short_bot.config import load_channel
    p = _plan(_sahte)
    slug = apply_plan(p, channels_dir=_sahte, templates_dir=tmp_path / "t",
                      db_path=tmp_path / "db.sqlite", settings=_Settings(),
                      secrets={}, llm=_llm())
    cfg = load_channel(_sahte / f"{slug}.yaml")
    ap = getattr(cfg, "autopilot", None)
    assert ap is None or ap.enabled is False


def test_apply_SERIYI_KAPALI_kurar(_sahte, tmp_path):
    from short_bot.config import load_channel
    p = _plan(_sahte)
    slug = apply_plan(p, channels_dir=_sahte, templates_dir=tmp_path / "t",
                      db_path=tmp_path / "db.sqlite", settings=_Settings(),
                      secrets={}, llm=_llm())
    cfg = load_channel(_sahte / f"{slug}.yaml")
    assert cfg.reel.series_enabled is False


def test_apply_KONU_BANKASINI_tohumlar(_sahte, tmp_path, monkeypatch):
    import short_bot.channel_agent as CA
    cagri = {}

    def _fake_refresh(eng, slug, niche, **kw):
        cagri["slug"] = slug
        cagri["niche"] = niche
        cagri["llm"] = kw.get("llm")
        return {"added": 5, "skipped_dup": 0, "rejected": 0}

    monkeypatch.setattr(CA, "refresh_topic_bank", _fake_refresh)
    p = _plan(_sahte)
    apply_plan(p, channels_dir=_sahte, templates_dir=tmp_path / "t",
               db_path=tmp_path / "db.sqlite", settings=_Settings(),
               secrets={}, llm=_llm())
    assert cagri["slug"] == p.slug
    assert cagri["niche"] == "bira bahcesi kulturu"
    assert cagri["llm"] is not None, "banka SONNET ile tohumlanmalı"


def test_apply_BANKA_PATLASA_da_kanal_KURULUR(_sahte, tmp_path, monkeypatch):
    """Kanal YAML'ı yazıldıysa kanal VARDIR. Banka sonra dolar (autofill 4 saatte bir)."""
    import short_bot.channel_agent as CA

    def _patla(*a, **kw):
        raise RuntimeError("kota doldu")

    monkeypatch.setattr(CA, "refresh_topic_bank", _patla)
    p = _plan(_sahte)
    slug = apply_plan(p, channels_dir=_sahte, templates_dir=tmp_path / "t",
                      db_path=tmp_path / "db.sqlite", settings=_Settings(),
                      secrets={}, llm=_llm())
    assert (_sahte / f"{slug}.yaml").exists()


def test_apply_CSS_override_yazar(_sahte, tmp_path):
    """Arketip önizlemesi için (reel çıktısı kullanmaz ama sihirbazla parite)."""
    t = tmp_path / "t"
    p = _plan(_sahte)
    slug = apply_plan(p, channels_dir=_sahte, templates_dir=t,
                      db_path=tmp_path / "db.sqlite", settings=_Settings(),
                      secrets={}, llm=_llm())
    assert (t / "css" / f"{slug}.css").exists()
```

Ayrıca dosyanın başındaki import'a `apply_plan` geri eklenir.

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_channel_agent.py -q`
Expected: FAIL — `ImportError: cannot import name 'apply_plan'`

- [ ] **Step 3: `apply_plan`'ı ekle**

`src/short_bot/channel_agent.py` sonuna:

```python
from short_bot.topic_miner import refresh_topic_bank   # dosya başına taşınır


def apply_plan(plan: ChannelPlan, *, channels_dir, templates_dir, db_path,
               settings, secrets: dict, llm=None) -> str:
    """Planı gerçeğe çevir: YAML yaz + CSS yaz + konu bankasını tohumla. Slug döner.

    AUTOPILOT AÇILMAZ ve SERİ KAPALI kurulur (spec): YouTube'a otomatik yükleme büyük
    bir taahhüt, kullanıcı bilinçli açar.

    Konu bankası tohumlaması PATLASA DA kanal kurulmuş sayılır — YAML yazıldıysa kanal
    VARDIR ve banka 4 saatte bir kendini doldurur (topic_autofill).
    """
    from short_bot.config import (ChannelConfig, GeneratorConfig, ReelConfig,
                                  save_channel)
    from short_bot.db import init_db
    from short_bot.dna import build_css_override
    from short_bot.locale import RSS_LOCALES

    channels_dir = Path(channels_dir)
    channels_dir.mkdir(parents=True, exist_ok=True)

    reel = ReelConfig(
        enabled=True,
        voice_id=plan.voice.voice_id,
        highlight_color=plan.highlight_color,
        cta_enabled=True,
        comment_question=True,
        series_enabled=False,      # kullanıcı açar
    )

    cfg = ChannelConfig(
        slug=plan.slug, name=plan.name, keywords=[],
        rss_locale=RSS_LOCALES[plan.language],
        schedule_cron="0 10 * * *",
        duration_s=40, min_score=7.0, max_candidates_per_run=3,
        template=plan.dna.archetype,
        colors={"primary": plan.dna.palette.primary,
                "accent": plan.highlight_color,
                "bg_gradient": plan.dna.palette.bg_gradient},
        handle=f"@{plan.slug}", output_dir=f"output/{plan.slug}",
        enabled=True,
        cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language=plan.language, dna=plan.dna, script_model=None,
        content_source="generator",
        generator=GeneratorConfig(topic=plan.niche),
        reel=reel,
        # autopilot AÇILMAZ — spec.
    )
    save_channel(channels_dir / f"{plan.slug}.yaml", cfg)

    css = Path(templates_dir) / "css" / f"{plan.slug}.css"
    css.parent.mkdir(parents=True, exist_ok=True)
    css.write_text(build_css_override(plan.dna), encoding="utf-8")

    # KONU BANKASI TOHUMU — patlasa da kanal kurulmuş sayılır.
    try:
        from short_bot.yt_outliers import resolve_youtube_api_keys
        eng = init_db(db_path)
        res = refresh_topic_bank(eng, plan.slug, plan.niche, language=plan.language,
                                 api_keys=resolve_youtube_api_keys(secrets or {}),
                                 llm=llm)
        log.info(f"[ajan] {plan.slug}: banka tohumlandı (+{res['added']} konu)")
    except Exception as e:   # noqa: BLE001 — kanal VAR; banka 4 saatte bir dolar
        log.warning(f"[ajan] {plan.slug}: banka tohumlanamadı ({e}) — kanal yine "
                    f"kuruldu, otomatik doldurma birkaç saat içinde deneyecek")

    log.info(f"[ajan] kanal kuruldu: {plan.slug} ({plan.language})")
    return plan.slug
```

- [ ] **Step 4: Testi koş**

Run: `python -m pytest tests/test_channel_agent.py -q`
Expected: PASS (13 test)

- [ ] **Step 5: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/channel_agent.py
git add -f tests/test_channel_agent.py
git commit -m "feat(agent): apply_plan - kanali kur, bankayi tohumla (autopilot ACMAZ)"
```

---

## Task 4: Panel — `/channels/agent`

**Files:**
- Create: `src/short_bot/web/routes/channel_agent.py`
- Create: `src/short_bot/web/templates/channel_agent.html.j2`
- Modify: `src/short_bot/web/routes/__init__.py`, `src/short_bot/web/templates/base.html.j2`
- Test: `tests/test_web_channel_agent.py` (yeni)

- [ ] **Step 1: Testi yaz**

`tests/test_web_channel_agent.py`:

```python
"""Kanal kurma ajanı paneli.

Kullanıcı bir cümle yazar, ajan planı gösterir, kullanıcı "Kur"a basar.
Plan ekranı SES GEREKÇESİNİ göstermeli — yanlış ses kanal kurulmadan görülsün.
"""
import pytest

from short_bot.db import init_db
from short_bot.web import create_app


def _app(tmp_path):
    cfg = tmp_path / "config"
    (cfg / "channels").mkdir(parents=True, exist_ok=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8")
    db = tmp_path / "db.sqlite"
    init_db(db)
    app = create_app(config_dir=cfg, db_path=db, templates_dir=tmp_path / "t",
                     music_root=tmp_path, cache_dir=tmp_path, lock_dir=tmp_path,
                     logs_dir=tmp_path, output_root=tmp_path,
                     secrets_path=tmp_path / "s.yaml", scheduler=False)
    return app, cfg


def test_sayfa_acilir(tmp_path):
    a, _ = _app(tmp_path)
    body = a.test_client().get("/channels/agent").data.decode("utf-8")
    assert "Kanal Kurma Ajanı" in body
    assert "Deutsch" in body                 # dil seçici


def test_PLAN_ekrani_SES_GEREKCESINI_gosterir(tmp_path, monkeypatch):
    """Yanlış ses, kanal KURULMADAN görülmeli."""
    import short_bot.web.routes.channel_agent as CA
    from short_bot.channel_agent import ChannelPlan
    from short_bot.dna import DnaSpec
    from short_bot.voice_picker import VoiceChoice

    plan = ChannelPlan(
        language="de", niche="bira bahcesi kulturu", evidence="8 outlier; en iyi 175x",
        name="Bierwissen", slug="bierwissen",
        voice=VoiceChoice(voice_id="v1", name="Daniel - Teacher",
                          reason="açıklayıcı anlatıcı, bilgi formatına uyar"),
        dna=DnaSpec(archetype="stat-hero"),
        sample_topics=["Bier braucht neun Monate im Keller"])

    monkeypatch.setattr(CA, "build_plan", lambda *a, **kw: plan)
    monkeypatch.setattr(CA, "_start_thread", lambda fn: fn())

    c = a_client = _app(tmp_path)[0].test_client()
    r = a_client.post("/channels/agent/plan",
                      data={"niche": "bira bahcesi kulturu", "language": "de"},
                      follow_redirects=True)
    body = r.data.decode("utf-8")
    assert "Daniel - Teacher" in body
    assert "açıklayıcı anlatıcı" in body, "ses GEREKÇESİ gösterilmiyor"
    assert "Bierwissen" in body
    assert "8 outlier" in body
    assert "Bier braucht neun Monate" in body


def test_KANIT_YOKSA_panel_KANIT_YOK_der(tmp_path, monkeypatch):
    """Uydurma kanıt yazmayız; kullanıcı neye baktığını bilmeli."""
    import short_bot.web.routes.channel_agent as CA
    from short_bot.channel_agent import ChannelPlan
    from short_bot.dna import DnaSpec
    from short_bot.voice_picker import VoiceChoice

    plan = ChannelPlan(language="de", niche="bira bahcesi", evidence="",
                       name="X", slug="x",
                       voice=VoiceChoice(voice_id="v", name="V", reason="r"),
                       dna=DnaSpec(archetype="stat-hero"))
    monkeypatch.setattr(CA, "build_plan", lambda *a, **kw: plan)
    monkeypatch.setattr(CA, "_start_thread", lambda fn: fn())
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/plan",
                             data={"niche": "bira bahcesi", "language": "de"},
                             follow_redirects=True)
    assert "kanıt yok" in r.data.decode("utf-8").lower()


def test_KUR_kanali_olusturur(tmp_path, monkeypatch):
    import short_bot.web.routes.channel_agent as CA
    kuruldu = {}

    monkeypatch.setattr(CA, "apply_plan",
                        lambda plan, **kw: kuruldu.setdefault("slug", plan.slug))
    a, _ = _app(tmp_path)

    from short_bot.channel_agent import ChannelPlan
    from short_bot.dna import DnaSpec
    from short_bot.voice_picker import VoiceChoice
    plan = ChannelPlan(language="de", niche="bira bahcesi", evidence="",
                       name="Bierwissen", slug="bierwissen",
                       voice=VoiceChoice(voice_id="v", name="V", reason="r"),
                       dna=DnaSpec(archetype="stat-hero"))
    CA._PLANS["job1"] = plan          # iş kuyruğuna elle koy

    r = a.test_client().post("/channels/agent/apply/job1", follow_redirects=False)
    assert kuruldu["slug"] == "bierwissen"
    assert r.status_code in (302, 303)
    assert "/channels/bierwissen" in r.headers["Location"]


def test_BILINMEYEN_is_404(tmp_path):
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/apply/yok")
    assert r.status_code == 404


def test_KISA_nis_reddedilir(tmp_path):
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/plan",
                             data={"niche": "bira", "language": "de"},
                             follow_redirects=True)
    assert "10 karakter" in r.data.decode("utf-8")
```

> **Uygulayıcıya not:** `test_PLAN_ekrani_SES_GEREKCESINI_gosterir` içindeki
> `c = a_client = _app(tmp_path)[0].test_client()` satırı iki kez app kuruyor — sadeleştir:
> `a, _ = _app(tmp_path)` yap ve `a.test_client()` kullan. (Monkeypatch'ler modül
> düzeyinde olduğu için sıra fark etmez.)

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_web_channel_agent.py -q`
Expected: FAIL — 404

- [ ] **Step 3: Rotaları yaz**

`src/short_bot/web/routes/channel_agent.py`:

```python
"""Kanal kurma ajanı paneli: bir cümle → çalışan bir kanal.

İKİ AŞAMA (kasıtlı): plan HAZIRLANIR ve GÖSTERİLİR, kullanıcı "Kur"a basar.
Ajan yanlış ses seçtiyse ya da niş kaydıysa, kanal KURULMADAN görülür.

Plan hazırlamak ~2-3 dk sürüyor (dil paketi + ses + DNA + örnek konular) → daemon
thread + HTMX poll. Desen niche_finder'ın iş kuyruğundan alındı (reel_new.py).
"""
from __future__ import annotations

import logging
import threading
import uuid

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.channel_agent import apply_plan, build_plan
from short_bot.locale import LANGUAGE_NAMES, SUPPORTED_LANGUAGES

bp = Blueprint("channel_agent", __name__)
_LOG = logging.getLogger(__name__)

# Bellek-içi iş kuyruğu (niche_finder deseni). Panel tek kullanıcılı bir masaüstü
# uygulaması; kalıcı kuyruk gerekmiyor.
_JOBS: dict = {}
_PLANS: dict = {}
_LOCK = threading.Lock()


def _start_thread(fn) -> None:
    threading.Thread(target=fn, daemon=True).start()


def _set_job(job_id: str, **fields) -> None:
    with _LOCK:
        _JOBS.setdefault(job_id, {}).update(fields)


def _get_job(job_id: str):
    with _LOCK:
        j = _JOBS.get(job_id)
        return dict(j) if j else None


def _secrets() -> dict:
    import yaml
    try:
        sp = current_app.config["SHORTBOT_SECRETS_PATH"]
        return (yaml.safe_load(sp.read_text(encoding="utf-8"))
                if sp.exists() else {}) or {}
    except Exception:   # noqa: BLE001
        return {}


def _sonnet():
    from short_bot.llm_sonnet import sonnet_json
    settings = current_app.config["SHORTBOT_SETTINGS"]
    secrets = _secrets()

    def _f(prompt, schema, **kw):
        return sonnet_json(prompt, schema,
                           claude_path=settings.claude_cli_path,
                           openrouter_model=settings.openrouter_models.get(
                               "script", "anthropic/claude-sonnet-5"),
                           openrouter_key=secrets.get("openrouter_api_key"))
    return _f


@bp.get("/channels/agent")
def page():
    return render_template("channel_agent.html.j2",
                           languages=[(k, LANGUAGE_NAMES[k])
                                      for k in SUPPORTED_LANGUAGES],
                           plan=None, job_id=None)


@bp.post("/channels/agent/plan")
def plan():
    niche = (request.form.get("niche") or "").strip()
    language = (request.form.get("language") or "tr").strip()
    if language not in SUPPORTED_LANGUAGES:
        language = "tr"
    if len(niche) < 10:
        flash("Niş en az 10 karakter olmalı — ne hakkında kanal istediğini yaz.",
              "error")
        return redirect(url_for("channel_agent.page"))

    from short_bot.tts.ai33_client import resolve_ai33_api_key
    secrets = _secrets()
    settings = current_app.config["SHORTBOT_SETTINGS"]
    channels_dir = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels"
    ai33_key = resolve_ai33_api_key(secrets)
    evidence = (request.form.get("evidence") or "").strip()
    llm = _sonnet()

    job_id = uuid.uuid4().hex[:12]
    _set_job(job_id, status="running", error="")

    def _job():
        try:
            p = build_plan(niche, language=language, channels_dir=channels_dir,
                           ai33_key=ai33_key, settings=settings, secrets=secrets,
                           llm=llm, evidence=evidence)
            with _LOCK:
                _PLANS[job_id] = p
            _set_job(job_id, status="done")
        except Exception as e:   # noqa: BLE001 — kullanıcıya SEBEBİ söyle
            _LOG.warning(f"[ajan] plan kurulamadı: {e}")
            _set_job(job_id, status="error", error=str(e))

    _start_thread(_job)
    return redirect(url_for("channel_agent.status", job_id=job_id))


@bp.get("/channels/agent/status/<job_id>")
def status(job_id):
    job = _get_job(job_id)
    if job is None:
        abort(404)
    with _LOCK:
        p = _PLANS.get(job_id)
    return render_template("channel_agent.html.j2",
                           languages=[(k, LANGUAGE_NAMES[k])
                                      for k in SUPPORTED_LANGUAGES],
                           plan=p, job=job, job_id=job_id)


@bp.post("/channels/agent/apply/<job_id>")
def apply(job_id):
    with _LOCK:
        p = _PLANS.get(job_id)
    if p is None:
        abort(404)
    try:
        slug = apply_plan(
            p,
            channels_dir=current_app.config["SHORTBOT_CONFIG_DIR"] / "channels",
            templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
            db_path=current_app.config["SHORTBOT_DB_PATH"],
            settings=current_app.config["SHORTBOT_SETTINGS"],
            secrets=_secrets(), llm=_sonnet())
    except Exception as e:   # noqa: BLE001
        flash(f"Kanal kurulamadı: {e}", "error")
        return redirect(url_for("channel_agent.status", job_id=job_id))

    with _LOCK:
        _PLANS.pop(job_id, None)
        _JOBS.pop(job_id, None)
    flash(f"'{p.name}' kuruldu. Konu bankası tohumlandı; üretim için 'Şimdi üret'e "
          f"basabilirsin.", "success")
    return redirect(f"/channels/{slug}")
```

`web/routes/__init__.py`'ye blueprint kaydı eklenir (mevcut desene uyarak:
import listesine `channel_agent`, sonra `app.register_blueprint(channel_agent.bp)`).

- [ ] **Step 4: Şablonu yaz**

`src/short_bot/web/templates/channel_agent.html.j2` — mevcut sayfaların sıcak paletini
izler (`topic_bank.html.j2` referans). İçerik:

1. **Giriş formu** (plan yokken): metin alanı (`niche`, placeholder
   *"Almanca bira bahçesi kültürü ve bira üretiminin şaşırtıcı gerçekleri"*), dil
   seçici, "Planı hazırla" düğmesi. Altında not: *"Ajan nişi araştırır, dil paketini
   hazırlar, hedef dilde bir anlatıcı ses seçer, kanal kimliğini üretir ve 3 örnek konu
   yazar. Kanal ancak sen onaylayınca kurulur."*
2. **Bekleme** (`job.status == "running"`): `hx-get` ile 3 saniyede bir
   `/channels/agent/status/<job_id>` poll; "Plan hazırlanıyor… (~2-3 dk)".
3. **Hata** (`job.status == "error"`): kırmızı kutu, `job.error` aynen gösterilir.
4. **Plan** (`plan` doluysa): kartlar —
   - Niş + `{% if plan.evidence %}{{ plan.evidence }}{% else %}kanıt yok (YouTube ölçümü
     yapılmadı){% endif %}`
   - Kanal adı + slug
   - **Ses**: `{{ plan.voice.name }}` + `{{ plan.voice.reason }}` (gerekçe MUTLAKA
     görünür)
   - Kimlik: `{{ plan.dna.archetype }}` + palet renk kutuları
   - Örnek konular listesi (boşsa: *"örnek konu üretilemedi — banka kurulumdan sonra
     dolar"*)
   - **"Kur"** düğmesi → `POST /channels/agent/apply/{{ job_id }}` (onay diyaloğu:
     *"'{{ plan.name }}' kanalı kurulacak. Autopilot KAPALI gelir; yükleme yapmaz."*)

`base.html.j2` navigasyonuna `<a href="/channels/agent">Ajan</a>` eklenir
("Kanallar"ın yanına).

- [ ] **Step 5: Testleri koş**

Run: `python -m pytest tests/test_web_channel_agent.py -q`
Expected: PASS

- [ ] **Step 6: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 7: Commit**

```bash
git add src/short_bot/web/routes/channel_agent.py src/short_bot/web/templates/channel_agent.html.j2 src/short_bot/web/routes/__init__.py src/short_bot/web/templates/base.html.j2
git add -f tests/test_web_channel_agent.py
git commit -m "feat(agent): /channels/agent paneli - plan goster, sonra kur"
```

---

## Task 5: Niş bulucuyu ajana bağla

Kullanıcı **"bana niş bul"** derse: niş bulucu adaylar üretir (YouTube kanıtıyla ölçülmüş), kullanıcı seçer, plan o nişle kurulur.

**Files:**
- Modify: `src/short_bot/web/routes/channel_agent.py`
- Modify: `src/short_bot/web/templates/channel_agent.html.j2`
- Test: `tests/test_web_channel_agent.py` (genişletilir)

- [ ] **Step 1: Testi yaz**

`tests/test_web_channel_agent.py` sonuna:

```python
def test_NIS_BUL_adaylari_KANITLA_listeler(tmp_path, monkeypatch):
    """Kullanıcı 'bana niş bul' derse: adaylar YouTube kanıtıyla ÖLÇÜLMÜŞ gelir."""
    import short_bot.web.routes.channel_agent as CA
    monkeypatch.setattr(CA, "_start_thread", lambda fn: fn())
    monkeypatch.setattr(CA, "find_niches_data", lambda *a, **kw: [
        {"nis": "Bira kültürü", "neden": "Kanıt: 8 outlier; en iyi 175x",
         "konu_tohumu": "bira bahcesi kulturu ve bira uretiminin gercekleri",
         "kanit_puani": 210.0},
        {"nis": "Bahçecilik", "neden": "Kanıt: 3 outlier",
         "konu_tohumu": "bahcecilik ve bitki bakimi hakkinda ilginc gercekler",
         "kanit_puani": 40.0}])

    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/find",
                             data={"query": "almanya", "language": "de"},
                             follow_redirects=True)
    body = r.data.decode("utf-8")
    assert "Bira kültürü" in body
    assert "175x" in body
    assert "210" in body                    # kanıt puanı görünür
    # Aday seçildiğinde plan kurulacak: konu tohumu formda taşınmalı
    assert "bira bahcesi kulturu" in body


def test_NIS_BULUCU_PATLARSA_sebebi_soylenir(tmp_path, monkeypatch):
    import short_bot.web.routes.channel_agent as CA
    monkeypatch.setattr(CA, "_start_thread", lambda fn: fn())

    def _patla(*a, **kw):
        raise RuntimeError("YouTube API anahtari yok")

    monkeypatch.setattr(CA, "find_niches_data", _patla)
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/find",
                             data={"query": "almanya", "language": "de"},
                             follow_redirects=True)
    assert "YouTube API anahtari yok" in r.data.decode("utf-8")
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_web_channel_agent.py -q`
Expected: FAIL — 404 (`/channels/agent/find` yok)

- [ ] **Step 3: `/channels/agent/find` rotasını ekle**

`channel_agent.py`'ye:

```python
from short_bot.web.niche_finder import find_niches_ai, find_niches_data

_NICHES: dict = {}


@bp.post("/channels/agent/find")
def find():
    """Niş bul: LLM adaylar üretir, YouTube outlier verisi HAKEMLİK eder.

    YouTube anahtarı yoksa AI moduna düşülür — adaylar gelir ama KANIT YOKTUR ve
    panel bunu söyler. Uydurma kanıt yazmayız.
    """
    query = (request.form.get("query") or "").strip()
    language = (request.form.get("language") or "tr").strip()
    if language not in SUPPORTED_LANGUAGES:
        language = "tr"
    if len(query) < 3:
        flash("Ne hakkında kanal istediğini yaz (ör. 'Almanya', 'bahçecilik').",
              "error")
        return redirect(url_for("channel_agent.page"))

    from short_bot.yt_outliers import resolve_youtube_api_keys
    secrets = _secrets()
    settings = current_app.config["SHORTBOT_SETTINGS"]
    api_keys = resolve_youtube_api_keys(secrets)
    or_model = settings.openrouter_models.get("dna", "anthropic/claude-opus-4.8")
    or_key = secrets.get("openrouter_api_key")

    job_id = uuid.uuid4().hex[:12]
    _set_job(job_id, status="running", error="", kind="find", language=language)

    def _job():
        try:
            if api_keys:
                out = find_niches_data(
                    query, language=language, count=6, api_keys=api_keys,
                    claude_path=settings.claude_cli_path,
                    openrouter_model=or_model, openrouter_key=or_key)
            else:
                # KANIT YOK — panel bunu söyleyecek.
                out = find_niches_ai(
                    query, language=language, count=6,
                    claude_path=settings.claude_cli_path,
                    openrouter_model=or_model, openrouter_key=or_key)
            with _LOCK:
                _NICHES[job_id] = out
            _set_job(job_id, status="done")
        except Exception as e:   # noqa: BLE001
            _LOG.warning(f"[ajan] niş bulucu: {e}")
            _set_job(job_id, status="error", error=str(e))

    _start_thread(_job)
    return redirect(url_for("channel_agent.status", job_id=job_id))
```

`status()` rotası `_NICHES`i de okur ve şablona `niches=` olarak geçirir.

- [ ] **Step 4: Şablona niş kartlarını ekle**

`channel_agent.html.j2`: `niches` doluysa her aday için bir kart —
niş adı, `neden` (kanıt cümlesi), `kanit_puani` rozeti, ve **"Bu nişle devam et"**
düğmesi. Düğme `POST /channels/agent/plan` yapar; gizli alanlar:
`niche = konu_tohumu`, `language`, `evidence = neden`.

Böylece niş bulucudan gelen KANIT, plana taşınır ve plan ekranında görünür.

Kanıt yoksa (AI modu) kartlarda "kanıt yok — YouTube anahtarı ekleyin" notu.

- [ ] **Step 5: Testleri koş**

Run: `python -m pytest tests/test_web_channel_agent.py -q`
Expected: PASS

- [ ] **Step 6: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 7: Commit**

```bash
git add src/short_bot/web/routes/channel_agent.py src/short_bot/web/templates/channel_agent.html.j2
git add -f tests/test_web_channel_agent.py
git commit -m "feat(agent): nis bulucu ajana bagli - kanit plana tasinir"
```

---

## Task 6: GERÇEK koşu — Almanca kanal kur ve ÖLÇ

Şimdiye kadar her şey sahte LLM ile test edildi. Ajanın **gerçekten** çalışan bir Almanca kanal kurduğu ÖLÇÜLMEDİ.

**Files:**
- Test: `tests/test_channel_agent_real.py` (yeni, `@pytest.mark.slow`)

- [ ] **Step 1: Kalite kapısı testini yaz**

`tests/test_channel_agent_real.py`:

```python
"""GERÇEK Sonnet + GERÇEK ai33 ile kalite kapısı.

Diğer testler sahte LLM kullanır — akışı kanıtlarlar, KALİTEYİ değil.
Bu dosya ajanın gerçekten çalışan bir Almanca kanal planı kurduğunu kanıtlar.

YAVAŞ (~3-5 dk) ve GERÇEK API kotası harcar (ai33 ses listesi + Sonnet + DNA).
"""
import pytest
import yaml

from short_bot.channel_agent import build_plan
from short_bot.config import load_settings
from short_bot.llm_sonnet import sonnet_json
from short_bot.tts.ai33_client import resolve_ai33_api_key


def _sonnet(prompt, schema, **kw):
    return sonnet_json(prompt, schema)


@pytest.mark.slow
def test_ALMANCA_kanal_plani_GERCEKTEN_kurulur(tmp_path):
    from pathlib import Path
    settings = load_settings(Path("config/settings.yaml"))
    secrets = yaml.safe_load(
        Path("data/secrets.yaml").read_text(encoding="utf-8")) or {}
    ai33 = resolve_ai33_api_key(secrets)
    if not ai33:
        pytest.skip("ai33 anahtarı yok")

    p = build_plan(
        "bira bahcesi kulturu ve bira uretiminin sasirtici gercekleri",
        language="de", channels_dir=tmp_path, ai33_key=ai33,
        settings=settings, secrets=secrets, llm=_sonnet)

    # SES: Almanca konuşan bir ses seçilmiş olmalı (İngilizceye DÜŞMEMELİ)
    assert p.voice.voice_id.startswith("elevenlabs_")
    assert p.voice.reason, "ses gerekçesi boş"

    # İSİM: Almanca, kısa
    assert p.name and len(p.name) <= 40
    assert p.slug

    # KİMLİK
    assert p.dna.archetype

    # ÖRNEK KONULAR: Almanca ve somut
    assert len(p.sample_topics) >= 2, f"yalnız {len(p.sample_topics)} konu üretildi"
    birlesik = " ".join(p.sample_topics)
    assert "ABONE" not in birlesik.upper(), "Türkçe sızıntı"
    # Almanca metinde umlaut/eszet ya da tipik Almanca kelime beklenir
    assert any(x in birlesik.lower() for x in ("bier", "die ", "der ", "das ",
                                               "ä", "ö", "ü", "ß"))

    # HİÇBİR DOSYA YAZILMAMIŞ olmalı (dil paketi hariç)
    assert list(tmp_path.glob("*.yaml")) == []
```

- [ ] **Step 2: Testi koş**

Run: `python -m pytest tests/test_channel_agent_real.py -q -m slow`
Expected: PASS

Kırılırsa **prompt/kodu düzelt**, testi değil. Bu bir kalite kapısıdır.

- [ ] **Step 3: Panelde gerçek bir kanal kur (elle)**

Paneli aç → `/channels/agent` → *"Almanca bira bahçesi kültürü ve bira üretiminin
şaşırtıcı gerçekleri"* + Deutsch → **Planı hazırla**.

Kontrol listesi:
- Ses Almanca mı? Gerekçesi anlamlı mı?
- Kanal adı Almanca ve kısa mı?
- Örnek konular Almanca, somut (sayı/mekanizma içeriyor) ve doğru mu?
- "Kur"a basınca kanal oluşuyor, `/channels/<slug>` açılıyor mu?
- Kanal YAML'ında `autopilot` YOK, `series_enabled: false` mu?
- Konu bankası doldu mu?

- [ ] **Step 4: Bulguları raporla ve düzelt**

Her sapma için: ne bekleniyordu, ne oldu, hangi katman. Düzelt, testini yaz, commit et.

- [ ] **Step 5: Commit**

```bash
git add -f tests/test_channel_agent_real.py
git commit -m "test(agent): GERCEK Sonnet + ai33 ile kalite kapisi (Almanca kanal plani)"
```

---

## Kapsam dışı (bilerek)

- **Autopilot'u ajan AÇMAZ.** YouTube'a otomatik yükleme büyük bir taahhüt; kullanıcı
  bilinçli açar (Otomasyon sayfasından).
- **Referans kanal önerisi YOK.** Ölçüldü: artık gerekmiyor (Sonnet kanıtsız iyi konu
  yazıyor) ve kullanıcının mevcut referansları zaten nişe uymuyordu — bir bilim-tarihi
  kanalının referansları "Uykuda AirPod Yutarsan Ne Olur?" getiriyordu.
- **Seri/ark KAPALI** gelir.
- **Mevcut `/channels/new-reel` sihirbazı DURUYOR** — elle tam kontrol isteyen için.
