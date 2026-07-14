# Konu Üretimi — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Konu bankası kaliteli konu üretsin — YouTube API anahtarı ya da referans kanal olmadan da.

**Architecture:** Damıtma ve üretim tek Sonnet 5 promptunda birleşir: kanıt (outlier başlıkları) varsa ilham olur, yoksa saf üretim koşar. Arkasına bir **doğrulama kapısı** konur — ölçüldü, model prompt'un yasak örneğini birebir yazdı; prompt'a güvenmek yetmiyor. Mekanik fallback (ham başlık = konu) kaldırılır: ölçülen çöpün kaynaklarından biri o.

**Tech Stack:** Python 3.14, pydantic v2, pytest, Claude CLI (Sonnet 5) → OpenRouter düşme yolu, YouTube Data API v3.

**Spec:** `docs/superpowers/specs/2026-07-14-konu-uretimi-design.md`

**Dal:** `feature/electron-installer`. YAYINLANMAYACAK.

---

## Değişmez kurallar

1. **Her görevin sonunda `python -m pytest tests/ -q` koşar ve HEPSİ geçer** (şu an 2159).
2. **`tests/` gitignore'da** → commit ederken `git add -f tests/<dosya>`. `docs/superpowers/` de ignore'da.
3. **Sessiz bozulma yasak.** Konu üretilemiyorsa `RuntimeError`; doğrulamayı hiçbir konu geçmezse `added=0` ve **UYARI logu**.
4. **Ölçülen bilgelik atılmaz.** Mevcut damıtma prompt'undaki kurallar (sözde-bilim yasağı, meta-tarif yasağı, format uyumu, "gerçeği içer vaat etme", içi boş genelleme yasağı) gerçek hatalardan öğrenildi — yeni prompt'a AYNEN taşınır.
5. Commit mesajını dosyaya yazıp `git commit -F <dosya>` kullan (PowerShell here-string kesme işaretinde kırılıyor).

---

## Dosya haritası

| Dosya | Sorumluluk | Durum |
|---|---|---|
| `src/short_bot/llm_sonnet.py` | Sonnet 5 çağırıcısı: Claude CLI → OpenRouter düşme | **YENİ** |
| `src/short_bot/lang_pack_gen.py` | Kendi CLI/OpenRouter mantığını `llm_sonnet`'e devreder | Değişir |
| `src/short_bot/topic_propose.py` | `propose_topics()` (damıtma+üretim) + `verify_topics()` (doğrulama kapısı) | **YENİ** |
| `src/short_bot/topic_miner.py` | Yalnız KANIT toplar (outlier satırları). `_distill*` silinir. | Değişir |
| `src/short_bot/topic_audit.py` | `audit_bank()` — mevcut çöpü `rejected` işaretler | **YENİ** |
| `src/short_bot/db.py` | `topic_bank.source` sütunu + migration | Değişir |
| `src/short_bot/web/routes/topic_bank.py` | "Bankayı denetle" rotası; `_miner_kwargs` sadeleşir | Değişir |
| `src/short_bot/web/templates/topic_bank.html.j2` | Kaynak rozeti + denetle düğmesi | Değişir |
| `src/short_bot/topic_autofill.py` | `api_keys` artık zorunlu değil | Değişir |

---

## Task 1: Ortak Sonnet çağırıcısı

Dil paketinde kurduğumuz desen tek yere çıkar; `lang_pack_gen` ona devreder.

**Files:**
- Create: `src/short_bot/llm_sonnet.py`
- Modify: `src/short_bot/lang_pack_gen.py`
- Test: `tests/test_llm_sonnet.py` (yeni)

- [ ] **Step 1: Testi yaz**

`tests/test_llm_sonnet.py`:

```python
"""Sonnet 5 çağırıcısı: önce Claude CLI (abonelik), patlarsa OpenRouter (AYNI model).

Aktif backend `openrouter` olduğu için resolve_ai_call her rol için OpenRouter
döndürür ve Claude CLI aboneliğini kullanamayız. Bu yüzden baypas ediyoruz —
kod tabanında kanıtlanmış desen (niche_finder, lang_pack_gen).
"""
import json
import subprocess

import pytest
from pydantic import BaseModel

from short_bot.llm_sonnet import SONNET_CLI, SONNET_OR, TIMEOUT_S, sonnet_json


class _Sema(BaseModel):
    x: int


def test_CLAUDE_CLI_ve_SONNET_kullanilir():
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw)
        return '{"x": 1}'

    assert sonnet_json("merhaba", _Sema, invoke=_invoke).x == 1
    assert cagri[0]["backend"] == "claude_cli"
    assert cagri[0]["model"] == SONNET_CLI == "sonnet"


def test_CLI_patlarsa_OPENROUTERA_duser():
    from short_bot.claude_cli import ClaudeCliError
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw)
        if kw["backend"] == "claude_cli":
            raise ClaudeCliError("claude yok")
        return '{"x": 2}'

    assert sonnet_json("merhaba", _Sema, invoke=_invoke, openrouter_key="k").x == 2
    assert [c["backend"] for c in cagri] == ["claude_cli", "openrouter"]
    assert "sonnet" in cagri[1]["model"], "düşme yolu AYNI modeli kullanmalı"
    assert cagri[1]["api_key"] == "k"


def test_CLI_ZAMAN_ASIMINDA_da_dusulur():
    """subprocess.TimeoutExpired OSError DEĞİL — ayrıca yakalanmalı. Ölçüldü:
    yakalanmayınca üretim düşme yolunu HİÇ DENEMEDEN ölüyordu."""
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw["backend"])
        if kw["backend"] == "claude_cli":
            raise subprocess.TimeoutExpired(cmd=["claude"], timeout=TIMEOUT_S)
        return '{"x": 3}'

    assert sonnet_json("merhaba", _Sema, invoke=_invoke).x == 3
    assert cagri == ["claude_cli", "openrouter"]


def test_CLI_YOKSA_da_dusulur():
    def _invoke(prompt, **kw):
        if kw["backend"] == "claude_cli":
            raise FileNotFoundError("claude")
        return '{"x": 4}'

    assert sonnet_json("merhaba", _Sema, invoke=_invoke).x == 4


def test_BOZUK_JSON_yeniden_denenir():
    cevaplar = ["bu json degil", '{"x": 5}']

    def _invoke(prompt, **kw):
        return cevaplar.pop(0)

    assert sonnet_json("merhaba", _Sema, invoke=_invoke).x == 5


def test_HEP_bozuksa_hata():
    def _invoke(prompt, **kw):
        return "asla json degil"

    with pytest.raises(RuntimeError):
        sonnet_json("merhaba", _Sema, invoke=_invoke)


def test_openrouter_modeli_SONNET():
    assert SONNET_OR == "anthropic/claude-sonnet-5"


def test_zaman_asimi_comert():
    # Uzun prompt + uzun çıktı. Ölçüldü: 240 sn YETMEDİ.
    assert TIMEOUT_S >= 480
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_llm_sonnet.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'short_bot.llm_sonnet'`

- [ ] **Step 3: `llm_sonnet.py`'yi yaz**

```python
"""Sonnet 5 çağırıcısı — önce Claude CLI, patlarsa OpenRouter (AYNI model).

NEDEN resolve_ai_call DEĞİL: aktif backend `openrouter` (config/settings.yaml) ve
resolve_ai_call her rol için OpenRouter döndürüyor — Claude CLI aboneliğini
kullanamayız. Baypas etmek kod tabanında kanıtlanmış desen: niche_finder da,
lang_pack_gen de aynısını yapıyor.

Düşme yolu AYNI MODELİ kullanır (anthropic/claude-sonnet-5): kalite değişmez,
yalnız fatura değişir.
"""
from __future__ import annotations

import json
import logging
import subprocess
from typing import TypeVar

from pydantic import BaseModel

from short_bot.claude_cli import (ClaudeCliError, _extract_json, _invoke_raw)

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

SONNET_CLI = "sonnet"                      # Claude CLI alias → Sonnet 5
SONNET_OR = "anthropic/claude-sonnet-5"    # OpenRouter düşme yolu (AYNI model)
# Prompt'lar uzun (banka + kanıt) ve çıktı da uzun. Ölçüldü: 240 sn YETMEDİ.
TIMEOUT_S = 600


def sonnet_json(prompt: str, schema: type[T], *, claude_path: str = "claude",
                openrouter_model: str = "", openrouter_key: str | None = None,
                timeout_s: int = TIMEOUT_S, retries: int = 2, invoke=None) -> T:
    """Sonnet 5'e prompt gönder, JSON'u `schema` ile doğrula.

    invoke: test enjeksiyonu. Üretimde claude_cli._invoke_raw kullanılır.
    """
    inv = invoke or _invoke_raw
    son: Exception | None = None

    for deneme in range(1, retries + 1):
        try:
            raw = inv(prompt, backend="claude_cli", model=SONNET_CLI,
                      claude_path=claude_path, api_key=None, timeout_s=timeout_s)
        except (ClaudeCliError, FileNotFoundError, OSError,
                subprocess.TimeoutExpired) as e:
            # CLI yok / patladı / yanıt vermedi → OpenRouter'daki AYNI modele düş.
            # TimeoutExpired ŞART: OSError DEĞİL, yakalanmazsa üretim düşme yolunu
            # HİÇ DENEMEDEN ölür (ölçüldü, gerçek koşuda yaşandı).
            log.info(f"[sonnet] Claude CLI kullanılamadı ({e}) → OpenRouter")
            raw = inv(prompt, backend="openrouter",
                      model=openrouter_model or SONNET_OR,
                      claude_path=claude_path, api_key=openrouter_key,
                      timeout_s=timeout_s)

        try:
            return schema.model_validate(json.loads(_extract_json(raw)))
        except Exception as e:   # noqa: BLE001 — JSON/şema hatası: yeniden dene
            son = e
            log.warning(f"[sonnet] deneme {deneme} şemaya uymadı: {e}")

    raise RuntimeError(f"Sonnet {retries} denemede geçerli JSON üretemedi: {son}")
```

- [ ] **Step 4: Testi koş**

Run: `python -m pytest tests/test_llm_sonnet.py -q`
Expected: PASS (8 test)

- [ ] **Step 5: `lang_pack_gen`'i devret**

`src/short_bot/lang_pack_gen.py` içindeki `generate_pack` gövdesinde CLI/OpenRouter
çağrı bloğunu `sonnet_json` ile değiştir. Doğrulama/retry döngüsü (validate_pack →
hataları prompt'a geri ver) AYNEN kalır — o, paket-özgü ve `llm_sonnet`'in işi değil.

```python
from short_bot.llm_sonnet import SONNET_OR, TIMEOUT_S, sonnet_json

def generate_pack(lang: str, *, claude_path: str = "claude",
                  openrouter_model: str = "", openrouter_key: str | None = None,
                  invoke=None) -> LangPack:
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"desteklenmeyen dil: {lang!r}")

    ref = load_pack("tr").model_dump_json(indent=2)
    hatalar: list[str] = []
    son: list[str] = ["(deneme yapılamadı)"]

    for deneme in range(1, _MAX_ATTEMPTS + 1):
        prompt = _prompt(lang, ref, hatalar)
        try:
            pack = sonnet_json(prompt, LangPack, claude_path=claude_path,
                               openrouter_model=openrouter_model or SONNET_OR,
                               openrouter_key=openrouter_key,
                               timeout_s=TIMEOUT_S, retries=1, invoke=invoke)
        except RuntimeError as e:
            hatalar = [f"JSON/şema hatası: {e}"]
            son = hatalar
            continue

        hatalar = validate_pack(pack)
        if not hatalar:
            return pack
        son = hatalar
        log.warning(f"[langpack] {lang}: deneme {deneme} doğrulamayı geçmedi: {hatalar}")

    raise RuntimeError(
        f"'{lang}' dil paketi üretilemedi ({_MAX_ATTEMPTS} deneme). Son hatalar:\n  • "
        + "\n  • ".join(son))
```

Artık kullanılmayan importlar (`json`, `subprocess`, `_extract_json`, `_invoke_raw`,
`ClaudeCliError`, `_SONNET_CLI`, `_SONNET_OR`, `_TIMEOUT_S`) temizlenir.

> **Uygulayıcıya not:** `tests/test_lang_pack_gen.py`'deki testler `invoke`'a
> `backend`/`model` anahtarlarıyla bakıyor; `sonnet_json` aynı anahtarları geçirdiği
> için geçmeye devam etmeli. `test_zaman_asimi_PAKETE_gore_cömert` `_TIMEOUT_S`'i
> import ediyor → `from short_bot.llm_sonnet import TIMEOUT_S` olarak güncelle.

- [ ] **Step 6: Dil paketi testleri hâlâ geçiyor mu**

Run: `python -m pytest tests/test_lang_pack_gen.py tests/test_llm_sonnet.py -q`
Expected: PASS

- [ ] **Step 7: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 8: Commit**

```bash
git add src/short_bot/llm_sonnet.py src/short_bot/lang_pack_gen.py
git add -f tests/test_llm_sonnet.py tests/test_lang_pack_gen.py
git commit -m "refactor(llm): ortak sonnet_json cagiricisi (Claude CLI -> OpenRouter)"
```

---

## Task 2: `topic_bank.source` sütunu

Kullanıcı neyin kanıtlı, neyin üretilmiş olduğunu bilmeli.

**Files:**
- Modify: `src/short_bot/db.py` (`topic_bank` tablosu + `_migrate_add_columns` + `insert_bank_topics`)
- Test: `tests/test_topic_source.py` (yeni)

- [ ] **Step 1: Testi yaz**

`tests/test_topic_source.py`:

```python
"""Konunun KAYNAĞI görünür olmalı.

Bir konu ya kanıtlıdır (referans kanal / arama outlier'ı) ya da modelin üretimidir.
İkisi aynı şey değil ve kullanıcı hangisine baktığını bilmeli — bu projenin
"sessiz bozulma olmasın" ilkesinin gereği.
"""
from short_bot.db import all_bank_topics, init_db, insert_bank_topics


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def test_kaynak_YAZILIR_ve_OKUNUR(tmp_path):
    eng = _eng(tmp_path)
    insert_bank_topics(eng, "k", [
        {"topic": "Referanstan gelen konu", "source_title": "V1",
         "views": 100, "subs": 10, "source": "reference"},
        {"topic": "Aramadan gelen konu", "source_title": "V2",
         "views": 50, "subs": 5, "source": "search"},
        {"topic": "Modelin urettigi konu", "source_title": "",
         "views": 0, "subs": 0, "source": "llm"},
    ])
    rows = {r["topic"]: r["source"] for r in all_bank_topics(eng, "k")}
    assert rows["Referanstan gelen konu"] == "reference"
    assert rows["Aramadan gelen konu"] == "search"
    assert rows["Modelin urettigi konu"] == "llm"


def test_kaynak_verilmezse_SEARCH(tmp_path):
    """Eski kayıtlar ve eski çağıranlar 'search' sayılır (migration varsayılanı)."""
    eng = _eng(tmp_path)
    insert_bank_topics(eng, "k", [
        {"topic": "Kaynaksiz konu", "source_title": "V", "views": 1, "subs": 1}])
    assert all_bank_topics(eng, "k")[0]["source"] == "search"
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_topic_source.py -q`
Expected: FAIL — `KeyError: 'source'` (sütun yok)

- [ ] **Step 3: Sütunu ekle**

`src/short_bot/db.py`, `topic_bank` tablosuna (`hook_pattern` satırının altına):

```python
    # KONUNUN KAYNAĞI: kanıtlı mı, üretilmiş mi?
    #   reference — referans kanalın kendi outlier'ı (format+kitle kanıtlı, en güçlü)
    #   search    — arama outlier'ı (izlenme/abone oranıyla kanıtlı)
    #   llm       — modelin üretimi, YouTube kanıtı YOK
    # Kullanıcı hangisine baktığını bilmeli; kanıtsız bir konuyu kanıtlı sanmak
    # sessiz bir yanılgıdır.
    Column("source", String, default="search", nullable=False),
```

`_migrate_add_columns` içindeki `migrations` listesine:

```python
        # Mevcut kayıtların hepsi arama/referans outlier'larından geldi → 'search'.
        ("topic_bank", "source", "TEXT DEFAULT 'search' NOT NULL"),
```

`insert_bank_topics` içindeki `values(...)` çağrısına:

```python
                source=str(r.get("source", "search"))[:20],
```

- [ ] **Step 4: Testi koş**

Run: `python -m pytest tests/test_topic_source.py -q`
Expected: PASS

- [ ] **Step 5: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/db.py
git add -f tests/test_topic_source.py
git commit -m "feat(bank): topic_bank.source sutunu (reference|search|llm)"
```

---

## Task 3: `propose_topics` — damıtma ve üretim birleşir

**Files:**
- Create: `src/short_bot/topic_propose.py`
- Test: `tests/test_topic_propose.py` (yeni)

- [ ] **Step 1: Testi yaz**

`tests/test_topic_propose.py`:

```python
"""Damıtma ve üretim TEK prompt.

ÖLÇÜLDÜ: kanıt (outlier videosu) KAYNAK VİDEOYA ait, konu CÜMLESİNE değil. 871 kat
patlamış bir videodan damıtılan cümle içi boş çıkabiliyor. Sonnet 5, hiçbir YouTube
verisi görmeden daha iyi konu yazıyor.

O yüzden kanıt bir ZORUNLULUK değil, İLHAM: "bu başlıklar bu nişte patladı; ilham al
ama kopyalamak zorunda değilsin". Kanıt yoksa saf üretim koşar — BANKA ASLA KURUMAZ.
"""
import json

import pytest

from short_bot.topic_propose import ProposedTopic, propose_topics

KANIT = [
    {"source_title": "Kalbin kendi elektrigi", "views": 900_000, "subs": 12_000},
    {"source_title": "Karaciger kendini yeniler", "views": 400_000, "subs": 9_000},
]


def _llm(topics):
    """Sahte Sonnet: verilen konuları döndürür, gördüğü prompt'u kaydeder."""
    gorulen = {}

    def _f(prompt, schema, **kw):
        gorulen["prompt"] = prompt
        return schema.model_validate({"topics": topics})

    _f.gorulen = gorulen
    return _f


def test_KANIT_VARSA_kaynak_bilgisi_tasinir():
    llm = _llm([{"topic": "Karacigerin %70'i gitse 3 haftada geri buyur",
                 "source_title": "Karaciger kendini yeniler",
                 "views": 400_000, "subs": 9_000, "hook_pattern": "sayi + iddia"}])
    out = propose_topics("insan vucudu", language="tr", evidence=KANIT,
                         existing=[], count=5, llm=llm)
    assert len(out) == 1
    assert out[0].views == 400_000
    assert out[0].source == "search"      # kanıttan geldi


def test_KANIT_YOKSA_uretim_kosar():
    """BANKA ASLA KURUMAZ. Eskiden taze outlier yoksa ValueError fırlıyordu."""
    llm = _llm([{"topic": "Mide ic zari hucrelerini 3-4 gunde bir yeniler",
                 "source_title": "", "views": 0, "subs": 0, "hook_pattern": ""}])
    out = propose_topics("insan vucudu", language="tr", evidence=[],
                         existing=[], count=5, llm=llm)
    assert len(out) == 1
    assert out[0].source == "llm"
    assert out[0].views == 0


def test_KANITSIZ_konu_llm_ETIKETLENIR():
    """Kanıt VARKEN bile model kendi olgusunu yazabilir → o konu 'llm' sayılır."""
    llm = _llm([
        {"topic": "Kanittan gelen", "source_title": "Kalbin kendi elektrigi",
         "views": 900_000, "subs": 12_000, "hook_pattern": ""},
        {"topic": "Modelin kendi bildigi olgu", "source_title": "",
         "views": 0, "subs": 0, "hook_pattern": ""},
    ])
    out = propose_topics("insan vucudu", language="tr", evidence=KANIT,
                         existing=[], count=5, llm=llm)
    kaynak = {t.topic: t.source for t in out}
    assert kaynak["Kanittan gelen"] == "search"
    assert kaynak["Modelin kendi bildigi olgu"] == "llm"


def test_REFERANS_kaniti_reference_etiketlenir():
    ref = [{"source_title": "Ref video", "views": 5, "subs": 1, "ref": True}]
    llm = _llm([{"topic": "Ref konusu", "source_title": "Ref video",
                 "views": 5, "subs": 1, "hook_pattern": ""}])
    out = propose_topics("x", language="tr", evidence=ref, existing=[],
                         count=5, llm=llm)
    assert out[0].source == "reference"


def test_MEVCUT_konular_PROMPTA_verilir():
    """Tekrar üretmesin diye bankadakiler prompt'a girer."""
    llm = _llm([{"topic": "Yeni konu", "source_title": "", "views": 0, "subs": 0,
                 "hook_pattern": ""}])
    propose_topics("x", language="tr", evidence=[],
                   existing=["Zaten bankada olan konu"], count=5, llm=llm)
    assert "Zaten bankada olan konu" in llm.gorulen["prompt"]


def test_KANIT_ILHAM_olarak_sunulur_ZORUNLULUK_degil():
    """Prompt açıkça 'kopyalamak zorunda değilsin' demeli — ölçüldü, zorlama damıtma
    içi boş cümle üretiyor."""
    llm = _llm([{"topic": "x y z", "source_title": "", "views": 0, "subs": 0,
                 "hook_pattern": ""}])
    propose_topics("x", language="tr", evidence=KANIT, existing=[], count=5, llm=llm)
    p = llm.gorulen["prompt"].lower()
    assert "zorunda değilsin" in p or "zorunlu değil" in p


def test_OLCULEN_prompt_kurallari_KORUNUR():
    """Bu kurallar GERÇEK HATALARDAN öğrenildi — atılamaz."""
    llm = _llm([{"topic": "x y z", "source_title": "", "views": 0, "subs": 0,
                 "hook_pattern": ""}])
    propose_topics("x", language="tr", evidence=[], existing=[], count=5, llm=llm)
    p = llm.gorulen["prompt"]
    assert "SÖZDE-BİLİM" in p          # mistik şifa bankaya girmişti
    assert "VAAT ETME" in p            # "şaşırtıcı rakamlarla ifade edilebilir"
    assert "GENELLEME" in p            # "her organ kusursuz uyum içinde çalışır"
    assert "TARİF ETMEZ" in p          # "…anlatan bir video"


def test_ADET_SINIRI_uygulanir():
    llm = _llm([{"topic": f"Konu {i}", "source_title": "", "views": 0, "subs": 0,
                 "hook_pattern": ""} for i in range(20)])
    out = propose_topics("x", language="tr", evidence=[], existing=[], count=5,
                         llm=llm)
    assert len(out) == 5


def test_BOS_konu_elenir():
    llm = _llm([{"topic": "   ", "source_title": "", "views": 0, "subs": 0,
                 "hook_pattern": ""},
                {"topic": "Gecerli konu burada", "source_title": "", "views": 0,
                 "subs": 0, "hook_pattern": ""}])
    out = propose_topics("x", language="tr", evidence=[], existing=[], count=5,
                         llm=llm)
    assert [t.topic for t in out] == ["Gecerli konu burada"]


def test_META_TARIF_elenir():
    """'…anlatan bir video' bir konu değil, video tarifidir (gerçek üretim hatası)."""
    llm = _llm([{"topic": "Einstein'in beynini konu alan bir inceleme",
                 "source_title": "", "views": 0, "subs": 0, "hook_pattern": ""},
                {"topic": "Einstein'in beyni olumunden sonra izinsiz calindi",
                 "source_title": "", "views": 0, "subs": 0, "hook_pattern": ""}])
    out = propose_topics("x", language="tr", evidence=[], existing=[], count=5,
                         llm=llm)
    assert len(out) == 1
    assert "inceleme" not in out[0].topic


def test_LLM_YOKSA_hata():
    """MEKANİK FALLBACK YOK. Eskiden llm_call=None iken ham başlık konu oluyordu —
    ölçülen çöpün kaynaklarından biri o. Konu üretemiyorsak DURMAK yeğdir."""
    with pytest.raises(RuntimeError, match="konu üretilemedi"):
        propose_topics("x", language="tr", evidence=[], existing=[], count=5,
                       llm=None)
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_topic_propose.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'short_bot.topic_propose'`

- [ ] **Step 3: `topic_propose.py`'yi yaz (propose kısmı)**

```python
"""Konu ÖNERİSİ: damıtma ve üretim tek prompt, arkasında doğrulama kapısı.

NEDEN BİRLEŞTİ (ölçüldü):
  • Kanıt (outlier videosu) KAYNAK VİDEOYA aittir, konu CÜMLESİNE değil. 871 kat
    patlamış bir videodan damıtılan cümle içi boş çıkabiliyor:
      "Gerçek bir sinir sistemi, ... karmaşık bir otoyol"      ← hiçbir şey demiyor
      "Vücudumuzdaki her organ kusursuz bir uyum içinde çalışır" ← prompt'un YASAK örneği
  • Sonnet 5, hiçbir YouTube verisi görmeden daha iyi konu yazıyor.
  • Bankanın %85'i çöptü (27 aktif konudan 23'ü); bazıları bilimsel olarak YANLIŞ.

O yüzden kanıt bir ZORUNLULUK değil, İLHAM. Kanıt yoksa saf üretim koşar:
BANKA ASLA KURUMAZ, referans kanal ve YouTube API anahtarı OPSİYONELDİR.

MEKANİK FALLBACK YOK: eskiden LLM yokken ham başlık konu oluyordu. Ölçülen çöpün
kaynaklarından biri o. Konu üretemiyorsak sessizce çöp üretmektense DURURUZ.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

log = logging.getLogger(__name__)

_LANG_NAMES = {"tr": "Türkçe", "en": "İngilizce", "de": "Almanca",
               "es": "İspanyolca", "fr": "Fransızca"}

# Damıtma çıktısında video-TARİFİ kalıpları (konu değil meta-açıklama) — yasak.
# Gerçek üretim hatası (2026-07-12): "…tanıtan bir seri", "…ele alan bir skeç".
# Gerçek kaçak: "anatomisi 3 boyutlu CANLANDIRMALARLA gösterilir" — bu bir İDDİA
# değil, kaynak videonun NASIL YAPILDIĞININ tarifi.
_META_WORDS = ("video", "belgesel", "seri", "skeç", "inceleme", "anlatım",
               "sunum", "içerik", "tanıtan", "anlatan", "özetleyen",
               "ele alan", "konu alan", "keşfeden bir", "yolculuğu",
               "canlandırma", "animasyon", "3 boyutlu", "3d ", "görselleştir",
               "gösterilir", "gösteren")


class ProposedTopic(BaseModel):
    topic: str
    source_title: str = ""      # kanıt kullanıldıysa
    views: int = 0
    subs: int = 0
    hook_pattern: str = ""
    source: str = "llm"         # "reference" | "search" | "llm"


class _Proposed(BaseModel):
    topics: list[ProposedTopic]


def _evidence_block(evidence: list[dict]) -> str:
    if not evidence:
        return ""
    satirlar = "\n".join(
        f'- "{e["source_title"]}"  ({e.get("views", 0):,} izlenme / '
        f'{e.get("subs", 0):,} abone)'
        for e in evidence if (e.get("source_title") or "").strip())
    if not satirlar:
        return ""
    return f"""
KANIT — bu nişte KÜÇÜK kanallarda PATLAMIŞ (outlier) shorts başlıkları:

{satirlar}

Bunlar izleyicinin neye tepki verdiğini gösterir. İLHAM AL — ama KOPYALAMAK ZORUNDA
DEĞİLSİN. Bir başlıktan somut bir olgu ÇIKARAMIYORSAN onu ATLA ve kendi bildiğin daha
iyi bir olguyu yaz. (Ölçüldü: başlığı zorla damıtmak içi boş cümle üretiyor —
"Gerçek bir sinir sistemi, karmaşık bir otoyol" gibi. Boş bir cümle, boş bir video
demektir.)

Bir konuyu bir başlıktan çıkardıysan `source_title`, `views`, `subs` alanlarını
KAYNAKTAN AYNEN kopyala. Kendi bildiğin bir olguyu yazdıysan bu üç alanı BOŞ/0 bırak.
"""


def _prompt(niche: str, lang: str, evidence: list[dict], existing: list[str],
            count: int) -> str:
    mevcut = "\n".join(f"- {t}" for t in existing if (t or "").strip())
    mevcut_blok = (f"\nBUNLAR ZATEN BANKADA — TEKRAR ETME, benzerini de yazma:\n{mevcut}\n"
                   if mevcut else "")
    return f"""Bir YouTube Shorts kanalı için {count} KONU üret.

NİŞ: {niche}
HEDEF FORMAT: 40 saniyelik faceless "ilginç bilgi" shorts — stok görüntü +
seslendirme. İzleyici 40 saniyede "vay be, bunu bilmiyordum" demeli.
DİL: {lang}
{_evidence_block(evidence)}{mevcut_blok}
KURALLAR (ÇOK ÖNEMLİ — hepsi GERÇEK HATALARDAN öğrenildi):

- Konu bir İDDİA ya da ŞAŞIRTICI GERÇEK cümlesidir; videoyu TARİF ETMEZ.
    ✗ "Einstein'ın beynini konu alan bir inceleme"
    ✓ "Einstein'ın beyni ölümünden sonra izinsiz çalındı ve 40 yıl kavanozda gezdirildi"

- GERÇEĞİ İÇER, VAAT ETME (en sık kaçan hata): konu şaşırtıcı olguyu KENDİSİ
  SÖYLEMELİ; "şaşırtıcıdır", "inanılmazdır", "rakamlarla ifade edilebilir" gibi
  ifadelerle onu ERTELEMEMELİ.
    ✗ "Vücuttaki kemik sayısı şaşırtıcı rakamlarla ifade edilebilir"   ← VAAT
    ✓ "Bebekler 300 kemikle doğar; yetişkinlikte bu sayı 206'ya iner"  ← GERÇEK

- İÇİ BOŞ GENELLEME YASAK: konu SPESİFİK ve ŞAŞIRTICI olmalı.
    ✗ "Vücudumuzdaki her organ kusursuz bir uyum içinde çalışır"  ← hiçbir şey demiyor
    ✓ "Karaciğerinin %70'ini kaybetsen bile 3 haftada kendini yeniden büyütür"
  Test: izleyici bunu ZATEN biliyor mu? Biliyorsa YAZMA.

- SÖZDE-BİLİM YASAK (SERT ELEME): konu BİLİMSEL OLARAK DOĞRULANABİLİR olmalı.
    ✗ alternatif tıp / mucize şifa / detoks / mistik şifa / enerji-aura-çakra
    ✗ kanıtsız sağlık tavsiyesi, komplo teorileri
  GERÇEK HATA: bir BİLİM kanalına "Mekke'nin adem elması, mistik bir şifa kaynağı"
  konusu girdi. Kanalın otoritesi ÜRÜNÜDÜR; bir tek sözde-bilim videosu onu yakar.
  Test: bunu bir ders kitabında bulabilir misin? Hayırsa YAZMA.

- BİLİMSEL OLARAK DOĞRU OLMALI. GERÇEK HATA: "Vücudunuz muzu sindirim sistemi
  boyunca saniyeler içinde…" — sindirim SAATLER sürer. Yanlış bir olgu, kanalın
  güvenilirliğini bitirir. Emin değilsen YAZMA.

- FORMAT UYUMU: tek, doğrulanabilir, şaşırtıcı GERÇEK. Şunları ATLA: film/dizi
  özetleri, kurgu sahneler, aşk/dram hikâyeleri, kişi-odaklı anlatılar, vlog/meme,
  hikâye anlatımı gerektiren konular.

- HEDEF KİTLE: {lang} konuşan GENEL izleyici. Evrensel merak (uzay, insan vücudu,
  tarihin şok anları, gizemler) İYİ; fazla akademik/teknik konular, başka ülkeye
  özgü yerel içerik, tanınmayan kişiler → YAZMA.

- ELEMEKTEN ÇEKİNME: {count} konu istiyoruz ama zorlama konu üretme. Az ve sağlam,
  çok ve boştan iyidir.

SADECE JSON: {{"topics": [{{"topic": "<{lang} tek çarpıcı iddia cümlesi>",
  "source_title": "<kanıttan geldiyse orijinal başlık, yoksa boş>",
  "views": <int, kanıt yoksa 0>, "subs": <int, kanıt yoksa 0>,
  "hook_pattern": "<{lang} 2-4 kelime örüntü, ör. 'sayı + beklenmedik iddia'>"}}]}}"""


def _is_meta(topic: str) -> bool:
    low = (topic or "").lower()
    return any(w in low for w in _META_WORDS)


def propose_topics(niche: str, *, language: str, evidence: list[dict],
                   existing: list[str], count: int, llm) -> list[ProposedTopic]:
    """Nişten konu öner. ``evidence`` boşsa saf üretim (banka asla kurumaz).

    ``llm``: (prompt, schema) → schema örneği döndüren çağrılabilir. None ise
    RuntimeError — MEKANİK FALLBACK YOK (bkz. modül docstring'i).
    """
    if llm is None:
        raise RuntimeError(
            "konu üretilemedi: LLM yok. (Mekanik fallback kaldırıldı — ham başlığı "
            "konu diye bankaya koymak, ölçülen çöpün kaynaklarından biriydi.)")

    lang = _LANG_NAMES.get(language, "Türkçe")
    # Referans kanaldan gelen kanıtlar 'reference', arama outlier'ları 'search'.
    ref_titles = {(e.get("source_title") or "").strip().lower()
                  for e in evidence if e.get("ref")}

    v = llm(_prompt(niche, lang, evidence, existing, count), _Proposed)

    out: list[ProposedTopic] = []
    for t in v.topics:
        konu = (t.topic or "").strip()
        if not konu or _is_meta(konu):
            continue
        src = (t.source_title or "").strip()
        if not src:
            t.source = "llm"          # kanıtsız — modelin kendi bildiği olgu
            t.views = t.subs = 0
        elif src.lower() in ref_titles:
            t.source = "reference"
        else:
            t.source = "search"
        t.topic = konu
        out.append(t)
        if len(out) >= count:
            break

    log.info(f"[konu] {len(v.topics)} öneri → {len(out)} geçerli "
             f"(kanıt: {len(evidence)} başlık)")
    return out
```

- [ ] **Step 4: Testi koş**

Run: `python -m pytest tests/test_topic_propose.py -q`
Expected: PASS (11 test)

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/topic_propose.py
git add -f tests/test_topic_propose.py
git commit -m "feat(bank): propose_topics - damitma+uretim tek promptta (kanit ILHAM, zorunluluk degil)"
```

---

## Task 4: `verify_topics` — doğrulama kapısı

Prompt'a güvenmek YETMİYOR. Ölçüldü: model, prompt'un yasak örneği olarak **birebir verdiği** cümleyi yazdı.

**Files:**
- Modify: `src/short_bot/topic_propose.py` (`verify_topics` ekle)
- Test: `tests/test_topic_verify.py` (yeni)

- [ ] **Step 1: Testi yaz**

`tests/test_topic_verify.py`:

```python
"""DOĞRULAMA KAPISI — prompt'a güvenmek yetmiyor.

ÖLÇÜLDÜ: damıtma prompt'u "Vücudumuzdaki her organ kusursuz bir uyum içinde çalışır"
cümlesini YASAK ÖRNEK olarak birebir veriyordu. Model onu kelimesi kelimesine yazdı ve
bankaya girdi. İkinci bir göz şart.
"""
import pytest

from short_bot.topic_propose import Verdict, verify_topics

# GERÇEK bankadan alınmış çöp (ölçüldü)
COP = [
    "Vücudumuzdaki her organ, hayatta kalmak için kusursuz bir uyum içinde çalışır.",
    "Vücuttaki kemik sayısı şaşırtıcı rakamlarla ifade edilebilir",
    "İnsan vücudu, evrimin milyonlarca yıllık kalıntılarıyla dolu şaşırtıcı bir sistemdir.",
]
# GERÇEK bankadan alınmış sağlam
SAGLAM = [
    "Bebekler 300 kemikle doğar; yetişkinlikte bu sayı 206'ya iner",
    "Karaciğerinin %70'ini kaybetsen bile 3 haftada kendini yeniden büyütür",
]


def _llm(yargilar):
    def _f(prompt, schema, **kw):
        _f.prompt = prompt
        return schema.model_validate({"verdicts": yargilar})
    return _f


def test_yargilar_DONER():
    llm = _llm([{"index": 0, "solid": False, "reason": "içi boş"},
                {"index": 1, "solid": True, "reason": ""}])
    out = verify_topics(["a", "b"], language="tr", llm=llm)
    assert [v.solid for v in out] == [False, True]
    assert isinstance(out[0], Verdict)


def test_KURALLAR_PROMPTA_girer():
    llm = _llm([{"index": 0, "solid": True}])
    verify_topics(["x"], language="tr", llm=llm)
    p = llm.prompt
    assert "VAAT" in p
    assert "GENELLEME" in p
    # Ölçülen gerçek çöp, prompt'ta ÖRNEK olarak veriliyor:
    assert "kusursuz bir uyum" in p


def test_BOS_liste_LLM_CAGIRMAZ():
    def _patla(*a, **kw):
        raise AssertionError("boş liste için LLM çağrıldı")
    assert verify_topics([], language="tr", llm=_patla) == []


def test_EKSIK_yargi_SAGLAM_SAYILMAZ():
    """Model bazı konular için yargı vermezse onları geçirmek, denetimi delmektir."""
    llm = _llm([{"index": 0, "solid": True}])          # 1. konu için yargı YOK
    out = verify_topics(["a", "b"], language="tr", llm=llm)
    assert len(out) == 2
    assert out[1].solid is False
    assert "yargı" in out[1].reason.lower()


def test_LLM_PATLARSA_hepsi_SAGLAM_sayilir():
    """Denetim çökerse üretimi DURDURMAYIZ — ama loglanır.

    Alternatif (hepsini elemek) bankayı sıfırlardı; kapıyı geçemeyen bir kapı,
    kapı olmaktan çıkar ama üretim de durmamalı."""
    def _patla(*a, **kw):
        raise RuntimeError("sonnet yok")
    out = verify_topics(["a", "b"], language="tr", llm=_patla)
    assert all(v.solid for v in out)
    assert all("denetlenemedi" in v.reason for v in out)


def test_LLM_None_ise_hepsi_SAGLAM():
    out = verify_topics(["a"], language="tr", llm=None)
    assert out[0].solid is True
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_topic_verify.py -q`
Expected: FAIL — `ImportError: cannot import name 'Verdict'`

- [ ] **Step 3: `verify_topics`'i ekle**

`src/short_bot/topic_propose.py` sonuna:

```python
# --- DOĞRULAMA KAPISI ------------------------------------------------------

class Verdict(BaseModel):
    index: int
    solid: bool
    reason: str = ""


class _Verdicts(BaseModel):
    verdicts: list[Verdict]


_VERIFY_PROMPT = """Aşağıda bir YouTube Shorts kanalının konu adayları var. Her birini
ŞU İKİ KURALA göre yargıla:

1. GERÇEĞİ İÇERİR, VAAT ETMEZ. Konu şaşırtıcı olguyu KENDİSİ söylemeli.
     SAĞLAM: "Bebekler 300 kemikle doğar; yetişkinlikte bu sayı 206'ya iner"
     ÇÖP:    "Vücuttaki kemik sayısı şaşırtıcı rakamlarla ifade edilebilir"   ← VAAT

2. İÇİ BOŞ GENELLEME DEĞİL. Spesifik, doğrulanabilir, izleyicinin BİLMEDİĞİ bir olgu.
     ÇÖP: "Vücudumuzdaki her organ kusursuz bir uyum içinde çalışır"  ← hiçbir şey demiyor
     ÇÖP: "İnsan vücudu şaşırtıcı bir sistemdir"                      ← boş

Ayrıca BİLİMSEL OLARAK YANLIŞ olanı ÇÖP say. (Gerçek örnek: "muz saniyeler içinde
sindirilir" — sindirim saatler sürer.)

Bir konu 40 saniyelik bir shorts'un TEK OMURGASI olacak. İçinde somut bir sayı,
mekanizma ya da şaşırtıcı olgu YOKSA o video da boş çıkar.

solid=true YALNIZ hepsini geçiyorsa. Şüphedeysen solid=false.

{liste}

SADECE JSON: {{"verdicts": [{{"index": <int>, "solid": <bool>,
  "reason": "<kısa gerekçe>"}}]}}"""


def verify_topics(topics: list[str], *, language: str, llm) -> list[Verdict]:
    """Her konuyu iki kurala göre yargıla. Konu sırasıyla AYNI uzunlukta liste döner.

    NEDEN VAR (ölçüldü): üretim prompt'u "Vücudumuzdaki her organ kusursuz bir uyum
    içinde çalışır" cümlesini YASAK ÖRNEK olarak birebir veriyordu — ve model onu
    kelimesi kelimesine yazıp bankaya soktu. Prompt'a güvenmek YETMİYOR.

    Denetim ÇÖKERSE üretimi durdurmayız: hepsi sağlam sayılır ve loglanır. Aksi hâlde
    tek bir LLM arızası bankayı sıfırlardı.
    """
    if not topics:
        return []
    if llm is None:
        return [Verdict(index=i, solid=True, reason="denetlenemedi (LLM yok)")
                for i in range(len(topics))]

    liste = "\n".join(f"{i}. {t}" for i, t in enumerate(topics))
    try:
        v = llm(_VERIFY_PROMPT.format(liste=liste), _Verdicts)
    except Exception as e:   # noqa: BLE001 — denetim çökse de üretim durmamalı
        log.warning(f"[konu] doğrulama kapısı çalışmadı ({e}) → hepsi geçti sayılıyor")
        return [Verdict(index=i, solid=True, reason=f"denetlenemedi ({e})")
                for i in range(len(topics))]

    # Model bazı konulara yargı vermemiş olabilir. Yargısı OLMAYANI SAĞLAM SAYMAK
    # kapıyı delmektir — çöp konu sessizce içeri girer.
    yargi = {int(x.index): x for x in v.verdicts}
    return [yargi.get(i, Verdict(index=i, solid=False,
                                 reason="model bu konuya yargı vermedi"))
            for i in range(len(topics))]
```

- [ ] **Step 4: Testi koş**

Run: `python -m pytest tests/test_topic_verify.py -q`
Expected: PASS (6 test)

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/topic_propose.py
git add -f tests/test_topic_verify.py
git commit -m "feat(bank): dogrulama kapisi - prompt'a guvenmek yetmiyor (olculdu)"
```

---

## Task 5: `topic_miner` sadeleşir — yalnız KANIT toplar

**Files:**
- Modify: `src/short_bot/topic_miner.py`
- Test: `tests/test_topic_miner.py` (mevcut — güncellenir), `tests/test_topic_bank_flow.py` (yeni)

- [ ] **Step 1: Yeni akış testini yaz**

`tests/test_topic_bank_flow.py`:

```python
"""refresh_topic_bank uçtan uca — YENİ AKIŞ.

  kanıt = madencilik (API anahtarı VARSA; yoksa [])
  konular = propose_topics(niş, kanıt=kanıt, mevcut=banka)
  yargılar = verify_topics(konular)
  taze = fuzzy-dedup(yargıyı geçenler)
  insert

API anahtarı ve referans kanal artık İKİSİ DE OPSİYONEL. Banka asla kurumaz.
"""
import pytest

from short_bot.db import all_bank_topics, init_db, insert_bank_topics
from short_bot.topic_miner import refresh_topic_bank


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def _llm(topics, verdicts=None):
    """Sahte Sonnet: ilk çağrı öneri, ikinci çağrı yargı."""
    def _f(prompt, schema, **kw):
        if "verdicts" in schema.model_json_schema().get("properties", {}):
            n = len(topics)
            v = verdicts if verdicts is not None else [
                {"index": i, "solid": True} for i in range(n)]
            return schema.model_validate({"verdicts": v})
        return schema.model_validate({"topics": topics})
    return _f


def _konu(t, src="", views=0, subs=0):
    return {"topic": t, "source_title": src, "views": views, "subs": subs,
            "hook_pattern": ""}


def test_API_ANAHTARI_YOKKEN_banka_dolar(tmp_path):
    """ESKİDEN: RuntimeError('YouTube API anahtarı yok') → banka HİÇ dolmuyordu."""
    eng = _eng(tmp_path)
    res = refresh_topic_bank(
        eng, "k", "insan vucudu", language="tr", api_keys=[],
        llm=_llm([_konu("Mide ic zari 3-4 gunde bir yenilenir")]))
    assert res["added"] == 1
    rows = all_bank_topics(eng, "k")
    assert rows[0]["source"] == "llm"       # kanıtsız, dürüstçe etiketli


def test_madencilik_PATLASA_da_banka_dolar(tmp_path, monkeypatch):
    """Kota doldu / ağ gitti → üretim yine koşar, loglanır."""
    import short_bot.topic_miner as M

    def _patla(*a, **kw):
        raise RuntimeError("kota doldu")

    monkeypatch.setattr(M, "mine_evidence", _patla)
    eng = _eng(tmp_path)
    res = refresh_topic_bank(
        eng, "k", "insan vucudu", language="tr", api_keys=["K"],
        llm=_llm([_konu("DNA gunde 10 bin kez hasar gorur")]))
    assert res["added"] == 1


def test_TAZE_OUTLIER_YOKSA_uretim_kosar(tmp_path, monkeypatch):
    """ESKİDEN: ValueError('TAZE outlier bulunamadı') → madencilik TAMAMEN duruyordu."""
    import short_bot.topic_miner as M
    monkeypatch.setattr(M, "mine_evidence", lambda *a, **kw: [])
    eng = _eng(tmp_path)
    res = refresh_topic_bank(
        eng, "k", "insan vucudu", language="tr", api_keys=["K"],
        llm=_llm([_konu("Kornea 24 saatte kendini onarir")]))
    assert res["added"] == 1


def test_DOGRULAMADAN_DUSEN_konu_BANKAYA_GIRMEZ(tmp_path, monkeypatch):
    import short_bot.topic_miner as M
    monkeypatch.setattr(M, "mine_evidence", lambda *a, **kw: [])
    eng = _eng(tmp_path)
    res = refresh_topic_bank(
        eng, "k", "x", language="tr", api_keys=[],
        llm=_llm([_konu("Ici bos genelleme"), _konu("Saglam somut olgu burada")],
                 verdicts=[{"index": 0, "solid": False, "reason": "içi boş"},
                           {"index": 1, "solid": True}]))
    assert res["added"] == 1
    assert res["rejected"] == 1
    assert [r["topic"] for r in all_bank_topics(eng, "k")] == \
        ["Saglam somut olgu burada"]


def test_HEPSI_DUSERSE_sifir_eklenir_ve_UYARILIR(tmp_path, monkeypatch, caplog):
    import logging

    import short_bot.topic_miner as M
    monkeypatch.setattr(M, "mine_evidence", lambda *a, **kw: [])
    eng = _eng(tmp_path)
    with caplog.at_level(logging.WARNING):
        res = refresh_topic_bank(
            eng, "k", "x", language="tr", api_keys=[],
            llm=_llm([_konu("Cop konu")],
                     verdicts=[{"index": 0, "solid": False, "reason": "boş"}]))
    assert res["added"] == 0
    assert "doğrulamayı geçmedi" in caplog.text


def test_MUKERRER_konu_elenir(tmp_path, monkeypatch):
    """fuzzy-dedup regresyon kalkanı."""
    import short_bot.topic_miner as M
    monkeypatch.setattr(M, "mine_evidence", lambda *a, **kw: [])
    eng = _eng(tmp_path)
    insert_bank_topics(eng, "k", [
        {"topic": "Karaciger kendini 3 haftada yeniler", "source_title": "V",
         "views": 1, "subs": 1}])
    res = refresh_topic_bank(
        eng, "k", "x", language="tr", api_keys=[],
        llm=_llm([_konu("Karaciger kendini 3 haftada yeniler.")]))
    assert res["added"] == 0
    assert res["skipped_dup"] == 1


def test_LLM_YOKSA_hata(tmp_path):
    """MEKANİK FALLBACK YOK."""
    eng = _eng(tmp_path)
    with pytest.raises(RuntimeError, match="konu üretilemedi"):
        refresh_topic_bank(eng, "k", "x", language="tr", api_keys=[], llm=None)
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_topic_bank_flow.py -q`
Expected: FAIL — `TypeError: refresh_topic_bank() got an unexpected keyword argument 'llm'`

- [ ] **Step 3: `topic_miner.py`'yi sadeleştir**

Silinecekler: `_MinedTopic`, `_MinedTopics`, `_META_WORDS`, `_drop_meta_topics`,
`_distill_prompt`, `_distill`, `_DISTILL_OVERSAMPLE`, `_LANG_NAMES` (hepsi
`topic_propose`'a taşındı ya da gereksiz).

`mine_topics_via_api` → `mine_evidence` olur ve **konu değil KANIT** döndürür:

```python
def mine_evidence(niche_query: str, *, api_keys: list, language: str = "tr",
                  anchor: str = "", llm_call=None, count: int = 12,
                  keywords=None, reference_channels=None,
                  exclude_sources=None, rotate: int = 0,
                  http_get=None) -> list[dict]:
    """YouTube outlier KANITI topla — konu ÜRETMEZ (o iş topic_propose'un).

    Dönen satırlar: {"source_title", "views", "subs", "ratio", "video_id", "ref"}
    ``ref=True`` → referans kanalın kendi outlier'ı (format+kitle kanıtlı).

    TAZE OUTLIER YOKSA BOŞ LİSTE DÖNER — hata FIRLATMAZ. Eskiden ValueError
    fırlıyordu ve madencilik TAMAMEN duruyordu; artık üretim kanıtsız koşar
    (bkz. topic_propose: kanıt İLHAM, zorunluluk değil).
    """
    from short_bot.yt_outliers import channel_outlier_shorts, search_outlier_shorts
    known = {str(s).strip().lower() for s in (exclude_sources or []) if str(s).strip()}

    # 0) Referans kanallar — kanıt en güçlü kaynak.
    ref_rows, seen_ids = [], set()
    for ref in (reference_channels or [])[:10]:
        try:
            found = channel_outlier_shorts(ref, api_keys=api_keys, limit=count * 3,
                                           http_get=http_get)
        except Exception as e:   # noqa: BLE001 — bir kanal ötekileri durdurmasın
            log.info(f"topic_miner: referans kanal atlandı ({ref!r}): {e}")
            continue
        for r in found:
            if r["video_id"] not in seen_ids:
                seen_ids.add(r["video_id"])
                r["ref"] = True
                ref_rows.append(r)
    ref_rows = _drop_known(ref_rows, known)
    ref_rows.sort(key=lambda r: r.get("ratio", 0), reverse=True)
    if len(ref_rows) >= count:
        log.info(f"topic_miner: referans kanallardan {len(ref_rows)} taze kanıt "
                 f"(arama atlanıyor, kota tasarrufu)")
        return ref_rows[:count * 3]

    # 1) Arama havuzu (HAM çek; kademeler yerelde — ekstra birim yakılmaz).
    queries = _search_queries(niche_query, language, llm_call, keywords=keywords,
                              rotate=rotate)
    if anchor and all(anchor.lower() != q.lower() for q in queries):
        queries.append(anchor)
    pool = []
    for q in queries[:4]:
        lang_q = "en" if (anchor and q == anchor) else language
        try:
            found = search_outlier_shorts(q, api_keys=api_keys, language=lang_q,
                                          limit=count * 4, http_get=http_get,
                                          min_views=1_000, max_subs=10**12,
                                          min_ratio=0.0)
        except Exception as e:   # noqa: BLE001 — kota/ağ: kanıtsız devam ederiz
            log.info(f"topic_miner: '{q}' araması atlandı: {e}")
            continue
        for r in found:
            if r["video_id"] not in seen_ids:
                seen_ids.add(r["video_id"])
                r["ref"] = False
                pool.append(r)

    havuz_ham = len(pool)
    pool = _drop_known(pool, known)
    log.info(f"topic_miner: havuz {havuz_ham} video → {havuz_ham - len(pool)} bilinen "
             f"elendi → {len(pool)} taze")

    rows = []
    for tier in _FILTER_TIERS:
        rows = _apply_tier(pool, tier)
        if rows:
            break
        log.info("topic_miner: filtre kademesi gevşetiliyor (0 outlier)")
    rows.sort(key=lambda r: r.get("ratio", 0), reverse=True)
    return (ref_rows + rows)[:count * 3]
```

`_search_queries`'in **keywords kısa devresi kaldırılır**:

```python
def _search_queries(niche_query: str, language: str, llm_call,
                    keywords=None, rotate: int = 0) -> list[str]:
    """Nişten KISA YouTube arama sorguları üret.

    ``keywords`` artık KISA DEVRE YAPMAZ, LLM'e İPUCU olur. Eskiden keywords doluysa
    fonksiyon TEK sorgu döndürüp LLM'e hiç gitmiyordu — arama havuzu tek sorguya
    iniyordu ve niş hızla tükeniyordu.
    """
    kw = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    short = _short_query(niche_query)
    fallback = ([" ".join(kw[:3])] if kw
                else ([" ".join(short.split()[:3])] if short else ["ilginç bilgiler"]))
    if llm_call is None:
        return fallback
    lang = _LANG_NAMES_Q.get(language, "Türkçe")
    ipucu = f'\nKANAL ANAHTAR KELİMELERİ (ipucu): {", ".join(kw[:6])}' if kw else ""
    try:
        v = run_json(
            f'Şu YouTube Shorts nişi için {_QUERY_POOL} KISA arama sorgusu üret. '
            f'Her biri 2-3 yaygın {lang} kelime; talimat değil ARAMA TERİMİ.\n'
            f'ÖNEMLİ: sorgular nişin FARKLI KÖŞELERİNİ taramalı — birbirinin '
            f'eşanlamlısı olmasın. Aynı şeyi soran sorgular YouTube\'dan aynı '
            f'videoları getirir ve yeni konu bulunamaz.\n'
            f'SÖZDE-BİLİM MIKNATISLARI YASAK: "doğal şifa", "mucize kür", "detoks" '
            f'gibi terimler alternatif tıp içeriği getirir — bilim kanalına ÇÖP taşır. '
            f'Sorgular SOMUT olguları hedeflesin: organ, hücre, mekanizma, olay.\n'
            f'NİŞ: "{short}"{ipucu}\n'
            f'SADECE JSON: {{"queries": ["...", "...", "..."]}}',
            _SearchQueries, claude_path=llm_call.claude_path, model=llm_call.model,
            backend=llm_call.backend, api_key=llm_call.api_key,
            retries=1, timeout_s=60)
        out = [q.strip() for q in v.queries if (q or "").strip()][:_QUERY_POOL]
    except Exception as e:   # noqa: BLE001
        log.info(f"topic_miner: sorgu türetme atlandı ({e}) → fallback")
        return fallback
    if not out:
        return fallback
    n = min(_QUERY_USE, len(out))
    secili = [out[(int(rotate) + i) % len(out)] for i in range(n)]
    log.info(f"topic_miner: {len(out)} sorgu üretildi, {n} tanesi aranıyor "
             f"(kaydırma {rotate}): {secili}")
    return secili
```

`_LANG_NAMES` → `_LANG_NAMES_Q` olarak kalır (yalnız sorgu prompt'u kullanıyor).

`refresh_topic_bank` yeni akış:

```python
def refresh_topic_bank(eng, channel_slug: str, niche_query: str, *,
                       language: str = "tr", api_keys: list | None = None,
                       anchor: str = "", llm_call=None, llm=None, http_get=None,
                       keywords=None, reference_channels=None, **_compat) -> dict:
    """kanıt → öneri → doğrulama → dedup → insert.

    {"added": N, "skipped_dup": M, "rejected": R}

    API ANAHTARI VE REFERANS KANAL İKİSİ DE OPSİYONEL:
      • api_keys yoksa madencilik atlanır → kanıtsız üretim (banka asla kurumaz)
      • taze outlier yoksa madenci boş liste döner → kanıtsız üretim
      • madencilik patlarsa (kota/ağ) loglanır → kanıtsız üretim

    ``llm``: Sonnet çağırıcısı (prompt, schema) → örnek. YOKSA RuntimeError —
    mekanik fallback KALDIRILDI (ham başlığı konu yapmak, ölçülen çöpün kaynağıydı).
    ``llm_call``: arama SORGUSU üretimi için ucuz model (opsiyonel).
    """
    from short_bot.db import all_bank_topics, insert_bank_topics
    from short_bot.topic_propose import propose_topics, verify_topics

    bank = all_bank_topics(eng, channel_slug)
    existing = [r["topic"] for r in bank]
    sources = {(r.get("source_title") or "").strip().lower()
               for r in bank if (r.get("source_title") or "").strip()}

    # 1) KANIT (opsiyonel)
    kanit: list[dict] = []
    if api_keys:
        try:
            kanit = mine_evidence(niche_query, api_keys=api_keys, language=language,
                                  anchor=anchor, llm_call=llm_call, http_get=http_get,
                                  keywords=keywords,
                                  reference_channels=reference_channels,
                                  exclude_sources=sources, rotate=len(bank))
        except Exception as e:   # noqa: BLE001 — kanıt YOK'sa üretim yine koşar
            log.warning(f"topic_miner: kanıt madenciliği başarısız ({e}) → "
                        f"kanıtsız üretime geçiliyor")
    else:
        log.info("topic_miner: YouTube API anahtarı yok → kanıtsız üretim")

    # 2) ÖNERİ
    onerilen = propose_topics(niche_query, language=language, evidence=kanit,
                              existing=existing, count=12, llm=llm)

    # 3) DOĞRULAMA KAPISI — prompt'a güvenmek yetmiyor (ölçüldü).
    yargilar = verify_topics([t.topic for t in onerilen], language=language, llm=llm)
    gecen, dusen = [], 0
    for t, y in zip(onerilen, yargilar):
        if y.solid:
            gecen.append(t)
        else:
            dusen += 1
            log.info(f"topic_miner: konu ELENDİ ({y.reason}): {t.topic[:60]}")
    if onerilen and not gecen:
        log.warning(f"topic_miner: {len(onerilen)} önerinin HİÇBİRİ doğrulamayı "
                    f"geçmedi — hiçbir konu eklenmedi")

    # 4) DEDUP + INSERT
    fresh, dup = [], 0
    for t in gecen:
        src = (t.source_title or "").strip().lower()
        if src and src in sources:
            dup += 1
            continue
        if any(fuzz.ratio(t.topic.lower(), e.lower()) > _DUP_THRESHOLD
               for e in existing):
            dup += 1
            continue
        existing.append(t.topic)
        if src:
            sources.add(src)
        fresh.append(t.model_dump())
    insert_bank_topics(eng, channel_slug, fresh)
    log.info(f"topic_miner: {len(fresh)} yeni konu ({dup} mükerrer, {dusen} elendi)")
    return {"added": len(fresh), "skipped_dup": dup, "rejected": dusen}
```

- [ ] **Step 4: Testi koş**

Run: `python -m pytest tests/test_topic_bank_flow.py -q`
Expected: PASS (7 test)

- [ ] **Step 5: Mevcut madenci testlerini güncelle**

`tests/test_topic_miner.py` — `mine_topics_via_api` çağrıları `mine_evidence`'e döner
ve artık konu değil kanıt satırı bekler. `_distill` testleri **silinir** (fonksiyon
`topic_propose`'a taşındı, orada test ediliyor). `refresh_topic_bank` testleri `llm=`
alır.

> **Uygulayıcıya not:** Bu dosyayı aç, her testin NEYİ kanıtladığına bak. Kanıt
> toplama davranışı (referans-önce, kademeli filtre, `_drop_known`, sorgu rotasyonu)
> KORUNMALI — o testler `mine_evidence`'e uyarlanır. Konu damıtma davranışını sınayan
> testler artık `tests/test_topic_propose.py`'de.

- [ ] **Step 6: Çağıranları güncelle**

| Yer | Değişiklik |
|---|---|
| `src/short_bot/topic_autofill.py` | `refresh_topic_bank(..., llm=<sonnet>)`; `if not api_keys: return 0` **KALDIRILIR** (anahtarsız da doldurabilir) |
| `src/short_bot/web/routes/topic_bank.py` | `_miner_kwargs`: `api_keys` artık zorunlu değil; `llm=` eklenir |
| `src/short_bot/web/autopilot_deps.py` | varsa aynı |

`llm` şöyle kurulur. **Aynı imza her yerde** (`_sonnet()` argümansız; ayarları
`current_app`'ten okur) — testler onu monkeypatch'liyor:

```python
# web/routes/topic_bank.py ve web/autopilot_deps.py içinde AYNI:
def _sonnet():
    """Konu üretimi ve doğrulama Sonnet 5 ile koşar (kullanıcının açık tercihi).

    Damıtma eskiden role='default' ile koşuyordu = google/gemini-3.1-flash-lite,
    sistemin EN UCUZ modeli. Ölçüldü: bankanın %85'i çöp oldu.
    """
    from short_bot.llm_sonnet import sonnet_json
    settings = current_app.config["SHORTBOT_SETTINGS"]
    secrets = _secrets()          # mevcut yardımcı (yoksa lang_packs.py'dekini kopyala)

    def _f(prompt, schema, **kw):
        return sonnet_json(prompt, schema,
                           claude_path=settings.claude_cli_path,
                           openrouter_model=settings.openrouter_models.get(
                               "script", "anthropic/claude-sonnet-5"),
                           openrouter_key=secrets.get("openrouter_api_key"))
    return _f
```

`topic_autofill.py` Flask bağlamında koşmuyor (scheduler thread'i) → oradaki çağırıcı
`settings`/`secrets`i parametre alır; `scheduler.py` zaten ikisini de elinde tutuyor.

- [ ] **Step 7: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 8: Commit**

```bash
git add src/short_bot/topic_miner.py src/short_bot/topic_autofill.py src/short_bot/web/routes/topic_bank.py
git add -f tests/test_topic_bank_flow.py tests/test_topic_miner.py
git commit -m "feat(bank): madenci yalniz KANIT toplar; API anahtari ve referans kanal OPSIYONEL"
```

---

## Task 6: Banka denetimi — mevcut çöpü temizle

**Files:**
- Create: `src/short_bot/topic_audit.py`
- Test: `tests/test_topic_audit.py` (yeni)

- [ ] **Step 1: Testi yaz**

`tests/test_topic_audit.py`:

```python
"""Mevcut bankadaki çöpü denetle.

ÖLÇÜLDÜ: vucudun-gizli-onarim-gucu bankasının 27 aktif konusundan 23'ü çöp (%85);
bazıları bilimsel olarak YANLIŞ ("muz saniyeler içinde sindirilir"). Bunlar üretilmeyi
bekliyordu — kanalın otoritesi ürünüdür.
"""
from short_bot.db import all_bank_topics, init_db, insert_bank_topics
from short_bot.topic_audit import audit_bank


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def _doldur(eng, konular):
    insert_bank_topics(eng, "k", [
        {"topic": t, "source_title": f"V{i}", "views": 1, "subs": 1}
        for i, t in enumerate(konular)])


def _llm(verdicts):
    def _f(prompt, schema, **kw):
        return schema.model_validate({"verdicts": verdicts})
    return _f


def test_COP_konular_REJECTED_isaretlenir(tmp_path):
    eng = _eng(tmp_path)
    _doldur(eng, ["Ici bos genelleme", "Saglam somut olgu"])
    res = audit_bank(eng, "k", language="tr",
                     llm=_llm([{"index": 0, "solid": False, "reason": "içi boş"},
                               {"index": 1, "solid": True}]))
    assert res == {"checked": 2, "rejected": 1}
    durum = {r["topic"]: r["status"] for r in all_bank_topics(eng, "k")}
    assert durum["Ici bos genelleme"] == "rejected"
    assert durum["Saglam somut olgu"] == "active"


def test_KULLANILMIS_konulara_dokunulmaz(tmp_path):
    """'used' konular geçmiştir; onları reddetmek anlamsız (video zaten üretildi)."""
    from short_bot.db import mark_bank_topic_used
    eng = _eng(tmp_path)
    _doldur(eng, ["Zaten uretilmis konu", "Aktif konu"])
    rows = all_bank_topics(eng, "k")
    kullanilmis = next(r for r in rows if r["topic"] == "Zaten uretilmis konu")
    mark_bank_topic_used(eng, kullanilmis["id"])

    res = audit_bank(eng, "k", language="tr",
                     llm=_llm([{"index": 0, "solid": False, "reason": "x"}]))
    assert res["checked"] == 1      # yalnız AKTİF konu denetlendi


def test_BOS_banka_LLM_CAGIRMAZ(tmp_path):
    def _patla(*a, **kw):
        raise AssertionError("boş banka için LLM çağrıldı")
    assert audit_bank(_eng(tmp_path), "k", language="tr", llm=_patla) == \
        {"checked": 0, "rejected": 0}


def test_LLM_PATLARSA_hicbir_sey_REDDEDILMEZ(tmp_path):
    """Denetim çökerse SAĞLAM konuları silmektense hiçbir şey yapmamak yeğdir."""
    eng = _eng(tmp_path)
    _doldur(eng, ["Konu bir", "Konu iki"])

    def _patla(*a, **kw):
        raise RuntimeError("sonnet yok")

    res = audit_bank(eng, "k", language="tr", llm=_patla)
    assert res["rejected"] == 0
    assert all(r["status"] == "active" for r in all_bank_topics(eng, "k"))
```

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_topic_audit.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'short_bot.topic_audit'`

- [ ] **Step 3: `topic_audit.py`'yi yaz**

```python
"""Bankadaki MEVCUT konuları denetle — çöpü 'rejected' işaretle.

NEDEN VAR (ölçüldü): konu damıtması sistemin en ucuz modelinde (gemini-flash-lite)
koşuyordu ve banka çöp biriktirdi:

    vucudun-gizli-onarim-gucu :  27 aktif konudan 23'ü ÇÖP (%85)
    bilim-tarihinin-sok-anlari:  21 aktif konudan  5'i ÇÖP (%23)

Bazıları sadece boş değil, BİLİMSEL OLARAK YANLIŞ:
    "Vücudunuz muzu sindirim sistemi boyunca SANİYELER İÇİNDE…"  ← saatler sürer
    "Kanser, bağışıklık sisteminin kendi hücrelerini tanıyamamasıdır"  ← nedensellik ters

Bunlar bankada ÜRETİLMEYİ BEKLİYORDU. Kanalın otoritesi ürünüdür; bir tek yanlış
video onu yakar.

Yeni konular artık üretim anında doğrulanıyor (topic_propose.verify_topics). Bu modül
ESKİ kayıtlar için: tek seferlik temizlik + panelden talep üzerine.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def audit_bank(eng, channel: str, *, language: str, llm) -> dict:
    """AKTİF konuları denetle, çöpü 'rejected' işaretle.

    {"checked": N, "rejected": M}

    Denetim ÇÖKERSE hiçbir şey reddedilmez: sağlam konuları silmektense hiçbir şey
    yapmamak yeğdir.
    """
    from short_bot.db import all_bank_topics, reject_bank_topic
    from short_bot.topic_propose import verify_topics

    aktif = [r for r in all_bank_topics(eng, channel) if r["status"] == "active"]
    if not aktif:
        return {"checked": 0, "rejected": 0}

    yargilar = verify_topics([r["topic"] for r in aktif], language=language, llm=llm)

    red = 0
    for r, y in zip(aktif, yargilar):
        if y.solid:
            continue
        # verify_topics denetim çökünce "denetlenemedi" gerekçesiyle solid=True
        # döndürür; buraya yalnız GERÇEK çöp yargısı düşer.
        reject_bank_topic(eng, r["id"])
        red += 1
        log.info(f"[denetim] {channel}: REDDEDİLDİ ({y.reason}) → {r['topic'][:60]}")

    log.info(f"[denetim] {channel}: {len(aktif)} konu denetlendi, {red} reddedildi")
    return {"checked": len(aktif), "rejected": red}
```

- [ ] **Step 4: Testi koş**

Run: `python -m pytest tests/test_topic_audit.py -q`
Expected: PASS (4 test)

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/topic_audit.py
git add -f tests/test_topic_audit.py
git commit -m "feat(bank): audit_bank - mevcut copu denetle ve reddet"
```

---

## Task 7: Panel — kaynak rozeti + denetle düğmesi

**Files:**
- Modify: `src/short_bot/web/routes/topic_bank.py`
- Modify: `src/short_bot/web/templates/topic_bank.html.j2`
- Test: `tests/test_web_topic_bank.py` (mevcut ya da yeni)

- [ ] **Step 1: Testi yaz**

`tests/test_web_topic_bank.py` sonuna (dosya yoksa `tests/test_web_lang_packs.py`
`_app` desenini kopyalayarak oluştur):

```python
def test_KAYNAK_rozeti_gorunur(tmp_path):
    """Kanıtlı mı, üretilmiş mi — kullanıcı bilmeli."""
    from short_bot.db import insert_bank_topics
    a, db = _app(tmp_path)
    insert_bank_topics(init_db(db), "k", [
        {"topic": "Kanitli konu", "source_title": "V", "views": 100_000,
         "subs": 1_000, "source": "search"},
        {"topic": "Modelin urettigi konu", "source_title": "", "views": 0,
         "subs": 0, "source": "llm"}])
    body = a.test_client().get("/channels/k/topic-bank").data.decode("utf-8")
    assert "model önerisi" in body.lower()
    assert "100× patlama" in body or "100x patlama" in body


def test_DENETLE_dugmesi_var(tmp_path):
    a, _ = _app(tmp_path)
    body = a.test_client().get("/channels/k/topic-bank").data.decode("utf-8")
    assert "/topic-bank/audit" in body
    assert "denetle" in body.lower()


def test_denetle_rotasi_COP_konuyu_REDDEDER(tmp_path, monkeypatch):
    """Rota SENKRON: gerçek audit_bank koşar, yalnız LLM sahte."""
    import short_bot.web.routes.topic_bank as TB
    from short_bot.db import all_bank_topics, insert_bank_topics
    a, db = _app(tmp_path)
    eng = init_db(db)
    insert_bank_topics(eng, "k", [
        {"topic": "Ici bos genelleme", "source_title": "V1", "views": 1, "subs": 1},
        {"topic": "Saglam somut olgu", "source_title": "V2", "views": 1, "subs": 1}])

    def _sahte_llm():
        def _f(prompt, schema, **kw):
            return schema.model_validate({"verdicts": [
                {"index": 0, "solid": False, "reason": "içi boş"},
                {"index": 1, "solid": True, "reason": ""}]})
        return _f

    monkeypatch.setattr(TB, "_sonnet", _sahte_llm)
    r = a.test_client().post("/channels/k/topic-bank/audit", follow_redirects=True)
    body = r.data.decode("utf-8")
    assert "2 konu denetlendi" in body
    assert "1 tanesi reddedildi" in body

    durum = {x["topic"]: x["status"] for x in all_bank_topics(eng, "k")}
    assert durum["Ici bos genelleme"] == "rejected"
    assert durum["Saglam somut olgu"] == "active"
```

> **Uygulayıcıya not — rota SENKRON olmalı:** "Yenile" rotası daemon thread kullanıyor
> çünkü madencilik dakikalar sürüyor. Denetim ise TEK LLM çağrısı (~30 sn) ve kullanıcı
> sonucu ANINDA görmeli ("kaç konu elendi"). Thread'e alırsak panel "birkaç dakika
> içinde biter" demek zorunda kalır ve sonucu asla göstermez — aynı yalanı autopilot
> planlayıcısında yaşadık ve düzelttik.

- [ ] **Step 2: Testi koş, kırıldığını gör**

Run: `python -m pytest tests/test_web_topic_bank.py -q`
Expected: FAIL — 404 / rozet yok

- [ ] **Step 3: Rotayı ekle**

`src/short_bot/web/routes/topic_bank.py`:

```python
@bp.post("/channels/<slug>/topic-bank/audit")
def audit(slug):
    """Bankayı denetle: içi boş / vaat eden / bilimsel olarak yanlış konuları reddet.

    SENKRON. Denetim tek LLM çağrısı (~30 sn) ve kullanıcı sonucu ANINDA görmeli.
    "Birkaç dakika içinde biter" diyen bir panel, sonucu göstermeyen bir paneldir.
    """
    from short_bot.topic_audit import audit_bank
    cfg = _load_cfg(slug)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    try:
        res = audit_bank(eng, slug, language=cfg.language, llm=_sonnet())
    except Exception as e:   # noqa: BLE001 — kullanıcıya sebebi söyle
        flash(f"Denetim başarısız: {e}", "error")
        return redirect(url_for("topic_bank.page", slug=slug))
    flash(f"{res['checked']} konu denetlendi, {res['rejected']} tanesi reddedildi "
          f"(içi boş / vaat eden / bilimsel olarak yanlış).", "success")
    return redirect(url_for("topic_bank.page", slug=slug))
```

`_sonnet()` yardımcısı (Task 5, Step 6'da tanımlanan desen) aynı dosyaya konur.

- [ ] **Step 4: Şablona rozet + düğme ekle**

`topic_bank.html.j2`:

Kaynak rozeti — patlama katsayısının yanına:

```jinja
{% if r.source == 'llm' %}
  <span class="px-2 py-0.5 rounded-md bg-claude-surface-alt text-claude-muted
               font-semibold">model önerisi</span>
{% elif r.source == 'reference' %}
  <span class="px-2 py-0.5 rounded-md bg-claude-accent/10 text-claude-accent
               font-semibold">referans kanal</span>
{% endif %}
```

Denetle düğmesi — "Yenile"nin yanına:

```jinja
<form method="post" action="/channels/{{ slug }}/topic-bank/audit"
      onsubmit="return confirm('Bankadaki {{ rows|length }} aktif konu denetlenecek. İçi boş, vaat eden ya da bilimsel olarak yanlış olanlar REDDEDİLECEK. Devam?')">
  <button class="px-4 py-2 rounded-lg bg-white border border-claude-border
                 text-sm font-semibold text-claude-text hover:bg-claude-surface-alt">
    Bankayı denetle</button>
</form>
```

- [ ] **Step 5: Testleri koş**

Run: `python -m pytest tests/test_web_topic_bank.py -q`
Expected: PASS

- [ ] **Step 6: Tam paket**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 7: Commit**

```bash
git add src/short_bot/web/routes/topic_bank.py src/short_bot/web/templates/topic_bank.html.j2
git add -f tests/test_web_topic_bank.py
git commit -m "feat(bank): panel - kaynak rozeti + Bankayi denetle dugmesi"
```

---

## Task 8: GERÇEK Sonnet ile kalite kapısı

Şimdiye kadar her şey sahte `llm` ile test edildi. Sonnet'in **gerçekten** iyi konu üretip çöpü **gerçekten** elediği ÖLÇÜLMEDİ.

**Files:**
- Test: `tests/test_topic_propose_real.py` (yeni)

- [ ] **Step 1: Kalite kapısı testini yaz**

`tests/test_topic_propose_real.py`:

```python
"""GERÇEK Sonnet 5 ile kalite kapısı (dil paketindeki de_real deseninin aynısı).

Diğer testler sahte `llm` kullanır — onlar akışı kanıtlar, KALİTEYİ değil.
Bu dosya modelin gerçekten iş gördüğünü kanıtlar.

YAVAŞ (~1-2 dk). Kırılırsa prompt düzeltilmeli — testi zayıflatarak geçirme.
"""
import pytest

from short_bot.llm_sonnet import sonnet_json
from short_bot.topic_propose import propose_topics, verify_topics


def _sonnet(prompt, schema, **kw):
    return sonnet_json(prompt, schema)


# GERÇEK bankadan alınmış çöp (ölçüldü)
COP = [
    "Vücudumuzdaki her organ, hayatta kalmak için kusursuz bir uyum içinde çalışır.",
    "Vücuttaki kemik sayısı şaşırtıcı rakamlarla ifade edilebilir",
    "Vücudunuz, yediğiniz bir muzu sindirim sistemi boyunca saniyeler içinde sindirir",
]
SAGLAM = [
    "Bebekler 300 kemikle doğar; yetişkinlikte bu sayı 206'ya iner",
    "Karaciğerinin %70'ini kaybetsen bile 3 haftada kendini yeniden büyütür",
]


@pytest.mark.slow
def test_dogrulama_GERCEK_copu_eler():
    y = verify_topics(COP + SAGLAM, language="tr", llm=_sonnet)
    cop_yargi = y[:len(COP)]
    saglam_yargi = y[len(COP):]
    assert not any(v.solid for v in cop_yargi), \
        f"çöp geçti: {[v.reason for v in cop_yargi if v.solid]}"
    assert all(v.solid for v in saglam_yargi), \
        f"sağlam elendi: {[v.reason for v in saglam_yargi if not v.solid]}"


@pytest.mark.slow
def test_KANITSIZ_uretim_SAGLAM_konu_verir():
    """Kullanıcının tezi: güçlü model, kanıt olmadan da iyi konu bulur."""
    out = propose_topics(
        "insan vucudunun gizli onarim ve yenilenme mekanizmalari",
        language="tr", evidence=[], existing=[], count=8, llm=_sonnet)
    assert len(out) >= 5, "kanıtsız üretim yeterli konu vermedi"
    assert all(t.source == "llm" for t in out)

    # Üretilenler KENDİ doğrulama kapımızdan geçmeli.
    y = verify_topics([t.topic for t in out], language="tr", llm=_sonnet)
    gecen = sum(1 for v in y if v.solid)
    assert gecen >= len(out) * 0.7, \
        f"üretilen konuların yalnız {gecen}/{len(out)}'i doğrulamayı geçti"
```

`pyproject.toml`'a marker eklenir (yoksa):

```toml
[tool.pytest.ini_options]
markers = ["slow: gerçek LLM çağırır (yavaş, ~1-2 dk)"]
```

- [ ] **Step 2: Testi koş**

Run: `python -m pytest tests/test_topic_propose_real.py -q -m slow`
Expected: PASS

Kırılırsa **prompt'u düzelt**, testi değil. Bu bir kalite kapısıdır.

- [ ] **Step 3: Tam paket (slow dahil)**

Run: `python -m pytest tests/ -q`
Expected: hepsi geçer

- [ ] **Step 4: Commit**

```bash
git add -f tests/test_topic_propose_real.py
git add pyproject.toml
git commit -m "test(bank): GERCEK Sonnet ile kalite kapisi (cop elenir, kanitsiz uretim saglam)"
```

---

## Task 9: Gerçek bankaları denetle ve ölç

Kod bitti; şimdi **gerçek veriyi** temizle. Bu, kullanıcının onayladığı iş.

**Files:** yok (ölçüm + veri temizliği)

- [ ] **Step 1: Denetimi gerçek bankada koştur**

Scratchpad betiği:

```python
import sys
from pathlib import Path
sys.path.insert(0, "D:/short/src")

import yaml
from short_bot.config import list_channels, load_settings
from short_bot.db import init_db
from short_bot.llm_sonnet import sonnet_json
from short_bot.topic_audit import audit_bank

settings = load_settings(Path("D:/short/config/settings.yaml"))
secrets = yaml.safe_load(Path("D:/short/data/secrets.yaml").read_text(encoding="utf-8"))
eng = init_db(Path("D:/short/data/short_bot.sqlite"))

def _llm(prompt, schema, **kw):
    return sonnet_json(prompt, schema, claude_path=settings.claude_cli_path,
                       openrouter_key=secrets.get("openrouter_api_key"))

for cfg in list_channels(Path("D:/short/config/channels")):
    if cfg.content_source != "generator":
        continue
    res = audit_bank(eng, cfg.slug, language=cfg.language, llm=_llm)
    print(f"{cfg.slug}: {res['checked']} denetlendi, {res['rejected']} reddedildi")
```

Beklenen (ölçülene yakın): vucudun ~23 reddedilir, bilim-tarihinin ~5.

- [ ] **Step 2: Bankayı doldur (kanıtsız üretim gerçekten çalışıyor mu)**

Denetimden sonra vucudun'da ~4 konu kalacak → su seviyesi (LOW_WATER=10) altında.
Panelden "Yenile"ye bas ya da betikle `refresh_topic_bank` koştur ve **gerçek çıktıyı
gözle denetle**:

- Konular somut mu (sayı/mekanizma içeriyor mu)?
- `source` etiketi doğru mu?
- Türkçe mi?
- Sözde-bilim var mı?

- [ ] **Step 3: Bulguları raporla**

Denetim öncesi/sonrası konu sayıları, üretilen yeni konulardan örnekler.

- [ ] **Step 4: Commit (varsa düzeltme)**

Prompt düzeltmesi gerektiyse commit et.

---

## Kapsam dışı (bilerek — alt proje 3)

- **Kanal kurma ajanı** ("Almanca bahçecilik kanalı istiyorum, niş bul") → sıradaki spec.
- **Üretilen konuları YouTube'da tek tek DOĞRULAMAK** (niche_finder'ın Veri-Destekli
  modu gibi): aday başına ~102 birim kota. Doğrulama kapısı kaliteyi zaten sağlıyor;
  kanıt istenirse referans kanal/arama zaten kanıt taşıyor. YAGNI.
- **`settings.yaml`'a yeni LLM rolü**: `llm_sonnet` doğrudan Claude CLI kullanıyor
  (kullanıcının açık tercihi). `default` rolü başka yerlerde kullanılmaya devam ediyor.
