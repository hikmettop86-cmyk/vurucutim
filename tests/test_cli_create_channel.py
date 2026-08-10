import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from short_bot.cli import _cmd_create_channel, _cmd_regenerate_dna, _cmd_rebuild_css, _cmd_migrate_channel
from short_bot.dna import DnaSpec, DnaPalette, DnaFonts, DnaTone


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config" / "channels").mkdir(parents=True)
    (tmp_path / "templates" / "css").mkdir(parents=True)
    (tmp_path / "config" / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5000}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: haiku\n",
        encoding="utf-8",
    )
    return tmp_path


def _fake_dna(archetype="newscast"):
    return DnaSpec(
        archetype=archetype,
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b","#0a1a3b"],
                           body_bg=["#1a1a2a","#0a0a1a"]),
        fonts=DnaFonts(headline="Inter", body="Inter"),
        tone=DnaTone(voice="x", style="y"),
        category_icon="📰",
        persona_summary="z",
    )


def test_create_channel_writes_yaml_and_css(cli_env):
    fake = _fake_dna(archetype="newscast")
    args = type("Args", (), {
        "name": "Test Kanal", "language": "tr",
        "keywords": "a,b,c", "topic_hint": "", "target_audience": "",
        "config_dir": "config", "templates_dir": "templates",
        "force": False,
    })()
    with patch("short_bot.cli.generate_dna", return_value=fake):
        rc = _cmd_create_channel(args)
    assert rc == 0
    yaml_path = cli_env / "config" / "channels" / "test-kanal.yaml"
    css_path = cli_env / "templates" / "css" / "test-kanal.css"
    assert yaml_path.exists()
    assert css_path.exists()
    txt = yaml_path.read_text(encoding="utf-8")
    assert "language: tr" in txt
    assert "Test Kanal" in txt
    css = css_path.read_text(encoding="utf-8")
    assert "--primary: #c81e1e" in css


def test_create_channel_existing_slug_without_force_returns_error(cli_env):
    yaml_path = cli_env / "config" / "channels" / "existing.yaml"
    yaml_path.write_text("slug: existing\n", encoding="utf-8")
    args = type("Args", (), {
        "name": "Existing", "language": "tr", "keywords": "a",
        "topic_hint": "", "target_audience": "",
        "config_dir": "config", "templates_dir": "templates", "force": False,
    })()
    with patch("short_bot.cli.generate_dna", return_value=_fake_dna()):
        rc = _cmd_create_channel(args)
    assert rc != 0


def test_create_channel_invalid_language_returns_error(cli_env):
    args = type("Args", (), {
        "name": "X", "language": "xx", "keywords": "a",
        "topic_hint": "", "target_audience": "",
        "config_dir": "config", "templates_dir": "templates", "force": False,
    })()
    rc = _cmd_create_channel(args)
    assert rc != 0


def _write_channel_yaml(cli_env, slug="test-kanal"):
    """Write a minimal valid channel YAML for tests that need an existing channel."""
    yaml_content = f"""\
slug: {slug}
name: Test Kanal
keywords: [a, b, c]
language: tr
schedule_cron: "0 8,14,20 * * *"
duration_s: 6
min_score: 6.0
max_candidates_per_run: 10
template: newscast
colors:
  primary: "#c81e1e"
  accent: "#ffea3b"
  bg_gradient: ["#1a3b6b", "#0a1a3b"]
handle: "@test-kanal"
output_dir: output/{slug}
enabled: true
cta:
  enabled: false
  text: ""
  icons: []
  duration_s: 0
  show_handle: false
"""
    yaml_path = cli_env / "config" / "channels" / f"{slug}.yaml"
    yaml_path.write_text(yaml_content, encoding="utf-8")
    return yaml_path


def test_regenerate_dna_overwrites_yaml_and_css(cli_env):
    """regenerate-dna should call generate_dna, update YAML and write CSS."""
    slug = "test-kanal"
    yaml_path = _write_channel_yaml(cli_env, slug)
    css_dir = cli_env / "templates" / "css"

    fake = _fake_dna(archetype="newscast")
    args = type("Args", (), {
        "channel": slug,
        "config_dir": "config",
        "templates_dir": "templates",
        "topic_hint": "",
        "target_audience": "",
    })()
    with patch("short_bot.cli.generate_dna", return_value=fake) as mock_gen:
        rc = _cmd_regenerate_dna(args)

    assert rc == 0
    mock_gen.assert_called_once()
    css_path = css_dir / f"{slug}.css"
    assert css_path.exists()
    assert "--primary: #c81e1e" in css_path.read_text(encoding="utf-8")
    updated_yaml = yaml_path.read_text(encoding="utf-8")
    assert "dna:" in updated_yaml


def test_rebuild_css_no_llm_call(cli_env):
    """rebuild-css must NOT call generate_dna; it only builds CSS from existing dna in YAML."""
    import yaml as _yaml

    slug = "test-kanal"
    yaml_path = _write_channel_yaml(cli_env, slug)

    # Add dna block directly to YAML
    fake = _fake_dna(archetype="newscast")
    data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    data["dna"] = fake.model_dump(mode="json")
    yaml_path.write_text(
        _yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )

    args = type("Args", (), {
        "channel": slug,
        "config_dir": "config",
        "templates_dir": "templates",
    })()
    with patch("short_bot.cli.generate_dna") as mock_gen:
        rc = _cmd_rebuild_css(args)

    assert rc == 0
    mock_gen.assert_not_called()
    css_path = cli_env / "templates" / "css" / f"{slug}.css"
    assert css_path.exists()
    assert "--primary: #c81e1e" in css_path.read_text(encoding="utf-8")


def test_migrate_channel_adds_language_field(cli_env):
    """migrate-channel (without --with-dna) should save YAML with language field, no LLM."""
    slug = "legacy-kanal"

    # Write a legacy-style YAML without 'language' field
    legacy_yaml = """\
slug: legacy-kanal
name: Legacy Kanal
keywords: [x, y]
schedule_cron: "0 8 * * *"
duration_s: 6
min_score: 6.0
max_candidates_per_run: 10
template: default
colors:
  primary: "#c81e1e"
  accent: "#ffea3b"
  bg_gradient: ["#1a3b6b", "#0a1a3b"]
handle: "@legacy-kanal"
output_dir: output/legacy-kanal
enabled: true
cta:
  enabled: false
  text: ""
  icons: []
  duration_s: 0
  show_handle: false
"""
    yaml_path = cli_env / "config" / "channels" / f"{slug}.yaml"
    yaml_path.write_text(legacy_yaml, encoding="utf-8")

    args = type("Args", (), {
        "channel": slug,
        "config_dir": "config",
        "templates_dir": "templates",
        "with_dna": False,
        "topic_hint": "",
        "target_audience": "",
    })()
    with patch("short_bot.cli.generate_dna") as mock_gen:
        rc = _cmd_migrate_channel(args)

    assert rc == 0
    mock_gen.assert_not_called()
    updated = yaml_path.read_text(encoding="utf-8")
    assert "language:" in updated
    # template: default → newscast backward-compat
    assert "newscast" in updated


def test_created_channel_inherits_dna_categories(cli_env, monkeypatch):
    """Yeni kanal canonical kategori listesiyle doğmalı, kota BOŞ olmalı.

    Kategori listesi olmadan kota/öğrenme ipucu çalışmaz. Kota ise veri
    olmadan konulamaz — "en çok üretilene kota koy" varsayımı ölçümle
    çürüdü; sınır ancak `short-bot analyze` çıktısıyla belirlenir.
    """
    from types import SimpleNamespace

    from short_bot.config import load_channel

    dna = _fake_dna()
    dna.categories = ["yeni-urun", "sirket-haberi", "duzenleme"]
    with patch("short_bot.cli.generate_dna", return_value=dna):
        rc = _cmd_create_channel(SimpleNamespace(
            name="Teknoloji", keywords="teknoloji", language="tr",
            archetype="newscast", config_dir="config",
            templates_dir="templates", slug=None, model="opus",
            topic_hint="", target_audience="", force=False,
        ))
    assert rc == 0

    cfg = load_channel(cli_env / "config" / "channels" / "teknoloji.yaml")
    assert cfg.categories == ["yeni-urun", "sirket-haberi", "duzenleme"]
    assert cfg.category_quota_per_day == {}
