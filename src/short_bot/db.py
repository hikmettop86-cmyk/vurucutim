"""SQLite via SQLAlchemy Core. Plain functions, no ORM session ceremony."""
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table,
    Text, create_engine, select, text,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

processed_items = Table(
    "processed_items", metadata,
    Column("guid", String, primary_key=True),
    Column("title", Text, nullable=False),
    Column("channel", String, nullable=False),
    Column("processed_at", DateTime, default=datetime.utcnow),
)

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
    Column("fetched_at", DateTime, default=datetime.utcnow),
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
    Column("created_at", DateTime, default=datetime.utcnow),
    Column("deleted_at", DateTime),
)

runs = Table(
    "runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False),
    Column("trigger", String, nullable=False),
    Column("started_at", DateTime, default=datetime.utcnow),
    Column("ended_at", DateTime),
    Column("status", String),
    Column("short_id", Integer, ForeignKey("shorts.id")),
    Column("error", Text),
    Column("log_path", Text),
)


def init_db(db_path: Path | str) -> Engine:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    metadata.create_all(eng)
    return eng


def mark_processed(eng: Engine, guid: str, title: str, channel: str) -> None:
    with eng.begin() as conn:
        conn.execute(processed_items.insert().prefix_with("OR IGNORE"),
                     {"guid": guid, "title": title, "channel": channel,
                      "processed_at": datetime.utcnow()})


def is_processed(eng: Engine, guid: str, channel: str) -> bool:
    with eng.connect() as conn:
        row = conn.execute(
            select(processed_items.c.guid)
            .where(processed_items.c.guid == guid)
            .where(processed_items.c.channel == channel)
        ).fetchone()
    return row is not None


def similar_title_exists(eng: Engine, title: str, channel: str, threshold: float) -> bool:
    with eng.connect() as conn:
        rows = conn.execute(
            select(processed_items.c.title).where(processed_items.c.channel == channel)
        ).fetchall()
    title_low = title.lower()
    for (existing,) in rows:
        if SequenceMatcher(None, title_low, existing.lower()).ratio() >= threshold:
            return True
    return False


def record_rss_item(eng: Engine, *, guid, channel, title, link, source,
                    pub_date, thumb_url, score, status) -> int:
    with eng.begin() as conn:
        result = conn.execute(rss_items.insert().values(
            guid=guid, channel=channel, title=title, link=link,
            source=source, pub_date=pub_date, thumb_url=thumb_url,
            score=score, status=status, fetched_at=datetime.utcnow(),
        ))
        return result.inserted_primary_key[0]


def record_short(eng: Engine, *, channel, rss_item_guid, title, file_path,
                 duration_s, script_json, render_ms) -> int:
    with eng.begin() as conn:
        result = conn.execute(shorts.insert().values(
            channel=channel, rss_item_guid=rss_item_guid, title=title,
            file_path=file_path, duration_s=duration_s, script_json=script_json,
            render_ms=render_ms, created_at=datetime.utcnow(),
        ))
        return result.inserted_primary_key[0]


def start_run(eng: Engine, channel: str, trigger: str, log_path: str) -> int:
    with eng.begin() as conn:
        result = conn.execute(runs.insert().values(
            channel=channel, trigger=trigger, status="running",
            started_at=datetime.utcnow(), log_path=log_path,
        ))
        return result.inserted_primary_key[0]


def finish_run(eng: Engine, run_id: int, *, status: str,
               short_id: int | None, error: str | None) -> None:
    with eng.begin() as conn:
        conn.execute(runs.update().where(runs.c.id == run_id).values(
            ended_at=datetime.utcnow(), status=status,
            short_id=short_id, error=error,
        ))
