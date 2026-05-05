import subprocess
import sys

import pytest


def test_module_invocation_prints_help():
    result = subprocess.run(
        [sys.executable, "-m", "short_bot", "--help"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0
    assert "run" in result.stdout
    assert "init" in result.stdout
    assert "list-channels" in result.stdout


def test_list_channels_subcommand(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    chans = tmp_path / "config" / "channels"
    chans.mkdir(parents=True)
    (chans / "demo.yaml").write_text(
        "slug: demo\nname: D\nkeywords: [x]\nrss_locale: hl=tr\n"
        "schedule_cron: '0 * * * *'\nduration_s: 30\nmin_score: 5\n"
        "max_candidates_per_run: 10\ntemplate: default\n"
        "colors: {primary: '#c81e1e', accent: '#ffea3b', bg_gradient: ['#1a3b6b', '#0a1a3b']}\n"
        "handle: '@d'\noutput_dir: output/demo\nenabled: true\n"
        "cta: {enabled: true, text: 'a', icons: ['x'], duration_s: 4, show_handle: true}\n",
        encoding="utf-8",
    )
    settings = tmp_path / "config" / "settings.yaml"
    settings.write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5000}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "short_bot", "list-channels"],
        capture_output=True, text=True, encoding="utf-8", cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "demo" in result.stdout
