"""content_source: trends + trends_region yükle/kaydet."""
from __future__ import annotations

import pytest
import yaml

from short_bot.config import load_channel, save_channel

_BASE = """\
slug: gundem
name: Gündem
keywords: []
language: tr
schedule_cron: 0 */2 * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 25
template: broadcast
colors:
  primary: '#ed1c2e'
  accent: '#ffea1c'
  bg_gradient: ['#2a3a5e', '#0a1428']
handle: '@gundem'
output_dir: output/gundem
enabled: true
"""


def _write(tmp_path, extra: str):
    p = tmp_path / "gundem.yaml"
    p.write_text(_BASE + extra, encoding="utf-8")
    return p


def test_trends_source_loads_without_keywords(tmp_path):
    cfg = load_channel(_write(tmp_path, "content_source: trends\ntrends_region: TR\n"))
    assert cfg.content_source == "trends"
    assert cfg.trends_region == "TR"
    assert cfg.keywords == []


def test_trends_region_defaults_to_none_and_is_uppercased(tmp_path):
    cfg = load_channel(_write(tmp_path, "content_source: trends\n"))
    assert cfg.trends_region is None
    cfg2 = load_channel(_write(tmp_path, "content_source: trends\ntrends_region: de\n"))
    assert cfg2.trends_region == "DE"


def test_invalid_trends_region_rejected(tmp_path):
    with pytest.raises(ValueError, match="trends_region"):
        load_channel(_write(tmp_path, "content_source: trends\ntrends_region: Almanya\n"))


def test_rss_source_still_requires_keywords(tmp_path):
    with pytest.raises(ValueError, match="keywords"):
        load_channel(_write(tmp_path, ""))


def test_save_roundtrip_keeps_trends_fields(tmp_path):
    p = _write(tmp_path, "content_source: trends\ntrends_region: DE\n")
    cfg = load_channel(p)
    out = tmp_path / "out.yaml"
    save_channel(out, cfg)
    raw = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert raw["content_source"] == "trends"
    assert raw["trends_region"] == "DE"
    assert load_channel(out).trends_region == "DE"


def test_save_omits_trends_region_when_unset(tmp_path):
    cfg = load_channel(_write(tmp_path, "content_source: trends\n"))
    out = tmp_path / "out.yaml"
    save_channel(out, cfg)
    assert "trends_region" not in yaml.safe_load(out.read_text(encoding="utf-8"))


def test_repo_gundem_channel_loads():
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "config" / "channels" / "gundem.yaml"
    if not p.exists():
        pytest.skip("config/channels takipsiz olabilir (worktree)")
    cfg = load_channel(p)
    assert cfg.content_source == "trends"
    assert cfg.trends_region == "TR"
    assert cfg.schedule_cron == "0 */2 * * *"
    assert cfg.trend_boost is None or cfg.trend_boost.enabled is False
    assert cfg.dna is not None and cfg.dna.archetype == cfg.template == "flas"
    assert cfg.youtube is not None and cfg.youtube.auto_upload is False
