"""Per-channel proxy support for YouTube API calls.

Handles URL parsing, http/session builders, and credentials redaction so
proxy URLs (which often contain user:pass) never leak into logs or error
messages.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import httplib2
import requests
import socks  # PySocks — provides PROXY_TYPE_* constants and connection layer
import yaml

logger = logging.getLogger(__name__)

_SCHEME_TO_TYPE = {
    "http":   socks.PROXY_TYPE_HTTP,
    "https":  socks.PROXY_TYPE_HTTP,   # HTTPS proxy = HTTP CONNECT tunnel
    "socks5": socks.PROXY_TYPE_SOCKS5,
    "socks4": socks.PROXY_TYPE_SOCKS4,
}


def normalize_proxy_url(raw: str) -> str:
    """Accept multiple proxy URL formats and return canonical scheme://[user:pass@]host:port.

    Supports:
      - Standard URL: ``http://user:pass@host:port``, ``socks5://host:port``, etc.
        Returned as-is (just stripped).
      - Residential format: ``host:port:user:pass`` (4 colon-separated segments,
        no scheme). Auto-converted to ``http://user:pass@host:port``.
      - Bare ``host:port`` (2 segments, no scheme). Auto-prefixed with ``http://``.

    Raises ValueError for empty input.
    """
    s = (raw or "").strip()
    if not s:
        raise ValueError("proxy URL bos")
    if "://" in s:
        return s
    parts = s.split(":")
    if len(parts) == 4:
        # host:port:user:pass — common residential proxy format
        host, port, user, password = parts
        return f"http://{user}:{password}@{host}:{port}"
    if len(parts) == 2:
        # host:port — IP-whitelist proxy
        return f"http://{s}"
    raise ValueError(
        f"Tanimsiz proxy formati: {raw!r}. Kabul edilen formatlar: "
        f"http://user:pass@host:port  veya  host:port:user:pass  veya  host:port"
    )


def parse_proxy_url(url: str) -> tuple[int, str, int, str | None, str | None]:
    """Parse a proxy URL into (proxy_type, host, port, user, password).

    Accepts multiple formats via :func:`normalize_proxy_url` (standard URL,
    residential ``host:port:user:pass``, bare ``host:port``).
    Raises ValueError for unsupported schemes or missing host/port.
    """
    url = normalize_proxy_url(url)
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


_CRED_RE = re.compile(r"://[^:/\s]+:[^@/\s]+@")


def _redact(url: str) -> str:
    """Mask user:pass in a proxy URL."""
    p = urlparse(url)
    if p.username or p.password:
        netloc = f"***:***@{p.hostname}:{p.port}"
        return f"{p.scheme}://{netloc}"
    return url


def _redact_err(exc: BaseException) -> str:
    """Mask any user:pass occurrence inside an exception message."""
    return _CRED_RE.sub("://***:***@", str(exc))


def load_channel_proxy_url(slug: str, secrets_path: Path) -> str | None:
    """Read data/secrets.yaml -> channel_proxies[slug].

    Returns the URL string, or None if:
      - secrets file missing
      - channel_proxies section missing
      - slug not present
      - value is empty/whitespace
    """
    p = Path(secrets_path)
    if not p.exists():
        return None
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    proxies = data.get("channel_proxies") or {}
    url = (proxies.get(slug) or "").strip()
    return url or None


def build_proxied_http(proxy_url: str | None, *, timeout: int = 60) -> httplib2.Http:
    """Build an httplib2.Http with proxy configured (or plain if None).

    Used as `http=` argument to googleapiclient.discovery.build(...) (wrapped
    by AuthorizedHttp at the call site).
    """
    if not proxy_url:
        return httplib2.Http(timeout=timeout)
    proxy_type, host, port, user, password = parse_proxy_url(proxy_url)
    proxy_info = httplib2.ProxyInfo(
        proxy_type=proxy_type, proxy_host=host, proxy_port=port,
        proxy_user=user, proxy_pass=password,
    )
    logger.info(f"using proxy {_redact(proxy_url)}")
    return httplib2.Http(timeout=timeout, proxy_info=proxy_info)


def build_proxied_requests_session(proxy_url: str | None) -> requests.Session:
    """Build a requests.Session with proxies configured (or plain if None).

    Used by google.auth.transport.requests.Request(session=...) for token
    refresh — that path uses requests, not httplib2.

    Normalizes alt-format inputs (host:port:user:pass, bare host:port) to
    standard scheme://[user:pass@]host:port so requests can parse them.
    """
    s = requests.Session()
    if not proxy_url:
        return s
    normalized = normalize_proxy_url(proxy_url)
    # requests proxies map is shared between http and https (server picks)
    s.proxies = {"http": normalized, "https": normalized}
    return s
