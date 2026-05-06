import json
from datetime import date, timedelta
from short_bot.web import create_app


def _make_app(tmp_path, with_channel=True, with_creds=True, with_history=False):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n",
        encoding="utf-8",
    )
    if with_channel:
        (cfg_dir / "channels" / "ch.yaml").write_text(
            "slug: ch\nname: My Channel\nkeywords: [a]\nlanguage: tr\n"
            "schedule_cron: '* * * * *'\nduration_s: 6\nmin_score: 6.0\n"
            "max_candidates_per_run: 10\ntemplate: newscast\n"
            "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}\n"
            "handle: '@ch'\noutput_dir: out\nenabled: true\n"
            "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
            encoding="utf-8",
        )
    app = create_app(
        config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
        templates_dir=tmp_path / "templates",
        music_root=tmp_path / "music", cache_dir=tmp_path / "cache",
        lock_dir=tmp_path / "locks", logs_dir=tmp_path / "logs",
        output_root=tmp_path / "out", scheduler=False,
    )
    if with_creds:
        yt_root = tmp_path / "yt_creds" / "ch"; yt_root.mkdir(parents=True)
        (yt_root / "token.json").write_text("{}")
        (yt_root / "channel_info.json").write_text(json.dumps({
            "id": "UC1",
            "snippet": {"title": "My Cool Channel", "customUrl": "@mychan",
                         "description": "A great channel about stuff."},
            "statistics": {"subscriberCount": "0", "videoCount": "42"},
        }))
        app.config["SHORTBOT_YT_CREDS_DIR"] = tmp_path / "yt_creds"
    if with_history:
        from short_bot.db import init_db, upsert_channel_stats
        eng = init_db(tmp_path / "x.sqlite")
        today = date.today()
        upsert_channel_stats(eng, channel="ch",
                              snapshot_date=today - timedelta(days=8),
                              subscribers=100, total_views=10000)
        upsert_channel_stats(eng, channel="ch", snapshot_date=today,
                              subscribers=150, total_views=15000)
    return app


def test_overview_renders_video_count_from_channel_info(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    body = client.get("/youtube").data.decode("utf-8")
    assert "42" in body  # videoCount


def test_overview_renders_handle_and_description(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    body = client.get("/youtube").data.decode("utf-8")
    assert "@mychan" in body or "mychan" in body
    assert "great channel" in body


def test_overview_renders_7day_deltas(tmp_path):
    app = _make_app(tmp_path, with_history=True)
    client = app.test_client()
    body = client.get("/youtube").data.decode("utf-8")
    # +50 subs delta, +5000 views delta — at least the +50 number visible
    assert "50" in body


def test_overview_skips_unconnected_channels(tmp_path):
    app = _make_app(tmp_path, with_creds=False)
    client = app.test_client()
    body = client.get("/youtube").data.decode("utf-8")
    # Empty state copy
    assert "henüz" in body.lower() or "bağlı" in body.lower()
