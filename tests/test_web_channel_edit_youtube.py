from pathlib import Path

from short_bot.web import create_app


def _make_app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n",
        encoding="utf-8",
    )
    (cfg_dir / "channels" / "ch.yaml").write_text(
        "slug: ch\nname: C\nkeywords: [a]\nlanguage: tr\n"
        "schedule_cron: '* * * * *'\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}\n"
        "handle: '@ch'\noutput_dir: out\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    return create_app(
        config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
        templates_dir=tmp_path / "templates",
        music_root=tmp_path / "music", cache_dir=tmp_path / "cache",
        lock_dir=tmp_path / "locks", logs_dir=tmp_path / "logs",
        output_root=tmp_path / "out", scheduler=False,
    )


def test_post_persists_youtube_block(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    resp = client.post("/channels/ch/edit", data={
        "schedule_cron": "* * * * *", "duration_s": "6",
        "min_score": "6.0", "max_candidates_per_run": "10",
        "handle": "@ch",
        "yt_auto_upload": "1", "yt_ai_content": "1",
        "yt_category_id": "28", "yt_privacy_status": "unlisted",
    }, follow_redirects=False)
    assert resp.status_code == 302
    from short_bot.config import load_channel
    cfg = load_channel(tmp_path / "config" / "channels" / "ch.yaml")
    assert cfg.youtube is not None
    assert cfg.youtube.auto_upload is True
    assert cfg.youtube.category_id == "28"
    assert cfg.youtube.privacy_status == "unlisted"


def test_post_persists_min_score_and_cron_preset(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    resp = client.post("/channels/ch/edit", data={
        "schedule_cron": "0 9 * * *", "duration_s": "6",
        "min_score": "6.0", "max_candidates_per_run": "10",
        "handle": "@ch",
        "yt_auto_upload": "1", "yt_ai_content": "1",
        "yt_category_id": "24", "yt_privacy_status": "public",
        "yt_min_score_for_upload": "8.5",
        "yt_cron_preset": "daily_09",
    }, follow_redirects=False)
    assert resp.status_code == 302
    from short_bot.config import load_channel
    cfg = load_channel(tmp_path / "config" / "channels" / "ch.yaml")
    assert cfg.youtube.min_score_for_upload == 8.5
    assert cfg.youtube.cron_preset == "daily_09"
    assert cfg.schedule_cron == "0 9 * * *"
