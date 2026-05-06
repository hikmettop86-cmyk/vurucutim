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
    return create_app(
        config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
        templates_dir=tmp_path / "templates",
        music_root=tmp_path / "music", cache_dir=tmp_path / "cache",
        lock_dir=tmp_path / "locks", logs_dir=tmp_path / "logs",
        output_root=tmp_path / "out", scheduler=False,
    )


def test_youtube_overview_renders_200_when_no_channels(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    r = client.get("/youtube")
    assert r.status_code == 200


def test_youtube_overview_lists_connected_channels(tmp_path):
    app = _make_app(tmp_path)
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels" / "ch.yaml").write_text(
        "slug: ch\nname: My Channel\nkeywords: [a]\nlanguage: tr\n"
        "schedule_cron: '* * * * *'\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}\n"
        "handle: '@ch'\noutput_dir: out\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    yt_root = tmp_path / "yt_creds" / "ch"
    yt_root.mkdir(parents=True)
    (yt_root / "token.json").write_text("{}")
    import json as _json
    (yt_root / "channel_info.json").write_text(_json.dumps({
        "id": "UC1",
        "snippet": {"title": "My Channel"},
        "statistics": {"subscriberCount": "0", "videoCount": "0"},
    }))
    app.config["SHORTBOT_YT_CREDS_DIR"] = tmp_path / "yt_creds"
    client = app.test_client()
    r = client.get("/youtube")
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="ignore")
    assert "My Channel" in body
    assert "ch" in body


def test_youtube_overview_shows_empty_state_when_no_connections(tmp_path):
    app = _make_app(tmp_path)
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels" / "ch.yaml").write_text(
        "slug: ch\nname: C\nkeywords: [a]\nlanguage: tr\n"
        "schedule_cron: '* * * * *'\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}\n"
        "handle: '@ch'\noutput_dir: out\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    client = app.test_client()
    r = client.get("/youtube")
    body = r.data.decode("utf-8", errors="ignore")
    assert r.status_code == 200
    # Empty-state hint
    assert "henüz" in body.lower() or "bağlı" in body.lower() or "no channels" in body.lower()


def test_dashboard_no_longer_shows_youtube_grid(tmp_path):
    """Regression: dashboard.html.j2 must NOT include the YouTube Kanalları grid header."""
    app = _make_app(tmp_path)
    client = app.test_client()
    r = client.get("/")
    body = r.data.decode("utf-8", errors="ignore")
    assert "YouTube Kanalları" not in body
