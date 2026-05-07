from datetime import datetime, timedelta, timezone
from pathlib import Path

from short_bot.db import (
    init_db, mark_processed, is_processed, similar_title_exists,
    record_rss_item, record_short, start_run, finish_run, cleanup_zombie_runs,
)


def test_init_creates_tables(tmp_path):
    db_path = tmp_path / "x.sqlite"
    eng = init_db(db_path)
    with eng.connect() as conn:
        from sqlalchemy import text
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        names = {r[0] for r in rows}
    assert {"processed_items", "rss_items", "shorts", "runs"} <= names


def test_mark_and_is_processed(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    assert not is_processed(eng, "g1", "ch")
    mark_processed(eng, "g1", "Title", "ch")
    assert is_processed(eng, "g1", "ch")
    assert not is_processed(eng, "g1", "other")


def test_similar_title_exists(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, "g1", "Merkez Bankası faizi indirdi", "ch")
    assert similar_title_exists(eng, "Merkez Bankası faizi 250 baz puan indirdi", "ch", threshold=0.7)
    assert not similar_title_exists(eng, "Tamamen alakasız bir başlık", "ch", threshold=0.85)


def test_run_lifecycle(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    run_id = start_run(eng, "ch", trigger="cli", log_path="logs/runs/1.log")
    assert run_id > 0
    finish_run(eng, run_id, status="success", short_id=None, error=None)
    from sqlalchemy import text
    with eng.connect() as conn:
        row = conn.execute(text("SELECT status, ended_at FROM runs WHERE id=:i"), {"i": run_id}).fetchone()
    assert row[0] == "success" and row[1] is not None


def test_record_short(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    sid = record_short(eng, channel="ch", rss_item_guid="g1", title="T",
                       file_path="output/ch/x.mp4", duration_s=30,
                       script_json='{"x":1}', render_ms=4200)
    assert sid > 0


def test_record_rss_item(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    rid = record_rss_item(eng, guid="g1", channel="ch", title="T", link="http://x",
                          source="S", pub_date=datetime.now(timezone.utc), thumb_url=None,
                          score=8.5, status="selected")
    assert rid > 0


def test_init_creates_indexes(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    with eng.connect() as conn:
        from sqlalchemy import text
        rows = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )).fetchall()
        names = {r[0] for r in rows}
    assert "idx_processed_channel_ts" in names
    assert "idx_shorts_channel_created" in names


def test_mark_processed_is_idempotent(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, "g1", "T", "ch")
    mark_processed(eng, "g1", "T2", "ch")  # second call should not raise
    with eng.connect() as conn:
        from sqlalchemy import text
        count = conn.execute(text(
            "SELECT COUNT(*) FROM processed_items WHERE guid='g1'"
        )).scalar()
    assert count == 1


def test_similar_title_skips_outside_lookback(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, "g_old", "Faiz indirimi", "ch")
    # Manually backdate the row 60 days
    from sqlalchemy import text
    with eng.begin() as conn:
        conn.execute(text(
            "UPDATE processed_items SET processed_at=:t WHERE guid='g_old'"
        ), {"t": datetime.now(timezone.utc) - timedelta(days=60)})
    # With default 30-day lookback, the old row should be ignored
    assert not similar_title_exists(eng, "Faiz indirimi 250 baz puan", "ch", threshold=0.5)
    # With explicit 90-day lookback, it should match
    assert similar_title_exists(eng, "Faiz indirimi 250 baz puan", "ch",
                                  threshold=0.5, lookback_days=90)


def _row_status(eng, run_id):
    from sqlalchemy import text
    with eng.connect() as conn:
        return conn.execute(
            text("SELECT status, error FROM runs WHERE id=:i"), {"i": run_id}
        ).fetchone()


def test_cleanup_zombie_runs_marks_stale_running_as_failed(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    from sqlalchemy import text
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO runs (channel, trigger, status, started_at, log_path) "
            "VALUES ('ch', 'cron', 'running', :ts, 'l')"
        ), {"ts": old})
    fresh_id = start_run(eng, "ch", trigger="manual", log_path="l")

    n = cleanup_zombie_runs(eng, lock_dir=None, age_minutes=60)
    assert n == 1

    rows = list(eng.connect().execute(text(
        "SELECT id, status, error, ended_at FROM runs ORDER BY id"
    )))
    old_row = rows[0]
    assert old_row.status == "failed"
    assert "zombie" in (old_row.error or "")
    assert old_row.ended_at is not None
    assert _row_status(eng, fresh_id).status == "running"


def test_cleanup_zombie_runs_no_op_when_clean(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    start_run(eng, "ch", trigger="cli", log_path="l")
    assert cleanup_zombie_runs(eng, lock_dir=None, age_minutes=60) == 0


def test_cleanup_zombie_runs_removes_lock_files(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    (lock_dir / "ch.lock").write_text("")
    (lock_dir / "other.lock").write_text("")

    from sqlalchemy import text
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO runs (channel, trigger, status, started_at, log_path) "
            "VALUES ('ch', 'cron', 'running', :ts, 'l')"
        ), {"ts": old})

    cleanup_zombie_runs(eng, lock_dir=lock_dir, age_minutes=60)
    assert not (lock_dir / "ch.lock").exists()
    assert (lock_dir / "other.lock").exists()


def test_cleanup_zombie_runs_handles_missing_lock_gracefully(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()

    from sqlalchemy import text
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO runs (channel, trigger, status, started_at, log_path) "
            "VALUES ('ch', 'cron', 'running', :ts, 'l')"
        ), {"ts": old})

    n = cleanup_zombie_runs(eng, lock_dir=lock_dir, age_minutes=60)
    assert n == 1

