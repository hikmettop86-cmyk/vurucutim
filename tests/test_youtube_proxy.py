"""Tests for short_bot.youtube.proxy."""
from __future__ import annotations

import pytest
import socks


def test_parse_http_proxy_with_credentials():
    from short_bot.youtube.proxy import parse_proxy_url
    proxy_type, host, port, user, password = parse_proxy_url(
        "http://alice:s3cret@proxy.example.com:8080"
    )
    assert proxy_type == socks.PROXY_TYPE_HTTP
    assert host == "proxy.example.com"
    assert port == 8080
    assert user == "alice"
    assert password == "s3cret"


def test_parse_https_proxy_no_credentials():
    from short_bot.youtube.proxy import parse_proxy_url
    proxy_type, host, port, user, password = parse_proxy_url("https://1.2.3.4:3128")
    assert proxy_type == socks.PROXY_TYPE_HTTP   # https proxy = http CONNECT
    assert host == "1.2.3.4"
    assert port == 3128
    assert user is None
    assert password is None


def test_parse_socks5():
    from short_bot.youtube.proxy import parse_proxy_url
    proxy_type, host, port, user, password = parse_proxy_url(
        "socks5://u:p@socks.host:1080"
    )
    assert proxy_type == socks.PROXY_TYPE_SOCKS5
    assert host == "socks.host"
    assert port == 1080
    assert user == "u"
    assert password == "p"


def test_parse_socks4():
    from short_bot.youtube.proxy import parse_proxy_url
    proxy_type, _h, _p, _u, _pw = parse_proxy_url("socks4://h:1080")
    assert proxy_type == socks.PROXY_TYPE_SOCKS4


def test_parse_unsupported_scheme_raises():
    from short_bot.youtube.proxy import parse_proxy_url
    with pytest.raises(ValueError, match="Unsupported proxy scheme"):
        parse_proxy_url("ftp://example.com:21")


def test_parse_missing_host_raises():
    from short_bot.youtube.proxy import parse_proxy_url
    with pytest.raises(ValueError, match="proxy URL.*host"):
        parse_proxy_url("http://:8080")


def test_parse_missing_port_raises():
    from short_bot.youtube.proxy import parse_proxy_url
    with pytest.raises(ValueError, match="proxy URL.*port"):
        parse_proxy_url("http://host.example.com")


def test_redact_url_with_credentials():
    from short_bot.youtube.proxy import _redact
    out = _redact("http://alice:s3cret@host.com:8080")
    assert out == "http://***:***@host.com:8080"
    assert "alice" not in out
    assert "s3cret" not in out


def test_redact_url_without_credentials():
    from short_bot.youtube.proxy import _redact
    out = _redact("https://1.2.3.4:3128")
    assert out == "https://1.2.3.4:3128"


def test_redact_err_with_url_in_message():
    from short_bot.youtube.proxy import _redact_err
    e = ValueError("connection failed for http://u:p@bad.host:1080/path")
    out = _redact_err(e)
    assert "u:p" not in out
    assert "***:***" in out


def test_redact_err_no_url_in_message():
    from short_bot.youtube.proxy import _redact_err
    e = TimeoutError("read timed out")
    assert _redact_err(e) == "read timed out"


def test_load_channel_proxy_url_present(tmp_path):
    from short_bot.youtube.proxy import load_channel_proxy_url
    p = tmp_path / "secrets.yaml"
    p.write_text(
        "pexels_api_key: x\nchannel_proxies:\n  galatasaray: http://u:p@h:1\n",
        encoding="utf-8",
    )
    assert load_channel_proxy_url("galatasaray", p) == "http://u:p@h:1"


def test_load_channel_proxy_url_slug_missing(tmp_path):
    from short_bot.youtube.proxy import load_channel_proxy_url
    p = tmp_path / "secrets.yaml"
    p.write_text("channel_proxies:\n  fenerbahce: http://h:1\n", encoding="utf-8")
    assert load_channel_proxy_url("galatasaray", p) is None


def test_load_channel_proxy_url_no_section(tmp_path):
    from short_bot.youtube.proxy import load_channel_proxy_url
    p = tmp_path / "secrets.yaml"
    p.write_text("pexels_api_key: x\n", encoding="utf-8")
    assert load_channel_proxy_url("galatasaray", p) is None


def test_load_channel_proxy_url_no_file(tmp_path):
    from short_bot.youtube.proxy import load_channel_proxy_url
    assert load_channel_proxy_url("galatasaray", tmp_path / "missing.yaml") is None


def test_load_channel_proxy_url_empty_value(tmp_path):
    from short_bot.youtube.proxy import load_channel_proxy_url
    p = tmp_path / "secrets.yaml"
    p.write_text("channel_proxies:\n  galatasaray: ''\n", encoding="utf-8")
    assert load_channel_proxy_url("galatasaray", p) is None
