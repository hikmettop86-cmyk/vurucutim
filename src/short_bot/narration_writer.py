"""LLM anlatım yazıcı: haber → Narration (hook + beat'ler + loop kapanışı)."""
from __future__ import annotations

from short_bot.claude_cli import run_json
from short_bot.locale import LANGUAGE_NAMES
from short_bot.narration import Narration

# Türkçe/İngilizce doğal anlatım hızı (retake payı dahil değil).
WORDS_PER_SECOND = 2.5


def word_budget(target_duration_s: tuple[int, int]) -> tuple[int, int]:
    """Hedef süre aralığından kelime bütçesi (min, max)."""
    lo, hi = target_duration_s
    return int(lo * WORDS_PER_SECOND), int(hi * WORDS_PER_SECOND)


def build_narration_prompt(item, body: str, channel) -> str:
    voice = channel.voice
    lo_w, hi_w = word_budget(voice.target_duration_s)
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
    """Anlatım senaryosu üretir; kelime bütçesi dışındaysa bir kez düzelttirir."""
    voice = getattr(channel, "voice", None)
    if voice is None:
        raise ValueError("write_narration: channel.voice tanımlı değil")

    lo_w, hi_w = word_budget(voice.target_duration_s)
    prompt = build_narration_prompt(item, body, channel)

    narration = run_json(prompt, Narration, claude_path=claude_path, model=model,
                         backend=backend, api_key=api_key, retries=3)
    actual = narration.word_count()
    if lo_w <= actual <= hi_w:
        return narration

    # Tek düzeltme turu. İkincisi de bütçe dışıysa kabul edilir —
    # süre zaten sesten okunur, bütçe sadece bir hedeftir.
    retry_prompt = prompt + _budget_feedback(actual, lo_w, hi_w)
    return run_json(retry_prompt, Narration, claude_path=claude_path, model=model,
                    backend=backend, api_key=api_key, retries=3)
