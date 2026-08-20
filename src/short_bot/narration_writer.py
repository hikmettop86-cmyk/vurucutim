"""LLM anlatım yazıcı: haber → Narration (hook + beat'ler + loop kapanışı)."""
from __future__ import annotations

from short_bot.claude_cli import run_json
import logging

from short_bot.fact_gate import unverified_claims
from short_bot.locale import LANGUAGE_NAMES
from short_bot.narration import Narration

log = logging.getLogger(__name__)

# Ölçülmüş anlatım hızı: ai33/ElevenLabs Türkçe sesi, speed=1.0 → 70 kelime
# 31.4 sn (2.23 kelime/sn). 2.5 varsayımı bütçeyi şişirip videoyu 67 sn'ye
# taşıyordu; 2.2 hedef 45-60 sn bandını tutturuyor.
WORDS_PER_SECOND = 2.2

# HIZ DİLE BAĞLI — Türkçe sabiti başka dilde SESSİZCE yanlış süre üretir; hata da
# vermez, video sadece hedefin dışına düşer.
#
# ÖLÇÜLDÜ (2026-08-09, gerçek koşular):
#   es, ses 'Juanka Dominguez':  90/29.2 = 3.08 | 110/39.5 = 2.78 | 102/38.7 = 2.64
#   tr, ses 'Mustafa Energetic': 103/52.1 = 1.98
# Hız hem içerikle (~%17) hem SESLE değişiyor: yukarıdaki 2.2 sabiti başka bir
# Türkçe sesle ölçülmüştü, Mustafa belirgin daha yavaş okuyor ve 35-50sn hedefi
# 52.1sn'ye taşıyordu. reel_narration'daki kanıtlanmış kural: bütçeyi EN YAVAŞ
# ölçüme göre kur — üst sınırın hedefi AŞMAMASI, kısa kalmaktan önemlidir
# (aşınca loop zorlaşır). Bu yüzden es'te ortalama (2.8) değil 2.64 yazılı.
WORDS_PER_SECOND_BY_LANG: dict[str, float] = {"es": 2.64, "tr": 1.98}


def words_per_second(language: str | None = None) -> float:
    """Bu dilin ölçülmüş anlatım hızı; ölçülmemişse Türkçe sabiti."""
    return WORDS_PER_SECOND_BY_LANG.get(language or "", WORDS_PER_SECOND)


def word_budget(target_duration_s: tuple[int, int],
                language: str | None = None) -> tuple[int, int]:
    """Hedef süre aralığından kelime bütçesi (min, max).

    `language` verilmezse Türkçe hızı kullanılır (mevcut çağıranların davranışı
    değişmesin diye).
    """
    wps = words_per_second(language)
    lo, hi = target_duration_s
    return int(lo * wps), int(hi * wps)


def build_narration_prompt(item, body: str, channel) -> str:
    voice = channel.voice
    lo_w, hi_w = word_budget(voice.target_duration_s, channel.language)
    lo_s, hi_s = voice.target_duration_s
    lang_name = LANGUAGE_NAMES.get(channel.language, "Turkish")

    return f"""You are writing a spoken-narration script for a {lo_s}-{hi_s} second
vertical short video. The narration will be read aloud by a text-to-speech voice
and every word will appear as karaoke subtitles.

WRITE IN: {lang_name}
NARRATOR PERSONA: {voice.persona}

NEWS HEADLINE: {item.title}
SOURCE: {getattr(item, "source", None) or "unknown"}
ARTICLE BODY:
{body[:3000]}

OUTPUT a JSON object with exactly these fields:
- "hook": the FIRST spoken sentence. It must create curiosity in under 2 seconds
  — a question or a shocking claim. Never start with "Bugün" / "Today" / a date.
- "beats": 3-5 narrative beats. Each beat is an object with:
    - "text": the spoken sentence(s) for that beat (10-400 chars)
    - "on_screen": a SHORT ALL-CAPS card shown while that beat is spoken
      (max 60 chars, 2-5 words, a fact/number/action — NOT a description of a photo)
- "loop_close": the LAST spoken sentence. CRITICAL: when the video loops back to
  the start, this sentence must read as a natural set-up for the hook. Do not say
  "abone ol", "subscribe", "in this video" or any meta phrase.
- "mood": one of "breaking" | "neutral" | "upbeat"

HARD RULES:
- TOTAL spoken words across hook + all beats + loop_close: between {lo_w} and {hi_w}.
- Plain spoken language. No markdown, no emoji, no stage directions, no brackets.
- Every claim must come from the article body. Invent nothing.
- Numbers should be written as they are spoken.

Return ONLY the JSON object."""


def _budget_feedback(actual: int, lo_w: int, hi_w: int) -> str:
    if actual > hi_w:
        return (f"\n\nKISALT: previous attempt had {actual} spoken words, "
                f"the limit is {hi_w}. Rewrite shorter, keep the same structure.\n")
    return (f"\n\nUZAT: previous attempt had only {actual} spoken words, "
            f"the minimum is {lo_w}. Add detail from the article body.\n")


def _fact_feedback(eksik: list[str]) -> str:
    return (
        "\n\nFACT ERROR — these names/numbers are in your narration but NOT in the "
        f"ARTICLE BODY: {', '.join(eksik)}.\n"
        "Rewrite. Use ONLY names, clubs and numbers that literally appear in the "
        "article body above. Your verdict/opinion is still REQUIRED, but an opinion "
        "must be about what the article says — it may not introduce a new person, "
        "club or figure. Do not replace them with other outside names either.\n"
    )


def write_narration(
    item,
    body: str,
    *,
    channel,
    claude_path: str = "claude",
    model: str = "default",
    backend: str = "claude_cli",
    api_key: str | None = None,
) -> Narration:
    """Anlatım senaryosu üretir; kelime bütçesi ve OLGU kapısından geçirir.

    Olgu kapısı (fact_gate): anlatımdaki her isim/sayı haberde geçmeli. Bir kez
    düzelttirilir; ikinci kez de uydurma varsa RuntimeError — video ÜRETİLMEZ.
    Prompt'taki "Invent nothing" kuralı tek başına yetmedi (bkz. fact_gate).
    """
    voice = getattr(channel, "voice", None)
    if voice is None:
        raise ValueError("write_narration: channel.voice tanımlı değil")

    lo_w, hi_w = word_budget(voice.target_duration_s, channel.language)
    prompt = build_narration_prompt(item, body, channel)

    def _uret(p: str) -> Narration:
        return run_json(p, Narration, claude_path=claude_path, model=model,
                        backend=backend, api_key=api_key, retries=3)

    narration = _uret(prompt)
    actual = narration.word_count()
    if not (lo_w <= actual <= hi_w):
        # Tek düzeltme turu. İkincisi de bütçe dışıysa kabul edilir —
        # süre zaten sesten okunur, bütçe sadece bir hedeftir.
        narration = _uret(prompt + _budget_feedback(actual, lo_w, hi_w))

    eksik = unverified_claims(narration.full_text(), body,
                              language=channel.language)
    if not eksik:
        return narration

    log.warning(f"[olgu] haberde geçmeyen isim/sayı: {eksik} → yeniden yazdırılıyor")
    narration = _uret(prompt + _fact_feedback(eksik))
    eksik = unverified_claims(narration.full_text(), body,
                              language=channel.language)
    if eksik:
        raise RuntimeError(
            f"anlatım haberde geçmeyen isim/sayı içeriyor: {', '.join(eksik)}. "
            f"İki denemede de düzelmedi — video üretilmedi (uydurma bilgi "
            f"yayınlamaktansa video çıkmasın).")
    log.info("[olgu] düzeltme turu temiz ✓")
    return narration
