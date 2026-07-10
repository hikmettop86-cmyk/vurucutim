"""LLM reel senaryo yazıcı: konu → ReelNarration (beat başına görsel sorgu).

Seslendirme metni kanal dilinde, her beat için SOMUT İngilizce görsel sorgu
(Pexels EN'de zengin). Kelime bütçesi ~2.2 kelime/sn (ai33 Türkçe ölçümü).
"""
from __future__ import annotations

from short_bot.claude_cli import run_json
from short_bot.reel_models import ReelNarration

WORDS_PER_SECOND = 2.2   # ai33/ElevenLabs Türkçe ölçümü

# Prompt İngilizce yazıldığından dil adları da İngilizce verilir. locale.LANGUAGE_NAMES
# yerel adları döndürüyor ("tr" -> "Türkçe") ve İngilizce prompt'a uymadığından burada
# ayrı İngilizce ad tablosu tutuyoruz (LLM'e "write in Turkish" gibi net talimat).
_PROMPT_LANGUAGE_NAMES = {
    "tr": "Turkish",
    "en": "English",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
}


def reel_word_budget(target_duration_s: tuple[int, int]) -> tuple[int, int]:
    lo, hi = target_duration_s
    return int(lo * WORDS_PER_SECOND), int(hi * WORDS_PER_SECOND)


def _language_name(code: str) -> str:
    return _PROMPT_LANGUAGE_NAMES.get(code, "Turkish")


def build_reel_prompt(topic: str, channel) -> str:
    lo_w, hi_w = reel_word_budget(channel.reel.target_duration_s)
    lo_s, hi_s = channel.reel.target_duration_s
    lang = _language_name(channel.language)
    return f"""You are writing a fast-paced, footage-driven "interesting facts /
how it works" vertical short ({lo_s}-{hi_s} seconds). It will be narrated by a
text-to-speech voice with karaoke subtitles, over stock footage clips that change
every beat.

TOPIC SEED: {topic}

OUTPUT a JSON object:
- "hook": FIRST spoken sentence in {lang}. A curiosity question or surprising claim,
  under 2 seconds. Never start with a date.
- "beats": 3-6 beats. Each beat:
    - "text": the spoken sentence(s) in {lang} for this beat
    - "visual_query": a SHORT English stock-footage search query (2-4 COMMON words)
      for what to SHOW during this beat. It MUST be a subject a generic stock library
      (Pexels) actually has — e.g. "lightning storm", "storm clouds", "ocean waves",
      "factory machine", "bee flower". Concrete but findable. AVOID rare compound
      descriptions like "storm cloud interior ice crystals turbulence" — those return
      zero results. English only.
    - "keyword": a SHORT ALL-CAPS on-screen tag in {lang} (max 40 chars, 1-3 words)
- "close": LAST spoken sentence in {lang}. It must bridge back to the hook when the
  video loops. No "abone ol"/"subscribe".
- "mood": one of "upbeat" | "neutral" | "calm"

HARD RULES:
- TOTAL spoken words across hook + beats + close: between {lo_w} and {hi_w}.
- Every visual_query must be a real, findable stock-footage subject (generic,
  evergreen — machines, nature, science, industry — NOT a specific named event).
- Plain spoken language, no markdown/emoji/brackets. Add a genuinely interesting
  angle, not a dry list.
Return ONLY the JSON object."""


def _budget_feedback(actual: int, lo_w: int, hi_w: int) -> str:
    if actual > hi_w:
        return f"\n\nKISALT: {actual} kelime vardı, üst sınır {hi_w}. Kısalt.\n"
    return f"\n\nUZAT: sadece {actual} kelime vardı, alt sınır {lo_w}. Detay ekle.\n"


def write_reel_narration(topic: str, *, channel, claude_path: str = "claude",
                         model: str = "default", backend: str = "claude_cli",
                         api_key: str | None = None) -> ReelNarration:
    reel = getattr(channel, "reel", None)
    if reel is None:
        raise ValueError("write_reel_narration: channel.reel tanımlı değil")
    lo_w, hi_w = reel_word_budget(reel.target_duration_s)
    prompt = build_reel_prompt(topic, channel)
    n = run_json(prompt, ReelNarration, claude_path=claude_path, model=model,
                 backend=backend, api_key=api_key, retries=3)
    if lo_w <= n.word_count() <= hi_w:
        return n
    retry = prompt + _budget_feedback(n.word_count(), lo_w, hi_w)
    return run_json(retry, ReelNarration, claude_path=claude_path, model=model,
                    backend=backend, api_key=api_key, retries=3)
