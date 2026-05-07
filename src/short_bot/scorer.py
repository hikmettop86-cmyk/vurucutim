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


_BATCH_SIZE = 30   # tighter batches keep Haiku responses fast and well within
                   # context. Tested at 30 items the model returns in 5-15s;
                   # 100+ items sometimes time out or return truncated JSON.


def score_items(
    items: list[NewsItem],
    *,
    claude_path: str = "claude",
    model: str = "default",
    batch_size: int = _BATCH_SIZE,
) -> list[ScoredItem]:
    if not items:
        return []
    by_guid = {i.guid: i for i in items}
    out: list[ScoredItem] = []
    # Batch to avoid timeouts on large feeds. Each batch is an independent
    # claude call — failures in one batch shouldn't kill the whole run.
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        prompt = build_scoring_prompt(batch)
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
