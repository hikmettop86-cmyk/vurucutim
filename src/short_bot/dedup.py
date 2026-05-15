"""Dedup: GUID exact + fuzzy title + RSS-topic embedding + produced-headline
embedding (catches the 'same story from 3 publishers' case where each yields
a different RSS title but Claude normalizes them all to the same headline)."""
import logging
import math

from sqlalchemy.engine import Engine

from short_bot.db import (
    fetch_recent_embeddings,
    fetch_recent_produced_title_embeddings,
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
    topic_threshold: float = 0.72,
    produced_threshold: float = 0.78,
    lookback_days: int = 14,
) -> list[NewsItem]:
    """Filter items, dropping ones we've already processed.

    Four layered checks (each cheaper than the next):
      1. GUID exact match against processed_items.
      2. Fuzzy title similarity vs recent processed_items.title.
      3. Embedding cosine of candidate.title vs RSS-side history
         (processed_items.embedding_json) — catches multi-publisher
         variants of the same story.
      4. Embedding cosine of candidate.title vs PRODUCED-headline history
         (processed_items.produced_title_embedding_json) — catches the
         case where 3 different RSS titles all yielded the same Claude
         output before; even if (3) misses, (4) anchors on the actual
         video output our channel published.

    Thresholds (smaller = stricter):
      topic_threshold     0.72  RSS-side title vs RSS-side history
      produced_threshold  0.78  RSS-side title vs Claude-side history
                                  (higher because Claude normalizes — the
                                  produced text clusters tighter so a same-
                                  story candidate scores HIGHER against
                                  produced output than against RSS title)

    When `embeddings_out` is provided, the embedding computed for each
    *passing* candidate is recorded there (keyed by guid) so the caller
    can persist it via mark_processed(... embedding=...) after a
    successful render.
    """
    existing_rss_embeddings: list[list[float]] = []
    existing_produced_embeddings: list[list[float]] = []
    if openai_api_key:
        existing_rss_embeddings = fetch_recent_embeddings(
            eng, channel, lookback_days=lookback_days,
        )
        existing_produced_embeddings = fetch_recent_produced_title_embeddings(
            eng, channel, lookback_days=lookback_days,
        )

    out: list[NewsItem] = []
    for item in items:
        if is_processed(eng, item.guid, channel):
            continue
        if similar_title_exists(eng, item.title, channel, fuzzy_threshold):
            continue

        candidate_embedding: list[float] | None = None
        if openai_api_key:
            try:
                candidate_embedding = embed_text(
                    item.title, api_key=openai_api_key,
                )
            except EmbeddingError as e:
                logger.warning(
                    f"embed_text failed for '{item.title[:50]}': {e} — "
                    f"skipping topic dedup for this item"
                )
                candidate_embedding = None

            if candidate_embedding is not None:
                # Check 3: RSS-side history
                if existing_rss_embeddings:
                    best = max(
                        (_cosine(candidate_embedding, e)
                         for e in existing_rss_embeddings),
                        default=0.0,
                    )
                    if best >= topic_threshold:
                        logger.info(
                            f"topic-dedup skip '{item.title[:50]}' "
                            f"(rss-side cosine={best:.3f} >= {topic_threshold})"
                        )
                        continue

                # Check 4: produced-headline history (new layer)
                if existing_produced_embeddings:
                    best = max(
                        (_cosine(candidate_embedding, e)
                         for e in existing_produced_embeddings),
                        default=0.0,
                    )
                    if best >= produced_threshold:
                        logger.info(
                            f"produced-dedup skip '{item.title[:50]}' "
                            f"(claude-side cosine={best:.3f} "
                            f">= {produced_threshold})"
                        )
                        continue

        if embeddings_out is not None and candidate_embedding is not None:
            embeddings_out[item.guid] = candidate_embedding
        out.append(item)
    return out
