"""Content generator: Sonnet-driven short content with 3-layer dedup."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from short_bot.models import Script
from short_bot.text_normalize import strip_non_turkish_diacritics


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
    image_keywords: list[str] = Field(min_length=1, max_length=8)
    bank_id: int | None = None   # seçilen kanıtlanmış-konu kaydı (banka rotasyonu)

    @field_validator("text", mode="before")
    @classmethod
    def _normalize_text(cls, v):
        return strip_non_turkish_diacritics(v) if isinstance(v, str) else v

    @field_validator("image_keywords", mode="before")
    @classmethod
    def _coerce_keywords(cls, v):
        # LLM bazen liste yerine tek string döndürüyor
        # (ör. "frill-necked lizard running on water"). Ayırıcı varsa böl,
        # yoksa tek arama ifadesi olarak listeye sar — üretim çökmesin.
        if isinstance(v, str):
            for sep in (";", "\n", "|", "/"):
                v = v.replace(sep, ",")
            parts = [p.strip() for p in v.split(",") if p.strip()]
            return parts or [v.strip()]
        return v


from short_bot.config import ChannelConfig
from short_bot.dna import DnaSpec
from short_bot.prompt_phrases import get_phrases


def build_generator_prompt(
    *,
    channel: ChannelConfig,
    dna: DnaSpec,
    forbidden_texts: list[str],
    topic_distribution: dict[str, int],
    proven_topics: list[dict] | None = None,
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

    def _fmt_n(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
        if n >= 1_000:
            return f"{n // 1_000}K"
        return str(n)

    proven_block = ""
    if proven_topics:
        lines = "\n".join(
            f"- [id={t['id']}] {t['topic']}  "
            f"(kanıt: {_fmt_n(int(t.get('views', 0)))} izlenme / "
            f"{_fmt_n(int(t.get('subs', 0)))} abonelik kanal)"
            for t in proven_topics)
        # ZORUNLU seçim: kaçış kapısı ("uymuyorsa serbest üret") bırakıldığında LLM
        # bankayı görmezden gelip halüsinasyon üretti (gerçek hata 2026-07-12:
        # "doktorlar sembolik güçlerini artırmak için tıbbi semboller yutuyordu").
        proven_block = (
            "\nKANITLANMIŞ KONULAR (nişinde küçük kanallarda patlamış gerçek "
            "videolardan damıtıldı — hepsi DOĞRULANMIŞ olgular):\n" + lines + "\n"
            'ZORUNLU: Bu listeden TAM OLARAK BİR konu seç ve çıktına '
            '"bank_id": <seçtiğin id> ekle. Serbest konu üretmek YASAK — '
            '"bank_id" null OLAMAZ.\n'
            "İçeriği SEÇTİĞİN konunun etrafında yaz: o olguyu açıkla, bağlamını ve "
            "şaşırtıcı yanını anlat.\n"
            "UYDURMA YASAĞI: Seçtiğin olgunun DIŞINDA yeni 'gerçek' UYDURMA. Emin "
            "olmadığın tarih, sayı, isim, mekanizma EKLEME. Bilmediğin detayı "
            "yazmak yerine olgunun bilinen kısmını derinleştir.\n")

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
{forbidden_block}{rotation_block}{proven_block}
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


_TAG_OVERLAP_THRESHOLD = 0.70   # same-tag medium-fuzzy match → duplicate


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
    backend: str = "claude_cli",
    api_key: str | None = None,
    proven_topics: list[dict] | None = None,
) -> GeneratorResult:
    prompt = build_generator_prompt(
        channel=channel, dna=dna,
        forbidden_texts=forbidden_texts,
        topic_distribution=topic_distribution,
        proven_topics=proven_topics,
    )
    result = run_json(
        prompt, GeneratorResult,
        claude_path=claude_path, model=model,
        backend=backend, api_key=api_key,
        retries=2, timeout_s=180,
    )
    if not proven_topics:
        return result
    # Banka doluysa seçim ZORUNLU: LLM atlarsa ya da uydurma id verirse bir kez
    # düzeltici tekrar (gerçek hata: bankayı yok sayıp halüsinasyon üretti).
    valid_ids = {int(t["id"]) for t in proven_topics}
    if result.bank_id in valid_ids:
        return result
    ids_txt = ", ".join(str(i) for i in sorted(valid_ids))
    retry = (prompt + f"\n\nHATA: Önceki denemende geçerli bir kanıtlanmış konu "
             f"SEÇMEDİN (bank_id={result.bank_id!r}). ZORUNLU: yukarıdaki "
             f"listeden bir konu seç; \"bank_id\" şu id'lerden biri OLMALI: "
             f"{ids_txt}. Serbest/uydurma konu YASAK.\n")
    result = run_json(
        retry, GeneratorResult,
        claude_path=claude_path, model=model,
        backend=backend, api_key=api_key,
        retries=2, timeout_s=180,
    )
    if result.bank_id not in valid_ids:
        result.bank_id = None   # yine seçmedi → mark_used no-op (üretim durmaz)
    return result
