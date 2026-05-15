"""SQLite via SQLAlchemy Core. Plain functions, no ORM session ceremony."""
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Index, Integer, MetaData, String,
    Table, Text, create_engine, select,
)
from sqlalchemy.engine import Engine


def _utcnow() -> datetime:
    """UTC now, timezone-aware. Replaces deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)


metadata = MetaData()

processed_items = Table(
    "processed_items", metadata,
    Column("guid", String, primary_key=True),
    Column("title", Text, nullable=False),
    Column("channel", String, nullable=False),
    Column("processed_at", DateTime, default=_utcnow),
    # OpenAI text-embedding-3-small vector (1536 dims) serialized as JSON
    # array. NULL on legacy rows or when no API key is configured. Used by
    # dedup.filter_new for topic-level similarity check beyond fuzzy title.
    Column("embedding_json", Text),
)
Index("idx_processed_channel_ts",
      processed_items.c.channel, processed_items.c.processed_at)

rss_items = Table(
    "rss_items", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("guid", String, nullable=False),
    Column("channel", String, nullable=False),
    Column("title", Text, nullable=False),
    Column("link", Text, nullable=False),
    Column("source", String),
    Column("pub_date", DateTime),
    Column("thumb_url", Text),
    Column("score", Float),
    Column("status", String),
    Column("fetched_at", DateTime, default=_utcnow),
    Column("short_id", Integer, ForeignKey("shorts.id")),
)

shorts = Table(
    "shorts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False),
    Column("rss_item_guid", String),
    Column("title", Text, nullable=False),
    Column("file_path", Text, nullable=False),
    Column("duration_s", Integer),
    Column("script_json", Text),
    Column("render_ms", Integer),
    Column("created_at", DateTime, default=_utcnow),
    Column("deleted_at", DateTime),
)
Index("idx_shorts_channel_created",
      shorts.c.channel, shorts.c.created_at.desc())

runs = Table(
    "runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False),
    Column("trigger", String, nullable=False),
    Column("started_at", DateTime, default=_utcnow),
    Column("ended_at", DateTime),
    Column("status", String),
    Column("short_id", Integer, ForeignKey("shorts.id")),
    Column("error", Text),
    Column("log_path", Text),
)

youtube_uploads = Table(
    "youtube_uploads", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("short_id", Integer, ForeignKey("shorts.id"), nullable=False),
    Column("video_id", String),
    Column("video_url", String),
    Column("status", String, nullable=False),
    Column("error", Text),
    Column("uploaded_at", DateTime, default=_utcnow),
)
Index("idx_yt_uploads_short", youtube_uploads.c.short_id, youtube_uploads.c.uploaded_at)

youtube_video_stats = Table(
    "youtube_video_stats", metadata,
    Column("video_id", String, nullable=False),
    Column("snapshot_date", String, nullable=False),
    Column("views", Integer, default=0),
    Column("likes", Integer, default=0),
    Column("comments", Integer, default=0),
    Column("watch_time_min", Float, default=0.0),
    Column("avg_view_duration_s", Float, default=0.0),
    Column("updated_at", DateTime, default=_utcnow),
)
Index("idx_yt_video_stats_video_date",
      youtube_video_stats.c.video_id, youtube_video_stats.c.snapshot_date,
      unique=True)

youtube_channel_stats = Table(
    "youtube_channel_stats", metadata,
    Column("channel", String, nullable=False),
    Column("snapshot_date", String, nullable=False),
    Column("subscribers", Integer, default=0),
    Column("total_views", Integer, default=0),
    Column("updated_at", DateTime, default=_utcnow),
)
Index("idx_yt_channel_stats_chan_date",
      youtube_channel_stats.c.channel, youtube_channel_stats.c.snapshot_date,
      unique=True)

youtube_quota = Table(
    "youtube_quota", metadata,
    Column("channel", String, nullable=False),
    Column("date", String, nullable=False),
    Column("units_used", Integer, default=0),
    Column("updated_at", DateTime, default=_utcnow),
)
Index("idx_yt_quota_chan_date",
      youtube_quota.c.channel, youtube_quota.c.date, unique=True)

dna_cache = Table(
    "dna_cache", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel_slug", String, nullable=False),
    Column("topic_text", Text, nullable=False),
    Column("embedding", Text, nullable=False),  # JSON array of floats; small enough
    Column("dna_json", Text, nullable=False),
    Column("css_filename", String, nullable=False),
    Column("archetype", String, nullable=False),
    Column("created_at", DateTime, default=_utcnow, nullable=False),
    Column("last_used_at", DateTime),
    Column("hit_count", Integer, default=0, nullable=False),
)
Index("idx_dna_cache_channel_created",
      dna_cache.c.channel_slug, dna_cache.c.created_at)

# Per-channel performance insights computed nightly (and on-demand from the
# /insights/<slug> web view). data_json is the structured aggregation dict
# documented in short_bot.learning.aggregator.compute_channel_insights().
# Used both for UI display AND for scorer prompt injection (so future runs
# inherit "what's actually worked for this channel").
channel_insights = Table(
    "channel_insights", metadata,
    Column("channel", String, primary_key=True),
    Column("computed_at", DateTime, default=_utcnow, nullable=False),
    Column("sample_size", Integer, default=0, nullable=False),
    Column("data_json", Text, nullable=False),
)


def init_db(db_path: Path | str) -> Engine:
    """Create engine, enable WAL + FK + busy_timeout, create schema if absent."""
    db_path = Path(db_path).resolve()    # absolute, avoids cwd surprises
    db_path.parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    with eng.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.exec_driver_sql("PRAGMA busy_timeout=5000")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    metadata.create_all(eng)
    # Also create generator-mode tables (separate MetaData object)
    from short_bot.generated_db import metadata as generator_metadata
    generator_metadata.create_all(eng)
    # Idempotent column-level migrations for tables that pre-date a feature.
    # create_all only creates missing tables, not missing columns.
    _migrate_add_columns(eng)
    return eng


def _migrate_add_columns(eng: Engine) -> None:
    """Add columns introduced in later versions to pre-existing production DBs.

    SQLite ALTER TABLE ADD COLUMN is non-locking and idempotent when guarded
    by a PRAGMA table_info check, so re-running init_db is safe.
    """
    migrations: list[tuple[str, str, str]] = [
        # (table, column, type)
        ("processed_items", "embedding_json", "TEXT"),
    ]
    with eng.begin() as conn:
        for table, col, coltype in migrations:
            existing = conn.exec_driver_sql(
                f"PRAGMA table_info({table})"
            ).fetchall()
            names = {row[1] for row in existing}
            if col not in names:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"
                )


def mark_processed(
    eng: Engine, guid: str, title: str, channel: str,
    *, embedding: list[float] | None = None,
) -> None:
    """Mark item as processed. embedding is optional; when provided it's
    stored as JSON and used by future fetch_recent_embeddings calls for
    topic-level dedup."""
    import json as _json
    with eng.begin() as conn:
        conn.execute(
            processed_items.insert().prefix_with("OR IGNORE"),
            {"guid": guid, "title": title, "channel": channel,
             "processed_at": _utcnow(),
             "embedding_json": _json.dumps(embedding) if embedding else None},
        )


def fetch_recent_embeddings(
    eng: Engine, channel: str, *, lookback_days: int = 7,
) -> list[list[float]]:
    """Return all non-null embedding vectors for `channel` processed in the
    last `lookback_days`. Rows with NULL embedding_json (pre-feature legacy
    or no API key at the time) are silently skipped."""
    import json as _json
    cutoff = _utcnow() - timedelta(days=lookback_days)
    with eng.connect() as conn:
        rows = conn.execute(
            select(processed_items.c.embedding_json)
            .where(processed_items.c.channel == channel)
            .where(processed_items.c.processed_at >= cutoff)
            .where(processed_items.c.embedding_json.is_not(None))
        ).fetchall()
    out: list[list[float]] = []
    for (raw,) in rows:
        if not raw:
            continue
        try:
            vec = _json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(vec, list) and vec:
            out.append(vec)
    return out


def is_processed(eng: Engine, guid: str, channel: str) -> bool:
    with eng.connect() as conn:
        row = conn.execute(
            select(processed_items.c.guid)
            .where(processed_items.c.guid == guid)
            .where(processed_items.c.channel == channel)
        ).fetchone()
    return row is not None


def similar_title_exists(
    eng: Engine,
    title: str,
    channel: str,
    threshold: float,
    *,
    lookback_days: int = 30,
) -> bool:
    """Fuzzy match against titles processed within lookback window (default 30 days)."""
    cutoff = _utcnow() - timedelta(days=lookback_days)
    with eng.connect() as conn:
        rows = conn.execute(
            select(processed_items.c.title)
            .where(processed_items.c.channel == channel)
            .where(processed_items.c.processed_at >= cutoff)
        ).fetchall()
    title_low = title.lower()
    for (existing,) in rows:
        if SequenceMatcher(None, title_low, existing.lower()).ratio() >= threshold:
            return True
    return False


def record_rss_item(
    eng: Engine, *, guid, channel, title, link, source,
    pub_date, thumb_url, score, status,
) -> int:
    with eng.begin() as conn:
        result = conn.execute(rss_items.insert().values(
            guid=guid, channel=channel, title=title, link=link,
            source=source, pub_date=pub_date, thumb_url=thumb_url,
            score=score, status=status, fetched_at=_utcnow(),
        ))
        return result.inserted_primary_key[0]


def record_short(
    eng: Engine, *, channel, rss_item_guid, title, file_path,
    duration_s, script_json, render_ms,
) -> int:
    with eng.begin() as conn:
        result = conn.execute(shorts.insert().values(
            channel=channel, rss_item_guid=rss_item_guid, title=title,
            file_path=file_path, duration_s=duration_s, script_json=script_json,
            render_ms=render_ms, created_at=_utcnow(),
        ))
        return result.inserted_primary_key[0]


def start_run(eng: Engine, channel: str, trigger: str, log_path: str) -> int:
    with eng.begin() as conn:
        result = conn.execute(runs.insert().values(
            channel=channel, trigger=trigger, status="running",
            started_at=_utcnow(), log_path=log_path,
        ))
        return result.inserted_primary_key[0]


def finish_run(
    eng: Engine, run_id: int, *,
    status: str, short_id: int | None = None, error: str | None = None,
) -> None:
    with eng.begin() as conn:
        conn.execute(runs.update().where(runs.c.id == run_id).values(
            ended_at=_utcnow(), status=status,
            short_id=short_id, error=error,
        ))


def cleanup_zombie_runs(
    eng: Engine, lock_dir: Path | None = None, *, age_minutes: int = 60,
) -> int:
    """Mark stale 'running' rows as failed and delete their lock files.

    A pipeline that died mid-run (process killed, OOM, panel restart) leaves
    runs.status='running' and a stranded data/locks/<slug>.lock file. New
    triggers then hit FileLock Timeout and the daemon thread swallows it.
    Run this on web app startup to self-heal.

    Uses SQLite's datetime() function for tolerant timestamp parsing — the
    runs.started_at column may contain either 'YYYY-MM-DD HH:MM:SS.ffffff'
    (SQLAlchemy default) or ISO 8601 with 'T'/tz suffix from older inserts.
    """
    from sqlalchemy import text
    with eng.begin() as conn:
        stale = list(conn.execute(text(
            "SELECT id, channel FROM runs "
            "WHERE status = 'running' "
            "AND datetime(started_at) < datetime('now', :delta)"
        ), {"delta": f"-{age_minutes} minutes"}))
        if not stale:
            return 0
        ids = [r.id for r in stale]
        placeholders = ",".join(f":id{i}" for i in range(len(ids)))
        params = {f"id{i}": v for i, v in enumerate(ids)}
        params["err"] = (
            f"zombie cleanup (stale >{age_minutes}min, process likely killed)"
        )
        conn.execute(text(
            "UPDATE runs SET ended_at = datetime('now'), status = 'failed', "
            f"error = :err WHERE id IN ({placeholders})"
        ), params)
    if lock_dir is not None:
        for r in stale:
            lock_path = Path(lock_dir) / f"{r.channel}.lock"
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass
    return len(stale)


def record_youtube_upload(
    eng: Engine, *, short_id: int, video_id: str | None,
    status: str, error: str | None, video_url: str | None,
) -> int:
    with eng.begin() as conn:
        result = conn.execute(youtube_uploads.insert().values(
            short_id=short_id, video_id=video_id, video_url=video_url,
            status=status, error=error, uploaded_at=_utcnow(),
        ))
        return result.inserted_primary_key[0]


def get_youtube_upload_for_short(eng: Engine, *, short_id: int):
    """Most recent upload row for a short, or None."""
    with eng.connect() as conn:
        return conn.execute(
            select(youtube_uploads)
            .where(youtube_uploads.c.short_id == short_id)
            .order_by(youtube_uploads.c.uploaded_at.desc())
            .limit(1)
        ).first()


def list_youtube_uploads_for_channel(eng: Engine, channel: str, *, limit: int = 20):
    """Recent uploads for a channel (joined via shorts.channel)."""
    with eng.connect() as conn:
        return list(conn.execute(
            select(youtube_uploads)
            .join(shorts, youtube_uploads.c.short_id == shorts.c.id)
            .where(shorts.c.channel == channel)
            .order_by(youtube_uploads.c.uploaded_at.desc())
            .limit(limit)
        ))


def get_rss_item_for_short(eng: Engine, *, short_id: int):
    """Return the rss_items row matching this short's rss_item_guid, or None.

    Generator-mode shorts have rss_item_guid=None and naturally return None.
    Used to surface source/link for YouTube descriptions.
    """
    with eng.connect() as conn:
        s = conn.execute(
            select(shorts.c.rss_item_guid, shorts.c.channel)
            .where(shorts.c.id == short_id)
        ).first()
        if s is None or s.rss_item_guid is None:
            return None
        return conn.execute(
            select(rss_items)
            .where(rss_items.c.guid == s.rss_item_guid)
            .where(rss_items.c.channel == s.channel)
            .limit(1)
        ).first()


def get_last_youtube_upload_at(eng: Engine):
    """Return the uploaded_at timestamp of the most recent successful upload
    across all channels, or None when no successes exist. Used for global
    cooldown / stagger between auto-uploads."""
    with eng.connect() as conn:
        row = conn.execute(
            select(youtube_uploads.c.uploaded_at)
            .where(youtube_uploads.c.status == "success")
            .order_by(youtube_uploads.c.uploaded_at.desc())
            .limit(1)
        ).first()
        return row[0] if row else None


def upsert_video_stats(eng: Engine, *, video_id: str, snapshot_date,
                       views: int, likes: int, comments: int,
                       watch_time_min: float, avg_view_duration_s: float) -> None:
    """UPSERT a video stats row keyed on (video_id, snapshot_date)."""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    iso = snapshot_date.isoformat()
    with eng.begin() as conn:
        stmt = sqlite_insert(youtube_video_stats).values(
            video_id=video_id, snapshot_date=iso,
            views=views, likes=likes, comments=comments,
            watch_time_min=watch_time_min,
            avg_view_duration_s=avg_view_duration_s,
            updated_at=_utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["video_id", "snapshot_date"],
            set_=dict(
                views=views, likes=likes, comments=comments,
                watch_time_min=watch_time_min,
                avg_view_duration_s=avg_view_duration_s,
                updated_at=_utcnow(),
            ),
        )
        conn.execute(stmt)


def get_video_stats_for_short(eng: Engine, *, short_id: int, days: int = 30):
    """Recent stats rows for the short's YouTube video, newest first."""
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    with eng.connect() as conn:
        upload = conn.execute(
            select(youtube_uploads.c.video_id)
            .where(youtube_uploads.c.short_id == short_id)
            .where(youtube_uploads.c.status == "success")
            .order_by(youtube_uploads.c.uploaded_at.desc())
            .limit(1)
        ).first()
        if upload is None or upload.video_id is None:
            return []
        return list(conn.execute(
            select(youtube_video_stats)
            .where(youtube_video_stats.c.video_id == upload.video_id)
            .where(youtube_video_stats.c.snapshot_date >= cutoff)
            .order_by(youtube_video_stats.c.snapshot_date.desc())
        ))


def upsert_channel_stats(eng: Engine, *, channel: str, snapshot_date,
                          subscribers: int, total_views: int) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    iso = snapshot_date.isoformat()
    with eng.begin() as conn:
        stmt = sqlite_insert(youtube_channel_stats).values(
            channel=channel, snapshot_date=iso,
            subscribers=subscribers, total_views=total_views,
            updated_at=_utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["channel", "snapshot_date"],
            set_=dict(subscribers=subscribers, total_views=total_views,
                      updated_at=_utcnow()),
        )
        conn.execute(stmt)


def get_channel_stats_history(eng: Engine, *, channel: str, days: int = 7):
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    with eng.connect() as conn:
        return list(conn.execute(
            select(youtube_channel_stats)
            .where(youtube_channel_stats.c.channel == channel)
            .where(youtube_channel_stats.c.snapshot_date >= cutoff)
            .order_by(youtube_channel_stats.c.snapshot_date.desc())
        ))


def incr_quota(eng: Engine, *, channel: str, units: int) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    today_iso = datetime.now(timezone.utc).date().isoformat()
    with eng.begin() as conn:
        stmt = sqlite_insert(youtube_quota).values(
            channel=channel, date=today_iso, units_used=units,
            updated_at=_utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["channel", "date"],
            set_=dict(
                units_used=youtube_quota.c.units_used + units,
                updated_at=_utcnow(),
            ),
        )
        conn.execute(stmt)


def get_quota_used_today(eng: Engine, *, channel: str) -> int:
    today_iso = datetime.now(timezone.utc).date().isoformat()
    with eng.connect() as conn:
        row = conn.execute(
            select(youtube_quota.c.units_used)
            .where(youtube_quota.c.channel == channel)
            .where(youtube_quota.c.date == today_iso)
        ).first()
        return int(row[0]) if row else 0


def count_uploads_for_channel(eng: Engine, channel: str) -> int:
    """Total successful YT uploads for a channel (joined via shorts.channel)."""
    from sqlalchemy import func
    with eng.connect() as conn:
        row = conn.execute(
            select(func.count())
            .select_from(youtube_uploads.join(shorts, youtube_uploads.c.short_id == shorts.c.id))
            .where(shorts.c.channel == channel)
            .where(youtube_uploads.c.status == "success")
        ).first()
        return int(row[0]) if row else 0


def last_upload_at_for_channel(eng: Engine, channel: str):
    """Most recent successful upload timestamp for a channel, or None."""
    with eng.connect() as conn:
        row = conn.execute(
            select(youtube_uploads.c.uploaded_at)
            .select_from(youtube_uploads.join(shorts, youtube_uploads.c.short_id == shorts.c.id))
            .where(shorts.c.channel == channel)
            .where(youtube_uploads.c.status == "success")
            .order_by(youtube_uploads.c.uploaded_at.desc())
            .limit(1)
        ).first()
        return row[0] if row else None


def upsert_channel_insights(eng: Engine, *, channel: str, sample_size: int,
                              data_json: str) -> None:
    """Persist computed insights for `channel`. Overwrites any prior row."""
    import json as _json
    with eng.begin() as conn:
        # SQLite-friendly upsert: try update first, insert if no row touched
        result = conn.execute(
            channel_insights.update()
            .where(channel_insights.c.channel == channel)
            .values(computed_at=_utcnow(), sample_size=sample_size,
                    data_json=data_json)
        )
        if result.rowcount == 0:
            conn.execute(channel_insights.insert().values(
                channel=channel, computed_at=_utcnow(),
                sample_size=sample_size, data_json=data_json,
            ))


def load_channel_insights(eng: Engine, channel: str) -> dict | None:
    """Return the cached insights dict for `channel`, or None when missing.

    Returned dict shape mirrors short_bot.learning.aggregator output plus a
    `_meta` wrapper with `computed_at` (ISO timestamp) and `sample_size`.
    """
    import json as _json
    with eng.connect() as conn:
        row = conn.execute(
            select(channel_insights).where(channel_insights.c.channel == channel)
        ).first()
    if row is None:
        return None
    try:
        data = _json.loads(row.data_json)
    except (ValueError, TypeError):
        return None
    data["_meta"] = {
        "computed_at": (row.computed_at.isoformat()
                         if row.computed_at else None),
        "sample_size": int(row.sample_size or 0),
    }
    return data


def load_channels_with_uploads(eng: Engine) -> list[str]:
    """Distinct channel slugs that have at least one successful YT upload.
    Used by the nightly insights aggregation cron to decide which channels
    need a refresh."""
    with eng.connect() as conn:
        rows = conn.execute(
            select(shorts.c.channel).distinct()
            .select_from(youtube_uploads.join(shorts, youtube_uploads.c.short_id == shorts.c.id))
            .where(youtube_uploads.c.status == "success")
        ).all()
    return [r[0] for r in rows]


def clear_recent_failed_runs(eng: Engine, *, hours: int = 24) -> int:
    """Delete 'failed' runs that started within the last `hours` hours.

    The dashboard surfaces these in its "Son 24 saat — N hata" panel; this
    helper backs the "Hataları temizle" button. Filesystem run logs are NOT
    touched — only the DB row that drives the panel. Returns deleted count.
    """
    from sqlalchemy import text
    with eng.begin() as conn:
        result = conn.execute(
            text("DELETE FROM runs WHERE status='failed' "
                 "AND datetime(started_at) > datetime('now', :delta)"),
            {"delta": f"-{hours} hours"}
        )
        return int(result.rowcount or 0)
