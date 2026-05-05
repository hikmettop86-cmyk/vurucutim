# Generator Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `content_source: "generator"` mode that produces shorts from Claude Sonnet (no RSS) with a 3-layer dedup pipeline backed by a `generated_items` table.

**Architecture:** Dispatcher pattern in `pipeline.run_pipeline` splits into `_run_rss` (existing, unchanged) and `_run_generator` (new). Generator emits a single Pydantic `GeneratorResult` (text + topic_tag + Script + image_keywords) per run. Dedup checks: exact hash → fuzzy text → tag-overlap fuzzy. Web UI gets a wizard radio + edit page conditional fields + ✨/📰 list badges.

**Tech Stack:** Python 3.11+, SQLAlchemy Core, Pydantic 2, rapidfuzz, Flask + HTMX + Alpine.js. No new external dependencies.

**Spec:** [docs/superpowers/specs/2026-05-06-generator-mode-design.md](../specs/2026-05-06-generator-mode-design.md)

---

## File Structure

**New files:**
- `src/short_bot/generated_db.py` — `generated_items` table + CRUD (text_hash, insert, recent, by-tag, distribution)
- `src/short_bot/prompt_phrases.py` — 5-language dict of sentinel phrases for prompts
- `src/short_bot/generator.py` — `build_generator_prompt`, `generate_quote`, `check_duplicate`, `GeneratorResult`, `GeneratorRetryExhausted`
- `src/short_bot/web/routes/generator_test.py` — `/channels/<slug>/generator-test` endpoint
- `src/short_bot/web/templates/_partials/generator_test_result.html.j2` — result panel
- `tests/test_generated_db.py`, `tests/test_generator_hash.py`, `tests/test_generator_prompt.py`, `tests/test_generator_result.py`, `tests/test_generator_dedup.py`, `tests/test_pipeline_generator.py`, `tests/test_config_generator.py`, `tests/test_web_generator_test.py`, `tests/test_web_channel_new_generator.py`, `tests/test_web_channel_edit_generator.py`

**Modified files:**
- `src/short_bot/config.py` — add `GeneratorConfig`, extend `ChannelConfig` with `content_source` + `generator`, update `load_channel`/`save_channel`
- `src/short_bot/db.py` — call `generated_db.metadata.create_all` from `init_db`
- `src/short_bot/image_picker.py` — extract `_run_image_search` internal + add `pick_image_for_generator`
- `src/short_bot/pipeline.py` — split into `_run_rss` + `_run_generator`, dispatcher in `run_pipeline`
- `src/short_bot/web/routes/channel_new.py` — handle `content_source` radio + `generator.topic` form field
- `src/short_bot/web/routes/channel_edit.py` — render+save generator fields
- `src/short_bot/web/routes/__init__.py` — register `generator_test` blueprint
- `src/short_bot/web/templates/channels/new.html.j2` — radio + Alpine `x-show` form
- `src/short_bot/web/templates/channels/edit.html.j2` — conditional generator block + Test Üret button
- `src/short_bot/web/templates/_partials/channel_row.html.j2` — ✨/📰 badge

---

## Task 1: `generated_items` Table + Hash Helper

**Files:**
- Create: `src/short_bot/generated_db.py`
- Test: `tests/test_generator_hash.py`

- [ ] **Step 1.1: Write failing tests for `text_hash`**

```python
# tests/test_generator_hash.py
from short_bot.generated_db import text_hash, normalize_for_hash


def test_normalize_strips_punctuation_and_lowercases():
    assert normalize_for_hash("Aşk, sabırla başlar.") == "aşk sabırla başlar"
    assert normalize_for_hash("AŞK SABIRLA BAŞLAR") == "aşk sabırla başlar"
    assert normalize_for_hash("aşk   sabırla\tbaşlar") == "aşk sabırla başlar"


def test_text_hash_paraphrase_collision():
    """Verbatim text and lowercase-with-different-punct should match."""
    h1 = text_hash("Aşk, sabırla başlar.")
    h2 = text_hash("aşk sabırla başlar")
    h3 = text_hash("AŞK; SABIRLA BAŞLAR!")
    assert h1 == h2 == h3
    assert len(h1) == 64  # sha256 hex


def test_text_hash_distinguishes_different_meanings():
    h1 = text_hash("Aşk sabırla başlar.")
    h2 = text_hash("Aşk hızla biter.")
    assert h1 != h2
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `pytest tests/test_generator_hash.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'short_bot.generated_db'`

- [ ] **Step 1.3: Implement `generated_db.py` (skeleton + hash)**

```python
# src/short_bot/generated_db.py
"""generated_items table for content-generator dedup + topic distribution."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, MetaData, String, Table, Text,
    UniqueConstraint, and_, func, select,
)
from sqlalchemy.engine import Engine


# Reuse the same MetaData object so init_db sees both tables.
# (db.py imports this and adds to its create_all run.)
metadata = MetaData()

generated_items = Table(
    "generated_items", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False),
    Column("text", Text, nullable=False),
    Column("text_hash", String(64), nullable=False),
    Column("topic_tag", String, nullable=False),
    Column("language", String, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("short_id", Integer, ForeignKey("shorts.id")),
    Column("status", String, nullable=False, default="used"),  # used | discarded
    UniqueConstraint("channel", "text_hash", name="ix_generated_unique_hash"),
)
Index("ix_generated_recent", generated_items.c.channel,
      generated_items.c.created_at.desc())
Index("ix_generated_topic", generated_items.c.channel,
      generated_items.c.topic_tag, generated_items.c.created_at.desc())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_for_hash(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Used so 'Aşk, sabırla başlar.' and 'aşk sabırla başlar' hash identically.
    """
    text = text.strip().lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `pytest tests/test_generator_hash.py -v`
Expected: 3 passed

- [ ] **Step 1.5: Commit**

```bash
git add src/short_bot/generated_db.py tests/test_generator_hash.py
git commit -m "feat(generator): add generated_items table + text_hash normalizer

3 tests covering punctuation/case normalization, paraphrase collision,
and distinct-meaning separation."
```

---

## Task 2: `generated_items` CRUD Helpers

**Files:**
- Modify: `src/short_bot/generated_db.py` (append CRUD functions)
- Modify: `src/short_bot/db.py` (extend `init_db` to also create generator table)
- Test: `tests/test_generated_db.py`

- [ ] **Step 2.1: Write failing tests for CRUD**

```python
# tests/test_generated_db.py
import pytest

from short_bot.db import init_db
from short_bot.generated_db import (
    insert_generated, recent_generated_texts, exists_hash,
    recent_by_tag, topic_distribution, text_hash,
)


@pytest.fixture
def eng(tmp_path):
    return init_db(tmp_path / "t.sqlite")


def test_insert_and_exists_hash(eng):
    insert_generated(eng, channel="sevgi", text="Aşk her şeydir.",
                     topic_tag="ask", language="tr", status="used",
                     short_id=None)
    h = text_hash("Aşk her şeydir.")
    assert exists_hash(eng, "sevgi", h)
    assert not exists_hash(eng, "sevgi", "0" * 64)
    assert not exists_hash(eng, "other-channel", h)


def test_recent_generated_texts_only_used(eng):
    insert_generated(eng, channel="sevgi", text="A", topic_tag="x",
                     language="tr", status="used", short_id=None)
    insert_generated(eng, channel="sevgi", text="B", topic_tag="x",
                     language="tr", status="discarded", short_id=None)
    insert_generated(eng, channel="sevgi", text="C", topic_tag="x",
                     language="tr", status="used", short_id=None)
    texts = recent_generated_texts(eng, "sevgi", limit=10)
    assert set(texts) == {"A", "C"}    # B excluded


def test_recent_generated_texts_respects_limit_and_order(eng):
    for i in range(5):
        insert_generated(eng, channel="sevgi", text=f"text-{i}",
                         topic_tag="x", language="tr", status="used",
                         short_id=None)
    texts = recent_generated_texts(eng, "sevgi", limit=3)
    assert len(texts) == 3
    assert texts[0] == "text-4"   # most recent first


def test_recent_by_tag_filters_tag_and_window(eng):
    insert_generated(eng, channel="sevgi", text="patient",
                     topic_tag="sabir", language="tr", status="used",
                     short_id=None)
    insert_generated(eng, channel="sevgi", text="hopeful",
                     topic_tag="umut", language="tr", status="used",
                     short_id=None)
    insert_generated(eng, channel="sevgi", text="another patient",
                     topic_tag="sabir", language="tr", status="used",
                     short_id=None)
    found = recent_by_tag(eng, "sevgi", tag="sabir", days=7, limit=10)
    assert set(found) == {"patient", "another patient"}


def test_topic_distribution(eng):
    for _ in range(3):
        insert_generated(eng, channel="sevgi", text=f"a-{_}", topic_tag="ask",
                         language="tr", status="used", short_id=None)
    insert_generated(eng, channel="sevgi", text="b1", topic_tag="umut",
                     language="tr", status="used", short_id=None)
    dist = topic_distribution(eng, "sevgi", days=7)
    assert dist == {"ask": 3, "umut": 1}


def test_unique_constraint_raises_on_duplicate_hash(eng):
    from sqlalchemy.exc import IntegrityError
    insert_generated(eng, channel="sevgi", text="same",
                     topic_tag="x", language="tr", status="used",
                     short_id=None)
    with pytest.raises(IntegrityError):
        insert_generated(eng, channel="sevgi", text="same",
                         topic_tag="x", language="tr", status="used",
                         short_id=None)
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `pytest tests/test_generated_db.py -v`
Expected: FAIL with `ImportError: cannot import name 'insert_generated'`

- [ ] **Step 2.3: Add CRUD functions to `generated_db.py`**

Append to the bottom of `src/short_bot/generated_db.py`:

```python
def insert_generated(
    eng: Engine, *,
    channel: str, text: str, topic_tag: str, language: str,
    status: str = "used", short_id: int | None = None,
) -> int:
    """Insert a generated item. Caller computes hash via `text_hash(text)` implicitly here."""
    h = text_hash(text)
    with eng.begin() as conn:
        result = conn.execute(generated_items.insert().values(
            channel=channel, text=text, text_hash=h,
            topic_tag=topic_tag, language=language,
            created_at=_utcnow(), short_id=short_id, status=status,
        ))
        return result.inserted_primary_key[0]


def update_generated_short_id(eng: Engine, generated_id: int, short_id: int) -> None:
    with eng.begin() as conn:
        conn.execute(generated_items.update()
                     .where(generated_items.c.id == generated_id)
                     .values(short_id=short_id))


def exists_hash(eng: Engine, channel: str, hash_value: str) -> bool:
    with eng.connect() as conn:
        row = conn.execute(
            select(generated_items.c.id)
            .where(generated_items.c.channel == channel)
            .where(generated_items.c.text_hash == hash_value)
            .limit(1)
        ).fetchone()
    return row is not None


def recent_generated_texts(
    eng: Engine, channel: str, *, limit: int = 50,
) -> list[str]:
    """Return most recent `used` texts (newest first), capped at `limit`."""
    with eng.connect() as conn:
        rows = conn.execute(
            select(generated_items.c.text)
            .where(generated_items.c.channel == channel)
            .where(generated_items.c.status == "used")
            .order_by(generated_items.c.created_at.desc())
            .limit(limit)
        ).fetchall()
    return [r[0] for r in rows]


def recent_by_tag(
    eng: Engine, channel: str, *, tag: str, days: int = 7, limit: int = 20,
) -> list[str]:
    cutoff = _utcnow() - timedelta(days=days)
    with eng.connect() as conn:
        rows = conn.execute(
            select(generated_items.c.text)
            .where(generated_items.c.channel == channel)
            .where(generated_items.c.topic_tag == tag)
            .where(generated_items.c.status == "used")
            .where(generated_items.c.created_at >= cutoff)
            .order_by(generated_items.c.created_at.desc())
            .limit(limit)
        ).fetchall()
    return [r[0] for r in rows]


def topic_distribution(
    eng: Engine, channel: str, *, days: int = 7,
) -> dict[str, int]:
    cutoff = _utcnow() - timedelta(days=days)
    with eng.connect() as conn:
        rows = conn.execute(
            select(generated_items.c.topic_tag,
                   func.count(generated_items.c.id))
            .where(generated_items.c.channel == channel)
            .where(generated_items.c.status == "used")
            .where(generated_items.c.created_at >= cutoff)
            .group_by(generated_items.c.topic_tag)
        ).fetchall()
    return {tag: count for tag, count in rows}
```

- [ ] **Step 2.4: Wire `init_db` to create the generator table**

Modify `src/short_bot/db.py:89` (the line `metadata.create_all(eng)`):

```python
def init_db(db_path: Path | str) -> Engine:
    """Create engine, enable WAL + FK + busy_timeout, create schema if absent."""
    db_path = Path(db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    with eng.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.exec_driver_sql("PRAGMA busy_timeout=5000")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    metadata.create_all(eng)
    # Also create generator-mode tables (separate MetaData object)
    from short_bot.generated_db import metadata as generator_metadata
    generator_metadata.create_all(eng)
    return eng
```

- [ ] **Step 2.5: Run tests to verify they pass**

Run: `pytest tests/test_generated_db.py tests/test_generator_hash.py -v`
Expected: 9 passed total (3 from Task 1 + 6 here)

- [ ] **Step 2.6: Run full suite to verify no regression**

Run: `pytest -q`
Expected: 192 passed (existing 183 + 9 new)

- [ ] **Step 2.7: Commit**

```bash
git add src/short_bot/generated_db.py src/short_bot/db.py tests/test_generated_db.py
git commit -m "feat(generator): generated_items CRUD + dispatcher init_db

insert_generated, exists_hash, recent_generated_texts (used-only),
recent_by_tag, topic_distribution. UNIQUE(channel, text_hash) enforced."
```

---

## Task 3: `GeneratorConfig` + `ChannelConfig.content_source`

**Files:**
- Modify: `src/short_bot/config.py`
- Test: `tests/test_config_generator.py`

- [ ] **Step 3.1: Write failing tests**

```python
# tests/test_config_generator.py
import pytest

from short_bot.config import (
    ChannelConfig, GeneratorConfig, load_channel, save_channel,
)


def _make_rss_yaml(tmp_path):
    p = tmp_path / "ch.yaml"
    p.write_text("""\
slug: test-rss
name: Test RSS
language: tr
keywords: [haber, ekonomi]
schedule_cron: "0 8 * * *"
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors: {primary: "#c81e1e", accent: "#ffea3b", bg_gradient: ["#1a3b6b", "#0a1a3b"]}
handle: "@test"
output_dir: output/test
enabled: true
cta:
  enabled: true
  text: BEĞEN
  icons: ["❤️"]
  duration_s: 4
  show_handle: true
""", encoding="utf-8")
    return p


def _make_generator_yaml(tmp_path):
    p = tmp_path / "gen.yaml"
    p.write_text("""\
slug: sevgi
name: Sevgi
language: tr
content_source: generator
generator:
  topic: "Sevgi ve aşk üzerine kısa, vurucu sözler"
  forbidden_lookback: 50
  max_retries: 3
  fuzzy_threshold: 0.85
schedule_cron: "0 9 * * *"
duration_s: 7
min_score: 0.0
max_candidates_per_run: 1
template: kinetic
colors: {primary: "#c81e1e", accent: "#ffea3b", bg_gradient: ["#000", "#111"]}
handle: "@sevgi"
output_dir: output/sevgi
enabled: true
cta:
  enabled: true
  text: BEĞEN
  icons: ["❤️"]
  duration_s: 4
  show_handle: true
""", encoding="utf-8")
    return p


def test_default_content_source_is_rss(tmp_path):
    cfg = load_channel(_make_rss_yaml(tmp_path))
    assert cfg.content_source == "rss"
    assert cfg.generator is None


def test_load_generator_channel(tmp_path):
    cfg = load_channel(_make_generator_yaml(tmp_path))
    assert cfg.content_source == "generator"
    assert cfg.generator is not None
    assert cfg.generator.topic.startswith("Sevgi")
    assert cfg.generator.forbidden_lookback == 50
    assert cfg.generator.max_retries == 3
    assert cfg.generator.fuzzy_threshold == 0.85


def test_generator_block_required_when_source_is_generator(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("""\
slug: bad
name: Bad
language: tr
content_source: generator
schedule_cron: "0 9 * * *"
duration_s: 7
min_score: 0.0
max_candidates_per_run: 1
template: kinetic
colors: {primary: "#000", accent: "#111", bg_gradient: ["#000", "#111"]}
handle: "@x"
output_dir: output/bad
enabled: true
cta: {enabled: false, text: "", icons: [], duration_s: 0, show_handle: false}
""", encoding="utf-8")
    with pytest.raises(ValueError, match="generator"):
        load_channel(p)


def test_generator_topic_min_length(tmp_path):
    """topic too short → reject."""
    p = tmp_path / "short.yaml"
    p.write_text("""\
slug: short-topic
name: X
language: tr
content_source: generator
generator: {topic: "kisa"}
schedule_cron: "0 9 * * *"
duration_s: 7
min_score: 0.0
max_candidates_per_run: 1
template: kinetic
colors: {primary: "#000", accent: "#111", bg_gradient: ["#000", "#111"]}
handle: "@x"
output_dir: output/x
enabled: true
cta: {enabled: false, text: "", icons: [], duration_s: 0, show_handle: false}
""", encoding="utf-8")
    with pytest.raises(ValueError, match="topic"):
        load_channel(p)


def test_save_channel_roundtrip_generator(tmp_path):
    src = _make_generator_yaml(tmp_path)
    cfg = load_channel(src)
    dst = tmp_path / "out.yaml"
    save_channel(dst, cfg)
    cfg2 = load_channel(dst)
    assert cfg2.content_source == "generator"
    assert cfg2.generator.topic == cfg.generator.topic
    assert cfg2.generator.forbidden_lookback == 50
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `pytest tests/test_config_generator.py -v`
Expected: FAIL with `ImportError: cannot import name 'GeneratorConfig'`

- [ ] **Step 3.3: Add `GeneratorConfig` + extend `ChannelConfig`**

Modify `src/short_bot/config.py`. Add after the existing `Settings` dataclass:

```python
from typing import Literal


@dataclass(frozen=True)
class GeneratorConfig:
    topic: str
    forbidden_lookback: int = 50
    max_retries: int = 3
    fuzzy_threshold: float | None = None


@dataclass(frozen=True)
class ChannelConfig:
    slug: str
    name: str
    keywords: list[str]
    rss_locale: str
    schedule_cron: str
    duration_s: int
    min_score: float
    max_candidates_per_run: int
    template: str
    colors: dict
    handle: str
    output_dir: str
    enabled: bool
    cta_enabled: bool
    cta_text: str
    cta_icons: list[str]
    cta_duration_s: int
    cta_show_handle: bool
    language: str = "tr"
    dna: DnaSpec | None = None
    script_model: str | None = None
    content_source: Literal["rss", "generator"] = "rss"
    generator: GeneratorConfig | None = None
```

(The existing `ChannelConfig` already has the fields above `language`; just add the two new fields at the bottom.)

- [ ] **Step 3.4: Update `load_channel` to parse generator block**

In `load_channel`, after the existing parse logic and before the final `return ChannelConfig(...)`, add:

```python
    content_source = data.get("content_source", "rss")
    if content_source not in ("rss", "generator"):
        raise ValueError(
            f"content_source must be 'rss' or 'generator', got {content_source!r}"
        )

    generator = None
    if content_source == "generator":
        gen_data = data.get("generator")
        if not gen_data:
            raise ValueError(
                "content_source='generator' requires a 'generator' block in YAML"
            )
        topic = (gen_data.get("topic") or "").strip()
        if len(topic) < 10:
            raise ValueError(
                f"generator.topic must be at least 10 chars, got {len(topic)}"
            )
        generator = GeneratorConfig(
            topic=topic,
            forbidden_lookback=int(gen_data.get("forbidden_lookback", 50)),
            max_retries=int(gen_data.get("max_retries", 3)),
            fuzzy_threshold=(float(gen_data["fuzzy_threshold"])
                              if "fuzzy_threshold" in gen_data else None),
        )
```

Then add to the `return ChannelConfig(...)` call:

```python
        # ... existing kwargs ...
        content_source=content_source,
        generator=generator,
```

- [ ] **Step 3.5: Update `save_channel` to emit generator block**

In `save_channel`, before the final `Path(path).write_text(...)`, add:

```python
    if cfg.content_source != "rss":
        data["content_source"] = cfg.content_source
    if cfg.generator is not None:
        gen_data = {
            "topic": cfg.generator.topic,
            "forbidden_lookback": cfg.generator.forbidden_lookback,
            "max_retries": cfg.generator.max_retries,
        }
        if cfg.generator.fuzzy_threshold is not None:
            gen_data["fuzzy_threshold"] = cfg.generator.fuzzy_threshold
        data["generator"] = gen_data
```

- [ ] **Step 3.6: Run tests to verify they pass**

Run: `pytest tests/test_config_generator.py -v`
Expected: 5 passed

- [ ] **Step 3.7: Run full suite to verify no regression**

Run: `pytest -q`
Expected: 197 passed (192 + 5)

- [ ] **Step 3.8: Commit**

```bash
git add src/short_bot/config.py tests/test_config_generator.py
git commit -m "feat(generator): GeneratorConfig + ChannelConfig.content_source

Default 'rss' for backward compat. 'generator' requires generator block
with topic >= 10 chars. Round-trips through save_channel/load_channel."
```

---

## Task 4: `prompt_phrases` Module (5 Languages)

**Files:**
- Create: `src/short_bot/prompt_phrases.py`
- Test: `tests/test_prompt_phrases.py`

- [ ] **Step 4.1: Write failing tests**

```python
# tests/test_prompt_phrases.py
from short_bot.prompt_phrases import GENERATOR_PHRASES, get_phrases


def test_all_5_languages_present():
    assert set(GENERATOR_PHRASES) == {"tr", "en", "de", "es", "fr"}


def test_each_language_has_required_keys():
    required = {"channel_id", "topic", "language", "task",
                "forbidden_intro", "forbidden_end", "topic_rotation",
                "output_intro", "critical"}
    for lang, phrases in GENERATOR_PHRASES.items():
        missing = required - set(phrases)
        assert not missing, f"{lang} missing: {missing}"


def test_get_phrases_falls_back_to_tr_for_unknown():
    p = get_phrases("zz")
    assert p == GENERATOR_PHRASES["tr"]


def test_tr_language_label_is_turkce():
    assert GENERATOR_PHRASES["tr"]["language"] == "Türkçe"
    assert GENERATOR_PHRASES["en"]["language"] == "English"
    assert GENERATOR_PHRASES["de"]["language"] == "Deutsch"
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `pytest tests/test_prompt_phrases.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4.3: Implement `prompt_phrases.py`**

```python
# src/short_bot/prompt_phrases.py
"""Localized sentinel phrases used by the generator-mode prompt."""
from __future__ import annotations


GENERATOR_PHRASES: dict[str, dict[str, str]] = {
    "tr": {
        "channel_id": "KANAL KİMLİĞİ",
        "topic": "Konu",
        "language": "Türkçe",
        "task": "GÖREV",
        "forbidden_intro": "ASLA AŞAĞIDAKİ METİNLERE BENZER ÜRETME (paraphrase dahil):",
        "forbidden_end": "─── liste sonu ───",
        "topic_rotation": "TEMA ROTASYONU (son 7 gün)",
        "output_intro": "ÇIKTI (sadece bu JSON, başka metin yazma)",
        "critical": "KRİTİK",
    },
    "en": {
        "channel_id": "CHANNEL IDENTITY",
        "topic": "Topic",
        "language": "English",
        "task": "TASK",
        "forbidden_intro": "DO NOT produce anything similar to these (paraphrase included):",
        "forbidden_end": "─── end of list ───",
        "topic_rotation": "TOPIC ROTATION (last 7 days)",
        "output_intro": "OUTPUT (only this JSON, no other text)",
        "critical": "CRITICAL",
    },
    "de": {
        "channel_id": "KANAL-IDENTITÄT",
        "topic": "Thema",
        "language": "Deutsch",
        "task": "AUFGABE",
        "forbidden_intro": "ERZEUGE NIEMALS etwas Ähnliches (Paraphrasen eingeschlossen):",
        "forbidden_end": "─── Ende der Liste ───",
        "topic_rotation": "THEMENROTATION (letzte 7 Tage)",
        "output_intro": "AUSGABE (nur dieses JSON, keinen anderen Text)",
        "critical": "WICHTIG",
    },
    "es": {
        "channel_id": "IDENTIDAD DEL CANAL",
        "topic": "Tema",
        "language": "Español",
        "task": "TAREA",
        "forbidden_intro": "NO produzcas nada similar a estos textos (paráfrasis incluida):",
        "forbidden_end": "─── fin de la lista ───",
        "topic_rotation": "ROTACIÓN DE TEMAS (últimos 7 días)",
        "output_intro": "SALIDA (solo este JSON, sin otro texto)",
        "critical": "CRÍTICO",
    },
    "fr": {
        "channel_id": "IDENTITÉ DE LA CHAÎNE",
        "topic": "Sujet",
        "language": "Français",
        "task": "TÂCHE",
        "forbidden_intro": "NE PRODUIS RIEN de similaire à ces textes (paraphrase incluse) :",
        "forbidden_end": "─── fin de la liste ───",
        "topic_rotation": "ROTATION DES SUJETS (7 derniers jours)",
        "output_intro": "SORTIE (uniquement ce JSON, aucun autre texte)",
        "critical": "CRITIQUE",
    },
}


def get_phrases(language: str) -> dict[str, str]:
    """Return the localized phrase dict, falling back to Turkish for unknown codes."""
    return GENERATOR_PHRASES.get(language, GENERATOR_PHRASES["tr"])
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `pytest tests/test_prompt_phrases.py -v`
Expected: 4 passed

- [ ] **Step 4.5: Commit**

```bash
git add src/short_bot/prompt_phrases.py tests/test_prompt_phrases.py
git commit -m "feat(generator): prompt_phrases module (5 languages)"
```

---

## Task 5: `GeneratorResult` Pydantic Model

**Files:**
- Create: `src/short_bot/generator.py` (skeleton + GeneratorResult only)
- Test: `tests/test_generator_result.py`

- [ ] **Step 5.1: Write failing tests**

```python
# tests/test_generator_result.py
import pytest
from pydantic import ValidationError

from short_bot.generator import GeneratorResult


def _valid_payload():
    return {
        "text": "Aşk, ilk anlayışta başlar.",
        "topic_tag": "tanisma",
        "script": {
            "header_top": "AŞK ÜZERİNE",
            "header_bottom": "BUGÜNÜN SÖZÜ",
            "photo_overlay": "Sevgi Sözü",
            "body_paragraph": "Aşk, ilk anlayışta başlar. İlk bakışta görünen yalnızca dış güzelliktir; ilk anlayışta uyanan ise asıl sevdadır.",
            "highlights": [{"text": "ilk anlayışta", "color": "yellow"}],
            "category": "ask",
            "mood": "neutral",
        },
        "image_keywords": ["couple sunset silhouette", "two hands holding"],
    }


def test_valid_payload_parses():
    r = GeneratorResult(**_valid_payload())
    assert r.text.startswith("Aşk")
    assert r.topic_tag == "tanisma"
    assert r.script.header_top == "AŞK ÜZERİNE"
    assert len(r.image_keywords) == 2


def test_topic_tag_must_be_lowercase_tr():
    payload = _valid_payload()
    payload["topic_tag"] = "Tanisma"   # uppercase first
    with pytest.raises(ValidationError, match="topic_tag"):
        GeneratorResult(**payload)


def test_topic_tag_must_be_single_word():
    payload = _valid_payload()
    payload["topic_tag"] = "tanisma sabir"   # space
    with pytest.raises(ValidationError, match="topic_tag"):
        GeneratorResult(**payload)


def test_text_length_bounds():
    payload = _valid_payload()
    payload["text"] = "x"   # too short
    with pytest.raises(ValidationError):
        GeneratorResult(**payload)
    payload["text"] = "x" * 250   # too long
    with pytest.raises(ValidationError):
        GeneratorResult(**payload)


def test_image_keywords_count_bounds():
    payload = _valid_payload()
    payload["image_keywords"] = ["only one"]
    with pytest.raises(ValidationError):
        GeneratorResult(**payload)
    payload["image_keywords"] = ["a"] * 9
    with pytest.raises(ValidationError):
        GeneratorResult(**payload)


def test_highlights_must_appear_in_body_paragraph():
    """Inherited from Script validator."""
    payload = _valid_payload()
    payload["script"]["highlights"] = [{"text": "DOES NOT APPEAR", "color": "red"}]
    with pytest.raises(ValidationError, match="paragrafta"):
        GeneratorResult(**payload)
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `pytest tests/test_generator_result.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 5.3: Implement `GeneratorResult` skeleton**

```python
# src/short_bot/generator.py
"""Content generator: Sonnet-driven short content with 3-layer dedup."""
from __future__ import annotations

from pydantic import BaseModel, Field

from short_bot.models import Script


class GeneratorRetryExhausted(RuntimeError):
    """Raised when all dedup retries return duplicates — topic likely exhausted."""


class GeneratorResult(BaseModel):
    text: str = Field(min_length=10, max_length=200)
    topic_tag: str = Field(
        min_length=2,
        max_length=20,
        pattern=r"^[a-zçğıöşü]+$",   # Turkish lowercase, single word
    )
    script: Script
    image_keywords: list[str] = Field(min_length=2, max_length=8)
```

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `pytest tests/test_generator_result.py -v`
Expected: 6 passed

- [ ] **Step 5.5: Commit**

```bash
git add src/short_bot/generator.py tests/test_generator_result.py
git commit -m "feat(generator): GeneratorResult Pydantic model

text 10-200, topic_tag /^[a-zçğıöşü]+\$/, image_keywords 2-8.
Inherits Script's highlights-must-be-substring validator."
```

---

## Task 6: `build_generator_prompt`

**Files:**
- Modify: `src/short_bot/generator.py` (append)
- Test: `tests/test_generator_prompt.py`

- [ ] **Step 6.1: Write failing tests**

```python
# tests/test_generator_prompt.py
from short_bot.config import ChannelConfig, GeneratorConfig
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
from short_bot.generator import build_generator_prompt


def _channel(language="tr"):
    return ChannelConfig(
        slug="sevgi", name="Sevgi", keywords=[], rss_locale="",
        schedule_cron="0 9 * * *", duration_s=7, min_score=0.0,
        max_candidates_per_run=1, template="kinetic",
        colors={"primary": "#000", "accent": "#fff", "bg_gradient": ["#000", "#111"]},
        handle="@sevgi", output_dir="output/sevgi", enabled=True,
        cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language=language, dna=None, script_model="sonnet",
        content_source="generator",
        generator=GeneratorConfig(
            topic="Sevgi ve aşk üzerine kısa, vurucu sözler",
        ),
    )


def _dna():
    return DnaSpec(
        archetype="kinetic",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(headline="Anton", body="Inter"),
        tone=DnaTone(voice="duygusal, samimi", style="kısa, vurucu",
                     forbidden=["klişe", "siyaset"], sentence_max_words=14,
                     body_max_chars=300, headline_style_hint="iki satır, büyük harf"),
        category_icon="❤️",
        persona_summary="Sevgi sözleri kanalı.",
    )


def test_includes_channel_topic():
    p = build_generator_prompt(channel=_channel(), dna=_dna(),
                                forbidden_texts=[], topic_distribution={})
    assert "Sevgi ve aşk üzerine kısa, vurucu sözler" in p


def test_includes_forbidden_list():
    p = build_generator_prompt(channel=_channel(), dna=_dna(),
                                forbidden_texts=["Aşk sabırla başlar.",
                                                  "Sevgi her şeydir."],
                                topic_distribution={})
    assert "Aşk sabırla başlar." in p
    assert "Sevgi her şeydir." in p
    assert "ASLA" in p  # forbidden_intro Turkish


def test_includes_topic_distribution_with_marks():
    p = build_generator_prompt(channel=_channel(), dna=_dna(),
                                forbidden_texts=[],
                                topic_distribution={"tanisma": 12, "ozlem": 0,
                                                     "sabir": 8})
    assert "tanisma: 12" in p
    assert "ozlem: 0" in p
    assert "sabir: 8" in p


def test_includes_dna_tone():
    p = build_generator_prompt(channel=_channel(), dna=_dna(),
                                forbidden_texts=[], topic_distribution={})
    assert "duygusal, samimi" in p     # voice
    assert "kısa, vurucu" in p          # style
    assert "klişe" in p                  # forbidden tone
    assert "300" in p                    # body_max_chars


def test_uses_english_phrases_for_en_channel():
    p = build_generator_prompt(channel=_channel(language="en"), dna=_dna(),
                                forbidden_texts=[], topic_distribution={})
    assert "DO NOT" in p              # forbidden_intro English
    assert "TASK" in p                 # task English
    assert "ASLA" not in p


def test_german_phrases_for_de():
    p = build_generator_prompt(channel=_channel(language="de"), dna=_dna(),
                                forbidden_texts=[], topic_distribution={})
    assert "AUFGABE" in p
    assert "Deutsch" in p
```

- [ ] **Step 6.2: Run tests to verify they fail**

Run: `pytest tests/test_generator_prompt.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_generator_prompt'`

- [ ] **Step 6.3: Implement `build_generator_prompt`**

Append to `src/short_bot/generator.py`:

```python
from short_bot.config import ChannelConfig
from short_bot.dna import DnaSpec
from short_bot.prompt_phrases import get_phrases


def build_generator_prompt(
    *,
    channel: ChannelConfig,
    dna: DnaSpec,
    forbidden_texts: list[str],
    topic_distribution: dict[str, int],
) -> str:
    ph = get_phrases(channel.language)
    assert channel.generator is not None, "generator config required"

    forbidden_block = ""
    if forbidden_texts:
        lines = "\n".join(f"{i+1}. {t!r}" for i, t in enumerate(forbidden_texts))
        forbidden_block = (
            f"\n{ph['forbidden_intro']}\n"
            f"─── {len(forbidden_texts)} {ph['forbidden_end'].split('─')[0].strip() or 'items'} ───\n"
            f"{lines}\n"
            f"{ph['forbidden_end']}\n"
        )

    rotation_block = ""
    if topic_distribution:
        # Order ascending — least-used first, marked
        sorted_dist = sorted(topic_distribution.items(), key=lambda kv: kv[1])
        max_count = max(topic_distribution.values()) if topic_distribution else 0
        lines = []
        for tag, count in sorted_dist:
            if count == 0:
                marker = " ← HİÇ KULLANILMAMIŞ" if channel.language == "tr" else " ← UNUSED"
            elif count <= max_count // 3:
                marker = " ← AZ" if channel.language == "tr" else " ← LOW"
            else:
                marker = ""
            lines.append(f"- {tag}: {count}{marker}")
        rotation_block = f"\n{ph['topic_rotation']}:\n" + "\n".join(lines) + "\n"

    forbidden_tone = ", ".join(dna.tone.forbidden) if dna.tone.forbidden else "—"

    return f"""Sen "{channel.name}" kanalı için kısa, vurucu içerik üreten bir yazarsın.

{ph['channel_id']}:
- {ph['topic']}: {channel.generator.topic}
- {ph['language']}: {ph['language']}
- Persona: {dna.persona_summary}
- Voice: {dna.tone.voice}
- Style: {dna.tone.style}
- Forbidden tone: {forbidden_tone}
- Sentence max words: {dna.tone.sentence_max_words}
- Body max chars: {dna.tone.body_max_chars}

{ph['task']}: 1 yeni içerik üret (1 short = 1 üretim).
{forbidden_block}{rotation_block}
topic_tag: tek kelime, lowercase, Türkçe (sabir/umut/ayrilik gibi). Az kullanılmış / hiç kullanılmamış temalardan birini seç.

{ph['output_intro']}:
{{
  "text": "<max 200 karakter, ekranda kalacak ana söz>",
  "topic_tag": "<lowercase tek kelime>",
  "script": {{
    "header_top": "<3-5 kelime, BÜYÜK HARF>",
    "header_bottom": "<3-5 kelime, BÜYÜK HARF>",
    "photo_overlay": "<1-3 kelime, görsel üst yazı>",
    "body_paragraph": "<text'i içersin, en fazla {dna.tone.body_max_chars} karakter>",
    "highlights": [{{"text": "<body_paragraph içinde BİREBİR geçen 1-3 kelime>", "color": "yellow"}}],
    "category": "<tek kelime kategori>",
    "mood": "<breaking|neutral|upbeat>"
  }},
  "image_keywords": ["<3-5 İngilizce arama kelimesi, virgülsüz>"]
}}

{ph['critical']}:
- text: max 200 karakter
- script.body_paragraph: text'i içermek zorunda; en fazla {dna.tone.body_max_chars} karakter
- script.highlights[*].text: body_paragraph içinde BİREBİR geçmek zorunda (case + punctuation dahil)
- script.mood: tam olarak breaking, neutral veya upbeat (üç seçenekten biri)
- image_keywords: İngilizce, görsel arama için ("couple silhouette sunset")
"""
```

- [ ] **Step 6.4: Run tests to verify they pass**

Run: `pytest tests/test_generator_prompt.py -v`
Expected: 6 passed

- [ ] **Step 6.5: Commit**

```bash
git add src/short_bot/generator.py tests/test_generator_prompt.py
git commit -m "feat(generator): build_generator_prompt with i18n phrases

Includes channel topic, DNA tone, forbidden list, topic rotation hints,
strict output schema (with body_paragraph + highlights substring rule)."
```

---

## Task 7: `generate_quote` (Sonnet Call)

**Files:**
- Modify: `src/short_bot/generator.py` (append)
- Test: `tests/test_generator_call.py`

- [ ] **Step 7.1: Write failing test**

```python
# tests/test_generator_call.py
from unittest.mock import patch

from short_bot.generator import GeneratorResult, generate_quote
from tests.test_generator_prompt import _channel, _dna


def _fake_result():
    return GeneratorResult(
        text="Aşk, ilk anlayışta başlar.",
        topic_tag="tanisma",
        script={
            "header_top": "AŞK ÜZERİNE",
            "header_bottom": "BUGÜNÜN SÖZÜ",
            "photo_overlay": "Sevgi",
            "body_paragraph": "Aşk, ilk anlayışta başlar. İlk bakış güzelliği, ilk anlayış sevdayı uyandırır.",
            "highlights": [{"text": "ilk anlayışta", "color": "yellow"}],
            "category": "ask",
            "mood": "neutral",
        },
        image_keywords=["couple sunset silhouette", "two hands"],
    )


def test_generate_quote_calls_run_json_with_correct_model():
    with patch("short_bot.generator.run_json", return_value=_fake_result()) as m:
        result = generate_quote(
            channel=_channel(), dna=_dna(),
            forbidden_texts=[], topic_distribution={},
            claude_path="claude", model="sonnet",
        )
    assert result.topic_tag == "tanisma"
    assert m.call_args.kwargs["model"] == "sonnet"
    # GeneratorResult class passed as schema
    assert m.call_args.args[1] is GeneratorResult


def test_generate_quote_passes_forbidden_into_prompt():
    captured = {}

    def fake_run_json(prompt, schema, *, claude_path, model, retries, timeout_s):
        captured["prompt"] = prompt
        return _fake_result()

    with patch("short_bot.generator.run_json", side_effect=fake_run_json):
        generate_quote(channel=_channel(), dna=_dna(),
                       forbidden_texts=["FORBIDDEN-A", "FORBIDDEN-B"],
                       topic_distribution={"x": 5},
                       claude_path="claude", model="sonnet")
    assert "FORBIDDEN-A" in captured["prompt"]
    assert "FORBIDDEN-B" in captured["prompt"]
    assert "x: 5" in captured["prompt"]
```

- [ ] **Step 7.2: Run test to verify it fails**

Run: `pytest tests/test_generator_call.py -v`
Expected: FAIL with `ImportError: cannot import name 'generate_quote'`

- [ ] **Step 7.3: Implement `generate_quote`**

Append to `src/short_bot/generator.py`:

```python
from short_bot.claude_cli import run_json


def generate_quote(
    *,
    channel: ChannelConfig,
    dna: DnaSpec,
    forbidden_texts: list[str],
    topic_distribution: dict[str, int],
    claude_path: str = "claude",
    model: str = "sonnet",
) -> GeneratorResult:
    prompt = build_generator_prompt(
        channel=channel, dna=dna,
        forbidden_texts=forbidden_texts,
        topic_distribution=topic_distribution,
    )
    return run_json(
        prompt, GeneratorResult,
        claude_path=claude_path, model=model,
        retries=2, timeout_s=180,
    )
```

- [ ] **Step 7.4: Run tests to verify they pass**

Run: `pytest tests/test_generator_call.py -v`
Expected: 2 passed

- [ ] **Step 7.5: Commit**

```bash
git add src/short_bot/generator.py tests/test_generator_call.py
git commit -m "feat(generator): generate_quote wrapper around run_json"
```

---

## Task 8: 3-Layer `check_duplicate`

**Files:**
- Modify: `src/short_bot/generator.py` (append)
- Test: `tests/test_generator_dedup.py`

- [ ] **Step 8.1: Write failing tests**

```python
# tests/test_generator_dedup.py
import pytest
from unittest.mock import MagicMock

from short_bot.db import init_db
from short_bot.generated_db import insert_generated
from short_bot.generator import check_duplicate, DupVerdict
from tests.test_generator_call import _fake_result


@pytest.fixture
def eng(tmp_path):
    return init_db(tmp_path / "t.sqlite")


def test_layer1_exact_hash_in_db(eng):
    insert_generated(eng, channel="sevgi",
                     text="Aşk, ilk anlayışta başlar.",
                     topic_tag="tanisma", language="tr",
                     status="used", short_id=None)
    result = _fake_result()    # same text
    verdict = check_duplicate(eng, "sevgi", result, forbidden=[],
                              fuzzy_threshold=0.85)
    assert verdict.is_duplicate
    assert verdict.reason == "exact_hash"


def test_layer2_fuzzy_text_against_forbidden(eng):
    result = _fake_result()
    forbidden = ["Aşk, ilk anlayışla başlar."]   # 1 character diff
    verdict = check_duplicate(eng, "sevgi", result, forbidden=forbidden,
                              fuzzy_threshold=0.85)
    assert verdict.is_duplicate
    assert verdict.reason.startswith("fuzzy_text")


def test_layer3_same_tag_medium_fuzzy(eng):
    insert_generated(eng, channel="sevgi",
                     text="Aşk, ilk bakışta değil ilk anlayışta başlamalı.",
                     topic_tag="tanisma", language="tr",
                     status="used", short_id=None)
    # _fake_result text: "Aşk, ilk anlayışta başlar." — same tag (tanisma),
    # fuzzy ratio ~ 0.7+ but < 0.85 → layer2 misses, layer3 catches
    result = _fake_result()
    verdict = check_duplicate(eng, "sevgi", result, forbidden=[],
                              fuzzy_threshold=0.85)
    assert verdict.is_duplicate
    assert verdict.reason.startswith("tag_overlap")


def test_novel_passes_all_layers(eng):
    insert_generated(eng, channel="sevgi", text="Tamamen farklı bir konu.",
                     topic_tag="ozlem", language="tr",
                     status="used", short_id=None)
    result = _fake_result()    # tanisma tag, different text
    verdict = check_duplicate(eng, "sevgi", result, forbidden=[],
                              fuzzy_threshold=0.85)
    assert not verdict.is_duplicate
    assert verdict.reason == ""


def test_other_channel_does_not_collide(eng):
    insert_generated(eng, channel="other", text=_fake_result().text,
                     topic_tag="tanisma", language="tr",
                     status="used", short_id=None)
    verdict = check_duplicate(eng, "sevgi", _fake_result(),
                              forbidden=[], fuzzy_threshold=0.85)
    assert not verdict.is_duplicate
```

- [ ] **Step 8.2: Run tests to verify they fail**

Run: `pytest tests/test_generator_dedup.py -v`
Expected: FAIL with `ImportError: cannot import name 'check_duplicate'`

- [ ] **Step 8.3: Implement `check_duplicate`**

Append to `src/short_bot/generator.py`:

```python
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy.engine import Engine

from short_bot.generated_db import (
    exists_hash, recent_by_tag, text_hash,
)


_TAG_OVERLAP_THRESHOLD = 0.70   # same-tag medium-fuzzy match → duplicate


@dataclass
class DupVerdict:
    is_duplicate: bool
    reason: str = ""


def check_duplicate(
    eng: Engine,
    channel_slug: str,
    result: "GeneratorResult",
    forbidden: list[str],
    fuzzy_threshold: float,
) -> DupVerdict:
    """Three-layer duplicate detection.

    Layer 1: exact hash in DB (fast).
    Layer 2: fuzzy ratio >= fuzzy_threshold against forbidden list (in-memory).
    Layer 3: same topic_tag + fuzzy ratio >= 0.70 (DB query).
    """
    # Layer 1: exact hash
    if exists_hash(eng, channel_slug, text_hash(result.text)):
        return DupVerdict(True, "exact_hash")

    # Layer 2: fuzzy text vs forbidden list
    new_low = result.text.lower()
    for prev in forbidden:
        ratio = fuzz.ratio(new_low, prev.lower()) / 100
        if ratio >= fuzzy_threshold:
            return DupVerdict(True, f"fuzzy_text({ratio:.2f})")

    # Layer 3: same-tag medium fuzzy
    same_tag = recent_by_tag(eng, channel_slug, tag=result.topic_tag,
                              days=7, limit=20)
    for prev in same_tag:
        ratio = fuzz.ratio(new_low, prev.lower()) / 100
        if ratio >= _TAG_OVERLAP_THRESHOLD:
            return DupVerdict(
                True, f"tag_overlap({result.topic_tag},{ratio:.2f})"
            )

    return DupVerdict(False)
```

- [ ] **Step 8.4: Run tests to verify they pass**

Run: `pytest tests/test_generator_dedup.py -v`
Expected: 5 passed

- [ ] **Step 8.5: Run full suite**

Run: `pytest -q`
Expected: 218 passed (197 + 21 new tasks 4-8)

- [ ] **Step 8.6: Commit**

```bash
git add src/short_bot/generator.py tests/test_generator_dedup.py
git commit -m "feat(generator): 3-layer dedup (hash → fuzzy → tag-overlap)

Tag-overlap threshold hardcoded at 0.70 (more strict than text fuzzy).
Layer ordering: cheapest first (DB hash lookup → in-mem fuzzy → DB by-tag)."
```

---

## Task 9: Refactor `image_picker` for Generator

**Files:**
- Modify: `src/short_bot/image_picker.py`
- Test: `tests/test_image_picker_generator.py`

- [ ] **Step 9.1: Write failing test**

```python
# tests/test_image_picker_generator.py
from unittest.mock import patch

from short_bot.image_picker import pick_image_for_generator
from short_bot.models import Script


def _script():
    return Script(
        header_top="A", header_bottom="B", photo_overlay="C",
        body_paragraph="x" * 50, highlights=[],
        category="ask", mood="neutral",
    )


def test_pick_image_for_generator_uses_keywords_as_query(tmp_path):
    captured = {}

    def fake_run(query, script, cache_dir, *, claude_path, max_candidates):
        captured["query"] = query
        return None    # simulate no acceptable candidate

    with patch("short_bot.image_picker._run_image_search",
               side_effect=fake_run):
        pick_image_for_generator(
            keywords=["couple silhouette", "sunset"],
            script=_script(), cache_dir=tmp_path,
            claude_path="claude",
        )
    assert captured["query"] == "couple silhouette sunset"
```

- [ ] **Step 9.2: Run test to verify it fails**

Run: `pytest tests/test_image_picker_generator.py -v`
Expected: FAIL with `ImportError: cannot import name 'pick_image_for_generator'`

- [ ] **Step 9.3: Refactor `image_picker.py` to extract internal helper**

Modify `src/short_bot/image_picker.py`. Replace the existing `pick_image_for_script` body, keeping the same public signature:

```python
def pick_image_for_script(
    script: Script,
    cache_dir: Path,
    *,
    claude_path: str = "claude",
    max_candidates: int = 3,
    channel: ChannelConfig | None = None,
) -> Path | None:
    """Search -> download candidates -> verify with Claude -> return first OK image path."""
    query = (build_search_query_for_channel(script, channel)
             if channel is not None else build_search_query(script))
    return _run_image_search(
        query, script, cache_dir,
        claude_path=claude_path, max_candidates=max_candidates,
    )


def pick_image_for_generator(
    *,
    keywords: list[str],
    script: Script,
    cache_dir: Path,
    claude_path: str = "claude",
    max_candidates: int = 3,
) -> Path | None:
    """Image picker for generator mode: query is space-joined keywords from Sonnet."""
    query = " ".join(keywords).strip()
    return _run_image_search(
        query, script, cache_dir,
        claude_path=claude_path, max_candidates=max_candidates,
    )


def _run_image_search(
    query: str,
    script: Script,
    cache_dir: Path,
    *,
    claude_path: str,
    max_candidates: int,
) -> Path | None:
    """Internal: shared DDG → Wikimedia fallback → download → Claude verify loop."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"image search (DDG): {query!r}")
    candidates = search_images(query, max_results=max_candidates)
    if not candidates:
        logger.warning("DDG returned 0 candidates; trying Wikimedia Commons")
        from short_bot.wikimedia_search import search_images_commons
        candidates = search_images_commons(query, max_results=max_candidates)
        if candidates:
            logger.warning(f"Wikimedia returned {len(candidates)} candidates")
    if not candidates:
        logger.warning("no image candidates from any source")
        return None

    for i, cand in enumerate(candidates):
        key = hashlib.sha1(cand.url.encode("utf-8")).hexdigest()[:16]
        path = cache_dir / f"{key}.jpg"
        if not path.exists():
            if not _download(cand.url, path):
                continue
        verdict = _verify_with_claude(path, script, claude_path)
        if verdict is None:
            logger.warning(f"  cand {i}: verification CLI failed -> skip")
            continue
        if verdict.appropriate:
            logger.warning(f"  cand {i} ACCEPTED: {verdict.reason}")
            return path
        logger.warning(f"  cand {i} rejected: {verdict.reason}")
    logger.info("no candidate passed verification")
    return None
```

- [ ] **Step 9.4: Run tests to verify they pass**

Run: `pytest tests/test_image_picker_generator.py tests/ -k image -v`
Expected: existing image picker tests still pass + 1 new

- [ ] **Step 9.5: Run full suite**

Run: `pytest -q`
Expected: 219 passed

- [ ] **Step 9.6: Commit**

```bash
git add src/short_bot/image_picker.py tests/test_image_picker_generator.py
git commit -m "refactor(image_picker): extract _run_image_search + add pick_image_for_generator

Public pick_image_for_script signature unchanged. Generator path joins
Sonnet's image_keywords with spaces and reuses the same DDG/Wiki/verify loop."
```

---

## Task 10: Pipeline Dispatcher (`_run_rss` Extraction)

**Files:**
- Modify: `src/short_bot/pipeline.py`
- Test: `tests/test_pipeline_dispatcher.py`

- [ ] **Step 10.1: Write failing test**

```python
# tests/test_pipeline_dispatcher.py
"""Verify run_pipeline routes by channel.content_source."""
from unittest.mock import patch

from short_bot.pipeline import run_pipeline


def test_rss_channel_routes_to_rss_runner(tmp_path):
    """A channel with content_source='rss' calls _run_rss, not _run_generator."""
    from short_bot.config import ChannelConfig
    cfg = ChannelConfig(
        slug="t", name="T", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="*", duration_s=6, min_score=6.0,
        max_candidates_per_run=1, template="newscast",
        colors={"primary": "#000", "accent": "#111", "bg_gradient": ["#000", "#111"]},
        handle="@t", output_dir=str(tmp_path / "out"),
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language="tr", dna=None, script_model=None,
        content_source="rss", generator=None,
    )
    from short_bot.config import Settings
    s = Settings(ffmpeg_path="ffmpeg", claude_cli_path="claude",
                 playwright_browser="chromium", web_host="127.0.0.1",
                 web_port=5005, fuzzy_dedup_threshold=0.85,
                 log_level="INFO", claude_models={"dna": "opus", "default": "haiku"})
    logs = tmp_path / "logs"; logs.mkdir()
    with patch("short_bot.pipeline._run_rss") as rss, \
         patch("short_bot.pipeline._run_generator") as gen:
        rss.return_value = None
        run_pipeline(channel=cfg, settings=s, db_path=tmp_path / "db.sqlite",
                     music_root=tmp_path, templates_dir=tmp_path,
                     cache_dir=tmp_path, lock_dir=tmp_path / "locks",
                     logs_dir=logs, trigger="test")
    assert rss.called
    assert not gen.called
```

- [ ] **Step 10.2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_dispatcher.py -v`
Expected: FAIL with `AttributeError: module 'short_bot.pipeline' has no attribute '_run_rss'`

- [ ] **Step 10.3: Refactor `pipeline.py` to extract `_run_rss`**

Wrap the existing 8-stage logic (lines 117-249, the body inside `with lock:`) into a new function `_run_rss(channel, run_id, log, eng, settings, lock, ...)` and call it from `run_pipeline`.

The new structure:

```python
def run_pipeline(*, channel, settings, db_path, music_root, templates_dir,
                 cache_dir, logs_dir, lock_dir=None, trigger="cli") -> RunResult:
    eng = init_db(db_path)
    log_path = logs_dir / f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{channel.slug}.log"
    log = _setup_logger(log_path)
    run_id = start_run(eng, channel.slug, trigger=trigger, log_path=str(log_path))

    lock_dir = Path(lock_dir) if lock_dir else Path("data/locks")
    lock = FileLock(str(lock_dir / f"{channel.slug}.lock"), timeout=0)
    (lock_dir).mkdir(parents=True, exist_ok=True)

    try:
        try:
            with lock:
                log.info(f"=== run {run_id} channel={channel.slug} "
                         f"trigger={trigger} source={channel.content_source} ===")
                if channel.content_source == "generator":
                    return _run_generator(
                        channel=channel, run_id=run_id, log=log, eng=eng,
                        settings=settings, music_root=music_root,
                        templates_dir=templates_dir, cache_dir=cache_dir,
                    )
                return _run_rss(
                    channel=channel, run_id=run_id, log=log, eng=eng,
                    settings=settings, music_root=music_root,
                    templates_dir=templates_dir, cache_dir=cache_dir,
                )
        except Timeout:
            finish_run(eng, run_id, status="failed", short_id=None,
                       error="lock busy: pipeline already running for this channel")
            return RunResult(run_id=run_id, status="failed",
                             short_path=None, error="lock busy")
        except Exception as e:
            log.exception("pipeline failed")
            finish_run(eng, run_id, status="failed", short_id=None, error=str(e))
            return RunResult(run_id=run_id, status="failed",
                             short_path=None, error=str(e))
    finally:
        for h in list(log.handlers):
            try:
                h.close()
            except Exception:
                pass
            log.removeHandler(h)
        eng.dispose()


def _run_rss(*, channel, run_id, log, eng, settings,
             music_root, templates_dir, cache_dir) -> RunResult:
    """Existing 8-stage RSS pipeline body. Returns RunResult."""
    log.info("[1/8] fetch_rss")
    items = fetch_rss(channel.keywords, channel.rss_locale)
    log.info(f"  → {len(items)} items")

    log.info("[2/8] dedup")
    new_items = filter_new(eng, items, channel.slug,
                            fuzzy_threshold=settings.fuzzy_dedup_threshold)
    log.info(f"  → {len(new_items)} new")
    from short_bot.db import is_processed
    new_guids = {n.guid for n in new_items}
    for old in items:
        if old.guid in new_guids:
            continue
        if is_processed(eng, old.guid, channel.slug):
            continue
        record_rss_item(eng, guid=old.guid, channel=channel.slug,
                        title=old.title, link=old.link, source=old.source,
                        pub_date=old.pub_date, thumb_url=old.thumb_url,
                        score=None, status="duplicate")

    if not new_items:
        log.info("no candidates → finish")
        finish_run(eng, run_id, status="no_candidates",
                   short_id=None, error=None)
        return RunResult(run_id=run_id, status="no_candidates",
                         short_path=None, error=None)

    # ... (rest of stages 3-8 verbatim from existing run_pipeline body) ...
```

**Implementation rule:** Move the existing `with lock:` body (everything between lines 117-249 of the current `pipeline.py`) into `_run_rss`. Keep all existing logic unchanged. The only edits are: dropping the `with lock:` indent level by one, and replacing `return RunResult(...)` lines that referenced lock-busy/exception cases with their existing handling kept in `run_pipeline`.

Add an empty stub for `_run_generator` for now (will be filled in Task 11):

```python
def _run_generator(*, channel, run_id, log, eng, settings,
                   music_root, templates_dir, cache_dir) -> RunResult:
    """Generator pipeline body (Task 11 fills this in)."""
    raise NotImplementedError("filled in Task 11")
```

- [ ] **Step 10.4: Run dispatcher test + full suite**

Run: `pytest tests/test_pipeline_dispatcher.py tests/test_pipeline_smoke.py -v`
Expected: dispatcher test passes; existing pipeline smoke test passes (regression).

Run: `pytest -q`
Expected: 220 passed

- [ ] **Step 10.5: Commit**

```bash
git add src/short_bot/pipeline.py tests/test_pipeline_dispatcher.py
git commit -m "refactor(pipeline): split into _run_rss + dispatcher (generator stub)

run_pipeline now routes by channel.content_source. _run_rss contains
the existing 8-stage logic verbatim. _run_generator stub raises
NotImplementedError until Task 11."
```

---

## Task 11: `_run_generator` Implementation

**Files:**
- Modify: `src/short_bot/pipeline.py`
- Test: `tests/test_pipeline_generator.py`

- [ ] **Step 11.1: Write failing test (mocked Sonnet)**

```python
# tests/test_pipeline_generator.py
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.config import ChannelConfig, GeneratorConfig, Settings
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
from short_bot.generator import GeneratorResult, GeneratorRetryExhausted
from short_bot.pipeline import run_pipeline


def _settings():
    return Settings(ffmpeg_path="ffmpeg", claude_cli_path="claude",
                    playwright_browser="chromium", web_host="127.0.0.1",
                    web_port=5005, fuzzy_dedup_threshold=0.85,
                    log_level="INFO",
                    claude_models={"dna": "opus", "default": "haiku"})


def _dna_spec():
    return DnaSpec(
        archetype="kinetic",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(headline="Anton", body="Inter"),
        tone=DnaTone(voice="duygusal", style="kısa",
                     forbidden=[], sentence_max_words=12,
                     body_max_chars=200, headline_style_hint="iki satır"),
        category_icon="❤️",
        persona_summary="Sevgi sözleri.",
    )


def _gen_channel(tmp_path, slug="sevgi"):
    return ChannelConfig(
        slug=slug, name="Sevgi", keywords=[], rss_locale="hl=tr",
        schedule_cron="*", duration_s=6, min_score=0.0,
        max_candidates_per_run=1, template="kinetic",
        colors={"primary": "#000", "accent": "#fff",
                "bg_gradient": ["#000", "#111"]},
        handle="@sevgi", output_dir=str(tmp_path / "out"),
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language="tr", dna=_dna_spec(), script_model="sonnet",
        content_source="generator",
        generator=GeneratorConfig(
            topic="Sevgi sözleri üret",
            forbidden_lookback=10, max_retries=2, fuzzy_threshold=0.85,
        ),
    )


def _ok_result(text="Aşk anlayışta başlar.", tag="tanisma"):
    return GeneratorResult(
        text=text,
        topic_tag=tag,
        script={
            "header_top": "AŞK", "header_bottom": "ÜZERİNE",
            "photo_overlay": "Sevgi",
            "body_paragraph": f"{text} Bu söz sevdayı anlatır.",
            "highlights": [], "category": "ask", "mood": "neutral",
        },
        image_keywords=["couple silhouette", "sunset"],
    )


def test_generator_pipeline_success(tmp_path):
    cfg = _gen_channel(tmp_path)
    logs = tmp_path / "logs"; logs.mkdir()
    out_path = tmp_path / "out" / "video.mp4"

    with patch("short_bot.pipeline.generate_quote", return_value=_ok_result()), \
         patch("short_bot.pipeline.pick_image_for_generator", return_value=None), \
         patch("short_bot.pipeline.pick_music",
               return_value=Path("dummy.mp3")), \
         patch("short_bot.pipeline.render_frames"), \
         patch("short_bot.pipeline.compose_video") as compose:
        # Make compose write a fake mp4 file at the expected path
        def _write_fake_mp4(frames_dir, music, op, *, fps, ffmpeg_path,
                             sfx_overlays):
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(b"fake mp4")
        compose.side_effect = _write_fake_mp4

        result = run_pipeline(
            channel=cfg, settings=_settings(),
            db_path=tmp_path / "db.sqlite",
            music_root=tmp_path, templates_dir=tmp_path,
            cache_dir=tmp_path / "cache",
            lock_dir=tmp_path / "locks", logs_dir=logs, trigger="test",
        )

    assert result.status == "success"
    assert result.short_path is not None and result.short_path.exists()


def test_generator_retry_exhaustion_marks_run_failed(tmp_path):
    """All max_retries return duplicates → GeneratorRetryExhausted → run failed."""
    cfg = _gen_channel(tmp_path)
    logs = tmp_path / "logs"; logs.mkdir()

    # Pre-seed DB with the text so layer-1 hash collision triggers each time
    from short_bot.db import init_db
    from short_bot.generated_db import insert_generated
    eng = init_db(tmp_path / "db.sqlite")
    fixed = _ok_result("Tekrarlı söz.")
    insert_generated(eng, channel="sevgi", text=fixed.text,
                     topic_tag=fixed.topic_tag, language="tr",
                     status="used", short_id=None)
    eng.dispose()

    with patch("short_bot.pipeline.generate_quote", return_value=fixed):
        result = run_pipeline(
            channel=cfg, settings=_settings(),
            db_path=tmp_path / "db.sqlite",
            music_root=tmp_path, templates_dir=tmp_path,
            cache_dir=tmp_path / "cache",
            lock_dir=tmp_path / "locks", logs_dir=logs, trigger="test",
        )

    assert result.status == "failed"
    assert "duplicate" in (result.error or "").lower() \
           or "exhausted" in (result.error or "").lower()


def test_generator_records_used_status_and_short_id(tmp_path):
    """After successful render, generated_items.short_id is populated."""
    cfg = _gen_channel(tmp_path)
    logs = tmp_path / "logs"; logs.mkdir()

    with patch("short_bot.pipeline.generate_quote", return_value=_ok_result()), \
         patch("short_bot.pipeline.pick_image_for_generator", return_value=None), \
         patch("short_bot.pipeline.pick_music",
               return_value=Path("dummy.mp3")), \
         patch("short_bot.pipeline.render_frames"), \
         patch("short_bot.pipeline.compose_video") as compose:
        def _w(frames_dir, music, op, *, fps, ffmpeg_path, sfx_overlays):
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(b"fake")
        compose.side_effect = _w

        run_pipeline(
            channel=cfg, settings=_settings(),
            db_path=tmp_path / "db.sqlite",
            music_root=tmp_path, templates_dir=tmp_path,
            cache_dir=tmp_path / "cache",
            lock_dir=tmp_path / "locks", logs_dir=logs, trigger="test",
        )

    # Verify DB state
    from short_bot.db import init_db
    from short_bot.generated_db import generated_items
    from sqlalchemy import select
    eng = init_db(tmp_path / "db.sqlite")
    with eng.connect() as conn:
        rows = conn.execute(select(generated_items)).fetchall()
    eng.dispose()
    assert len(rows) == 1
    assert rows[0].status == "used"
    assert rows[0].short_id is not None
```

- [ ] **Step 11.2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline_generator.py -v`
Expected: FAIL — `_run_generator` raises `NotImplementedError`

- [ ] **Step 11.3: Implement `_run_generator`**

Replace the stub `_run_generator` in `src/short_bot/pipeline.py` with:

```python
from short_bot.generator import (
    GeneratorRetryExhausted, check_duplicate, generate_quote,
)
from short_bot.generated_db import (
    insert_generated, recent_generated_texts, topic_distribution,
    update_generated_short_id,
)
from short_bot.image_picker import pick_image_for_generator


def _run_generator(*, channel, run_id, log, eng, settings,
                   music_root, templates_dir, cache_dir) -> RunResult:
    """6-phase generator pipeline."""
    log.info("[1/6] prepare (forbidden + topic distribution)")
    forbidden = recent_generated_texts(
        eng, channel.slug, limit=channel.generator.forbidden_lookback,
    )
    topic_dist = topic_distribution(eng, channel.slug, days=7)
    log.info(f"  → forbidden={len(forbidden)} topic_dist={topic_dist}")

    fuzzy_threshold = (channel.generator.fuzzy_threshold
                       or settings.fuzzy_dedup_threshold)

    last_text = ""
    chosen_result = None
    for attempt in range(1, channel.generator.max_retries + 1):
        log.info(f"[2/6] generate attempt {attempt}/{channel.generator.max_retries}")
        result = generate_quote(
            channel=channel, dna=channel.dna,
            forbidden_texts=forbidden, topic_distribution=topic_dist,
            claude_path=settings.claude_cli_path,
            model=channel.script_model
                  or settings.claude_models.get("default", "sonnet"),
        )

        log.info(f"[3/6] dedup-check (text={result.text[:60]!r})")
        verdict = check_duplicate(eng, channel.slug, result, forbidden,
                                  fuzzy_threshold)
        if verdict.is_duplicate:
            log.warning(f"  duplicate ({verdict.reason}) → discard")
            try:
                insert_generated(
                    eng, channel=channel.slug, text=result.text,
                    topic_tag=result.topic_tag, language=channel.language,
                    status="discarded", short_id=None,
                )
            except Exception as e:
                log.warning(f"  discarded insert failed (probably hash race): {e}")
            last_text = result.text
            continue

        chosen_result = result
        break

    if chosen_result is None:
        msg = (f"{channel.slug}: {channel.generator.max_retries} attempts all "
               f"duplicate. Last attempt: {last_text[:80]!r}")
        finish_run(eng, run_id, status="failed",
                   short_id=None, error=msg)
        raise GeneratorRetryExhausted(msg)

    # Record as 'used' WITHOUT short_id yet (filled after render)
    generated_id = insert_generated(
        eng, channel=channel.slug, text=chosen_result.text,
        topic_tag=chosen_result.topic_tag, language=channel.language,
        status="used", short_id=None,
    )

    # Phase 4: image
    log.info("[4/6] image search (Sonnet keywords)")
    images_cache = Path(cache_dir) / "images"
    bg = pick_image_for_generator(
        keywords=chosen_result.image_keywords,
        script=chosen_result.script,
        cache_dir=images_cache,
        claude_path=settings.claude_cli_path,
    )
    music = pick_music(music_root, mood=chosen_result.script.mood)
    log.info(f"  → bg={'cached' if bg else 'none'} music={music.name}")

    # Phase 5+6: render + compose (same RenderJob shape as RSS path)
    log.info("[5/6] render_frames")
    job = RenderJob(
        script=chosen_result.script, bg_image_path=bg, music_path=music,
        channel_colors=channel.colors, handle=channel.handle,
        duration_s=channel.duration_s, language=channel.language,
        cta_enabled=channel.cta_enabled, cta_text=channel.cta_text,
        cta_icons=channel.cta_icons, cta_duration_s=channel.cta_duration_s,
        cta_show_handle=channel.cta_show_handle,
    )

    with tempfile.TemporaryDirectory() as tmpd:
        frames_dir = Path(tmpd) / "frames"
        t0 = time.perf_counter()
        template_path = templates_dir / f"{channel.template}.html.j2"
        ui_labels = ui_labels_for(channel.language)
        dna_css_path = Path("templates") / "css" / f"{channel.slug}.css"
        dna_css = dna_css_path.read_text(encoding="utf-8") if dna_css_path.exists() else ""
        render_frames(job, template_path, frames_dir,
                      fps=30, browser=settings.playwright_browser,
                      ui_labels=ui_labels, dna_css=dna_css)

        log.info("[6/6] compose_video")
        out_dir = Path(channel.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(chosen_result.text)
        out_path = out_dir / f"{datetime.now(timezone.utc):%Y-%m-%d}_{slug}.mp4"
        sfx_overlays = _build_cta_sfx(channel)
        compose_video(frames_dir, music, out_path,
                      fps=30, ffmpeg_path=settings.ffmpeg_path,
                      sfx_overlays=sfx_overlays)
        render_ms = int((time.perf_counter() - t0) * 1000)
        log.info(f"  → {out_path.name} ({render_ms}ms)")

    short_id = record_short(
        eng, channel=channel.slug, rss_item_guid=None,
        title=chosen_result.script.header_top + " " + chosen_result.script.header_bottom,
        file_path=str(out_path), duration_s=channel.duration_s,
        script_json=chosen_result.script.model_dump_json(),
        render_ms=render_ms,
    )
    update_generated_short_id(eng, generated_id, short_id)
    finish_run(eng, run_id, status="success", short_id=short_id, error=None)
    log.info(f"=== success short_id={short_id} ===")
    return RunResult(run_id=run_id, status="success",
                     short_path=out_path, error=None)
```

- [ ] **Step 11.4: Run tests to verify they pass**

Run: `pytest tests/test_pipeline_generator.py -v`
Expected: 3 passed

- [ ] **Step 11.5: Run full suite**

Run: `pytest -q`
Expected: 223 passed (220 + 3)

- [ ] **Step 11.6: Commit**

```bash
git add src/short_bot/pipeline.py tests/test_pipeline_generator.py
git commit -m "feat(generator): _run_generator pipeline (6 phases)

Prepare → generate → dedup → image → render → compose. Records
'used' generated_items rows with short_id back-fill after render.
Discarded items keep status='discarded' for telemetry."
```

---

## Task 12: New Channel Wizard — `content_source` Radio

**Files:**
- Modify: `src/short_bot/web/templates/channels/new.html.j2`
- Modify: `src/short_bot/web/routes/channel_new.py`
- Test: `tests/test_web_channel_new_generator.py`

- [ ] **Step 12.1: Write failing test**

```python
# tests/test_web_channel_new_generator.py
from short_bot.web import create_app


def _client(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text("""\
ffmpeg_path: ffmpeg
claude_cli_path: claude
playwright_browser: chromium
web: {host: 127.0.0.1, port: 5005}
fuzzy_dedup_threshold: 0.85
log_level: INFO
claude_models: {dna: opus, default: haiku}
""", encoding="utf-8")
    app = create_app(config_dir=cfg_dir, db_path=tmp_path / "db.sqlite",
                     templates_dir=tmp_path / "templates",
                     music_root=tmp_path, cache_dir=tmp_path,
                     lock_dir=tmp_path, logs_dir=tmp_path,
                     output_root=tmp_path, scheduler=False)
    return app.test_client()


def test_new_channel_form_has_content_source_radio(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/channels/new")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'name="content_source"' in body
    assert 'value="rss"' in body
    assert 'value="generator"' in body


def test_new_channel_form_has_generator_topic_field(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/channels/new")
    body = r.data.decode("utf-8")
    assert 'name="generator_topic"' in body
```

- [ ] **Step 12.2: Run test to verify it fails**

Run: `pytest tests/test_web_channel_new_generator.py -v`
Expected: FAIL — fields not in HTML yet.

- [ ] **Step 12.3: Update `channels/new.html.j2`**

Replace the form `<form>` element with Alpine state. After the `<h1>` title, before the existing `<div class="grid grid-cols-2 gap-6">`, insert:

```html
<div x-data="{ source: 'rss' }" class="grid grid-cols-2 gap-6">
  <form id="wizard-form" hx-post="/channels/new/generate" hx-target="#preview" hx-indicator="#loading"
        class="space-y-4">

    <fieldset class="border border-claude-border rounded-lg p-3">
      <legend class="text-xs text-claude-muted uppercase px-2">Kanal Türü</legend>
      <label class="flex items-center gap-2 cursor-pointer">
        <input type="radio" name="content_source" value="rss" x-model="source" checked>
        <span>📰 Haber (RSS)</span>
      </label>
      <label class="flex items-center gap-2 cursor-pointer mt-1">
        <input type="radio" name="content_source" value="generator" x-model="source">
        <span>✨ Üretici (Sonnet ile sıfırdan)</span>
      </label>
    </fieldset>

    <h2 class="font-serif text-lg font-bold">Temel Bilgi</h2>

    <label class="block">
      <span class="text-xs text-claude-muted uppercase">Kanal İsim</span>
      <input type="text" name="name" required
             class="bg-claude-surface border border-claude-border px-3 py-2 rounded-lg w-full mt-1 text-sm text-claude-text">
    </label>

    <label class="block">
      <span class="text-xs text-claude-muted uppercase">Dil</span>
      <select name="language" class="bg-claude-surface border border-claude-border px-3 py-2 rounded-lg w-full mt-1 text-sm text-claude-text">
        <option value="tr">Türkçe</option>
        <option value="en">English</option>
        <option value="de">Deutsch</option>
        <option value="es">Español</option>
        <option value="fr">Français</option>
      </select>
    </label>

    <label class="block" x-show="source === 'rss'">
      <span class="text-xs text-claude-muted uppercase">Keywords (virgülle)</span>
      <input type="text" name="keywords"
             placeholder="Bundesliga, Bayern, Champions League"
             class="bg-claude-surface border border-claude-border px-3 py-2 rounded-lg w-full mt-1 text-sm text-claude-text placeholder:text-claude-muted">
    </label>

    <label class="block" x-show="source === 'generator'">
      <span class="text-xs text-claude-muted uppercase">Konu (en az 1 cümle)</span>
      <textarea name="generator_topic" rows="3"
                placeholder='Sevgi ve aşk üzerine kısa, vurucu sözler — günlük instagram alıntısı tarzında.'
                class="bg-claude-surface border border-claude-border px-3 py-2 rounded-lg w-full mt-1 text-sm text-claude-text placeholder:text-claude-muted"></textarea>
    </label>

    <label class="block">
      <span class="text-xs text-claude-muted uppercase">Konu ipucu (opsiyonel)</span>
      <input type="text" name="topic_hint"
             class="bg-claude-surface border border-claude-border px-3 py-2 rounded-lg w-full mt-1 text-sm text-claude-text">
    </label>

    <label class="block">
      <span class="text-xs text-claude-muted uppercase">Hedef kitle (opsiyonel)</span>
      <input type="text" name="target_audience"
             class="bg-claude-surface border border-claude-border px-3 py-2 rounded-lg w-full mt-1 text-sm text-claude-text">
    </label>

    <button type="submit" class="bg-claude-accent hover:bg-claude-accent-hover text-white px-4 py-2 rounded-lg font-semibold mt-4 w-full">
      DNA Üret (Opus, ~30-60s)
    </button>
    <div id="loading" class="htmx-indicator text-claude-accent text-sm">
      Opus düşünüyor...
    </div>
  </form>

  <div>
    <h2 class="font-serif text-lg font-bold mb-4">Canlı Önizleme</h2>
    <div id="preview" class="bg-claude-surface-alt border border-claude-border rounded-lg p-4 text-claude-muted text-center text-sm aspect-[9/16] flex items-center justify-center">
      Önce DNA üret →
    </div>
  </div>
</div>
```

(Replace the entire existing `<div class="grid grid-cols-2 gap-6">...</div>` block with the above. The wrapping `x-data` div takes its place.)

- [ ] **Step 12.4: Run tests to verify they pass**

Run: `pytest tests/test_web_channel_new_generator.py -v`
Expected: 2 passed

- [ ] **Step 12.5: Commit**

```bash
git add src/short_bot/web/templates/channels/new.html.j2 tests/test_web_channel_new_generator.py
git commit -m "feat(web): new-channel wizard adds content_source radio + topic textarea"
```

---

## Task 13: New Channel Save — Generator Branch

**Files:**
- Modify: `src/short_bot/web/routes/channel_new.py`
- Test: `tests/test_web_channel_new_generator.py` (extend)

- [ ] **Step 13.1: Add failing tests**

Append to `tests/test_web_channel_new_generator.py`:

```python
from unittest.mock import patch

from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec


def _fake_dna():
    return DnaSpec(
        archetype="kinetic",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
    )


def test_save_generator_channel_writes_yaml_with_generator_block(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    with patch("short_bot.web.routes.channel_new.generate_dna",
               return_value=_fake_dna()):
        r1 = c.post("/channels/new/generate", data={
            "name": "Sevgi Sözleri", "language": "tr",
            "content_source": "generator",
            "generator_topic": "Sevgi ve aşk üzerine kısa, vurucu sözler",
        })
        assert r1.status_code == 200

    r2 = c.post("/channels/new/save", data={
        "name": "Sevgi Sözleri", "language": "tr",
        "content_source": "generator",
        "generator_topic": "Sevgi ve aşk üzerine kısa, vurucu sözler",
    })
    assert r2.status_code in (200, 302)

    yaml_path = (tmp_path / "config" / "channels" / "sevgi-sozleri.yaml")
    assert yaml_path.exists()
    contents = yaml_path.read_text(encoding="utf-8")
    assert "content_source: generator" in contents
    assert "generator:" in contents
    assert "Sevgi ve aşk" in contents


def test_save_rss_channel_unchanged_no_generator_block(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    with patch("short_bot.web.routes.channel_new.generate_dna",
               return_value=_fake_dna()):
        c.post("/channels/new/generate", data={
            "name": "Haber", "language": "tr",
            "content_source": "rss",
            "keywords": "ekonomi, siyaset",
        })

    r2 = c.post("/channels/new/save", data={
        "name": "Haber", "language": "tr",
        "content_source": "rss",
        "keywords": "ekonomi, siyaset",
    })
    assert r2.status_code in (200, 302)
    yaml_path = tmp_path / "config" / "channels" / "haber.yaml"
    assert yaml_path.exists()
    contents = yaml_path.read_text(encoding="utf-8")
    assert "content_source" not in contents    # default not serialized
    assert "generator:" not in contents
```

- [ ] **Step 13.2: Run tests to verify they fail**

Run: `pytest tests/test_web_channel_new_generator.py -v`
Expected: 2 new tests fail.

- [ ] **Step 13.3: Update `channel_new.py` to handle generator**

Replace the existing `save()` function in `src/short_bot/web/routes/channel_new.py`:

```python
@bp.route("/channels/new/save", methods=["POST"])
def save():
    if "wizard_dna" not in session:
        abort(400)
    dna = DnaSpec.model_validate_json(session["wizard_dna"])
    name = session.get("wizard_name", request.form.get("name", "Channel"))
    language = session.get("wizard_language", request.form.get("language", "tr"))
    content_source = request.form.get("content_source", "rss")
    keywords = [k.strip() for k in request.form.get("keywords", "").split(",") if k.strip()]
    slug = _slug_from_name(name)

    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    templates_dir = current_app.config["SHORTBOT_TEMPLATES_DIR"]
    yaml_path = cfg_dir / "channels" / f"{slug}.yaml"
    css_path = templates_dir / "css" / f"{slug}.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(build_css_override(dna), encoding="utf-8")

    generator = None
    if content_source == "generator":
        from short_bot.config import GeneratorConfig
        topic = request.form.get("generator_topic", "").strip()
        if len(topic) < 10:
            flash("generator.topic en az 10 karakter olmalı.", "error")
            return redirect(url_for("channel_new.form"))
        generator = GeneratorConfig(topic=topic)

    cfg = ChannelConfig(
        slug=slug, name=name, keywords=keywords,
        rss_locale=RSS_LOCALES[language],
        schedule_cron="0 8,14,20 * * *",
        duration_s=6, min_score=6.0, max_candidates_per_run=10,
        template=dna.archetype,
        colors={"primary": dna.palette.primary,
                "accent": dna.palette.accent,
                "bg_gradient": dna.palette.bg_gradient},
        handle=f"@{slug}", output_dir=f"output/{slug}",
        enabled=True,
        cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language=language, dna=dna, script_model=None,
        content_source=content_source,
        generator=generator,
    )
    save_channel(yaml_path, cfg)
    session.pop("wizard_dna", None)
    session.pop("wizard_name", None)
    session.pop("wizard_language", None)
    return redirect(url_for("channel_edit.edit", slug=slug))
```

Also add `from flask import flash` to the imports at the top of `channel_new.py`.

- [ ] **Step 13.4: Run tests to verify they pass**

Run: `pytest tests/test_web_channel_new_generator.py -v`
Expected: 4 passed (2 existing + 2 new)

- [ ] **Step 13.5: Commit**

```bash
git add src/short_bot/web/routes/channel_new.py tests/test_web_channel_new_generator.py
git commit -m "feat(web): new-channel save handles generator config

Default content_source='rss' produces backward-compatible YAML.
Generator branch validates topic length and writes generator block."
```

---

## Task 14: Edit Page — Generator Block + Save

**Files:**
- Modify: `src/short_bot/web/templates/channels/edit.html.j2`
- Modify: `src/short_bot/web/routes/channel_edit.py`
- Test: `tests/test_web_channel_edit_generator.py`

- [ ] **Step 14.1: Write failing test**

```python
# tests/test_web_channel_edit_generator.py
import pytest
import yaml

from short_bot.config import ChannelConfig, GeneratorConfig, save_channel
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text("""\
ffmpeg_path: ffmpeg
claude_cli_path: claude
playwright_browser: chromium
web: {host: 127.0.0.1, port: 5005}
fuzzy_dedup_threshold: 0.85
log_level: INFO
claude_models: {dna: opus, default: haiku}
""", encoding="utf-8")

    dna = DnaSpec(
        archetype="kinetic",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
    )
    cfg = ChannelConfig(
        slug="sevgi", name="Sevgi", keywords=[], rss_locale="hl=tr",
        schedule_cron="0 9 * * *", duration_s=7, min_score=0.0,
        max_candidates_per_run=1, template="kinetic",
        colors={"primary": "#000", "accent": "#fff",
                "bg_gradient": ["#000", "#111"]},
        handle="@sevgi", output_dir="output/sevgi",
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language="tr", dna=dna, script_model="sonnet",
        content_source="generator",
        generator=GeneratorConfig(topic="Sevgi sözleri üretiyoruz."),
    )
    save_channel(cfg_dir / "channels" / "sevgi.yaml", cfg)

    return create_app(config_dir=cfg_dir, db_path=tmp_path / "db.sqlite",
                      templates_dir=tmp_path / "templates",
                      music_root=tmp_path, cache_dir=tmp_path,
                      lock_dir=tmp_path, logs_dir=tmp_path,
                      output_root=tmp_path, scheduler=False)


def test_edit_page_shows_generator_topic_field(app):
    r = app.test_client().get("/channels/sevgi/edit")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'name="generator_topic"' in body
    assert "Sevgi sözleri üretiyoruz." in body


def test_edit_page_shows_test_uret_button_for_generator(app):
    r = app.test_client().get("/channels/sevgi/edit")
    body = r.data.decode("utf-8")
    assert "Test örnek" in body or "generator-test" in body


def test_edit_save_updates_generator_topic(app, tmp_path):
    c = app.test_client()
    r = c.post("/channels/sevgi/edit", data={
        "keywords": "",
        "schedule_cron": "0 9 * * *",
        "duration_s": "7", "min_score": "0",
        "max_candidates_per_run": "1",
        "handle": "@sevgi",
        "enabled": "1",
        "generator_topic": "GÜNCELLENDİ topic minimum on karakter.",
        "generator_forbidden_lookback": "75",
        "generator_max_retries": "5",
        # Other DNA/CTA fields submitted with defaults...
    })
    assert r.status_code in (200, 302)

    yaml_path = tmp_path / "config" / "channels" / "sevgi.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert data["generator"]["topic"].startswith("GÜNCELLENDİ")
    assert data["generator"]["forbidden_lookback"] == 75
    assert data["generator"]["max_retries"] == 5
```

- [ ] **Step 14.2: Run test to verify it fails**

Run: `pytest tests/test_web_channel_edit_generator.py -v`
Expected: 3 fails.

- [ ] **Step 14.3: Update `edit.html.j2` — add generator block**

Find the section starting with `{% if c.dna %}` (DNA editor). Just **after** the closing `</details>` of `Persona özeti`, **before** the closing `{% endif %}` of `c.dna`, insert:

```html
    {% if c.content_source == 'generator' %}
    <h2 class="font-serif text-lg font-bold mt-6 border-t border-claude-border pt-4">Generator Ayarları</h2>

    <label class="block">
      <span class="text-xs text-claude-muted uppercase">Konu (en az 10 karakter)</span>
      <textarea name="generator_topic" rows="3"
                class="bg-claude-surface border border-claude-border px-3 py-2 rounded-lg w-full mt-1 text-sm text-claude-text">{{ c.generator.topic }}</textarea>
    </label>

    <div class="grid grid-cols-3 gap-3">
      <label class="block">
        <span class="text-xs text-claude-muted uppercase">Forbidden lookback</span>
        <input type="number" name="generator_forbidden_lookback"
               value="{{ c.generator.forbidden_lookback }}" min="0" max="500"
               class="bg-claude-surface border border-claude-border px-3 py-2 rounded-lg w-full mt-1 text-sm text-claude-text">
      </label>
      <label class="block">
        <span class="text-xs text-claude-muted uppercase">Max retries</span>
        <input type="number" name="generator_max_retries"
               value="{{ c.generator.max_retries }}" min="1" max="10"
               class="bg-claude-surface border border-claude-border px-3 py-2 rounded-lg w-full mt-1 text-sm text-claude-text">
      </label>
      <label class="block">
        <span class="text-xs text-claude-muted uppercase">Fuzzy threshold</span>
        <input type="number" name="generator_fuzzy_threshold" step="0.05" min="0" max="1"
               value="{{ c.generator.fuzzy_threshold if c.generator.fuzzy_threshold is not none else '' }}"
               placeholder="boş = settings"
               class="bg-claude-surface border border-claude-border px-3 py-2 rounded-lg w-full mt-1 text-sm text-claude-text">
      </label>
    </div>
    {% endif %}
```

In the same file, in the action button row near top (where "▶ Şimdi üret", "↻ DNA Yenile", "Sil" live), add a new button **just after "Şimdi üret"**:

```html
    {% if c.content_source == 'generator' %}
    <form method="POST" action="/channels/{{ c.slug }}/generator-test" class="inline">
      <button type="submit"
              class="bg-claude-surface hover:bg-claude-surface-alt border border-claude-border px-3 py-2 rounded-lg text-sm">
        🧪 Test örnek üret
      </button>
    </form>
    {% endif %}
```

Also hide RSS-only fields when generator. Wrap the existing `keywords`, `min_score`, `max_candidates_per_run` `<label>` blocks in the form with `{% if c.content_source != 'generator' %}…{% endif %}`.

- [ ] **Step 14.4: Update `channel_edit.py:save()`**

In `src/short_bot/web/routes/channel_edit.py`, modify `save()` to include the generator fields. Find the `new_cfg = ChannelConfig(...)` block and replace it with:

```python
    new_generator = cfg.generator
    if cfg.content_source == "generator":
        from short_bot.config import GeneratorConfig
        topic = (request.form.get("generator_topic", "").strip()
                 or (cfg.generator.topic if cfg.generator else ""))
        if len(topic) < 10:
            flash("generator.topic en az 10 karakter olmalı.", "error")
            return redirect(url_for("channel_edit.edit", slug=slug))
        try:
            forbidden_lookback = int(request.form.get("generator_forbidden_lookback",
                                                       cfg.generator.forbidden_lookback))
        except (TypeError, ValueError):
            forbidden_lookback = cfg.generator.forbidden_lookback
        try:
            max_retries = int(request.form.get("generator_max_retries",
                                                cfg.generator.max_retries))
        except (TypeError, ValueError):
            max_retries = cfg.generator.max_retries
        ft_raw = request.form.get("generator_fuzzy_threshold", "").strip()
        fuzzy_threshold = float(ft_raw) if ft_raw else None
        new_generator = GeneratorConfig(
            topic=topic, forbidden_lookback=forbidden_lookback,
            max_retries=max_retries, fuzzy_threshold=fuzzy_threshold,
        )

    new_cfg = ChannelConfig(
        slug=cfg.slug, name=cfg.name, keywords=keywords,
        rss_locale=cfg.rss_locale,
        schedule_cron=request.form.get("schedule_cron", cfg.schedule_cron),
        duration_s=_form_get_int("duration_s", cfg.duration_s),
        min_score=_form_get_float("min_score", cfg.min_score),
        max_candidates_per_run=_form_get_int("max_candidates_per_run",
                                              cfg.max_candidates_per_run),
        template=new_template,
        colors={
            "primary": new_dna.palette.primary if new_dna else cfg.colors["primary"],
            "accent": new_dna.palette.accent if new_dna else cfg.colors["accent"],
            "bg_gradient": (list(new_dna.palette.bg_gradient) if new_dna
                            else cfg.colors["bg_gradient"]),
        },
        handle=request.form.get("handle", cfg.handle),
        output_dir=cfg.output_dir,
        enabled=request.form.get("enabled") == "1",
        cta_enabled=request.form.get("cta_enabled") == "1",
        cta_text=request.form.get("cta_text", cfg.cta_text),
        cta_icons=_form_get_list("cta_icons") or cfg.cta_icons,
        cta_duration_s=_form_get_int("cta_duration_s", cfg.cta_duration_s),
        cta_show_handle=request.form.get("cta_show_handle") == "1",
        language=cfg.language, dna=new_dna, script_model=cfg.script_model,
        content_source=cfg.content_source,
        generator=new_generator,
    )
```

- [ ] **Step 14.5: Run tests to verify they pass**

Run: `pytest tests/test_web_channel_edit_generator.py -v`
Expected: 3 passed

- [ ] **Step 14.6: Commit**

```bash
git add src/short_bot/web/templates/channels/edit.html.j2 src/short_bot/web/routes/channel_edit.py tests/test_web_channel_edit_generator.py
git commit -m "feat(web): edit page renders+saves generator fields

Generator block (topic + lookback + retries + threshold) appears only
for generator channels. RSS-only fields hidden in generator mode.
Test Üret button stub added — endpoint follows in Task 15."
```

---

## Task 15: Test Üret Endpoint

**Files:**
- Create: `src/short_bot/web/routes/generator_test.py`
- Create: `src/short_bot/web/templates/_partials/generator_test_result.html.j2`
- Modify: `src/short_bot/web/routes/__init__.py`
- Test: `tests/test_web_generator_test.py`

- [ ] **Step 15.1: Write failing test**

```python
# tests/test_web_generator_test.py
from unittest.mock import patch

import pytest

from short_bot.config import ChannelConfig, GeneratorConfig, save_channel
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
from short_bot.generator import GeneratorResult
from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text("""\
ffmpeg_path: ffmpeg
claude_cli_path: claude
playwright_browser: chromium
web: {host: 127.0.0.1, port: 5005}
fuzzy_dedup_threshold: 0.85
log_level: INFO
claude_models: {dna: opus, default: haiku}
""", encoding="utf-8")

    dna = DnaSpec(
        archetype="kinetic",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
    )
    cfg = ChannelConfig(
        slug="sevgi", name="Sevgi", keywords=[], rss_locale="hl=tr",
        schedule_cron="0 9 * * *", duration_s=7, min_score=0.0,
        max_candidates_per_run=1, template="kinetic",
        colors={"primary": "#000", "accent": "#fff",
                "bg_gradient": ["#000", "#111"]},
        handle="@sevgi", output_dir="output/sevgi",
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language="tr", dna=dna, script_model="sonnet",
        content_source="generator",
        generator=GeneratorConfig(topic="Sevgi sözleri üretiyoruz."),
    )
    save_channel(cfg_dir / "channels" / "sevgi.yaml", cfg)

    return create_app(config_dir=cfg_dir, db_path=tmp_path / "db.sqlite",
                      templates_dir=tmp_path / "templates",
                      music_root=tmp_path, cache_dir=tmp_path,
                      lock_dir=tmp_path, logs_dir=tmp_path,
                      output_root=tmp_path, scheduler=False)


def _fake_result():
    return GeneratorResult(
        text="Aşk anlayışta başlar.",
        topic_tag="tanisma",
        script={
            "header_top": "AŞK", "header_bottom": "ÜZERİNE",
            "photo_overlay": "Sevgi",
            "body_paragraph": "Aşk anlayışta başlar. Bir bakış güzelliktir, anlayış sevdadır.",
            "highlights": [{"text": "anlayışta", "color": "yellow"}],
            "category": "ask", "mood": "neutral",
        },
        image_keywords=["couple silhouette", "sunset"],
    )


def test_generator_test_endpoint_returns_result(app):
    c = app.test_client()
    with patch("short_bot.web.routes.generator_test.generate_quote",
               return_value=_fake_result()):
        r = c.post("/channels/sevgi/generator-test")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Aşk anlayışta" in body
    assert "tanisma" in body


def test_generator_test_does_not_persist(app, tmp_path):
    c = app.test_client()
    with patch("short_bot.web.routes.generator_test.generate_quote",
               return_value=_fake_result()):
        c.post("/channels/sevgi/generator-test")
    # Verify nothing in generated_items
    from short_bot.db import init_db
    from short_bot.generated_db import generated_items
    from sqlalchemy import select
    eng = init_db(tmp_path / "db.sqlite")
    with eng.connect() as conn:
        rows = conn.execute(select(generated_items)).fetchall()
    eng.dispose()
    assert rows == []


def test_generator_test_404_on_rss_channel(app, tmp_path):
    """Test endpoint refuses non-generator channels."""
    cfg_dir = tmp_path / "config"
    rss_yaml = cfg_dir / "channels" / "haber.yaml"
    rss_yaml.write_text("""\
slug: haber
name: Haber
language: tr
keywords: [x]
schedule_cron: "0 9 * * *"
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors: {primary: "#000", accent: "#111", bg_gradient: ["#000", "#111"]}
handle: "@h"
output_dir: output/h
enabled: true
cta: {enabled: false, text: "", icons: [], duration_s: 0, show_handle: false}
""", encoding="utf-8")
    r = app.test_client().post("/channels/haber/generator-test")
    assert r.status_code == 400
```

- [ ] **Step 15.2: Run test to verify it fails**

Run: `pytest tests/test_web_generator_test.py -v`
Expected: FAIL with 404 (endpoint doesn't exist).

- [ ] **Step 15.3: Implement endpoint**

```python
# src/short_bot/web/routes/generator_test.py
"""POST /channels/<slug>/generator-test — preview generator output without persisting."""
from flask import Blueprint, abort, current_app, render_template

from short_bot.config import load_channel
from short_bot.db import init_db
from short_bot.generated_db import recent_generated_texts, topic_distribution
from short_bot.generator import generate_quote

bp = Blueprint("generator_test", __name__)


@bp.route("/channels/<slug>/generator-test", methods=["POST"])
def test(slug):
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not cfg_path.exists():
        abort(404)
    cfg = load_channel(cfg_path)
    if cfg.content_source != "generator" or cfg.generator is None:
        abort(400, description="Test üret sadece generator kanallarında çalışır.")

    settings = current_app.config["SHORTBOT_SETTINGS"]
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    forbidden = recent_generated_texts(eng, slug,
                                        limit=cfg.generator.forbidden_lookback)
    topic_dist = topic_distribution(eng, slug, days=7)
    eng.dispose()

    try:
        result = generate_quote(
            channel=cfg, dna=cfg.dna,
            forbidden_texts=forbidden, topic_distribution=topic_dist,
            claude_path=settings.claude_cli_path,
            model=cfg.script_model
                  or settings.claude_models.get("default", "sonnet"),
        )
    except Exception as e:
        return render_template(
            "_partials/generator_test_result.html.j2",
            error=str(e), result=None,
        )
    return render_template(
        "_partials/generator_test_result.html.j2",
        error=None, result=result,
    )
```

- [ ] **Step 15.4: Create result partial**

```html
<!-- src/short_bot/web/templates/_partials/generator_test_result.html.j2 -->
{% if error %}
  <div class="bg-claude-error/10 border border-claude-error/40 rounded-lg p-4 text-claude-error text-sm">
    Hata: {{ error }}
  </div>
{% elif result %}
  <div class="bg-claude-surface border border-claude-border rounded-lg p-4 space-y-3 text-sm">
    <div>
      <span class="text-xs text-claude-muted uppercase">Topic tag:</span>
      <strong class="text-claude-accent">{{ result.topic_tag }}</strong>
    </div>
    <div>
      <span class="text-xs text-claude-muted uppercase">Text:</span>
      <p class="font-serif text-base leading-snug mt-1">{{ result.text }}</p>
    </div>
    <details>
      <summary class="text-xs text-claude-muted uppercase cursor-pointer">Script JSON</summary>
      <pre class="text-xs whitespace-pre-wrap mt-2 bg-claude-surface-alt p-2 rounded">{{ result.script.model_dump_json(indent=2) }}</pre>
    </details>
    <div>
      <span class="text-xs text-claude-muted uppercase">Image keywords:</span>
      <span class="font-mono text-xs">{{ result.image_keywords | join(' · ') }}</span>
    </div>
    <p class="text-xs text-claude-muted italic">⚠️ DB'ye kaydedilmedi — gerçek üretim için "Şimdi üret" kullan.</p>
  </div>
{% endif %}
```

- [ ] **Step 15.5: Register blueprint**

In `src/short_bot/web/routes/__init__.py`, add to imports + register:

```python
from short_bot.web.routes import (
    dashboard, shorts, rss, channels,
    channel_new, channel_edit, preview, logs, settings,
    generator_test,
)
# ... existing register_blueprint calls ...
app.register_blueprint(generator_test.bp)
```

- [ ] **Step 15.6: Update edit.html.j2 to render result inline (HTMX)**

In `edit.html.j2`, find the `<form method="POST" action="/channels/{{ c.slug }}/generator-test">` block from Task 14 and update to use HTMX so the result appears below without page reload:

```html
{% if c.content_source == 'generator' %}
<button hx-post="/channels/{{ c.slug }}/generator-test"
        hx-target="#generator-test-result"
        hx-swap="innerHTML"
        class="bg-claude-surface hover:bg-claude-surface-alt border border-claude-border px-3 py-2 rounded-lg text-sm">
  🧪 Test örnek üret
</button>
{% endif %}
```

In the right column (preview), add an inline result panel **after** the iframe and "Son Run'lar" table:

```html
{% if c.content_source == 'generator' %}
<h2 class="font-serif text-lg font-bold mt-6 mb-3">Test Sonucu</h2>
<div id="generator-test-result" class="text-sm text-claude-muted">
  "🧪 Test örnek üret" butonuna basıldığında burada görünür.
</div>
{% endif %}
```

- [ ] **Step 15.7: Run tests to verify they pass**

Run: `pytest tests/test_web_generator_test.py -v`
Expected: 3 passed

- [ ] **Step 15.8: Run full suite**

Run: `pytest -q`
Expected: 230+ passed

- [ ] **Step 15.9: Commit**

```bash
git add src/short_bot/web/routes/generator_test.py src/short_bot/web/templates/_partials/generator_test_result.html.j2 src/short_bot/web/routes/__init__.py src/short_bot/web/templates/channels/edit.html.j2 tests/test_web_generator_test.py
git commit -m "feat(web): generator-test endpoint + inline result panel

POST /channels/<slug>/generator-test runs Sonnet, returns preview without
DB write or render. Results appear via HTMX swap below the iframe."
```

---

## Task 16: Channel List Badge

**Files:**
- Modify: `src/short_bot/web/templates/_partials/channel_row.html.j2`
- Test: `tests/test_web_channels_list_badge.py`

- [ ] **Step 16.1: Write failing test**

```python
# tests/test_web_channels_list_badge.py
import pytest

from short_bot.config import ChannelConfig, GeneratorConfig, save_channel
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
from short_bot.web import create_app


def _seed_two_channels(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text("""\
ffmpeg_path: ffmpeg
claude_cli_path: claude
playwright_browser: chromium
web: {host: 127.0.0.1, port: 5005}
fuzzy_dedup_threshold: 0.85
log_level: INFO
claude_models: {dna: opus, default: haiku}
""", encoding="utf-8")

    dna = DnaSpec(
        archetype="kinetic",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
    )
    rss_cfg = ChannelConfig(
        slug="haber", name="Haber", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="*", duration_s=6, min_score=6.0,
        max_candidates_per_run=5, template="newscast",
        colors={"primary": "#000", "accent": "#111", "bg_gradient": ["#000", "#111"]},
        handle="@h", output_dir="output/h",
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language="tr", dna=None, script_model=None,
        content_source="rss", generator=None,
    )
    gen_cfg = ChannelConfig(
        slug="sevgi", name="Sevgi", keywords=[], rss_locale="hl=tr",
        schedule_cron="*", duration_s=7, min_score=0.0,
        max_candidates_per_run=1, template="kinetic",
        colors={"primary": "#000", "accent": "#fff", "bg_gradient": ["#000", "#111"]},
        handle="@s", output_dir="output/s",
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language="tr", dna=dna, script_model="sonnet",
        content_source="generator",
        generator=GeneratorConfig(topic="Sevgi sözleri üretiyoruz."),
    )
    save_channel(cfg_dir / "channels" / "haber.yaml", rss_cfg)
    save_channel(cfg_dir / "channels" / "sevgi.yaml", gen_cfg)

    return create_app(config_dir=cfg_dir, db_path=tmp_path / "db.sqlite",
                      templates_dir=tmp_path / "templates",
                      music_root=tmp_path, cache_dir=tmp_path,
                      lock_dir=tmp_path, logs_dir=tmp_path,
                      output_root=tmp_path, scheduler=False)


def test_channels_list_shows_badges_for_each_type(tmp_path):
    app = _seed_two_channels(tmp_path)
    r = app.test_client().get("/channels")
    body = r.data.decode("utf-8")
    # Both badges present somewhere in the list
    assert "📰" in body
    assert "✨" in body
```

- [ ] **Step 16.2: Run test to verify it fails**

Run: `pytest tests/test_web_channels_list_badge.py -v`
Expected: FAIL — neither emoji present.

- [ ] **Step 16.3: Update `channel_row.html.j2`**

Modify the `<td class="p-3 font-mono text-xs">{{ c.slug }}</td>` line in `src/short_bot/web/templates/_partials/channel_row.html.j2` to:

```html
  <td class="p-3 font-mono text-xs">
    {{ c.slug }}
    {% if c.content_source == 'generator' %}
      <span title="Generator (Sonnet)" class="text-claude-accent ml-1">✨</span>
    {% else %}
      <span title="RSS" class="text-claude-muted ml-1">📰</span>
    {% endif %}
  </td>
```

- [ ] **Step 16.4: Run test to verify it passes**

Run: `pytest tests/test_web_channels_list_badge.py -v`
Expected: 1 passed

- [ ] **Step 16.5: Commit**

```bash
git add src/short_bot/web/templates/_partials/channel_row.html.j2 tests/test_web_channels_list_badge.py
git commit -m "feat(web): channel list badges (✨ generator / 📰 RSS)"
```

---

## Task 17: Manual Smoke + Tag

**Files:**
- None (operational task)

- [ ] **Step 17.1: Run full test suite one more time**

Run: `pytest -q`
Expected: All 230+ tests pass.

- [ ] **Step 17.2: Manual smoke (optional but recommended)**

Start the panel and do an end-to-end manual creation:

```bash
python -m short_bot web
```

In browser at `http://127.0.0.1:5005`:
1. Create a new channel — choose "✨ Üretici (Sonnet)" radio
2. Name: "Sevgi Sözleri", Topic: "Sevgi ve aşk üzerine kısa sözler — vurucu instagram tarzı"
3. Click "DNA Üret" — wait for Opus
4. Click "Kaydet"
5. On edit page, click "🧪 Test örnek üret" — confirm Sonnet response renders
6. Click "▶ Şimdi üret" — wait for full pipeline; check `/shorts` for the new short
7. Click "Şimdi üret" again — verify second run produces *different* content (forbidden list working)

If smoke fails, fix the issue (or revert Tasks 11+) before tagging.

- [ ] **Step 17.3: Tag and push**

```bash
git tag -a v0.4.0-generator -m "Generator mode: Sonnet-driven content with 3-layer dedup"
git log --oneline v0.3.0-web-panel..HEAD | head -30
```

(Push only if user requests; don't auto-push.)

- [ ] **Step 17.4: Final commit (if any UI tweaks needed from smoke)**

```bash
git status
# If anything is staged, write a "smoke test fixes" commit; otherwise skip.
```

---

## Spec Coverage Self-Review

Spec Section → Plan Task mapping:

| Spec | Task |
|---|---|
| §1 Configuration (GeneratorConfig + content_source + YAML) | Task 3 |
| §1.4 Sub-theme strategy (Sonnet auto) | Task 6 (prompt requests topic_tag in prompt) |
| §2 DB schema (generated_items + indexes + hash + queries) | Tasks 1 & 2 |
| §2.4 Migration (init_db idempotent) | Task 2 step 2.4 |
| §3.1 Dispatcher | Task 10 |
| §3.2 Generator 6-phase flow | Task 11 |
| §3.3 RSS path unchanged | Task 10 (extract verbatim) |
| §3.4 Image picker integration | Task 9 |
| §4.1 GeneratorResult model | Task 5 |
| §4.2 build_generator_prompt | Task 6 |
| §4.3 5-language phrases | Task 4 |
| §4.4 generate_quote | Task 7 |
| §5 3-layer dedup + retry exhaustion | Tasks 8 & 11 |
| §5.3 Atomicity (used vs discarded) | Task 11 |
| §6.1 New wizard radio | Tasks 12 & 13 |
| §6.2 Edit page conditional fields | Task 14 |
| §6.3 List badge | Task 16 |
| §6.4 Test Üret button | Task 15 |
| §7 Test strategy | Tests embedded in Tasks 1-16 |
| §8 Backward compatibility | Verified via existing tests + Task 13 (RSS yaml unchanged) |
| §10 Acceptance criteria | Task 17 (manual smoke) |

All spec sections covered. No placeholders. Type names consistent across tasks (`GeneratorConfig`, `GeneratorResult`, `DupVerdict`, `_run_generator`, `pick_image_for_generator`).

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-06-generator-mode.md`.** Two execution options:

**1. Subagent-Driven (recommended)** — Fresh subagent per task, two-stage review (spec + code-quality) between tasks. Slower but stricter quality gate.

**2. Inline Execution** — I run tasks here in order, check off steps, batch commits at logical breakpoints. Faster but you watch a single conversation.

Hangisi?
