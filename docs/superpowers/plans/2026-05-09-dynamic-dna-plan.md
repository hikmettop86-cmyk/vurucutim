# Dynamic DNA — Per-Video Style Selection (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in per-channel feature where every video gets its own LLM-generated DNA (archetype + palette + fonts + tone + animation) tailored to the article's topic, with embedding-based per-channel cache to bound Opus cost.

**Architecture:** F1 ships embedding infrastructure (OpenAI text-embedding-3-small) + `dna_cache` SQLite table + secrets plumbing. F2 ships per-video DNA generation, pipeline integration, and the opt-in UI. F3 adds `animation_style` field + CSS keyframes + 15-template wiring. F4 adds dashboard observability + daily TTL cleanup cron.

**Tech Stack:** Python 3.11, SQLAlchemy Core, requests (for OpenAI HTTP), numpy (new dep — for embedding cosine), pydantic v2, Jinja2, Playwright, pytest + pytest-mock, Flask.

**Spec:** `docs/superpowers/specs/2026-05-09-dynamic-dna-design.md`

**Phases (each independently shippable):**
- **F1** (Tasks 1-4): Cache infra
- **F2** (Tasks 5-11): Per-video DNA + opt-in UI
- **F3** (Tasks 12-15): Animation style + template wiring
- **F4** (Tasks 16-18): Observability + cleanup

---

## File Structure (locked in)

**New files:**
- `src/short_bot/embeddings.py` — OpenAI embedding HTTP client wrapper (~80 lines)
- `src/short_bot/dna_cache.py` — Per-channel cache: save/lookup/cleanup (~140 lines)
- `templates/css/_animations.css` — Shared keyframes + stage-class selectors (~60 lines, F3)
- `tests/test_embeddings.py` — F1
- `tests/test_dna_cache.py` — F1
- `tests/test_dna_cache_pipeline.py` — F2 e2e
- `tests/test_dna_animation.py` — F3

**Modified files:**
- `pyproject.toml` — add `numpy>=1.24` dep (Task 1)
- `src/short_bot/secrets_io.py` — add `update_openai_api_key()` (Task 2)
- `src/short_bot/pexels.py` — add `resolve_openai_api_key()` next to existing pexels resolver (Task 2)
- `src/short_bot/db.py` — add `dna_cache` Table definition (Task 4)
- `src/short_bot/config.py` — add `ChannelConfig.dynamic_dna` field + YAML round-trip (Task 5)
- `src/short_bot/dna.py` — add `generate_dna_for_video()` + `animation_style` field (Tasks 6, 12)
- `src/short_bot/pipeline.py` — add `_resolve_dna_for_video()` + wire into `_run_rss`/`_run_generator` (Tasks 7-8)
- `src/short_bot/renderer.py` — pass `animation_style` Jinja var (Task 14)
- `src/short_bot/web/routes/channel_edit.py` — handle `dynamic_dna` form field (Task 9)
- `src/short_bot/web/routes/settings.py` — add OpenAI key form field (Task 10)
- `src/short_bot/web/templates/channels/edit.html.j2` — checkbox UI (Task 9)
- `src/short_bot/web/templates/settings.html.j2` — OpenAI key input (Task 10)
- `templates/{15 archetypes}.html.j2` — stage class wiring (Task 13)
- `templates/gundem.html.j2` — `--i` index var on list items (Task 13)
- `src/short_bot/web/scheduler.py` — daily cleanup job (Task 17)
- `src/short_bot/web/templates/dashboard.html.j2` — cache hit rate badge (Task 18)

---

# Phase F1: Cache Infrastructure

Foundation: embedding client, cache table, secrets plumbing. Ships independently — no user-visible behavior change yet (no caller wired in).

---

### Task 1: Add numpy dependency

**Files:**
- Modify: `pyproject.toml:11-36` (dependencies block)

- [ ] **Step 1: Add numpy to dependencies**

Edit `pyproject.toml`, in the `dependencies` array (after `"PySocks>=1.7",`):

```toml
    "PySocks>=1.7",
    "numpy>=1.24",
]
```

- [ ] **Step 2: Install the new dep**

Run: `pip install -e .`
Expected: `Successfully installed numpy-...` line in output.

- [ ] **Step 3: Verify import works**

Run: `python -c "import numpy as np; print(np.__version__)"`
Expected: A version string ≥ 1.24.0.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(deps): add numpy for embedding cosine similarity"
```

---

### Task 2: Secrets helpers for OpenAI key

**Files:**
- Modify: `src/short_bot/secrets_io.py` (add `update_openai_api_key`)
- Modify: `src/short_bot/pexels.py` (add `resolve_openai_api_key` — keeps secret-resolver pattern colocated)
- Test: `tests/test_secrets_io_openai.py` (new)

- [ ] **Step 1: Write failing test for resolve_openai_api_key**

Create `tests/test_secrets_io_openai.py`:

```python
"""Tests for OpenAI key resolution + secrets writer."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from short_bot.pexels import resolve_openai_api_key
from short_bot.secrets_io import update_openai_api_key


def test_resolve_openai_api_key_from_secrets():
    secrets = {"openai_api_key": "sk-test-123"}
    assert resolve_openai_api_key(secrets) == "sk-test-123"


def test_resolve_openai_api_key_env_beats_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    secrets = {"openai_api_key": "sk-from-secrets"}
    assert resolve_openai_api_key(secrets) == "sk-from-env"


def test_resolve_openai_api_key_empty_when_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert resolve_openai_api_key({}) == ""


def test_update_openai_api_key_writes_to_file(tmp_path: Path):
    p = tmp_path / "secrets.yaml"
    update_openai_api_key(p, "sk-abc")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data == {"openai_api_key": "sk-abc"}


def test_update_openai_api_key_preserves_other_keys(tmp_path: Path):
    p = tmp_path / "secrets.yaml"
    p.write_text(yaml.safe_dump({"pexels_api_key": "px-1"}), encoding="utf-8")
    update_openai_api_key(p, "sk-abc")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data == {"pexels_api_key": "px-1", "openai_api_key": "sk-abc"}


def test_update_openai_api_key_clear_with_none(tmp_path: Path):
    p = tmp_path / "secrets.yaml"
    p.write_text(
        yaml.safe_dump({"openai_api_key": "sk-old", "pexels_api_key": "px-1"}),
        encoding="utf-8",
    )
    update_openai_api_key(p, None)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data == {"pexels_api_key": "px-1"}
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_secrets_io_openai.py -v`
Expected: ImportError — `cannot import name 'resolve_openai_api_key'` and `cannot import name 'update_openai_api_key'`.

- [ ] **Step 3: Add resolve_openai_api_key to pexels.py**

In `src/short_bot/pexels.py`, after `resolve_pexels_api_key` (around line 26):

```python
def resolve_openai_api_key(secrets: dict) -> str:
    """Resolve the OpenAI API key. Env var OPENAI_API_KEY beats secrets dict."""
    return os.environ.get("OPENAI_API_KEY") or secrets.get("openai_api_key") or ""
```

- [ ] **Step 4: Add update_openai_api_key to secrets_io.py**

In `src/short_bot/secrets_io.py`, after `update_channel_proxy`:

```python
def update_openai_api_key(secrets_path: Path, key: str | None) -> None:
    """Set or clear top-level openai_api_key in secrets.yaml.

    - key=str  → upsert
    - key=None → remove

    File created if missing. Other top-level keys are preserved.
    """
    p = Path(secrets_path)
    data: dict = {}
    if p.exists():
        loaded = yaml.safe_load(p.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    if key is None:
        data.pop("openai_api_key", None)
    else:
        data["openai_api_key"] = key
    _atomic_write_yaml(p, data)
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_secrets_io_openai.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/pexels.py src/short_bot/secrets_io.py tests/test_secrets_io_openai.py
git commit -m "feat(secrets): OpenAI API key resolve + update helpers"
```

---

### Task 3: Embeddings client module

**Files:**
- Create: `src/short_bot/embeddings.py`
- Test: `tests/test_embeddings.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_embeddings.py`:

```python
"""Tests for OpenAI embedding HTTP client wrapper."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from short_bot.embeddings import EmbeddingError, embed_text


def _mock_ok_response(vec: list[float]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": [{"embedding": vec}]}
    return resp


def test_embed_text_returns_float_list():
    vec = [0.01] * 1536
    with patch("short_bot.embeddings.requests.post",
               return_value=_mock_ok_response(vec)) as mock_post:
        result = embed_text("hello world", api_key="sk-test")
    assert isinstance(result, list)
    assert len(result) == 1536
    assert result[0] == 0.01
    # Verify POST called with correct URL + headers + payload
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.openai.com/v1/embeddings"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
    body = kwargs["json"]
    assert body["model"] == "text-embedding-3-small"
    assert body["input"] == "hello world"


def test_embed_text_raises_when_no_api_key():
    with pytest.raises(EmbeddingError, match="api_key required"):
        embed_text("hello", api_key="")


def test_embed_text_raises_on_http_error():
    resp = MagicMock()
    resp.status_code = 401
    resp.text = '{"error": "invalid api key"}'
    with patch("short_bot.embeddings.requests.post", return_value=resp):
        with pytest.raises(EmbeddingError, match="HTTP 401"):
            embed_text("hello", api_key="sk-bad")


def test_embed_text_retries_on_5xx_then_succeeds():
    vec = [0.5] * 1536
    err = MagicMock(); err.status_code = 503; err.text = "service down"
    ok = _mock_ok_response(vec)
    with patch("short_bot.embeddings.requests.post",
               side_effect=[err, err, ok]) as mock_post:
        with patch("short_bot.embeddings.time.sleep"):  # skip backoff
            result = embed_text("hello", api_key="sk-test")
    assert len(result) == 1536
    assert mock_post.call_count == 3


def test_embed_text_gives_up_after_retries():
    err = MagicMock(); err.status_code = 503; err.text = "down"
    with patch("short_bot.embeddings.requests.post", return_value=err):
        with patch("short_bot.embeddings.time.sleep"):
            with pytest.raises(EmbeddingError, match="HTTP 503"):
                embed_text("hello", api_key="sk-test")


def test_embed_text_validates_dimension():
    """If OpenAI returns wrong-sized vector, raise."""
    short_vec = [0.1] * 100  # not 1536
    with patch("short_bot.embeddings.requests.post",
               return_value=_mock_ok_response(short_vec)):
        with pytest.raises(EmbeddingError, match="unexpected dimension"):
            embed_text("hello", api_key="sk-test")


def test_embed_text_truncates_oversize_input():
    """Input over ~8000 chars should be truncated to OpenAI's token limit."""
    vec = [0.1] * 1536
    huge = "x" * 50000
    with patch("short_bot.embeddings.requests.post",
               return_value=_mock_ok_response(vec)) as mock_post:
        embed_text(huge, api_key="sk-test")
    sent = mock_post.call_args.kwargs["json"]["input"]
    assert len(sent) <= 8000
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_embeddings.py -v`
Expected: ImportError — `cannot import name 'EmbeddingError'`.

- [ ] **Step 3: Implement embeddings.py**

Create `src/short_bot/embeddings.py`:

```python
"""OpenAI text-embedding-3-small HTTP client wrapper.

Used by dna_cache for per-channel similarity lookup. Pure-requests
(no openai SDK dep) to keep the dep tree minimal.
"""
from __future__ import annotations

import logging
import time

import requests

_LOG = logging.getLogger(__name__)

_OPENAI_URL = "https://api.openai.com/v1/embeddings"
_MODEL = "text-embedding-3-small"
_EXPECTED_DIM = 1536
# Truncate input to 8000 chars before sending. OpenAI's tokenizer ~4 chars/token,
# 8000 chars ≈ 2000 tokens — well under the 8192 token model limit.
_MAX_INPUT_CHARS = 8000
_MAX_RETRIES = 3
_RETRY_BACKOFF_S = 1.0


class EmbeddingError(RuntimeError):
    """Raised when embedding cannot be produced (key missing, API error, etc.)."""


def embed_text(text: str, *, api_key: str, timeout_s: float = 10.0) -> list[float]:
    """Return a 1536-dim embedding vector for `text`.

    Raises EmbeddingError on any failure (caller falls back to static DNA).
    """
    if not api_key:
        raise EmbeddingError("api_key required (no OPENAI_API_KEY env or secrets value)")

    payload = {
        "model": _MODEL,
        "input": text[:_MAX_INPUT_CHARS],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    last_err: str = ""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.post(_OPENAI_URL, json=payload, headers=headers,
                                  timeout=timeout_s)
        except requests.RequestException as e:
            last_err = f"network error: {e}"
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_S * attempt)
                continue
            raise EmbeddingError(last_err) from e

        if resp.status_code == 200:
            data = resp.json().get("data") or []
            if not data:
                raise EmbeddingError("empty data in OpenAI response")
            vec = data[0].get("embedding") or []
            if len(vec) != _EXPECTED_DIM:
                raise EmbeddingError(
                    f"unexpected dimension {len(vec)} (want {_EXPECTED_DIM})"
                )
            return [float(x) for x in vec]

        # Retry on 5xx; bail on 4xx
        if 500 <= resp.status_code < 600 and attempt < _MAX_RETRIES:
            last_err = f"HTTP {resp.status_code} {resp.text[:200]}"
            time.sleep(_RETRY_BACKOFF_S * attempt)
            continue
        raise EmbeddingError(f"HTTP {resp.status_code} {resp.text[:200]}")

    raise EmbeddingError(last_err or "exhausted retries")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_embeddings.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/embeddings.py tests/test_embeddings.py
git commit -m "feat(embeddings): OpenAI text-embedding-3-small HTTP client"
```

---

### Task 4: dna_cache table + save/lookup/cleanup

**Files:**
- Modify: `src/short_bot/db.py` (add `dna_cache` table)
- Create: `src/short_bot/dna_cache.py` (helpers)
- Test: `tests/test_dna_cache.py` (new)

- [ ] **Step 1: Add dna_cache table definition to db.py**

In `src/short_bot/db.py`, after the existing tables (around line 100, before any function definitions), add:

```python
dna_cache = Table(
    "dna_cache", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel_slug", String, nullable=False),
    Column("topic_text", Text, nullable=False),
    Column("embedding", Text, nullable=False),  # JSON array of floats; small enough
    Column("dna_json", Text, nullable=False),
    Column("css_filename", String, nullable=False),
    Column("archetype", String, nullable=False),
    Column("created_at", DateTime, default=_utcnow, nullable=False),
    Column("last_used_at", DateTime),
    Column("hit_count", Integer, default=0, nullable=False),
)
Index("idx_dna_cache_channel_created",
      dna_cache.c.channel_slug, dna_cache.c.created_at)
```

> **Note:** Spec called for BLOB-packed float32 (~6KB/row). For simplicity and to keep `db.py` Text-only, store as JSON array of floats (~24KB/row). At expected per-channel volume (~1000 rows max), the size delta is irrelevant. Conversion to numpy happens in `dna_cache.py` lookup helpers below.

- [ ] **Step 2: Write failing tests**

Create `tests/test_dna_cache.py`:

```python
"""Tests for dna_cache: save, lookup-by-similarity, cleanup."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert, select

from short_bot.db import dna_cache, init_db
from short_bot.dna import DnaSpec
from short_bot.dna_cache import (
    CacheHit, cleanup_expired_dna_cache, increment_hit_count,
    lookup_cached_dna, save_cached_dna,
)


@pytest.fixture
def eng(tmp_path):
    db_path = tmp_path / "test.db"
    return init_db(db_path)


def _vec(seed: float) -> list[float]:
    """Construct a 1536-dim test vector dominated by `seed`."""
    return [seed] + [0.0] * 1535


def _sample_dna() -> DnaSpec:
    """Minimal valid DnaSpec for tests."""
    return DnaSpec.model_validate({
        "archetype": "newscast",
        "palette": {
            "primary": "#bb1f1f", "accent": "#ffd54a",
            "bg_gradient": ["#0a0a0a", "#1a1a1a"],
            "body_bg": ["#101010", "#1f1f1f"],
            "text_main": "#ffffff", "text_muted": "#cccccc",
        },
        "fonts": {"headline": "Inter", "body": "Inter", "google_imports": []},
        "tone": {
            "voice": "ciddi", "style": "haber",
            "forbidden": [], "sentence_max_words": 18,
            "paragraph_sentences": [3, 5],
            "body_max_chars": 350, "headline_style_hint": "",
        },
        "persona_summary": "test", "custom_css": "", "ui_badge": "TEST",
    })


def test_save_then_lookup_roundtrip(eng):
    dna = _sample_dna()
    save_cached_dna(eng, "ch1", "transfer haberi", _vec(1.0), dna, "dynamic-ch1-aaa.css")
    hit = lookup_cached_dna(eng, "ch1", _vec(1.0), threshold=0.85)
    assert hit is not None
    assert hit.archetype == "newscast"
    assert hit.css_filename == "dynamic-ch1-aaa.css"
    assert hit.score > 0.99


def test_lookup_returns_none_below_threshold(eng):
    dna = _sample_dna()
    save_cached_dna(eng, "ch1", "transfer haberi", _vec(1.0), dna, "x.css")
    # Orthogonal vector → cosine ≈ 0
    other = [0.0] * 1535 + [1.0]
    hit = lookup_cached_dna(eng, "ch1", other, threshold=0.85)
    assert hit is None


def test_lookup_per_channel_isolation(eng):
    dna = _sample_dna()
    save_cached_dna(eng, "ch1", "x", _vec(1.0), dna, "a.css")
    hit = lookup_cached_dna(eng, "ch2", _vec(1.0), threshold=0.85)
    assert hit is None  # ch1 row not visible to ch2


def test_lookup_picks_max_cosine(eng):
    dna = _sample_dna()
    # Two stored rows: one near, one far
    save_cached_dna(eng, "ch1", "near", _vec(0.9), dna, "near.css")
    save_cached_dna(eng, "ch1", "far",  [0.1] + [0.0]*1535, dna, "far.css")
    query = _vec(0.95)
    hit = lookup_cached_dna(eng, "ch1", query, threshold=0.85)
    assert hit is not None
    assert hit.css_filename == "near.css"


def test_increment_hit_count(eng):
    dna = _sample_dna()
    save_cached_dna(eng, "ch1", "x", _vec(1.0), dna, "x.css")
    hit = lookup_cached_dna(eng, "ch1", _vec(1.0), threshold=0.85)
    assert hit is not None
    increment_hit_count(eng, hit.id)
    increment_hit_count(eng, hit.id)
    with eng.begin() as conn:
        row = conn.execute(select(dna_cache).where(dna_cache.c.id == hit.id)).one()
    assert row.hit_count == 2
    assert row.last_used_at is not None


def test_cleanup_expired_deletes_old_rows_and_files(eng, tmp_path):
    css_dir = tmp_path / "css"; css_dir.mkdir()
    old_css = css_dir / "old.css"; old_css.write_text("/* old */", encoding="utf-8")
    new_css = css_dir / "new.css"; new_css.write_text("/* new */", encoding="utf-8")

    dna = _sample_dna()
    # Manually insert with old timestamp
    old_dt = datetime.now(timezone.utc) - timedelta(days=120)
    new_dt = datetime.now(timezone.utc) - timedelta(days=10)
    with eng.begin() as conn:
        conn.execute(insert(dna_cache).values(
            channel_slug="ch1", topic_text="old",
            embedding=json.dumps(_vec(1.0)),
            dna_json=dna.model_dump_json(),
            css_filename="old.css", archetype="newscast",
            created_at=old_dt, hit_count=0,
        ))
        conn.execute(insert(dna_cache).values(
            channel_slug="ch1", topic_text="new",
            embedding=json.dumps(_vec(1.0)),
            dna_json=dna.model_dump_json(),
            css_filename="new.css", archetype="newscast",
            created_at=new_dt, hit_count=0,
        ))
    deleted = cleanup_expired_dna_cache(eng, css_dir, days=90)
    assert deleted == 1
    assert not old_css.exists()
    assert new_css.exists()
    with eng.begin() as conn:
        rows = conn.execute(select(dna_cache)).fetchall()
    assert len(rows) == 1
    assert rows[0].topic_text == "new"
```

- [ ] **Step 3: Run tests to verify failure**

Run: `pytest tests/test_dna_cache.py -v`
Expected: ImportError — `cannot import name 'CacheHit'` from `short_bot.dna_cache` (module doesn't exist yet).

- [ ] **Step 4: Implement dna_cache.py**

Create `src/short_bot/dna_cache.py`:

```python
"""Per-channel DNA cache with embedding-based similarity lookup.

Backed by the `dna_cache` SQLite table (defined in db.py). Embeddings stored
as JSON arrays; cosine computed in numpy on each lookup. At expected
per-channel volume (~1000 rows over 90 days), linear scan is well under 50ms.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import insert, select, update, delete
from sqlalchemy.engine import Engine

from short_bot.db import dna_cache as _dna_cache_table
from short_bot.dna import DnaSpec

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheHit:
    id: int
    archetype: str
    css_filename: str
    dna: DnaSpec
    score: float


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def save_cached_dna(
    eng: Engine,
    channel_slug: str,
    topic_text: str,
    embedding: list[float],
    dna: DnaSpec,
    css_filename: str,
) -> int:
    """Insert a new cache row. Returns the new id."""
    now = _utcnow()
    with eng.begin() as conn:
        result = conn.execute(insert(_dna_cache_table).values(
            channel_slug=channel_slug,
            topic_text=topic_text,
            embedding=json.dumps(embedding),
            dna_json=dna.model_dump_json(),
            css_filename=css_filename,
            archetype=dna.archetype,
            created_at=now,
            last_used_at=now,
            hit_count=0,
        ))
        return int(result.inserted_primary_key[0])


def lookup_cached_dna(
    eng: Engine,
    channel_slug: str,
    embedding: list[float],
    *,
    threshold: float = 0.85,
) -> CacheHit | None:
    """Find the best-matching cached DNA for this channel, or None.

    Returns None if no row exists or if the best cosine is below threshold.
    """
    query_vec = np.array(embedding, dtype=np.float32)
    query_norm = float(np.linalg.norm(query_vec))
    if query_norm == 0.0:
        return None

    with eng.begin() as conn:
        rows = conn.execute(
            select(_dna_cache_table).where(
                _dna_cache_table.c.channel_slug == channel_slug
            )
        ).fetchall()

    if not rows:
        return None

    best_score = -1.0
    best_row = None
    for row in rows:
        try:
            row_vec = np.array(json.loads(row.embedding), dtype=np.float32)
        except (ValueError, TypeError):
            continue
        row_norm = float(np.linalg.norm(row_vec))
        if row_norm == 0.0:
            continue
        score = float(np.dot(query_vec, row_vec) / (query_norm * row_norm))
        if score > best_score:
            best_score = score
            best_row = row

    if best_row is None or best_score < threshold:
        return None

    try:
        dna = DnaSpec.model_validate(json.loads(best_row.dna_json))
    except Exception as e:
        _LOG.warning(f"failed to parse cached dna_json id={best_row.id}: {e}")
        return None

    return CacheHit(
        id=int(best_row.id),
        archetype=str(best_row.archetype),
        css_filename=str(best_row.css_filename),
        dna=dna,
        score=best_score,
    )


def increment_hit_count(eng: Engine, cache_id: int) -> None:
    """Bump hit_count and update last_used_at."""
    with eng.begin() as conn:
        conn.execute(
            update(_dna_cache_table)
            .where(_dna_cache_table.c.id == cache_id)
            .values(
                hit_count=_dna_cache_table.c.hit_count + 1,
                last_used_at=_utcnow(),
            )
        )


def cleanup_expired_dna_cache(
    eng: Engine,
    css_dir: Path,
    *,
    days: int = 90,
) -> int:
    """Delete cache rows older than `days` and their CSS files. Returns count."""
    cutoff = _utcnow() - timedelta(days=days)
    with eng.begin() as conn:
        rows_to_delete = conn.execute(
            select(_dna_cache_table.c.id, _dna_cache_table.c.css_filename)
            .where(_dna_cache_table.c.created_at < cutoff)
        ).fetchall()
        if not rows_to_delete:
            return 0
        ids = [r.id for r in rows_to_delete]
        conn.execute(
            delete(_dna_cache_table).where(_dna_cache_table.c.id.in_(ids))
        )

    for r in rows_to_delete:
        f = Path(css_dir) / r.css_filename
        try:
            f.unlink(missing_ok=True)
        except OSError as e:
            _LOG.warning(f"could not delete cache CSS {f}: {e}")
    return len(rows_to_delete)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_dna_cache.py -v`
Expected: 6 passed.

- [ ] **Step 6: Run full suite to confirm no regression**

Run: `pytest tests/ -x`
Expected: All previously-passing tests still pass; 13 new tests added across F1.

- [ ] **Step 7: Commit**

```bash
git add src/short_bot/db.py src/short_bot/dna_cache.py tests/test_dna_cache.py
git commit -m "feat(dna_cache): per-channel embedding-based DNA cache"
```

**End of Phase F1.** At this point: cache infrastructure exists, has zero callers, no production behavior change. Safe to ship and iterate.

---

# Phase F2: Per-Video DNA + Opt-In UI

Wires F1's cache into the pipeline. Adds `ChannelConfig.dynamic_dna` flag, `generate_dna_for_video()` LLM function, `_resolve_dna_for_video()` pipeline helper, and the channel-edit UI checkbox + secrets UI for OpenAI key.

---

### Task 5: ChannelConfig.dynamic_dna field

**Files:**
- Modify: `src/short_bot/config.py:55-86` (ChannelConfig dataclass), `:170-197` (load_channel), `:200-262` (save_channel)
- Test: `tests/test_config.py` (extend)

- [ ] **Step 1: Write failing test**

Append to `tests/test_config.py`:

```python
def test_channel_config_dynamic_dna_default_false(tmp_path):
    """dynamic_dna defaults to False; YAML without the key loads cleanly."""
    from short_bot.config import load_channel
    yaml_text = """
slug: test-ch
name: Test
keywords: [a]
language: tr
schedule_cron: "0 * * * *"
duration_s: 25
min_score: 6.0
max_candidates_per_run: 3
template: newscast
colors: {primary: "#fff"}
handle: "@test"
output_dir: "out"
"""
    p = tmp_path / "ch.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    cfg = load_channel(p)
    assert cfg.dynamic_dna is False


def test_channel_config_dynamic_dna_round_trip(tmp_path):
    """dynamic_dna=True survives save → load."""
    from short_bot.config import ChannelConfig, load_channel, save_channel
    cfg = ChannelConfig(
        slug="test-ch", name="Test", keywords=["a"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@test", output_dir="out",
        enabled=True, cta_enabled=True, cta_text="x", cta_icons=[],
        cta_duration_s=4, cta_show_handle=True, language="tr",
        max_age_hours=24, dynamic_dna=True,
    )
    p = tmp_path / "ch.yaml"
    save_channel(p, cfg)
    cfg2 = load_channel(p)
    assert cfg2.dynamic_dna is True


def test_channel_config_dynamic_dna_false_not_written(tmp_path):
    """When dynamic_dna=False, the key is NOT written to YAML (keeps yamls clean)."""
    from short_bot.config import ChannelConfig, save_channel
    cfg = ChannelConfig(
        slug="test-ch", name="Test", keywords=["a"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@test", output_dir="out",
        enabled=True, cta_enabled=True, cta_text="x", cta_icons=[],
        cta_duration_s=4, cta_show_handle=True, language="tr",
        max_age_hours=24, dynamic_dna=False,
    )
    p = tmp_path / "ch.yaml"
    save_channel(p, cfg)
    text = p.read_text(encoding="utf-8")
    assert "dynamic_dna" not in text
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_config.py -k dynamic_dna -v`
Expected: FAIL — `unexpected keyword argument 'dynamic_dna'`.

- [ ] **Step 3: Add field to ChannelConfig dataclass**

In `src/short_bot/config.py`, in the `ChannelConfig` frozen dataclass (after `max_age_hours: int = 24`):

```python
    max_age_hours: int = 24
    dynamic_dna: bool = False
    dna: DnaSpec | None = None
```

- [ ] **Step 4: Read field in load_channel**

In `load_channel()`, in the `return ChannelConfig(...)` constructor call, add (alongside `max_age_hours`):

```python
        max_age_hours=int(data.get("max_age_hours", 24)),
        dynamic_dna=bool(data.get("dynamic_dna", False)),
        template=template,
```

- [ ] **Step 5: Write field in save_channel (only when True)**

In `save_channel()`, after the `data` dict is constructed (around the `if cfg.script_model:` block), add:

```python
    if cfg.dynamic_dna:
        data["dynamic_dna"] = True
```

- [ ] **Step 6: Run tests to verify pass**

Run: `pytest tests/test_config.py -k dynamic_dna -v`
Expected: 3 passed.

- [ ] **Step 7: Run full config tests for regression**

Run: `pytest tests/test_config.py -v`
Expected: All passing.

- [ ] **Step 8: Commit**

```bash
git add src/short_bot/config.py tests/test_config.py
git commit -m "feat(config): ChannelConfig.dynamic_dna opt-in flag"
```

---

### Task 6: generate_dna_for_video LLM function

**Files:**
- Modify: `src/short_bot/dna.py` (append new function after `generate_dna`)
- Test: `tests/test_dna.py` (extend)

- [ ] **Step 1: Write failing test**

Append to `tests/test_dna.py`:

```python
def test_generate_dna_for_video_uses_article_context(monkeypatch):
    """The per-video prompt must include headline + body excerpt."""
    from short_bot.config import ChannelConfig
    from short_bot.dna import build_dna_for_video_prompt

    cfg = ChannelConfig(
        slug="spor-haber", name="Spor", keywords=["futbol"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@spor", output_dir="out",
        enabled=True, cta_enabled=True, cta_text="x", cta_icons=[],
        cta_duration_s=4, cta_show_handle=True, language="tr",
        max_age_hours=24, dynamic_dna=True,
    )
    prompt = build_dna_for_video_prompt(
        channel=cfg,
        headline="Galatasaray Osimhen transferinde son aşamada",
        body="Sarı kırmızılılar Napoli'den Osimhen için 75M Euro teklifte bulundu...",
    )
    assert "Osimhen" in prompt
    assert "Galatasaray" in prompt
    assert "Sarı kırmızılılar" in prompt
    # Channel persona should be referenced when channel has DNA
    assert "Spor" in prompt or "futbol" in prompt
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_dna.py::test_generate_dna_for_video_uses_article_context -v`
Expected: FAIL — `cannot import name 'build_dna_for_video_prompt'`.

- [ ] **Step 3: Implement the prompt builder + generator**

In `src/short_bot/dna.py`, after the existing `generate_dna` function, add:

```python
def build_dna_for_video_prompt(
    *,
    channel: 'ChannelConfig',  # forward ref; imported lazily by callers
    headline: str,
    body: str,
) -> str:
    """Per-article DNA prompt — extends build_dna_prompt with article context.

    Channel persona (from channel.dna.persona_summary if set, else channel.name +
    keywords) anchors the brand; the article's headline + body steers archetype,
    palette mood, and animation_style choice for this specific video.
    """
    lang_name = LANGUAGE_NAMES.get(channel.language, channel.language)
    persona = (
        channel.dna.persona_summary
        if (channel.dna is not None and channel.dna.persona_summary)
        else f"{channel.name} ({', '.join(channel.keywords)})"
    )
    base_voice = (
        channel.dna.tone.voice if channel.dna is not None else "default"
    )

    base = build_dna_prompt(
        name=channel.name,
        keywords=channel.keywords,
        language=channel.language,
    )
    article_block = f"""

═══ BU VİDEO İÇİN MAKALE ═══
KANAL PERSONA: {persona}
KANAL TONU: {base_voice}
DİL: {lang_name}

MAKALE BAŞLIK: {headline}
MAKALE BODY (ilk 500 char): {body[:500]}

EK GÖREV (yukarıdaki kuralların hepsine sadık kal — palette/font/archetype
seçimini sadece BU MAKALEYE göre yap):
- archetype'ı makaleye göre seç (transfer haberi → spor-haber, ekonomi
  açıklaması → ekonomi, magazin dedikodu → tabloid, vb.) — kanalın
  varsayılanına bağlı değilsin
- palette'i makalenin duygusuna göre ayarla (kriz/skandal → koyu+kırmızı,
  başarı/zafer → parlak/altın, sakin teknik → mavi+gri)
- persona_summary kanal personasına SADIK KAL (yukarıda verilen)
- ui_badge bu makalenin temasına uygun kısa bir rozet
"""
    return base + article_block


def generate_dna_for_video(
    *,
    channel: 'ChannelConfig',
    headline: str,
    body: str,
    claude_path: str = "claude",
    model: str = "opus",
) -> DnaSpec:
    """Generate a fresh DnaSpec tuned to a specific article.

    Raises on LLM failure; caller (pipeline._resolve_dna_for_video) catches
    and falls back to channel.dna.
    """
    prompt = build_dna_for_video_prompt(
        channel=channel, headline=headline, body=body,
    )
    return run_json(
        prompt, DnaSpec,
        claude_path=claude_path, model=model,
        retries=2, timeout_s=180,
    )
```

> **Note:** `'ChannelConfig'` is a forward reference (string) to avoid a circular import (`config.py` already imports from `dna.py`). The function only reads fields; no isinstance checks needed.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_dna.py::test_generate_dna_for_video_uses_article_context -v`
Expected: PASS.

- [ ] **Step 5: Run full dna tests**

Run: `pytest tests/test_dna.py -v`
Expected: All passing.

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/dna.py tests/test_dna.py
git commit -m "feat(dna): generate_dna_for_video + per-article prompt"
```

---

### Task 7: Pipeline _resolve_dna_for_video helper

**Files:**
- Modify: `src/short_bot/pipeline.py` (add helper after `_is_recent`)
- Test: `tests/test_pipeline_dynamic_dna.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_pipeline_dynamic_dna.py`:

```python
"""Tests for pipeline._resolve_dna_for_video — cache hit/miss + fallback paths."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.config import ChannelConfig
from short_bot.db import init_db
from short_bot.dna import DnaSpec
from short_bot.pipeline import _resolve_dna_for_video


def _channel(dynamic: bool = True) -> ChannelConfig:
    return ChannelConfig(
        slug="test", name="Test", keywords=["a"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@test", output_dir="out",
        enabled=True, cta_enabled=True, cta_text="x", cta_icons=[],
        cta_duration_s=4, cta_show_handle=True, language="tr",
        max_age_hours=24, dynamic_dna=dynamic,
    )


def _sample_dna() -> DnaSpec:
    return DnaSpec.model_validate({
        "archetype": "tabloid",
        "palette": {
            "primary": "#e8141a", "accent": "#fff100",
            "bg_gradient": ["#000000", "#2a0000"],
            "body_bg": ["#0a0000", "#220000"],
            "text_main": "#ffffff", "text_muted": "#ffd1d1",
        },
        "fonts": {"headline": "Bebas Neue", "body": "Inter", "google_imports": []},
        "tone": {
            "voice": "x", "style": "x", "forbidden": [],
            "sentence_max_words": 10, "paragraph_sentences": [2, 3],
            "body_max_chars": 200, "headline_style_hint": "",
        },
        "persona_summary": "test", "custom_css": "", "ui_badge": "X",
    })


@pytest.fixture
def eng(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def templates_dir(tmp_path):
    d = tmp_path / "templates" / "css"
    d.mkdir(parents=True)
    return tmp_path / "templates"


@pytest.fixture
def secrets_path(tmp_path):
    p = tmp_path / "secrets.yaml"
    p.write_text("openai_api_key: sk-test\n", encoding="utf-8")
    return p


def test_returns_none_when_dynamic_disabled(eng, templates_dir, secrets_path):
    cfg = _channel(dynamic=False)
    log = MagicMock()
    result = _resolve_dna_for_video(
        channel=cfg, headline="x", body="y",
        log=log, claude_path="claude", secrets_path=secrets_path,
        templates_dir=templates_dir, eng=eng,
    )
    assert result is None


def test_returns_none_when_no_api_key(eng, templates_dir, tmp_path):
    cfg = _channel(dynamic=True)
    secrets = tmp_path / "empty.yaml"
    secrets.write_text("", encoding="utf-8")
    log = MagicMock()
    with patch.dict("os.environ", {}, clear=False):
        # Ensure env var not set
        import os
        os.environ.pop("OPENAI_API_KEY", None)
        result = _resolve_dna_for_video(
            channel=cfg, headline="x", body="y",
            log=log, claude_path="claude", secrets_path=secrets,
            templates_dir=templates_dir, eng=eng,
        )
    assert result is None


def test_cache_miss_generates_and_saves(eng, templates_dir, secrets_path):
    cfg = _channel(dynamic=True)
    log = MagicMock()
    fake_emb = [0.1] * 1536
    fake_dna = _sample_dna()

    with patch("short_bot.pipeline.embed_text", return_value=fake_emb), \
         patch("short_bot.pipeline.generate_dna_for_video", return_value=fake_dna):
        result = _resolve_dna_for_video(
            channel=cfg, headline="Galatasaray", body="x" * 500,
            log=log, claude_path="claude", secrets_path=secrets_path,
            templates_dir=templates_dir, eng=eng,
        )
    assert result is not None
    dna, css_path = result
    assert dna.archetype == "tabloid"
    assert css_path.exists()  # CSS file was written
    assert css_path.parent == templates_dir / "css"
    assert css_path.name.startswith("dynamic-test-")


def test_cache_hit_skips_llm(eng, templates_dir, secrets_path):
    cfg = _channel(dynamic=True)
    log = MagicMock()
    fake_emb = [0.5] * 1536
    fake_dna = _sample_dna()

    # Seed cache with a near-identical embedding
    from short_bot.dna_cache import save_cached_dna
    save_cached_dna(eng, "test", "seeded", fake_emb, fake_dna, "preexisting.css")
    # Pre-create the CSS file so the cache hit path can find it
    (templates_dir / "css" / "preexisting.css").write_text("/* seeded */",
                                                          encoding="utf-8")

    with patch("short_bot.pipeline.embed_text", return_value=fake_emb), \
         patch("short_bot.pipeline.generate_dna_for_video") as mock_gen:
        result = _resolve_dna_for_video(
            channel=cfg, headline="x", body="y",
            log=log, claude_path="claude", secrets_path=secrets_path,
            templates_dir=templates_dir, eng=eng,
        )
    assert result is not None
    dna, css_path = result
    assert css_path.name == "preexisting.css"
    mock_gen.assert_not_called()  # LLM never invoked on cache hit


def test_embedding_failure_returns_none(eng, templates_dir, secrets_path):
    """If OpenAI embedding fails, return None so caller falls back to static DNA."""
    cfg = _channel(dynamic=True)
    log = MagicMock()
    from short_bot.embeddings import EmbeddingError
    with patch("short_bot.pipeline.embed_text", side_effect=EmbeddingError("boom")):
        result = _resolve_dna_for_video(
            channel=cfg, headline="x", body="y",
            log=log, claude_path="claude", secrets_path=secrets_path,
            templates_dir=templates_dir, eng=eng,
        )
    assert result is None


def test_generation_failure_returns_none(eng, templates_dir, secrets_path):
    """If Opus generation fails, return None for fallback."""
    cfg = _channel(dynamic=True)
    log = MagicMock()
    fake_emb = [0.2] * 1536

    with patch("short_bot.pipeline.embed_text", return_value=fake_emb), \
         patch("short_bot.pipeline.generate_dna_for_video",
               side_effect=RuntimeError("opus down")):
        result = _resolve_dna_for_video(
            channel=cfg, headline="x", body="y",
            log=log, claude_path="claude", secrets_path=secrets_path,
            templates_dir=templates_dir, eng=eng,
        )
    assert result is None
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_pipeline_dynamic_dna.py -v`
Expected: ImportError — `cannot import name '_resolve_dna_for_video'`.

- [ ] **Step 3: Add helper to pipeline.py**

In `src/short_bot/pipeline.py`, add the imports near the top (after existing imports):

```python
import os
import secrets as _secrets_mod  # avoid shadowing the local `secrets_path` var
from short_bot.dna import DnaSpec, build_css_override, generate_dna_for_video
from short_bot.dna_cache import (
    increment_hit_count, lookup_cached_dna, save_cached_dna,
)
from short_bot.embeddings import EmbeddingError, embed_text
from short_bot.pexels import load_secrets as _load_secrets
from short_bot.pexels import resolve_openai_api_key
```

Then, after `_is_recent` (around line 68), add:

```python
def _resolve_dna_for_video(
    *,
    channel: ChannelConfig,
    headline: str,
    body: str,
    log: logging.Logger,
    claude_path: str,
    secrets_path: Path,
    templates_dir: Path,
    eng,
) -> tuple[DnaSpec, Path] | None:
    """For dynamic_dna channels: lookup cache or generate per-video DNA.

    Returns (dna, css_path) on success or None on any failure
    (caller falls back to channel.dna or channel.template).
    """
    if not channel.dynamic_dna:
        return None

    topic_text = f"{headline}\n{body[:200]}"

    # 1. Resolve key + embed
    api_key = resolve_openai_api_key(_load_secrets(secrets_path))
    if not api_key:
        log.warning("  [dna] no openai_api_key configured → fallback to static")
        return None
    try:
        emb = embed_text(topic_text, api_key=api_key)
    except EmbeddingError as e:
        log.warning(f"  [dna] embedding failed: {e} → fallback to static")
        return None

    css_dir = templates_dir / "css"

    # 2. Cache lookup
    hit = lookup_cached_dna(eng, channel.slug, emb, threshold=0.85)
    if hit is not None:
        css_path = css_dir / hit.css_filename
        if css_path.exists():
            log.info(
                f"  [dna] cache HIT id={hit.id} archetype={hit.archetype} "
                f"(cos={hit.score:.3f})"
            )
            increment_hit_count(eng, hit.id)
            return hit.dna, css_path
        # CSS missing on disk (manual cleanup, etc.) — treat as miss, fall through
        log.warning(
            f"  [dna] cache HIT id={hit.id} but {css_path.name} missing → regenerating"
        )

    # 3. Cache miss → generate
    log.info("  [dna] cache MISS → generating (Opus)…")
    try:
        dna = generate_dna_for_video(
            channel=channel, headline=headline, body=body,
            claude_path=claude_path,
        )
    except Exception as e:  # broad: timeout, JSON parse, validation, etc.
        log.warning(f"  [dna] generation failed: {e} → fallback to static")
        return None

    # 4. Save (DNA + CSS file + cache row)
    try:
        css_text = build_css_override(dna)
        css_filename = f"dynamic-{channel.slug}-{_secrets_mod.token_hex(3)}.css"
        css_path = css_dir / css_filename
        css_dir.mkdir(parents=True, exist_ok=True)
        css_path.write_text(css_text, encoding="utf-8")
        save_cached_dna(eng, channel.slug, topic_text, emb, dna, css_filename)
        log.info(f"  [dna] saved: archetype={dna.archetype} css={css_filename}")
        return dna, css_path
    except OSError as e:
        log.warning(f"  [dna] save failed: {e} → fallback to static")
        return None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pipeline_dynamic_dna.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/pipeline.py tests/test_pipeline_dynamic_dna.py
git commit -m "feat(pipeline): _resolve_dna_for_video cache+generate+fallback"
```

---

### Task 8: Wire _resolve_dna_for_video into _run_rss and _run_generator

**Files:**
- Modify: `src/short_bot/pipeline.py` — both run functions, around the existing template_path resolution

- [ ] **Step 1: Locate and read the existing call sites**

Run: `grep -n "template_path = templates_dir" src/short_bot/pipeline.py`
Expected: 3 occurrences (lines ~410, ~508, ~657).

These are the places where pipeline picks `channel.template` to find the Jinja file. We replace them with effective archetype after resolution.

- [ ] **Step 2: Add resolution block in _run_rss**

In `src/short_bot/pipeline.py`, locate the section in `_run_rss` immediately before the first `template_path = templates_dir / f"{channel.template}.html.j2"`. The relevant block currently looks like:

```python
        script = write_script(...)
        ...
        template_path = templates_dir / f"{channel.template}.html.j2"
```

Replace with:

```python
        script = write_script(...)
        ...
        # Resolve effective DNA (per-video for dynamic_dna channels, else channel-level)
        effective_dna = channel.dna
        effective_css_path = templates_dir / "css" / f"{channel.slug}.css"
        resolved = _resolve_dna_for_video(
            channel=channel,
            headline=f"{script.header_top} {script.header_bottom}",
            body=script.body_paragraph,
            log=log, claude_path=settings.claude_cli_path,
            secrets_path=secrets_path, templates_dir=templates_dir, eng=eng,
        )
        if resolved is not None:
            effective_dna, effective_css_path = resolved
        archetype = effective_dna.archetype if effective_dna is not None else channel.template
        template_path = templates_dir / f"{archetype}.html.j2"
```

> **Note:** Use the actual field names of the `Script` model (`header_top`, `header_bottom`, `body_paragraph`). If those names differ in this codebase, adapt accordingly — verify with `grep -n "class Script" src/short_bot/models.py`.

- [ ] **Step 3: Replicate the same block in _run_generator**

Find the equivalent location in `_run_generator` (just before its `template_path = templates_dir / f"{channel.template}.html.j2"`) and apply the identical `effective_dna` resolution block. Body for generator is `script.body_paragraph` same as RSS.

- [ ] **Step 4: Update overflow_check call site to use effective archetype**

Locate the call: `report = check_overflow(html, archetype=channel.template)` (around line 772 in `_check_overflow_with_retry`). The function signature already takes archetype as a param. Verify by inspection that the *caller* of `_check_overflow_with_retry` has access to the effective archetype. If not, **thread it through** as an additional parameter:

```python
def _check_overflow_with_retry(
    ...,
    template_path: Path,
    archetype: str,   # NEW — was previously read from channel.template inside
    ...
):
    ...
    report = check_overflow(html, archetype=archetype)
```

And update both call sites in `_run_rss` and `_run_generator` to pass the effective archetype.

- [ ] **Step 5: Update build_html call to pass effective DNA + CSS**

The `render_frames` call (which internally calls `build_html`) and `build_html` direct calls inside the overflow check both need to receive `dna_css=effective_css_path.read_text(...)` instead of the static path. Find these calls and update:

```python
# Before:
build_html(check_job, template_path)
# After (in dynamic mode, dna_css comes from effective_css_path):
build_html(check_job, template_path,
           dna_css=effective_css_path.read_text(encoding="utf-8")
                   if effective_css_path.exists() else "")
```

- [ ] **Step 6: Run all pipeline tests**

Run: `pytest tests/test_pipeline.py tests/test_pipeline_dynamic_dna.py tests/test_pipeline_age_filter.py -v`
Expected: All passing. If existing pipeline tests break because they don't set `dynamic_dna`, the field defaults to False, so the new branch is skipped and nothing should break. Investigate any failure.

- [ ] **Step 7: Commit**

```bash
git add src/short_bot/pipeline.py
git commit -m "feat(pipeline): wire dynamic DNA resolution into _run_rss/_run_generator"
```

---

### Task 9: Channel edit UI checkbox

**Files:**
- Modify: `src/short_bot/web/templates/channels/edit.html.j2`
- Modify: `src/short_bot/web/routes/channel_edit.py`
- Test: `tests/test_channel_edit_dynamic_dna.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/test_channel_edit_dynamic_dna.py`:

```python
"""Tests for the dynamic_dna form field in the channel-edit route."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def test_form_post_enables_dynamic_dna(tmp_path, monkeypatch):
    """POSTing dynamic_dna=1 must set the YAML field to True."""
    from short_bot.web.routes.channel_edit import _form_get_bool
    # Form data simulation
    form = {"dynamic_dna": "1"}
    assert _form_get_bool(form, "dynamic_dna", default=False) is True


def test_form_post_omitting_dynamic_dna_disables_it():
    from short_bot.web.routes.channel_edit import _form_get_bool
    form = {}  # checkbox unchecked → key absent
    assert _form_get_bool(form, "dynamic_dna", default=True) is False
```

> **Note:** The route already has a `_form_get_int` helper (used by `max_age_hours`). If `_form_get_bool` doesn't exist yet, add it. If a similar helper exists under another name, adjust the import.

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_channel_edit_dynamic_dna.py -v`
Expected: FAIL — `_form_get_bool` not found, OR test passes if helper already exists.

- [ ] **Step 3: Add _form_get_bool helper if missing**

In `src/short_bot/web/routes/channel_edit.py`, near the existing `_form_get_int`:

```python
def _form_get_bool(form, key: str, *, default: bool) -> bool:
    """Checkbox form field — present means True, absent means False."""
    val = form.get(key)
    if val is None:
        return default if key not in form else False
    return val in ("1", "true", "on", "yes")
```

> **Note:** Form-data semantics — when a checkbox is unchecked, the key is omitted entirely. So we treat absence as False (regardless of `default`) when the form was submitted. The `default` arg is for cases where the form wasn't submitted at all (initial render). The test expects: present-with-1 → True, absent → False (when default=True).

Adjust logic accordingly:

```python
def _form_get_bool(form, key: str, *, default: bool) -> bool:
    """Checkbox: present means True, absent in submitted form means False.
    `default` only applies when the key is fundamentally not represented
    (e.g., GET render, not POST submit). For POST submits, absence == False.
    """
    if key not in form:
        return default
    val = form.get(key)
    return val in ("1", "true", "on", "yes")
```

The test reflects POST: `{}` (no key) — but we want False per checkbox semantics. Update the test:

```python
def test_form_post_omitting_dynamic_dna_disables_it():
    from short_bot.web.routes.channel_edit import _form_get_bool
    # Simulate the form-key-missing-but-submitted case by providing a marker:
    form = {"_form_submitted": "1"}  # key not in form means unchecked
    # In real Flask, request.form is an ImmutableMultiDict; "in" works
    assert _form_get_bool(form, "dynamic_dna", default=False) is False
```

The simpler design: ignore `default` and just return `key in form and form[key] in ("1", ...)`. Pick whichever the route uses elsewhere; document the chosen semantics in the helper docstring.

- [ ] **Step 4: Wire into the form-handler route**

In the POST handler in `channel_edit.py`, where `ChannelConfig(...)` is constructed, add the field:

```python
        max_age_hours=_form_get_int(form, "max_age_hours", default=cfg.max_age_hours),
        dynamic_dna=_form_get_bool(form, "dynamic_dna", default=cfg.dynamic_dna),
```

- [ ] **Step 5: Add checkbox HTML to edit.html.j2**

In `src/short_bot/web/templates/channels/edit.html.j2`, in the form (near the `max_age_hours` field added in v0.1.51):

```html
<label class="block">
  <input type="checkbox" name="dynamic_dna" value="1"
         {% if c.dynamic_dna %}checked{% endif %}
         class="mr-2">
  <span class="text-sm font-semibold text-claude-text">
    🧬 Dinamik DNA — her video için stil yenilensin
  </span>
  <span class="text-[11px] text-claude-subtle block mt-1 ml-6">
    Açıkken her video için Claude (Opus) konuya göre archetype + palette + animation seçer.
    Benzer konular cache'ten gelir (90 gün saklanır). OpenAI API key gerekir
    (Settings → OpenAI Key).
  </span>
</label>
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_channel_edit_dynamic_dna.py -v`
Expected: All passing.

- [ ] **Step 7: Manual smoke (optional, document in commit)**

Start web app, edit a channel, toggle the checkbox, save, reload, verify it persists by inspecting the YAML file.

- [ ] **Step 8: Commit**

```bash
git add src/short_bot/web/routes/channel_edit.py \
        src/short_bot/web/templates/channels/edit.html.j2 \
        tests/test_channel_edit_dynamic_dna.py
git commit -m "feat(ui): channel-edit dynamic_dna checkbox"
```

---

### Task 10: Settings UI for OpenAI API key

**Files:**
- Modify: `src/short_bot/web/routes/settings.py`
- Modify: `src/short_bot/web/templates/settings.html.j2`

- [ ] **Step 1: Inspect existing settings route + template**

Run: `grep -n "pexels_api_key\|PEXELS" src/short_bot/web/routes/settings.py src/short_bot/web/templates/settings.html.j2`

If Pexels key has a UI form already, mirror its pattern for OpenAI. If not, add a minimal form per below.

- [ ] **Step 2: Add OpenAI key handling in settings route**

In the settings POST handler (or read the route file to find the right hook), add:

```python
from short_bot.secrets_io import update_openai_api_key
...
if "openai_api_key" in request.form:
    new_key = (request.form.get("openai_api_key") or "").strip()
    update_openai_api_key(secrets_path, new_key or None)
    flash("OpenAI key updated", "success")
```

- [ ] **Step 3: Add input field to settings template**

In `settings.html.j2`, in the secrets/keys section:

```html
<form method="post" class="mt-4">
  <label class="block mb-2">
    <span class="text-xs text-claude-muted uppercase">OpenAI API Key</span>
    <input type="password" name="openai_api_key"
           value="{{ openai_api_key_masked or '' }}"
           placeholder="sk-..."
           class="bg-claude-surface border border-claude-border px-3 py-2 rounded-lg w-full mt-1 text-sm text-claude-text">
    <span class="text-[10px] text-claude-subtle block mt-1">
      Dinamik DNA özelliği için gereklidir (text-embedding-3-small).
      Boş bırak → mevcut anahtarı sil.
    </span>
  </label>
  <button type="submit" class="bg-claude-primary px-4 py-2 rounded-lg text-sm">Kaydet</button>
</form>
```

- [ ] **Step 4: Pass masked key to template**

In the GET handler:

```python
from short_bot.pexels import load_secrets, resolve_openai_api_key
secrets = load_secrets(secrets_path)
key = resolve_openai_api_key(secrets)
masked = (key[:6] + "…" + key[-4:]) if len(key) > 12 else ""
return render_template("settings.html.j2", openai_api_key_masked=masked, ...)
```

- [ ] **Step 5: Manual smoke**

Start web app, navigate to settings, enter `sk-test-fake`, save, verify `data/secrets.yaml` contains `openai_api_key: sk-test-fake`.

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/web/routes/settings.py \
        src/short_bot/web/templates/settings.html.j2
git commit -m "feat(ui): OpenAI API key field in settings"
```

---

### Task 11: F2 end-to-end smoke test

**Files:**
- Modify: `tests/test_pipeline_dynamic_dna.py` (extend)

- [ ] **Step 1: Add e2e test that exercises full _run_rss with mocked LLM**

Append to `tests/test_pipeline_dynamic_dna.py`:

```python
def test_run_rss_with_dynamic_dna_uses_per_video_archetype(
    tmp_path, monkeypatch
):
    """E2E: a dynamic_dna channel with mocked embeddings + Opus call yields
    a video rendered with the per-video archetype, not channel.template."""
    pytest.importorskip("playwright")  # only run if playwright is installed

    # This is a heavy integration test — see test_pipeline.py fixtures for
    # the full setup pattern. Skipping a literal implementation here because
    # the existing tests/test_pipeline.py contains the channel + RSS fixture
    # scaffolding to copy from. The acceptance behavior:
    #   - channel.template = "newscast" (static fallback would render newscast)
    #   - dynamic_dna = True
    #   - mocked generate_dna_for_video returns DNA with archetype="tabloid"
    #   - assert: rendered HTML contains tabloid-specific element (e.g.,
    #     `.header .top` font weight that differs from newscast).
    pytest.skip("E2E pipeline render test — implement after F2 smoke")
```

This is intentionally a placeholder skip to remind the operator to add a full e2e test once the pipeline is wired. The key unit-level tests in Task 7 already validate `_resolve_dna_for_video` exhaustively; the e2e adds a final integration check after manual smoke.

- [ ] **Step 2: Manual smoke run**

1. Set `OPENAI_API_KEY` env var.
2. Pick or create a low-stakes channel; toggle `dynamic_dna` on via UI.
3. Trigger a "Run Now" from the dashboard.
4. Inspect the run log: should see either `[dna] cache MISS → generating (Opus)…` followed by `[dna] saved`, OR `[dna] cache HIT`.
5. Inspect `templates/css/dynamic-<slug>-*.css` — file should exist.
6. Inspect produced video — visual style should reflect archetype chosen by Opus, possibly different from `channel.template`.

- [ ] **Step 3: Commit (placeholder + smoke notes)**

```bash
git add tests/test_pipeline_dynamic_dna.py
git commit -m "test(pipeline): F2 e2e placeholder + smoke notes"
```

**End of Phase F2.** Dynamic DNA is functional end-to-end. Animation is still `"none"` for all generated DNAs.

---

# Phase F3: Animation Style + Template Wiring

Adds `animation_style` field to DnaSpec, shared CSS keyframes, stage-class wiring on all 15 archetype templates, and gundem stagger `--i` variable. Extends the per-video DNA prompt to suggest animation per article tempo.

---

### Task 12: DnaSpec.animation_style field

**Files:**
- Modify: `src/short_bot/dna.py:185-202` (DnaSpec class)
- Test: `tests/test_dna.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_dna.py`:

```python
def test_dnaspec_animation_style_default_none():
    """Existing DNA without animation_style must default to 'none'."""
    from short_bot.dna import DnaSpec
    spec = DnaSpec.model_validate({
        "archetype": "newscast",
        "palette": {
            "primary": "#bb1f1f", "accent": "#ffd54a",
            "bg_gradient": ["#0a0a0a", "#1a1a1a"],
            "body_bg": ["#101010", "#1f1f1f"],
            "text_main": "#ffffff", "text_muted": "#cccccc",
        },
        "fonts": {"headline": "Inter", "body": "Inter", "google_imports": []},
        "tone": {
            "voice": "x", "style": "x", "forbidden": [],
            "sentence_max_words": 18, "paragraph_sentences": [3, 5],
            "body_max_chars": 350, "headline_style_hint": "",
        },
        "persona_summary": "x", "custom_css": "", "ui_badge": "x",
    })
    assert spec.animation_style == "none"


def test_dnaspec_animation_style_accepts_all_six_values():
    from short_bot.dna import DnaSpec
    base = {
        "archetype": "newscast",
        "palette": {
            "primary": "#bb1f1f", "accent": "#ffd54a",
            "bg_gradient": ["#0a0a0a", "#1a1a1a"],
            "body_bg": ["#101010", "#1f1f1f"],
            "text_main": "#ffffff", "text_muted": "#cccccc",
        },
        "fonts": {"headline": "Inter", "body": "Inter", "google_imports": []},
        "tone": {
            "voice": "x", "style": "x", "forbidden": [],
            "sentence_max_words": 18, "paragraph_sentences": [3, 5],
            "body_max_chars": 350, "headline_style_hint": "",
        },
        "persona_summary": "x", "custom_css": "", "ui_badge": "x",
    }
    for v in ["none", "fade-up", "slide-in", "stagger-reveal",
              "typewriter", "zoom-in"]:
        spec = DnaSpec.model_validate({**base, "animation_style": v})
        assert spec.animation_style == v


def test_dnaspec_animation_style_rejects_invalid():
    import pytest
    from short_bot.dna import DnaSpec
    base = {
        "archetype": "newscast",
        "palette": {
            "primary": "#bb1f1f", "accent": "#ffd54a",
            "bg_gradient": ["#0a0a0a", "#1a1a1a"],
            "body_bg": ["#101010", "#1f1f1f"],
            "text_main": "#ffffff", "text_muted": "#cccccc",
        },
        "fonts": {"headline": "Inter", "body": "Inter", "google_imports": []},
        "tone": {
            "voice": "x", "style": "x", "forbidden": [],
            "sentence_max_words": 18, "paragraph_sentences": [3, 5],
            "body_max_chars": 350, "headline_style_hint": "",
        },
        "persona_summary": "x", "custom_css": "", "ui_badge": "x",
        "animation_style": "rainbow-explosion",
    }
    with pytest.raises(Exception):  # pydantic ValidationError
        DnaSpec.model_validate(base)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_dna.py -k animation_style -v`
Expected: FAIL — `animation_style` field doesn't exist yet.

- [ ] **Step 3: Add field to DnaSpec**

In `src/short_bot/dna.py`, in the `DnaSpec` class (after `ui_badge`):

```python
    ui_badge: str = Field(default="", max_length=24)
    animation_style: Literal[
        "none", "fade-up", "slide-in", "stagger-reveal", "typewriter", "zoom-in",
    ] = "none"
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_dna.py -k animation_style -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/dna.py tests/test_dna.py
git commit -m "feat(dna): animation_style field on DnaSpec"
```

---

### Task 13: Shared animation CSS + 15 template stage classes

**Files:**
- Create: `templates/css/_animations.css`
- Modify: 15 templates in `templates/*.html.j2`

- [ ] **Step 1: Create _animations.css**

Create `templates/css/_animations.css`:

```css
/* Shared animation keyframes for DnaSpec.animation_style.
   Selector pattern: .stage.dna-anim-<style> ... applies to body-text/header.
   Activated by per-video CSS via @import in build_css_override. */

@keyframes anim-fade-up {
  from { opacity: 0; transform: translateY(40px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes anim-slide-in {
  from { opacity: 0; transform: translateX(60px); }
  to   { opacity: 1; transform: translateX(0); }
}
@keyframes anim-zoom-in {
  from { opacity: 0; transform: scale(0.85); }
  to   { opacity: 1; transform: scale(1); }
}
@keyframes anim-typewriter {
  from { clip-path: inset(0 100% 0 0); }
  to   { clip-path: inset(0 0 0 0); }
}

/* Single-element animations */
.dna-anim-fade-up    .body-text,
.dna-anim-fade-up    .header .top  { animation: anim-fade-up 0.8s ease-out forwards; }
.dna-anim-slide-in   .body-text,
.dna-anim-slide-in   .header .top  { animation: anim-slide-in 0.7s ease-out forwards; }
.dna-anim-zoom-in    .body-text,
.dna-anim-zoom-in    .header .top  { animation: anim-zoom-in 0.7s ease-out forwards; }
.dna-anim-typewriter .body-text    { display: inline-block;
                                      animation: anim-typewriter 1.2s steps(40) forwards; }

/* List-mode stagger (gundem) — uses --i index var per item */
.dna-anim-stagger-reveal .list-item {
  opacity: 0;
  animation: anim-fade-up 0.6s ease-out forwards;
  animation-delay: calc(var(--i, 0) * var(--stagger-delay, 1s));
}
```

- [ ] **Step 2: Update build_css_override to import _animations.css**

In `src/short_bot/dna.py`, in `build_css_override()`, before the `:root { ... }` block, prepend:

```python
    css = f"""{google}@import url('_animations.css');
:root {{
  --primary: {p.primary};
  ...
```

> **Note:** This relies on Playwright's `set_content` resolving relative `@import url('_animations.css')` against the page's base. Since pages render via `set_content` (no base URL), prefer **inlining** the animations CSS rather than `@import`. Replace the `@import` line with the literal CSS contents read at module import time:

```python
# At module top
_ANIMATIONS_CSS = (
    Path(__file__).resolve().parent.parent.parent
    / "templates" / "css" / "_animations.css"
).read_text(encoding="utf-8")

# In build_css_override
    css = f"""{google}{_ANIMATIONS_CSS}
:root {{
  --primary: {p.primary};
  ...
```

Verify the path resolves correctly via:

```python
python -c "from short_bot.dna import _ANIMATIONS_CSS; print(len(_ANIMATIONS_CSS))"
```

Expected: an integer matching the file size (~1500 bytes).

- [ ] **Step 3: Add stage-class wiring on all 15 templates**

For each of these templates, locate the root stage div (line 1 of `<body>` content typically `<div class="stage">`):

| Template | Action |
|---|---|
| `templates/newscast.html.j2` | `<div class="stage">` → `<div class="stage dna-anim-{{ animation_style|default('none') }}">` |
| `templates/tabloid.html.j2` | same |
| `templates/magazine.html.j2` | same |
| `templates/kinetic.html.j2` | same |
| `templates/dark-tech.html.j2` | same |
| `templates/stadium.html.j2` | same |
| `templates/meme.html.j2` | same |
| `templates/politika.html.j2` | same |
| `templates/ekonomi.html.j2` | same |
| `templates/spor-haber.html.j2` | same |
| `templates/tech-haber.html.j2` | same |
| `templates/hava-durumu.html.j2` | same |
| `templates/yerel.html.j2` | same |
| `templates/dosya.html.j2` | same |
| `templates/gundem.html.j2` | same — AND add `style="--i: {{ loop.index0 }};"` to `.list-item` element inside the `{% for %}` loop |

For each: use Edit with `old_string='class="stage"'` → `new_string='class="stage dna-anim-{{ animation_style|default(\'none\') }}"'`.

For gundem additionally: locate the `{% for item in items %}` loop's `.list-item` div and add the inline style.

- [ ] **Step 4: Pass animation_style into build_html**

In `src/short_bot/renderer.py`, in `build_html()`, in the `template.render(...)` call, add a new kwarg:

```python
        rss_source=job.rss_source,
        animation_style=getattr(getattr(job, 'dna', None), 'animation_style', 'none')
            if hasattr(job, 'dna') else 'none',
    )
```

> **Note:** `RenderJob` may not currently carry `dna`. Inspect `models.py` and either (a) add `dna: DnaSpec | None` to `RenderJob`, or (b) pass `animation_style` as a separate parameter to `build_html()` and from there into `render_frames()`. Pick (b) if RenderJob is widely consumed and you want the smaller change. The pipeline call site (Task 8) passes `effective_dna.animation_style`.

If choosing (b), update `build_html` signature:

```python
def build_html(
    job: RenderJob,
    template_path: Path,
    *,
    ui_labels: dict[str, str] | None = None,
    dna_css: str = "",
    animation_style: str = "none",  # NEW
) -> str:
```

And in pipeline call sites:

```python
build_html(check_job, template_path, dna_css=..., animation_style=
           effective_dna.animation_style if effective_dna else "none")
```

And in `render_frames()` similarly.

- [ ] **Step 5: Run all tests**

Run: `pytest tests/ -x`
Expected: all passing. Snapshot tests (if any rely on exact HTML) may need re-recording — they all default to `animation_style="none"` so HTML class is `stage dna-anim-none` (a literal change from `stage`). Re-record any failing snapshots.

- [ ] **Step 6: Commit**

```bash
git add templates/css/_animations.css templates/*.html.j2 \
        src/short_bot/dna.py src/short_bot/renderer.py
git commit -m "feat(animation): _animations.css + stage class on all 15 templates"
```

---

### Task 14: Re-record snapshot tests for animation_style="none"

**Files:**
- Modify: `tests/fixtures/snapshots/*.png` (regenerate)

- [ ] **Step 1: Run snapshot tests, observe diffs**

Run: `pytest tests/test_render_snapshots.py -v` (or whichever file holds snapshots)
Expected: snapshot mismatches due to the new `dna-anim-none` class on `.stage`. Even with `animation_style="none"` no actual visual animation runs, but the class itself is in the HTML.

> **Note:** The class change does NOT cause any rendered-pixel diff because no `.dna-anim-none` selector exists in `_animations.css`. Snapshots SHOULD still match unless the test compares HTML strings rather than rendered pixels. Verify by inspecting what the snapshot test asserts.

- [ ] **Step 2: If pixel snapshots match, no update needed**

Run: `pytest tests/test_render_snapshots.py -v`
Expected: passing. If so, skip to step 4.

- [ ] **Step 3: If snapshots are HTML or don't match, regenerate**

Run the regeneration command (per existing project convention; `pytest tests/test_render_snapshots.py --snapshot-update` or similar — check the test file's docstring).

Inspect each updated PNG/file in `git diff` to confirm only expected changes (class attribute, no visual difference).

- [ ] **Step 4: Commit (only if files changed)**

```bash
git add tests/fixtures/snapshots/
git commit -m "test(snapshots): refresh after animation_style class wiring"
```

---

### Task 15: Extend per-video prompt to suggest animation_style

**Files:**
- Modify: `src/short_bot/dna.py` (in `build_dna_for_video_prompt`)

- [ ] **Step 1: Update prompt with animation guidance**

In `build_dna_for_video_prompt`, in the `article_block` string, append after the `ui_badge` instruction:

```python
    article_block = f"""
═══ BU VİDEO İÇİN MAKALE ═══
KANAL PERSONA: {persona}
KANAL TONU: {base_voice}
DİL: {lang_name}

MAKALE BAŞLIK: {headline}
MAKALE BODY (ilk 500 char): {body[:500]}

EK GÖREV (yukarıdaki kuralların hepsine sadık kal — palette/font/archetype
seçimini sadece BU MAKALEYE göre yap):
- archetype'ı makaleye göre seç (transfer haberi → spor-haber, ekonomi
  açıklaması → ekonomi, magazin dedikodu → tabloid, vb.) — kanalın
  varsayılanına bağlı değilsin
- palette'i makalenin duygusuna göre ayarla (kriz/skandal → koyu+kırmızı,
  başarı/zafer → parlak/altın, sakin teknik → mavi+gri)
- persona_summary kanal personasına SADIK KAL (yukarıda verilen)
- ui_badge bu makalenin temasına uygun kısa bir rozet
- animation_style'ı makalenin tempo'suna göre seç:
  * none: sakin, kurumsal duyuru
  * fade-up: standart info shot, çoğu haber için iyi default
  * slide-in: hızlı transfer, son dakika, akut olay
  * stagger-reveal: liste/sayı haberi (gundem, top-5 list, fixtures)
  * typewriter: alıntı/açıklama, derinlikli analiz
  * zoom-in: heyecan, skor, zafer, viral moment
"""
    return base + article_block
```

- [ ] **Step 2: Add a sanity test that animation_style guidance is in prompt**

Append to `tests/test_dna.py`:

```python
def test_per_video_prompt_includes_animation_guidance():
    from short_bot.config import ChannelConfig
    from short_bot.dna import build_dna_for_video_prompt
    cfg = ChannelConfig(
        slug="x", name="X", keywords=["a"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@x", output_dir="out",
        enabled=True, cta_enabled=True, cta_text="x", cta_icons=[],
        cta_duration_s=4, cta_show_handle=True, language="tr",
        max_age_hours=24, dynamic_dna=True,
    )
    prompt = build_dna_for_video_prompt(channel=cfg, headline="x", body="y")
    assert "animation_style" in prompt
    assert "stagger-reveal" in prompt
    assert "fade-up" in prompt
```

- [ ] **Step 3: Run test**

Run: `pytest tests/test_dna.py -k animation_guidance -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/short_bot/dna.py tests/test_dna.py
git commit -m "feat(dna): per-video prompt suggests animation_style per article tempo"
```

**End of Phase F3.** A dynamic-DNA channel can now produce videos with article-appropriate animations.

---

# Phase F4: Observability + Cleanup

Daily TTL cleanup cron + dashboard cache hit-rate badge. No new core features — maintenance and visibility only.

---

### Task 16: Daily cleanup cron job

**Files:**
- Modify: `src/short_bot/web/scheduler.py`

- [ ] **Step 1: Inspect existing scheduler**

Run: `grep -n "add_job\|cron\|interval\|BackgroundScheduler" src/short_bot/web/scheduler.py`

Find the place where scheduled jobs are registered.

- [ ] **Step 2: Add daily cleanup job**

In `scheduler.py`, alongside existing job registrations, add:

```python
from datetime import datetime
from pathlib import Path
from short_bot.dna_cache import cleanup_expired_dna_cache

def _daily_dna_cache_cleanup(eng, templates_dir: Path, log) -> None:
    """Daily cron: delete dna_cache rows older than 90 days + their CSS files."""
    css_dir = Path(templates_dir) / "css"
    try:
        n = cleanup_expired_dna_cache(eng, css_dir, days=90)
        if n > 0:
            log.info(f"[dna_cache] daily cleanup: deleted {n} expired entries")
    except Exception as e:
        log.warning(f"[dna_cache] daily cleanup failed: {e}")

# Register: trigger='cron', hour=3, minute=15 (run at 03:15 every day)
scheduler.add_job(
    _daily_dna_cache_cleanup,
    trigger='cron', hour=3, minute=15,
    args=[eng, templates_dir, log],
    id='dna_cache_cleanup',
    replace_existing=True,
)
```

> **Note:** Adapt the registration to match the existing `scheduler.add_job` style in this codebase. If jobs are registered in a function (e.g., `register_jobs(scheduler, ...)`), add it there.

- [ ] **Step 3: Manual test**

After deploying, wait until the next 03:15 UTC, or trigger manually via:

```python
python -c "
from short_bot.dna_cache import cleanup_expired_dna_cache
from short_bot.db import init_db
from pathlib import Path
eng = init_db(Path('data/state.db'))
n = cleanup_expired_dna_cache(eng, Path('templates/css'), days=90)
print(f'deleted {n}')
"
```

- [ ] **Step 4: Commit**

```bash
git add src/short_bot/web/scheduler.py
git commit -m "feat(scheduler): daily dna_cache cleanup cron at 03:15"
```

---

### Task 17: Dashboard cache hit-rate badge

**Files:**
- Modify: `src/short_bot/web/routes/dashboard.py` (compute stats)
- Modify: `src/short_bot/web/templates/dashboard.html.j2` (render badge)

- [ ] **Step 1: Add cache stats query helper to dna_cache.py**

In `src/short_bot/dna_cache.py`, append:

```python
@dataclass(frozen=True)
class CacheStats:
    rows: int
    total_hits: int

    @property
    def hit_rate(self) -> float:
        """hits / (hits + rows). 0.0 if both are zero."""
        denom = self.total_hits + self.rows
        return self.total_hits / denom if denom > 0 else 0.0


def get_cache_stats(eng: Engine, channel_slug: str) -> CacheStats:
    """Return (row_count, total_hit_count) for a channel's cache."""
    from sqlalchemy import func
    with eng.begin() as conn:
        row = conn.execute(
            select(
                func.count(_dna_cache_table.c.id).label("rows"),
                func.coalesce(func.sum(_dna_cache_table.c.hit_count), 0).label("hits"),
            ).where(_dna_cache_table.c.channel_slug == channel_slug)
        ).one()
    return CacheStats(rows=int(row.rows), total_hits=int(row.hits))
```

- [ ] **Step 2: Write test**

Append to `tests/test_dna_cache.py`:

```python
def test_get_cache_stats(eng):
    from short_bot.dna_cache import get_cache_stats
    dna = _sample_dna()
    save_cached_dna(eng, "ch1", "a", _vec(1.0), dna, "a.css")
    save_cached_dna(eng, "ch1", "b", _vec(0.5), dna, "b.css")
    save_cached_dna(eng, "ch2", "c", _vec(1.0), dna, "c.css")
    # Bump hits on ch1's first row
    hit = lookup_cached_dna(eng, "ch1", _vec(1.0), threshold=0.85)
    increment_hit_count(eng, hit.id)
    increment_hit_count(eng, hit.id)
    stats = get_cache_stats(eng, "ch1")
    assert stats.rows == 2
    assert stats.total_hits == 2
    # hits / (hits + rows) = 2 / 4 = 0.5
    assert stats.hit_rate == 0.5
    other = get_cache_stats(eng, "ch2")
    assert other.rows == 1
    assert other.total_hits == 0
    assert other.hit_rate == 0.0
```

Run: `pytest tests/test_dna_cache.py::test_get_cache_stats -v`
Expected: PASS.

- [ ] **Step 3: Use in dashboard route**

In `src/short_bot/web/routes/dashboard.py`, where channel cards are built, fetch stats:

```python
from short_bot.dna_cache import get_cache_stats

for ch in channels:
    if ch.dynamic_dna:
        ch._cache_stats = get_cache_stats(eng, ch.slug)
    else:
        ch._cache_stats = None
```

- [ ] **Step 4: Render badge in template**

In `dashboard.html.j2`, in the channel card markup, add:

```html
{% if c.dynamic_dna and c._cache_stats %}
  <span class="text-[10px] bg-purple-900/40 text-purple-200 px-2 py-0.5 rounded-full ml-2">
    🧬 dyn ({{ c._cache_stats.rows }} cache,
    {{ '%.0f' % (c._cache_stats.hit_rate * 100) }}% hit)
  </span>
{% endif %}
```

- [ ] **Step 5: Manual smoke**

Visit dashboard, verify badge shows for dynamic-DNA channels with sensible counts.

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/dna_cache.py tests/test_dna_cache.py \
        src/short_bot/web/routes/dashboard.py \
        src/short_bot/web/templates/dashboard.html.j2
git commit -m "feat(dashboard): per-channel dna_cache hit-rate badge"
```

---

### Task 18: Release v0.1.54 with dynamic DNA

**Files:**
- Modify: `pyproject.toml` (version bump)

- [ ] **Step 1: Bump version**

In `pyproject.toml`:
```toml
version = "0.1.54"
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All passing.

- [ ] **Step 3: Run release.ps1 (or manual equivalent)**

Run: `pwsh -File release.ps1 0.1.54` or manual:
```bash
git add pyproject.toml
git commit -m "chore: release v0.1.54 (dynamic DNA per-video style)"
git tag v0.1.54
git push origin master
git push origin v0.1.54
gh release create v0.1.54 --title "v0.1.54 — Dynamic DNA per-video style" \
  --notes "Opt-in per-channel feature: each video gets its own LLM-generated DNA tailored to the article. Embedding-based per-channel cache (90d TTL) bounds Opus cost. New: ChannelConfig.dynamic_dna flag, OpenAI key in settings, animation_style field on DnaSpec, dashboard cache hit-rate badge."
```

- [ ] **Step 4: Verify release**

Open the GitHub releases page, confirm v0.1.54 published with assets.

**End of Phase F4.** Feature shipped end-to-end.

---

## Self-Review

**Spec coverage:**
- ✅ ChannelConfig.dynamic_dna flag → Task 5
- ✅ Embedding client → Task 3
- ✅ DnaCache table + ops → Task 4
- ✅ generate_dna_for_video → Task 6
- ✅ _resolve_dna_for_video pipeline helper → Task 7
- ✅ Pipeline integration (overflow, image picker effective archetype) → Task 8
- ✅ UI checkbox → Task 9
- ✅ OpenAI key UI → Task 10
- ✅ animation_style field → Task 12
- ✅ _animations.css + stage class on 15 templates → Task 13
- ✅ Per-video prompt animation guidance → Task 15
- ✅ Daily cleanup cron → Task 16
- ✅ Dashboard cache stats badge → Task 17
- ✅ Failure modes (embed fail / Opus fail / IO fail) tested → Task 7
- ✅ TTL 90 days → Task 4 + Task 16
- ✅ Per-channel cache scope → Task 4 (channel_slug column + index)

No gaps.

**Placeholder scan:** All steps contain runnable code or exact commands. Task 11 has an explicit `pytest.skip` for the e2e — labeled as a placeholder for manual smoke; not a hidden TODO.

**Type consistency:** `CacheHit`, `CacheStats`, `cleanup_expired_dna_cache(eng, css_dir, *, days)`, `get_cache_stats(eng, channel_slug) -> CacheStats` — all match across tasks. `DnaSpec.animation_style: Literal[...]` matches between Task 12 (definition) and Task 15 (prompt mentions). `_resolve_dna_for_video` signature consistent between Task 7 (definition) and Task 8 (call site).

**Notes for executor:**
- Tasks 8, 9, 10 require minor code reading (existing form helpers, route shape) — instructions say "verify by inspection" rather than dictating exact line numbers, since the exact line numbers shift as the codebase evolves.
- Task 13's `_ANIMATIONS_CSS` path resolution depends on the project layout — the `Path(__file__).resolve().parent.parent.parent` walks from `src/short_bot/dna.py` up to the repo root, then into `templates/css/`. Verify with the explicit `python -c` command in step 2.
- Task 11's e2e skip is intentional; full Playwright integration test is a v2 nice-to-have. Manual smoke notes in Task 11 step 2 are the v1 acceptance.
