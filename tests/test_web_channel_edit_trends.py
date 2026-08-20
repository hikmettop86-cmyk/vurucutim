"""Kanal düzenleme: content_source=trends + trends_region formdan YAML'a."""
from __future__ import annotations

import pytest
import yaml

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
name: Demo
keywords: [x]
language: tr
schedule_cron: 0 * * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors:
  primary: '#c81e1e'
  accent: '#ffea3b'
  bg_gradient: ['#000000', '#111111']
handle: '@demo'
output_dir: output/demo
enabled: true
""", encoding="utf-8")
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=tmp_path / "data" / "secrets.yaml",
                      scheduler=False)


def _base_post() -> dict:
    return {"schedule_cron": "0 * * * *", "duration_s": "6", "min_score": "6.0",
            "max_candidates_per_run": "5", "handle": "@demo", "enabled": "1"}


def _yaml(tmp_path):
    return yaml.safe_load(
        (tmp_path / "config" / "channels" / "demo.yaml").read_text(encoding="utf-8"))


def test_edit_page_offers_trends_source_and_region(app):
    body = app.test_client().get("/channels/demo/edit").data.decode("utf-8")
    assert 'name="content_source" value="trends"' in body
    assert 'name="trends_region"' in body
    assert 'value="DE"' in body


def test_post_trends_source_with_region_writes_yaml(app, tmp_path):
    form = _base_post()
    form["content_source"] = "trends"
    form["trends_region"] = "DE"
    resp = app.test_client().post("/channels/demo/edit", data=form)
    assert resp.status_code in (200, 302)
    raw = _yaml(tmp_path)
    assert raw["content_source"] == "trends"
    assert raw["trends_region"] == "DE"


def test_post_trends_source_with_empty_region_omits_field(app, tmp_path):
    form = _base_post()
    form["content_source"] = "trends"
    form["trends_region"] = ""
    app.test_client().post("/channels/demo/edit", data=form)
    raw = _yaml(tmp_path)
    assert raw["content_source"] == "trends"
    assert "trends_region" not in raw


def test_post_invalid_region_is_rejected_and_keeps_old(app, tmp_path):
    form = _base_post()
    form["content_source"] = "trends"
    form["trends_region"] = "Almanya"
    resp = app.test_client().post("/channels/demo/edit", data=form,
                                  follow_redirects=True)
    assert resp.status_code == 200
    raw = _yaml(tmp_path)
    assert raw.get("content_source", "rss") == "rss"   # kayıt yapılmadı


def test_post_rss_keeps_no_trends_region(app, tmp_path):
    form = _base_post()
    form["content_source"] = "rss"
    form["keywords"] = "x"
    form["trends_region"] = "DE"          # kaynak rss ise bölge yok sayılır
    app.test_client().post("/channels/demo/edit", data=form)
    raw = _yaml(tmp_path)
    assert "trends_region" not in raw
