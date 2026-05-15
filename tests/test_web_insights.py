"""/insights/<slug> view + index + refresh endpoints."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from short_bot.db import (init_db, record_short, record_youtube_upload,
                          upsert_video_stats)
from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8",
    )
    (cfg_dir / "channels" / "demo.yaml").write_text("""\
slug: demo
name: Demo Channel
keywords: [x]
language: tr
schedule_cron: 0 * * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors: {primary: '#fff', accent: '#fff', bg_gradient: ['#000', '#111']}
handle: '@demo'
output_dir: output/demo
enabled: true
cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}
""", encoding="utf-8")
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=tmp_path / "data" / "secrets.yaml",
                      scheduler=False)


def _seed_some_uploads(eng):
    """Create 3 demo shorts with stats."""
    for i, (title, cat, mood, views) in enumerate([
        ("Top Story", "Dünya", "breaking", 5000),
        ("Mid Story", "Dünya", "breaking", 1500),
        ("Watch Champ", "Gündem", "breaking", 800),
    ]):
        sid = record_short(
            eng, channel="demo", rss_item_guid=f"g{i}",
            title=title, file_path="out.mp4", duration_s=6,
            script_json=json.dumps({
                "header_top": title.split()[0], "header_bottom": "X",
                "photo_overlay": "y", "body_paragraph": "body",
                "highlights": [], "category": cat, "mood": mood,
            }),
            render_ms=100,
        )
        vid = f"V{i}"
        record_youtube_upload(eng, short_id=sid, video_id=vid,
                              status="success", error=None,
                              video_url=f"https://youtu.be/{vid}")
        avg = 12.0 if title == "Watch Champ" else 3.0
        upsert_video_stats(
            eng, video_id=vid, snapshot_date=date.today(),
            views=views, likes=10, comments=2,
            watch_time_min=(views * avg) / 60, avg_view_duration_s=avg,
        )


# --- /insights index --------------------------------------------------------

def test_index_page_lists_channels(app):
    body = app.test_client().get("/insights").data.decode("utf-8")
    assert "İçgörüler" in body
    assert "Demo Channel" in body


def test_index_marks_channel_without_uploads(app):
    body = app.test_client().get("/insights").data.decode("utf-8")
    # No uploads yet -> channel listed but the connected badge is absent
    assert "Demo Channel" in body
    # The green "bağlı" badge has a specific CSS class — column header has
    # different classes. Look for the badge specifically:
    assert "bg-green-100 text-green-800" not in body


def test_index_shows_connected_badge_after_upload(app, tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _seed_some_uploads(eng)
    body = app.test_client().get("/insights").data.decode("utf-8")
    # Once uploads exist, the green badge appears
    assert "bg-green-100 text-green-800" in body


# --- /insights/<slug> view --------------------------------------------------

def test_channel_view_404_for_unknown(app):
    r = app.test_client().get("/insights/nonexistent")
    assert r.status_code == 404


def test_channel_view_renders_with_zero_data(app):
    """No uploads → page still renders with a 'no stats' warning."""
    body = app.test_client().get("/insights/demo").data.decode("utf-8")
    assert "Demo Channel" in body
    assert "Analytics" in body or "stats" in body.lower()


def test_channel_view_shows_top_examples_when_data_exists(app, tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _seed_some_uploads(eng)
    body = app.test_client().get("/insights/demo").data.decode("utf-8")
    assert "Top Story" in body
    assert "5000" in body
    assert "Watch Champ" in body  # appears in watch_pct_leaders (12s avg vs 6s duration)


def test_channel_view_watch_pct_leaders_show_200(app, tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _seed_some_uploads(eng)
    body = app.test_client().get("/insights/demo").data.decode("utf-8")
    # Watch Champ has 12s avg dur on 6s short → 200%
    assert "200%" in body


# --- POST /insights/<slug>/refresh ------------------------------------------

def test_refresh_recomputes_and_redirects(app, tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _seed_some_uploads(eng)
    r = app.test_client().post("/insights/demo/refresh", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/insights/demo")


def test_refresh_404_for_unknown_channel(app):
    r = app.test_client().post("/insights/nope/refresh")
    assert r.status_code == 404


# --- nav link ---------------------------------------------------------------

def test_nav_includes_insights_link(app):
    body = app.test_client().get("/").data.decode("utf-8")
    assert "/insights" in body
    assert "İçgörüler" in body
