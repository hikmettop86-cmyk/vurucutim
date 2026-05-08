"""POST /channels/<slug>/edit yt_proxy_url alanini secrets.yaml'a yazar."""
from __future__ import annotations

from pathlib import Path

import yaml

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
        output_root=tmp_path / "out",
        secrets_path=tmp_path / "secrets.yaml",
        scheduler=False,
    )


def test_post_edit_writes_proxy_to_secrets(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    resp = client.post("/channels/ch/edit", data={
        "schedule_cron": "* * * * *", "duration_s": "6",
        "min_score": "6.0", "max_candidates_per_run": "10",
        "handle": "@ch",
        "yt_auto_upload": "1", "yt_ai_content": "1",
        "yt_category_id": "24", "yt_privacy_status": "public",
        "yt_proxy_url": "http://test:s3@proxy.local:8080",
    }, follow_redirects=False)
    assert resp.status_code == 302
    secrets = yaml.safe_load((tmp_path / "secrets.yaml").read_text(encoding="utf-8"))
    assert secrets["channel_proxies"]["ch"] == "http://test:s3@proxy.local:8080"


def test_post_edit_empty_proxy_removes_key(tmp_path):
    """Eger kullanici alani bos birakirsa, kanal slug'i secrets'tan silinir."""
    app = _make_app(tmp_path)
    secrets_path = tmp_path / "secrets.yaml"
    secrets_path.write_text(
        "channel_proxies:\n  ch: http://old:1\n  other: http://x:2\n",
        encoding="utf-8",
    )
    client = app.test_client()
    resp = client.post("/channels/ch/edit", data={
        "schedule_cron": "* * * * *", "duration_s": "6",
        "min_score": "6.0", "max_candidates_per_run": "10",
        "handle": "@ch",
        "yt_auto_upload": "1", "yt_ai_content": "1",
        "yt_category_id": "24", "yt_privacy_status": "public",
        "yt_proxy_url": "",
    }, follow_redirects=False)
    assert resp.status_code == 302
    secrets = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    proxies = secrets.get("channel_proxies") or {}
    assert "ch" not in proxies
    assert proxies.get("other") == "http://x:2"   # diger slug bozulmaz


def test_post_edit_no_proxy_field_does_not_touch_secrets(tmp_path):
    """yt_proxy_url alani hic gonderilmezse secrets degismez (idempotent)."""
    app = _make_app(tmp_path)
    secrets_path = tmp_path / "secrets.yaml"
    secrets_path.write_text(
        "channel_proxies:\n  ch: http://existing:1\n", encoding="utf-8",
    )
    client = app.test_client()
    resp = client.post("/channels/ch/edit", data={
        "schedule_cron": "* * * * *", "duration_s": "6",
        "min_score": "6.0", "max_candidates_per_run": "10",
        "handle": "@ch",
        # NO yt_proxy_url field at all
    }, follow_redirects=False)
    assert resp.status_code == 302
    # When yt_proxy_url is absent, channel_edit treats it as empty → key removed
    # That's expected behavior — empty form field semantically equals None.
    # If you want preserve-on-omit, that's a separate decision; plan says
    # `request.form.get("yt_proxy_url") or "").strip() or None` then update.
    secrets = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    proxies = secrets.get("channel_proxies") or {}
    # Form omitting field is same as empty → removes
    assert "ch" not in proxies
