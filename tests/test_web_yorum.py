"""Gündem Yorum UI: kurulum sihirbazı, düzenleme sayfası, liste rozeti/yönlendirme."""
from __future__ import annotations

import pytest
import yaml

from short_bot.web import create_app

_SETTINGS = ("ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
             "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
             "claude_models: {dna: opus, default: haiku}\n")

_CARD = """\
slug: kart
name: Kart
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
handle: '@kart'
output_dir: output/kart
enabled: true
"""

_YORUM = """\
slug: yorum
name: Yorum
keywords: []
language: tr
content_source: trends
trends_region: TR
trends_min_volume: 5000
schedule_cron: 30 8-20/3 * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 25
template: flas
colors:
  primary: '#d0021b'
  accent: '#ffe600'
  bg_gradient: ['#3a3a3a', '#141414']
handle: '@yorum'
output_dir: output/yorum
enabled: true
voice:
  enabled: true
  provider: cartesia
  voice_id: c1cf
  speed: 1.05
  persona: p
  target_duration_s: [35, 50]
  music_volume: 0.05
"""


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(_SETTINGS, encoding="utf-8")
    (cfg_dir / "channels" / "kart.yaml").write_text(_CARD, encoding="utf-8")
    (cfg_dir / "channels" / "yorum.yaml").write_text(_YORUM, encoding="utf-8")
    (tmp_path / "data").mkdir()
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=tmp_path / "data" / "secrets.yaml", scheduler=False)


def _yaml(tmp_path, slug):
    return yaml.safe_load((tmp_path / "config" / "channels" / f"{slug}.yaml").read_text(encoding="utf-8"))


def test_list_has_button_badge_and_format_links(app):
    body = app.test_client().get("/channels").data.decode("utf-8")
    assert 'href="/channels/new-yorum"' in body
    assert "YORUM" in body
    assert 'href="/channels/yorum/edit-yorum"' in body
    assert 'href="/channels/kart/edit"' in body


def test_new_form_renders_with_defaults(app):
    body = app.test_client().get("/channels/new-yorum").data.decode("utf-8")
    for needle in ('name="name"', 'name="trends_region"', 'name="runs_per_day"', 'name="voice_persona"',
                   "kimsenin adamı olmayan", 'name="voice_provider"', 'id="btn-cartesia-voices"',
                   'name="trends_min_volume"'):
        assert needle in body, needle


def test_new_create_writes_channel_yaml(app, tmp_path):
    form = {"name": "Gündem Yorum", "language": "tr", "trends_region": "TR", "trends_min_volume": "5000",
            "runs_per_day": "5", "voice_provider": "cartesia", "voice_id": "c1cf", "voice_speed": "1.05",
            "voice_model": "sonic-3.5", "voice_volume": "1.0", "voice_emotion": "",
            "voice_target_min": "35", "voice_target_max": "50", "voice_music_volume": "0.05",
            "script_model": "opus", "handle": "@gundem"}
    r = app.test_client().post("/channels/new-yorum", data=form)
    assert r.status_code == 302 and r.headers["Location"].endswith("/channels/gundem-yorum/edit-yorum")
    raw = _yaml(tmp_path, "gundem-yorum")
    assert raw["content_source"] == "trends" and raw["trends_region"] == "TR"
    assert raw["trends_min_volume"] == 5000 and raw["schedule_cron"] == "30 8-20/3 * * *"
    assert raw["template"] == "flas" and raw["script_model"] == "opus"
    assert raw["voice"]["provider"] == "cartesia" and raw["voice"]["enabled"] is True
    assert raw["voice"]["target_duration_s"] == [35, 50] and raw["voice"]["music_volume"] == 0.05
    assert "kimsenin adamı olmayan" in raw["voice"]["persona"]
    assert raw["youtube"]["auto_upload"] is False


def test_new_create_requires_voice(app, tmp_path):
    r = app.test_client().post("/channels/new-yorum", data={"name": "X", "voice_id": ""}, follow_redirects=True)
    assert r.status_code == 200
    assert not (tmp_path / "config" / "channels" / "x.yaml").exists()


def test_edit_page_shows_format_fields_only(app):
    body = app.test_client().get("/channels/yorum/edit-yorum").data.decode("utf-8")
    for needle in ('name="trends_region"', 'name="runs_per_day"', 'name="voice_persona"',
                   'name="voice_id"', "Şimdi üret", "compile-day", "Son üretimler"):
        assert needle in body, needle
    assert 'name="dna_bg_grad_1"' not in body and "Overflow" not in body


def test_edit_redirects_non_yorum_channel(app):
    r = app.test_client().get("/channels/kart/edit-yorum")
    assert r.status_code == 302 and r.headers["Location"].endswith("/channels/kart/edit")


def test_edit_post_updates_fields(app, tmp_path):
    form = {"name": "Yorum 2", "handle": "@y2", "trends_region": "DE", "trends_min_volume": "8000",
            "runs_per_day": "3", "min_score": "7.0", "enabled": "1", "auto_upload": "on",
            "voice_provider": "cartesia", "voice_id": "c1cf", "voice_speed": "1.1", "voice_persona": "yeni p",
            "voice_target_min": "30", "voice_target_max": "45", "voice_music_volume": "0.08",
            "voice_model": "sonic-preview", "voice_volume": "1.2", "voice_emotion": "[sakin]",
            "script_model": "sonnet"}
    r = app.test_client().post("/channels/yorum/edit-yorum", data=form)
    assert r.status_code == 302
    raw = _yaml(tmp_path, "yorum")
    assert raw["name"] == "Yorum 2" and raw["handle"] == "@y2"
    assert raw["trends_region"] == "DE" and raw["trends_min_volume"] == 8000
    assert raw["schedule_cron"] == "30 9,14,19 * * *" and raw["min_score"] == 7.0
    assert raw["youtube"]["auto_upload"] is True and raw["script_model"] == "sonnet"
    v = raw["voice"]
    assert v["persona"] == "yeni p" and v["target_duration_s"] == [30, 45] and v["speed"] == 1.1
    assert v["model"] == "sonic-preview" and v["volume"] == 1.2 and v["emotion"] == "[sakin]"


def test_edit_post_invalid_speed_is_rejected(app, tmp_path):
    r = app.test_client().post("/channels/yorum/edit-yorum",
                               data={"voice_speed": "0.5", "voice_id": "c1cf"}, follow_redirects=True)
    assert r.status_code == 200
    assert _yaml(tmp_path, "yorum")["voice"]["speed"] == 1.05
