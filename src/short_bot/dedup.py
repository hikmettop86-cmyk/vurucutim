"""Dedup: GUID exact match + fuzzy title similarity (per channel)."""
from sqlalchemy.engine import Engine

from short_bot.db import is_processed, similar_title_exists
from short_bot.models import NewsItem


def filter_new(
    eng: Engine,
    items: list[NewsItem],
    channel: str,
    *,
    fuzzy_threshold: float,
) -> list[NewsItem]:
    out: list[NewsItem] = []
    for item in items:
        if is_processed(eng, item.guid, channel):
            continue
        if similar_title_exists(eng, item.title, channel, fuzzy_threshold):
            continue
        out.append(item)
    return out
