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


def test_build_proxied_http_none_returns_plain_httplib2():
    """No proxy → still httplib2.Http (preserves direct path)."""
    import httplib2
    from short_bot.youtube.proxy import build_proxied_http
    http = build_proxied_http(None)
    assert isinstance(http, httplib2.Http)


def test_build_proxied_http_with_proxy_returns_requests_backed():
    """With proxy → RequestsBackedHttp adapter (PySocks bypass)."""
    from short_bot.youtube.proxy import build_proxied_http, RequestsBackedHttp
    http = build_proxied_http("http://alice:s3cret@h.example.com:8080")
    assert isinstance(http, RequestsBackedHttp)
    # Verify session has proxies configured
    assert http._session.proxies == {
        "http": "http://alice:s3cret@h.example.com:8080",
        "https": "http://alice:s3cret@h.example.com:8080",
    }


def test_build_proxied_http_socks5_returns_requests_backed():
    from short_bot.youtube.proxy import build_proxied_http, RequestsBackedHttp
    http = build_proxied_http("socks5://h:1080")
    assert isinstance(http, RequestsBackedHttp)


def test_requests_backed_http_request_returns_tuple():
    """request() returns (httplib2.Response-like, bytes)."""
    from unittest.mock import MagicMock
    from short_bot.youtube.proxy import RequestsBackedHttp
    fake_session = MagicMock()
    fake_resp = MagicMock(status_code=200, content=b"hello", headers={"X-Foo": "bar"})
    fake_session.request.return_value = fake_resp

    http = RequestsBackedHttp(fake_session)
    resp, content = http.request("https://example.com", method="GET")

    assert resp.status == 200
    assert content == b"hello"
    assert resp["x-foo"] == "bar"   # httplib2 lowercases keys
    assert resp["status"] == "200"


def test_requests_backed_http_passes_body_and_headers():
    from unittest.mock import MagicMock
    from short_bot.youtube.proxy import RequestsBackedHttp
    fake_session = MagicMock()
    fake_resp = MagicMock(status_code=204, content=b"", headers={})
    fake_session.request.return_value = fake_resp

    http = RequestsBackedHttp(fake_session)
    http.request("https://example.com", method="POST",
                 body=b"data", headers={"Content-Type": "video/mp4"})

    args, kwargs = fake_session.request.call_args
    assert kwargs["method"] == "POST"
    assert kwargs["url"] == "https://example.com"
    assert kwargs["data"] == b"data"
    assert kwargs["headers"]["Content-Type"] == "video/mp4"


def test_requests_backed_http_real_https_no_proxy():
    """Sanity: adapter actually does HTTP via real requests session."""
    import requests
    from short_bot.youtube.proxy import RequestsBackedHttp
    s = requests.Session()
    http = RequestsBackedHttp(s, timeout=10)
    resp, content = http.request(
        "https://api.ipify.org?format=json", method="GET",
    )
    assert resp.status == 200
    assert b"ip" in content


def test_build_proxied_session_none_no_proxies():
    import requests
    from short_bot.youtube.proxy import build_proxied_requests_session
    s = build_proxied_requests_session(None)
    assert isinstance(s, requests.Session)
    assert s.proxies == {}


def test_build_proxied_session_http():
    from short_bot.youtube.proxy import build_proxied_requests_session
    s = build_proxied_requests_session("http://u:p@h.example:8080")
    assert s.proxies == {
        "http":  "http://u:p@h.example:8080",
        "https": "http://u:p@h.example:8080",
    }


def test_build_proxied_session_socks5():
    from short_bot.youtube.proxy import build_proxied_requests_session
    s = build_proxied_requests_session("socks5://h:1080")
    # requests resmi olarak socks5h:// (DNS through proxy) çevirir
    assert s.proxies["http"].startswith("socks5")
    assert s.proxies["https"].startswith("socks5")


# ---------------------------------------------------------------------------
# normalize_proxy_url — alt format (host:port:user:pass) ve bare host:port
# ---------------------------------------------------------------------------

def test_normalize_residential_format():
    """host:port:user:pass formati http://user:pass@host:port'a cevrilir."""
    from short_bot.youtube.proxy import normalize_proxy_url
    out = normalize_proxy_url("45.41.178.248:6469:ltzzjsoy:nreys25apf01")
    assert out == "http://ltzzjsoy:nreys25apf01@45.41.178.248:6469"


def test_normalize_bare_host_port():
    """host:port (IP-whitelist) http://host:port'a cevrilir."""
    from short_bot.youtube.proxy import normalize_proxy_url
    out = normalize_proxy_url("1.2.3.4:3128")
    assert out == "http://1.2.3.4:3128"


def test_normalize_standard_url_passthrough():
    from short_bot.youtube.proxy import normalize_proxy_url
    assert normalize_proxy_url("http://u:p@h:1") == "http://u:p@h:1"
    assert normalize_proxy_url("socks5://h:1080") == "socks5://h:1080"


def test_normalize_strips_whitespace():
    from short_bot.youtube.proxy import normalize_proxy_url
    assert normalize_proxy_url("  http://h:1  ") == "http://h:1"


def test_normalize_empty_raises():
    import pytest
    from short_bot.youtube.proxy import normalize_proxy_url
    with pytest.raises(ValueError, match="bos"):
        normalize_proxy_url("")
    with pytest.raises(ValueError, match="bos"):
        normalize_proxy_url("   ")


def test_normalize_invalid_segments_raises():
    import pytest
    from short_bot.youtube.proxy import normalize_proxy_url
    with pytest.raises(ValueError, match="Tanimsiz proxy formati"):
        normalize_proxy_url("just-some-text")
    with pytest.raises(ValueError, match="Tanimsiz proxy formati"):
        normalize_proxy_url("a:b:c")        # 3 segment — geçersiz


def test_parse_proxy_url_accepts_residential_format():
    """parse_proxy_url normalize'i kullanir, residential format direkt parse eder."""
    import socks
    from short_bot.youtube.proxy import parse_proxy_url
    proxy_type, host, port, user, password = parse_proxy_url(
        "45.41.178.248:6469:ltzzjsoy:nreys25apf01"
    )
    assert proxy_type == socks.PROXY_TYPE_HTTP
    assert host == "45.41.178.248"
    assert port == 6469
    assert user == "ltzzjsoy"
    assert password == "nreys25apf01"


def test_build_proxied_session_residential_format():
    """build_proxied_requests_session also accepts residential format."""
    from short_bot.youtube.proxy import build_proxied_requests_session
    s = build_proxied_requests_session("1.2.3.4:8080:user:pass")
    assert s.proxies == {
        "http": "http://user:pass@1.2.3.4:8080",
        "https": "http://user:pass@1.2.3.4:8080",
    }
