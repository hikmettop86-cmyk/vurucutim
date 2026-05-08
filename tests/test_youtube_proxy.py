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
