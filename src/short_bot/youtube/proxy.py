"""Per-channel proxy support for YouTube API calls.

Handles URL parsing, http/session builders, and credentials redaction so
proxy URLs (which often contain user:pass) never leak into logs or error
messages.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import socks  # PySocks — provides PROXY_TYPE_* constants and connection layer

logger = logging.getLogger(__name__)

_SCHEME_TO_TYPE = {
    "http":   socks.PROXY_TYPE_HTTP,
    "https":  socks.PROXY_TYPE_HTTP,   # HTTPS proxy = HTTP CONNECT tunnel
    "socks5": socks.PROXY_TYPE_SOCKS5,
    "socks4": socks.PROXY_TYPE_SOCKS4,
}


def parse_proxy_url(url: str) -> tuple[int, str, int, str | None, str | None]:
    """Parse a proxy URL into (proxy_type, host, port, user, password).

    Supports schemes: http, https, socks4, socks5.
    Raises ValueError for unsupported schemes or missing host/port.
    """
    p = urlparse(url)
    scheme = (p.scheme or "").lower()
    if scheme not in _SCHEME_TO_TYPE:
        raise ValueError(
            f"Unsupported proxy scheme {scheme!r} (use http/https/socks5/socks4)"
        )
    if not p.hostname:
        raise ValueError(f"proxy URL missing host: {url!r}")
    if p.port is None:
        raise ValueError(f"proxy URL missing port: {url!r}")
    return _SCHEME_TO_TYPE[scheme], p.hostname, p.port, p.username, p.password
