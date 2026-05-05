import pytest
from datetime import datetime

from short_bot.db import init_db, record_rss_item
from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: haiku\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "x.sqlite"
    eng = init_db(db_path)
    record_rss_item(eng, guid="g1", channel="ch", title="Big news", link="http://x",
                    source="Reuters", pub_date=datetime.utcnow(), thumb_url=None,
                    score=8.5, status="selected")
    record_rss_item(eng, guid="g2", channel="ch", title="Smaller news", link="http://y",
                    source="AA", pub_date=datetime.utcnow(), thumb_url=None,
                    score=5.0, status="below_threshold")
    return create_app(config_dir=cfg_dir, db_path=db_path, scheduler=False)


def test_rss_page_lists_items(app):
    client = app.test_client()
    resp = client.get("/rss")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Big news" in body
    assert "Smaller news" in body
    assert "8.5" in body
    assert "selected" in body or "SEÇİLDİ" in body
