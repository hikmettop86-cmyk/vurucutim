"""Per-channel DNA cache with embedding-based similarity lookup.

Backed by the `dna_cache` SQLite table (defined in db.py). Embeddings stored
as JSON arrays; cosine computed in numpy on each lookup. At expected
per-channel volume (~1000 rows over 90 days), linear scan is well under 50ms.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import insert, select, update, delete
from sqlalchemy.engine import Engine

from short_bot.db import dna_cache as _dna_cache_table
from short_bot.dna import DnaSpec

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheHit:
    id: int
    archetype: str
    css_filename: str
    dna: DnaSpec
    score: float


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def save_cached_dna(
    eng: Engine,
    channel_slug: str,
    topic_text: str,
    embedding: list[float],
    dna: DnaSpec,
    css_filename: str,
) -> int:
    """Insert a new cache row. Returns the new id."""
    now = _utcnow()
    with eng.begin() as conn:
        result = conn.execute(insert(_dna_cache_table).values(
            channel_slug=channel_slug,
            topic_text=topic_text,
            embedding=json.dumps(embedding),
            dna_json=dna.model_dump_json(),
            css_filename=css_filename,
            archetype=dna.archetype,
            created_at=now,
            last_used_at=now,
            hit_count=0,
        ))
        return int(result.inserted_primary_key[0])


def lookup_cached_dna(
    eng: Engine,
    channel_slug: str,
    embedding: list[float],
    *,
    threshold: float = 0.85,
) -> CacheHit | None:
    """Find the best-matching cached DNA for this channel, or None.

    Returns None if no row exists or if the best cosine is below threshold.
    """
    query_vec = np.array(embedding, dtype=np.float32)
    query_norm = float(np.linalg.norm(query_vec))
    if query_norm == 0.0:
        return None

    with eng.begin() as conn:
        rows = conn.execute(
            select(_dna_cache_table).where(
                _dna_cache_table.c.channel_slug == channel_slug
            )
        ).fetchall()

    if not rows:
        return None

    best_score = -1.0
    best_row = None
    for row in rows:
        try:
            row_vec = np.array(json.loads(row.embedding), dtype=np.float32)
        except (ValueError, TypeError):
            continue
        row_norm = float(np.linalg.norm(row_vec))
        if row_norm == 0.0:
            continue
        score = float(np.dot(query_vec, row_vec) / (query_norm * row_norm))
        if score > best_score:
            best_score = score
            best_row = row

    if best_row is None or best_score < threshold:
        return None

    try:
        dna = DnaSpec.model_validate(json.loads(best_row.dna_json))
    except Exception as e:
        _LOG.warning(f"failed to parse cached dna_json id={best_row.id}: {e}")
        return None

    return CacheHit(
        id=int(best_row.id),
        archetype=str(best_row.archetype),
        css_filename=str(best_row.css_filename),
        dna=dna,
        score=best_score,
    )


def increment_hit_count(eng: Engine, cache_id: int) -> None:
    """Bump hit_count and update last_used_at."""
    with eng.begin() as conn:
        conn.execute(
            update(_dna_cache_table)
            .where(_dna_cache_table.c.id == cache_id)
            .values(
                hit_count=_dna_cache_table.c.hit_count + 1,
                last_used_at=_utcnow(),
            )
        )


def cleanup_expired_dna_cache(
    eng: Engine,
    css_dir: Path,
    *,
    days: int = 90,
) -> int:
    """Delete cache rows older than `days` and their CSS files. Returns count."""
    cutoff = _utcnow() - timedelta(days=days)
    with eng.begin() as conn:
        rows_to_delete = conn.execute(
            select(_dna_cache_table.c.id, _dna_cache_table.c.css_filename)
            .where(_dna_cache_table.c.created_at < cutoff)
        ).fetchall()
        if not rows_to_delete:
            return 0
        ids = [r.id for r in rows_to_delete]
        conn.execute(
            delete(_dna_cache_table).where(_dna_cache_table.c.id.in_(ids))
        )

    for r in rows_to_delete:
        f = Path(css_dir) / r.css_filename
        try:
            f.unlink(missing_ok=True)
        except OSError as e:
            _LOG.warning(f"could not delete cache CSS {f}: {e}")
    return len(rows_to_delete)
