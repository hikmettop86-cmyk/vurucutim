"""Content generator: Sonnet-driven short content with 3-layer dedup."""
from __future__ import annotations

from pydantic import BaseModel, Field

from short_bot.models import Script


class GeneratorRetryExhausted(RuntimeError):
    """Raised when all dedup retries return duplicates — topic likely exhausted."""


class GeneratorResult(BaseModel):
    text: str = Field(min_length=10, max_length=200)
    topic_tag: str = Field(
        min_length=2,
        max_length=20,
        pattern=r"^[a-zçğıöşü]+$",   # Turkish lowercase, single word
    )
    script: Script
    image_keywords: list[str] = Field(min_length=2, max_length=8)


from short_bot.config import ChannelConfig
from short_bot.dna import DnaSpec
from short_bot.prompt_phrases import get_phrases


def build_generator_prompt(
    *,
    channel: ChannelConfig,
    dna: DnaSpec,
    forbidden_texts: list[str],
    topic_distribution: dict[str, int],
) -> str:
    ph = get_phrases(channel.language)
    if channel.generator is None:
        raise ValueError("build_generator_prompt requires channel.generator")

    if forbidden_texts:
        lines = "\n".join(f"{i+1}. {t!r}" for i, t in enumerate(forbidden_texts))
        forbidden_block = (
            f"\n{ph['forbidden_intro']}\n"
            f"─── {len(forbidden_texts)} items ───\n"
            f"{lines}\n"
            f"{ph['forbidden_end']}\n"
        )
    else:
        forbidden_block = f"\n{ph['forbidden_intro']} (none yet)\n"

    rotation_block = ""
    if topic_distribution:
        # Order ascending — least-used first, marked
        sorted_dist = sorted(topic_distribution.items(), key=lambda kv: kv[1])
        max_count = max(topic_distribution.values())
        lines = []
        for tag, count in sorted_dist:
            if count == 0:
                marker = ph["marker_unused"]
            elif count <= max_count // 3:
                marker = ph["marker_low"]
            else:
                marker = ""
            lines.append(f"- {tag}: {count}{marker}")
        rotation_block = f"\n{ph['topic_rotation']}:\n" + "\n".join(lines) + "\n"

    forbidden_tone = ", ".join(dna.tone.forbidden) if dna.tone.forbidden else "—"

    return f"""Sen "{channel.name}" kanalı için kısa, vurucu içerik üreten bir yazarsın.

{ph['channel_id']}:
- {ph['topic']}: {channel.generator.topic}
- {ph['language_label']}: {ph['language_name']}
- Persona: {dna.persona_summary}
- Voice: {dna.tone.voice}
- Style: {dna.tone.style}
- Forbidden tone: {forbidden_tone}
- Sentence max words: {dna.tone.sentence_max_words}
- Body max chars: {dna.tone.body_max_chars}

{ph['task']}: 1 yeni içerik üret (1 short = 1 üretim).
{forbidden_block}{rotation_block}
topic_tag: tek kelime, lowercase, Türkçe (sabir/umut/ayrilik gibi). Az kullanılmış / hiç kullanılmamış temalardan birini seç.

{ph['output_intro']}:
{{
  "text": "<max 200 karakter, ekranda kalacak ana söz>",
  "topic_tag": "<lowercase tek kelime>",
  "script": {{
    "header_top": "<3-5 kelime, BÜYÜK HARF>",
    "header_bottom": "<3-5 kelime, BÜYÜK HARF>",
    "photo_overlay": "<1-3 kelime, görsel üst yazı>",
    "body_paragraph": "<text'i içersin, en fazla {dna.tone.body_max_chars} karakter>",
    "highlights": [{{"text": "<body_paragraph içinde BİREBİR geçen 1-3 kelime>", "color": "yellow"}}],
    "category": "<tek kelime kategori>",
    "mood": "<breaking|neutral|upbeat>"
  }},
  "image_keywords": ["<3-5 İngilizce arama kelimesi, virgülsüz>"]
}}

{ph['critical']}:
- text: max 200 karakter
- script.body_paragraph: text'i içermek zorunda; en fazla {dna.tone.body_max_chars} karakter
- script.highlights[*].text: body_paragraph içinde BİREBİR geçmek zorunda (case + punctuation dahil)
- script.mood: tam olarak breaking, neutral veya upbeat (üç seçenekten biri)
- image_keywords: İngilizce, görsel arama için ("couple silhouette sunset")
"""


from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy.engine import Engine

from short_bot.generated_db import (
    exists_hash, recent_by_tag, text_hash,
)


_TAG_OVERLAP_THRESHOLD = 0.65   # same-tag medium-fuzzy match → duplicate


@dataclass
class DupVerdict:
    is_duplicate: bool
    reason: str = ""


def check_duplicate(
    eng: Engine,
    channel_slug: str,
    result: "GeneratorResult",
    forbidden: list[str],
    fuzzy_threshold: float,
) -> DupVerdict:
    """Three-layer duplicate detection.

    Layer 1: exact hash in DB (fast).
    Layer 2: fuzzy ratio >= fuzzy_threshold against forbidden list (in-memory).
    Layer 3: same topic_tag + fuzzy ratio >= 0.70 (DB query).
    """
    # Layer 1: exact hash
    if exists_hash(eng, channel_slug, text_hash(result.text)):
        return DupVerdict(True, "exact_hash")

    # Layer 2: fuzzy text vs forbidden list
    new_low = result.text.lower()
    for prev in forbidden:
        ratio = fuzz.ratio(new_low, prev.lower()) / 100
        if ratio >= fuzzy_threshold:
            return DupVerdict(True, f"fuzzy_text({ratio:.2f})")

    # Layer 3: same-tag medium fuzzy
    same_tag = recent_by_tag(eng, channel_slug, tag=result.topic_tag,
                              days=7, limit=20)
    for prev in same_tag:
        ratio = fuzz.ratio(new_low, prev.lower()) / 100
        if ratio >= _TAG_OVERLAP_THRESHOLD:
            return DupVerdict(
                True, f"tag_overlap({result.topic_tag},{ratio:.2f})"
            )

    return DupVerdict(False)


from short_bot.claude_cli import run_json


def generate_quote(
    *,
    channel: ChannelConfig,
    dna: DnaSpec,
    forbidden_texts: list[str],
    topic_distribution: dict[str, int],
    claude_path: str = "claude",
    model: str = "sonnet",
) -> GeneratorResult:
    prompt = build_generator_prompt(
        channel=channel, dna=dna,
        forbidden_texts=forbidden_texts,
        topic_distribution=topic_distribution,
    )
    return run_json(
        prompt, GeneratorResult,
        claude_path=claude_path, model=model,
        retries=2, timeout_s=180,
    )
