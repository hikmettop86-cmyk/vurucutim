"""generated_items table for content-generator dedup + topic distribution."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Column, DateTime, Index, Integer, MetaData, String, Table, Text,
    UniqueConstraint, func, select,
)
from sqlalchemy.engine import Engine


# Separate MetaData object — db.py's init_db will call create_all on this.
# (Wiring happens in Task 2; until then this table won't be auto-created.)
metadata = MetaData()

generated_items = Table(
    "generated_items", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False),
    Column("text", Text, nullable=False),
    Column("text_hash", String(64), nullable=False),
    Column("topic_tag", String, nullable=False),
    Column("language", String, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("short_id", Integer),  # soft-ref to shorts.id; no FK across MetaData objects
    Column("status", String, nullable=False, default="used"),  # used | discarded
    UniqueConstraint("channel", "text_hash", name="ix_generated_unique_hash"),
)
Index("ix_generated_recent", generated_items.c.channel,
      generated_items.c.created_at.desc())
Index("ix_generated_topic", generated_items.c.channel,
      generated_items.c.topic_tag, generated_items.c.created_at.desc())


_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")

# Turkish-aware uppercase-to-lowercase mapping before calling str.lower().
# In Turkish: İ → i (dotted I), I → ı (dotless i).
# Python's str.lower() maps I → i (not ı), so we pre-substitute.
_TR_UPPER_MAP = str.maketrans("İI", "iı")


def normalize_for_hash(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Uses Turkish-aware lowercasing so 'I' → 'ı' and 'İ' → 'i' before
    applying str.lower(), ensuring 'SABIRLA' → 'sabırla' when the source
    text uses Turkish orthography.

    Used so 'Aşk, sabırla başlar.' and 'aşk sabırla başlar' hash identically.
    """
    text = text.strip().translate(_TR_UPPER_MAP).lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def insert_generated(
    eng: Engine, *,
    channel: str, text: str, topic_tag: str, language: str,
    status: str = "used", short_id: int | None = None,
) -> int:
    """Insert a generated item. Caller computes hash via `text_hash(text)` implicitly here."""
    h = text_hash(text)
    with eng.begin() as conn:
        result = conn.execute(generated_items.insert().values(
            channel=channel, text=text, text_hash=h,
            topic_tag=topic_tag, language=language,
            created_at=_utcnow(), short_id=short_id, status=status,
        ))
        return result.inserted_primary_key[0]


def update_generated_short_id(eng: Engine, generated_id: int, short_id: int) -> None:
    with eng.begin() as conn:
        conn.execute(generated_items.update()
                     .where(generated_items.c.id == generated_id)
                     .values(short_id=short_id))


def exists_hash(eng: Engine, channel: str, hash_value: str) -> bool:
    with eng.connect() as conn:
        row = conn.execute(
            select(generated_items.c.id)
            .where(generated_items.c.channel == channel)
            .where(generated_items.c.text_hash == hash_value)
            .limit(1)
        ).fetchone()
    return row is not None


def recent_generated_texts(
    eng: Engine, channel: str, *, limit: int = 50,
) -> list[str]:
    """Return most recent `used` texts (newest first), capped at `limit`."""
    with eng.connect() as conn:
        rows = conn.execute(
            select(generated_items.c.text)
            .where(generated_items.c.channel == channel)
            .where(generated_items.c.status == "used")
            .order_by(generated_items.c.created_at.desc())
            .limit(limit)
        ).fetchall()
    return [r[0] for r in rows]


def recent_by_tag(
    eng: Engine, channel: str, *, tag: str, days: int = 7, limit: int = 20,
) -> list[str]:
    cutoff = _utcnow() - timedelta(days=days)
    with eng.connect() as conn:
        rows = conn.execute(
            select(generated_items.c.text)
            .where(generated_items.c.channel == channel)
            .where(generated_items.c.topic_tag == tag)
            .where(generated_items.c.status == "used")
            .where(generated_items.c.created_at >= cutoff)
            .order_by(generated_items.c.created_at.desc())
            .limit(limit)
        ).fetchall()
    return [r[0] for r in rows]


def topic_distribution(
    eng: Engine, channel: str, *, days: int = 7,
) -> dict[str, int]:
    cutoff = _utcnow() - timedelta(days=days)
    with eng.connect() as conn:
        rows = conn.execute(
            select(generated_items.c.topic_tag,
                   func.count(generated_items.c.id))
            .where(generated_items.c.channel == channel)
            .where(generated_items.c.status == "used")
            .where(generated_items.c.created_at >= cutoff)
            .group_by(generated_items.c.topic_tag)
        ).fetchall()
    return {tag: count for tag, count in rows}
