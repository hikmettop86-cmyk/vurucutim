# Vahşi Mizah Arketipi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reel motoruna izole bir "vahşi mizah" personası ekle — hayvan konularını mahalle-karakteri mizahıyla, gerçek bilgiye dayanarak anlatan Türkçe kanallar için.

**Architecture:** `ReelConfig.persona` alanı (boş = bugünkü davranış, sıfır regresyon). Persona metni (few-shot + kurallar) dil paketinden gelir ve `reel_narration` prompt'una enjekte edilir. Üretilen senaryo yeni bir `reel_humor_check` kapısından geçer (mevcut olgu kapısının kardeşi). Olgu kapısı da açık kalır.

**Tech Stack:** Python 3.14, pydantic v2, SQLAlchemy Core, pytest, `llm_sonnet.run_json`/`sonnet_json`, OpenRouter (aktif backend).

---

## Notlar (implementasyon başlamadan oku)

- **Test dosyaları, `config/channels/*.yaml`, `docs/superpowers/` GITIGNORE'da** → `git add -f`.
- **Commit mesajları:** PowerShell here-string kesme işaretinde bozulur → mesajı `/tmp/cm.txt`'ye yaz, `git commit -F /tmp/cm.txt`.
- **Türkçe cevap**, tam ortografik doğruluk.
- **Panel yeniden başlatılmadan** Python değişikliklerini görmez (uçtan uca test için taze `python -m short_bot run` süreci kullan).
- LLM çağrısı OpenRouter'a gitmeli; `claude` CLI boş dönüyor. Kapı modülleri `reel_factcheck` gibi `run_json(..., backend=backend)` kullanır — backend `channel`'dan gelir, üretimde `openrouter`.

## File Structure

- `src/short_bot/config.py` — MODIFY: `ReelConfig.persona` alanı + `to_channel_data` reel dict.
- `src/short_bot/persona.py` — CREATE: `Persona` modeli, `load_persona`, `persona_block`.
- `src/short_bot/lang_pack.py` — MODIFY: `LangPack.personas` alanı + `validate_pack` kontrolü.
- `src/short_bot/langpacks/tr.json` — MODIFY: `personas.vahsi_mizah` (few_shot + rules).
- `src/short_bot/reel_humor_check.py` — CREATE: `HumorIssue`, `check_humor`, `humor_feedback`.
- `src/short_bot/reel_narration.py` — MODIFY: persona enjeksiyonu + mizah kapısı wiring.
- `config/archetypes.json` — MODIFY: `vahsi-mizah` girişi.
- `src/short_bot/channel_agent.py` — MODIFY: mizah niyeti → `reel.persona` işareti.
- `tests/test_persona.py`, `tests/test_reel_humor_check.py`, `tests/test_reel_narration_persona.py` — CREATE.

---

### Task 1: `ReelConfig.persona` alanı

**Files:**
- Modify: `src/short_bot/config.py` (`ReelConfig` sınıfı + `to_channel_data`)
- Test: `tests/test_reel_persona_config.py` (CREATE)

- [ ] **Step 1: Failing test**

```python
# tests/test_reel_persona_config.py
def test_reelconfig_persona_default_bos():
    from short_bot.config import ReelConfig
    c = ReelConfig(enabled=False)
    assert c.persona == ""                      # varsayılan: kişiliksiz


def test_reelconfig_persona_set():
    from short_bot.config import ReelConfig
    c = ReelConfig(enabled=False, persona="vahsi_mizah")
    assert c.persona == "vahsi_mizah"


def test_persona_channel_data_roundtrip(tmp_path):
    from short_bot.config import ChannelConfig, ReelConfig, save_channel, load_channel
    ch = ChannelConfig(slug="m", name="M", language="tr",
                       reel=ReelConfig(enabled=True, persona="vahsi_mizah"))
    p = tmp_path / "m.yaml"
    save_channel(ch, p)
    assert load_channel(str(p)).reel.persona == "vahsi_mizah"
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_reel_persona_config.py -q`
Expected: FAIL (`persona` alanı yok / roundtrip'te kaybolur)

- [ ] **Step 3: Implement**

`ReelConfig` içinde `cta_text_custom` alanının hemen ardına ekle:
```python
    # PERSONA: reel anlatım tonu. "" = kişiliksiz (bugünkü "ilginç bilgiler" tonu).
    # "vahsi_mizah" = hayvanı mahalle-karakterine büründüren komik anlatım.
    # Boş varsayılan KRİTİK: mevcut tüm kanallar bugünkü prompt'u alır → sıfır regresyon.
    persona: str = ""
```

`to_channel_data` reel dict'inde `"cta_text_custom": cfg.reel.cta_text_custom,` satırının ardına ekle:
```python
            "persona": cfg.reel.persona,
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_reel_persona_config.py -q`
Expected: PASS (3 test)

- [ ] **Step 5: Commit**

```bash
git add -f src/short_bot/config.py tests/test_reel_persona_config.py
git commit -F /tmp/cm.txt   # "feat(reel): ReelConfig.persona alani (bos = sifir regresyon)"
```

---

### Task 2: `LangPack.personas` + `tr.json` persona bloğu

**Files:**
- Modify: `src/short_bot/lang_pack.py` (`LangPack` + `validate_pack`)
- Modify: `src/short_bot/langpacks/tr.json`
- Test: `tests/test_lang_pack_persona.py` (CREATE)

- [ ] **Step 1: Failing test**

```python
# tests/test_lang_pack_persona.py
def test_langpack_personas_alani():
    from short_bot.lang_pack import LangPack
    assert "personas" in LangPack.model_fields


def test_tr_paketinde_vahsi_mizah_var():
    from short_bot.lang_pack import load_pack
    pack = load_pack("tr")
    p = pack.personas["vahsi_mizah"]
    assert p["few_shot"].strip()
    assert len(p["rules"]) >= 5


def test_validate_persona_bos_few_shot_yakalar():
    from short_bot.lang_pack import LangPack, validate_pack
    base = load_min_pack()   # aşağıdaki yardımcı
    base.personas = {"vahsi_mizah": {"few_shot": "", "rules": ["x"]}}
    hatalar = validate_pack(base)
    assert any("few_shot" in h for h in hatalar)


def load_min_pack():
    from short_bot.lang_pack import load_pack
    return load_pack("tr").model_copy(deep=True)
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_lang_pack_persona.py -q`
Expected: FAIL (`personas` alanı yok)

- [ ] **Step 3: Implement — model + validate**

`lang_pack.py`, `LangPack` sınıfına alan ekle (mevcut alanların sonuna):
```python
    # Persona metinleri (opsiyonel): slug → {"few_shot": str, "rules": list[str]}.
    # Dile ÖZEL: Türk dizisi referansları yalnız tr paketinde olur. Başka dilde bu
    # personayı istemek load_persona'da RuntimeError verir (sessiz düşme yok).
    personas: dict = Field(default_factory=dict)
```
(Field zaten import ediliyorsa tekrar etme; değilse `from pydantic import Field`.)

`validate_pack` fonksiyonunun sonuna, `return h`'den önce:
```python
    for slug, p in (pack.personas or {}).items():
        if not isinstance(p, dict) or not (p.get("few_shot") or "").strip():
            h.append(f"persona '{slug}': few_shot boş olamaz")
        if not p.get("rules"):
            h.append(f"persona '{slug}': rules boş olamaz")
```

- [ ] **Step 4: Implement — tr.json**

`src/short_bot/langpacks/tr.json`'a en üst düzeyde `"personas"` anahtarı ekle:
```json
  "personas": {
    "vahsi_mizah": {
      "few_shot": "Bugün Zavana'nın bıçkın delikanlısı, ruhsatlı delisinin mahremine giriyoruz. Porsuk Dumrul. Bu kıprağın aşk hayatı mı hacı? Adamın kalbi Bihter'in Behlül'e olan kini gibi taş kesilmiş. Bizim porsuk öyle 'akşam mesaj attım görüldü attı ama dönmedi' diye trip atmaz. O direkt Abdülhey modunda. Bal porsuğu dediğin ormanların yalnız kurdudur. Ne Kızılcık Şerbeti'ndeki gibi aile konseyi ne de 'kayınço yine borç istedi' diye dert yanar. Çiftleşme dönemi gelince bir selamünaleyküm der, işini görür. Sonra çat arazi. Bizim Dumrul'da aşk, Aşk-ı Memnu'daki gibi yasak değil, direkt yasak elmadaki gibi entrikasızdır. Peki ya yenge hanım? Yaprak Dökümü'ndeki Hayriye Hanım gibi 'aman tadımız kaçmasın Ali Rıza Bey' demez. Yavruyu doğurur, kreşmiş özel dersmiş anlamaz, direkt Survivor elemelerine sokar. Aile WhatsApp grubu yok, 'Cumanız mübarek olsun' diyen halalar yok. Sadece doğa, kavga ve hayatta kalma.",
      "rules": [
        "HAYVANI KARAKTERE BÜRÜNDÜR: ona bir isim/lakap ver ('Porsuk Dumrul', 'ormanların yalnız kurdu') ve bir mahalle tipine benzet.",
        "GERÇEK Türk dizisi / pop-kültür referansları kullan (Aşk-ı Memnu, Yaprak Dökümü, Kızılcık Şerbeti, Kurtlar Vadisi, Çukur, Survivor gibi). Davranışı bu dizilere benzet. UYDURMA dizi/karakter YASAK.",
        "MODERN SOSYAL MEDYA DİLİ: 'mesaj attı görüldü', 'konum atmak', 'aile WhatsApp grubu', 'trip atmak' gibi güncel deyimlerle anakronizm yarat.",
        "GERÇEK BİLGİYİ KOMİK ÇERÇEVEYE SOK: hayvanın GERÇEK biyolojisi (avlanma, çiftleşme, yavru bakımı) komik bir hikâyeye dönüşsün. Bilgi DOĞRU, sunum çatlak olsun. Yanlış bilgi vermek YASAK.",
        "ARGO/AĞIZ: anlatıcı mahalleden biri gibi konuşsun ('hacı', 'çat arazi', 'işini görür').",
        "Sonda kısa bir halk ozanı / aşık edebiyatı parodisiyle kapat (kapanış hook'u geri çağırsın)."
      ]
    }
  }
```

- [ ] **Step 5: Run, verify pass**

Run: `python -m pytest tests/test_lang_pack_persona.py -q`
Expected: PASS (3 test)

- [ ] **Step 6: Regresyon — tüm lang_pack testleri**

Run: `python -m pytest tests/ -q -k "lang_pack or langpack"`
Expected: mevcut testler PASS (personas opsiyonel, diğer paketleri bozmaz)

- [ ] **Step 7: Commit**

```bash
git add -f src/short_bot/lang_pack.py src/short_bot/langpacks/tr.json tests/test_lang_pack_persona.py
git commit -F /tmp/cm.txt   # "feat(lang): LangPack.personas + tr vahsi_mizah blogu"
```

---

### Task 3: `persona.py` — yükleme + prompt bloğu

**Files:**
- Create: `src/short_bot/persona.py`
- Test: `tests/test_persona.py` (CREATE)

- [ ] **Step 1: Failing test**

```python
# tests/test_persona.py
import pytest


def test_bos_slug_none():
    from short_bot.persona import load_persona
    assert load_persona("", language="tr") is None


def test_vahsi_mizah_yuklenir():
    from short_bot.persona import load_persona
    p = load_persona("vahsi_mizah", language="tr")
    assert p is not None
    assert p.slug == "vahsi_mizah"
    assert "Porsuk Dumrul" in p.few_shot
    assert len(p.rules) >= 5
    assert p.humor_check is True


def test_bilinmeyen_slug_raise():
    from short_bot.persona import load_persona
    with pytest.raises(RuntimeError, match="persona"):
        load_persona("boyle_bir_persona_yok", language="tr")


def test_yanlis_dilde_raise():
    # Türk dizisi referansları yalnız tr'de. Almanca'da vahsi_mizah RuntimeError.
    from short_bot.persona import load_persona
    with pytest.raises(RuntimeError, match="persona"):
        load_persona("vahsi_mizah", language="de")


def test_persona_block_few_shot_ve_kurallari_icerir():
    from short_bot.persona import load_persona, persona_block
    p = load_persona("vahsi_mizah", language="tr")
    blok = persona_block(p)
    assert "Porsuk Dumrul" in blok          # few-shot örneği
    assert "KARAKTERE BÜRÜNDÜR" in blok      # kurallar
    assert "GERÇEK" in blok
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_persona.py -q`
Expected: FAIL (`persona` modülü yok)

- [ ] **Step 3: Implement**

```python
# src/short_bot/persona.py
"""Reel anlatım personası: few-shot örneği + ton kuralları.

Persona metni DİL PAKETİNDEN gelir (Türk dizisi referansları yalnız tr'de). Bilinmeyen
slug ya da yanlış dil RuntimeError verir — sessizce kişiliksiz'e / yanlış dile düşmek
YASAK: kullanıcı mizah seçtiyse mizah almalı, seçmediyse bugünkü davranışı almalı.
"""
from __future__ import annotations

from pydantic import BaseModel

from short_bot.lang_pack import load_pack


class Persona(BaseModel):
    slug: str
    few_shot: str
    rules: list[str]
    humor_check: bool = True


def load_persona(slug: str, *, language: str) -> Persona | None:
    if not (slug or "").strip():
        return None                      # kişiliksiz: bugünkü prompt
    pack = load_pack(language)
    data = (pack.personas or {}).get(slug)
    if not data:
        raise RuntimeError(
            f"persona '{slug}' {language} dil paketinde yok — "
            f"bu persona bu dilde tanımlı değil (sessiz düşme yok)")
    return Persona(slug=slug, few_shot=data.get("few_shot", ""),
                   rules=list(data.get("rules", [])),
                   humor_check=bool(data.get("humor_check", True)))


def persona_block(persona: Persona) -> str:
    kurallar = "\n".join(f"{i+1}. {r}" for i, r in enumerate(persona.rules))
    return (
        "=== ANLATIM PERSONASI (TON) ===\n"
        "Bu videoyu aşağıdaki KOMİK personada yaz. Yapı (hook→tırmanış→tepe→callback) "
        "AYNI kalır; DEĞİŞEN şey TON.\n\n"
        f"TARZIN TAM ÖRNEĞİ:\n---\n{persona.few_shot}\n---\n\n"
        f"KURALLAR (hepsini uygula):\n{kurallar}\n")
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_persona.py -q`
Expected: PASS (5 test)

- [ ] **Step 5: Commit**

```bash
git add -f src/short_bot/persona.py tests/test_persona.py
git commit -F /tmp/cm.txt   # "feat(reel): persona yukleme + prompt blogu"
```

---

### Task 4: `reel_narration` persona enjeksiyonu

**Files:**
- Modify: `src/short_bot/reel_narration.py` (`write_reel_narration`, prompt kurulumu)
- Test: `tests/test_reel_narration_persona.py` (CREATE)

- [ ] **Step 1: Failing test** — prompt'a persona bloğunun girip girmediğini, `_budgeted`'a giden prompt'u yakalayarak ölç.

```python
# tests/test_reel_narration_persona.py
from short_bot.config import ChannelConfig, ReelConfig
from short_bot.reel_models import ReelNarration, ReelBeat


def _kanal(persona=""):
    return ChannelConfig(slug="m", name="M", language="tr",
                         reel=ReelConfig(enabled=True, persona=persona,
                                         target_duration_s=(25, 45)))


def _sahte_narration():
    return ReelNarration(
        hook="Bir soru cümlesi burada duruyor.",
        beats=[ReelBeat(text="Birinci beat cümlesi.", visual_query="crow", keyword="A"),
               ReelBeat(text="İkinci beat cümlesi.", visual_query="bird", keyword="B"),
               ReelBeat(text="Üçüncü beat cümlesi.", visual_query="nest", keyword="C")],
        close="Ve işte bir soru cümlesi burada.", mood="neutral")


def test_persona_promptu_enjekte_edilir(monkeypatch):
    import short_bot.reel_narration as RN
    yakalanan = {}
    def sahte_run_json(prompt, schema, **kw):
        yakalanan["prompt"] = prompt
        return _sahte_narration()
    monkeypatch.setattr(RN, "run_json", sahte_run_json)
    monkeypatch.setattr(RN, "check_narration", lambda *a, **k: [])
    monkeypatch.setattr(RN, "check_humor", lambda *a, **k: [], raising=False)
    RN.write_reel_narration("karga", channel=_kanal("vahsi_mizah"))
    assert "ANLATIM PERSONASI" in yakalanan["prompt"]
    assert "Porsuk Dumrul" in yakalanan["prompt"]


def test_personasiz_prompt_degismez(monkeypatch):
    import short_bot.reel_narration as RN
    yakalanan = {}
    def sahte_run_json(prompt, schema, **kw):
        yakalanan["prompt"] = prompt
        return _sahte_narration()
    monkeypatch.setattr(RN, "run_json", sahte_run_json)
    monkeypatch.setattr(RN, "check_narration", lambda *a, **k: [])
    RN.write_reel_narration("karga", channel=_kanal(""))
    assert "ANLATIM PERSONASI" not in yakalanan["prompt"]   # sıfır regresyon
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_reel_narration_persona.py::test_persona_promptu_enjekte_edilir -q`
Expected: FAIL (persona bloğu prompt'a girmiyor)

- [ ] **Step 3: Implement**

`reel_narration.py` başına import:
```python
from short_bot.persona import load_persona, persona_block
```

`write_reel_narration` içinde, `prompt = build_reel_prompt(...)` satırından SONRA, `hook_angle`/`series_directive` eklerinin yanına:
```python
    persona = load_persona(getattr(reel, "persona", ""), language=channel.language)
    if persona:
        prompt = prompt + "\n\n" + persona_block(persona)
```
(`reel = getattr(channel, "reel", None)` zaten fonksiyonun başında var.)

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_reel_narration_persona.py -q`
Expected: PASS (2 test)

- [ ] **Step 5: Regresyon**

Run: `python -m pytest tests/ -q -k "reel_narration"`
Expected: mevcut anlatım testleri PASS

- [ ] **Step 6: Commit**

```bash
git add -f src/short_bot/reel_narration.py tests/test_reel_narration_persona.py
git commit -F /tmp/cm.txt   # "feat(reel): persona prompt enjeksiyonu (personasiz = degismez)"
```

---

### Task 5: `reel_humor_check.py` — mizah kapısı

**Files:**
- Create: `src/short_bot/reel_humor_check.py`
- Test: `tests/test_reel_humor_check.py` (CREATE)

Referans deseni: `src/short_bot/reel_factcheck.py` (`check_narration`, `Issue`, `run_json`, `invoke` enjeksiyonu, çökerse boş liste).

- [ ] **Step 1: Failing test**

```python
# tests/test_reel_humor_check.py
def test_temiz_senaryo_bos_liste():
    from short_bot.reel_humor_check import check_humor
    # invoke enjeksiyonu: gerçek LLM YOK
    def sahte(prompt, schema):
        return schema(issues=[])
    assert check_humor("karga", text="komik metin", language="tr", invoke=sahte) == []


def test_uydurma_referans_yakalanir():
    from short_bot.reel_humor_check import check_humor, HumorIssue
    def sahte(prompt, schema):
        return schema(issues=[HumorIssue(problem="'Gökkuşağı Sokağı' diye dizi yok",
                                         kind="reference")])
    r = check_humor("karga", text="...", language="tr", invoke=sahte)
    assert len(r) == 1 and r[0].kind == "reference"


def test_cokerse_bos_liste_uretim_durmaz():
    from short_bot.reel_humor_check import check_humor
    def patlayan(prompt, schema):
        raise RuntimeError("LLM patladı")
    assert check_humor("karga", text="...", language="tr", invoke=patlayan) == []


def test_bos_metin_bos_liste():
    from short_bot.reel_humor_check import check_humor
    assert check_humor("karga", text="  ", language="tr",
                       invoke=lambda p, s: 1/0) == []


def test_humor_feedback_metni():
    from short_bot.reel_humor_check import humor_feedback, HumorIssue
    fb = humor_feedback([HumorIssue(problem="zorlama şaka", kind="humor")])
    assert "zorlama şaka" in fb
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_reel_humor_check.py -q`
Expected: FAIL (modül yok)

- [ ] **Step 3: Implement**

```python
# src/short_bot/reel_humor_check.py
"""Mizah doğrulama kapısı — reel_factcheck.check_narration'ın kardeşi.

Persona'lı (mizah) senaryoyu ikinci bir LLM çağrısıyla denetler: KOMİK mi (zorlama
değil), referanslar GERÇEK mi, biyoloji DOĞRU mu. Boş liste = temiz. Denetim çökerse
BOŞ LİSTE (üretim durmaz) + log — tek LLM arızası üretimi öldürmesin.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

from short_bot.llm_sonnet import run_json

log = logging.getLogger(__name__)

_LANG_NAMES = {"tr": "Türkçe", "de": "Almanca", "en": "İngilizce"}


class HumorIssue(BaseModel):
    problem: str
    kind: str = "humor"        # "humor" | "reference" | "biology"


class _Issues(BaseModel):
    issues: list[HumorIssue] = []


def _prompt(topic: str, text: str, lang: str) -> str:
    return f"""Aşağıdaki {lang} mizah senaryosunu DENETLE. Konu: {topic}

SENARYO:
{text}

Şu üç ölçütü kontrol et ve YALNIZ GERÇEK sorunları bildir:
1. KOMİK mi? Zorlama, jenerik ya da düz mü? (Gerçekten esprili değilse "humor" sorunu.)
2. REFERANSLAR GERÇEK mi? Uydurma/var olmayan dizi/karakter/olay varsa "reference" sorunu.
   (Gerçek ve tema-uyumlu referanslar SORUN DEĞİL.)
3. BİYOLOJİ DOĞRU mu? Hayvan hakkında yanlış/uydurma bilgi varsa "biology" sorunu.

Sorun yoksa boş liste döndür. SADECE şu JSON: {{"issues": [{{"problem": "...", "kind": "humor|reference|biology"}}]}}"""


def check_humor(topic: str, *, text: str, language: str, claude_path: str = "claude",
                model: str = "default", backend: str = "claude_cli",
                api_key: str | None = None, invoke=None) -> list[HumorIssue]:
    if not (text or "").strip():
        return []
    lang = _LANG_NAMES.get(language, "Türkçe")
    p = _prompt(topic, text, lang)
    try:
        if invoke is not None:
            v = invoke(p, _Issues)
        else:
            v = run_json(p, _Issues, claude_path=claude_path, model=model,
                         backend=backend, api_key=api_key, retries=1, timeout_s=120)
    except Exception as e:   # noqa: BLE001 — denetim çökse de üretim durmamalı
        log.warning(f"  mizah denetimi çalışmadı ({e}) → atlanıyor")
        return []
    return [i for i in v.issues if (i.problem or "").strip()]


def humor_feedback(issues: list[HumorIssue]) -> str:
    satirlar = "\n".join(f"  - [{i.kind}] {i.problem}" for i in issues)
    return ("\n\nÖNCEKİ DENEME ŞU MİZAH SORUNLARINI TAŞIYORDU — düzelt:\n"
            f"{satirlar}\n"
            "Referanslar GERÇEK olmalı, biyoloji DOĞRU olmalı, mizah zorlama değil "
            "GERÇEKTEN komik olmalı.\n")
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_reel_humor_check.py -q`
Expected: PASS (5 test)

- [ ] **Step 5: Commit**

```bash
git add -f src/short_bot/reel_humor_check.py tests/test_reel_humor_check.py
git commit -F /tmp/cm.txt   # "feat(reel): mizah dogrulama kapisi (reel_humor_check)"
```

---

### Task 6: Mizah kapısı wiring (`reel_narration`)

**Files:**
- Modify: `src/short_bot/reel_narration.py` (olgu kapısından sonra mizah kapısı)
- Test: `tests/test_reel_narration_persona.py` (Task 4'e ekle)

- [ ] **Step 1: Failing test** (aynı dosyaya ekle)

```python
def test_mizah_kapisi_zayif_senaryoyu_reddeder(monkeypatch):
    import short_bot.reel_narration as RN
    monkeypatch.setattr(RN, "run_json", lambda p, s, **k: _sahte_narration())
    monkeypatch.setattr(RN, "check_narration", lambda *a, **k: [])
    from short_bot.reel_humor_check import HumorIssue
    # her iki denemede de mizah sorunu → ValueError
    monkeypatch.setattr(RN, "check_humor",
                        lambda *a, **k: [HumorIssue(problem="zorlama", kind="humor")],
                        raising=False)
    import pytest
    with pytest.raises(ValueError, match="mizah denetiminden geçemedi"):
        RN.write_reel_narration("karga", channel=_kanal("vahsi_mizah"))


def test_mizah_kapisi_personasiz_calismaz(monkeypatch):
    import short_bot.reel_narration as RN
    monkeypatch.setattr(RN, "run_json", lambda p, s, **k: _sahte_narration())
    monkeypatch.setattr(RN, "check_narration", lambda *a, **k: [])
    cagrildi = {"n": 0}
    def sayan(*a, **k):
        cagrildi["n"] += 1
        return []
    monkeypatch.setattr(RN, "check_humor", sayan, raising=False)
    RN.write_reel_narration("karga", channel=_kanal(""))   # persona yok
    assert cagrildi["n"] == 0        # mizah kapısı personasız çağrılmamalı
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_reel_narration_persona.py -k mizah -q`
Expected: FAIL (mizah kapısı henüz yok / persona None iken çağrılıyor)

- [ ] **Step 3: Implement**

`reel_narration.py` başına import:
```python
from short_bot.reel_humor_check import check_humor, humor_feedback
```

Olgu kapısı bloğunun BİTİMİNDEN sonra (manşet yeniden-yazımından sonra), `return n`'den önce ekle:
```python
    # MİZAH KAPISI — yalnız persona'lı (mizah) üretimlerde. Olgu kapısı gibi:
    # üretilen senaryo GERÇEKTEN komik mi, referanslar GERÇEK mi, biyoloji DOĞRU mu.
    # Bu oturumun kanıtlanmış dersi: güçlü prompt yetmez, kapı şart.
    if persona and persona.humor_check:
        mizah = check_humor(topic, text=n.full_text(), language=channel.language,
                            claude_path=claude_path, model=model, backend=backend,
                            api_key=api_key)
        if mizah:
            log.warning(f"  senaryo mizah denetiminden kaldı "
                        f"({'; '.join(i.problem for i in mizah)}) → yeniden yazılıyor")
            n = _budgeted(prompt + humor_feedback(mizah))
            hala = check_humor(topic, text=n.full_text(), language=channel.language,
                               claude_path=claude_path, model=model, backend=backend,
                               api_key=api_key)
            if hala:
                raise ValueError(
                    "senaryo mizah denetiminden geçemedi (2 deneme): "
                    + "; ".join(f"[{i.kind}] {i.problem}" for i in hala))
```
(`persona` değişkeni Task 4'te aynı fonksiyonda tanımlandı, kapsamda.)

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_reel_narration_persona.py -q`
Expected: PASS (4 test)

- [ ] **Step 5: Regresyon + conftest guard**

`tests/conftest.py`'deki `_olgu_denetimi_kapali` fixture'ına mizah kapısını da ekle (birim testler LLM çağırmasın):
```python
    monkeypatch.setattr(RN, "check_humor", lambda *a, **kw: [], raising=False)
```
Run: `python -m pytest tests/ -q -k "reel_narration or reel_factcheck"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -f src/short_bot/reel_narration.py tests/test_reel_narration_persona.py tests/conftest.py
git commit -F /tmp/cm.txt   # "feat(reel): mizah kapisi wiring (persona varsa)"
```

---

### Task 7: `vahsi-mizah` görsel arketip girişi

**Files:**
- Modify: `config/archetypes.json`
- Test: `tests/test_archetype_vahsi_mizah.py` (CREATE)

Önce KEŞİF: `python -c "import json; d=json.load(open('config/archetypes.json')); print(d[0].keys())"` ile şemayı doğrula. `.j2` ZORUNLU değil (reel formatı `reel_overlay.html.j2` kullanır); yalnızca defaults + pexels_queries.

- [ ] **Step 1: Failing test**

```python
# tests/test_archetype_vahsi_mizah.py
import json


def test_vahsi_mizah_arketibi_var():
    d = json.load(open("config/archetypes.json", encoding="utf-8"))
    slugs = [a["slug"] for a in d]
    assert "vahsi-mizah" in slugs


def test_vahsi_mizah_defaults_gecerli():
    d = json.load(open("config/archetypes.json", encoding="utf-8"))
    a = next(x for x in d if x["slug"] == "vahsi-mizah")
    assert a["defaults"]["colors"]["primary"].startswith("#")
    assert len(a["pexels_queries"]) >= 2
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_archetype_vahsi_mizah.py -q`
Expected: FAIL (arketip yok)

- [ ] **Step 3: Implement** — `config/archetypes.json` listesine yeni obje ekle:

```json
  {
    "slug": "vahsi-mizah",
    "label": "Vahşi Mizah",
    "subtitle": "Belgesel-üstü komik anlatım · sıcak palet",
    "defaults": {
      "colors": {
        "primary": "#e8551d",
        "accent": "#ffd400",
        "primary_light": "#ff7a45",
        "bg_gradient": ["#1a1410", "#2b1d12"]
      },
      "body_bg": ["#faf3e6", "#f0e6d2"],
      "text_main": "#1a1410",
      "text_muted": "#6b5a48",
      "font_headline": "Anton",
      "font_body": "Inter"
    },
    "pexels_queries": ["wildlife closeup", "wild animal nature", "documentary animal"]
  }
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_archetype_vahsi_mizah.py -q`
Expected: PASS

- [ ] **Step 5: DNA yükleme regresyonu** — arketip DNA registry'sine temiz giriyor mu:

Run: `python -m pytest tests/ -q -k "dna or archetype"`
Expected: PASS (yeni arketip mevcut DNA yüklemesini bozmaz)

- [ ] **Step 6: Commit**

```bash
git add -f config/archetypes.json tests/test_archetype_vahsi_mizah.py
git commit -F /tmp/cm.txt   # "feat(dna): vahsi-mizah gorsel arketip girisi"
```

---

### Task 8: Kanal kurma ajanı — mizah niyeti → persona

**Files:**
- Modify: `src/short_bot/channel_agent.py` (`build_plan` / `apply_plan` persona işareti)
- Test: `tests/test_channel_agent_persona.py` (CREATE)

Önce KEŞİF: `grep -n "def build_plan\|def apply_plan\|reel=\|ReelConfig\|persona\|_normalize_niche" src/short_bot/channel_agent.py`. Persona işareti `apply_plan`'ın `ReelConfig(...)` kurulumuna eklenir; mizah niyeti basit anahtar-kelime tespiti (LLM'e ek çağrı YOK — YAGNI).

- [ ] **Step 1: Failing test**

```python
# tests/test_channel_agent_persona.py
def test_mizah_niyeti_personaya_cevrilir():
    from short_bot.channel_agent import detect_persona
    assert detect_persona("komik bir karga kanalı") == "vahsi_mizah"
    assert detect_persona("mizahi hayvan belgeseli") == "vahsi_mizah"
    assert detect_persona("bilim tarihi kanalı") == ""      # mizah değil
    assert detect_persona("almanca bahçe kanalı") == ""
```

- [ ] **Step 2: Run, verify fail**

Run: `python -m pytest tests/test_channel_agent_persona.py -q`
Expected: FAIL (`detect_persona` yok)

- [ ] **Step 3: Implement** — `channel_agent.py`'ye ekle:

```python
# Mizah niyeti tespiti — kanal kurma ajanı bir mizah personası seçebilsin.
# Anahtar-kelime tabanlı (LLM'e ek çağrı YOK): niyet metninde bunlar geçerse mizah.
_MIZAH_ISARETLERI = ("komik", "mizah", "espri", "eğlenceli", "eglenceli",
                     "güldür", "guldur", "dalga", "capraz", "çılgın")


def detect_persona(intent: str) -> str:
    dusuk = (intent or "").casefold()
    return "vahsi_mizah" if any(k in dusuk for k in _MIZAH_ISARETLERI) else ""
```

`apply_plan` içinde `ReelConfig(...)` kurulumuna `persona=` bağla. Persona planda taşınmalı; `ChannelPlan`'a alan ekle:
```python
    persona: str = ""
```
`build_plan`'da nişe/niyete göre işaretle:
```python
    plan_persona = detect_persona(intent) or detect_persona(niche)
```
ve `ChannelPlan(...)` kurulumunda `persona=plan_persona`, `apply_plan`'da `ReelConfig(..., persona=plan.persona)`.

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_channel_agent_persona.py -q`
Expected: PASS

- [ ] **Step 5: Regresyon**

Run: `python -m pytest tests/ -q -k "channel_agent"`
Expected: PASS (mevcut ajan testleri; persona varsayılan boş)

- [ ] **Step 6: Commit**

```bash
git add -f src/short_bot/channel_agent.py tests/test_channel_agent_persona.py
git commit -F /tmp/cm.txt   # "feat(agent): mizah niyeti -> vahsi_mizah persona"
```

---

### Task 9: Uçtan uca gerçek doğrulama (manuel, işaretli)

**Files:** yok (doğrulama görevi)

Bu görev OTOMATİK TEST DEĞİL — bu oturumun disiplini: gerçek üretim + kare kare inceleme. Otonom akışta ben (asistan) çalıştırırım.

- [ ] **Step 1: Tam süit yeşil**

Run: `python -m pytest tests/ -q -p no:randomly`
Expected: tüm testler PASS (yeni testler dahil, regresyon yok)

- [ ] **Step 2: Mizah kanalı kur** — geçici bir Türkçe hayvan kanalı (persona="vahsi_mizah") config'i yaz, konu bankasına bir hayvan konusu koy.

- [ ] **Step 3: Taze süreçte üret** (panel eski kodu tutar):

Run: `python -m short_bot run --channel <mizah-kanal> --max 1`
Expected: `status=success`, senaryo logunda mizah tonu görünür.

- [ ] **Step 4: Kare kare + senaryo incele** — anlatım komik mi, referanslar gerçek mi, biyoloji doğru mu, altyazı/kapanış/kuyruk önceki düzeltmelerle uyumlu mu (font/satır, donmuş kuyruk yok). Mizah kapısının loglarını doğrula.

- [ ] **Step 5: Bulguları raporla** — kullanıcıya senaryo + kare bulguları. Sorun varsa yeni görev.

---

## Self-Review

**Spec coverage:**
- Persona işareti (spec §1) → Task 1 ✓
- persona.py (spec §2) → Task 3 ✓
- Persona enjeksiyonu (spec §3) → Task 4 ✓
- Dil paketi mizah bloğu (spec §4) → Task 2 ✓
- Mizah kapısı (spec §5) → Task 5 ✓
- Kapı wiring (spec §6) → Task 6 ✓
- Görsel arketip (spec §7) → Task 7 ✓
- Kanal ajanı entegrasyonu (spec §8) → Task 8 ✓
- Test listesi (spec Test) → her task'ta + Task 9 uçtan uca ✓

**Tip tutarlılığı:** `load_persona(slug, *, language)` → `Persona(slug, few_shot, rules, humor_check)`; `persona_block(persona)` → str; `check_humor(topic, *, text, language, ..., invoke)` → `list[HumorIssue]`; `HumorIssue(problem, kind)`; `humor_feedback(list[HumorIssue])` → str; `detect_persona(intent)` → str. Task 4/6'da `persona` aynı fonksiyon kapsamında. `full_text()` gerçek metod (doğrulandı).

**Placeholder:** yok — her kod adımı tam.
