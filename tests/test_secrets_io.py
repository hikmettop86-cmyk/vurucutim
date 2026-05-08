"""Tests for short_bot.secrets_io."""
from __future__ import annotations

import yaml


def test_update_channel_proxy_creates_section(tmp_path):
    from short_bot.secrets_io import update_channel_proxy
    p = tmp_path / "secrets.yaml"
    p.write_text("pexels_api_key: x\n", encoding="utf-8")
    update_channel_proxy(p, "galatasaray", "http://h:1")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["pexels_api_key"] == "x"
    assert data["channel_proxies"] == {"galatasaray": "http://h:1"}


def test_update_channel_proxy_replaces_existing(tmp_path):
    from short_bot.secrets_io import update_channel_proxy
    p = tmp_path / "secrets.yaml"
    p.write_text(
        "channel_proxies:\n  galatasaray: http://old:1\n  fenerbahce: http://fb:2\n",
        encoding="utf-8",
    )
    update_channel_proxy(p, "galatasaray", "http://new:3")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["channel_proxies"]["galatasaray"] == "http://new:3"
    assert data["channel_proxies"]["fenerbahce"] == "http://fb:2"   # diğerini bozmaz


def test_update_channel_proxy_none_removes_key(tmp_path):
    from short_bot.secrets_io import update_channel_proxy
    p = tmp_path / "secrets.yaml"
    p.write_text(
        "channel_proxies:\n  galatasaray: http://h:1\n  fenerbahce: http://fb:2\n",
        encoding="utf-8",
    )
    update_channel_proxy(p, "galatasaray", None)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert "galatasaray" not in data["channel_proxies"]
    assert data["channel_proxies"]["fenerbahce"] == "http://fb:2"


def test_update_channel_proxy_none_when_section_empty_removes_section(tmp_path):
    from short_bot.secrets_io import update_channel_proxy
    p = tmp_path / "secrets.yaml"
    p.write_text(
        "pexels_api_key: x\nchannel_proxies:\n  galatasaray: http://h:1\n",
        encoding="utf-8",
    )
    update_channel_proxy(p, "galatasaray", None)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert "channel_proxies" not in data       # boş section temizlenir
    assert data["pexels_api_key"] == "x"


def test_update_channel_proxy_creates_file_if_missing(tmp_path):
    from short_bot.secrets_io import update_channel_proxy
    p = tmp_path / "secrets.yaml"
    update_channel_proxy(p, "galatasaray", "http://h:1")
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data == {"channel_proxies": {"galatasaray": "http://h:1"}}


def test_update_channel_proxy_idempotent_noop_for_missing_slug(tmp_path):
    from short_bot.secrets_io import update_channel_proxy
    p = tmp_path / "secrets.yaml"
    p.write_text("pexels_api_key: x\n", encoding="utf-8")
    update_channel_proxy(p, "galatasaray", None)   # zaten yok
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data == {"pexels_api_key": "x"}
