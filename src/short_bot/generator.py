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
    assert channel.generator is not None, "generator config required"

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
        max_count = max(topic_distribution.values()) if topic_distribution else 0
        lines = []
        for tag, count in sorted_dist:
            if count == 0:
                marker = " ← HİÇ KULLANILMAMIŞ" if channel.language == "tr" else " ← UNUSED"
            elif count <= max_count // 3:
                marker = " ← AZ" if channel.language == "tr" else " ← LOW"
            else:
                marker = ""
            lines.append(f"- {tag}: {count}{marker}")
        rotation_block = f"\n{ph['topic_rotation']}:\n" + "\n".join(lines) + "\n"

    forbidden_tone = ", ".join(dna.tone.forbidden) if dna.tone.forbidden else "—"

    return f"""Sen "{channel.name}" kanalı için kısa, vurucu içerik üreten bir yazarsın.

{ph['channel_id']}:
- {ph['topic']}: {channel.generator.topic}
- {ph['language']}: {ph['language']}
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
