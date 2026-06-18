"""Community-tab post suggester.

YouTube Community posts can't be created via the Data API (read-only), so
this module generates DRAFT TEXTS the user copy-pastes manually into the
YouTube Studio's "Community" tab.

A single call to Claude Sonnet produces 5 drafts in 5 different formats
(poll, question, nostalgia, tier-list, hot-take) so the user has variety.
Channel DNA tone + recent short titles + currently-trending terms are all
fed into the prompt so each draft fits the channel voice and the current
news cycle.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.engine import Engine

from short_bot.claude_cli import run_json
from short_bot.config import ChannelConfig
from short_bot.db import shorts


DraftFormat = Literal["poll", "question", "nostalgia", "tier_list", "hot_take"]


class CommunityDraft(BaseModel):
    format: DraftFormat
    text: str = Field(min_length=5, max_length=300)
    options: list[str] = Field(default_factory=list, max_length=6)
    image_hint: str = Field(default="", max_length=200)


class _Drafts(BaseModel):
    drafts: list[CommunityDraft] = Field(min_length=3, max_length=8)


_FORMAT_DESCRIPTIONS = """\
5 farklı FORMAT ile 5 community post taslağı üret:

1. poll — 3-5 seçenekli oylama (en yüksek engagement)
   text: kısa soru başlığı (örn "RAMS PARK'taki en güzel an?")
   options: ["🏆 Kupanın kalkması", "🦁 Erden Timur sürprizi", ...]

2. question — tek-kelimelik cevap isteyen soru
   text: "🦁 Tek kelimeyle: Icardi gelecek sezon? 💛❤️\\nYorumlarda görelim 👇"

3. nostalgia — geçmişe gönderme + bağlama-davet
   text: "👑 Bu anı hatırlayan VAR MI?\\nİlk gördüğünüzdeki yaşınızı yazın 🦁"
   image_hint: "2000 UEFA finalindeki kupanın havaya kalkma anı"

4. tier_list — sıralama yorum patlatır
   text: "🦁 GS tarihinin en iyi forveti?"
   options: ["1️⃣ Hakan Şükür", "2️⃣ Drogba", "3️⃣ Icardi", "4️⃣ Hagi"]

5. hot_take — provokatif, kontrlöz fikir
   text: "💥 Net konuşalım: Bu kadro şampiyonlar liginde 8'i geçer mi?"
"""

_PROMPT_TEMPLATE = """\
Sen "{channel_name}" YouTube kanalının topluluk sekmesi için post fikirleri \
üreten editörsün.

KANAL KİMLİĞİ
- Ad: {channel_name}
- Dil: {language_name}
- Persona: {persona}
- Voice: {voice}
- Style: {style}
- Kaçınılacak ton: {forbidden}
- Anahtar kelimeler: {keywords}

SON ÜRETILEN SHORTS (kanalın güncel konuları):
{recent_shorts}

REGION'DA AKTİF TREND OLAN TERİMLER (varsa kullan):
{trend_terms}

{format_descriptions}

KURALLAR
- Her post EMOJI ile başlasın
- Cümle sonu soru → "?" zorunlu
- 280 karakteri geçme
- Polls: 3-5 seçenek, her birinde emoji
- Nostalji formatı için image_hint yaz (görsel önerisi, 200 char altı)
- Türkçe konuş, taraftar tonunda
- Asla generic/abur cubur olma — KANALIN bu hafta gündemine uygun olsun

SADECE şu JSON'u dön:
{{
  "drafts": [
    {{"format": "poll", "text": "...", "options": ["...", "...", "..."]}},
    {{"format": "question", "text": "..."}},
    {{"format": "nostalgia", "text": "...", "image_hint": "..."}},
    {{"format": "tier_list", "text": "...", "options": ["...", "..."]}},
    {{"format": "hot_take", "text": "..."}}
  ]
}}
"""

_LANG_NAMES = {"tr": "Türkçe", "en": "English", "de": "Deutsch",
                "es": "Español", "fr": "Français"}


def fetch_recent_short_titles(eng: Engine, channel: str, *, limit: int = 8,
                               days: int = 14) -> list[str]:
    """Recent (non-deleted) short titles for `channel`, newest first."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with eng.connect() as conn:
        rows = conn.execute(
            select(shorts.c.title)
            .where(shorts.c.channel == channel)
            .where(shorts.c.deleted_at.is_(None))
            .where(shorts.c.created_at >= cutoff)
            .order_by(shorts.c.created_at.desc())
            .limit(limit)
        ).all()
    return [r[0] for r in rows]


def build_community_prompt(
    channel: ChannelConfig,
    *,
    recent_titles: list[str],
    trend_terms: list[str] | None = None,
) -> str:
    dna = channel.dna
    if dna is not None:
        persona = dna.persona_summary
        voice = dna.tone.voice
        style = dna.tone.style
        forbidden = ", ".join(dna.tone.forbidden) if dna.tone.forbidden else "(yok)"
    else:
        persona = f"{channel.name} taraftarı için içerik üreten kanal"
        voice = "tutkulu, vurucu"
        style = "kısa, samimi"
        forbidden = "(yok)"

    recent_block = (
        "\n".join(f"- {t}" for t in recent_titles[:8])
        if recent_titles else "(henüz veri yok)"
    )
    trend_block = (
        "\n".join(f"- {t}" for t in (trend_terms or [])[:8])
        if trend_terms else "(şu an aktif trend bilgisi yok)"
    )
    keywords = ", ".join(channel.keywords or []) or "(yok)"

    return _PROMPT_TEMPLATE.format(
        channel_name=channel.name,
        language_name=_LANG_NAMES.get(channel.language, channel.language),
        persona=persona,
        voice=voice,
        style=style,
        forbidden=forbidden,
        keywords=keywords,
        recent_shorts=recent_block,
        trend_terms=trend_block,
        format_descriptions=_FORMAT_DESCRIPTIONS,
    )


def suggest_community_posts(
    channel: ChannelConfig,
    *,
    recent_titles: list[str],
    trend_terms: list[str] | None = None,
    claude_path: str = "claude",
    model: str = "sonnet",
    backend: str = "claude_cli",
    api_key: str | None = None,
) -> list[CommunityDraft]:
    """Generate 5 community-post drafts via the active AI backend. Returns drafts list.

    Raises short_bot.claude_cli.ClaudeCliError on CLI / JSON failure (caller
    surfaces an error flash). On model returning fewer/more than 5 drafts,
    we just return what came back — UI handles the count gracefully."""
    prompt = build_community_prompt(
        channel, recent_titles=recent_titles, trend_terms=trend_terms,
    )
    parsed = run_json(prompt, _Drafts, claude_path=claude_path,
                       model=model, backend=backend, api_key=api_key,
                       retries=2, timeout_s=90)
    return list(parsed.drafts)
