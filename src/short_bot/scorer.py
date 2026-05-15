"""LLM-based interestingness scorer (0-10) per news item."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from short_bot.claude_cli import run_json
from short_bot.models import NewsItem, ScoredItem

if TYPE_CHECKING:
    from short_bot.config import ChannelConfig


class _ItemScore(BaseModel):
    guid: str
    score: float = Field(ge=0, le=10)
    reasoning: str = Field(max_length=200)


class _ScoreResponse(BaseModel):
    scores: list[_ItemScore]


_PROMPT_TEMPLATES = {
    "tr": """Sen bir YouTube Shorts kanalının editörüsün.

KANAL: {channel_name}
KONU/ANAHTAR KELİMELER: {keywords}

Aşağıdaki haber başlıklarını bu KANALA UYGUNLUK ve ilginçlik açısından 0-10 puanla:
- 9-10: Bu kanal için son dakika çok etkileyici (kanalın konusuyla doğrudan ilgili, viral)
- 7-8: Konuyla ilgili, önemli, video yapılır
- 5-6: Konuyla yan ilgili veya derinliği zayıf
- 1-4: Sıkıcı, teknik, lokal
- 0:   KONU DIŞI (kanalın anahtar kelimeleriyle alakasız) — başlık ne kadar çekici olursa olsun 0-3 ver

Başlıklar:
{listing}

SADECE şu JSON formatında yanıtla, başka metin yazma:
{{"scores": [{{"guid": "<aynısı>", "score": <0-10>, "reasoning": "<≤200 char, neden bu puan>"}}, ...]}}""",

    "en": """You are an editor for a YouTube Shorts channel.

CHANNEL: {channel_name}
TOPIC/KEYWORDS: {keywords}

Score the news headlines below from 0-10 based on RELEVANCE TO THIS CHANNEL and interestingness:
- 9-10: Major breaking news for this channel (directly on topic, viral potential)
- 7-8: On topic, important, worth a video
- 5-6: Tangentially related or shallow
- 1-4: Boring, technical, hyperlocal
- 0:   OFF-TOPIC (unrelated to channel keywords) — even if the headline sounds catchy, score 0-3

Headlines:
{listing}

Reply ONLY in this JSON format, no other text:
{{"scores": [{{"guid": "<same>", "score": <0-10>, "reasoning": "<≤200 char, why this score>"}}, ...]}}""",

    "de": """Du bist Redakteur eines YouTube Shorts Kanals.

KANAL: {channel_name}
THEMA/SCHLÜSSELWÖRTER: {keywords}

Bewerte die folgenden Schlagzeilen von 0-10 nach RELEVANZ FÜR DIESEN KANAL und Interesse:
- 9-10: Wichtige Eilmeldung für diesen Kanal (direkt zum Thema, viraler Charakter)
- 7-8: Thematisch passend, wichtig, video-würdig
- 5-6: Nur am Rande relevant oder oberflächlich
- 1-4: Langweilig, technisch, lokal
- 0:   OFF-TOPIC (nicht verwandt mit Kanal-Schlüsselwörtern) — egal wie spannend die Schlagzeile klingt, gib 0-3

Schlagzeilen:
{listing}

Antworte NUR in diesem JSON-Format, kein anderer Text:
{{"scores": [{{"guid": "<gleich>", "score": <0-10>, "reasoning": "<≤200 char, warum>"}}, ...]}}""",
}


def build_scoring_prompt(
    items: list[NewsItem],
    *,
    channel: "ChannelConfig | None" = None,
    performance_insights: dict | None = None,
) -> str:
    listing = "\n".join(f"- guid={i.guid} | {i.title}" for i in items)
    if channel is None:
        # Backward-compat fallback: legacy callers (no channel context). Use
        # generic Turkish prompt without channel anchoring.
        return (
            "Aşağıdaki haber başlıklarını bir YouTube Shorts kanalı için "
            "ilginçlik/önem açısından 0-10 arası puanla. 9-10 = son dakika çok etkileyici "
            "(deprem, kritik karar, şok haber); 7-8 = önemli ama bekleyebilir; "
            "5-6 = ilginç ama derinliği yok; 0-4 = sıkıcı/teknik/lokal.\n\n"
            f"Başlıklar:\n{listing}\n\n"
            "SADECE şu JSON formatında yanıtla, başka metin yazma:\n"
            '{"scores": [{"guid": "<aynısı>", "score": <0-10>, "reasoning": "<≤200 char>"}, ...]}'
        )
    template = _PROMPT_TEMPLATES.get(channel.language, _PROMPT_TEMPLATES["en"])
    keywords_str = ", ".join(channel.keywords) if channel.keywords else "(no keywords)"
    base = template.format(
        channel_name=channel.name,
        keywords=keywords_str,
        listing=listing,
    )
    # Optional performance-feedback hint. format_scorer_hint returns "" when
    # the insight set is too sparse (<5 samples) so callers can pass freely
    # without worrying about anchoring on noise.
    if performance_insights:
        from short_bot.learning.injection import format_scorer_hint
        hint = format_scorer_hint(performance_insights)
        if hint:
            base = base + "\n\n" + hint
    return base


_BATCH_SIZE = 30   # tighter batches keep Haiku responses fast and well within
                   # context. Tested at 30 items the model returns in 5-15s;
                   # 100+ items sometimes time out or return truncated JSON.


def score_items(
    items: list[NewsItem],
    *,
    claude_path: str = "claude",
    model: str = "default",
    batch_size: int = _BATCH_SIZE,
    channel: "ChannelConfig | None" = None,
    performance_insights: dict | None = None,
) -> list[ScoredItem]:
    if not items:
        return []
    by_guid = {i.guid: i for i in items}
    out: list[ScoredItem] = []
    # Batch to avoid timeouts on large feeds. Each batch is an independent
    # claude call — failures in one batch shouldn't kill the whole run.
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        prompt = build_scoring_prompt(
            batch, channel=channel,
            performance_insights=performance_insights,
        )
        try:
            response = run_json(
                prompt, _ScoreResponse,
                claude_path=claude_path, model=model,
            )
        except Exception:
            # Batch failure: skip this batch, score the rest. Better to lose
            # some candidates than to fail the entire run.
            continue
        for s in response.scores:
            item = by_guid.get(s.guid)
            if item is None:
                continue
            out.append(ScoredItem(item=item, score=s.score, reasoning=s.reasoning))
    return out


def select_top(scored: list[ScoredItem], min_score: float, n: int = 1) -> list[ScoredItem]:
    above = [s for s in scored if s.score >= min_score]
    above.sort(key=lambda s: s.score, reverse=True)
    return above[:n]
