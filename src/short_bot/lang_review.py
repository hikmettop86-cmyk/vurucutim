"""Anlatım dil denetimi (TÜM diller): yerli okur yargısı + geri çeviri.

NEDEN VAR: mevcut kapıların hiçbiri metnin DİL olarak sağlam olup olmadığını sormaz —
sadakat kapısı anlatımı GÖRÜNTÜYLE karşılaştırır, netlik kapısı MANTIĞA bakar. Bozuk ama
tutarlı bir cümle ikisini de geçer.

Kapı önce yalnız Türkçe DIŞI kanallarda çalışıyordu; gerekçe "operatör hedef dili bilmiyor,
Türkçeyi zaten kendi okur" idi. Bu varsayım koşu 1434'te çürüdü: oto-üretimde Türkçe metni
de kimse okumuyor ve anlatım "Kimsenin bırakmadığı o minik el gerek yok, sen de birine sıkı
sarıl." diye BOZUK bir cümleyle yayına gitti. Dil doğruluğu dilden bağımsızdır → kapı artık
her dilde çalışır. (Geri çeviri hâlâ yalnız tr DIŞI: Türkçede çevrilecek bir şey yok.)

İki ayrı iş var ve biri diğerinin yerini TUTMAZ:

  • ``judge_native_text`` — metni hedef dilde yargılar (doğallık, kayıt tutarlılığı,
    çeviri kokusu, yanlış kelime seçimi). Bu bir KAPIDIR: geçmezse yeniden yazdırılır.

  • ``back_translate`` — anlatımın ANLAMINI operatöre Türkçe gösterir (panelde yan yana).
    Bu bir kapı DEĞİL, bir pencere: fail-open, patlarsa üretim sürer. Ve tek başına
    yetmez — bozuk bir Japonca cümle Türkçeye gayet düzgün geri çevrilir.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from short_bot.claude_cli import run_json

log = logging.getLogger(__name__)

# LLM'e verilen İngilizce dil adları (prompt İngilizce yazıldığı için). Bilinmeyen dil
# SESSİZCE Türkçeye düşmez — düşerse yargı anlamsızlaşır ve bunu hiçbir hata bildirmez.
_LANG_EN = {
    "tr": "Turkish",
    "en": "English",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
    "ja": "Japanese",
}


def _language_en(code: str) -> str:
    try:
        return _LANG_EN[code]
    except KeyError:
        raise ValueError(
            f"dil denetimi için bilinmeyen dil: {code!r}. lang_review._LANG_EN'e ekleyin — "
            f"sessizce başka bir dile düşmek yargıyı anlamsız kılar.") from None


class NativeVerdict(BaseModel):
    """Yerli okur yargısı.

    ``natural`` ZORUNLU (default YOK): zayıf model ``{}`` ya da kısmi JSON dönerse
    pydantic HATA atmalı ki çağıran fail-open'a düşsün. Default verirsek doğrulama
    sessizce geçer ve bozuk metin 'doğal' sayılır (aynı hata 2026-07-19 denetiminde
    güvenlik şemalarında yakalanmıştı)."""

    natural: bool
    issue: str = Field(default="", max_length=400)


class _BackTranslation(BaseModel):
    turkish: str = Field(default="", max_length=2000)


_JUDGE_PROMPT = """You are a NATIVE {lang} speaker reviewing the voice-over script of a
short vertical video (YouTube Shorts). The script will be read aloud by a TTS voice and
shown as on-screen subtitles.

Judge ONLY the language itself. Do NOT judge the story, the topic, or whether it is
interesting — another reviewer already did that.

Mark it NOT natural if ANY of these is true:
  1) It reads like a TRANSLATION: word order, idioms or sentence rhythm that a native
     writer would not produce.
  2) INCONSISTENT REGISTER: the politeness/formality level jumps around (in {lang},
     mixing speech levels inside one short script sounds broken).
  3) WRONG WORD CHOICE: a word that is technically related but wrong in this context,
     or an unnatural collocation.
  4) It is grammatically wrong, or a particle/inflection is misused.
  5) It sounds like WRITTEN/LITERARY language where spoken narration is expected.

Mark it natural if a native viewer would hear it and notice nothing odd. Small stylistic
preferences are NOT problems — be strict about real errors, tolerant about taste.

DELIBERATE SPOKEN STYLE IS NOT AN ERROR. This is a narrator's voice, not an essay. The
following are INTENTIONAL and must be judged natural:
  - inverted / non-canonical word order used for emphasis (very common in spoken {lang}),
  - elliptical or verbless short sentences,
  - colloquial, street or neighbourhood register, slang and familiar address,
  - direct address to the viewer, rhetorical questions, sentence-final emphasis.
Judge the sentence as SPOKEN {lang}: would a native SAY it this way? Only flag it when
meaning actually breaks down — the listener cannot parse it, a word is used wrongly, or
an inflection/agreement is simply incorrect. Sounding informal is not breaking down.

THE TEST THAT DECIDES IT. Take each sentence and try to restate it in your own words in
ONE sentence. If you cannot — because the words do not combine into a coherent claim —
it is BROKEN, however poetic or emotional it sounds. Narration is heard once, at speed,
with no rewinding: a line that needs a second pass has already failed.

REAL BROKEN LINE THAT SHIPPED because no reviewer flagged it (this is the failure you
exist to prevent):
  "Kimsenin bırakmadığı o minik el gerek yok, sen de birine sıkı sarıl."
  "gerek yok" attaches to nothing, and the relative clause qualifies a hand that was
  never established as an entity. A native listener stalls mid-sentence. natural=false.

Equally important, do NOT flag a line just because:
  - a reference could in principle be phrased more explicitly, but context resolves it,
  - you personally would have worded it differently,
  - a word repeats, or the imagery is sentimental.
Ambiguity a listener resolves instantly is NOT a defect. Flag collapse of meaning, not
imperfection. When the sentence parses and you can restate it, answer natural=true.

Return JSON:
{{"natural": true or false, "issue": "if not natural: name the WORST single problem and
quote the exact offending phrase. Write this in TURKISH so the operator can read it. Max
2 sentences. If natural: empty string."}}

SCRIPT ({lang}):
{text}
"""


_BACK_PROMPT = """Translate the following {lang} voice-over script into TURKISH.

This translation is shown to an operator who does NOT speak {lang}, so they can check
WHAT the video says. Therefore:
  - Translate the MEANING faithfully, sentence by sentence, in the same order.
  - Do NOT improve, shorten or embellish it. If the original is clumsy, the Turkish
    should read clumsy too — the operator must see what is really there.
  - Keep it plain prose. No notes, no commentary.

Return JSON: {{"turkish": "the full Turkish translation"}}

SCRIPT ({lang}):
{text}
"""


def judge_native_text(text: str, *, language: str, backend: str = "claude_cli",
                      model: str = "default", api_key: str | None = None,
                      claude_path: str = "claude") -> NativeVerdict | None:
    """Metin hedef dilde DOĞAL mı? ``NativeVerdict`` ya da None (hata → fail-open).

    Geçici hataya karşı iki kez denenir (netlik kapısıyla aynı sözleşme)."""
    lang = _language_en(language)
    if not (text or "").strip():
        return None
    prompt = _JUDGE_PROMPT.format(lang=lang, text=text[:1200])
    last: Exception | None = None
    for _ in range(2):
        try:
            return run_json(prompt, NativeVerdict, claude_path=claude_path, model=model,
                            backend=backend, api_key=api_key, retries=2, timeout_s=60)
        except Exception as e:  # noqa: BLE001 — geçici → tekrar dene
            last = e
    log.info(f"  kürate[dil]: yerli okur yargısı alınamadı ({last})")
    return None


def back_translate(text: str, *, language: str, backend: str = "claude_cli",
                   model: str = "default", api_key: str | None = None,
                   claude_path: str = "claude") -> str:
    """Anlatımı Türkçeye geri çevir (panelde gösterilir). Hata → "" (fail-open).

    Türkçe kaynakta boş döner: çevrilecek bir şey yok, çağrı israf olur."""
    if language == "tr" or not (text or "").strip():
        return ""
    lang = _language_en(language)
    prompt = _BACK_PROMPT.format(lang=lang, text=text[:1800])
    try:
        return (run_json(prompt, _BackTranslation, claude_path=claude_path, model=model,
                         backend=backend, api_key=api_key, retries=2,
                         timeout_s=90).turkish or "").strip()
    except Exception as e:  # noqa: BLE001 — pencere, kapı değil: üretimi durdurmaz
        log.info(f"  kürate[dil]: geri çeviri alınamadı ({e})")
        return ""
