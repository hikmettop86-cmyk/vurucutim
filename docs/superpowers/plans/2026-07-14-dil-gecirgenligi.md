# Dil Geçirgenliği — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Türkçe dışında bir dilde açılan kanal gerçekten o dilde çalışsın — ekran metni, anlatım harfleri, klişe denetçisi ve seri yönergeleri dahil.

**Architecture:** İki katman. (1) Dile duyarlı normalleştirme — `locale_fold`, `locale_upper`, `strip_foreign_diacritics` + `language()` contextvar. Bu ÖN KOŞUL: onsuz dil paketinin denetçi bölümü ölü doğar, çünkü `_fold` Türkçe için `I→ı` yapıyor ve Almanca regex asla eşleşmiyor. (2) `LangPack` — dile özgü metinlerin tamamı JSON dosyada; `tr`/`en` elle yazılır, `de`/`es`/`fr` Claude CLI + Sonnet 5 ile üretilip önbelleklenir.

**Tech Stack:** Python 3.14, pydantic v2, pytest, contextvars, `claude_cli.run_json`.

**Spec:** `docs/superpowers/specs/2026-07-14-dil-gecirgenligi-design.md`

**Dal:** `feature/electron-installer`. YAYINLANMAYACAK.

---

## Değişmez kurallar (her görevde geçerli)

1. **Türkçe davranış birebir korunur.** Her görevin sonunda `pytest tests/ -q` çalışır ve 2033 testin hepsi geçer. Bir Türkçe testi kırılırsa görev bitmemiştir.
2. **`tests/` gitignore'da.** Commit ederken `git add -f tests/<dosya>` gerekir. `src/`, `docs/` için `-f` gerekmez (docs/superpowers de ignore'da → `-f` gerekir).
3. **Sessiz düşme yasak.** Bir dil paketi bulunamaz/üretilemezse `RuntimeError` fırlatılır. Türkçe pakete DÜŞÜLMEZ.
4. **PowerShell here-string kesme işaretinde kırılıyor.** Commit mesajını dosyaya yazıp `git commit -F <dosya>` kullan, ya da Bash tool'da tek satırlık `-m` kullan.

---

## Dosya haritası

| Dosya | Sorumluluk | Durum |
|---|---|---|
| `src/short_bot/locale.py` | `SUPPORTED_LANGUAGES`, `UI_LABELS`, **+ `ALPHABET_EXTRA`** (dil → alfabesindeki ASCII-dışı harfler) | Değişir |
| `src/short_bot/text_normalize.py` | `turkish_upper`, `strip_non_turkish_diacritics` → **+ `locale_fold`, `locale_upper`, `strip_foreign_diacritics`, `language()` contextvar** | Değişir |
| `src/short_bot/lang_pack.py` | `LangPack` modeli + `load_pack()` + `validate_pack()` | **YENİ** |
| `src/short_bot/lang_pack_gen.py` | Sonnet 5 ile paket üretimi (Claude CLI → OpenRouter düşme) | **YENİ** |
| `src/short_bot/langpacks/tr.json` | Türkçe paket — bugünkü sabitlerin BİREBİR kopyası | **YENİ (veri)** |
| `src/short_bot/langpacks/en.json` | İngilizce paket — elle yazılır | **YENİ (veri)** |
| `src/short_bot/reel_phrases.py` | Sabitler silinir; `pick_styles(seed, n, *, pack)`, `find_overused(text, *, pack)` | Değişir |
| `src/short_bot/reel_subscribe.py` | Sabitler silinir; `build_subscribe_bits` paketi kendi yükler | Değişir |
| `src/short_bot/reel_series.py` | `episode_badge/trade_cta/series_directive/clean_open_loop` paket alır | Değişir |
| `src/short_bot/tts/fidelity.py` | `_fold(text, lang)`, `normalize_tokens(text, lang)` | Değişir |
| `src/short_bot/web/routes/lang_packs.py` | Panel: listele / göster / düzenle / yeniden üret | **YENİ** |

---

## Task 1: Dile duyarlı normalleştirme temeli

Bu ÖN KOŞUL. `_fold("Ich")` bugün `"ıch"` döndürüyor; bu düzelmeden Almanca denetçi kalıpları hiçbir zaman eşleşmez.

**Files:**
- Modify: `src/short_bot/locale.py` (dosya sonuna ekleme)
- Modify: `src/short_bot/text_normalize.py`
- Test: `tests/test_locale_normalize.py` (yeni)

- [ ] **Step 1: Testi yaz (kırılacak)**

`tests/test_locale_normalize.py`:

```python
"""Dile duyarlı normalleştirme.

ÖLÇÜLDÜ (düzeltmeden önce, gerçek kod):
    _fold("Ich zeige euch")            -> "ıch zeige euch"   (I -> ı)
    re.search(r"\\bich\\b", ...)         -> None
    turkish_upper("Bier Garten")       -> "BİER GARTEN"      (noktalı İ)
    strip_non_turkish_diacritics("Täglich") -> "Taglich"     (ä silindi)

Yani mükemmel bir Almanca kalıp listesi yazsak bile eşleşmezdi; ve Almanca anlatım
metni model sınırında sessizce bozuluyordu.
"""
import re

import pytest

from short_bot.locale import ALPHABET_EXTRA, SUPPORTED_LANGUAGES
from short_bot.text_normalize import (language, locale_fold, locale_upper,
                                      strip_foreign_diacritics, turkish_upper)


# --- ALFABE TABLOSU --------------------------------------------------------

def test_her_desteklenen_dilin_alfabesi_TANIMLI():
    for lang in SUPPORTED_LANGUAGES:
        assert lang in ALPHABET_EXTRA, f"{lang} alfabesi tanımsız"


def test_almanca_alfabesi_ESZET_icerir():
    # Sonnet'e bıraksaydık 'ß'i unutabilirdi ve Almanca anlatım sessizce bozulurdu.
    # Bu yüzden alfabe OLGU tablosu, LLM üretimi değil.
    for ch in "äöüßÄÖÜ":
        assert ch in ALPHABET_EXTRA["de"]


def test_turkce_alfabesi_bugunku_KEEP_setiyle_ayni():
    for ch in "ÇĞİıÖŞÜçğöşü":
        assert ch in ALPHABET_EXTRA["tr"]


# --- KÜÇÜLTME (locale_fold) ------------------------------------------------

def test_turkce_fold_BUGUNKU_davranis():
    # 'İ'.lower() birleşik nokta üretir; elle eşlenmeli.
    assert locale_fold("İSTANBUL", "tr") == "istanbul"
    assert locale_fold("IŞIK", "tr") == "ışık"


def test_almanca_fold_I_harfini_BOZMAZ():
    """GERÇEK HATA: _fold Türkçe için I->ı yapıyordu, Almanca 'Ich' -> 'ıch' oluyordu
    ve r'\\bich\\b' asla eşleşmiyordu. Denetçi çalışıyor görünüp sıfır şey buluyordu."""
    assert locale_fold("Ich", "de") == "ich"
    assert re.search(r"\bich\b", locale_fold("Ich zeige euch", "de"))


def test_fold_varsayilani_TURKCE():
    # Mevcut çağıranlar dil geçirmiyor; davranış değişmemeli.
    assert locale_fold("IŞIK") == "ışık"


# --- BÜYÜTME (locale_upper) ------------------------------------------------

def test_turkce_upper_NOKTALI_I():
    assert locale_upper("Bilinmeyen Tarih", "tr") == "BİLİNMEYEN TARİH"
    assert locale_upper("Bilinmeyen Tarih", "tr") == turkish_upper("Bilinmeyen Tarih")


def test_almanca_upper_NOKTASIZ_I():
    """Ekranda görünür: Almanca kanalın rozeti 'BİER GARTEN' yazıyordu."""
    assert locale_upper("Bier Garten", "de") == "BIER GARTEN"


# --- AKSAN KORUMASI (strip_foreign_diacritics) -----------------------------

def test_turkce_YABANCI_aksani_siler():
    # Var oluş sebebi: Sonnet Türkçe çıktıya İspanyolca aksan sızdırıyor.
    with language("tr"):
        assert strip_foreign_diacritics("CANLÍ") == "CANLI"
        assert strip_foreign_diacritics("español") == "espanol"
        assert strip_foreign_diacritics("Çocuklar") == "Çocuklar"   # Türkçe: korunur


def test_almanca_KENDI_harflerini_korur():
    """EN AĞIR SESSİZ HATA: 'Täglich' -> 'Taglich'. Bu bir pydantic field_validator,
    yani LLM'in yazdığı her anlatım cümlesinde koşuyordu. TTS yanlış okuyor,
    altyazıda yanlış görünüyordu."""
    with language("de"):
        assert strip_foreign_diacritics("Täglich frisches Bier") == "Täglich frisches Bier"
        assert strip_foreign_diacritics("Weiß") == "Weiß"
        assert strip_foreign_diacritics("Öl") == "Öl"
        # Almanca alfabesinde OLMAYAN aksan yine silinir:
        assert strip_foreign_diacritics("café") == "cafe"


def test_ispanyolca_kendi_harflerini_korur():
    with language("es"):
        assert strip_foreign_diacritics("español") == "español"
        assert strip_foreign_diacritics("¿Sabías?") == "¿Sabías?"


def test_dil_kurulmazsa_TURKCE_varsayilan():
    # Bugünkü davranış: contextvar'ın varsayılanı "tr".
    assert strip_foreign_diacritics("español") == "espanol"


def test_language_blogu_KAPSAMI_sinirlar():
    with language("de"):
        assert strip_foreign_diacritics("Täglich") == "Täglich"
    # Blok bitince eski dile döner — sızıntı yok.
    assert strip_foreign_diacritics("Täglich") == "Taglich"


def test_language_blogu_IC_ICE():
    with language("de"):
        with language("es"):
            assert strip_foreign_diacritics("español") == "español"
        assert strip_foreign_diacritics("Täglich") == "Täglich"


def test_eski_ad_TAKMA_AD_olarak_calisir():
    """15 import noktası var; kırmıyoruz."""
    from short_bot.text_normalize import strip_non_turkish_diacritics
    assert strip_non_turkish_diacritics("CANLÍ") == "CANLI"
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_locale_normalize.py -q`
Expected: FAIL — `ImportError: cannot import name 'ALPHABET_EXTRA' from 'short_bot.locale'`

- [ ] **Step 3: `locale.py`'ye alfabe tablosunu ekle**

`src/short_bot/locale.py` dosya sonuna:

```python
# Dilin alfabesindeki ASCII-DIŞI harfler. Aksan temizleyicisi (text_normalize.
# strip_foreign_diacritics) bu tabloda OLMAYAN her aksanı söker.
#
# NEDEN OLGU TABLOSU, NEDEN DİL PAKETİNDE DEĞİL: alfabe bir olgudur, üslup değil.
# Dil paketini Sonnet üretiyor; 'ß'i unutursa Almanca anlatım metni SESSİZCE bozulur
# ("Weiß" → "Wei"). Bu riski almanın hiçbir karşılığı yok.
ALPHABET_EXTRA: dict[str, str] = {
    "tr": "ÇĞİıÖŞÜçğöşü",
    "en": "",
    "de": "ÄÖÜäöüß",
    "es": "ÑñÁÉÍÓÚÜáéíóúü¿¡",
    "fr": "ÀÂÆÇÉÈÊËÎÏÔŒÙÛÜŸàâæçéèêëîïôœùûüÿ",
}
```

- [ ] **Step 4: `text_normalize.py`'yi dile duyarlı yap**

`src/short_bot/text_normalize.py` — mevcut `strip_non_turkish_diacritics` ve
`_TURKISH_KEEP` yerine (import satırlarını da güncelle):

```python
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar

from short_bot.locale import ALPHABET_EXTRA

# Aktif hedef dil. Aksan temizleyicisi bir pydantic field_validator'dan çağrılıyor ve
# validator'ın çağıranın dilini görmesinin yolu yok. Dili her model kurulum noktasından
# (LLM parse + fit_word_budget gibi yeniden-kurma yolları + testler) elle geçirmek
# onlarca dokunuş demek ve BİRİ UNUTULURSA SESSİZCE TÜRKÇEYE DÜŞER — düzeltmeye
# çalıştığımız hatanın aynısı. Contextvar iş parçacığı başına yalıtık (her pipeline
# koşusu kendi thread'inde) ve `with language(...)` kapsamı açıkça sınırlar.
_LANG: ContextVar[str] = ContextVar("shortbot_lang", default="tr")


@contextmanager
def language(lang: str):
    """Bu blok boyunca hedef dil ``lang``. İç içe kullanılabilir."""
    tok = _LANG.set(lang)
    try:
        yield
    finally:
        _LANG.reset(tok)


def current_language() -> str:
    return _LANG.get()


def strip_foreign_diacritics(s: str) -> str:
    """Hedef dilin alfabesinde OLMAYAN harflerin aksanını sök.

    Var oluş sebebi: model ara sıra hedef dile yabancı aksan sızdırıyor (Türkçe
    çıktıda 'CANLÍ'). Ama sökme işlemi HEDEF DİLE GÖRE yapılmalı — Almanca'da 'ä'
    yabancı değil, alfabenin harfidir. Dile duyarsız hâli 'Täglich'i 'Taglich'
    yapıyordu ve bu bir field_validator olduğu için her anlatım cümlesinde koşuyordu.
    """
    keep = ALPHABET_EXTRA.get(_LANG.get(), ALPHABET_EXTRA["tr"])
    out = []
    for ch in s:
        if ord(ch) < 128 or ch in keep:
            out.append(ch)
            continue
        decomposed = unicodedata.normalize("NFKD", ch)
        base = "".join(c for c in decomposed if not unicodedata.combining(c))
        out.append(base if base else "")
    return "".join(out)


# Eski ad: 15 import noktası var, kırmıyoruz. Varsayılan dil "tr" olduğu için
# davranış birebir aynı kalır.
strip_non_turkish_diacritics = strip_foreign_diacritics


_TR_UPPER = str.maketrans({"i": "İ", "ı": "I"})


def turkish_upper(s: str) -> str:
    """Türkçe-farkında büyük harf. 'Bilim'.upper() → 'BILIM' (yanlış)."""
    return s.translate(_TR_UPPER).upper()


def locale_upper(s: str, lang: str = "tr") -> str:
    """Dile duyarlı büyük harf. Almanca rozet 'BİER GARTEN' yazıyordu."""
    return turkish_upper(s) if lang == "tr" else s.upper()


def locale_fold(text: str, lang: str = "tr") -> str:
    """Eşleştirme için küçültme.

    Türkçe: ``"İ".lower()`` birleşik nokta üretir (i̇) ve kelimeyi eşleşmez kılar;
    harfleri elle eşliyoruz. Ama bu eşleme DİLE ÖZGÜ: Almanca'da 'I' harfi 'ı' değil
    'i' olur. Dile duyarsız hâli 'Ich' → 'ıch' yapıyordu ve r'\\bich\\b' asla
    eşleşmiyordu — denetçi çalışıyor görünüp sıfır şey buluyordu.
    """
    if lang == "tr":
        return text.replace("İ", "i").replace("I", "ı").lower()
    return text.casefold()
```

`strip_non_turkish_diacritics`'in eski docstring'i ve `_TURKISH_KEEP` sabiti silinir.

- [ ] **Step 5: Testi koş**

Run: `python -m pytest tests/test_locale_normalize.py -q`
Expected: PASS (14 test)

- [ ] **Step 6: Tam paketi koş — Türkçe regresyon yok**

Run: `python -m pytest tests/ -q`
Expected: `2047 passed, 1 skipped` (2033 + 14 yeni)

Eğer bir Türkçe testi kırıldıysa DUR: `strip_non_turkish_diacritics` takma adı ya da
`ALPHABET_EXTRA["tr"]` eski `_TURKISH_KEEP` ile aynı değil demektir.

- [ ] **Step 7: Commit**

```bash
git add src/short_bot/locale.py src/short_bot/text_normalize.py
git add -f tests/test_locale_normalize.py
git commit -m "feat(lang): dile duyarli normallestirme (locale_fold/locale_upper/strip_foreign_diacritics)"
```

---

## Task 2: Aksan korumasını pipeline'a bağla

Task 1 aracı yaptı; bu görev onu **kullanır**. Bu olmadan `language()` hiç kurulmaz ve Almanca metin bozulmaya devam eder.

**Files:**
- Modify: `src/short_bot/pipeline.py` (`run_pipeline` gövdesi)
- Test: `tests/test_lang_context.py` (yeni)

- [ ] **Step 1: Testi yaz**

`tests/test_lang_context.py`:

```python
"""Hedef dil, LLM çıktısının modele girdiği SINIRDA kurulmalı.

Aksi hâlde strip_foreign_diacritics contextvar'ın varsayılanına ("tr") düşer ve
Almanca anlatım sessizce bozulur — düzelttiğimiz hatanın ta kendisi.
"""
from short_bot.reel_models import ReelBeat
from short_bot.text_normalize import language


def _beat(text):
    return ReelBeat(text=text, visual_query="bier garten", keyword="")


def test_almanca_baglamda_anlatim_METNI_BOZULMAZ():
    with language("de"):
        b = _beat("Täglich frisches Bier aus Bayern")
    assert b.text == "Täglich frisches Bier aus Bayern"


def test_baglam_kurulmazsa_TURKCE_davranis_korunur():
    # Bugünkü davranış (regresyon kalkanı): Türkçe çıktıya sızan yabancı aksan silinir.
    b = _beat("CANLÍ yayin burada simdi")
    assert b.text == "CANLI yayin burada simdi"


def test_run_pipeline_kanalin_DILINI_kurar(monkeypatch):
    """run_pipeline gövdesi `with language(channel.language)` içinde koşmalı."""
    import short_bot.pipeline as P
    gorulen = {}

    from short_bot.text_normalize import current_language

    # Pipeline'ın ilk adımını yakalayıp o anki dili okuyoruz.
    def _sahte_preflight(*a, **kw):
        gorulen["lang"] = current_language()
        raise RuntimeError("dur")   # gerisi bizi ilgilendirmiyor

    monkeypatch.setattr(P, "preflight", _sahte_preflight, raising=False)
    # NOT: `preflight` adı pipeline.py'de farklıysa, run_pipeline'ın ÇAĞIRDIĞI ilk
    # fonksiyonu yakala — amaç, gövdenin language() bloğu içinde koştuğunu kanıtlamak.
```

> **Uygulayıcıya not:** Step 1'deki üçüncü test bir iskelet. `run_pipeline`'ı aç, gövdesinin çağırdığı ilk fonksiyonun gerçek adını bul (`grep -n "def run_pipeline" -A 30 src/short_bot/pipeline.py`) ve `monkeypatch.setattr` hedefini ona göre düzelt. Kanıtlamak istediğimiz tek şey: `run_pipeline` gövdesi `language(channel.language)` bloğu içinde koşuyor.

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_lang_context.py -q`
Expected: `test_almanca_baglamda_anlatim_METNI_BOZULMAZ` PASS (Task 1 sayesinde),
`test_run_pipeline_kanalin_DILINI_kurar` FAIL (`gorulen["lang"] == "tr"`, beklenen `"de"`)

- [ ] **Step 3: `run_pipeline` gövdesini `language()` içine al**

`src/short_bot/pipeline.py` — `run_pipeline` gövdesinin tamamını sar:

```python
def run_pipeline(channel, ..., defer_upload: bool = False, standalone: bool = False):
    # LLM çıktısının aksanları HEDEF DİLE göre korunmalı. Bu blok, model
    # doğrulayıcılarının (strip_foreign_diacritics bir field_validator'dır) kanalın
    # dilini görmesini sağlar. Kurulmazsa Almanca "Täglich" → "Taglich" olur ve
    # bunu hiçbir hata bildirmez.
    from short_bot.text_normalize import language
    with language(channel.language):
        return _run_pipeline_inner(channel, ..., defer_upload=defer_upload,
                                   standalone=standalone)
```

Mevcut gövde `_run_pipeline_inner` adına taşınır (imza aynen korunur).

- [ ] **Step 4: Testi koş**

Run: `python -m pytest tests/test_lang_context.py -q`
Expected: PASS

- [ ] **Step 5: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/pipeline.py
git add -f tests/test_lang_context.py
git commit -m "fix(lang): pipeline kanalin dilini kurar - Almanca anlatim metni artik bozulmuyor"
```

---

## Task 3: `LangPack` modeli + doğrulama

**Files:**
- Create: `src/short_bot/lang_pack.py`
- Test: `tests/test_lang_pack.py` (yeni)

- [ ] **Step 1: Testi yaz**

`tests/test_lang_pack.py`:

```python
"""LangPack doğrulaması.

SERT KISITLAR koddan gelir, paketten değil:
  CTA_MAX_CHARS = 24   — Almanca'da "ABONNIEREN" tek başına 10 karakter.
                         Çalışma anında kırpılırsa ekranda "ABONNIE" yazar.
  BADGE_MAX_CHARS = 28
Bu yüzden paket ÜRETİLDİĞİ AN doğrulanır.
"""
import pytest

from short_bot.lang_pack import LangPack, SeriesDirectives, validate_pack


def _seri(**kw):
    d = dict(
        header="Dies ist Folge {no} von '{title}'. Die nächste ist {next_no}.",
        paying_promise="Diese Folge löst ein Versprechen ein: \"{promise}\"",
        announce_arc="Kündige die Serie an: '{arc_title}', {arc_total} Folgen.",
        finale="Letzte Folge von '{arc_title}'. Folge {next_no} bringt ein neues Thema.",
        planned_loop="Das Thema von Folge {next_no} steht fest: \"{next_topic}\"",
        chain_loop="Öffne eine Tür; die Antwort kommt in Folge {next_no}.",
        teaser_fallback="Dies ist eine Folge der Serie '{title}'.",
    )
    d.update(kw)
    return SeriesDirectives(**d)


def _pack(**kw):
    d = dict(
        lang="de",
        cta_texts=["Täglich neu — ABONNIEREN", "Morgen mehr — ABO",
                   "Serie läuft — ABO", "Teil 2 morgen — ABO"],
        trade_cta="#{no} morgen — ABONNIEREN",
        default_series_title="Kuriose Fakten",
        comment_styles=["A", "B", "C", "D"],
        connective_styles=list("12345678"),
        series=_seri(),
        overused=["wusstest du schon", "hallo leute", "heute zeige ich euch",
                  "bleibt dran", "vergesst nicht"],
        overused_patterns=[
            {"label": "Wusstest du schon? (beantwortbare Ja/Nein-Frage)",
             "pattern": r"\bwusstest du\b"},
            {"label": "Hallo Leute (Kanal-Intro)", "pattern": r"\bhallo leute\b"},
            {"label": "Heute zeige ich euch", "pattern": r"\bheute zeige ich\b"},
            {"label": "Seid ihr bereit?", "pattern": r"\bseid ihr bereit\b"},
        ],
        meta_tail_pattern=r"\bin\s+folge\s+\d+\b.*$",
    )
    d.update(kw)
    return LangPack(**d)


def test_gecerli_paket_KABUL_edilir():
    assert validate_pack(_pack()) == []


# --- EKRAN KISITLARI -------------------------------------------------------

def test_24_karakterlik_CTA_KABUL():
    cta = "Täglich neu — ABONNIEREN"
    assert len(cta) == 24
    assert validate_pack(_pack(cta_texts=[cta, "a", "b", "c"])) == []


def test_25_karakterlik_CTA_RED():
    """Sınır testi. Kırpılan çip ekranda 'ABONNIE' yazar — her şeyden kötü."""
    uzun = "Täglich neues — ABONNIEREN"
    assert len(uzun) == 25
    hatalar = validate_pack(_pack(cta_texts=[uzun, "a", "b", "c"]))
    assert any("24" in h for h in hatalar)


def test_trade_cta_RENDER_EDILINCE_olculur():
    """'#{no} ...' şablonu ham hâlde kısa görünüp, no=48 ile taşabilir."""
    hatalar = validate_pack(_pack(trade_cta="#{no} morgen — JETZT ABONNIEREN"))
    assert hatalar, "render edilmiş uzunluk ölçülmedi"


def test_trade_cta_no_yer_tutucusu_ZORUNLU():
    hatalar = validate_pack(_pack(trade_cta="morgen — ABONNIEREN"))
    assert any("{no}" in h for h in hatalar)


def test_seri_basligi_ROZETE_sigmali():
    # Rozet: "BASLIK #47" ≤ 28 karakter → başlık ≤ 24
    hatalar = validate_pack(_pack(default_series_title="A" * 25))
    assert hatalar


# --- SAYILAR ---------------------------------------------------------------

def test_comment_styles_TAM_4():
    assert validate_pack(_pack(comment_styles=["A", "B", "C"]))
    assert validate_pack(_pack(comment_styles=["A", "B", "C", "D", "E"]))


def test_connective_styles_TAM_8():
    assert validate_pack(_pack(connective_styles=list("1234567")))


def test_denetci_BOS_olamaz():
    # Boş liste = denetçi yok = sessiz bozulma.
    assert validate_pack(_pack(overused=[]))
    assert validate_pack(_pack(overused_patterns=[]))


# --- REGEX -----------------------------------------------------------------

def test_DERLENMEYEN_regex_RED():
    bozuk = [{"label": "x", "pattern": r"\b(unclosed"}] * 4
    hatalar = validate_pack(_pack(overused_patterns=bozuk))
    assert any("regex" in h.lower() for h in hatalar)


def test_bozuk_meta_tail_RED():
    assert validate_pack(_pack(meta_tail_pattern=r"[unclosed"))


# --- SERİ ŞABLONLARI: YER TUTUCULAR ----------------------------------------

def test_EKSIK_yer_tutucusu_RED():
    """planned_loop'ta {next_no} yoksa LLM'e bölüm numarası hiç söylenmez."""
    hatalar = validate_pack(_pack(series=_seri(planned_loop='Thema: "{next_topic}"')))
    assert any("next_no" in h for h in hatalar)


def test_BILINMEYEN_yer_tutucusu_RED():
    """{bilinmeyen} çalışma anında KeyError fırlatır — üretimin ortasında."""
    hatalar = validate_pack(_pack(series=_seri(chain_loop="Folge {bilinmeyen}")))
    assert any("bilinmeyen" in h for h in hatalar)


def test_desteklenmeyen_dil_RED():
    assert validate_pack(_pack(lang="zz"))
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_lang_pack.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'short_bot.lang_pack'`

- [ ] **Step 3: `lang_pack.py`'yi yaz**

`src/short_bot/lang_pack.py`:

```python
"""Dile özgü metinlerin tamamı: ekran metni, LLM yönergeleri, klişe denetçisi.

NEDEN VAR: sistem beş dili destekliyor (locale.SUPPORTED_LANGUAGES) ama reel
katmanının metinleri Türkçe SABİTTİ. Almanca kanalda ekrana Türkçe "ABONE OL" çipi
basılıyor, rozet "BİER GARTEN" yazıyor ve klişe denetçisi hiçbir şey yakalayamıyordu.
İlk ikisi görünür; üçüncüsü sessiz — denetçi çalışıyor görünüp sıfır şey buluyordu.

Paket dosyadan gelir (langpacks/<dil>.json). tr/en elle yazıldı; de/es/fr Sonnet 5
üretiyor (lang_pack_gen). Türkçe paket bugünkü sabitlerin BİREBİR kopyasıdır —
altın test çıktının zerre değişmediğini kanıtlıyor.
"""
from __future__ import annotations

import json
import re
import string
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from short_bot.locale import SUPPORTED_LANGUAGES

# Ekran kısıtları KODDAN gelir, paketten değil — paket bunlara UYMAK zorunda.
CTA_MAX_CHARS = 24      # 1080px'e sığan tek satır abone çipi
BADGE_MAX_CHARS = 28    # kare-sıfır feed rozeti
TITLE_MAX_CHARS = BADGE_MAX_CHARS - len(" #47")   # rozette numaraya yer kalmalı

N_COMMENT_STYLES = 4
N_CONNECTIVE_STYLES = 8
MIN_OVERUSED = 5
MIN_OVERUSED_PATTERNS = 4

# Seri yönergesi şablonlarının yer tutucuları: (zorunlu, izin verilen)
SERIES_PLACEHOLDERS: dict[str, tuple[set[str], set[str]]] = {
    "header":          ({"title", "no", "next_no"}, {"title", "no", "next_no"}),
    "paying_promise":  ({"promise"}, {"promise", "no"}),
    "announce_arc":    ({"arc_title", "arc_total"}, {"arc_title", "arc_total", "no"}),
    "finale":          ({"arc_title", "next_no"}, {"arc_title", "next_no", "no"}),
    "planned_loop":    ({"next_no", "next_topic"}, {"next_no", "next_topic"}),
    "chain_loop":      ({"next_no"}, {"next_no"}),
    "teaser_fallback": ({"title"}, {"title"}),
}


class OverusedPattern(BaseModel):
    label: str = Field(min_length=3)     # LLM'e geri bildirimde gösterilir
    pattern: str = Field(min_length=2)   # hedef dilde regex


class SeriesDirectives(BaseModel):
    header: str
    paying_promise: str
    announce_arc: str
    finale: str
    planned_loop: str
    chain_loop: str
    teaser_fallback: str


class LangPack(BaseModel):
    lang: str
    # EKRANA BASILAN
    cta_texts: list[str]
    trade_cta: str
    default_series_title: str
    # LLM YÖNERGELERİ
    comment_styles: list[str]
    connective_styles: list[str]
    series: SeriesDirectives
    # DENETÇİ
    overused: list[str]
    overused_patterns: list[OverusedPattern]
    meta_tail_pattern: str


def _placeholders(tmpl: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(tmpl) if f}


def validate_pack(pack: LangPack) -> list[str]:
    """Hataların listesi (boş = geçerli). Üretim anında koşar — çalışma anında DEĞİL.

    Çalışma anında kırpmak/patlamak kabul edilemez: kırpılmış bir abone çipi ekranda
    "ABONNIE" yazar, eksik yer tutucu üretimin ortasında KeyError fırlatır.
    """
    h: list[str] = []

    if pack.lang not in SUPPORTED_LANGUAGES:
        h.append(f"desteklenmeyen dil: {pack.lang!r}")

    # --- ekran metni
    if len(pack.cta_texts) != 4:
        h.append(f"cta_texts tam 4 olmalı, {len(pack.cta_texts)} geldi")
    if len(set(pack.cta_texts)) != len(pack.cta_texts):
        h.append("cta_texts tekrarlı")
    for c in pack.cta_texts:
        if not c.strip():
            h.append("cta_texts boş metin içeriyor")
        elif len(c) > CTA_MAX_CHARS:
            h.append(f"CTA {len(c)} karakter, en fazla {CTA_MAX_CHARS}: {c!r}")

    if "{no}" not in pack.trade_cta:
        h.append("trade_cta '{no}' yer tutucusu içermeli")
    else:
        # HAM uzunluk değil, RENDER edilmiş uzunluk ölçülür.
        render = pack.trade_cta.replace("{no}", "48")
        if len(render) > CTA_MAX_CHARS:
            h.append(f"trade_cta render edilince {len(render)} karakter, "
                     f"en fazla {CTA_MAX_CHARS}: {render!r}")

    if not pack.default_series_title.strip():
        h.append("default_series_title boş")
    elif len(pack.default_series_title) > TITLE_MAX_CHARS:
        h.append(f"default_series_title {len(pack.default_series_title)} karakter, "
                 f"rozete sığması için en fazla {TITLE_MAX_CHARS}")

    # --- sayılar (seed rotasyonu bunlara dayanıyor)
    if len(pack.comment_styles) != N_COMMENT_STYLES:
        h.append(f"comment_styles tam {N_COMMENT_STYLES} olmalı, "
                 f"{len(pack.comment_styles)} geldi")
    if len(pack.connective_styles) != N_CONNECTIVE_STYLES:
        h.append(f"connective_styles tam {N_CONNECTIVE_STYLES} olmalı, "
                 f"{len(pack.connective_styles)} geldi")

    # --- denetçi (boş liste = denetçi yok = sessiz bozulma)
    if len(pack.overused) < MIN_OVERUSED:
        h.append(f"overused en az {MIN_OVERUSED} olmalı, {len(pack.overused)} geldi")
    if len(pack.overused_patterns) < MIN_OVERUSED_PATTERNS:
        h.append(f"overused_patterns en az {MIN_OVERUSED_PATTERNS} olmalı, "
                 f"{len(pack.overused_patterns)} geldi")
    for op in pack.overused_patterns:
        try:
            re.compile(op.pattern)
        except re.error as e:
            h.append(f"geçersiz regex {op.pattern!r}: {e}")
    try:
        re.compile(pack.meta_tail_pattern)
    except re.error as e:
        h.append(f"geçersiz meta_tail_pattern regex: {e}")

    # --- seri şablonları
    for alan, (zorunlu, izinli) in SERIES_PLACEHOLDERS.items():
        tmpl = getattr(pack.series, alan)
        var = _placeholders(tmpl)
        for eksik in sorted(zorunlu - var):
            h.append(f"series.{alan}: zorunlu yer tutucu eksik: {{{eksik}}}")
        for fazla in sorted(var - izinli):
            h.append(f"series.{alan}: bilinmeyen yer tutucu: {{{fazla}}}")

    return h
```

- [ ] **Step 4: Testi koş**

Run: `python -m pytest tests/test_lang_pack.py -q`
Expected: PASS (15 test)

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/lang_pack.py
git add -f tests/test_lang_pack.py
git commit -m "feat(lang): LangPack modeli + uretim-ani dogrulamasi (CTA 24 karakter, yer tutucular, regex)"
```

---

## Task 4: Türkçe paketi çıkar + yükleyici + ALTIN TEST

Bu planın en kritik görevi. `tr.json` bugünkü sabitlerin **birebir** kopyası olmalı; altın test bunu kanıtlar. Kopyalarken tek karakter değiştirme.

**Files:**
- Create: `src/short_bot/langpacks/tr.json`
- Modify: `src/short_bot/lang_pack.py` (`load_pack` ekle)
- Test: `tests/test_lang_pack_tr_golden.py` (yeni)

- [ ] **Step 1: `tr.json`'u bugünkü sabitlerden ÜRET (elle değil, betikle)**

Elle kopyalamak hata davet eder. Bir kereye mahsus betik yaz ve çalıştır — kaynak kod
ne diyorsa JSON'a o girsin:

`C:\Users\Hiko\AppData\Local\Temp\claude\...\scratchpad\dump_tr.py`:

```python
import json, sys
sys.path.insert(0, "D:/short/src")
from short_bot.reel_phrases import CONNECTIVE_STYLES, OVERUSED, OVERUSED_PATTERNS
from short_bot.reel_subscribe import COMMENT_STYLES, CTA_TEXTS

pack = {
    "lang": "tr",
    "cta_texts": list(CTA_TEXTS),
    "trade_cta": "#{no} yarın — ABONE OL",          # reel_series.trade_cta
    "default_series_title": "İlginç Bilgiler",       # reel_subscribe/reel_series fallback
    "comment_styles": list(COMMENT_STYLES),
    "connective_styles": list(CONNECTIVE_STYLES),
    "series": {},        # aşağıda elle doldurulacak (reel_series.series_directive)
    "overused": list(OVERUSED),
    "overused_patterns": [{"label": e, "pattern": p} for e, p in OVERUSED_PATTERNS],
    "meta_tail_pattern": "",   # reel_series._META örüntüsü
}
print(json.dumps(pack, ensure_ascii=False, indent=2))
```

Çalıştır, çıktıyı `src/short_bot/langpacks/tr.json` içine koy. Sonra elle üç alanı
tamamla:

- **`series.*`** — `reel_series.series_directive()`'in f-string dallarını `.format`
  şablonlarına çevir. `{plan.episode_no}` → `{no}`, `{plan.next_no}` → `{next_no}`,
  `{t}` → `{title}`, `{plan.continue_from}` → `{promise}`, `{plan.arc_title}` →
  `{arc_title}`, `{plan.arc_total}` → `{arc_total}`, `{plan.next_topic}` →
  `{next_topic}`. **Metni değiştirme, sadece yer tutucuları çevir.**
- **`meta_tail_pattern`** — `reel_series._META`'nın desen dizgesi
  (`_B`/`_V` genişletilmiş hâliyle, tek dizge olarak).
- **`teaser_fallback`** — `reel_subscribe.py:94-98`'deki "seri açık ama plan yok"
  metni, `{title}` yer tutucusuyla.

- [ ] **Step 2: Altın testi yaz — bugünkü sabitlerle BİREBİR eşitlik**

`tests/test_lang_pack_tr_golden.py`:

```python
"""ALTIN TEST — regresyon kalkanı.

tr.json bugünkü Türkçe sabitlerin BİREBİR kopyası olmalı. Bu test onu kanıtlar:
paketten okunan her değer, koddaki sabitle karakter karakter aynı.

Bu test kırılırsa tr.json yanlış çıkarılmıştır ve Türkçe kanalların çıktısı DEĞİŞİR.
"""
from short_bot.lang_pack import load_pack, validate_pack

PACK = load_pack("tr")


def test_tr_paketi_GECERLI():
    assert validate_pack(PACK) == []


def test_cta_metinleri_BIREBIR():
    assert PACK.cta_texts == [
        "Her gün yeni — ABONE OL",
        "Yarın devamı — ABONE OL",
        "Seri sürüyor — ABONE OL",
        "Devamı yarın — ABONE OL",
    ]


def test_trade_cta_BIREBIR():
    assert PACK.trade_cta.replace("{no}", "48") == "#48 yarın — ABONE OL"


def test_baglac_yonergeleri_TAM_8_ve_ILK_SONUNCU_ayni():
    assert len(PACK.connective_styles) == 8
    assert PACK.connective_styles[0].startswith("BEKLENTİYİ KIR")
    assert PACK.connective_styles[-1].startswith("SON ANDA ÇEVİR")


def test_yorum_yonergeleri_TAM_4():
    assert len(PACK.comment_styles) == 4
    assert PACK.comment_styles[0].startswith("İKİLİ SORU")


def test_asinmis_kaliplar_BIREBIR():
    assert "ama asıl garip olan şu" in PACK.overused
    assert "inanılmaz ama gerçek" in PACK.overused


def test_kalip_orintuleri_GERCEK_KACAGI_hala_yakalar():
    """Bölüm #2'de yaşanan gerçek kaçak: 'bunu biliyor muydunuz' dizgesi yasaklıydı
    ama LLM '...sahip olduğunu biliyor muydunuz?' yazıp DENETİMDEN GEÇTİ."""
    import re
    from short_bot.text_normalize import locale_fold
    metin = locale_fold("Kalbin kendi elektriğini ürettiğini biliyor muydunuz", "tr")
    assert any(re.search(op.pattern, metin, re.IGNORECASE)
               for op in PACK.overused_patterns)


def test_varsayilan_seri_basligi():
    assert PACK.default_series_title == "İlginç Bilgiler"


def test_seri_sablonlari_RENDER_EDILEBILIR():
    s = PACK.series
    assert s.header.format(title="Bilinmeyen Tarih", no=47, next_no=48)
    assert s.paying_promise.format(promise="fener balığının ışığı")
    assert s.announce_arc.format(arc_title="Derin Deniz", arc_total=3)
    assert s.finale.format(arc_title="Derin Deniz", next_no=48)
    assert s.planned_loop.format(next_no=48, next_topic="simbiyotik bakteri")
    assert s.chain_loop.format(next_no=48)
    assert s.teaser_fallback.format(title="Bilinmeyen Tarih")


def test_meta_tail_TURKCE_meta_dili_soker():
    import re
    metin = "Ev kedilerinden iyi olmalarının bilimsel sırrını 2. bölümde açıklıyoruz."
    assert re.search(PACK.meta_tail_pattern, metin, re.IGNORECASE)
```

- [ ] **Step 3: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_lang_pack_tr_golden.py -q`
Expected: FAIL — `ImportError: cannot import name 'load_pack'`

- [ ] **Step 4: `load_pack` yükleyicisini ekle**

`src/short_bot/lang_pack.py` sonuna:

```python
# Kodla gelen varsayılan paketler. Kullanıcının yazılabilir dizini ÖNCELİKLİ:
# paketlenmiş Electron uygulamasında kurulum dizini salt-okunur olabilir ve üretilen
# paketlerin bir yere yazılması gerekir.
_BUILTIN_DIR = Path(__file__).parent / "langpacks"

_user_dir: Path | None = None


def set_user_dir(path: Path | None) -> None:
    """Üretilen paketlerin okunacağı/yazılacağı dizin (SHORTBOT_CONFIG_DIR/langpacks)."""
    global _user_dir
    _user_dir = path
    load_pack.cache_clear()


def pack_path(lang: str, *, user: bool = False) -> Path:
    base = (_user_dir if user else _BUILTIN_DIR)
    if base is None:
        raise RuntimeError("kullanıcı dizini kurulmadı (set_user_dir)")
    return base / f"{lang}.json"


@lru_cache(maxsize=8)
def load_pack(lang: str) -> LangPack:
    """Dil paketini yükle. Bulunamazsa RuntimeError.

    SESSİZ DÜŞME YASAK: Türkçe pakete DÜŞMEZ. Almanca kanalın Türkçe çip basması —
    düzeltmeye çalıştığımız hatanın ta kendisi. Paket yoksa üretilmeli
    (lang_pack_gen.generate_pack), üretilemiyorsa kanal kurulmamalı.
    """
    for p in ([pack_path(lang, user=True)] if _user_dir else []) + [pack_path(lang)]:
        if p.exists():
            pack = LangPack.model_validate(json.loads(p.read_text(encoding="utf-8")))
            hatalar = validate_pack(pack)
            if hatalar:
                raise RuntimeError(
                    f"{p} geçersiz dil paketi:\n  " + "\n  ".join(hatalar))
            return pack
    raise RuntimeError(
        f"'{lang}' dil paketi yok. Panelden Ayarlar → Dil paketleri'nden üretin "
        f"(Sonnet 5 ile ~1 dakika). Türkçe pakete DÜŞÜLMEZ — Almanca kanalın "
        f"Türkçe abone çipi basması sessiz bir bozulmadır.")
```

`lang_pack.py`'nin başındaki import'lara `from functools import lru_cache` ve
`from pathlib import Path` zaten var (Step 3'te eklendi).

- [ ] **Step 5: Testi koş**

Run: `python -m pytest tests/test_lang_pack_tr_golden.py -q`
Expected: PASS (10 test)

Kırılırsa `tr.json` yanlış çıkarılmıştır — hangi alan kırıldıysa kaynak sabitle
karakter karakter karşılaştır.

- [ ] **Step 6: Sessiz-düşme yasağını test et**

`tests/test_lang_pack.py` sonuna ekle:

```python
def test_paket_YOKSA_TURKCEYE_DUSMEZ():
    """SESSİZ BOZULMANIN TA KENDİSİ: Almanca kanal Türkçe çip basıyordu.
    Paket yoksa net hata verilir — sessizce Türkçe döndürülmez."""
    from short_bot.lang_pack import load_pack, set_user_dir
    # TEST YALITIMI: `_user_dir` modül-global ve `load_pack` lru_cache'li. Bir web
    # testi daha önce set_user_dir çağırdıysa bu test onun dizinini görür ve sonuç
    # test SIRASINA bağlı olur. Açıkça sıfırlıyoruz (cache de temizlenir).
    set_user_dir(None)
    with pytest.raises(RuntimeError, match="dil paketi yok"):
        load_pack("fr")     # kodla gelmiyor, üretilmedi
```

> **Uygulayıcıya not:** `fr.json` kodla GELMEZ ve bu planda üretilmez (yalnız `tr`/`en`
> kodla gelir, `de` Task 10'da üretilir). Yani bu test kalıcı olarak geçerlidir.
>
> Aynı yalıtım gerekçesiyle `tests/conftest.py`'ye bir autouse fixture ekle — aksi
> hâlde dil paketi testleri birbirini kirletir:
>
> ```python
> @pytest.fixture(autouse=True)
> def _lang_pack_yalitimi():
>     """Her testten sonra dil paketi global durumunu sıfırla.
>
>     `lang_pack._user_dir` modül-global ve `load_pack` lru_cache'li; web testleri
>     set_user_dir çağırıyor. Sıfırlanmazsa sonuçlar test SIRASINA bağlı olur."""
>     yield
>     from short_bot.lang_pack import set_user_dir
>     set_user_dir(None)
> ```

Run: `python -m pytest tests/test_lang_pack.py -q`
Expected: PASS

- [ ] **Step 7: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 8: Commit**

```bash
git add src/short_bot/lang_pack.py src/short_bot/langpacks/tr.json
git add -f tests/test_lang_pack_tr_golden.py tests/test_lang_pack.py
git commit -m "feat(lang): tr.json (bugunku sabitlerin birebir kopyasi) + load_pack + ALTIN TEST"
```

---

## Task 5: `reel_phrases` paketten beslensin

**Files:**
- Modify: `src/short_bot/reel_phrases.py`
- Modify: `src/short_bot/reel_narration.py:12,51,52,313,317`
- Test: `tests/test_reel_phrases.py` (mevcut — güncellenir), `tests/test_lang_pack_de.py` (yeni)

- [ ] **Step 1: Almanca testini yaz**

`tests/test_lang_pack_de.py` (elle yazılmış fixture — LLM çağrılmaz):

```python
"""Almanca paketle uçtan uca: denetçi GERÇEKTEN yakalıyor mu?

ÖLÇÜLDÜ (düzeltmeden önce): _fold Türkçe için I->ı yaptığı için Almanca metin
"ıch zeige euch" oluyordu ve r"\\bich\\b" ASLA eşleşmiyordu. Yani mükemmel bir
Almanca kalıp listesi bile ölü doğardı. Bu test o zinciri baştan sona kanıtlar.
"""
import pytest

from short_bot.lang_pack import LangPack
from short_bot.reel_phrases import find_overused, pick_styles

DE = LangPack.model_validate({
    "lang": "de",
    "cta_texts": ["Täglich neu — ABONNIEREN", "Morgen mehr — ABO",
                  "Serie läuft — ABO", "Teil 2 morgen — ABO"],
    "trade_cta": "#{no} morgen — ABO",
    "default_series_title": "Kuriose Fakten",
    "comment_styles": ["A", "B", "C", "D"],
    "connective_styles": [f"S{i}" for i in range(8)],
    "series": {
        "header": "Folge {no} von '{title}'. Nächste: {next_no}.",
        "paying_promise": "Löse dieses Versprechen ein: \"{promise}\"",
        "announce_arc": "Serie '{arc_title}', {arc_total} Folgen.",
        "finale": "Letzte Folge von '{arc_title}'. Folge {next_no} neu.",
        "planned_loop": "Thema von Folge {next_no}: \"{next_topic}\"",
        "chain_loop": "Öffne eine Tür — Antwort in Folge {next_no}.",
        "teaser_fallback": "Eine Folge der Serie '{title}'.",
    },
    "overused": ["wusstest du schon", "hallo leute", "heute zeige ich euch",
                 "bleibt dran", "vergesst nicht zu abonnieren"],
    "overused_patterns": [
        {"label": "Wusstest du schon? (beantwortbare Ja/Nein-Frage — kein Hook)",
         "pattern": r"\bwusstest du\b"},
        {"label": "Hallo Leute (Kanal-Intro — verschwendet die erste Sekunde)",
         "pattern": r"\bhallo leute\b"},
        {"label": "Heute zeige ich euch (Ankündigung, kein Versprechen)",
         "pattern": r"\bheute zeige ich\b"},
        {"label": "Seid ihr bereit? (leere Floskel)",
         "pattern": r"\bseid ihr bereit\b"},
    ],
    "meta_tail_pattern": r"\s*[—,;:-]*\s*(in\s+)?folge\s+\d+[^.]*?(erkl|zeig|sag)\w*\s*[.!?]?\s*$",
})


def test_almanca_KALIP_yakalanir():
    """Bu, düzeltmeden önce ÇALIŞMIYORDU — 'Ich' -> 'ıch' oluyordu."""
    assert find_overused("Heute zeige ich euch etwas Verrücktes", pack=DE)


def test_wusstest_du_schon_yakalanir():
    assert find_overused("Wusstest du schon, dass Bier älter ist als Brot?", pack=DE)


def test_temiz_almanca_metin_GECER():
    assert find_overused("Ein Bier braucht neun Monate Zeit im Keller.", pack=DE) == []


def test_TURKCE_kaliplar_ALMANCA_pakette_ARANMAZ():
    # Almanca kanalda Türkçe denetçi koşmamalı.
    assert find_overused("Bunu biliyor muydunuz", pack=DE) == []


def test_pick_styles_ALMANCA_havuzdan_secer():
    secilen = pick_styles(42, 4, pack=DE)
    assert len(secilen) == 4
    assert all(s in DE.connective_styles for s in secilen)


def test_pick_styles_DETERMINISTIK():
    assert pick_styles(7, 4, pack=DE) == pick_styles(7, 4, pack=DE)
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_lang_pack_de.py -q`
Expected: FAIL — `TypeError: find_overused() got an unexpected keyword argument 'pack'`

- [ ] **Step 3: `reel_phrases.py`'yi paketten besle**

`src/short_bot/reel_phrases.py` — tamamını değiştir:

```python
"""Kalıp tekrarını kıran ifade havuzu + aşınmış kalıp denetçisi.

NEDEN VAR: prompt, mikro-döngü bağlaçlarını BİREBİR CÜMLE olarak veriyordu ve LLM
onları olduğu gibi kopyalıyordu. Ölçüldü: üç anlatımın İKİSİNDE aynı iki cümle
kelimesi kelimesine geçiyordu.

İKİ KATMANLI ÇÖZÜM:
  1. ÜRETİM: prompt cümle değil YÖNERGE veriyor; yönergeler seed'e göre dönüyor.
  2. DENETİM: üretilen anlatım aşınmış kalıplara karşı taranır; bulunursa LLM'e ne
     yaptığı söylenip yeniden yazdırılır. Prompt'a "kullanma" demek yetmiyor.

Yönergeler ve kalıplar artık DİL PAKETİNDEN geliyor (lang_pack). Türkçe sabit
oldukları sürece Almanca kanalda denetçi hiçbir şey yakalayamıyordu — ve bu SESSİZDİ.
"""
from __future__ import annotations

import hashlib
import re

from short_bot.text_normalize import locale_fold


def _norm(text: str, lang: str) -> str:
    """Dile duyarlı küçültme + noktalama temizliği (kalıp eşleşmesi için).

    Dil ŞART: locale_fold Türkçe için 'I' → 'ı' yapıyor. Almanca metinde bu 'Ich'i
    'ıch' yapar ve r'\\bich\\b' asla eşleşmez — denetçi çalışıyor görünüp sıfır şey
    bulur.
    """
    return re.sub(r"[^\w\s]", " ", locale_fold(text, lang)).replace("  ", " ")


def pick_styles(seed: int, n: int = 4, *, pack) -> list[str]:
    """Bu videonun göreceği bağlaç YÖNERGELERİ. Deterministik: aynı seed → aynı set.

    Havuzun tamamını her videoya vermek işe yaramaz — LLM ilk örneklere yapışıyor.
    """
    havuz = pack.connective_styles
    n = max(1, min(n, len(havuz)))
    idx = list(range(len(havuz)))
    # Deterministik karıştırma (Fisher-Yates, hash-güdümlü).
    for i in range(len(idx) - 1, 0, -1):
        h = int(hashlib.sha1(f"{seed}:conn:{i}".encode()).hexdigest(), 16)
        j = h % (i + 1)
        idx[i], idx[j] = idx[j], idx[i]
    return [havuz[i] for i in idx[:n]]


def find_overused(text: str, *, pack) -> list[str]:
    """Metindeki aşınmış kalıplar: hem BİREBİR ifadeler hem ÖRÜNTÜLER.

    Örüntü katmanı şart: dizge denetimi "bunu biliyor muydunuz"u yakalıyor ama
    "...sahip olduğunu biliyor muydunuz?"u KAÇIRIYOR (gerçek kaçak, bölüm #2) —
    yasak olan şey dizge değil, kalıbın kendisi.
    """
    t = _norm(text, pack.lang)
    bulunan = [p for p in pack.overused if _norm(p, pack.lang) in t]
    bulunan += [op.label for op in pack.overused_patterns
                if re.search(op.pattern, t, re.IGNORECASE)]
    return bulunan
```

- [ ] **Step 4: `reel_narration.py` çağrılarını güncelle**

`src/short_bot/reel_narration.py`:

- satır 12: `from short_bot.reel_phrases import OVERUSED, find_overused, pick_styles`
  → `from short_bot.reel_phrases import find_overused, pick_styles`
- `pick_styles(seed, 4)` çağıran fonksiyona `pack` parametresi eklenir;
  `pick_styles(seed, 4, pack=pack)`
- satır 52: `banned_block = "\n".join(f'    ✗ "{p}"' for p in OVERUSED)`
  → `banned_block = "\n".join(f'    ✗ "{p}"' for p in pack.overused)`
- satır 313/317: `find_overused(n.full_text())` → `find_overused(n.full_text(), pack=pack)`
- `write(...)` imzasına `pack` eklenir; çağıran `reel.py` `load_pack(channel.language)`
  ile geçirir.

> **Uygulayıcıya not:** `reel_narration.py`'yi aç, `pick_styles`/`OVERUSED`/
> `find_overused` kullanan fonksiyonların imzalarını izle ve `pack`'i en dıştaki
> genel giriş noktasına (`write`) parametre olarak ekleyip aşağı ilet. Yeni bir
> yükleme yapma — paket bir kez yüklenip taşınır.

- [ ] **Step 5: Mevcut Türkçe testleri güncelle**

`tests/test_reel_phrases.py` — `pick_styles(seed, n)` ve `find_overused(text)`
çağrılarına `pack=load_pack("tr")` ekle. **Beklenen değerler DEĞİŞMEZ** — altın test
tr.json'un birebir kopya olduğunu zaten kanıtladı.

- [ ] **Step 6: Testleri koş**

Run: `python -m pytest tests/test_lang_pack_de.py tests/test_reel_phrases.py tests/test_reel_narration.py -q`
Expected: PASS

- [ ] **Step 7: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 8: Commit**

```bash
git add src/short_bot/reel_phrases.py src/short_bot/reel_narration.py src/short_bot/reel.py
git add -f tests/test_lang_pack_de.py tests/test_reel_phrases.py
git commit -m "feat(lang): reel_phrases paketten beslenir - Almanca klise denetcisi artik GERCEKTEN yakaliyor"
```

---

## Task 6: `reel_series` + `reel_subscribe` paketten beslensin

**Files:**
- Modify: `src/short_bot/reel_series.py`
- Modify: `src/short_bot/reel_subscribe.py`
- Modify: `src/short_bot/pipeline.py:1296`, `src/short_bot/web/routes/series.py:85,93,94`, `src/short_bot/reel.py:259`
- Test: `tests/test_lang_pack_de.py` (genişletilir), mevcut `tests/test_reel_series.py`, `tests/test_reel_subscribe.py`

- [ ] **Step 1: Almanca ekran testini yaz**

`tests/test_lang_pack_de.py` sonuna ekle (DE paketi yukarıda tanımlı):

```python
def test_almanca_rozet_NOKTASIZ_I():
    """GÖRÜNÜR HATA: turkish_upper 'Bier Garten' -> 'BİER GARTEN' yapıyordu.
    Rozet, kanalın özenli olduğunu SÖYLEMESİ gereken şeydir."""
    from short_bot.reel_series import episode_badge
    assert episode_badge("Bier Garten", 47, pack=DE) == "BIER GARTEN #47"


def test_almanca_trade_cta():
    from short_bot.reel_series import trade_cta
    assert trade_cta(48, pack=DE) == "#48 morgen — ABO"


def test_almanca_CTA_24_karaktere_sigar():
    from short_bot.lang_pack import CTA_MAX_CHARS
    for c in DE.cta_texts:
        assert len(c) <= CTA_MAX_CHARS
    assert len(DE.trade_cta.replace("{no}", "48")) <= CTA_MAX_CHARS


def test_almanca_seri_yonergesi_ALMANCA():
    from short_bot.reel_series import EpisodePlan, series_directive
    plan = EpisodePlan(episode_no=47, arc_pos=2, continue_from="das Bakterium im Licht")
    d = series_directive(plan, "Kuriose Fakten", pack=DE)
    assert "Folge 47" in d
    assert "das Bakterium im Licht" in d
    assert "BÖLÜM" not in d, "Türkçe yönerge sızdı"


def test_almanca_meta_dili_SOKULUR():
    """clean_open_loop Almanca meta dilini sökmeli — sökmezse o metin bir sonraki
    bölümün ÜRETİM KONUSU olarak kullanılır ve senaryo yazıcısını yanıltır."""
    from short_bot.reel_series import clean_open_loop
    ham = "Das leuchtende Bakterium erkläre ich in Folge 48."
    assert clean_open_loop(ham, pack=DE) == "Das leuchtende Bakterium"


def test_almanca_abone_bitleri_ALMANCA(monkeypatch):
    from short_bot.reel_subscribe import build_subscribe_bits

    class _Reel:
        series_enabled = False
        comment_question = True
        cta_enabled = True
        cta_text_custom = ""

    class _Ch:
        language = "de"
        reel = _Reel()

    monkeypatch.setattr("short_bot.reel_subscribe.load_pack", lambda lang: DE)
    bits = build_subscribe_bits(_Ch(), seed=3)
    assert bits.cta_text in DE.cta_texts
    assert "ABONE OL" not in bits.cta_text, "Türkçe çip Almanca kanalda"
    assert bits.comment_line in DE.comment_styles
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_lang_pack_de.py -q`
Expected: FAIL — `TypeError: episode_badge() got an unexpected keyword argument 'pack'`

- [ ] **Step 3: `reel_series.py`'yi paketten besle**

Değişiklikler (docstring'ler ve pedagojik yorumlar **aynen korunur**):

```python
from short_bot.text_normalize import locale_upper


def episode_badge(series_title: str, episode_no: int, *, pack) -> str:
    """Feed kimliği rozeti: "BİLİNMEYEN TARİH #47". Kare sıfırda görünür.

    locale_upper ŞART: Python'un .upper()'ı Türkçede 'i' → 'I' yapar (yanlış), ama
    Almancada 'I' → 'İ' yapmak da yanlıştır ("BİER GARTEN"). Büyütme DİLE ÖZGÜDÜR.
    """
    t = locale_upper((series_title or "").strip(), pack.lang)
    if not t:
        return f"#{episode_no}"
    rozet = f"{t} #{episode_no}"
    if len(rozet) <= BADGE_MAX_CHARS:
        return rozet
    kuyruk = f"… #{episode_no}"
    return t[:max(1, BADGE_MAX_CHARS - len(kuyruk))].rstrip() + kuyruk


def trade_cta(next_no: int, *, pack) -> str:
    """Abone isteği bir TAKASTIR: söz verilen cevap karşılığında abone."""
    return pack.trade_cta.format(no=next_no)


def series_directive(plan: EpisodePlan, series_title: str, *, pack) -> str:
    """Senaryo LLM'ine geçen seri yönergesi. Metinler dil paketinden gelir."""
    if not plan.enabled:
        return ""
    t = (series_title or pack.default_series_title).strip()
    s = pack.series
    satirlar = [s.header.format(title=t, no=plan.episode_no, next_no=plan.next_no)]
    if plan.continue_from:
        satirlar.append(s.paying_promise.format(promise=plan.continue_from,
                                                no=plan.episode_no))
    if plan.is_planned and plan.is_new_arc:
        satirlar.append(s.announce_arc.format(arc_title=plan.arc_title,
                                              arc_total=plan.arc_total,
                                              no=plan.episode_no))
    if plan.is_arc_finale:
        satirlar.append(s.finale.format(arc_title=plan.arc_title,
                                        next_no=plan.next_no, no=plan.episode_no))
        return "\n".join(satirlar)
    if plan.next_topic:
        satirlar.append(s.planned_loop.format(next_no=plan.next_no,
                                              next_topic=plan.next_topic))
        return "\n".join(satirlar)
    satirlar.append(s.chain_loop.format(next_no=plan.next_no))
    return "\n".join(satirlar)


def clean_open_loop(text: str, *, pack) -> str:
    """Meta dili ayıkla: geriye KONUNUN KENDİSİ kalsın.

    Temizlik sonrası çok az şey kalıyorsa ham metni geri ver — yanlış kırpmaktansa
    gürültülü bir tohum yeğdir.
    """
    s = (text or "").strip()
    if not s:
        return ""
    meta = re.compile(pack.meta_tail_pattern, re.IGNORECASE)
    kirpik = _TAIL.sub("", meta.sub("", s)).strip()
    if len(kirpik.split()) < 3:
        return s
    return kirpik
```

`turkish_upper` import'u, `_B`/`_V`/`_META` sabitleri silinir (`_TAIL` kalır).
`BADGE_MAX_CHARS` `lang_pack`'ten import edilir (tek kaynak).

- [ ] **Step 4: `reel_subscribe.py`'yi paketten besle**

`COMMENT_STYLES`, `CTA_TEXTS`, `CTA_MAX_CHARS` sabitleri silinir; `CTA_MAX_CHARS`
`lang_pack`'ten import edilir.

```python
from short_bot.lang_pack import CTA_MAX_CHARS, load_pack


def build_subscribe_bits(channel, seed: int, episode=None) -> SubscribeBits:
    """Abone mekanikleri. ``episode`` (EpisodePlan) verilirse SERİ modu devreye girer.

    (Mevcut docstring aynen korunur.)
    """
    reel = channel.reel
    pack = load_pack(channel.language)
    seri = episode is not None and getattr(episode, "enabled", True)

    series_directive = ""
    badge = ""
    if seri:
        from short_bot.reel_series import episode_badge
        from short_bot.reel_series import series_directive as _sd
        title = (getattr(reel, "series_title", "") or pack.default_series_title).strip()
        series_directive = _sd(episode, title, pack=pack)
        badge = episode_badge(title, episode.episode_no, pack=pack)
    elif getattr(reel, "series_enabled", False):
        title = (getattr(reel, "series_title", "") or pack.default_series_title).strip()
        series_directive = pack.series.teaser_fallback.format(title=title)

    comment_line = ""
    if getattr(reel, "comment_question", False) and not seri:
        comment_line = pack.comment_styles[
            _idx(seed, "comment", len(pack.comment_styles))]

    cta_text = ""
    if getattr(reel, "cta_enabled", False):
        custom = (getattr(reel, "cta_text_custom", "") or "").strip()
        if seri and not custom:
            from short_bot.reel_series import trade_cta
            cta_text = trade_cta(episode.next_no, pack=pack)
        else:
            cta_text = custom or pack.cta_texts[_idx(seed, "cta", len(pack.cta_texts))]
        if len(cta_text) > CTA_MAX_CHARS:
            # Paket üretim anında doğrulandığı için buraya YALNIZ cta_text_custom
            # düşebilir (kullanıcının elle girdiği metin).
            log.warning(f"  abone çipi çok uzun ({len(cta_text)} > {CTA_MAX_CHARS} "
                        f"karakter), kırpılıyor: {cta_text!r}")
            cta_text = cta_text[:CTA_MAX_CHARS].rstrip()

    return SubscribeBits(series_directive=series_directive,
                         comment_line=comment_line, cta_text=cta_text, badge=badge)
```

- [ ] **Step 5: Çağıranları güncelle**

| Yer | Değişiklik |
|---|---|
| `pipeline.py:1296` | `clean_open_loop(episode.continue_from)` → `clean_open_loop(episode.continue_from, pack=load_pack(channel.language))` |
| `web/routes/series.py:85` | `clean_open_loop(plan.continue_from)` → `..., pack=pack` (`pack = load_pack(cfg.language)`) |
| `web/routes/series.py:93` | `episode_badge(baslik, plan.episode_no)` → `..., pack=pack` |
| `web/routes/series.py:94` | `trade_cta(plan.next_no)` → `..., pack=pack` |
| `reel.py:259` | değişmez (`build_subscribe_bits` paketi kendi yükler) |

- [ ] **Step 6: Mevcut Türkçe testleri güncelle**

`tests/test_reel_series.py`, `tests/test_reel_subscribe.py` — çağrılara
`pack=load_pack("tr")` ekle. **Beklenen değerler DEĞİŞMEZ.**

- [ ] **Step 7: Testleri koş**

Run: `python -m pytest tests/test_lang_pack_de.py tests/test_reel_series.py tests/test_reel_subscribe.py -q`
Expected: PASS

- [ ] **Step 8: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 9: Commit**

```bash
git add src/short_bot/reel_series.py src/short_bot/reel_subscribe.py src/short_bot/pipeline.py src/short_bot/web/routes/series.py
git add -f tests/test_lang_pack_de.py tests/test_reel_series.py tests/test_reel_subscribe.py
git commit -m "feat(lang): reel_series + reel_subscribe paketten beslenir - Almanca rozet/cip artik Almanca"
```

---

## Task 7: TTS sadakat karşılaştırması dile duyarlı

**Files:**
- Modify: `src/short_bot/tts/fidelity.py:40,46,50,79`
- Modify: `src/short_bot/caption_align.py:47`
- Test: `tests/test_tts_fidelity.py` (mevcut — genişletilir)

- [ ] **Step 1: Testi yaz**

`tests/test_tts_fidelity.py` sonuna:

```python
def test_almanca_BUYUK_I_asimetri_yaratmaz():
    """_fold Türkçe için I->ı yapıyordu. Senaryo 'Ich' (büyük), Whisper dökümü 'ich'
    (küçük) yazarsa: 'ıch' vs 'ich' → kelime EŞLEŞMEZ ve sadakat yanlış alarm verir.
    Almanca'da 'Ich/In/Ist/Immer' çok sık."""
    from short_bot.tts.fidelity import normalize_tokens
    assert normalize_tokens("Ich", lang="de") == normalize_tokens("ich", lang="de")


def test_turkce_fold_BUGUNKU_davranis_korunur():
    from short_bot.tts.fidelity import normalize_tokens
    assert normalize_tokens("IŞIK") == ["ışık"]
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_tts_fidelity.py -q`
Expected: FAIL — `TypeError: normalize_tokens() got an unexpected keyword argument 'lang'`

- [ ] **Step 3: `fidelity.py`'yi güncelle**

```python
from short_bot.text_normalize import locale_fold


def _fold(text: str, lang: str = "tr") -> str:
    """Dile duyarlı küçültme (bkz. text_normalize.locale_fold)."""
    return locale_fold(text, lang)


def normalize_tokens(text: str, lang: str = "tr") -> list[str]:
    """Karşılaştırılabilir kelime dizisi.

    Dil ŞART: Türkçe eşlemesi 'I' → 'ı' yapıyor. Almanca senaryoda büyük 'Ich',
    Whisper dökümünde küçük 'ich' geldiğinde 'ıch' ≠ 'ich' olur ve sadakat denetimi
    var olmayan bir hata bildirir.
    """
    out: list[str] = []
    for raw in _fold(text, lang).split():
        w = re.sub(r"[^\w]", "", unicodedata.normalize("NFC", raw), flags=re.UNICODE)
        if not w:
            continue
        out.append(_NUMBERS.get(w, w))
    return out
```

`fidelity.py:79`'daki karşılaştırma fonksiyonuna `lang: str = "tr"` parametresi eklenir
ve `normalize_tokens(script, lang), normalize_tokens(heard, lang)` çağrılır. Çağıran
`reel.py` `channel.language` geçirir.

`caption_align.py:47` — `normalize_tokens(word)` → `normalize_tokens(word, lang)`;
fonksiyona `lang: str = "tr"` parametresi eklenir, çağıran `channel.language` geçirir.

- [ ] **Step 4: Testleri koş**

Run: `python -m pytest tests/test_tts_fidelity.py tests/test_caption_align.py -q`
Expected: PASS

- [ ] **Step 5: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/tts/fidelity.py src/short_bot/caption_align.py src/short_bot/reel.py
git add -f tests/test_tts_fidelity.py
git commit -m "fix(lang): TTS sadakat karsilastirmasi dile duyarli (Almanca 'Ich' asimetrisi)"
```

---

## Task 8: İngilizce paket

**Files:**
- Create: `src/short_bot/langpacks/en.json`
- Test: `tests/test_lang_pack_en.py` (yeni)

- [ ] **Step 1: `en.json`'u yaz**

Türkçe paketin İngilizce **muadili** — çeviri değil. Yasaklı kalıplar gerçek İngilizce
Shorts klişeleri olmalı:

```json
{
  "lang": "en",
  "cta_texts": [
    "New daily — SUBSCRIBE",
    "More tomorrow — SUB",
    "Series runs — SUBSCRIBE",
    "Part 2 tomorrow — SUB"
  ],
  "trade_cta": "#{no} tomorrow — SUBSCRIBE",
  "default_series_title": "Strange Facts",
  "comment_styles": [
    "BINARY QUESTION: ask a question comparing two things from the video, answerable with a single letter (A/B). Pattern: 'Which is crazier: A or B? Just type the letter.'",
    "PERSONAL RECALL: ask something the viewer can answer in one word from their own experience ('How old were you when you learned this?').",
    "VALIDATION: write a line that invites agreement OR objection — both produce comments ('Tell me I'm not the only one who got chills').",
    "FIND THE GAP: 'I left out one detail on purpose — can you find it?' Send the viewer back into the video. (NEVER state false information — authority is the product.)"
  ],
  "connective_styles": [
    "BREAK THE EXPECTATION: imply the explanation now in the viewer's head is WRONG. Don't reveal the right one yet.",
    "SCALE UP: hint that the number you just gave is small compared to what's coming.",
    "HIDDEN ACTOR: announce there's a cause BEHIND this that you haven't named yet.",
    "COUNTDOWN: say a threshold is approaching — cut before 'and then'.",
    "OPEN A CONTRADICTION: signal that a fact contradicts what you just said.",
    "IMPLY A COST: say this ability has a price. Withhold the price.",
    "MAKE IT PERSONAL: imply this is happening in the viewer's own body or life.",
    "TURN AT THE LAST MOMENT: start with 'but' and invert the picture you just painted."
  ],
  "series": {
    "header": "This is EPISODE {no} of '{title}'. The next one will be number {next_no}.",
    "paying_promise": "THIS EPISODE PAYS A PROMISE. The previous episode promised the viewer:\n  \"{promise}\"\nThe PEAK of the video (peak_beat) must pay exactly THIS promise. The viewer subscribed for this answer; tell them anything else and the trade is broken.",
    "announce_arc": "ANNOUNCE THE SERIES: this is the FIRST episode of a {arc_total}-EPISODE series called '{arc_title}'. Somewhere in the narration (not the hook — after the peak), say in one sentence that the series runs {arc_total} episodes and where it's going. Nobody subscribes to a video; people subscribe to a SERIES.",
    "finale": "THIS IS THE LAST EPISODE OF '{arc_title}'. The arc closes here:\n  • Leave 'open_loop' EMPTY — the next episode brings a NEW topic.\n  • But the series is NOT over: after the peak, say in one sentence that episode {next_no} arrives tomorrow with a new subject.",
    "planned_loop": "OPEN DOOR — ALREADY WRITTEN, DO NOT INVENT. The topic of the next episode ({next_no}) is:\n  \"{next_topic}\"\n  • Put THIS TOPIC verbatim into 'open_loop'.\n  • Also name it IN THE BEAT AFTER THE PEAK, in your own words, and hand it to episode {next_no}. NOT in the closing — the subscribe chip appears on screen exactly then; if the promise hasn't been spoken yet, the ask lands on nothing.\n    ✗ 'But the story doesn't end here.'   ← says nothing about what's coming\n    ✓ 'But that light isn't the fish's own — the bacterium making it is episode {next_no}.'",
    "chain_loop": "OPEN DOOR — MANDATORY. This episode pays its own peak IN FULL, but does not close: it leaves a new and SPECIFIC subject that the peak itself exposed, and its answer is in episode {next_no}. This requires TWO SEPARATE OUTPUTS:\n\n  1) 'open_loop' FIELD = THE NEXT EPISODE'S TOPIC (never spoken).\n     This text will be used VERBATIM as episode {next_no}'s production topic.\n     No episode numbers, no 'next time', no 'I'll explain' — the topic ONLY.\n     ✗ 'I'll reveal this secret in episode {next_no}.'\n     ✓ 'The symbiotic bacterium that produces the anglerfish's light'\n\n  2) THE BEAT AFTER THE PEAK = the SPOKEN cliffhanger.\n     Name the same subject THERE, in your own words, and hand it to episode {next_no}. NOT in the closing — the subscribe chip appears exactly then; an unspoken promise makes the ask land on nothing.\n     ✗ 'But the story doesn't end here.'\n     ✓ 'But that light isn't the fish's own — the bacterium making it is episode {next_no}.'\n\n  BOTH must share the same subject (overlapping words): the field NAMES it, the beat SPEAKS it.",
    "teaser_fallback": "This is an episode of the '{title}' series. End the closing with an OPEN LOOP / teaser that makes the viewer curious about the next episode ('the next one is even stranger')."
  },
  "overused": [
    "but here's the crazy part",
    "and this is where it gets weird",
    "the reason will shock you",
    "you won't believe what happens next",
    "wait for it",
    "let that sink in",
    "and that's not even the craziest part"
  ],
  "overused_patterns": [
    {"label": "Did you know …? (answerable yes/no question — not a hook)", "pattern": "\\bdid you know\\b"},
    {"label": "Have you ever wondered …? (same pattern)", "pattern": "\\bhave you ever wondered\\b"},
    {"label": "Hey guys / what's up guys (channel intro — burns the first second)", "pattern": "\\b(hey|what'?s up|hello)\\s+(guys|everyone|folks)\\b"},
    {"label": "Today I'm going to show you … (an agenda, not a promise)", "pattern": "\\btoday (i'?m going to|i will|we'?re going to)\\b"},
    {"label": "Are you ready? (empty filler)", "pattern": "\\bare you ready\\b"}
  ],
  "meta_tail_pattern": "\\s*[—,;:-]*\\s*((in|on)\\s+)?(episode\\s+\\d+|the\\s+next\\s+(episode|part)|tomorrow)[^.]*?(explain|show|reveal|tell|cover)\\w*\\s*[.!?]?\\s*$"
}
```

- [ ] **Step 2: Testi yaz**

`tests/test_lang_pack_en.py`:

```python
"""İngilizce paket — elle yazıldı, LLM üretmedi (bildiğimiz dil)."""
import re

from short_bot.lang_pack import CTA_MAX_CHARS, load_pack, validate_pack
from short_bot.reel_phrases import find_overused
from short_bot.reel_series import clean_open_loop, episode_badge, trade_cta

EN = load_pack("en")


def test_gecerli():
    assert validate_pack(EN) == []


def test_CTA_24_karaktere_sigar():
    for c in EN.cta_texts:
        assert len(c) <= CTA_MAX_CHARS, c
    assert len(EN.trade_cta.replace("{no}", "48")) <= CTA_MAX_CHARS


def test_rozet_NOKTASIZ_I():
    assert episode_badge("Big History", 47, pack=EN) == "BIG HISTORY #47"


def test_trade_cta():
    assert trade_cta(48, pack=EN) == "#48 tomorrow — SUBSCRIBE"


def test_ingilizce_KLISE_yakalanir():
    assert find_overused("Did you know that octopuses have three hearts?", pack=EN)
    assert find_overused("Hey guys, today I'm going to show you something", pack=EN)


def test_temiz_metin_gecer():
    assert find_overused("An octopus has three hearts and blue blood.", pack=EN) == []


def test_meta_dili_sokulur():
    ham = "The symbiotic bacterium I'll explain in episode 48."
    assert clean_open_loop(ham, pack=EN) == "The symbiotic bacterium"
```

- [ ] **Step 3: Testi koş**

Run: `python -m pytest tests/test_lang_pack_en.py -q`
Expected: PASS

Kırılırsa `en.json`'daki `meta_tail_pattern` ya da CTA uzunlukları hatalıdır —
doğrulama hata mesajı hangi alan olduğunu söyler.

- [ ] **Step 4: Commit**

```bash
git add src/short_bot/langpacks/en.json
git add -f tests/test_lang_pack_en.py
git commit -m "feat(lang): en.json - Ingilizce paket (elle yazildi, gercek Ingilizce Shorts kliseleri)"
```

---

## Task 9: Paket üretimi — Claude CLI + Sonnet 5

**Files:**
- Create: `src/short_bot/lang_pack_gen.py`
- Test: `tests/test_lang_pack_gen.py` (yeni)

- [ ] **Step 1: Testi yaz**

`tests/test_lang_pack_gen.py`:

```python
"""Paket üretimi — Sonnet 5, Claude CLI üzerinden.

Aktif backend openrouter olduğu için resolve_ai_call baypas edilir. Bu, kod tabanında
kanıtlanmış bir desen: niche_finder.py:158-179 aynısını yapıyor (önce Claude CLI,
patlarsa OpenRouter). Düşme yolu aynı modeli kullanır — openrouter_models["script"]
zaten anthropic/claude-sonnet-5.

Gerçek LLM ÇAĞRILMAZ: sahte `invoke` enjekte edilir.
"""
import json

import pytest

from short_bot.lang_pack import LangPack, validate_pack
from short_bot.lang_pack_gen import generate_pack

# Geçerli bir Almanca paket (test_lang_pack_de.py'deki DE ile aynı şekil)
GECERLI = {
    "lang": "de",
    "cta_texts": ["Täglich neu — ABONNIEREN", "Morgen mehr — ABO",
                  "Serie läuft — ABO", "Teil 2 morgen — ABO"],
    "trade_cta": "#{no} morgen — ABO",
    "default_series_title": "Kuriose Fakten",
    "comment_styles": ["A", "B", "C", "D"],
    "connective_styles": [f"S{i}" for i in range(8)],
    "series": {
        "header": "Folge {no} von '{title}'. Nächste: {next_no}.",
        "paying_promise": "Löse ein: \"{promise}\"",
        "announce_arc": "Serie '{arc_title}', {arc_total} Folgen.",
        "finale": "Letzte Folge von '{arc_title}'. Folge {next_no} neu.",
        "planned_loop": "Thema von Folge {next_no}: \"{next_topic}\"",
        "chain_loop": "Antwort in Folge {next_no}.",
        "teaser_fallback": "Eine Folge der Serie '{title}'.",
    },
    "overused": ["wusstest du schon", "hallo leute", "heute zeige ich euch",
                 "bleibt dran", "vergesst nicht"],
    "overused_patterns": [
        {"label": "Wusstest du schon?", "pattern": r"\bwusstest du\b"},
        {"label": "Hallo Leute", "pattern": r"\bhallo leute\b"},
        {"label": "Heute zeige ich", "pattern": r"\bheute zeige ich\b"},
        {"label": "Seid ihr bereit?", "pattern": r"\bseid ihr bereit\b"},
    ],
    "meta_tail_pattern": r"\bin\s+folge\s+\d+\b.*$",
}


def test_gecerli_paket_URETILIR():
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw)
        return json.dumps(GECERLI, ensure_ascii=False)

    pack = generate_pack("de", invoke=_invoke)
    assert isinstance(pack, LangPack)
    assert validate_pack(pack) == []
    assert pack.lang == "de"
    # SONNET, Claude CLI üzerinden:
    assert cagri[0]["model"] == "sonnet"
    assert cagri[0]["backend"] == "claude_cli"


def test_TURKCE_paket_PROMPTA_referans_verilir():
    """'Çevir' demiyoruz, 'bu dilin kendi muadilini yaz' diyoruz — ama modelin neyin
    muadilini yazacağını görmesi lazım."""
    gorulen = {}

    def _invoke(prompt, **kw):
        gorulen["prompt"] = prompt
        return json.dumps(GECERLI, ensure_ascii=False)

    generate_pack("de", invoke=_invoke)
    p = gorulen["prompt"]
    assert "ABONE OL" in p, "Türkçe paket referans olarak verilmedi"
    assert "24" in p, "CTA karakter sınırı prompt'ta söylenmedi"
    assert "Almanca" in p or "German" in p or "de" in p


def test_GECERSIZ_paket_HATALARLA_yeniden_denenir():
    """Doğrulama hataları prompt'a geri verilir ve bir kez daha denenir."""
    uzun = dict(GECERLI, cta_texts=["A" * 30, "b", "c", "d"])
    promptlar = []

    def _invoke(prompt, **kw):
        promptlar.append(prompt)
        return json.dumps(uzun if len(promptlar) == 1 else GECERLI, ensure_ascii=False)

    pack = generate_pack("de", invoke=_invoke)
    assert validate_pack(pack) == []
    assert len(promptlar) == 2
    assert "24" in promptlar[1], "hata geri bildirilmedi"


def test_IKI_deneme_de_duserse_RUNTIME_ERROR():
    """SESSİZ KABUL YOK. Geçersiz paket kaydedilirse Almanca kanal bozuk çalışır."""
    uzun = dict(GECERLI, cta_texts=["A" * 30, "b", "c", "d"])

    def _invoke(prompt, **kw):
        return json.dumps(uzun, ensure_ascii=False)

    with pytest.raises(RuntimeError, match="dil paketi üretilemedi"):
        generate_pack("de", invoke=_invoke)


def test_CLAUDE_CLI_patlarsa_OPENROUTERA_duser():
    from short_bot.claude_cli import ClaudeCliError
    cagrilar = []

    def _invoke(prompt, **kw):
        cagrilar.append(kw)
        if kw["backend"] == "claude_cli":
            raise ClaudeCliError("claude binary not found")
        return json.dumps(GECERLI, ensure_ascii=False)

    pack = generate_pack("de", invoke=_invoke,
                         openrouter_model="anthropic/claude-sonnet-5",
                         openrouter_key="k")
    assert validate_pack(pack) == []
    assert cagrilar[0]["backend"] == "claude_cli"
    assert cagrilar[1]["backend"] == "openrouter"
    # AYNI MODEL, farklı yol:
    assert "sonnet" in cagrilar[1]["model"]


def test_desteklenmeyen_dil_RED():
    with pytest.raises(ValueError):
        generate_pack("zz", invoke=lambda *a, **k: "{}")
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_lang_pack_gen.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'short_bot.lang_pack_gen'`

- [ ] **Step 3: `lang_pack_gen.py`'yi yaz**

```python
"""Dil paketi üretimi — Sonnet 5, Claude CLI üzerinden.

MODEL SEÇİMİ: aktif backend `openrouter` (config/settings.yaml) olduğu için
`resolve_ai_call` her rol için OpenRouter döndürür. Sonnet 5'i Claude CLI'dan (abonelik,
marjinal maliyet yok) çekmek için baypas ediyoruz. Bu, kod tabanında kanıtlanmış bir
desen — niche_finder.py aynısını yapıyor. CLI yoksa OpenRouter'daki
anthropic/claude-sonnet-5'e düşülür: AYNI MODEL, farklı yol.

Paket dil başına BİR KEZ üretilip dosyaya yazılır; maliyet önemsiz.
"""
from __future__ import annotations

import json
import logging

from short_bot.claude_cli import ClaudeCliError, _extract_json, _invoke_raw
from short_bot.lang_pack import LangPack, load_pack, validate_pack
from short_bot.locale import LANGUAGE_NAMES, SUPPORTED_LANGUAGES

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 2


def _prompt(lang: str, ref_json: str, hatalar: list[str]) -> str:
    ad = LANGUAGE_NAMES.get(lang, lang)
    p = f"""Bir YouTube Shorts otomasyon sisteminin DİL PAKETİNİ üreteceksin.

HEDEF DİL: {ad} ({lang})

Aşağıda TÜRKÇE paket REFERANS olarak veriliyor. Görevin ÇEVİRMEK DEĞİL — aynı işlevin
{ad} dilindeki KENDİ MUADİLİNİ yazmak. Özellikle yasaklı kalıplar (overused,
overused_patterns) {ad} YouTube Shorts'unun GERÇEK klişeleri olmalı; Türkçe listenin
çevirisi değil. ({ad} için tipik olanlar: kanal açılış selamı, cevaplanabilir evet/hayır
sorusu şeklindeki sahte hook, "bugün size göstereceğim" tarzı gündem duyurusu.)

SERT KISITLAR — bunlara uymayan paket REDDEDİLİR:
  • cta_texts: TAM 4 metin, her biri EN FAZLA 24 KARAKTER. Bu bir ekran çipi ve
    1080 piksele sığmak zorunda; taşarsa kırpılır ve ekranda yarım kelime yazar.
  • trade_cta: "{{no}}" yer tutucusu ZORUNLU; no=48 ile render edilince EN FAZLA
    24 KARAKTER.
  • default_series_title: EN FAZLA 24 KARAKTER (rozette " #47" için yer kalmalı).
  • comment_styles: TAM 4.   connective_styles: TAM 8.
  • overused: EN AZ 5.       overused_patterns: EN AZ 4 (regex DERLENEBİLİR olmalı).
  • series.* şablonlarının yer tutucuları AYNEN korunmalı:
      header: {{title}} {{no}} {{next_no}}
      paying_promise: {{promise}}
      announce_arc: {{arc_title}} {{arc_total}}
      finale: {{arc_title}} {{next_no}}
      planned_loop: {{next_no}} {{next_topic}}
      chain_loop: {{next_no}}
      teaser_fallback: {{title}}
    Başka yer tutucu EKLEME.
  • meta_tail_pattern: {ad} dilinde "…{{konu}} 48. bölümde anlatacağım" gibi bir
    HAVALE cümleciğini cümle SONUNDA yakalayan regex. Bu alan bir sonraki bölümün
    ÜRETİM KONUSU olarak kullanılıyor; meta dil temizlenmezse senaryo yazıcısı yanılır.

SERİ YÖNERGELERİNİN PEDAGOJİSİ KORUNMALI (ödenmiş tepe + açık kapı): video kendi
vaadini TUTAR, tepeden hemen sonra yeni ve SPESİFİK bir kapı açılır ve o kapının cevabı
BİR SONRAKİ BÖLÜMDEDİR. Örnek cümleleri {ad} dilinde YENİDEN YAZ, çevirme.

"lang" alanı "{lang}" olmalı.

REFERANS (Türkçe paket):
{ref_json}
"""
    if hatalar:
        p += ("\nÖNCEKİ DENEMEN REDDEDİLDİ. Şu hataları düzelt:\n  • "
              + "\n  • ".join(hatalar) + "\n")
    return p


def generate_pack(lang: str, *, claude_path: str = "claude",
                  openrouter_model: str = "", openrouter_key: str | None = None,
                  invoke=None) -> LangPack:
    """Dil paketini üret. Doğrulamadan geçmezse RuntimeError.

    invoke: test enjeksiyonu. Üretimde claude_cli._invoke_raw kullanılır.
    """
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"desteklenmeyen dil: {lang!r}")

    inv = invoke or _invoke_raw
    ref = load_pack("tr").model_dump_json(indent=2)
    hatalar: list[str] = []
    son: list[str] = []

    for _ in range(_MAX_ATTEMPTS):
        prompt = _prompt(lang, ref, hatalar)
        try:
            raw = inv(prompt, backend="claude_cli", model="sonnet",
                      claude_path=claude_path, api_key=None, timeout_s=180)
        except (ClaudeCliError, FileNotFoundError) as e:
            # CLI yok/patladı → OpenRouter'daki AYNI modele düş.
            log.info(f"[langpack] Claude CLI kullanılamadı ({e}) → OpenRouter")
            if not openrouter_model:
                openrouter_model = "anthropic/claude-sonnet-5"
            raw = inv(prompt, backend="openrouter", model=openrouter_model,
                      claude_path=claude_path, api_key=openrouter_key, timeout_s=180)

        try:
            pack = LangPack.model_validate(json.loads(_extract_json(raw)))
        except Exception as e:   # noqa: BLE001 — şema hatası da bir doğrulama hatası
            hatalar = [f"JSON/şema hatası: {e}"]
            son = hatalar
            continue

        hatalar = validate_pack(pack)
        if not hatalar:
            return pack
        son = hatalar
        log.warning(f"[langpack] {lang}: doğrulama düştü, yeniden deneniyor: {hatalar}")

    raise RuntimeError(
        f"'{lang}' dil paketi üretilemedi ({_MAX_ATTEMPTS} deneme). Son hatalar:\n  • "
        + "\n  • ".join(son))
```

> **Uygulayıcıya not:** `claude_cli._invoke_raw`'ın gerçek imzasını doğrula
> (`grep -n "def _invoke_raw" -A 8 src/short_bot/claude_cli.py`) ve çağrıyı ona
> uydur. Test sahte `invoke` enjekte ettiği için imza uyuşmazlığı testlerde
> yakalanmaz — bu yüzden elle kontrol et.

- [ ] **Step 4: Testi koş**

Run: `python -m pytest tests/test_lang_pack_gen.py -q`
Expected: PASS (6 test)

- [ ] **Step 5: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/lang_pack_gen.py
git add -f tests/test_lang_pack_gen.py
git commit -m "feat(lang): dil paketi uretimi - Sonnet 5 (Claude CLI, OpenRouter dusme)"
```

---

## Task 10: GERÇEK Almanca paketi üret ve ÖLÇ

Bu görev kod yazmıyor — **gerçek Sonnet 5'i çağırıp çıktısını denetliyor.** Plan boyunca
her şey sahte `invoke` ile test edildi; Sonnet'in gerçekten kullanılabilir bir Almanca
paket üretip üretmediği ÖLÇÜLMEDİ.

**Files:**
- Create: `src/short_bot/langpacks/de.json` (üretilen çıktı, denetlendikten sonra)

- [ ] **Step 1: Gerçek üretimi çalıştır**

Scratchpad'e betik yaz:

```python
import sys, json
sys.path.insert(0, "D:/short/src")
from short_bot.lang_pack_gen import generate_pack
from short_bot.lang_pack import validate_pack, CTA_MAX_CHARS

pack = generate_pack("de")          # gerçek Claude CLI + Sonnet 5
print("DOĞRULAMA:", validate_pack(pack) or "TEMİZ")
print("\nCTA'lar (sınır 24):")
for c in pack.cta_texts:
    print(f"  {len(c):2d}  {c}")
print(f"  {len(pack.trade_cta.replace('{no}','48')):2d}  "
      f"{pack.trade_cta.replace('{no}','48')}")
print("\nYASAKLI KALIPLAR:")
for op in pack.overused_patterns:
    print(f"  {op.pattern:35s}  {op.label}")
print("\nÖRNEK SERİ YÖNERGESİ:")
print(pack.series.chain_loop.format(next_no=48))
open("D:/short/src/short_bot/langpacks/de.json", "w", encoding="utf-8").write(
    pack.model_dump_json(indent=2))
```

- [ ] **Step 2: Çıktıyı GÖZLE denetle**

Kontrol listesi:
- CTA'lar gerçekten Almanca ve doğal mı? ("ABONNIEREN" geçiyor mu?)
- Yasaklı kalıplar gerçek Almanca Shorts klişeleri mi, yoksa Türkçe listenin
  çevirisi mi? ("Wusstest du schon", "Hallo Leute" tarzı bekleniyor.)
- Seri yönergeleri Almanca mı, pedagoji korunmuş mu (ödenmiş tepe + açık kapı)?
- Türkçe sızıntı var mı? (`"BÖLÜM" in json` → olmamalı)

Kabul edilemezse `_prompt`'u düzelt ve yeniden üret. **Bu bir kalite kapısıdır.**

- [ ] **Step 3: Üretilen paketle testleri koş**

`tests/test_lang_pack_de_real.py`:

```python
"""ÜRETİLEN Almanca paketin gerçekten kullanılabilir olduğunu kanıtlar.
(test_lang_pack_de.py elle yazılmış fixture kullanır; bu, Sonnet'in çıktısını sınar.)"""
import pytest

from short_bot.lang_pack import CTA_MAX_CHARS, load_pack, validate_pack
from short_bot.reel_phrases import find_overused
from short_bot.reel_series import episode_badge

DE = load_pack("de")


def test_uretilen_paket_GECERLI():
    assert validate_pack(DE) == []


def test_CTA_ALMANCA_ve_sigar():
    for c in DE.cta_texts:
        assert len(c) <= CTA_MAX_CHARS
    birlesik = " ".join(DE.cta_texts) + DE.trade_cta
    assert "ABONE OL" not in birlesik, "Türkçe sızdı"
    assert "ABONNIER" in birlesik.upper(), "Almanca abone kelimesi yok"


def test_TURKCE_sizintisi_YOK():
    ham = DE.model_dump_json()
    for tr in ["BÖLÜM", "ABONE OL", "İzleyici", "yarın —"]:
        assert tr not in ham, f"Türkçe sızıntı: {tr!r}"


def test_rozet_NOKTASIZ_I():
    assert episode_badge("Bier Garten", 47, pack=DE) == "BIER GARTEN #47"


def test_gercek_ALMANCA_klise_yakalanir():
    """Sonnet'in yazdığı kalıplar GERÇEKTEN eşleşiyor mu?"""
    ornekler = [
        "Wusstest du schon, dass Bier älter ist als Brot?",
        "Hallo Leute, heute zeige ich euch etwas Verrücktes",
    ]
    yakalanan = sum(1 for o in ornekler if find_overused(o, pack=DE))
    assert yakalanan >= 1, "üretilen kalıplardan hiçbiri gerçek klişeyi yakalamadı"


def test_temiz_ALMANCA_metin_GECER():
    temiz = "Ein Bier braucht neun Monate im kalten Keller."
    assert find_overused(temiz, pack=DE) == [], "yanlış pozitif"
```

Run: `python -m pytest tests/test_lang_pack_de_real.py -q`
Expected: PASS

`test_gercek_ALMANCA_klise_yakalanir` düşerse Sonnet'in kalıpları işe yaramıyor —
prompt'u düzelt, yeniden üret. **Bu testi zayıflatarak geçirme.**

- [ ] **Step 4: Commit**

```bash
git add src/short_bot/langpacks/de.json
git add -f tests/test_lang_pack_de_real.py
git commit -m "feat(lang): de.json - Sonnet 5 uretti, gozle denetlendi, gercek klise yakalama testi gecti"
```

---

## Task 11: Panel — dil paketi görünür ve yönetilebilir olsun

**Files:**
- Create: `src/short_bot/web/routes/lang_packs.py`
- Create: `src/short_bot/web/templates/lang_packs.html.j2`
- Modify: `src/short_bot/web/routes/__init__.py` (blueprint kaydı)
- Modify: `src/short_bot/web/__init__.py` (`lang_pack.set_user_dir`)
- Modify: `src/short_bot/web/routes/reel_new.py` (sihirbaz: paket yoksa üret)
- Test: `tests/test_web_lang_packs.py` (yeni)

- [ ] **Step 1: Testi yaz**

`tests/test_web_lang_packs.py`:

```python
"""Panel: dil paketleri görünür, üretilebilir, doğrulanır.

Kullanıcının korkusu SESSİZ BOZULMA. Paket yoksa kanal kurulmamalı ve SEBEBİ
söylenmeli — "Almanca kanal açtım, ekranda Türkçe yazıyor" yaşanmamalı.
"""
import pytest


def test_sayfa_KODLA_GELEN_paketleri_listeler(tmp_path):
    a, _ = _app(tmp_path)
    body = a.test_client().get("/lang-packs").data.decode("utf-8")
    assert "Türkçe" in body
    assert "English" in body


def test_URETILMEMIS_dil_EKSIK_gorunur(tmp_path):
    a, _ = _app(tmp_path)
    body = a.test_client().get("/lang-packs").data.decode("utf-8")
    assert "Français" in body
    assert "üretilmedi" in body.lower()


def test_paket_YOKKEN_o_dilde_kanal_KURULAMAZ(tmp_path):
    """SESSİZ DÜŞME YASAĞININ panel ucu."""
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/new-reel", data={
        "name": "Jardin", "topic": "jardinage interessant et surprenant",
        "language": "fr", "voice_id": "elevenlabs_x",
    }, follow_redirects=True)
    body = r.data.decode("utf-8")
    assert "dil paketi" in body.lower()
    assert "üret" in body.lower()


def test_BOZUK_paket_KAYDEDILMEZ(tmp_path):
    a, _ = _app(tmp_path)
    r = a.test_client().post("/lang-packs/de", data={
        "json": '{"lang": "de", "cta_texts": ["' + "A" * 30 + '"]}'
    }, follow_redirects=True)
    assert "24" in r.data.decode("utf-8")
```

> **Uygulayıcıya not:** `_app()` yardımcısını `tests/test_web_autopilot.py`'deki
> desenden kopyala (`SHORTBOT_CONFIG_DIR`, `SHORTBOT_DB_PATH` vs. kuran fixture).

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_web_lang_packs.py -q`
Expected: FAIL — 404

- [ ] **Step 3: `set_user_dir`'i uygulama kurulumuna bağla**

`src/short_bot/web/__init__.py` — uygulama kurulurken:

```python
    # Üretilen dil paketleri kullanıcının yazılabilir dizinine gider; paketlenmiş
    # Electron uygulamasında kurulum dizini salt-okunur olabilir.
    from short_bot.lang_pack import set_user_dir
    _lp = app.config["SHORTBOT_CONFIG_DIR"] / "langpacks"
    _lp.mkdir(parents=True, exist_ok=True)
    set_user_dir(_lp)
```

- [ ] **Step 4: Rotaları yaz**

`src/short_bot/web/routes/lang_packs.py`:

```python
"""Dil paketleri paneli: listele / göster / düzenle / üret.

Kullanıcı Almanca kanal açtığında ekranda ne yazacağını GÖREBİLMELİ. Paket üretimi
bir LLM çıktısıdır; gözden geçirilmeden üretime girmemeli.
"""
from __future__ import annotations

import json
import logging
import threading

from flask import Blueprint, current_app, flash, redirect, render_template, url_for

from short_bot.lang_pack import (LangPack, load_pack, pack_path, set_user_dir,
                                 validate_pack)
from short_bot.locale import LANGUAGE_NAMES, SUPPORTED_LANGUAGES

bp = Blueprint("lang_packs", __name__)
_LOG = logging.getLogger(__name__)


def _durum(lang: str) -> dict:
    try:
        pack = load_pack(lang)
        return {"lang": lang, "name": LANGUAGE_NAMES.get(lang, lang),
                "var": True, "pack": pack,
                "json": pack.model_dump_json(indent=2)}
    except RuntimeError:
        return {"lang": lang, "name": LANGUAGE_NAMES.get(lang, lang),
                "var": False, "pack": None, "json": ""}


@bp.get("/lang-packs")
def page():
    return render_template("lang_packs.html.j2",
                           diller=[_durum(l) for l in SUPPORTED_LANGUAGES])


@bp.post("/lang-packs/<lang>/generate")
def generate(lang):
    from short_bot.lang_pack_gen import generate_pack
    if lang not in SUPPORTED_LANGUAGES:
        flash(f"desteklenmeyen dil: {lang}", "error")
        return redirect(url_for("lang_packs.page"))

    settings = current_app.config["SHORTBOT_SETTINGS"]
    secrets = current_app.config.get("SHORTBOT_SECRETS", {}) or {}
    hedef = pack_path(lang, user=True)

    def _job():
        try:
            pack = generate_pack(
                lang,
                claude_path=settings.claude_cli_path,
                openrouter_model=settings.openrouter_models.get(
                    "script", "anthropic/claude-sonnet-5"),
                openrouter_key=secrets.get("openrouter_api_key"))
            hedef.write_text(pack.model_dump_json(indent=2), encoding="utf-8")
            load_pack.cache_clear()
            _LOG.info(f"[langpack] {lang} üretildi → {hedef}")
        except Exception as e:   # noqa: BLE001 — thread paneli düşürmesin
            _LOG.warning(f"[langpack] {lang} üretilemedi: {e}")

    threading.Thread(target=_job, daemon=True).start()
    flash(f"{LANGUAGE_NAMES.get(lang, lang)} dil paketi üretiliyor (Sonnet 5, ~1 dk). "
          f"Sayfayı sonra yenileyin.", "info")
    return redirect(url_for("lang_packs.page"))


@bp.post("/lang-packs/<lang>")
def save(lang):
    """Elle düzenlenen paketi kaydet — DOĞRULAMADAN GEÇMEDEN kaydedilmez."""
    from flask import request
    try:
        pack = LangPack.model_validate(json.loads(request.form.get("json", "")))
    except Exception as e:   # noqa: BLE001
        flash(f"Geçersiz JSON/şema: {e}", "error")
        return redirect(url_for("lang_packs.page"))
    hatalar = validate_pack(pack)
    if hatalar:
        flash("Paket reddedildi:\n  • " + "\n  • ".join(hatalar), "error")
        return redirect(url_for("lang_packs.page"))
    pack_path(lang, user=True).write_text(pack.model_dump_json(indent=2),
                                          encoding="utf-8")
    load_pack.cache_clear()
    flash(f"{LANGUAGE_NAMES.get(lang, lang)} paketi kaydedildi.", "success")
    return redirect(url_for("lang_packs.page"))
```

`src/short_bot/web/routes/__init__.py`'ye blueprint kaydı ekle (mevcut desene uyarak).

- [ ] **Step 5: Şablonu yaz**

`src/short_bot/web/templates/lang_packs.html.j2` — mevcut sayfaların (örn.
`topic_bank.html.j2`) sıcak paletini ve yapısını izle. Her dil için bir kart:

- dil adı + durum rozeti (kodla gelen / üretildi / **üretilmedi**)
- "üretilmedi" ise kırmızı uyarı + "Sonnet 5 ile üret" düğmesi
- varsa: CTA metinleri, yasaklı kalıplar ve ham JSON'u gösteren açılır `<details>`
  + kaydet düğmesi (POST `/lang-packs/<lang>`)

- [ ] **Step 6: Sihirbazı bağla — paket yoksa kanal kurulmasın**

`src/short_bot/web/routes/reel_new.py`, `create()` içinde, DNA üretiminden ÖNCE:

```python
    # DİL PAKETİ ŞART: yoksa kanal Türkçe çip basar, Türkçe rozet yazar ve klişe
    # denetçisi hiçbir şey yakalayamaz — hepsi SESSİZCE. Kanalı kurmaktansa
    # kurulumu reddetmek yeğdir.
    from short_bot.lang_pack import load_pack
    try:
        load_pack(language)
    except RuntimeError:
        flash(f"'{LANGUAGE_NAMES.get(language, language)}' dil paketi henüz "
              f"üretilmedi. Ayarlar → Dil paketleri sayfasından üretin (~1 dk), "
              f"sonra kanalı kurun.", "error")
        return redirect(url_for("lang_packs.page"))
```

- [ ] **Step 7: Testleri koş**

Run: `python -m pytest tests/test_web_lang_packs.py -q`
Expected: PASS

- [ ] **Step 8: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 9: Commit**

```bash
git add src/short_bot/web/routes/lang_packs.py src/short_bot/web/templates/lang_packs.html.j2 src/short_bot/web/routes/__init__.py src/short_bot/web/__init__.py src/short_bot/web/routes/reel_new.py
git add -f tests/test_web_lang_packs.py
git commit -m "feat(lang): dil paketleri paneli + sihirbaz kapisi (paket yoksa kanal kurulmaz)"
```

---

## Task 12: Uçtan uca — GERÇEK Almanca video üret ve ölç

Bu planın kanıtı. Şimdiye kadar her şey birim testiyle doğrulandı; **gerçek bir Almanca
video üretilmedi.** Sessiz bozulmalar tam da burada ortaya çıkar.

**Files:** yok (ölçüm görevi). Bulgu çıkarsa düzeltme kendi commit'ini alır.

- [ ] **Step 1: Almanca test kanalı kur**

Panelden `/channels/new-reel`:
- Ad: `Bier Garten Fakten`
- Dil: `Deutsch`
- Konu: `überraschende Fakten über Bier und Brauerei`
- Ses: Almanca okuyan bir ElevenLabs multilingual `voice_id`
- `produce_now`: hayır

- [ ] **Step 2: Bir video üret ve ÖLÇ**

Üretimi başlat. Bittiğinde şunları **gerçekten kontrol et**:

| Ne | Nasıl | Beklenen |
|---|---|---|
| Anlatım metni | `data/shorts/<id>/narration.json` | `ä/ö/ü/ß` **sağ kalmış** ("Täglich", "Weiß") — `Taglich` görürsen Task 2 bağlanmamış |
| Abone çipi | Kare çıkar: `ffmpeg -ss <peak+1.5> -i <mp4> -frames:v 1 chip.png` | Almanca, kırpılmamış, 1080px'e sığmış |
| Rozet (varsa seri) | Kare sıfır | `BIER GARTEN #1` — `BİER` görürsen `locale_upper` bağlanmamış |
| Altyazı | Video | Almanca harfler doğru |
| Klişe denetçisi | Üretim logu | `find_overused` koştu; yakalarsa yeniden yazdırdı |
| TTS sadakati | Üretim logu | Yanlış alarm yok |

- [ ] **Step 3: Bulguları raporla**

Her sapma için: ne bekleniyordu, ne oldu, hangi katman bağlanmamış. Düzelt, testini
yaz, commit et.

- [ ] **Step 4: Türkçe kanal REGRESYON kontrolü**

Mevcut bir Türkçe kanaldan bir video üret. Çıktı, bu plandan ÖNCEKİ videolarla aynı
karakterde olmalı (CTA Türkçe, rozet noktalı İ, denetçi çalışıyor). Altın test bunu
birim düzeyinde kanıtladı; bu, uçtan uca teyididir.

- [ ] **Step 5: Son commit**

```bash
git add -A src/ && git add -f tests/
git commit -m "test(lang): uctan uca Almanca uretim olcumu + Turkce regresyon teyidi"
```

---

## Kapsam dışı (bilerek — sonraki alt projeler)

- **Konu üretimi kalitesi ve referans-kanal zorunluluğu** → alt proje 2. Bugün konu
  damıtma `role="default"` ile koşuyor, o da `google/gemini-3.1-flash-lite` — yani
  nişteki konuları seçen model sistemdeki EN UCUZ model. Ayrı iş.
- **Kanal kurma ajanı** ("Almanca bahçecilik kanalı istiyorum, niş bul") → alt proje 3.
- **Panelin kendi arayüzü** Türkçe kalır (kullanıcı Türk).
- **`renderer.py` `DEFAULT_UI_LABELS_TR`** (klasik/RSS yolu, reel değil) — `locale.
  UI_LABELS` zaten 5 dili taşıyor; reel yolu etkilenmiyor.
