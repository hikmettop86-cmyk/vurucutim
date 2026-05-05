import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from short_bot.cli import _cmd_create_channel
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
