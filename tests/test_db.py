from datetime import datetime
from pathlib import Path

from short_bot.db import (
    init_db, mark_processed, is_processed, similar_title_exists,
    record_rss_item, record_short, start_run, finish_run,
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
                          source="S", pub_date=datetime.utcnow(), thumb_url=None,
                          score=8.5, status="selected")
    assert rid > 0
