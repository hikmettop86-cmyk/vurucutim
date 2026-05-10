"""Dedup: GUID exact match + fuzzy title similarity + optional embedding-based
topic similarity (for the multi-publisher same-story case)."""
import logging
import math

from sqlalchemy.engine import Engine

from short_bot.db import (
    fetch_recent_embeddings,
    is_processed,
    similar_title_exists,
)
from short_bot.embeddings import EmbeddingError, embed_text
from short_bot.models import NewsItem

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def filter_new(
    eng: Engine,
    items: list[NewsItem],
    channel: str,
    *,
    fuzzy_threshold: float,
    openai_api_key: str | None = None,
    embeddings_out: dict[str, list[float]] | None = None,
    topic_threshold: float = 0.80,
    lookback_days: int = 7,
) -> list[NewsItem]:
    """Filter items, dropping ones we've already processed.

    Three layered checks (each cheaper than the next):
      1. GUID exact match against processed_items
      2. Fuzzy title similarity vs recent processed_items
      3. Embedding cosine vs recent processed_items embeddings (only when
         openai_api_key is provided; graceful skip on any embed failure)

    When `embeddings_out` is provided, the embedding computed for each
    *passing* candidate is recorded there (keyed by guid) so the caller
    can persist it via mark_processed(... embedding=...) after a
    successful render.
    """
    existing_embeddings: list[list[float]] = []
    if openai_api_key:
        existing_embeddings = fetch_recent_embeddings(
            eng, channel, lookback_days=lookback_days
        )

    out: list[NewsItem] = []
    for item in items:
        if is_processed(eng, item.guid, channel):
            continue
        if similar_title_exists(eng, item.title, channel, fuzzy_threshold):
            continue

        # Topic-level dedup via embeddings — only when we have a key.
        candidate_embedding: list[float] | None = None
        if openai_api_key:
            try:
                candidate_embedding = embed_text(
                    item.title, api_key=openai_api_key
                )
            except EmbeddingError as e:
                logger.warning(
                    f"embed_text failed for '{item.title[:50]}': {e} — "
                    f"skipping topic dedup for this item"
                )
                candidate_embedding = None

            if candidate_embedding is not None and existing_embeddings:
                topic_match = False
                for ex_emb in existing_embeddings:
                    sim = _cosine(candidate_embedding, ex_emb)
                    if sim >= topic_threshold:
                        logger.info(
                            f"topic-dedup skip '{item.title[:50]}' "
                            f"(cosine={sim:.3f} >= {topic_threshold})"
                        )
                        topic_match = True
                        break
                if topic_match:
                    continue

        if embeddings_out is not None and candidate_embedding is not None:
            embeddings_out[item.guid] = candidate_embedding
        out.append(item)
    return out
