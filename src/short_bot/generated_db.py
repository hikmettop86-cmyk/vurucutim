"""generated_items table for content-generator dedup + topic distribution."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, MetaData, String, Table, Text,
    UniqueConstraint, and_, func, select,
)
from sqlalchemy.engine import Engine


# Reuse the same MetaData object so init_db sees both tables.
# (db.py imports this and adds to its create_all run.)
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
    Column("short_id", Integer, ForeignKey("shorts.id")),
    Column("status", String, nullable=False, default="used"),  # used | discarded
    UniqueConstraint("channel", "text_hash", name="ix_generated_unique_hash"),
)
Index("ix_generated_recent", generated_items.c.channel,
      generated_items.c.created_at.desc())
Index("ix_generated_topic", generated_items.c.channel,
      generated_items.c.topic_tag, generated_items.c.created_at.desc())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
