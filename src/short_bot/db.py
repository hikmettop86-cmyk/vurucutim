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
    return eng


def mark_processed(eng: Engine, guid: str, title: str, channel: str) -> None:
    with eng.begin() as conn:
        conn.execute(
            processed_items.insert().prefix_with("OR IGNORE"),
            {"guid": guid, "title": title, "channel": channel,
             "processed_at": _utcnow()},
        )


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
