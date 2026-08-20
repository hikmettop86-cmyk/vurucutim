"""YouTube kimlik paylaşımı: iki format tek YouTube kanalını paylaşır."""
from __future__ import annotations

import json

import pytest
import yaml

from short_bot.config import YoutubeChannelConfig, load_channel, save_channel
from short_bot.youtube import auth as ya

_BASE = """\
slug: {slug}
name: {slug}
keywords: []
language: tr
content_source: trends
schedule_cron: 0 * * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: flas
colors:
  primary: '#d0021b'
  accent: '#ffe600'
  bg_gradient: ['#3a3a3a', '#141414']
handle: '@x'
output_dir: out
enabled: true
"""


def _write(tmp_path, slug, extra=""):
    p = tmp_path / f"{slug}.yaml"
    p.write_text(_BASE.format(slug=slug) + extra, encoding="utf-8")
    return p


def _connect(root, slug, channel_id="UC1", title="Kanal"):
    d = root / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "token.json").write_text("{}", encoding="utf-8")
    (d / "channel_info.json").write_text(
        json.dumps({"id": channel_id, "snippet": {"title": title}}), encoding="utf-8")


def test_creds_slug_defaults_to_own_slug(tmp_path):
    cfg = load_channel(_write(tmp_path, "gundem"))
    assert ya.creds_slug(cfg) == "gundem"


def test_creds_slug_follows_credentials_from(tmp_path):
    cfg = load_channel(_write(tmp_path, "gundem-yorum",
                              "youtube:\n  credentials_from: gundem\n  auto_upload: false\n"))
    assert ya.creds_slug(cfg) == "gundem"


def test_borrowed_credentials_are_found(tmp_path):
    root = tmp_path / "creds"
    _connect(root, "gundem")
    cfg = load_channel(_write(tmp_path, "gundem-yorum",
                              "youtube:\n  credentials_from: gundem\n"))
    assert ya.has_credentials(root, ya.creds_slug(cfg)) is True
    assert ya.has_credentials(root, cfg.slug) is False      # kendi klasörü yok


def test_credentials_from_roundtrips_through_yaml(tmp_path):
    cfg = load_channel(_write(tmp_path, "gundem-yorum",
                              "youtube:\n  credentials_from: gundem\n  auto_upload: true\n"))
    out = tmp_path / "o.yaml"
    save_channel(out, cfg)
    raw = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert raw["youtube"]["credentials_from"] == "gundem"
    assert load_channel(out).youtube.credentials_from == "gundem"


def test_no_credentials_from_is_not_written(tmp_path):
    cfg = load_channel(_write(tmp_path, "gundem", "youtube:\n  auto_upload: true\n"))
    out = tmp_path / "o.yaml"
    save_channel(out, cfg)
    assert "credentials_from" not in yaml.safe_load(out.read_text(encoding="utf-8"))["youtube"]


def test_invalid_slug_rejected():
    with pytest.raises(ValueError, match="credentials_from"):
        YoutubeChannelConfig(credentials_from="Büyük Harf!")


def test_same_youtube_channel_detects_shared_binding(tmp_path):
    root = tmp_path / "creds"
    _connect(root, "gundem", channel_id="UCKAOS", title="Kaos Dayı")
    _connect(root, "kaosdayi", channel_id="UCKAOS", title="Kaos Dayı")
    _connect(root, "galatasaray", channel_id="UCGS", title="Aslan Gündem")
    assert ya.same_youtube_channel(root, "gundem", ["gundem", "kaosdayi", "galatasaray"]) == ["kaosdayi"]
    assert ya.same_youtube_channel(root, "galatasaray", ["gundem", "kaosdayi", "galatasaray"]) == []
    assert ya.same_youtube_channel(root, "yok", ["gundem"]) == []     # bağlı değil


def test_repo_gundem_yorum_borrows_gundem():
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "config" / "channels" / "gundem-yorum.yaml"
    if not p.exists():
        pytest.skip("config/channels takipsiz olabilir")
    cfg = load_channel(p)
    assert ya.creds_slug(cfg) == "gundem"
