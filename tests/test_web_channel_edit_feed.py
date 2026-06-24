from pathlib import Path
import pytest
from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg = tmp_path / "config"
    (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\n", encoding="utf-8")
    (cfg / "channels" / "feedch.yaml").write_text(
        "slug: feedch\nname: Feed Kanalı\nkeywords: [x]\n"
        "schedule_cron: '0 * * * *'\nduration_s: 6\nmin_score: 6\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#fff', accent: '#000', bg_gradient: ['#111','#222']}\n"
        "handle: '@f'\noutput_dir: out\n", encoding="utf-8")
    app = create_app(config_dir=cfg, db_path=tmp_path / "db.sqlite",
                     scheduler=False)
    app.config.update(TESTING=True)
    return app


def test_save_sets_feed_source_and_ids(app):
    from short_bot.db import init_db, add_feed
    eng = init_db(app.config["SHORTBOT_DB_PATH"])
    f1 = add_feed(eng, url="https://a.com/rss", title="A")
    f2 = add_feed(eng, url="https://b.com/rss", title="B")
    client = app.test_client()
    r = client.post("/channels/feedch/edit", data={
        "content_source": "feed",
        "auto_feed_ids": [str(f1), str(f2)],
        "schedule_cron": "0 */4 * * *", "duration_s": "6",
        "min_score": "6", "max_candidates_per_run": "10",
        "handle": "@f", "enabled": "1",
    }, follow_redirects=True)
    assert r.status_code == 200

    from short_bot.config import load_channel
    cfg = load_channel(app.config["SHORTBOT_CONFIG_DIR"] / "channels" / "feedch.yaml")
    assert cfg.content_source == "feed"
    assert set(cfg.auto_feed_ids) == {f1, f2}
