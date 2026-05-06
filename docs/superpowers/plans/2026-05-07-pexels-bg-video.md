# Pexels Animated Background Video Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render a per-channel opt-in 9:16 short with the existing archetype frame scaled (0.88x or 0.80x) and centered over a Pexels stock video clip used as a blurred ambient background.

**Architecture:** Pexels client downloads a short mp4 keyed by archetype-pool query and caches it. Pipeline asset stage adds an optional `bg_video_path`. Composer gains a 2-input ffmpeg path that blurs/dims the bg, scales the foreground PNG sequence, and overlays them centered. API key is read from env var or git-ignored `data/secrets.yaml` — never `config/settings.yaml`.

**Tech Stack:** Python 3.14, Pydantic v2, Flask, Jinja2, htmx, FFmpeg, Pexels Videos API, pytest, requests.

**Spec:** `docs/superpowers/specs/2026-05-07-pexels-bg-video-design.md`

---

## File Structure

**Create:**
- `src/short_bot/pexels.py` — Pexels client + archetype query pool + key resolver
- `tests/test_pexels.py` — Pexels client unit tests
- `tests/test_composer_bg_video.py` — composer 2-input path tests

**Modify:**
- `.gitignore` — add `data/secrets.yaml`
- `src/short_bot/config.py` — `BgVideoConfig`, `ChannelConfig.bg_video`, `load_channel`/`save_channel` round-trip
- `src/short_bot/composer.py` — `compose_video` gains `bg_video_path`, `bg_blur_px`, `bg_dim`, `fg_scale` params
- `src/short_bot/pipeline.py` — RSS asset stage searches/downloads Pexels video, passes to composer
- `src/short_bot/web/routes/settings.py` — read/write `data/secrets.yaml` for `pexels_api_key`
- `src/short_bot/web/templates/settings.html.j2` — masked password input + "değiştir" toggle
- `src/short_bot/web/routes/channel_edit.py` — read/write `bg_video` block
- `src/short_bot/web/routes/channel_new.py` — write `bg_video` defaults if submitted
- `src/short_bot/web/templates/channels/edit.html.j2` — bg_video collapsible section
- `src/short_bot/web/templates/channels/new.html.j2` — bg_video opt-in toggle
- `tests/test_config.py` — `bg_video` parse + round-trip
- `tests/test_pipeline.py` — Pexels graceful fallback when key missing
- `tests/test_web_settings.py` — secrets.yaml read/write
- `tests/test_web_channel_edit.py` (or whichever exists) — bg_video form binding

**Test:**
- All under `tests/` matching the modules above.

---

## Task 1: Add `data/secrets.yaml` to .gitignore

This must land BEFORE any code that writes the file, so an accidental commit can't leak the key.

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Append entry**

Edit `.gitignore` — append at the end:

```
# Secrets (Pexels API key, etc.) — never commit
data/secrets.yaml
```

- [ ] **Step 2: Verify**

Run: `git check-ignore -v data/secrets.yaml`
Expected output: line containing `data/secrets.yaml` (file doesn't have to exist, the rule must match).

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore data/secrets.yaml for Pexels API key storage"
```

---

## Task 2: Pexels secret resolver (no client yet)

Standalone function: read `data/secrets.yaml` if it exists, return the API key from env var or that file. Drives every later integration point.

**Files:**
- Create: `src/short_bot/pexels.py`
- Create: `tests/test_pexels.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pexels.py`:

```python
import os
from pathlib import Path

import pytest

from short_bot.pexels import load_secrets, resolve_pexels_api_key


def test_load_secrets_returns_empty_dict_when_file_missing(tmp_path):
    assert load_secrets(tmp_path / "missing.yaml") == {}


def test_load_secrets_parses_yaml(tmp_path):
    p = tmp_path / "secrets.yaml"
    p.write_text("pexels_api_key: abc123\n", encoding="utf-8")
    assert load_secrets(p) == {"pexels_api_key": "abc123"}


def test_resolve_returns_env_var_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "from-env")
    assert resolve_pexels_api_key({"pexels_api_key": "from-file"}) == "from-env"


def test_resolve_falls_back_to_secrets_dict(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert resolve_pexels_api_key({"pexels_api_key": "from-file"}) == "from-file"


def test_resolve_returns_empty_string_when_neither_set(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert resolve_pexels_api_key({}) == ""
```

- [ ] **Step 2: Run test, expect FAIL (module not found)**

Run: `python -m pytest tests/test_pexels.py -v`
Expected: ImportError / ModuleNotFoundError for `short_bot.pexels`.

- [ ] **Step 3: Create minimal module**

Create `src/short_bot/pexels.py`:

```python
"""Pexels Videos API client + archetype-pool query selector + secret resolver."""
from __future__ import annotations

import os
from pathlib import Path

import yaml


def load_secrets(secrets_path: Path) -> dict:
    """Return parsed YAML dict from secrets_path, or {} if file missing/empty."""
    p = Path(secrets_path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def resolve_pexels_api_key(secrets: dict) -> str:
    """Resolve the Pexels API key. Env var PEXELS_API_KEY beats secrets dict."""
    return os.environ.get("PEXELS_API_KEY") or secrets.get("pexels_api_key") or ""
```

- [ ] **Step 4: Run test, expect PASS**

Run: `python -m pytest tests/test_pexels.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/pexels.py tests/test_pexels.py
git commit -m "feat(pexels): add secret resolver (env var or data/secrets.yaml)"
```

---

## Task 3: Pexels archetype query pool

Static dict mapping each archetype to 3 search queries; `pick_query_for_archetype` picks one randomly.

**Files:**
- Modify: `src/short_bot/pexels.py`
- Modify: `tests/test_pexels.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pexels.py`:

```python
from short_bot.pexels import ARCHETYPE_BG_QUERIES, pick_query_for_archetype


def test_archetype_pool_covers_all_seven_archetypes():
    expected = {"newscast", "tabloid", "magazine", "kinetic",
                "dark-tech", "stadium", "meme"}
    assert set(ARCHETYPE_BG_QUERIES.keys()) == expected


def test_each_archetype_pool_has_at_least_three_queries():
    for arch, queries in ARCHETYPE_BG_QUERIES.items():
        assert len(queries) >= 3, f"{arch} has fewer than 3 queries"


def test_pick_query_returns_member_of_pool():
    q = pick_query_for_archetype("newscast")
    assert q in ARCHETYPE_BG_QUERIES["newscast"]


def test_pick_query_unknown_archetype_falls_back_to_generic():
    q = pick_query_for_archetype("nonexistent-xyz")
    assert q == "abstract motion background"
```

- [ ] **Step 2: Run, expect FAIL (ImportError on ARCHETYPE_BG_QUERIES)**

Run: `python -m pytest tests/test_pexels.py -v`
Expected: ImportError.

- [ ] **Step 3: Add the constants and picker**

Append to `src/short_bot/pexels.py`:

```python
import random


ARCHETYPE_BG_QUERIES: dict[str, list[str]] = {
    "newscast":  ["newsroom blur", "studio lights motion", "news ticker abstract"],
    "tabloid":   ["paparazzi flash", "neon city night", "magazine pages turning"],
    "magazine":  ["soft fabric texture", "ink water swirl", "warm bokeh"],
    "kinetic":   ["geometric motion", "abstract neon lines", "particle wave"],
    "dark-tech": ["circuit board glow", "matrix code rain", "server room cyan"],
    "stadium":   ["stadium lights night", "crowd cheering blur", "grass pitch zoom"],
    "meme":      ["confetti pop", "colorful gradient swirl", "cartoon background"],
}


def pick_query_for_archetype(archetype: str) -> str:
    """Random pick from the pool. Unknown archetype → generic fallback."""
    pool = ARCHETYPE_BG_QUERIES.get(archetype)
    if not pool:
        return "abstract motion background"
    return random.choice(pool)
```

- [ ] **Step 4: Run, expect PASS**

Run: `python -m pytest tests/test_pexels.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/pexels.py tests/test_pexels.py
git commit -m "feat(pexels): add archetype-pool query selector"
```

---

## Task 4: Pexels search_videos client

Wraps `https://api.pexels.com/videos/search`. Returns `[]` on any failure (no exceptions bubble) so pipeline can fallback gracefully.

**Files:**
- Modify: `src/short_bot/pexels.py`
- Modify: `tests/test_pexels.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pexels.py`:

```python
from unittest.mock import patch, MagicMock

from short_bot.pexels import PexelsCandidate, search_videos


def _mock_response(json_payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_payload
    return r


def test_search_videos_returns_candidates_from_api_payload():
    payload = {
        "videos": [
            {
                "id": 111,
                "duration": 12,
                "video_files": [
                    {"link": "https://x/lo.mp4", "width": 540,  "height": 960,  "file_type": "video/mp4"},
                    {"link": "https://x/hd.mp4", "width": 1080, "height": 1920, "file_type": "video/mp4"},
                ],
            },
            {
                "id": 222,
                "duration": 8,
                "video_files": [
                    {"link": "https://y/hd.mp4", "width": 720, "height": 1280, "file_type": "video/mp4"},
                ],
            },
        ]
    }
    with patch("short_bot.pexels.requests.get", return_value=_mock_response(payload)):
        out = search_videos("query", api_key="KEY", max_results=5)
    assert len(out) == 2
    assert out[0].id == 111
    # Picks the highest-resolution mp4 link from each candidate
    assert out[0].url == "https://x/hd.mp4"
    assert out[0].duration_s == 12
    assert out[1].url == "https://y/hd.mp4"


def test_search_videos_returns_empty_on_http_error():
    with patch("short_bot.pexels.requests.get", return_value=_mock_response({}, status=429)):
        out = search_videos("q", api_key="KEY")
    assert out == []


def test_search_videos_returns_empty_on_request_exception():
    import requests
    with patch("short_bot.pexels.requests.get", side_effect=requests.RequestException("boom")):
        out = search_videos("q", api_key="KEY")
    assert out == []


def test_search_videos_returns_empty_when_no_videos_field():
    with patch("short_bot.pexels.requests.get", return_value=_mock_response({"videos": []})):
        out = search_videos("q", api_key="KEY")
    assert out == []


def test_search_videos_skips_candidates_without_mp4_files():
    payload = {"videos": [{"id": 333, "duration": 5, "video_files": []}]}
    with patch("short_bot.pexels.requests.get", return_value=_mock_response(payload)):
        out = search_videos("q", api_key="KEY")
    assert out == []


def test_search_videos_passes_authorization_header_and_orientation():
    captured = {}
    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["params"] = params
        return _mock_response({"videos": []})
    with patch("short_bot.pexels.requests.get", side_effect=fake_get):
        search_videos("query", api_key="MYKEY", max_results=3)
    assert captured["headers"]["Authorization"] == "MYKEY"
    assert captured["params"]["query"] == "query"
    assert captured["params"]["orientation"] == "portrait"
    assert captured["params"]["per_page"] == 3
```

- [ ] **Step 2: Run, expect FAIL (search_videos / PexelsCandidate not defined)**

Run: `python -m pytest tests/test_pexels.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement search_videos**

Append to `src/short_bot/pexels.py` (top imports first, then code):

Add to imports block at top of the file (combine with existing):

```python
import logging
from typing import Literal

import requests
from pydantic import BaseModel
```

Append to the bottom of the file:

```python
logger = logging.getLogger(__name__)

_PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"


class PexelsCandidate(BaseModel):
    id: int
    url: str          # highest-resolution mp4 link
    duration_s: int


def _pick_best_mp4(video_files: list[dict]) -> str | None:
    """From a Pexels video's file list, return the highest-resolution mp4 link."""
    mp4s = [
        f for f in video_files
        if f.get("file_type") == "video/mp4" and f.get("link")
    ]
    if not mp4s:
        return None
    mp4s.sort(key=lambda f: (f.get("width", 0) * f.get("height", 0)), reverse=True)
    return mp4s[0]["link"]


def search_videos(
    query: str,
    api_key: str,
    *,
    max_results: int = 5,
    orientation: Literal["portrait", "landscape", "square"] = "portrait",
    timeout_s: int = 15,
) -> list[PexelsCandidate]:
    """Search Pexels Videos. Returns [] on any error or empty result."""
    if not api_key:
        return []
    try:
        r = requests.get(
            _PEXELS_SEARCH_URL,
            headers={"Authorization": api_key},
            params={"query": query, "orientation": orientation, "per_page": max_results},
            timeout=timeout_s,
        )
    except requests.RequestException as e:
        logger.warning(f"pexels search request failed: {e}")
        return []
    if r.status_code != 200:
        logger.warning(f"pexels search HTTP {r.status_code}: {r.text[:200]}")
        return []
    payload = r.json() or {}
    out: list[PexelsCandidate] = []
    for v in payload.get("videos", []):
        url = _pick_best_mp4(v.get("video_files", []))
        if not url:
            continue
        out.append(PexelsCandidate(
            id=int(v.get("id", 0)),
            url=url,
            duration_s=int(v.get("duration", 0)),
        ))
    return out
```

- [ ] **Step 4: Run, expect PASS**

Run: `python -m pytest tests/test_pexels.py -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/pexels.py tests/test_pexels.py
git commit -m "feat(pexels): add search_videos client with graceful failure"
```

---

## Task 5: Pexels download_video with cache

Idempotent download to `cache_dir/<sha1[:16]>.mp4`. Returns cached path on success, None on failure.

**Files:**
- Modify: `src/short_bot/pexels.py`
- Modify: `tests/test_pexels.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pexels.py`:

```python
from short_bot.pexels import download_video


def test_download_video_returns_cached_path_when_already_present(tmp_path):
    cache = tmp_path / "videos"
    cache.mkdir()
    # Pre-create a cached file matching the sha1 of the URL we'll request
    import hashlib
    url = "https://example.com/clip.mp4"
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    cached = cache / f"{key}.mp4"
    cached.write_bytes(b"already-here")

    with patch("short_bot.pexels.requests.get") as gm:
        out = download_video(url, cache)
    assert out == cached
    gm.assert_not_called()


def test_download_video_writes_response_body_to_cache(tmp_path):
    cache = tmp_path / "videos"
    fake = MagicMock()
    fake.status_code = 200
    fake.iter_content.return_value = iter([b"chunk1", b"chunk2"])
    fake.__enter__ = lambda self: self
    fake.__exit__ = lambda *a: None

    with patch("short_bot.pexels.requests.get", return_value=fake):
        out = download_video("https://example.com/x.mp4", cache)
    assert out is not None
    assert out.exists()
    assert out.read_bytes() == b"chunk1chunk2"


def test_download_video_returns_none_on_http_error(tmp_path):
    fake = MagicMock()
    fake.status_code = 404
    fake.__enter__ = lambda self: self
    fake.__exit__ = lambda *a: None
    with patch("short_bot.pexels.requests.get", return_value=fake):
        out = download_video("https://example.com/x.mp4", tmp_path / "videos")
    assert out is None


def test_download_video_returns_none_on_request_exception(tmp_path):
    with patch("short_bot.pexels.requests.get",
               side_effect=requests.RequestException("boom")):
        out = download_video("https://example.com/x.mp4", tmp_path / "videos")
    assert out is None
```

Add `import requests` near the top of the test module if not already present (it is — added in Task 4 indirectly through patches; ensure top-of-file: `import requests`).

- [ ] **Step 2: Run, expect FAIL (download_video not defined)**

Run: `python -m pytest tests/test_pexels.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement download_video**

Add to imports at top of `src/short_bot/pexels.py`:

```python
import hashlib
```

Append to the bottom:

```python
def download_video(url: str, cache_dir: Path, *, timeout_s: int = 60) -> Path | None:
    """Stream-download to cache_dir/<sha1>.mp4. Idempotent. Returns None on failure."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    out = cache_dir / f"{key}.mp4"
    if out.exists() and out.stat().st_size > 0:
        return out
    try:
        with requests.get(url, stream=True, timeout=timeout_s) as r:
            if r.status_code != 200:
                logger.warning(f"pexels download HTTP {r.status_code} for {url[:80]}")
                return None
            with open(out, "wb") as fh:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        fh.write(chunk)
    except requests.RequestException as e:
        logger.warning(f"pexels download failed for {url[:80]}: {e}")
        # Clean up partial file if any
        if out.exists():
            out.unlink(missing_ok=True)
        return None
    return out
```

- [ ] **Step 4: Run, expect PASS**

Run: `python -m pytest tests/test_pexels.py -v`
Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/pexels.py tests/test_pexels.py
git commit -m "feat(pexels): add cached video downloader"
```

---

## Task 6: `BgVideoConfig` Pydantic model

Validates the YAML block. `scale` is constrained to exactly `0.88` or `0.80`.

**Files:**
- Modify: `src/short_bot/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py` (anywhere after the existing imports):

```python
def test_bg_video_config_defaults():
    from short_bot.config import BgVideoConfig
    cfg = BgVideoConfig()
    assert cfg.enabled is False
    assert cfg.scale == 0.88
    assert cfg.blur_px == 30
    assert cfg.dim == 0.4


def test_bg_video_config_accepts_valid_scale():
    from short_bot.config import BgVideoConfig
    BgVideoConfig(scale=0.88)
    BgVideoConfig(scale=0.80)


def test_bg_video_config_rejects_invalid_scale():
    from pydantic import ValidationError
    from short_bot.config import BgVideoConfig
    with pytest.raises(ValidationError):
        BgVideoConfig(scale=0.5)
    with pytest.raises(ValidationError):
        BgVideoConfig(scale=1.0)


def test_bg_video_config_blur_range():
    from pydantic import ValidationError
    from short_bot.config import BgVideoConfig
    BgVideoConfig(blur_px=0)
    BgVideoConfig(blur_px=80)
    with pytest.raises(ValidationError):
        BgVideoConfig(blur_px=-1)
    with pytest.raises(ValidationError):
        BgVideoConfig(blur_px=81)


def test_bg_video_config_dim_range():
    from pydantic import ValidationError
    from short_bot.config import BgVideoConfig
    BgVideoConfig(dim=0.0)
    BgVideoConfig(dim=1.0)
    with pytest.raises(ValidationError):
        BgVideoConfig(dim=-0.1)
    with pytest.raises(ValidationError):
        BgVideoConfig(dim=1.5)
```

If `pytest` isn't already imported in `tests/test_config.py`, add it at the top.

- [ ] **Step 2: Run, expect FAIL (BgVideoConfig not defined)**

Run: `python -m pytest tests/test_config.py -k bg_video -v`
Expected: ImportError.

- [ ] **Step 3: Add BgVideoConfig model to config.py**

In `src/short_bot/config.py`, after the `YoutubeChannelConfig` class definition (around line 41), add:

```python
class BgVideoConfig(BaseModel):
    enabled: bool = False
    scale: Literal[0.88, 0.80] = 0.88
    blur_px: int = Field(ge=0, le=80, default=30)
    dim: float = Field(ge=0.0, le=1.0, default=0.4)
```

Update the existing import at the top:

```python
from pydantic import BaseModel, Field
```

(replace the `from pydantic import BaseModel` line — `Field` is now needed too).

- [ ] **Step 4: Run, expect PASS**

Run: `python -m pytest tests/test_config.py -k bg_video -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/config.py tests/test_config.py
git commit -m "feat(config): add BgVideoConfig schema with constrained scale"
```

---

## Task 7: Wire `bg_video` into `ChannelConfig` + load/save round-trip

Optional `bg_video` field on `ChannelConfig`; YAML parser populates it from a `bg_video:` block; saver writes it back when present and `enabled=true` (omitted otherwise to keep YAML clean).

**Files:**
- Modify: `src/short_bot/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def _minimal_channel_yaml(bg_video_block: str = "") -> str:
    """Return a YAML body that parses to a valid channel; optionally append a bg_video block."""
    return f"""\
slug: test-bg
name: Test BG
keywords: [x]
language: tr
schedule_cron: 0 * * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors:
  primary: '#c81e1e'
  accent: '#ffea3b'
  bg_gradient: ['#000000', '#111111']
handle: '@x'
output_dir: output/test-bg
enabled: true
cta:
  enabled: false
  text: ''
  icons: []
  duration_s: 0
  show_handle: false
{bg_video_block}
"""


def test_load_channel_bg_video_absent_yields_none(tmp_path):
    from short_bot.config import load_channel
    p = tmp_path / "c.yaml"
    p.write_text(_minimal_channel_yaml(), encoding="utf-8")
    c = load_channel(p)
    assert c.bg_video is None


def test_load_channel_bg_video_block_parses(tmp_path):
    from short_bot.config import load_channel
    p = tmp_path / "c.yaml"
    block = "bg_video:\n  enabled: true\n  scale: 0.80\n  blur_px: 20\n  dim: 0.3\n"
    p.write_text(_minimal_channel_yaml(block), encoding="utf-8")
    c = load_channel(p)
    assert c.bg_video is not None
    assert c.bg_video.enabled is True
    assert c.bg_video.scale == 0.80
    assert c.bg_video.blur_px == 20
    assert c.bg_video.dim == 0.3


def test_save_channel_round_trip_preserves_bg_video(tmp_path):
    import yaml
    from short_bot.config import load_channel, save_channel
    src = tmp_path / "c.yaml"
    block = "bg_video:\n  enabled: true\n  scale: 0.88\n  blur_px: 30\n  dim: 0.4\n"
    src.write_text(_minimal_channel_yaml(block), encoding="utf-8")
    c = load_channel(src)

    dst = tmp_path / "out.yaml"
    save_channel(dst, c)
    raw = yaml.safe_load(dst.read_text(encoding="utf-8"))
    assert raw["bg_video"]["enabled"] is True
    assert raw["bg_video"]["scale"] == 0.88
    assert raw["bg_video"]["blur_px"] == 30
    assert raw["bg_video"]["dim"] == 0.4


def test_save_channel_omits_bg_video_when_disabled_default(tmp_path):
    """Channels without bg_video shouldn't gain the block on save (keeps YAML clean)."""
    import yaml
    from short_bot.config import load_channel, save_channel
    src = tmp_path / "c.yaml"
    src.write_text(_minimal_channel_yaml(), encoding="utf-8")
    c = load_channel(src)
    dst = tmp_path / "out.yaml"
    save_channel(dst, c)
    raw = yaml.safe_load(dst.read_text(encoding="utf-8"))
    assert "bg_video" not in raw
```

- [ ] **Step 2: Run, expect FAIL**

Run: `python -m pytest tests/test_config.py -k "channel" -v`
Expected: AttributeError on `c.bg_video`.

- [ ] **Step 3: Add the field to ChannelConfig dataclass**

In `src/short_bot/config.py`, in the `ChannelConfig` dataclass (around line 44), append a field:

```python
    bg_video: BgVideoConfig | None = None
```

(place it after `youtube: YoutubeChannelConfig | None = None`).

- [ ] **Step 4: Parse `bg_video:` block in `load_channel`**

In `load_channel`, just after the `youtube = YoutubeChannelConfig.model_validate(yt_data) if yt_data else None` line (around line 147), add:

```python
    bg_video_data = data.get("bg_video")
    bg_video = BgVideoConfig.model_validate(bg_video_data) if bg_video_data else None
```

Then in the `return ChannelConfig(...)` constructor call, add at the end (after `youtube=youtube,`):

```python
        bg_video=bg_video,
```

- [ ] **Step 5: Write `bg_video` block in `save_channel`**

In `save_channel`, just before `if cfg.dna is not None:` (around line 222), add:

```python
    if cfg.bg_video is not None and cfg.bg_video.enabled:
        data["bg_video"] = {
            "enabled": cfg.bg_video.enabled,
            "scale": cfg.bg_video.scale,
            "blur_px": cfg.bg_video.blur_px,
            "dim": cfg.bg_video.dim,
        }
```

- [ ] **Step 6: Run, expect PASS**

Run: `python -m pytest tests/test_config.py -v`
Expected: All previously-passing tests + 4 new ones pass. No regressions.

- [ ] **Step 7: Commit**

```bash
git add src/short_bot/config.py tests/test_config.py
git commit -m "feat(config): wire BgVideoConfig into ChannelConfig with YAML round-trip"
```

---

## Task 8: Composer 2-input bg-video path

Extend `compose_video` with optional `bg_video_path`, `bg_blur_px`, `bg_dim`, `fg_scale`. When `bg_video_path` is None, behavior is identical to before. Tests assert the ffmpeg command shape; we **don't** run ffmpeg.

**Files:**
- Modify: `src/short_bot/composer.py`
- Create: `tests/test_composer_bg_video.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_composer_bg_video.py`:

```python
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.composer import compose_video


def _setup_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_00001.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    music = tmp_path / "m.mp3"
    music.write_bytes(b"ID3")
    out = tmp_path / "out.mp4"
    return frames, music, out


def _ok_proc():
    p = MagicMock()
    p.returncode = 0
    p.stderr = ""
    return p


def test_compose_without_bg_video_keeps_single_input_pipeline(tmp_path):
    frames, music, out = _setup_inputs(tmp_path)
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out.write_bytes(b"fake")
        return _ok_proc()

    with patch("short_bot.composer.subprocess.run", side_effect=fake_run):
        compose_video(frames, music, out)
    cmd = captured["cmd"]
    # No bg video → only frames + music as inputs (2 -i flags)
    assert cmd.count("-i") == 2
    assert "overlay=" not in " ".join(cmd)


def test_compose_with_bg_video_emits_three_inputs_and_overlay(tmp_path):
    frames, music, out = _setup_inputs(tmp_path)
    bg = tmp_path / "bg.mp4"
    bg.write_bytes(b"fake-mp4")
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out.write_bytes(b"fake")
        return _ok_proc()

    with patch("short_bot.composer.subprocess.run", side_effect=fake_run):
        compose_video(
            frames, music, out,
            bg_video_path=bg, bg_blur_px=25, bg_dim=0.5, fg_scale=0.88,
        )
    cmd = captured["cmd"]
    cmd_str = " ".join(cmd)
    # Three -i inputs: bg, frames, music
    assert cmd.count("-i") == 3
    # bg input must come first (and use stream_loop -1 for indefinite loop)
    assert "-stream_loop" in cmd
    bg_idx = cmd.index(str(bg))
    frames_idx = cmd.index(str(frames / "frame_%05d.png"))
    music_idx = cmd.index(str(music))
    assert bg_idx < frames_idx < music_idx
    # Filter graph references
    assert "gblur=sigma=25" in cmd_str
    assert "scale=iw*0.88:ih*0.88" in cmd_str
    assert "overlay=" in cmd_str


def test_compose_with_bg_video_and_fg_scale_one_still_emits_overlay(tmp_path):
    """fg_scale=1.0 with a bg video means letterboxed-but-same-size foreground.
    The overlay path should still run (background is the whole point)."""
    frames, music, out = _setup_inputs(tmp_path)
    bg = tmp_path / "bg.mp4"
    bg.write_bytes(b"x")
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out.write_bytes(b"fake")
        return _ok_proc()

    with patch("short_bot.composer.subprocess.run", side_effect=fake_run):
        compose_video(frames, music, out, bg_video_path=bg, fg_scale=1.0)
    cmd_str = " ".join(captured["cmd"])
    assert "overlay=" in cmd_str
    assert "scale=iw*1.0:ih*1.0" in cmd_str


def test_compose_with_bg_video_raises_when_bg_missing(tmp_path):
    frames, music, out = _setup_inputs(tmp_path)
    missing_bg = tmp_path / "nope.mp4"
    with pytest.raises(FileNotFoundError):
        compose_video(frames, music, out, bg_video_path=missing_bg)


def test_compose_with_bg_video_propagates_ffmpeg_failure(tmp_path):
    frames, music, out = _setup_inputs(tmp_path)
    bg = tmp_path / "bg.mp4"
    bg.write_bytes(b"x")

    fail = MagicMock()
    fail.returncode = 1
    fail.stderr = "synthetic error"

    with patch("short_bot.composer.subprocess.run", return_value=fail):
        with pytest.raises(RuntimeError, match="ffmpeg failed"):
            compose_video(frames, music, out, bg_video_path=bg)
```

- [ ] **Step 2: Run, expect FAIL (compose_video missing kwargs)**

Run: `python -m pytest tests/test_composer_bg_video.py -v`
Expected: TypeError on unexpected kwargs.

- [ ] **Step 3: Extend compose_video signature and add the 2-input branch**

Replace the `compose_video` function in `src/short_bot/composer.py` entirely with:

```python
def compose_video(
    frames_dir: Path,
    music_path: Path,
    out_path: Path,
    *,
    fps: int = 30,
    ffmpeg_path: str = "ffmpeg",
    sfx_overlays: list[SfxOverlay] | None = None,
    music_volume: float = 0.7,
    bg_video_path: Path | None = None,
    bg_blur_px: int = 30,
    bg_dim: float = 0.4,
    fg_scale: float = 1.0,
) -> Path:
    """Compose final video.

    Without bg_video_path: PNG frames + music (+ optional SFX) → mp4 (legacy path).
    With bg_video_path: bg video (looped, blurred, dimmed, cropped 1080x1920)
    underneath PNG frames (scaled by fg_scale, centered) → mp4.
    """
    frames_dir = Path(frames_dir)
    music_path = Path(music_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not any(frames_dir.glob("frame_*.png")):
        raise FileNotFoundError(f"No frames in {frames_dir}")
    if not music_path.exists():
        raise FileNotFoundError(f"Music not found: {music_path}")
    if bg_video_path is not None and not Path(bg_video_path).exists():
        raise FileNotFoundError(f"BG video not found: {bg_video_path}")

    sfx_overlays = sfx_overlays or []
    for s in sfx_overlays:
        if not Path(s.path).exists():
            raise FileNotFoundError(f"SFX not found: {s.path}")

    if bg_video_path is None:
        cmd, video_map = _build_legacy_cmd(
            frames_dir, music_path, fps, ffmpeg_path, sfx_overlays, music_volume,
        )
    else:
        cmd, video_map = _build_bg_video_cmd(
            frames_dir, music_path, Path(bg_video_path),
            fps=fps, ffmpeg_path=ffmpeg_path,
            sfx_overlays=sfx_overlays, music_volume=music_volume,
            bg_blur_px=bg_blur_px, bg_dim=bg_dim, fg_scale=fg_scale,
        )

    cmd += [
        "-map", video_map,
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}): {proc.stderr[-1500:]}")
    return out_path


def _build_legacy_cmd(frames_dir, music_path, fps, ffmpeg_path,
                      sfx_overlays, music_volume) -> tuple[list[str], str]:
    """Single-stream pipeline (no bg video). Returns (cmd-prefix, video-map-label)."""
    cmd = [
        ffmpeg_path, "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-i", str(music_path),
    ]
    for s in sfx_overlays:
        cmd += ["-i", str(s.path)]

    if not sfx_overlays:
        filter_complex = f"[1:a]volume={music_volume}[aout]"
    else:
        parts = [f"[1:a]volume={music_volume}[bgm]"]
        labels = ["[bgm]"]
        for i, s in enumerate(sfx_overlays):
            in_idx = 2 + i
            tag = f"sfx{i}"
            parts.append(
                f"[{in_idx}:a]adelay={s.delay_ms}|{s.delay_ms},volume={s.volume}[{tag}]"
            )
            labels.append(f"[{tag}]")
        n = len(labels)
        parts.append(
            f"{''.join(labels)}amix=inputs={n}:duration=first:dropout_transition=0[aout]"
        )
        filter_complex = ";".join(parts)

    cmd += ["-filter_complex", filter_complex]
    return cmd, "0:v"


def _build_bg_video_cmd(
    frames_dir, music_path, bg_video_path, *,
    fps, ffmpeg_path, sfx_overlays, music_volume,
    bg_blur_px, bg_dim, fg_scale,
) -> tuple[list[str], str]:
    """Two-stream pipeline. Returns (cmd-prefix, video-map-label).

    Inputs (in order):
      0: bg video (looped)
      1: frame PNG seq
      2: music
      3+: optional SFX
    """
    cmd = [
        ffmpeg_path, "-y",
        "-stream_loop", "-1",
        "-i", str(bg_video_path),
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-i", str(music_path),
    ]
    for s in sfx_overlays:
        cmd += ["-i", str(s.path)]

    # Brightness expression: dim=0 → black (-1), dim=1 → unchanged (0)
    brightness = -(1.0 - bg_dim)

    # Video filter graph
    bg_chain = (
        f"[0:v]gblur=sigma={bg_blur_px},"
        f"scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,"
        f"eq=brightness={brightness:.2f}:saturation={bg_dim:.2f}[bg]"
    )
    fg_chain = f"[1:v]scale=iw*{fg_scale}:ih*{fg_scale},format=rgba[fg]"
    overlay_chain = "[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto[outv]"

    # Audio (same logic as legacy, but music is input 2 and SFX 3+)
    if not sfx_overlays:
        audio_chain = f"[2:a]volume={music_volume}[aout]"
    else:
        parts = [f"[2:a]volume={music_volume}[bgm]"]
        labels = ["[bgm]"]
        for i, s in enumerate(sfx_overlays):
            in_idx = 3 + i
            tag = f"sfx{i}"
            parts.append(
                f"[{in_idx}:a]adelay={s.delay_ms}|{s.delay_ms},volume={s.volume}[{tag}]"
            )
            labels.append(f"[{tag}]")
        n = len(labels)
        parts.append(
            f"{''.join(labels)}amix=inputs={n}:duration=first:dropout_transition=0[aout]"
        )
        audio_chain = ";".join(parts)

    filter_complex = ";".join([bg_chain, fg_chain, overlay_chain, audio_chain])
    cmd += ["-filter_complex", filter_complex]
    return cmd, "[outv]"
```

- [ ] **Step 4: Run, expect PASS (both new and existing composer tests)**

Run: `python -m pytest tests/test_composer_bg_video.py tests/test_composer.py -v` (the second path may not exist; that's fine — only the new file matters for now). All composer-related tests must pass.

If `tests/test_composer.py` exists, run it too — must stay green.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/composer.py tests/test_composer_bg_video.py
git commit -m "feat(composer): add 2-input bg-video overlay path with letterbox foreground"
```

---

## Task 9: Pipeline asset stage — Pexels search/download

Asset phase (`_run_rss`) gains a Pexels block that runs only when `channel.bg_video.enabled`. Result is passed to composer via new `bg_video_path`/`fg_scale`/`bg_blur_px`/`bg_dim` kwargs. Failure paths log and continue with `bg_video_path=None`.

**Files:**
- Modify: `src/short_bot/pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline.py` (using the same conftest patterns as existing tests):

```python
def test_pipeline_skips_pexels_when_bg_video_disabled(tmp_path, monkeypatch):
    """When bg_video is None on the channel, Pexels code paths must not be called."""
    from short_bot.pipeline import _resolve_pexels_bg
    from short_bot.config import ChannelConfig
    # Build a channel without bg_video
    ch = _make_test_channel(bg_video=None)  # see helper added below
    secrets_path = tmp_path / "secrets.yaml"
    cache = tmp_path / "cache"

    called = {"search": 0, "download": 0}
    monkeypatch.setattr("short_bot.pexels.search_videos",
                        lambda *a, **k: (called.__setitem__("search", called["search"] + 1) or []))
    monkeypatch.setattr("short_bot.pexels.download_video",
                        lambda *a, **k: (called.__setitem__("download", called["download"] + 1) or None))

    out = _resolve_pexels_bg(channel=ch, cache_dir=cache, secrets_path=secrets_path,
                              log=_silent_log())
    assert out is None
    assert called["search"] == 0
    assert called["download"] == 0


def test_pipeline_pexels_fallback_when_no_api_key(tmp_path, monkeypatch):
    from short_bot.pipeline import _resolve_pexels_bg
    from short_bot.config import BgVideoConfig
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    ch = _make_test_channel(bg_video=BgVideoConfig(enabled=True))
    secrets_path = tmp_path / "secrets.yaml"   # absent
    out = _resolve_pexels_bg(channel=ch, cache_dir=tmp_path / "cache",
                              secrets_path=secrets_path, log=_silent_log())
    assert out is None


def test_pipeline_pexels_downloads_first_successful_candidate(tmp_path, monkeypatch):
    from short_bot.pipeline import _resolve_pexels_bg
    from short_bot.config import BgVideoConfig
    from short_bot.pexels import PexelsCandidate
    monkeypatch.setenv("PEXELS_API_KEY", "TESTKEY")

    ch = _make_test_channel(bg_video=BgVideoConfig(enabled=True))

    fake_candidates = [
        PexelsCandidate(id=1, url="https://x/a.mp4", duration_s=10),
        PexelsCandidate(id=2, url="https://x/b.mp4", duration_s=12),
    ]
    monkeypatch.setattr("short_bot.pexels.search_videos",
                        lambda *a, **k: fake_candidates)

    cached = tmp_path / "cache" / "pexels_videos" / "abc.mp4"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"video")

    monkeypatch.setattr("short_bot.pexels.download_video",
                        lambda url, cache_dir, **k: cached if "a.mp4" in url else None)

    out = _resolve_pexels_bg(channel=ch, cache_dir=tmp_path / "cache",
                              secrets_path=tmp_path / "secrets.yaml",
                              log=_silent_log())
    assert out == cached


def test_pipeline_pexels_returns_none_when_search_empty(tmp_path, monkeypatch):
    from short_bot.pipeline import _resolve_pexels_bg
    from short_bot.config import BgVideoConfig
    monkeypatch.setenv("PEXELS_API_KEY", "TESTKEY")
    ch = _make_test_channel(bg_video=BgVideoConfig(enabled=True))
    monkeypatch.setattr("short_bot.pexels.search_videos", lambda *a, **k: [])
    out = _resolve_pexels_bg(channel=ch, cache_dir=tmp_path / "cache",
                              secrets_path=tmp_path / "secrets.yaml",
                              log=_silent_log())
    assert out is None
```

Add helpers near the top of `tests/test_pipeline.py` (or in a shared place — but inline-appending is fine for first pass):

```python
import logging


def _silent_log():
    log = logging.getLogger("test.silent")
    log.handlers = []
    log.addHandler(logging.NullHandler())
    return log


def _make_test_channel(*, bg_video=None):
    """Minimal ChannelConfig sufficient for _resolve_pexels_bg."""
    from short_bot.config import ChannelConfig
    return ChannelConfig(
        slug="t", name="T", keywords=["x"],
        rss_locale="hl=tr&gl=TR&ceid=TR:tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=5, template="newscast",
        colors={"primary": "#000", "accent": "#fff",
                "bg_gradient": ["#000", "#111"]},
        handle="@x", output_dir="output/t",
        enabled=True, cta_enabled=False, cta_text="",
        cta_icons=[], cta_duration_s=0, cta_show_handle=False,
        language="tr", bg_video=bg_video,
    )
```

- [ ] **Step 2: Run, expect FAIL (function not defined)**

Run: `python -m pytest tests/test_pipeline.py -k pexels -v`
Expected: ImportError on `_resolve_pexels_bg`.

- [ ] **Step 3: Add `_resolve_pexels_bg` to pipeline.py**

Add to imports at top of `src/short_bot/pipeline.py`:

```python
from short_bot.pexels import (
    download_video as _pexels_download,
    load_secrets as _load_secrets,
    pick_query_for_archetype,
    resolve_pexels_api_key,
    search_videos as _pexels_search,
)
```

Add this helper function near the other module-level helpers (after `_setup_logger`):

```python
def _resolve_pexels_bg(*, channel, cache_dir, secrets_path, log) -> Path | None:
    """Search/download a Pexels bg video for `channel`. None on opt-out / failure."""
    if channel.bg_video is None or not channel.bg_video.enabled:
        return None
    api_key = resolve_pexels_api_key(_load_secrets(secrets_path))
    if not api_key:
        log.warning("  bg_video enabled but PEXELS_API_KEY not set → fallback")
        return None
    archetype = (channel.dna.archetype if channel.dna is not None
                 else channel.template)
    query = pick_query_for_archetype(archetype)
    log.info(f"  pexels search: query={query!r}")
    candidates = _pexels_search(query, api_key, max_results=3)
    if not candidates:
        log.warning("  pexels: no candidates returned → fallback")
        return None
    bg_cache = Path(cache_dir) / "pexels_videos"
    for cand in candidates:
        path = _pexels_download(cand.url, bg_cache)
        if path is not None:
            log.info(f"  pexels accepted: {path.name} (id={cand.id})")
            return path
    log.warning("  pexels: all candidate downloads failed → fallback")
    return None
```

- [ ] **Step 4: Wire it into `_run_rss` and into the `compose_video` call**

Locate the asset block in `_run_rss` (right after `bg = pick_image_for_script(...)` succeeds and `music = pick_music(...)` runs, before the `compose_video` call). Add — just before `compose_video(frames_dir, music, out_path, ...)`:

```python
        secrets_path = current_app_secrets_path()  # see helper below
        bg_video_path = _resolve_pexels_bg(
            channel=channel, cache_dir=cache_dir,
            secrets_path=secrets_path, log=log,
        )
```

Then update the `compose_video(...)` call to pass the new kwargs:

```python
        bv = channel.bg_video
        compose_video(
            frames_dir, music, out_path,
            fps=30, ffmpeg_path=settings.ffmpeg_path,
            sfx_overlays=sfx_overlays,
            bg_video_path=bg_video_path,
            bg_blur_px=bv.blur_px if bv else 30,
            bg_dim=bv.dim if bv else 0.4,
            fg_scale=bv.scale if (bv and bg_video_path) else 1.0,
        )
```

Add this helper at module level (top of the file, near other path helpers):

```python
def current_app_secrets_path() -> Path:
    """Resolve the secrets path relative to the project's data dir.

    Pipeline runs both inside Flask (web 'Run now') and standalone (CLI/cron).
    We don't want to depend on flask.current_app — keep it simple: data/secrets.yaml
    next to the cwd's data directory."""
    return Path("data") / "secrets.yaml"
```

(If a project-level `DATA_DIR` already exists somewhere in code, prefer it — but don't refactor for it now. The simple cwd-based path matches the rest of `pipeline.py` patterns.)

- [ ] **Step 5: Run, expect PASS**

Run: `python -m pytest tests/test_pipeline.py -k pexels -v`
Expected: 4 passed (the new pexels tests).

Run also: `python -m pytest tests/test_pipeline.py -v` — make sure no existing test broke (the `compose_video` call gained kwargs but defaults preserve old behavior).

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): integrate Pexels bg-video lookup into RSS asset stage"
```

---

## Task 10: Settings web UI — Pexels API key input

`/settings` GET reads from `data/secrets.yaml`, renders a masked password input. POST writes the key only if a non-empty value arrives.

**Files:**
- Modify: `src/short_bot/web/routes/settings.py`
- Modify: `src/short_bot/web/templates/settings.html.j2`
- Modify: `tests/test_web_settings.py` (or create if absent)

- [ ] **Step 1: Write the failing test**

Open or create `tests/test_web_settings.py`. Append:

```python
import pytest
import yaml

from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: haiku\n",
        encoding="utf-8",
    )
    secrets_dir = tmp_path / "data"
    secrets_dir.mkdir()
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=secrets_dir / "secrets.yaml",
                      scheduler=False)


def test_settings_page_shows_pexels_key_field_unset(app):
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert "Pexels" in body
    assert "pexels_api_key" in body  # input name
    # Unset → input should be present with empty value
    assert 'value=""' in body or "value=''" in body or "değiştir" not in body


def test_settings_save_pexels_key_writes_secrets_file(app, tmp_path):
    secrets_path = tmp_path / "data" / "secrets.yaml"
    resp = app.test_client().post("/settings", data={
        # All existing fields pass through; only pexels key is new
        "ffmpeg_path": "ffmpeg",
        "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85",
        "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku",
        "pexels_api_key": "MYTESTKEY",
    })
    assert resp.status_code in (200, 302)
    assert secrets_path.exists()
    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert data["pexels_api_key"] == "MYTESTKEY"


def test_settings_save_empty_pexels_key_clears(app, tmp_path):
    secrets_path = tmp_path / "data" / "secrets.yaml"
    secrets_path.write_text("pexels_api_key: OLDKEY\n", encoding="utf-8")
    app.test_client().post("/settings", data={
        "ffmpeg_path": "ffmpeg", "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85", "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku",
        "pexels_api_key": "",
        "pexels_api_key_clear": "1",   # explicit clear flag
    })
    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    assert data.get("pexels_api_key", "") == ""


def test_settings_save_omits_pexels_key_does_not_overwrite(app, tmp_path):
    """No `pexels_api_key_clear` flag and empty value → preserve existing key."""
    secrets_path = tmp_path / "data" / "secrets.yaml"
    secrets_path.write_text("pexels_api_key: KEEPER\n", encoding="utf-8")
    app.test_client().post("/settings", data={
        "ffmpeg_path": "ffmpeg", "claude_cli_path": "claude",
        "playwright_browser": "chromium",
        "fuzzy_dedup_threshold": "0.85", "log_level": "INFO",
        "web_host": "127.0.0.1", "web_port": "5005",
        "model_dna": "opus", "model_default": "haiku",
        "pexels_api_key": "",   # empty, no clear flag
    })
    data = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert data["pexels_api_key"] == "KEEPER"
```

The test depends on `create_app(secrets_path=...)`. If `create_app` doesn't yet accept that kwarg, do a quick read of `src/short_bot/web/__init__.py` and add it as an optional argument — defaulting to `Path("data/secrets.yaml")`. Wire it into `app.config["SHORTBOT_SECRETS_PATH"]`.

- [ ] **Step 2: Run, expect FAIL**

Run: `python -m pytest tests/test_web_settings.py -v`
Expected: failures (route doesn't read/write secrets, template lacks input).

- [ ] **Step 3: Wire `secrets_path` into the app factory**

In `src/short_bot/web/__init__.py`, find the `create_app` signature and the config setup. Add:

- A new kwarg `secrets_path: Path | None = None` (default `Path("data") / "secrets.yaml"` if None).
- A new `app.config["SHORTBOT_SECRETS_PATH"] = secrets_path`.

(Do not change other defaults.)

- [ ] **Step 4: Update `settings.py` route to read/write secrets**

Modify `src/short_bot/web/routes/settings.py`. Replace the entire file body below the imports with:

```python
"""Settings page: view + edit settings.yaml + write Pexels API key to data/secrets.yaml."""
from pathlib import Path

import yaml
from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)

bp = Blueprint("settings", __name__)


def _settings_path() -> Path:
    return current_app.config["SHORTBOT_CONFIG_DIR"] / "settings.yaml"


def _secrets_path() -> Path:
    return Path(current_app.config["SHORTBOT_SECRETS_PATH"])


def _load_secrets() -> dict:
    p = _secrets_path()
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _save_secrets(data: dict) -> None:
    p = _secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")


def _mask_key(key: str) -> str:
    if not key:
        return ""
    return "•" * 8 + (key[-4:] if len(key) >= 4 else "")


@bp.route("/settings", methods=["GET"])
def view():
    data = yaml.safe_load(_settings_path().read_text(encoding="utf-8")) or {}
    secrets = _load_secrets()
    paths = {
        "Config dir": str(current_app.config["SHORTBOT_CONFIG_DIR"]),
        "DB":         str(current_app.config["SHORTBOT_DB_PATH"]),
        "Templates":  str(current_app.config["SHORTBOT_TEMPLATES_DIR"]),
        "Music":      str(current_app.config["SHORTBOT_MUSIC_ROOT"]),
        "Cache":      str(current_app.config["SHORTBOT_CACHE_DIR"]),
        "Locks":      str(current_app.config["SHORTBOT_LOCK_DIR"]),
        "Logs":       str(current_app.config["SHORTBOT_LOGS_DIR"]),
        "Output":     str(current_app.config["SHORTBOT_OUTPUT_ROOT"]),
        "Secrets":    str(_secrets_path()),
    }
    pexels_key_masked = _mask_key(secrets.get("pexels_api_key", ""))
    return render_template("settings.html.j2", data=data, paths=paths,
                            pexels_key_masked=pexels_key_masked,
                            pexels_key_set=bool(secrets.get("pexels_api_key")))


@bp.route("/settings", methods=["POST"])
def save():
    """Update settings.yaml and (separately) data/secrets.yaml for Pexels key."""
    path = _settings_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    data["ffmpeg_path"]      = request.form.get("ffmpeg_path", data.get("ffmpeg_path"))
    data["claude_cli_path"]  = request.form.get("claude_cli_path", data.get("claude_cli_path"))
    data["playwright_browser"] = request.form.get("playwright_browser",
                                                  data.get("playwright_browser"))
    try:
        data["fuzzy_dedup_threshold"] = float(request.form.get("fuzzy_dedup_threshold",
                                                                 data.get("fuzzy_dedup_threshold")))
    except (TypeError, ValueError):
        pass
    data["log_level"]        = request.form.get("log_level", data.get("log_level"))

    web = data.get("web", {})
    web["host"] = request.form.get("web_host", web.get("host"))
    try:
        web["port"] = int(request.form.get("web_port", web.get("port")))
    except (TypeError, ValueError):
        pass
    data["web"] = web

    models = data.get("claude_models", {})
    models["dna"]     = request.form.get("model_dna", models.get("dna"))
    models["default"] = request.form.get("model_default", models.get("default"))
    data["claude_models"] = models

    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")

    # Pexels key — separate file
    secrets = _load_secrets()
    new_key = request.form.get("pexels_api_key", "").strip()
    clear = request.form.get("pexels_api_key_clear") == "1"
    if new_key:
        secrets["pexels_api_key"] = new_key
        _save_secrets(secrets)
    elif clear:
        secrets.pop("pexels_api_key", None)
        _save_secrets(secrets)
    # else: leave existing key as-is

    flash("Ayarlar kaydedildi. Bazı değişiklikler için panel yeniden başlatılmalı.", "success")
    return redirect(url_for("settings.view"))
```

- [ ] **Step 5: Add the input + masked display to the template**

In `src/short_bot/web/templates/settings.html.j2`, locate the form (look for "ffmpeg_path" input). Add this block somewhere inside the `<form>` (e.g., as a new section labeled "Pexels"):

```html
<div class="bg-claude-surface border border-claude-border rounded-lg p-4 mt-4">
  <div class="text-xs text-claude-muted uppercase tracking-wider mb-2">Pexels API</div>
  {% if pexels_key_set %}
    <div class="flex items-center gap-3">
      <span class="font-mono text-sm">{{ pexels_key_masked }}</span>
      <label class="text-xs flex items-center gap-1">
        <input type="checkbox" name="pexels_api_key_clear" value="1"> Sil
      </label>
    </div>
    <input type="password" name="pexels_api_key" placeholder="Yeni key gir (değiştir)"
           class="bg-claude-surface-alt border border-claude-border px-3 py-2 rounded-lg text-sm w-full mt-2 text-claude-text">
  {% else %}
    <input type="password" name="pexels_api_key" value="" placeholder="Pexels API key"
           class="bg-claude-surface-alt border border-claude-border px-3 py-2 rounded-lg text-sm w-full text-claude-text">
    <div class="text-xs text-claude-muted mt-1">
      pexels.com/api kayıt → key al → buraya yapıştır. Key git'e yazılmaz.
    </div>
  {% endif %}
</div>
```

- [ ] **Step 6: Run, expect PASS**

Run: `python -m pytest tests/test_web_settings.py -v`
Expected: 4 new tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/short_bot/web src/short_bot/web/templates/settings.html.j2 tests/test_web_settings.py
git commit -m "feat(web/settings): add Pexels API key input writing to data/secrets.yaml"
```

---

## Task 11: Channel edit form — `bg_video` section

Edit page renders the existing channel's `bg_video` block (or defaults if absent), POST persists it.

**Files:**
- Modify: `src/short_bot/web/routes/channel_edit.py`
- Modify: `src/short_bot/web/templates/channels/edit.html.j2`
- Modify: `tests/test_web_channel_edit_generator.py` (or create dedicated `tests/test_web_channel_edit_bg.py`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_channel_edit_bg.py`:

```python
import pytest
import yaml

from short_bot.config import save_channel
from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8",
    )
    # Seed one channel without bg_video
    (cfg_dir / "channels" / "demo.yaml").write_text("""\
slug: demo
name: Demo
keywords: [x]
language: tr
schedule_cron: 0 * * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors:
  primary: '#c81e1e'
  accent: '#ffea3b'
  bg_gradient: ['#000000', '#111111']
handle: '@demo'
output_dir: output/demo
enabled: true
cta:
  enabled: false
  text: ''
  icons: []
  duration_s: 0
  show_handle: false
""", encoding="utf-8")
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      scheduler=False)


def test_edit_page_shows_bg_video_section(app):
    body = app.test_client().get("/channels/demo/edit").data.decode("utf-8")
    assert "Arka plan videosu" in body or "bg_video" in body
    assert 'name="bg_video_enabled"' in body
    # Both scale options present
    assert "0.88" in body
    assert "0.80" in body


def test_edit_post_enables_bg_video_writes_yaml(app, tmp_path):
    client = app.test_client()
    # First do a GET to populate any CSRF/session if used (Flask default: none)
    client.get("/channels/demo/edit")
    resp = client.post("/channels/demo/edit", data={
        # Required existing fields
        "name": "Demo",
        "keywords": "x",
        "schedule_cron": "0 * * * *",
        "duration_s": "6", "min_score": "6.0",
        "max_candidates_per_run": "5",
        "handle": "@demo",
        "language": "tr",
        "enabled": "on",
        # bg_video new fields
        "bg_video_enabled": "on",
        "bg_video_scale": "0.88",
        "bg_video_blur_px": "30",
        "bg_video_dim": "0.4",
    })
    assert resp.status_code in (200, 302)
    yaml_path = tmp_path / "config" / "channels" / "demo.yaml"
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert raw["bg_video"]["enabled"] is True
    assert raw["bg_video"]["scale"] == 0.88


def test_edit_post_disables_bg_video_omits_block(app, tmp_path):
    """Submitting without bg_video_enabled should remove the block from YAML."""
    # First seed an enabled bg_video on disk
    yaml_path = tmp_path / "config" / "channels" / "demo.yaml"
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    raw["bg_video"] = {"enabled": True, "scale": 0.80,
                        "blur_px": 20, "dim": 0.3}
    yaml_path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
                          encoding="utf-8")

    client = app.test_client()
    client.get("/channels/demo/edit")
    client.post("/channels/demo/edit", data={
        "name": "Demo", "keywords": "x",
        "schedule_cron": "0 * * * *",
        "duration_s": "6", "min_score": "6.0",
        "max_candidates_per_run": "5",
        "handle": "@demo", "language": "tr", "enabled": "on",
        # bg_video_enabled NOT set (checkbox unchecked)
    })
    raw_after = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert "bg_video" not in raw_after
```

- [ ] **Step 2: Run, expect FAIL**

Run: `python -m pytest tests/test_web_channel_edit_bg.py -v`
Expected: form fields missing.

- [ ] **Step 3: Read the existing edit POST handler to know which fields it accepts**

Run: open `src/short_bot/web/routes/channel_edit.py` (you've inspected the area in earlier tasks).

Inside the POST handler — wherever it builds the new `ChannelConfig` from form data — add:

```python
    bg_v_enabled = request.form.get("bg_video_enabled") == "on"
    if bg_v_enabled:
        from short_bot.config import BgVideoConfig
        try:
            scale = float(request.form.get("bg_video_scale", "0.88"))
            if scale not in (0.88, 0.80):
                scale = 0.88
        except (TypeError, ValueError):
            scale = 0.88
        try:
            blur = int(request.form.get("bg_video_blur_px", "30"))
        except (TypeError, ValueError):
            blur = 30
        try:
            dim = float(request.form.get("bg_video_dim", "0.4"))
        except (TypeError, ValueError):
            dim = 0.4
        bg_video = BgVideoConfig(enabled=True, scale=scale,
                                   blur_px=blur, dim=dim)
    else:
        bg_video = None
```

Pass `bg_video=bg_video` to the `ChannelConfig(...)` constructor (or `dataclasses.replace(existing, bg_video=bg_video)` — whichever pattern the file already uses).

In the GET handler, ensure `c` (the channel) is passed to the template; the template will read `c.bg_video`.

- [ ] **Step 4: Update the edit template**

In `src/short_bot/web/templates/channels/edit.html.j2`, append (anywhere before the form's submit button):

```html
<div class="bg-claude-surface border border-claude-border rounded-lg p-4 mt-4">
  <div class="flex items-center justify-between mb-3">
    <div class="text-xs text-claude-muted uppercase tracking-wider">Arka plan videosu (Pexels)</div>
    <label class="flex items-center gap-2 text-sm">
      <input type="checkbox" name="bg_video_enabled"
             {% if c.bg_video and c.bg_video.enabled %}checked{% endif %}>
      Etkin
    </label>
  </div>
  <div class="grid grid-cols-3 gap-3">
    <label class="text-xs">
      <span class="block text-claude-muted mb-1">Çerçeve oranı</span>
      <select name="bg_video_scale"
              class="bg-claude-surface-alt border border-claude-border px-2 py-1 rounded w-full text-sm text-claude-text">
        <option value="0.88" {% if c.bg_video and c.bg_video.scale == 0.88 %}selected{% endif %}>0.88 (dar şerit)</option>
        <option value="0.80" {% if c.bg_video and c.bg_video.scale == 0.80 %}selected{% endif %}>0.80 (geniş şerit)</option>
      </select>
    </label>
    <label class="text-xs">
      <span class="block text-claude-muted mb-1">Bulanıklık (px)</span>
      <input type="number" name="bg_video_blur_px" min="0" max="80"
             value="{{ (c.bg_video.blur_px if c.bg_video else 30) }}"
             class="bg-claude-surface-alt border border-claude-border px-2 py-1 rounded w-full text-sm text-claude-text">
    </label>
    <label class="text-xs">
      <span class="block text-claude-muted mb-1">Karartma (0–1)</span>
      <input type="number" step="0.05" name="bg_video_dim" min="0" max="1"
             value="{{ (c.bg_video.dim if c.bg_video else 0.4) }}"
             class="bg-claude-surface-alt border border-claude-border px-2 py-1 rounded w-full text-sm text-claude-text">
    </label>
  </div>
</div>
```

If the existing edit template uses a variable other than `c` for the channel object, substitute that name.

- [ ] **Step 5: Run, expect PASS**

Run: `python -m pytest tests/test_web_channel_edit_bg.py -v`
Expected: 3 passed.

Run also: `python -m pytest tests/test_web_channel_edit_generator.py -v` (existing tests must stay green).

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/web/routes/channel_edit.py src/short_bot/web/templates/channels/edit.html.j2 tests/test_web_channel_edit_bg.py
git commit -m "feat(web/channels): add bg_video section to edit form"
```

---

## Task 12: Channel new wizard — bg_video opt-in

The new-channel form gets the same bg_video block, defaulted to `enabled=false`. Submission writes the block when checked.

**Files:**
- Modify: `src/short_bot/web/routes/channel_new.py`
- Modify: `src/short_bot/web/templates/channels/new.html.j2`
- Modify or create: `tests/test_web_channel_new.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web_channel_new.py` (or wherever new-channel form is tested):

```python
def test_new_channel_form_shows_bg_video_section(app):
    body = app.test_client().get("/channels/new").data.decode("utf-8")
    assert "Arka plan videosu" in body or "bg_video_enabled" in body


def test_new_channel_with_bg_video_writes_yaml(app, tmp_path):
    client = app.test_client()
    client.post("/channels/new", data={
        # Whatever the existing new-channel form requires; only relevant fields shown:
        "slug": "newbg", "name": "NewBG",
        "keywords": "x", "language": "tr",
        "template": "newscast",
        "duration_s": "6", "schedule_cron": "0 * * * *",
        "min_score": "6.0", "max_candidates_per_run": "5",
        "handle": "@newbg",
        "primary": "#c81e1e", "accent": "#ffea3b",
        "bg_grad_1": "#000000", "bg_grad_2": "#111111",
        # bg_video opt-in
        "bg_video_enabled": "on",
        "bg_video_scale": "0.80",
        "bg_video_blur_px": "25",
        "bg_video_dim": "0.5",
    })
    import yaml
    yaml_path = tmp_path / "config" / "channels" / "newbg.yaml"
    if not yaml_path.exists():
        # The new-channel route may complete via redirect — the file must exist
        # somewhere under config/channels.
        from pathlib import Path
        candidates = list((tmp_path / "config" / "channels").glob("*.yaml"))
        assert candidates, "No channel yaml created by new flow"
        yaml_path = candidates[0]
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert raw["bg_video"]["enabled"] is True
    assert raw["bg_video"]["scale"] == 0.80
```

(If `tests/test_web_channel_new.py` doesn't have an `app` fixture, copy/adapt the one from `test_web_channel_edit_bg.py`.)

- [ ] **Step 2: Run, expect FAIL**

Run: `python -m pytest tests/test_web_channel_new.py -k bg_video -v`
Expected: input not found / yaml lacks block.

- [ ] **Step 3: Update the new-channel POST handler**

In `src/short_bot/web/routes/channel_new.py`, in the POST handler where the YAML or `ChannelConfig` is built, add the same bg_video parsing block from Task 11 Step 3, then:

```python
    # When constructing the new ChannelConfig:
    cfg = ChannelConfig(..., bg_video=bg_video)   # bg_video may be None
```

- [ ] **Step 4: Update the new-channel template**

In `src/short_bot/web/templates/channels/new.html.j2`, append the same block from Task 11 Step 4 (with `c.bg_video` references replaced by literal defaults — there's no existing channel here):

```html
<div class="bg-claude-surface border border-claude-border rounded-lg p-4 mt-4">
  <div class="flex items-center justify-between mb-3">
    <div class="text-xs text-claude-muted uppercase tracking-wider">Arka plan videosu (Pexels)</div>
    <label class="flex items-center gap-2 text-sm">
      <input type="checkbox" name="bg_video_enabled"> Etkin
    </label>
  </div>
  <div class="grid grid-cols-3 gap-3">
    <label class="text-xs">
      <span class="block text-claude-muted mb-1">Çerçeve oranı</span>
      <select name="bg_video_scale"
              class="bg-claude-surface-alt border border-claude-border px-2 py-1 rounded w-full text-sm text-claude-text">
        <option value="0.88" selected>0.88 (dar şerit)</option>
        <option value="0.80">0.80 (geniş şerit)</option>
      </select>
    </label>
    <label class="text-xs">
      <span class="block text-claude-muted mb-1">Bulanıklık (px)</span>
      <input type="number" name="bg_video_blur_px" min="0" max="80" value="30"
             class="bg-claude-surface-alt border border-claude-border px-2 py-1 rounded w-full text-sm text-claude-text">
    </label>
    <label class="text-xs">
      <span class="block text-claude-muted mb-1">Karartma (0–1)</span>
      <input type="number" step="0.05" name="bg_video_dim" min="0" max="1" value="0.4"
             class="bg-claude-surface-alt border border-claude-border px-2 py-1 rounded w-full text-sm text-claude-text">
    </label>
  </div>
</div>
```

- [ ] **Step 5: Run, expect PASS**

Run: `python -m pytest tests/test_web_channel_new.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/web/routes/channel_new.py src/short_bot/web/templates/channels/new.html.j2 tests/test_web_channel_new.py
git commit -m "feat(web/channels): add bg_video section to new-channel wizard"
```

---

## Task 13: End-to-end smoke test (manual + automated)

A scripted test covers the YAML round-trip path, but the FFmpeg overlay is verified manually since real Pexels download + FFmpeg run is too heavy for CI.

**Files:**
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Add a smoke test that exercises the wired path with everything mocked**

Append to `tests/test_pipeline.py`:

```python
def test_pipeline_passes_bg_video_to_composer_when_enabled(monkeypatch, tmp_path):
    """Integration: when channel has bg_video enabled and a key, the cached video
    path lands in compose_video kwargs."""
    from short_bot.config import BgVideoConfig
    from short_bot.pexels import PexelsCandidate
    monkeypatch.setenv("PEXELS_API_KEY", "K")

    fake_bg = tmp_path / "cache" / "pexels_videos" / "fake.mp4"
    fake_bg.parent.mkdir(parents=True)
    fake_bg.write_bytes(b"x")

    monkeypatch.setattr("short_bot.pexels.search_videos",
                        lambda *a, **k: [PexelsCandidate(id=1, url="https://x/a.mp4", duration_s=5)])
    monkeypatch.setattr("short_bot.pexels.download_video",
                        lambda url, cache_dir, **k: fake_bg)

    captured = {}
    def fake_compose(frames, music, out, **kw):
        captured.update(kw)
        out.write_bytes(b"fake-mp4")
        return out
    monkeypatch.setattr("short_bot.pipeline.compose_video", fake_compose)

    from short_bot.pipeline import _resolve_pexels_bg
    ch = _make_test_channel(bg_video=BgVideoConfig(enabled=True, scale=0.80))
    bg_path = _resolve_pexels_bg(channel=ch, cache_dir=tmp_path / "cache",
                                   secrets_path=tmp_path / "secrets.yaml",
                                   log=_silent_log())
    assert bg_path == fake_bg
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest -q`
Expected: All tests pass — old + new.

- [ ] **Step 3: Manual verification checklist**

Document for the user (paste into final commit message or a plan-completion note):

```
Manual verification (do these once after merge):
1. Open /settings, paste a Pexels API key, save. Confirm `data/secrets.yaml` exists
   with the key and is in `.gitignore`.
2. Edit any channel, enable Arka plan videosu, scale=0.88, blur=30, dim=0.4. Save.
   Confirm channel YAML now has bg_video block.
3. Trigger Run now. Watch logs for:
     - "pexels search: query='...'" line
     - "pexels accepted: <hash>.mp4" line
4. Open the resulting short. Confirm:
     - archetype frame is centered, smaller than full-bleed
     - background video is visibly blurred/dimmed
     - audio = music as before (no Pexels audio)
5. Disable bg_video on the channel, run again. Confirm:
     - no pexels search log lines
     - short renders in original fullscreen layout
6. Switch scale to 0.80, run. Confirm wider letterbox margin.
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline.py
git commit -m "test(pipeline): add bg_video integration smoke test"
```

---

## Self-Review Notes

**Spec coverage check:**

| Spec section | Implemented in |
|---|---|
| 1. Pexels client | Tasks 2-5 |
| 2. Channel config schema | Tasks 6, 7 |
| 3. Settings/secrets handling | Tasks 1, 2, 10 |
| 4. Pipeline integration | Task 9 |
| 5. Composer 2-input path | Task 8 |
| 6. Web UI (Settings) | Task 10 |
| 6. Web UI (channel edit) | Task 11 |
| 6. Web UI (channel new) | Task 12 |
| 7. Cache | Task 5 (sha1 cache + idempotent) |
| Failure modes | Tasks 4, 5, 9 (graceful fallback) |
| Test plan | Each task has its own tests + Task 13 smoke |
| Out-of-scope: TTL eviction, scoring, AI query gen, audio mixing, re-render | not in plan ✓ |

**Type consistency:**
- `BgVideoConfig.scale` is `Literal[0.88, 0.80]` everywhere (Task 6, used Tasks 7, 9, 11, 12).
- `bg_video_path: Path | None` matches between `_resolve_pexels_bg` return (Task 9) and `compose_video` param (Task 8).
- `resolve_pexels_api_key(secrets: dict)` signature consistent across Tasks 2 and 9.
- `pick_query_for_archetype(archetype: str)` signature consistent (Task 3 → Task 9).

**No placeholders:** All steps either show full code, exact commands, or call out a specific 1-2 line edit referencing existing patterns (e.g., "matches the existing youtube=youtube line").

Plan complete and saved to `docs/superpowers/plans/2026-05-07-pexels-bg-video.md`.
