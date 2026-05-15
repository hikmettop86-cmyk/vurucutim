"""Channel edit page: trend_boost UI + form submission persistence."""
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
        "claude_models: {dna: opus, default: haiku}\n"
        "trends:\n  enabled: true\n  refresh_minutes: 60\n"
        "  default_sources: [google_daily, youtube]\n"
        "  cache_max_age_minutes: 90\n",
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
cta:
  enabled: false
  text: ''
  icons: []
  duration_s: 0
  show_handle: false
""", encoding="utf-8")
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=tmp_path / "data" / "secrets.yaml",
                      scheduler=False)


def _base_post() -> dict:
    return {
        "schedule_cron": "0 * * * *",
        "duration_s": "6", "min_score": "6.0",
        "max_candidates_per_run": "5",
        "handle": "@demo",
        "enabled": "1",
    }


# --- UI rendering ------------------------------------------------------------

def test_edit_page_shows_trend_boost_card(app):
    body = app.test_client().get("/channels/demo/edit").data.decode("utf-8")
    assert "Trend Boost" in body
    assert 'name="tb_enabled"' in body
    assert 'name="tb_max_boost"' in body
    assert 'name="tb_fuzzy_threshold"' in body
    assert 'name="tb_src_google_daily"' in body
    assert 'name="tb_src_youtube"' in body
    assert 'name="tb_exclude_terms"' in body
    assert 'name="tb_region_override"' in body


# --- Form submission ---------------------------------------------------------

def test_post_enables_trend_boost_writes_yaml(app, tmp_path):
    form = _base_post()
    form["tb_enabled"] = "1"
    form["tb_max_boost"] = "2.5"
    form["tb_min_term_length"] = "5"
    form["tb_fuzzy_threshold"] = "90"
    form["tb_src_google_daily"] = "1"
    form["tb_exclude_terms"] = "hava durumu, magazin"

    resp = app.test_client().post("/channels/demo/edit", data=form)
    assert resp.status_code in (200, 302)

    raw = yaml.safe_load(
        (tmp_path / "config" / "channels" / "demo.yaml").read_text(encoding="utf-8")
    )
    tb = raw["trend_boost"]
    assert tb["enabled"] is True
    assert tb["max_boost"] == 2.5
    assert tb["min_term_length"] == 5
    assert tb["fuzzy_threshold"] == 90
    assert tb["sources"] == ["google_daily"]
    assert tb["exclude_terms"] == ["hava durumu", "magazin"]


def test_post_no_sources_inherits_settings_default(app, tmp_path):
    """If neither source checkbox is set, the saved YAML should NOT contain
    a `sources` field (so settings.trends.default_sources is used at runtime)."""
    form = _base_post()
    form["tb_enabled"] = "1"
    form["tb_max_boost"] = "2.0"
    form["tb_fuzzy_threshold"] = "85"
    # no tb_src_* keys

    app.test_client().post("/channels/demo/edit", data=form)

    raw = yaml.safe_load(
        (tmp_path / "config" / "channels" / "demo.yaml").read_text(encoding="utf-8")
    )
    tb = raw["trend_boost"]
    assert tb["enabled"] is True
    assert "sources" not in tb  # None -> inherit


def test_post_region_override_uppercased(app, tmp_path):
    form = _base_post()
    form["tb_enabled"] = "1"
    form["tb_region_override"] = "gb"
    app.test_client().post("/channels/demo/edit", data=form)
    raw = yaml.safe_load(
        (tmp_path / "config" / "channels" / "demo.yaml").read_text(encoding="utf-8")
    )
    assert raw["trend_boost"]["region_override"] == "GB"


def test_post_disabled_persists_with_enabled_false(app, tmp_path):
    """Form rendered with no enabled box ticked -> enabled=false written."""
    form = _base_post()
    # tb_enabled NOT set, but other tb_* fields present -> form_present=True
    form["tb_max_boost"] = "1.5"
    app.test_client().post("/channels/demo/edit", data=form)
    raw = yaml.safe_load(
        (tmp_path / "config" / "channels" / "demo.yaml").read_text(encoding="utf-8")
    )
    assert raw["trend_boost"]["enabled"] is False
    assert raw["trend_boost"]["max_boost"] == 1.5


def test_post_round_trip_preserves_existing_trend_boost(app, tmp_path):
    """Pre-existing trend_boost in YAML + re-submit form -> values updated."""
    yaml_path = tmp_path / "config" / "channels" / "demo.yaml"
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    raw["trend_boost"] = {
        "enabled": True, "max_boost": 1.0, "min_term_length": 4,
        "fuzzy_threshold": 80, "sources": ["youtube"],
        "exclude_terms": ["old"],
    }
    yaml_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    form = _base_post()
    form["tb_enabled"] = "1"
    form["tb_max_boost"] = "3.0"
    form["tb_fuzzy_threshold"] = "92"
    form["tb_src_google_daily"] = "1"
    form["tb_exclude_terms"] = "yeni"

    app.test_client().post("/channels/demo/edit", data=form)

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    tb = raw["trend_boost"]
    assert tb["max_boost"] == 3.0
    assert tb["fuzzy_threshold"] == 92
    assert tb["sources"] == ["google_daily"]
    assert tb["exclude_terms"] == ["yeni"]
