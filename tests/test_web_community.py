"""/community/<slug> route tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from short_bot.community import CommunityDraft, _Drafts
from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: haiku, script: sonnet}\n",
        encoding="utf-8",
    )
    (cfg_dir / "channels" / "demo.yaml").write_text("""\
slug: demo
name: Demo Channel
keywords: [test]
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


def _drafts():
    return _Drafts(drafts=[
        CommunityDraft(format="poll", text="🏆 Test?",
                        options=["A", "B", "C"]),
        CommunityDraft(format="question", text="🦁 Tek kelimeyle ne?"),
        CommunityDraft(format="hot_take", text="💥 Provokatif düşünce"),
    ])


# --- GET /community/<slug> -------------------------------------------------

def test_view_404_for_unknown_channel(app):
    r = app.test_client().get("/community/nope")
    assert r.status_code == 404


def test_view_renders_empty_state(app):
    body = app.test_client().get("/community/demo").data.decode("utf-8")
    assert "Topluluk" in body or "Community" in body
    assert "Taslak üret" in body
    assert "Demo Channel" in body


# --- POST /community/<slug>/generate ---------------------------------------

def test_generate_renders_drafts(app):
    with patch("short_bot.web.routes.community.suggest_community_posts",
                return_value=_drafts().drafts):
        body = app.test_client().post(
            "/community/demo/generate", follow_redirects=True
        ).data.decode("utf-8")
    assert "Test?" in body
    assert "Tek kelimeyle ne" in body
    assert "Provokatif" in body
    # Format badges
    assert "POLL" in body
    assert "SORU" in body
    assert "HOT TAKE" in body


def test_generate_failure_flashes_error(app):
    from short_bot.claude_cli import ClaudeCliError
    with patch("short_bot.web.routes.community.suggest_community_posts",
                side_effect=ClaudeCliError("timeout")):
        r = app.test_client().post("/community/demo/generate",
                                     follow_redirects=True)
    body = r.data.decode("utf-8")
    assert "üretilemedi" in body.lower() or "hata" in body.lower()


def test_generate_passes_recent_titles_to_suggester(app, tmp_path):
    """Recent shorts should feed into the prompt builder."""
    from short_bot.db import init_db, record_short
    eng = init_db(tmp_path / "x.sqlite")
    record_short(eng, channel="demo", rss_item_guid="g1",
                  title="Bizim son short", file_path="o.mp4",
                  duration_s=6, script_json="{}", render_ms=1)

    captured = {}
    def fake_suggest(channel, *, recent_titles, trend_terms, **kw):
        captured["recent_titles"] = recent_titles
        return _drafts().drafts

    with patch("short_bot.web.routes.community.suggest_community_posts",
                side_effect=fake_suggest):
        app.test_client().post("/community/demo/generate")
    assert "Bizim son short" in captured["recent_titles"]


def test_generate_404_for_unknown_channel(app):
    r = app.test_client().post("/community/nope/generate")
    assert r.status_code == 404


def _openrouter_app(tmp_path):
    """App configured with ai_backend=openrouter + a secrets file holding a key."""
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: haiku, script: sonnet}\n"
        "ai_backend: openrouter\n"
        "openrouter_models: {dna: or-opus, default: or-default, script: or-script}\n",
        encoding="utf-8",
    )
    (cfg_dir / "channels" / "demo.yaml").write_text("""\
slug: demo
name: Demo Channel
keywords: [test]
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
    secrets_path = tmp_path / "data" / "secrets.yaml"
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text("openrouter_api_key: sk-or-test123\n", encoding="utf-8")
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=secrets_path, scheduler=False)


def test_generate_uses_openrouter_backend_when_configured(tmp_path):
    """ai_backend=openrouter → suggest_community_posts gets backend/api_key/model."""
    app = _openrouter_app(tmp_path)
    captured = {}

    def fake_suggest(channel, *, recent_titles, trend_terms, **kw):
        captured.update(kw)
        return _drafts().drafts

    with patch("short_bot.web.routes.community.suggest_community_posts",
                side_effect=fake_suggest):
        app.test_client().post("/community/demo/generate", follow_redirects=True)
    assert captured["backend"] == "openrouter"
    assert captured["api_key"] == "sk-or-test123"
    assert captured["model"] == "or-default"


# --- channel edit page link ------------------------------------------------

def test_channel_edit_includes_community_link(app):
    body = app.test_client().get("/channels/demo/edit").data.decode("utf-8")
    assert "/community/demo" in body
    assert "Topluluk" in body or "Post fikirleri" in body
