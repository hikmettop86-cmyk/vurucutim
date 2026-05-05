"""LLM-based interestingness scorer (0-10) per news item."""
from pydantic import BaseModel, Field

from short_bot.claude_cli import run_json
from short_bot.models import NewsItem, ScoredItem


class _ItemScore(BaseModel):
    guid: str
    score: float = Field(ge=0, le=10)
    reasoning: str = Field(max_length=200)


class _ScoreResponse(BaseModel):
    scores: list[_ItemScore]


def build_scoring_prompt(items: list[NewsItem]) -> str:
    listing = "\n".join(f"- guid={i.guid} | {i.title}" for i in items)
    return (
        "Aşağıdaki Türkçe haber başlıklarını bir YouTube Shorts kanalı için "
        "ilginçlik/önem açısından 0-10 arası puanla. 9-10 = son dakika çok etkileyici "
        "(deprem, kritik karar, şok haber); 7-8 = önemli ama bekleyebilir; "
        "5-6 = ilginç ama derinliği yok; 0-4 = sıkıcı/teknik/lokal.\n\n"
        f"Başlıklar:\n{listing}\n\n"
        "SADECE şu JSON formatında yanıtla, başka metin yazma:\n"
        '{"scores": [{"guid": "<aynısı>", "score": <0-10>, "reasoning": "<≤200 char>"}, ...]}'
    )


def score_items(
    items: list[NewsItem],
    *,
    claude_path: str = "claude",
) -> list[ScoredItem]:
    if not items:
        return []
    prompt = build_scoring_prompt(items)
    response = run_json(prompt, _ScoreResponse, claude_path=claude_path)
    by_guid = {i.guid: i for i in items}
    out: list[ScoredItem] = []
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
