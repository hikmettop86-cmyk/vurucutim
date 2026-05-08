# Per-Channel YouTube Proxy Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Her kanalın YouTube API çağrılarını (upload + token refresh + auxiliary calls) kendisine atanmış proxy üzerinden gönderme yeteneği eklemek; proxy fail olursa upload abort edilsin.

**Architecture:** Yeni `youtube/proxy.py` modülü URL parse edip `httplib2.Http` (API client için) ve `requests.Session` (token refresh için) üretir. 4 mevcut `build("youtube", "v3", credentials=...)` çağrısı `http=AuthorizedHttp(creds, http=proxied_http)` versiyonuna geçer. `auth.py:load_credentials` `Request(session=proxied_session)` alır. Proxy URL'leri `data/secrets.yaml > channel_proxies` altında saklanır. Web UI'da kanal edit ekranına URL alanı + "Test Et" butonu eklenir; backend `POST /channels/<slug>/test-proxy` endpoint'i `api.ipify.org` üzerinden ping atar.

**Tech Stack:** Python 3.11, `httplib2`, `google-api-python-client`, `google-auth-httplib2`, `requests`, `PySocks` (yeni dep — SOCKS5), Flask, pytest, pytest-mock.

**Spec referansı:** `docs/superpowers/specs/2026-05-08-channel-proxy-design.md`

---

## File Structure

**Yaratılacak:**
- `src/short_bot/youtube/proxy.py` — proxy URL parsing, http/session builders, redact helpers
- `src/short_bot/secrets_io.py` — atomic secrets.yaml writer (`update_channel_proxy`)
- `tests/test_youtube_proxy.py` — proxy.py tüm fonksiyonları
- `tests/test_secrets_io.py` — secrets_io.update_channel_proxy

**Değiştirilecek:**
- `pyproject.toml` — `PySocks>=1.7` ekle
- `src/short_bot/youtube/auth.py` — `load_credentials(..., proxy_session=None)`, `fetch_and_save_channel_info(..., http=None)`
- `src/short_bot/youtube/uploader.py` — `upload_video(..., http=None)`
- `src/short_bot/youtube/data_api.py` — iki public fonksiyon `http=None` parametresi
- `src/short_bot/youtube/auto_upload.py` — proxy URL load + http/session inject + `UploadAbortError` + `status='proxy_failed'`
- `src/short_bot/pipeline.py` — `_maybe_auto_upload` secrets_path parametresi
- `src/short_bot/web/routes/channel_edit.py` — `yt_proxy_url` form field okuma + `update_channel_proxy` çağrısı
- `src/short_bot/web/routes/youtube.py` — `POST /channels/<slug>/test-proxy` endpoint
- `src/short_bot/web/templates/channel_edit.html` — Proxy URL input + "Test Et" butonu + JS handler

**Kapsam dışı (DEĞİŞMEZ):**
- `data/secrets.yaml` — yapı değişmez, opsiyonel `channel_proxies` anahtarı eklenir kullanım anında
- DB schema — `youtube_uploads.status` zaten String, migration gereksiz
- `src/short_bot/pexels.py:load_secrets` — mevcut kullanılıyor, taşınmaz

---

## Task 1: PySocks dependency ekle

**Files:**
- Modify: `pyproject.toml:32` (cryptography satırı sonrası)

- [ ] **Step 1: pyproject.toml'a PySocks ekle**

`pyproject.toml` 32. satırdan sonra (cryptography>=42.0 sonrası, kapanış `]`'ndan önce) yeni satır:

```toml
    "google-api-python-client>=2.100",
    "google-auth>=2.20",
    "google-auth-oauthlib>=1.0",
    "google-auth-httplib2>=0.1.0",
    "cryptography>=42.0",
    "PySocks>=1.7",
]
```

- [ ] **Step 2: PySocks'u dev ortama kur**

Run: `pip install "PySocks>=1.7"`
Expected: `Successfully installed PySocks-1.7.x`

- [ ] **Step 3: Import test**

Run: `python -c "import socks; print(socks.PROXY_TYPE_SOCKS5)"`
Expected: `2` (veya başka int — sabit yazılır, hata fırlatmaz)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps: PySocks>=1.7 ekle (SOCKS5 proxy desteği için)"
```

---

## Task 2: proxy.py — `parse_proxy_url` (URL parser)

**Files:**
- Create: `src/short_bot/youtube/proxy.py`
- Test: `tests/test_youtube_proxy.py`

- [ ] **Step 1: Failing testleri yaz**

`tests/test_youtube_proxy.py`:

```python
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
```

- [ ] **Step 2: Run testleri — fail bekleniyor**

Run: `pytest tests/test_youtube_proxy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'short_bot.youtube.proxy'`

- [ ] **Step 3: proxy.py'ı yarat — minimum impl**

`src/short_bot/youtube/proxy.py`:

```python
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
```

- [ ] **Step 4: Run testler — pass bekleniyor**

Run: `pytest tests/test_youtube_proxy.py -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/youtube/proxy.py tests/test_youtube_proxy.py
git commit -m "feat(youtube): proxy URL parser (HTTP/HTTPS/SOCKS5/SOCKS4)"
```

---

## Task 3: proxy.py — `_redact` ve `_redact_err`

**Files:**
- Modify: `src/short_bot/youtube/proxy.py`
- Test: `tests/test_youtube_proxy.py` (yeni testler eklenir)

- [ ] **Step 1: Failing testleri ekle**

`tests/test_youtube_proxy.py` sonuna ekle:

```python
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
```

- [ ] **Step 2: Run — 4 yeni test fail**

Run: `pytest tests/test_youtube_proxy.py -v -k "redact"`
Expected: 4 FAIL — "_redact / _redact_err not defined"

- [ ] **Step 3: Implementasyon ekle**

`src/short_bot/youtube/proxy.py` sonuna:

```python
import re

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
```

- [ ] **Step 4: Run — pass**

Run: `pytest tests/test_youtube_proxy.py -v`
Expected: 11 tests PASS (7 önceki + 4 yeni)

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/youtube/proxy.py tests/test_youtube_proxy.py
git commit -m "feat(youtube): proxy URL redact helpers (credentials sızıntısı önleme)"
```

---

## Task 4: proxy.py — `load_channel_proxy_url`

**Files:**
- Modify: `src/short_bot/youtube/proxy.py`
- Test: `tests/test_youtube_proxy.py`

- [ ] **Step 1: Failing testleri ekle**

`tests/test_youtube_proxy.py` sonuna:

```python
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
```

- [ ] **Step 2: Run — fail**

Run: `pytest tests/test_youtube_proxy.py -v -k "load_channel_proxy_url"`
Expected: 5 FAIL

- [ ] **Step 3: Impl ekle**

`src/short_bot/youtube/proxy.py` üst tarafa imports güncelle:

```python
from pathlib import Path
import yaml
```

Sonuna ekle:

```python
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
```

- [ ] **Step 4: Run — pass**

Run: `pytest tests/test_youtube_proxy.py -v`
Expected: 16 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/youtube/proxy.py tests/test_youtube_proxy.py
git commit -m "feat(youtube): load_channel_proxy_url — secrets.yaml'dan kanal proxy URL"
```

---

## Task 5: proxy.py — `build_proxied_http`

**Files:**
- Modify: `src/short_bot/youtube/proxy.py`
- Test: `tests/test_youtube_proxy.py`

- [ ] **Step 1: Failing testleri ekle**

```python
def test_build_proxied_http_none_returns_plain():
    import httplib2
    from short_bot.youtube.proxy import build_proxied_http
    http = build_proxied_http(None)
    assert isinstance(http, httplib2.Http)
    assert http.proxy_info is None or http.proxy_info() is None


def test_build_proxied_http_http_proxy_with_credentials():
    import httplib2
    import socks
    from short_bot.youtube.proxy import build_proxied_http
    http = build_proxied_http("http://alice:s3cret@h.example.com:8080")
    pi = http.proxy_info("https") if callable(http.proxy_info) else http.proxy_info
    assert pi.proxy_type == socks.PROXY_TYPE_HTTP
    assert pi.proxy_host == "h.example.com"
    assert pi.proxy_port == 8080
    assert pi.proxy_user == "alice"
    assert pi.proxy_pass == "s3cret"


def test_build_proxied_http_socks5():
    import socks
    from short_bot.youtube.proxy import build_proxied_http
    http = build_proxied_http("socks5://h:1080")
    pi = http.proxy_info("https") if callable(http.proxy_info) else http.proxy_info
    assert pi.proxy_type == socks.PROXY_TYPE_SOCKS5
```

- [ ] **Step 2: Run — fail**

Run: `pytest tests/test_youtube_proxy.py -v -k "build_proxied_http"`
Expected: 3 FAIL

- [ ] **Step 3: Impl ekle**

`src/short_bot/youtube/proxy.py` üstüne:

```python
import httplib2
```

Sonuna ekle:

```python
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
```

- [ ] **Step 4: Run — pass**

Run: `pytest tests/test_youtube_proxy.py -v`
Expected: 19 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/youtube/proxy.py tests/test_youtube_proxy.py
git commit -m "feat(youtube): build_proxied_http — httplib2.Http(proxy_info=...)"
```

---

## Task 6: proxy.py — `build_proxied_requests_session`

**Files:**
- Modify: `src/short_bot/youtube/proxy.py`
- Test: `tests/test_youtube_proxy.py`

- [ ] **Step 1: Failing testleri ekle**

```python
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
```

- [ ] **Step 2: Run — fail**

Run: `pytest tests/test_youtube_proxy.py -v -k "build_proxied_session"`
Expected: 3 FAIL

- [ ] **Step 3: Impl ekle**

`src/short_bot/youtube/proxy.py` üstüne:

```python
import requests
```

Sonuna ekle:

```python
def build_proxied_requests_session(proxy_url: str | None) -> requests.Session:
    """Build a requests.Session with proxies configured (or plain if None).

    Used by google.auth.transport.requests.Request(session=...) for token
    refresh — that path uses requests, not httplib2.
    """
    s = requests.Session()
    if not proxy_url:
        return s
    # requests proxies map is shared between http and https (server picks)
    s.proxies = {"http": proxy_url, "https": proxy_url}
    return s
```

- [ ] **Step 4: Run — pass**

Run: `pytest tests/test_youtube_proxy.py -v`
Expected: 22 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/youtube/proxy.py tests/test_youtube_proxy.py
git commit -m "feat(youtube): build_proxied_requests_session — token refresh için requests.Session"
```

---

## Task 7: secrets_io.py — `update_channel_proxy`

**Files:**
- Create: `src/short_bot/secrets_io.py`
- Test: `tests/test_secrets_io.py`

- [ ] **Step 1: Failing testleri yaz**

`tests/test_secrets_io.py`:

```python
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
```

- [ ] **Step 2: Run — fail**

Run: `pytest tests/test_secrets_io.py -v`
Expected: 6 FAIL — `ModuleNotFoundError`

- [ ] **Step 3: secrets_io.py'ı yarat**

`src/short_bot/secrets_io.py`:

```python
"""Atomic writers for data/secrets.yaml.

Read path (load_secrets) lives in pexels.py — kept there to avoid a circular
import; this module only handles writes.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml


def _atomic_write_yaml(path: Path, data: dict) -> None:
    """Write yaml atomically (write to .tmp, rename) so a crash mid-write
    can't leave a half-written secrets file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def update_channel_proxy(secrets_path: Path, slug: str, url: str | None) -> None:
    """Set or clear channel_proxies[slug] in secrets.yaml.

    - url=str  → upsert
    - url=None → remove. If channel_proxies becomes empty, remove the section.

    File created if missing. Other top-level keys are preserved.
    """
    p = Path(secrets_path)
    data: dict = {}
    if p.exists():
        loaded = yaml.safe_load(p.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    proxies = dict(data.get("channel_proxies") or {})
    if url is None:
        proxies.pop(slug, None)
    else:
        proxies[slug] = url
    if proxies:
        data["channel_proxies"] = proxies
    else:
        data.pop("channel_proxies", None)
    _atomic_write_yaml(p, data)
```

- [ ] **Step 4: Run — pass**

Run: `pytest tests/test_secrets_io.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/secrets_io.py tests/test_secrets_io.py
git commit -m "feat(secrets): atomic update_channel_proxy (idempotent yaml writer)"
```

---

## Task 8: youtube/auth.py — `load_credentials` proxy_session parametresi

**Files:**
- Modify: `src/short_bot/youtube/auth.py:43-53`
- Test: `tests/test_youtube_auth_proxy.py` (yeni)

- [ ] **Step 1: Failing test yaz**

`tests/test_youtube_auth_proxy.py`:

```python
"""Tests for proxy injection into youtube.auth.load_credentials."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock


def _make_token_dict():
    return {
        "token": "old",
        "refresh_token": "r",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid",
        "client_secret": "cs",
        "scopes": [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
        "expiry": "2000-01-01T00:00:00Z",   # expired → refresh tetiklenir
    }


def test_load_credentials_passes_session_to_request(tmp_path):
    from short_bot.youtube import auth as yt_auth
    slug = "ch1"
    d = tmp_path / slug
    d.mkdir()
    (d / "token.json").write_text(json.dumps(_make_token_dict()), encoding="utf-8")
    sess = MagicMock(name="proxy_session")

    with patch("short_bot.youtube.auth.Request") as mock_request, \
         patch.object(yt_auth, "save_credentials"):
        # Credentials.refresh stub'ı request objesini çağırır; biz Request'i
        # mock'ladık, dolayısıyla refresh içeride raise etmesin diye:
        mock_request.return_value = MagicMock()
        # creds.refresh'i de mock'la
        with patch("short_bot.youtube.auth.Credentials") as mock_creds_cls:
            mock_creds = MagicMock()
            mock_creds.expired = True
            mock_creds.refresh_token = "r"
            mock_creds_cls.from_authorized_user_info.return_value = mock_creds
            yt_auth.load_credentials(tmp_path, slug, proxy_session=sess)

    mock_request.assert_called_once_with(session=sess)


def test_load_credentials_no_session_arg_uses_default_request(tmp_path):
    """Backward-compat: proxy_session argümanı verilmezse Request() default."""
    from short_bot.youtube import auth as yt_auth
    slug = "ch1"
    d = tmp_path / slug
    d.mkdir()
    (d / "token.json").write_text(json.dumps(_make_token_dict()), encoding="utf-8")

    with patch("short_bot.youtube.auth.Request") as mock_request, \
         patch.object(yt_auth, "save_credentials"), \
         patch("short_bot.youtube.auth.Credentials") as mock_creds_cls:
        mock_request.return_value = MagicMock()
        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "r"
        mock_creds_cls.from_authorized_user_info.return_value = mock_creds
        yt_auth.load_credentials(tmp_path, slug)

    mock_request.assert_called_once_with()   # session= argümanı YOK
```

- [ ] **Step 2: Run — fail**

Run: `pytest tests/test_youtube_auth_proxy.py -v`
Expected: 2 FAIL — `load_credentials() got an unexpected keyword argument 'proxy_session'`

- [ ] **Step 3: auth.py:load_credentials güncelle**

`src/short_bot/youtube/auth.py:43-53` (mevcut `load_credentials`):

```python
def load_credentials(
    root: Path, slug: str, *, proxy_session=None,
) -> Credentials | None:
    """Load + auto-refresh credentials for the channel. Returns None if missing.

    proxy_session: optional requests.Session (from build_proxied_requests_session)
    used when token refresh hits Google's OAuth endpoint. Lets us route the
    refresh through the same proxy as the upload.
    """
    token_path = credentials_dir(root, slug) / "token.json"
    if not token_path.is_file():
        return None
    info = json.loads(token_path.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(info, scopes=info.get("scopes", SCOPES))
    if creds.expired and creds.refresh_token:
        request = Request(session=proxy_session) if proxy_session else Request()
        creds.refresh(request)
        save_credentials(root, slug, creds)
    return creds
```

- [ ] **Step 4: Run — pass**

Run: `pytest tests/test_youtube_auth_proxy.py -v`
Expected: 2 PASS

- [ ] **Step 5: Mevcut auth testleri etkilenmedi doğrula**

Run: `pytest tests/ -v -k "youtube" --tb=short`
Expected: önceki YouTube testleri yine PASS

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/youtube/auth.py tests/test_youtube_auth_proxy.py
git commit -m "feat(youtube/auth): load_credentials proxy_session parametresi"
```

---

## Task 9: youtube/auth.py — `fetch_and_save_channel_info` http parametresi

**Files:**
- Modify: `src/short_bot/youtube/auth.py:87-104`
- Test: `tests/test_youtube_auth_proxy.py`

- [ ] **Step 1: Failing test ekle**

`tests/test_youtube_auth_proxy.py` sonuna:

```python
def test_fetch_and_save_channel_info_uses_authorized_http_when_http_given(tmp_path):
    """When http= is given, build() must receive AuthorizedHttp(creds, http=http),
    NOT credentials= directly. (proxy path)"""
    from short_bot.youtube import auth as yt_auth
    fake_http = MagicMock(name="proxied_http")
    fake_creds = MagicMock(name="creds")
    slug = "ch1"
    (tmp_path / slug).mkdir()

    with patch("short_bot.youtube.auth.build") as mock_build, \
         patch("short_bot.youtube.auth.AuthorizedHttp") as mock_authed:
        mock_authed.return_value = "AUTHED"
        mock_yt = MagicMock()
        mock_yt.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "c1", "snippet": {}, "statistics": {}}],
        }
        mock_build.return_value = mock_yt
        with patch("short_bot.youtube.avatar.fetch_and_cache_avatar"):
            yt_auth.fetch_and_save_channel_info(tmp_path, slug, fake_creds, http=fake_http)

    mock_authed.assert_called_once_with(fake_creds, http=fake_http)
    mock_build.assert_called_once_with("youtube", "v3", http="AUTHED")


def test_fetch_and_save_channel_info_no_http_uses_credentials_directly(tmp_path):
    """Backward-compat: http= yoksa eski davranış (credentials= geçer)."""
    from short_bot.youtube import auth as yt_auth
    fake_creds = MagicMock(name="creds")
    slug = "ch1"
    (tmp_path / slug).mkdir()

    with patch("short_bot.youtube.auth.build") as mock_build, \
         patch("short_bot.youtube.auth.AuthorizedHttp") as mock_authed:
        mock_yt = MagicMock()
        mock_yt.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "c1", "snippet": {}, "statistics": {}}],
        }
        mock_build.return_value = mock_yt
        with patch("short_bot.youtube.avatar.fetch_and_cache_avatar"):
            yt_auth.fetch_and_save_channel_info(tmp_path, slug, fake_creds)

    mock_authed.assert_not_called()
    mock_build.assert_called_once_with("youtube", "v3", credentials=fake_creds)
```

- [ ] **Step 2: Run — fail**

Run: `pytest tests/test_youtube_auth_proxy.py -v -k "fetch_and_save"`
Expected: 2 FAIL

- [ ] **Step 3: auth.py'ı güncelle**

Üst tarafa import ekle:

```python
from google_auth_httplib2 import AuthorizedHttp
```

Mevcut `fetch_and_save_channel_info` (87-104):

```python
def fetch_and_save_channel_info(
    root: Path, slug: str, creds: Credentials, *, http=None,
) -> dict:
    """Call channels().list(mine=True), persist response as channel_info.json.

    http: optional proxied httplib2.Http. When given, wrapped in AuthorizedHttp
    and passed to build(http=...). When None, credentials= is passed (no proxy).
    """
    if http is not None:
        youtube = build("youtube", "v3", http=AuthorizedHttp(creds, http=http))
    else:
        youtube = build("youtube", "v3", credentials=creds)
    resp = youtube.channels().list(part="snippet,statistics", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise RuntimeError("YouTube channels().list returned no items for this account")
    info = items[0]
    d = credentials_dir(root, slug)
    d.mkdir(parents=True, exist_ok=True)
    (d / "channel_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    from short_bot.youtube.avatar import fetch_and_cache_avatar
    fetch_and_cache_avatar(root, slug, info)
    return info
```

- [ ] **Step 4: Run — pass**

Run: `pytest tests/test_youtube_auth_proxy.py -v`
Expected: tüm testler PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/youtube/auth.py tests/test_youtube_auth_proxy.py
git commit -m "feat(youtube/auth): fetch_and_save_channel_info http parametresi"
```

---

## Task 10: youtube/uploader.py — `upload_video` http parametresi

**Files:**
- Modify: `src/short_bot/youtube/uploader.py:54-81`
- Test: `tests/test_youtube_uploader_proxy.py` (yeni)

- [ ] **Step 1: Failing test yaz**

`tests/test_youtube_uploader_proxy.py`:

```python
"""upload_video respects proxied http when given."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock


def test_upload_video_with_http_uses_authorized_http(tmp_path):
    from short_bot.youtube import uploader
    fake_http = MagicMock(name="proxied_http")
    fake_creds = MagicMock(name="creds")
    file = tmp_path / "video.mp4"
    file.write_bytes(b"\x00" * 16)

    with patch("short_bot.youtube.uploader.build") as mock_build, \
         patch("short_bot.youtube.uploader.AuthorizedHttp") as mock_authed, \
         patch("short_bot.youtube.uploader.MediaFileUpload"):
        mock_authed.return_value = "AUTHED"
        mock_req = MagicMock()
        mock_req.next_chunk.return_value = (None, {"id": "VID123"})
        mock_build.return_value.videos.return_value.insert.return_value = mock_req

        out = uploader.upload_video(
            credentials=fake_creds, file_path=file,
            snippet={"title": "t"}, status={"privacyStatus": "public"},
            http=fake_http,
        )

    assert out == "VID123"
    mock_authed.assert_called_once_with(fake_creds, http=fake_http)
    mock_build.assert_called_once_with("youtube", "v3", http="AUTHED")


def test_upload_video_without_http_uses_credentials_directly(tmp_path):
    """Backward-compat."""
    from short_bot.youtube import uploader
    fake_creds = MagicMock(name="creds")
    file = tmp_path / "video.mp4"
    file.write_bytes(b"\x00" * 16)

    with patch("short_bot.youtube.uploader.build") as mock_build, \
         patch("short_bot.youtube.uploader.AuthorizedHttp") as mock_authed, \
         patch("short_bot.youtube.uploader.MediaFileUpload"):
        mock_req = MagicMock()
        mock_req.next_chunk.return_value = (None, {"id": "VID999"})
        mock_build.return_value.videos.return_value.insert.return_value = mock_req
        out = uploader.upload_video(
            credentials=fake_creds, file_path=file,
            snippet={"title": "t"}, status={"privacyStatus": "public"},
        )
    assert out == "VID999"
    mock_authed.assert_not_called()
    mock_build.assert_called_once_with("youtube", "v3", credentials=fake_creds)
```

- [ ] **Step 2: Run — fail**

Run: `pytest tests/test_youtube_uploader_proxy.py -v`
Expected: 2 FAIL — `upload_video() got an unexpected keyword argument 'http'`

- [ ] **Step 3: uploader.py güncelle**

`src/short_bot/youtube/uploader.py` üstüne import:

```python
from google_auth_httplib2 import AuthorizedHttp
```

`upload_video` (54-81):

```python
def upload_video(*, credentials: Credentials, file_path: Path,
                 snippet: dict, status: dict, max_retries: int = 5,
                 http=None) -> str:
    """Upload mp4 with retry. Re-creates the request on each retry because
    a partial resumable session can't be safely resumed across exceptions.

    http: optional proxied httplib2.Http. When given wrapped via AuthorizedHttp
    so the entire upload (including resumable chunks) goes through proxy.
    """
    if http is not None:
        youtube = build("youtube", "v3", http=AuthorizedHttp(credentials, http=http))
    else:
        youtube = build("youtube", "v3", credentials=credentials)
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        media = MediaFileUpload(
            str(file_path), mimetype="video/mp4",
            resumable=True, chunksize=10 * 1024 * 1024,
        )
        request = youtube.videos().insert(
            part="snippet,status",
            body={"snippet": snippet, "status": status},
            media_body=media,
        )
        try:
            response = None
            while response is None:
                _status, response = request.next_chunk()
            return response["id"]
        except ResumableUploadError as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_error  # unreachable
```

- [ ] **Step 4: Run — pass**

Run: `pytest tests/test_youtube_uploader_proxy.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/youtube/uploader.py tests/test_youtube_uploader_proxy.py
git commit -m "feat(youtube/uploader): upload_video http parametresi"
```

---

## Task 11: youtube/data_api.py — iki public fonksiyon http parametresi

**Files:**
- Modify: `src/short_bot/youtube/data_api.py:18, 37`
- Test: `tests/test_youtube_data_api_proxy.py` (yeni)

- [ ] **Step 1: Mevcut data_api fonksiyonlarını oku ve isim/imzaları öğren**

Run: `grep -n "^def " src/short_bot/youtube/data_api.py`

İmzaları ve mevcut çağrı pattern'ini görüp test'i ona göre yaz.

- [ ] **Step 2: Failing test yaz**

`tests/test_youtube_data_api_proxy.py`:

```python
"""data_api fonksiyonları http= parametresiyle AuthorizedHttp kullanır."""
from __future__ import annotations

import inspect
from unittest.mock import patch, MagicMock


def test_data_api_functions_accept_http_kwarg():
    """Mevcut iki public fonksiyon http= parametresi kabul ediyor mu."""
    from short_bot.youtube import data_api
    public_fns = [getattr(data_api, n) for n in dir(data_api)
                  if not n.startswith("_") and callable(getattr(data_api, n))
                  and inspect.getmodule(getattr(data_api, n)) is data_api]
    assert len(public_fns) >= 2
    for fn in public_fns:
        sig = inspect.signature(fn)
        assert "http" in sig.parameters, (
            f"{fn.__name__} should accept http= kwarg")


def test_data_api_with_http_wraps_authorized_http():
    """İlk public fonksiyon http geçilince AuthorizedHttp(creds, http=...) build."""
    from short_bot.youtube import data_api
    fake_http = MagicMock(name="proxied_http")
    fake_creds = MagicMock(name="creds")

    with patch("short_bot.youtube.data_api.build") as mock_build, \
         patch("short_bot.youtube.data_api.AuthorizedHttp") as mock_authed:
        mock_authed.return_value = "AUTHED"
        mock_build.return_value = MagicMock()
        # İlk public fonksiyonu bul ve çağır — minimal kwargs.
        public = [n for n in dir(data_api)
                  if not n.startswith("_")
                  and callable(getattr(data_api, n))
                  and inspect.getmodule(getattr(data_api, n)) is data_api]
        first = getattr(data_api, sorted(public)[0])
        sig = inspect.signature(first)
        kwargs = {"credentials": fake_creds, "http": fake_http}
        # Mevcut zorunlu pozitif parametreleri MagicMock ile doldur
        for name, p in sig.parameters.items():
            if name in kwargs: continue
            if p.default is inspect.Parameter.empty and name != "self":
                kwargs[name] = MagicMock()
        try:
            first(**kwargs)
        except Exception:
            pass    # build() veya sonraki çağrı mock; nesneler eksik olabilir

    mock_authed.assert_called_with(fake_creds, http=fake_http)
```

- [ ] **Step 3: Run — fail**

Run: `pytest tests/test_youtube_data_api_proxy.py -v`
Expected: FAIL (http kwarg yok)

- [ ] **Step 4: data_api.py'ı güncelle**

`src/short_bot/youtube/data_api.py` üstüne import:

```python
from google_auth_httplib2 import AuthorizedHttp
```

İçindeki HER public fonksiyona `http=None` parametresi ekle ve build çağrısını şu desene çevir:

```python
def some_fn(credentials, ..., *, http=None):
    if http is not None:
        youtube = build("youtube", "v3", http=AuthorizedHttp(credentials, http=http))
    else:
        youtube = build("youtube", "v3", credentials=credentials)
    ...
```

(İki public fonksiyon var — her ikisini de aynı şekilde değiştir.)

- [ ] **Step 5: Run — pass**

Run: `pytest tests/test_youtube_data_api_proxy.py -v`
Expected: PASS

- [ ] **Step 6: Mevcut data_api kullanıcılarını kırmadığını doğrula**

Run: `pytest tests/ -v --tb=short -k "data_api or youtube"`
Expected: önceki testler PASS

- [ ] **Step 7: Commit**

```bash
git add src/short_bot/youtube/data_api.py tests/test_youtube_data_api_proxy.py
git commit -m "feat(youtube/data_api): iki public fonksiyona http parametresi"
```

---

## Task 12: auto_upload.py — proxy entegrasyonu + UploadAbortError + DB status

**Files:**
- Modify: `src/short_bot/youtube/auto_upload.py:59-117`
- Test: `tests/test_auto_upload_proxy.py` (yeni)

- [ ] **Step 1: Failing testleri yaz**

`tests/test_auto_upload_proxy.py`:

```python
"""run_auto_upload proxy yolunu doğru çağırıyor + fail durumlarını
proxy_failed olarak işaretliyor."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def channel_with_yt():
    from short_bot.config import ChannelConfig, YoutubeChannelConfig
    yt = YoutubeChannelConfig(
        auto_upload=True, ai_content=True, category_id="24",
        privacy_status="public", min_score_for_upload=0.0, cron_preset=None,
    )
    return ChannelConfig(
        slug="t", name="t", keywords=[], rss_locale="tr-TR",
        schedule_cron="* * * * *", duration_s=30, min_score=0.0,
        max_candidates_per_run=5, template="newscast", colors={},
        handle="@x", output_dir="output/t", enabled=True,
        cta_enabled=False, cta_text="", cta_icons=[], cta_duration_s=3,
        cta_show_handle=False, language="tr",
        youtube=yt,
    )


def test_run_auto_upload_uses_proxy_when_set(tmp_path, channel_with_yt):
    """Proxy URL secrets'ta varsa upload_video http= ile çağrılır."""
    from short_bot.youtube import auto_upload
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("channel_proxies:\n  t: http://h:1\n", encoding="utf-8")

    with patch.object(auto_upload, "upload_video") as mock_upload, \
         patch.object(auto_upload, "build_proxied_http") as mock_bph, \
         patch.object(auto_upload, "build_proxied_requests_session") as mock_bps, \
         patch.object(auto_upload, "record_youtube_upload"), \
         patch.object(auto_upload, "_load_short_for_upload") as mock_load, \
         patch.object(auto_upload, "generate_youtube_metadata", side_effect=Exception()):
        mock_load.return_value = (
            MagicMock(file_path=str(tmp_path / "v.mp4"), script_json="{}"),
            None, None,
        )
        (tmp_path / "v.mp4").write_bytes(b"\x00")
        mock_bph.return_value = "PROXIED_HTTP"
        mock_bps.return_value = MagicMock()
        mock_upload.return_value = "VID"
        auto_upload.run_auto_upload(
            eng=MagicMock(), short_id=1, channel=channel_with_yt,
            credentials=MagicMock(), secrets_path=secrets,
        )

    mock_bph.assert_called_once_with("http://h:1")
    # upload_video http=PROXIED_HTTP ile çağrılmalı
    _, kwargs = mock_upload.call_args
    assert kwargs.get("http") == "PROXIED_HTTP"


def test_run_auto_upload_no_proxy_passes_none(tmp_path, channel_with_yt):
    """Secrets'ta proxy yoksa http=None geçilir (existing direct behavior)."""
    from short_bot.youtube import auto_upload
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("pexels_api_key: x\n", encoding="utf-8")

    with patch.object(auto_upload, "upload_video") as mock_upload, \
         patch.object(auto_upload, "record_youtube_upload"), \
         patch.object(auto_upload, "_load_short_for_upload") as mock_load, \
         patch.object(auto_upload, "generate_youtube_metadata", side_effect=Exception()):
        mock_load.return_value = (
            MagicMock(file_path=str(tmp_path / "v.mp4"), script_json="{}"),
            None, None,
        )
        (tmp_path / "v.mp4").write_bytes(b"\x00")
        mock_upload.return_value = "VID"
        auto_upload.run_auto_upload(
            eng=MagicMock(), short_id=1, channel=channel_with_yt,
            credentials=MagicMock(), secrets_path=secrets,
        )
    _, kwargs = mock_upload.call_args
    assert kwargs.get("http") is None


def test_run_auto_upload_proxy_fail_raises_abort_and_records_proxy_failed(
    tmp_path, channel_with_yt
):
    """Proxy fail edince UploadAbortError + record_youtube_upload(status='proxy_failed')."""
    import requests
    from short_bot.youtube import auto_upload
    from short_bot.youtube.auto_upload import UploadAbortError
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("channel_proxies:\n  t: http://h:1\n", encoding="utf-8")

    fake_creds = MagicMock()
    fake_creds.expired = True
    fake_creds.refresh_token = "r"
    fake_creds.refresh.side_effect = requests.exceptions.ProxyError("proxy down")

    with patch.object(auto_upload, "upload_video"), \
         patch.object(auto_upload, "record_youtube_upload") as mock_record, \
         patch.object(auto_upload, "_load_short_for_upload") as mock_load, \
         patch.object(auto_upload, "generate_youtube_metadata", side_effect=Exception()):
        mock_load.return_value = (
            MagicMock(file_path=str(tmp_path / "v.mp4"), script_json="{}"), None, None,
        )
        (tmp_path / "v.mp4").write_bytes(b"\x00")
        with pytest.raises(UploadAbortError):
            auto_upload.run_auto_upload(
                eng=MagicMock(), short_id=1, channel=channel_with_yt,
                credentials=fake_creds, secrets_path=secrets,
            )
    # Hata kaydı status='proxy_failed' ile yapılmış olmalı
    mock_record.assert_called_once()
    _, kw = mock_record.call_args
    assert kw["status"] == "proxy_failed"
    assert "proxy" in (kw["error"] or "").lower()
```

- [ ] **Step 2: Run — fail**

Run: `pytest tests/test_auto_upload_proxy.py -v`
Expected: 3 FAIL — `secrets_path` kwarg yok, `UploadAbortError` import edilemedi, `_load_short_for_upload` yok

- [ ] **Step 3: auto_upload.py'ı güncelle**

`src/short_bot/youtube/auto_upload.py` tam dosyayı şuna çevir (mevcut yapıyı koruyup proxy + abort path ekleyerek):

```python
"""Decision + execution layer for pipeline-triggered auto-upload."""
from __future__ import annotations

import json as _json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from sqlalchemy import select
from google.auth.transport.requests import Request


@dataclass(frozen=True)
class AutoUploadDecision:
    eligible: bool
    reason: str = ""


def should_auto_upload(*, channel, picked_score: float | None,
                       last_upload_at: datetime | None,
                       cooldown_minutes: int) -> AutoUploadDecision:
    """(unchanged from prior version)"""
    if channel.youtube is None or not channel.youtube.auto_upload:
        return AutoUploadDecision(False, "youtube auto_upload off")
    threshold = channel.youtube.min_score_for_upload
    if picked_score is not None and picked_score < threshold:
        return AutoUploadDecision(
            False, f"skor {picked_score:.1f} eşiğin altında ({threshold:.1f})",
        )
    if last_upload_at is not None:
        if last_upload_at.tzinfo is None:
            last_upload_at = last_upload_at.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - last_upload_at
        if delta < timedelta(minutes=cooldown_minutes):
            remaining = cooldown_minutes * 60 - delta.total_seconds()
            return AutoUploadDecision(
                False, f"global cooldown — {int(remaining)}s daha bekle",
            )
    return AutoUploadDecision(True)


from short_bot.db import get_rss_item_for_short, record_youtube_upload, shorts as _shorts_table  # noqa: E402
from short_bot.youtube.metadata_writer import generate_youtube_metadata  # noqa: E402
from short_bot.youtube.uploader import build_snippet, build_status, upload_video  # noqa: E402
from short_bot.youtube.proxy import (  # noqa: E402
    load_channel_proxy_url, build_proxied_http,
    build_proxied_requests_session, _redact_err,
)


class UploadAbortError(RuntimeError):
    """Upload aborted because proxy/network setup failed.

    Distinct from ResumableUploadError so callers can distinguish
    'API said no' from 'we never reached the API'.
    """


@dataclass(frozen=True)
class AutoUploadResult:
    video_id: str
    video_url: str


def _load_short_for_upload(eng, short_id: int):
    """Return (row, rss_source, rss_link) tuple for a short."""
    with eng.connect() as conn:
        row = conn.execute(
            select(_shorts_table).where(_shorts_table.c.id == short_id)
        ).first()
    if row is None:
        raise RuntimeError(f"short {short_id} not found")
    rss = get_rss_item_for_short(eng, short_id=short_id)
    return row, (rss.source if rss else None), (rss.link if rss else None)


def run_auto_upload(*, eng, short_id: int, channel, credentials,
                    claude_path: str = "claude",
                    model: str = "sonnet",
                    secrets_path: Path | None = None) -> AutoUploadResult:
    """Build metadata via Sonnet (best-effort) + upload + record DB row.

    secrets_path: data/secrets.yaml path. If None, no proxy lookup is attempted.

    Behavior:
      - If channel has a configured proxy: route token refresh + upload through it.
        Proxy failures raise UploadAbortError, recorded with status='proxy_failed'.
      - Otherwise: existing direct path.
    """
    row, rss_source, rss_link = _load_short_for_upload(eng, short_id)
    script = _json.loads(row.script_json or "{}")

    # Resolve proxy (if any) before any network I/O
    proxy_url = (
        load_channel_proxy_url(channel.slug, secrets_path)
        if secrets_path else None
    )
    http = build_proxied_http(proxy_url) if proxy_url else None
    session = build_proxied_requests_session(proxy_url) if proxy_url else None

    # Token refresh through proxy (only if expired) — surfaces proxy failure early
    if proxy_url and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request(session=session))
        except (requests.exceptions.ProxyError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            err = f"proxy fail (token refresh, {channel.slug}): {_redact_err(e)}"
            record_youtube_upload(
                eng, short_id=short_id, video_id=None,
                status="proxy_failed", error=err[:1000], video_url=None,
            )
            raise UploadAbortError(err) from e

    # Best-effort metadata generation
    generated = None
    try:
        meta = generate_youtube_metadata(
            channel=channel, script=script,
            rss_source=rss_source, rss_link=rss_link,
            claude_path=claude_path, model=model,
        )
        generated = {"title": meta.title, "description": meta.description, "tags": meta.tags}
    except Exception:
        pass

    yt = channel.youtube
    snippet = build_snippet(
        header_top=script.get("header_top", ""),
        header_bottom=script.get("header_bottom", ""),
        body_paragraph=script.get("body_paragraph", ""),
        handle=channel.handle, keywords=channel.keywords or [],
        category_id=yt.category_id, language=channel.language,
        generated=generated,
    )
    status = build_status(privacy_status=yt.privacy_status, ai_content=yt.ai_content)

    try:
        video_id = upload_video(
            credentials=credentials, file_path=Path(row.file_path),
            snippet=snippet, status=status, http=http,
        )
        url = f"https://youtu.be/{video_id}"
        record_youtube_upload(
            eng, short_id=short_id, video_id=video_id, status="success",
            error=None, video_url=url,
        )
        return AutoUploadResult(video_id=video_id, video_url=url)
    except Exception as e:
        # If we have a proxy and the error looks like a transport failure,
        # categorize it as proxy_failed (for UI distinction).
        is_proxy_fail = proxy_url is not None and isinstance(
            e, (requests.exceptions.ProxyError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                ConnectionError, OSError),
        )
        status_str = "proxy_failed" if is_proxy_fail else "failed"
        record_youtube_upload(
            eng, short_id=short_id, video_id=None, status=status_str,
            error=_redact_err(e)[:1000], video_url=None,
        )
        if is_proxy_fail:
            raise UploadAbortError(f"proxy fail (upload, {channel.slug}): {_redact_err(e)}") from e
        raise
```

- [ ] **Step 4: Run — pass**

Run: `pytest tests/test_auto_upload_proxy.py -v`
Expected: 3 PASS

- [ ] **Step 5: Mevcut auto_upload testleri etkilenmedi doğrula**

Run: `pytest tests/ -v -k "auto_upload" --tb=short`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/youtube/auto_upload.py tests/test_auto_upload_proxy.py
git commit -m "feat(youtube/auto_upload): proxy entegrasyonu + UploadAbortError + status='proxy_failed'"
```

---

## Task 13: pipeline.py — `_maybe_auto_upload` secrets_path parametresi

**Files:**
- Modify: `src/short_bot/pipeline.py:68-94, 517-525, 661-669`

- [ ] **Step 1: pipeline.py'da `_maybe_auto_upload`'a secrets_path parametresi ekle**

68-94 satırlarındaki `_maybe_auto_upload` imzasını şuna çevir:

```python
def _maybe_auto_upload(*, eng, short_id: int, channel, picked_score: float | None,
                       log, yt_creds_root: Path, claude_path: str,
                       model: str, cooldown_minutes: int = 5,
                       secrets_path: Path | None = None) -> None:
    """Post-render hook: if channel opts in, evaluate gates + run upload."""
    if channel.youtube is None or not channel.youtube.auto_upload:
        return
    # Token refresh için proxy session hazır olsun (varsa)
    proxy_session = None
    if secrets_path:
        from short_bot.youtube.proxy import (
            load_channel_proxy_url, build_proxied_requests_session,
        )
        proxy_url = load_channel_proxy_url(channel.slug, secrets_path)
        if proxy_url:
            proxy_session = build_proxied_requests_session(proxy_url)
    creds = _yt_auth.load_credentials(
        yt_creds_root, channel.slug, proxy_session=proxy_session,
    )
    if creds is None:
        log.info("[YT] auto-upload atlandı — kanal bağlanmamış (token.json yok)")
        return
    last_at = get_last_youtube_upload_at(eng)
    decision = should_auto_upload(
        channel=channel, picked_score=picked_score,
        last_upload_at=last_at, cooldown_minutes=cooldown_minutes,
    )
    if not decision.eligible:
        log.info(f"[YT] auto-upload atlandı — {decision.reason}")
        return
    log.info(f"[YT] auto-upload başlıyor (short {short_id})")
    try:
        result = run_auto_upload(
            eng=eng, short_id=short_id, channel=channel,
            credentials=creds, claude_path=claude_path, model=model,
            secrets_path=secrets_path,
        )
        log.info(f"[YT] auto-upload başarılı: {result.video_url}")
    except Exception as e:
        log.warning(f"[YT] auto-upload hatası: {e}")
```

- [ ] **Step 2: İki çağrı yerinde secrets_path geçir**

`pipeline.py` 517-525 ve 661-669 satırlarındaki `_maybe_auto_upload(...)` çağrılarına `secrets_path=` ekle. Hangi değişken kullanılacak: pipeline'da zaten secrets_path benzeri var (`secrets_path = Path("data/secrets.yaml").resolve()` veya benzeri). Eğer yoksa, yt_creds_root.parent / "secrets.yaml" mantıklı default:

```python
secrets_path = (Path(eng.url.database).parent / "secrets.yaml").resolve() \
    if eng.url.database else Path("data/secrets.yaml").resolve()
_maybe_auto_upload(
    eng=eng, short_id=short_id, channel=channel,
    picked_score=picked_score, log=log,
    yt_creds_root=yt_creds_root,
    claude_path=settings.claude_cli_path,
    model=settings.claude_models.get("default", "haiku"),
    secrets_path=secrets_path,
)
```

(Mevcut iki `_maybe_auto_upload` çağrısının her birinde aynı pattern.)

- [ ] **Step 3: Smoke pipeline test'i çalıştır**

Run: `pytest tests/ -v -k "pipeline or auto_upload" --tb=short`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/short_bot/pipeline.py
git commit -m "feat(pipeline): _maybe_auto_upload secrets_path parametresi (proxy yolu)"
```

---

## Task 14: web/routes/channel_edit.py — proxy form save

**Files:**
- Modify: `src/short_bot/web/routes/channel_edit.py` (yt_present bloğu sonrası)
- Test: `tests/test_channel_edit_proxy.py` (yeni)

- [ ] **Step 1: Failing test yaz**

`tests/test_channel_edit_proxy.py`:

```python
"""POST /channels/<slug>/edit yt_proxy_url alanını secrets.yaml'a yazar."""
from __future__ import annotations

import yaml
import pytest
from unittest.mock import patch


@pytest.fixture
def web_client(tmp_path, monkeypatch):
    # Çevreyi tmp_path'a yönlendir, in-memory db, vb.
    # NOT: Mevcut web app fixture'ını yeniden kullan — projede var olan
    # `client` fixture'ı varsa onu import et. Yoksa minimal app oluştur.
    from short_bot.web import create_app
    app = create_app({
        "TESTING": True,
        "SECRETS_PATH": str(tmp_path / "secrets.yaml"),
        "CHANNELS_DIR": str(tmp_path / "channels"),
    })
    return app.test_client(), tmp_path


def test_post_edit_writes_proxy_to_secrets(web_client, monkeypatch):
    """yt_proxy_url='http://h:1' verilince secrets.yaml channel_proxies'e yazılır."""
    client, tmp_path = web_client
    # Mevcut bir kanal yaml setup'ı — çevre fixture'ları gerek
    # ... (proje fixture'ı proje-spesifik, plan'da inline pattern göstermek
    # yerine grep'le mevcut test_channel_edit_*.py pattern'ini referans al)
    # NOT: Bu testin tam form parametre listesi mevcut channel_edit POST
    # endpoint'inin zorunlu alanlarına bağlı. Eksik alanlar için
    # mevcut tests/test_channel_edit_*.py dosyasındaki minimal payload'u
    # referans al.
    pytest.skip("İmpl tarafından doldurulacak: mevcut test_channel_edit fixture'larını kullan")
```

> **Not:** Bu test'in tam payload'u mevcut `tests/test_channel_edit_*.py` dosyalarındaki minimal POST body örnek alınarak yazılır. İmplementasyon adımında, mevcut bir test'in pattern'ini referans alıp formu yt_proxy_url ile genişlet.

- [ ] **Step 2: Run — skip (impl bekliyor)**

Run: `pytest tests/test_channel_edit_proxy.py -v`
Expected: SKIP (impl yapana kadar)

- [ ] **Step 3: channel_edit.py'da yt_proxy_url okuma + update_channel_proxy çağrısı**

`src/short_bot/web/routes/channel_edit.py` içinde mevcut `yt_present` bloğunun (212-230 civarı) **sonrasına**, `new_youtube = ...` atamasından sonra:

```python
# Proxy URL — secrets.yaml'a yazılır (kanal yaml'a değil — credentials güvenliği)
yt_proxy_url = (request.form.get("yt_proxy_url") or "").strip() or None
from short_bot.secrets_io import update_channel_proxy
from flask import current_app
secrets_path = Path(current_app.config.get("SECRETS_PATH")
                    or "data/secrets.yaml")
update_channel_proxy(secrets_path, cfg.slug, yt_proxy_url)
```

(Path import'u dosyada zaten varsa tekrar ekleme.)

- [ ] **Step 4: Mevcut bir test'i referans al + skip kaldır**

`tests/test_channel_edit_proxy.py`'da skip'i kaldır, mevcut `tests/test_channel_edit_*.py`'lardan bir test'in payload'unu kopyala, yt_proxy_url alanını ekle, response 200/302 sonrası `secrets.yaml` dosyasını oku ve assert et:

```python
def test_post_edit_writes_proxy_to_secrets(web_client):
    client, tmp_path = web_client
    # ... mevcut test'in base payload'unu kullan ...
    payload = {
        # ... zorunlu alanlar ...
        "yt_proxy_url": "http://test:s3@proxy.local:8080",
    }
    r = client.post("/channels/<slug>/edit", data=payload, follow_redirects=False)
    assert r.status_code in (200, 302)
    secrets = yaml.safe_load((tmp_path / "secrets.yaml").read_text(encoding="utf-8"))
    assert secrets["channel_proxies"]["<slug>"] == "http://test:s3@proxy.local:8080"


def test_post_edit_empty_proxy_removes_key(web_client):
    client, tmp_path = web_client
    secrets_path = tmp_path / "secrets.yaml"
    secrets_path.write_text(
        "channel_proxies:\n  <slug>: http://old:1\n", encoding="utf-8",
    )
    payload = {
        # ... zorunlu alanlar ...
        "yt_proxy_url": "",
    }
    client.post("/channels/<slug>/edit", data=payload)
    secrets = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    assert "channel_proxies" not in secrets
```

- [ ] **Step 5: Run — pass**

Run: `pytest tests/test_channel_edit_proxy.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/web/routes/channel_edit.py tests/test_channel_edit_proxy.py
git commit -m "feat(web): yt_proxy_url alanı secrets.yaml'a yazılır"
```

---

## Task 15: web/templates/channel_edit.html — Proxy URL input + Test Et butonu

**Files:**
- Modify: `src/short_bot/web/templates/channel_edit.html`

- [ ] **Step 1: Mevcut YouTube section'ını bul**

Run: `grep -n "yt_auto_upload\|yt_category_id\|YouTube" src/short_bot/web/templates/channel_edit.html | head -10`

YouTube ile ilgili form bölümünün sonunu bul (genelde `<fieldset>` veya `<section>` kapanışı önce).

- [ ] **Step 2: Proxy alanını ekle**

YouTube section'ın sonuna (kapanan tag'den önce):

```html
<div class="form-row">
  <label for="yt_proxy_url">
    YouTube Upload Proxy URL
    <small>(opsiyonel — same-IP riskini düşürmek için)</small>
  </label>
  <input type="text" id="yt_proxy_url" name="yt_proxy_url"
         value="{{ proxy_url|default('', true)|e }}"
         placeholder="http://user:pass@host:8080  veya  socks5://host:1080">
  <button type="button" id="btn-test-proxy" class="secondary">Test Et</button>
  <span id="proxy-test-result" style="margin-left: 8px;"></span>
  <small style="display:block; color:#888; margin-top:4px;">
    secrets.yaml dosyasında saklanır, kanal yaml'a yazılmaz.
  </small>
</div>

<script>
(function() {
  const btn = document.getElementById('btn-test-proxy');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    const input = document.getElementById('yt_proxy_url');
    const url = (input.value || '').trim();
    const slug = '{{ cfg.slug }}';
    const el = document.getElementById('proxy-test-result');
    el.textContent = 'Test ediliyor…';
    el.className = '';
    try {
      const r = await fetch(`/channels/${slug}/test-proxy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proxy_url: url }),
      });
      const j = await r.json();
      if (j.ok) {
        el.textContent = `✓ Çalışıyor — IP: ${j.ip}` + (j.country ? ` (${j.country})` : '');
        el.className = 'ok';
      } else {
        el.textContent = `✗ ${j.error}`;
        el.className = 'err';
      }
    } catch (e) {
      el.textContent = `✗ ${e.message}`;
      el.className = 'err';
    }
  });
})();
</script>

<style>
#proxy-test-result.ok  { color: #22c55e; }
#proxy-test-result.err { color: #ef4444; }
</style>
```

- [ ] **Step 3: channel_edit.py GET handler proxy_url context'i geçir**

`channel_edit.py`'da template render eden GET handler'ı bul. Render context dict'ine ekle:

```python
from short_bot.youtube.proxy import load_channel_proxy_url
proxy_url = load_channel_proxy_url(slug, secrets_path) or ""
return render_template("channel_edit.html", cfg=cfg, proxy_url=proxy_url, ...)
```

- [ ] **Step 4: Manuel UI smoke test**

Run: `python -m short_bot serve` (veya mevcut başlatma komutu)
Tarayıcı: `http://localhost:5005/channels/<slug>/edit`
Beklenen: Proxy URL alanı görünür, Test Et butonu var. Boş URL'de butona basınca "✗ proxy URL boş" çıkar.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/web/templates/channel_edit.html src/short_bot/web/routes/channel_edit.py
git commit -m "feat(web/ui): kanal edit sayfasına Proxy URL alanı + Test Et butonu"
```

---

## Task 16: `POST /channels/<slug>/test-proxy` endpoint

**Files:**
- Modify: `src/short_bot/web/routes/youtube.py` (test_proxy endpoint ekle)
- Test: `tests/test_test_proxy_endpoint.py` (yeni)

- [ ] **Step 1: Failing testleri yaz**

`tests/test_test_proxy_endpoint.py`:

```python
"""POST /channels/<slug>/test-proxy endpoint testleri."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture
def client(tmp_path):
    from short_bot.web import create_app
    app = create_app({
        "TESTING": True,
        "SECRETS_PATH": str(tmp_path / "secrets.yaml"),
    })
    return app.test_client()


def test_test_proxy_empty_url_returns_400(client):
    r = client.post("/channels/galatasaray/test-proxy",
                    json={"proxy_url": ""})
    assert r.status_code == 400
    assert r.get_json() == {"ok": False, "error": "proxy URL boş"}


def test_test_proxy_success_returns_ip(client):
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"ip": "1.2.3.4"}
    fake_resp.status_code = 200
    fake_resp.text = "Germany"
    fake_session = MagicMock()
    fake_session.get.return_value = fake_resp

    with patch("short_bot.web.routes.youtube.build_proxied_requests_session",
               return_value=fake_session):
        r = client.post("/channels/g/test-proxy",
                        json={"proxy_url": "http://h:1"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["ip"] == "1.2.3.4"


def test_test_proxy_credentials_redacted_in_error(client):
    """Hata mesajı içinde user:pass olsa bile response'a sızmamalı."""
    fake_session = MagicMock()
    fake_session.get.side_effect = Exception(
        "connection failed for http://alice:s3cret@bad:1080"
    )
    with patch("short_bot.web.routes.youtube.build_proxied_requests_session",
               return_value=fake_session):
        r = client.post("/channels/g/test-proxy",
                        json={"proxy_url": "http://alice:s3cret@bad:1080"})
    body = r.get_json()
    assert body["ok"] is False
    assert "alice" not in body["error"]
    assert "s3cret" not in body["error"]
    assert "***" in body["error"]
```

- [ ] **Step 2: Run — fail**

Run: `pytest tests/test_test_proxy_endpoint.py -v`
Expected: FAIL — endpoint 404

- [ ] **Step 3: Endpoint'i ekle**

`src/short_bot/web/routes/youtube.py` içine (mevcut blueprint'e):

```python
from flask import jsonify, request

from short_bot.youtube.proxy import (
    build_proxied_requests_session, _redact_err,
)


@bp.post("/channels/<slug>/test-proxy")
def test_proxy(slug):
    payload = request.get_json(silent=True) or {}
    proxy_url = (payload.get("proxy_url") or "").strip()
    if not proxy_url:
        return jsonify(ok=False, error="proxy URL boş"), 400
    try:
        sess = build_proxied_requests_session(proxy_url)
        r = sess.get("https://api.ipify.org?format=json", timeout=10)
        ip = r.json().get("ip")
        country = None
        try:
            r2 = sess.get(
                f"https://ipapi.co/{ip}/country_name/", timeout=5,
            )
            if r2.status_code == 200:
                country = r2.text.strip()
        except Exception:
            pass
        return jsonify(ok=True, ip=ip, country=country)
    except Exception as e:
        return jsonify(ok=False, error=_redact_err(e)[:200])
```

(Blueprint adı `bp` örnek — mevcut youtube.py'da hangi isim kullanılıyorsa onu kullan. Aynı dosyada başka `@bp.<verb>` route'ları varsa pattern'i izle.)

- [ ] **Step 4: Run — pass**

Run: `pytest tests/test_test_proxy_endpoint.py -v`
Expected: 3 PASS

- [ ] **Step 5: Manuel UI smoke**

Tarayıcı: kanal edit sayfasında geçerli bir proxy URL gir, "Test Et" basıp dönen IP'yi gör.

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/web/routes/youtube.py tests/test_test_proxy_endpoint.py
git commit -m "feat(web): POST /channels/<slug>/test-proxy endpoint (api.ipify probe)"
```

---

## Task 17: Manuel End-to-End smoke test

**Files:** (kod değişikliği yok — manuel doğrulama)

- [ ] **Step 1: secrets.yaml'a real proxy URL ekle**

```yaml
channel_proxies:
  <test-slug>: http://<real-proxy>:port
```

- [ ] **Step 2: Token refresh smoke (proxy üzerinden)**

```python
# python -c
from short_bot.youtube import auth, proxy
sess = proxy.build_proxied_requests_session("http://<real-proxy>:port")
creds = auth.load_credentials(Path("data/youtube_credentials"), "<test-slug>",
                              proxy_session=sess)
print("token loaded:", creds is not None)
```

Expected: token yüklenir, `creds.expired=False` (refresh başarılı).

- [ ] **Step 3: Pipeline ile gerçek upload (test kanalı)**

Run: `python -m short_bot run --channel <test-slug>` (veya mevcut komut)
Expected:
- Log'da `using proxy http://***:***@host:port` (redacted)
- Upload başarılı, `youtube_uploads.status = 'success'`
- YouTube Studio'da yeni video private/unlisted

- [ ] **Step 4: Proxy fail simülasyonu**

Geçersiz proxy URL ile aynı pipeline'i çalıştır. Beklenen:
- `UploadAbortError` log'a düşer
- `youtube_uploads.status = 'proxy_failed'`
- Hata mesajı redacted (kullanıcı:şifre yok)

- [ ] **Step 5: Final commit (changelog/docs varsa güncelle)**

```bash
git add CHANGELOG.md   # varsa
git commit -m "docs: per-channel YouTube proxy support — feature complete"
```

---

## Self-Review Checklist (yazar olarak)

**Spec coverage:**
- [x] Veri modeli (secrets.yaml channel_proxies) → Task 4 (load), Task 7 (write)
- [x] proxy.py (parse, _redact, _redact_err, load, build_http, build_session) → Task 2-6
- [x] secrets_io.update_channel_proxy → Task 7
- [x] auth.py iki fonksiyon → Task 8, 9
- [x] uploader.py upload_video → Task 10
- [x] data_api.py iki fonksiyon → Task 11
- [x] auto_upload UploadAbortError + proxy_failed → Task 12
- [x] pipeline.py secrets_path geçişi → Task 13
- [x] Web UI form → Task 15
- [x] Web form save → Task 14
- [x] Test endpoint → Task 16
- [x] PySocks dep → Task 1
- [x] Manuel smoke → Task 17

**Placeholder taraması:** Task 14 ve 15'te "mevcut fixture/test pattern'ini referans al" dedim — bu acceptable (test kütüphanesinin proje-spesifik fixture'larını burada inline yeniden yazmak DRY ihlali olur). Diğer hiçbir adımda TBD/TODO yok.

**Type/imza tutarlılığı:**
- `proxy_session` adı — `auth.py:load_credentials` Task 8 ✓; `pipeline.py` Task 13 ✓
- `http=None` kwarg — uploader Task 10, auth Task 9, data_api Task 11 ✓
- `secrets_path: Path | None = None` — auto_upload Task 12, pipeline Task 13 ✓
- `UploadAbortError` — Task 12'de tanımlı, Task 17 manual smoke'ta referans veriliyor ✓

**Scope:** Tek implementation cycle. Her task küçük (5-15 dk), kendi commit'i, kendi test'i.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-08-channel-proxy.md`. Two execution options:

1. **Subagent-Driven (recommended)** — Her task için fresh subagent dispatch, iki aşamalı review, hızlı iterasyon
2. **Inline Execution** — Bu session'da executing-plans skill ile, batch checkpoint review

Which approach?
