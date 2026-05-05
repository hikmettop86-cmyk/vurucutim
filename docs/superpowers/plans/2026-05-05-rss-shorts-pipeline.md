# RSS → Shorts Pipeline (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python CLI that fetches Turkish news from Google News RSS, scores items with Claude CLI, extracts article bodies, generates 30-second 9:16 kinetic-text Shorts videos with a 3-layer infographic layout, and writes mp4s to disk.

**Architecture:** 8-stage pipeline (fetch → dedup → score → extract → script → assets → render → compose). Each stage is an isolated module with a dataclass interface. Render uses Playwright to capture frames from a Jinja2 HTML template, FFmpeg composes frames + music. Persistence: SQLite for dedup/audit. LLM calls: `claude` CLI subprocess.

**Tech Stack:** Python 3.11+, feedparser, trafilatura, Pydantic, Jinja2, Playwright (chromium), Pillow, ffmpeg-python, SQLAlchemy, PyYAML, pytest.

**Spec reference:** `docs/superpowers/specs/2026-05-05-rss-news-shorts-design.md`

**Phase 1 deliverable:** `python -m short_bot run --channel son-dakika --max 1` end-to-end produces a 30s mp4 in `output/son-dakika/`. Web panel is Phase 2 (separate plan).

---

## File Structure

```
D:\short\
├── .gitignore
├── README.md
├── pyproject.toml
├── config\
│   ├── settings.yaml
│   └── channels\son-dakika.yaml
├── src\short_bot\
│   ├── __init__.py             # version
│   ├── __main__.py             # `python -m short_bot` → cli.main()
│   ├── cli.py                  # argparse: run, init, list-channels
│   ├── config.py               # YAML loader + ChannelConfig + Settings dataclasses
│   ├── models.py               # NewsItem, ScoredItem, Script, Highlight, RenderJob
│   ├── db.py                   # SQLAlchemy engine + ORM models + helpers
│   ├── claude_cli.py           # subprocess wrapper: run_json(prompt, schema) + retry
│   ├── fetcher.py              # RSS Fetcher
│   ├── dedup.py                # GUID + fuzzy filter
│   ├── scorer.py               # LLM score + top-N
│   ├── extractor.py            # trafilatura + fallback
│   ├── script_writer.py        # LLM JSON → Script
│   ├── assets.py               # thumb download + blur, music picker
│   ├── renderer.py             # Jinja2 + Playwright frame capture
│   ├── composer.py             # ffmpeg compose
│   └── pipeline.py             # Orchestrator: run(channel, max=1, trigger='cli')
├── templates\default.html.j2   # 3-layer Short template
├── assets\
│   ├── music\{breaking,neutral,upbeat}\.gitkeep
│   └── fonts\.gitkeep
├── output\.gitkeep
├── data\{cache,locks}\.gitkeep
├── logs\runs\.gitkeep
└── tests\
    ├── conftest.py             # fixtures (tmp dirs, fake settings)
    ├── fixtures\
    │   ├── rss_son_dakika.xml
    │   ├── rss_with_thumbs.xml
    │   ├── article_basic.html
    │   ├── article_empty.html
    │   ├── thumb_sample.jpg
    │   ├── music_sample.mp3
    │   └── snapshot_default.png
    ├── test_models.py
    ├── test_config.py
    ├── test_db.py
    ├── test_claude_cli.py
    ├── test_fetcher.py
    ├── test_dedup.py
    ├── test_scorer.py
    ├── test_extractor.py
    ├── test_script_writer.py
    ├── test_assets.py
    ├── test_renderer.py
    ├── test_composer.py
    └── test_pipeline.py
```

**Total: 16 tasks.** Each task creates 1-2 files, follows TDD, ends with a commit.

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md`
- Create: directories per File Structure above (with `.gitkeep` files)

- [ ] **Step 1: Initialize git**

```bash
cd /d/short
git init
git config user.name "shortbot-dev"
git config user.email "shortbot@local"
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "short-bot"
version = "0.1.0"
description = "RSS → YouTube Shorts video generator"
requires-python = ">=3.11"
dependencies = [
    "feedparser>=6.0",
    "trafilatura>=1.6",
    "requests>=2.31",
    "pydantic>=2.5",
    "jinja2>=3.1",
    "playwright>=1.40",
    "pillow>=10.1",
    "ffmpeg-python>=0.2",
    "sqlalchemy>=2.0",
    "pyyaml>=6.0",
    "python-dateutil>=2.8",
    "filelock>=3.13",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-cov>=4.1",
    "pytest-mock>=3.12",
]

[project.scripts]
short-bot = "short_bot.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"
```

- [ ] **Step 3: Create `.gitignore`**

```
__pycache__/
*.pyc
*.egg-info/
.pytest_cache/
.coverage
htmlcov/
build/
dist/

# project artifacts
output/*
!output/.gitkeep
data/*.sqlite
data/cache/*
!data/cache/.gitkeep
data/locks/*
!data/locks/.gitkeep
logs/*
!logs/.gitkeep
!logs/runs/
logs/runs/*
!logs/runs/.gitkeep

# brainstorm/spec working files
.superpowers/
```

- [ ] **Step 4: Create directory tree with .gitkeep files**

```bash
mkdir -p src/short_bot config/channels templates assets/music/{breaking,neutral,upbeat} assets/fonts output data/cache data/locks logs/runs tests/fixtures
touch src/short_bot/__init__.py
touch assets/music/breaking/.gitkeep assets/music/neutral/.gitkeep assets/music/upbeat/.gitkeep assets/fonts/.gitkeep
touch output/.gitkeep data/cache/.gitkeep data/locks/.gitkeep logs/runs/.gitkeep
touch tests/__init__.py
```

- [ ] **Step 5: Create `README.md`**

```markdown
# short-bot

RSS → YouTube Shorts (9:16, 30s, kinetic text + müzik).

## Kurulum

```bash
pip install -e ".[dev]"
playwright install chromium
```

## İlk Çalıştırma

```bash
python -m short_bot init                            # SQLite şemasını oluştur
python -m short_bot run --channel son-dakika --max 1
```

Çıktı: `output/son-dakika/<tarih>_<slug>.mp4`

Detay: `docs/superpowers/specs/2026-05-05-rss-news-shorts-design.md`
```

- [ ] **Step 6: Create `src/short_bot/__init__.py`**

```python
"""short-bot: RSS → YouTube Shorts generator."""
__version__ = "0.1.0"
```

- [ ] **Step 7: Install dev deps and verify**

```bash
pip install -e ".[dev]"
```
Expected: installs without error.

```bash
python -c "import short_bot; print(short_bot.__version__)"
```
Expected: `0.1.0`

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore README.md src/ config/ templates/ assets/ output/ data/ logs/ tests/
git commit -m "chore: project scaffold"
```

---

## Task 2: Domain Models

**Files:**
- Create: `src/short_bot/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing test**

`tests/test_models.py`:
```python
from datetime import datetime
import pytest
from pydantic import ValidationError

from short_bot.models import NewsItem, ScoredItem, Highlight, Script


def test_news_item_minimal():
    item = NewsItem(guid="g1", title="T", link="http://x", source=None, pub_date=None, thumb_url=None, description=None)
    assert item.guid == "g1"


def test_scored_item_score_range():
    item = NewsItem(guid="g", title="t", link="l", source=None, pub_date=None, thumb_url=None, description=None)
    s = ScoredItem(item=item, score=8.5, reasoning="r")
    assert s.score == 8.5


def test_highlight_color_validates():
    Highlight(text="x", color="red")
    Highlight(text="x", color="yellow")
    with pytest.raises(ValidationError):
        Highlight(text="x", color="blue")


def test_script_validation_succeeds():
    s = Script(
        header_top="FAİZ ŞOKU",
        header_bottom="BAŞLADI",
        photo_overlay="250 BAZ PUAN",
        body_paragraph="Türkiye Cumhuriyet Merkez Bankası faizi 250 baz puan indirdi. Karar piyasada şok etkisi yarattı.",
        highlights=[Highlight(text="250 baz puan", color="yellow")],
        category="EKONOMİ",
        mood="breaking",
    )
    assert s.mood == "breaking"


def test_script_highlight_must_be_substring_of_body():
    with pytest.raises(ValidationError, match="paragrafta"):
        Script(
            header_top="A", header_bottom="B", photo_overlay="C",
            body_paragraph="Kısa bir metin.",
            highlights=[Highlight(text="bulunmayan ifade", color="red")],
            category="X", mood="neutral",
        )


def test_script_mood_validates():
    with pytest.raises(ValidationError):
        Script(
            header_top="A", header_bottom="B", photo_overlay="C",
            body_paragraph="Yeterince uzun bir paragraf metni.",
            highlights=[],
            category="X", mood="dance-party",
        )
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
pytest tests/test_models.py -v
```
Expected: ImportError (module not yet created).

- [ ] **Step 3: Implement `src/short_bot/models.py`**

```python
"""Domain models. Frozen dataclasses for in-pipeline data, Pydantic for LLM output."""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


@dataclass(frozen=True)
class NewsItem:
    guid: str
    title: str
    link: str
    source: str | None
    pub_date: datetime | None
    thumb_url: str | None
    description: str | None


@dataclass(frozen=True)
class ScoredItem:
    item: NewsItem
    score: float            # 0-10
    reasoning: str          # LLM's short rationale (debug/UI)


class Highlight(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    color: Literal["red", "yellow"]


class Script(BaseModel):
    header_top: str = Field(min_length=1, max_length=40)
    header_bottom: str = Field(min_length=1, max_length=40)
    photo_overlay: str = Field(min_length=1, max_length=60)
    body_paragraph: str = Field(min_length=20, max_length=800)
    highlights: list[Highlight] = Field(default_factory=list, max_length=8)
    category: str = Field(min_length=1, max_length=30)
    mood: Literal["breaking", "neutral", "upbeat"]

    @model_validator(mode="after")
    def highlights_must_be_substrings(self) -> "Script":
        for h in self.highlights:
            if h.text not in self.body_paragraph:
                raise ValueError(
                    f"Highlight '{h.text}' paragrafta birebir geçmiyor"
                )
        return self


@dataclass
class RenderJob:
    script: Script
    bg_image_path: Path | None
    music_path: Path
    channel_colors: dict
    handle: str
    duration_s: int
    cta_enabled: bool = True
    cta_text: str = "BEĞEN · ABONE OL · PAYLAŞ"
    cta_icons: list[str] = field(default_factory=lambda: ["❤️", "🔔", "↗️"])
    cta_duration_s: int = 4
    cta_show_handle: bool = True
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
pytest tests/test_models.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/models.py tests/test_models.py
git commit -m "feat(models): NewsItem, ScoredItem, Script with highlight validation"
```

---

## Task 3: Config Loader

**Files:**
- Create: `src/short_bot/config.py`, `config/settings.yaml`, `config/channels/son-dakika.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

`tests/test_config.py`:
```python
from pathlib import Path
import pytest

from short_bot.config import load_settings, load_channel, list_channels, ChannelConfig, Settings


def test_load_settings(tmp_path):
    (tmp_path / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web:\n  host: 127.0.0.1\n  port: 5000\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n",
        encoding="utf-8",
    )
    s = load_settings(tmp_path / "settings.yaml")
    assert isinstance(s, Settings)
    assert s.ffmpeg_path == "ffmpeg"
    assert s.fuzzy_dedup_threshold == 0.85
    assert s.web_port == 5000


def test_load_channel(tmp_path):
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nkeywords: [a, b]\nrss_locale: hl=tr&gl=TR&ceid=TR:tr\n"
        "schedule_cron: '0 * * * *'\nduration_s: 30\nmin_score: 8.0\n"
        "max_candidates_per_run: 30\ntemplate: default\n"
        "colors:\n  primary: '#c81e1e'\n  accent: '#ffea3b'\n  bg_gradient: ['#1a3b6b', '#0a1a3b']\n"
        "handle: '@x'\noutput_dir: output/test\nenabled: true\n"
        "cta:\n  enabled: true\n  text: 'A · B · C'\n  icons: ['❤️', '🔔', '↗️']\n  duration_s: 4\n  show_handle: true\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.slug == "test"
    assert c.keywords == ["a", "b"]
    assert c.colors["primary"] == "#c81e1e"
    assert c.cta_enabled is True
    assert c.cta_duration_s == 4


def test_load_channel_invalid_slug(tmp_path):
    (tmp_path / "bad.yaml").write_text(
        "slug: 'BAD SLUG!'\nname: x\nkeywords: []\nrss_locale: ''\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: default\n"
        "colors: {primary: '#000', accent: '#fff', bg_gradient: ['#0', '#1']}\n"
        "handle: '@x'\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="slug"):
        load_channel(tmp_path / "bad.yaml")


def test_list_channels(tmp_path):
    (tmp_path / "a.yaml").write_text("slug: a\nname: A\nkeywords: []\nrss_locale: ''\nschedule_cron: ''\nduration_s: 30\nmin_score: 0\nmax_candidates_per_run: 1\ntemplate: default\ncolors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\nhandle: x\noutput_dir: x\nenabled: true\ncta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("slug: b\nname: B\nkeywords: []\nrss_locale: ''\nschedule_cron: ''\nduration_s: 30\nmin_score: 0\nmax_candidates_per_run: 1\ntemplate: default\ncolors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\nhandle: x\noutput_dir: x\nenabled: false\ncta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n", encoding="utf-8")
    chans = list_channels(tmp_path, enabled_only=True)
    assert len(chans) == 1 and chans[0].slug == "a"
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
pytest tests/test_config.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/short_bot/config.py`**

```python
"""YAML config loader for global settings and per-channel configs."""
from dataclasses import dataclass, field
from pathlib import Path
import re

import yaml

SLUG_RE = re.compile(r"^[a-z0-9\-]+$")


@dataclass(frozen=True)
class Settings:
    ffmpeg_path: str
    claude_cli_path: str
    playwright_browser: str
    web_host: str
    web_port: int
    fuzzy_dedup_threshold: float
    log_level: str


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


def load_settings(path: Path) -> Settings:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    web = data.get("web", {})
    return Settings(
        ffmpeg_path=data["ffmpeg_path"],
        claude_cli_path=data["claude_cli_path"],
        playwright_browser=data.get("playwright_browser", "chromium"),
        web_host=web.get("host", "127.0.0.1"),
        web_port=int(web.get("port", 5000)),
        fuzzy_dedup_threshold=float(data.get("fuzzy_dedup_threshold", 0.85)),
        log_level=data.get("log_level", "INFO"),
    )


def load_channel(path: Path) -> ChannelConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    slug = data["slug"]
    if not SLUG_RE.match(slug):
        raise ValueError(f"Geçersiz slug '{slug}': sadece [a-z0-9-] izinli")
    cta = data.get("cta", {})
    return ChannelConfig(
        slug=slug,
        name=data["name"],
        keywords=list(data.get("keywords", [])),
        rss_locale=data["rss_locale"],
        schedule_cron=data["schedule_cron"],
        duration_s=int(data["duration_s"]),
        min_score=float(data["min_score"]),
        max_candidates_per_run=int(data["max_candidates_per_run"]),
        template=data["template"],
        colors=dict(data["colors"]),
        handle=data["handle"],
        output_dir=data["output_dir"],
        enabled=bool(data.get("enabled", True)),
        cta_enabled=bool(cta.get("enabled", True)),
        cta_text=cta.get("text", "BEĞEN · ABONE OL · PAYLAŞ"),
        cta_icons=list(cta.get("icons", ["❤️", "🔔", "↗️"])),
        cta_duration_s=int(cta.get("duration_s", 4)),
        cta_show_handle=bool(cta.get("show_handle", True)),
    )


def list_channels(channels_dir: Path, enabled_only: bool = False) -> list[ChannelConfig]:
    out = []
    for p in sorted(Path(channels_dir).glob("*.yaml")):
        c = load_channel(p)
        if enabled_only and not c.enabled:
            continue
        out.append(c)
    return out
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
pytest tests/test_config.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Create `config/settings.yaml`**

```yaml
ffmpeg_path: ffmpeg
claude_cli_path: claude
playwright_browser: chromium
web:
  host: 127.0.0.1
  port: 5000
fuzzy_dedup_threshold: 0.85
log_level: INFO
```

- [ ] **Step 6: Create `config/channels/son-dakika.yaml`**

```yaml
slug: son-dakika
name: "Son Dakika"
keywords: ["son dakika", "deprem", "faiz", "dolar", "seçim", "asgari ücret"]
rss_locale: "hl=tr&gl=TR&ceid=TR:tr"
schedule_cron: "0 2,6,10,14,18,22 * * *"
duration_s: 30
min_score: 8.0
max_candidates_per_run: 30
template: default
colors:
  primary: "#c81e1e"
  accent: "#ffea3b"
  bg_gradient: ["#1a3b6b", "#0a1a3b"]
handle: "@HaberShortsTR"
output_dir: output/son-dakika
enabled: true
cta:
  enabled: true
  text: "BEĞEN · ABONE OL · PAYLAŞ"
  icons: ["❤️", "🔔", "↗️"]
  duration_s: 4
  show_handle: true
```

- [ ] **Step 7: Commit**

```bash
git add src/short_bot/config.py tests/test_config.py config/settings.yaml config/channels/son-dakika.yaml
git commit -m "feat(config): YAML loader for settings and channels"
```

---

## Task 4: SQLite + DB helpers

**Files:**
- Create: `src/short_bot/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing test**

`tests/test_db.py`:
```python
from datetime import datetime
from pathlib import Path

from short_bot.db import (
    init_db, mark_processed, is_processed, similar_title_exists,
    record_rss_item, record_short, start_run, finish_run,
)


def test_init_creates_tables(tmp_path):
    db_path = tmp_path / "x.sqlite"
    eng = init_db(db_path)
    with eng.connect() as conn:
        from sqlalchemy import text
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        names = {r[0] for r in rows}
    assert {"processed_items", "rss_items", "shorts", "runs"} <= names


def test_mark_and_is_processed(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    assert not is_processed(eng, "g1", "ch")
    mark_processed(eng, "g1", "Title", "ch")
    assert is_processed(eng, "g1", "ch")
    assert not is_processed(eng, "g1", "other")


def test_similar_title_exists(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, "g1", "Merkez Bankası faizi indirdi", "ch")
    assert similar_title_exists(eng, "Merkez Bankası faizi 250 baz puan indirdi", "ch", threshold=0.7)
    assert not similar_title_exists(eng, "Tamamen alakasız bir başlık", "ch", threshold=0.85)


def test_run_lifecycle(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    run_id = start_run(eng, "ch", trigger="cli", log_path="logs/runs/1.log")
    assert run_id > 0
    finish_run(eng, run_id, status="success", short_id=None, error=None)
    from sqlalchemy import text
    with eng.connect() as conn:
        row = conn.execute(text("SELECT status, ended_at FROM runs WHERE id=:i"), {"i": run_id}).fetchone()
    assert row[0] == "success" and row[1] is not None


def test_record_short(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    sid = record_short(eng, channel="ch", rss_item_guid="g1", title="T",
                       file_path="output/ch/x.mp4", duration_s=30,
                       script_json='{"x":1}', render_ms=4200)
    assert sid > 0


def test_record_rss_item(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    rid = record_rss_item(eng, guid="g1", channel="ch", title="T", link="http://x",
                          source="S", pub_date=datetime.utcnow(), thumb_url=None,
                          score=8.5, status="selected")
    assert rid > 0
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
pytest tests/test_db.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/short_bot/db.py`**

```python
"""SQLite via SQLAlchemy Core. Plain functions, no ORM session ceremony."""
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table,
    Text, create_engine, select, text,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

processed_items = Table(
    "processed_items", metadata,
    Column("guid", String, primary_key=True),
    Column("title", Text, nullable=False),
    Column("channel", String, nullable=False),
    Column("processed_at", DateTime, default=datetime.utcnow),
)

rss_items = Table(
    "rss_items", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("guid", String, nullable=False),
    Column("channel", String, nullable=False),
    Column("title", Text, nullable=False),
    Column("link", Text, nullable=False),
    Column("source", String),
    Column("pub_date", DateTime),
    Column("thumb_url", Text),
    Column("score", Float),
    Column("status", String),
    Column("fetched_at", DateTime, default=datetime.utcnow),
    Column("short_id", Integer, ForeignKey("shorts.id")),
)

shorts = Table(
    "shorts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False),
    Column("rss_item_guid", String),
    Column("title", Text, nullable=False),
    Column("file_path", Text, nullable=False),
    Column("duration_s", Integer),
    Column("script_json", Text),
    Column("render_ms", Integer),
    Column("created_at", DateTime, default=datetime.utcnow),
    Column("deleted_at", DateTime),
)

runs = Table(
    "runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False),
    Column("trigger", String, nullable=False),
    Column("started_at", DateTime, default=datetime.utcnow),
    Column("ended_at", DateTime),
    Column("status", String),
    Column("short_id", Integer, ForeignKey("shorts.id")),
    Column("error", Text),
    Column("log_path", Text),
)


def init_db(db_path: Path | str) -> Engine:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    metadata.create_all(eng)
    return eng


def mark_processed(eng: Engine, guid: str, title: str, channel: str) -> None:
    with eng.begin() as conn:
        conn.execute(processed_items.insert().prefix_with("OR IGNORE"),
                     {"guid": guid, "title": title, "channel": channel,
                      "processed_at": datetime.utcnow()})


def is_processed(eng: Engine, guid: str, channel: str) -> bool:
    with eng.connect() as conn:
        row = conn.execute(
            select(processed_items.c.guid)
            .where(processed_items.c.guid == guid)
            .where(processed_items.c.channel == channel)
        ).fetchone()
    return row is not None


def similar_title_exists(eng: Engine, title: str, channel: str, threshold: float) -> bool:
    with eng.connect() as conn:
        rows = conn.execute(
            select(processed_items.c.title).where(processed_items.c.channel == channel)
        ).fetchall()
    title_low = title.lower()
    for (existing,) in rows:
        if SequenceMatcher(None, title_low, existing.lower()).ratio() >= threshold:
            return True
    return False


def record_rss_item(eng: Engine, *, guid, channel, title, link, source,
                    pub_date, thumb_url, score, status) -> int:
    with eng.begin() as conn:
        result = conn.execute(rss_items.insert().values(
            guid=guid, channel=channel, title=title, link=link,
            source=source, pub_date=pub_date, thumb_url=thumb_url,
            score=score, status=status, fetched_at=datetime.utcnow(),
        ))
        return result.inserted_primary_key[0]


def record_short(eng: Engine, *, channel, rss_item_guid, title, file_path,
                 duration_s, script_json, render_ms) -> int:
    with eng.begin() as conn:
        result = conn.execute(shorts.insert().values(
            channel=channel, rss_item_guid=rss_item_guid, title=title,
            file_path=file_path, duration_s=duration_s, script_json=script_json,
            render_ms=render_ms, created_at=datetime.utcnow(),
        ))
        return result.inserted_primary_key[0]


def start_run(eng: Engine, channel: str, trigger: str, log_path: str) -> int:
    with eng.begin() as conn:
        result = conn.execute(runs.insert().values(
            channel=channel, trigger=trigger, status="running",
            started_at=datetime.utcnow(), log_path=log_path,
        ))
        return result.inserted_primary_key[0]


def finish_run(eng: Engine, run_id: int, *, status: str,
               short_id: int | None, error: str | None) -> None:
    with eng.begin() as conn:
        conn.execute(runs.update().where(runs.c.id == run_id).values(
            ended_at=datetime.utcnow(), status=status,
            short_id=short_id, error=error,
        ))
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
pytest tests/test_db.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/db.py tests/test_db.py
git commit -m "feat(db): SQLite schema + helpers (dedup, runs, shorts, rss_items)"
```

---

## Task 5: Claude CLI Wrapper

**Files:**
- Create: `src/short_bot/claude_cli.py`
- Test: `tests/test_claude_cli.py`

- [ ] **Step 1: Write failing test**

`tests/test_claude_cli.py`:
```python
import json
from unittest.mock import patch, MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from short_bot.claude_cli import run_json, ClaudeCliError


class _Out(BaseModel):
    score: float
    why: str


def _fake_proc(stdout: str, returncode: int = 0):
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = ""
    return p


def test_run_json_parses_valid(tmp_path):
    payload = {"score": 8.5, "why": "interesting"}
    with patch("short_bot.claude_cli.subprocess.run",
               return_value=_fake_proc(json.dumps(payload))):
        result = run_json("prompt", _Out, claude_path="claude")
    assert result.score == 8.5


def test_run_json_extracts_from_code_fence():
    text = "Here you go:\n```json\n{\"score\": 7.2, \"why\": \"ok\"}\n```\nDone."
    with patch("short_bot.claude_cli.subprocess.run",
               return_value=_fake_proc(text)):
        r = run_json("p", _Out, claude_path="claude")
    assert r.score == 7.2


def test_run_json_retries_on_invalid():
    bad = "not json at all"
    good = json.dumps({"score": 6.0, "why": "x"})
    with patch("short_bot.claude_cli.subprocess.run",
               side_effect=[_fake_proc(bad), _fake_proc(good)]):
        r = run_json("p", _Out, claude_path="claude", retries=2)
    assert r.score == 6.0


def test_run_json_raises_after_retries_exhausted():
    bad = "not json"
    with patch("short_bot.claude_cli.subprocess.run",
               return_value=_fake_proc(bad)):
        with pytest.raises(ClaudeCliError):
            run_json("p", _Out, claude_path="claude", retries=2)


def test_run_json_raises_on_non_zero_exit():
    with patch("short_bot.claude_cli.subprocess.run",
               return_value=_fake_proc("", returncode=1)):
        with pytest.raises(ClaudeCliError):
            run_json("p", _Out, claude_path="claude", retries=1)
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
pytest tests/test_claude_cli.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/short_bot/claude_cli.py`**

```python
"""Wrapper around `claude` CLI in headless (-p) mode. JSON-only output."""
from __future__ import annotations

import json
import re
import subprocess
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class ClaudeCliError(RuntimeError):
    pass


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
_FIRST_OBJ_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty output")
    m = _CODE_FENCE_RE.search(raw)
    if m:
        return m.group(1)
    m = _FIRST_OBJ_RE.search(raw)
    if m:
        return m.group(1)
    return raw


def run_json(
    prompt: str,
    schema: type[T],
    *,
    claude_path: str = "claude",
    retries: int = 2,
    timeout_s: int = 90,
) -> T:
    """Invoke `claude -p PROMPT --output-format text` and parse output as JSON validating against `schema`."""
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            proc = subprocess.run(
                [claude_path, "-p", prompt, "--output-format", "text"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            last_error = e
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

        if proc.returncode != 0:
            last_error = ClaudeCliError(f"claude exit {proc.returncode}: {proc.stderr[:500]}")
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

        try:
            payload = _extract_json(proc.stdout)
            data = json.loads(payload)
            return schema.model_validate(data)
        except (ValueError, json.JSONDecodeError, ValidationError) as e:
            last_error = e
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

    raise ClaudeCliError(f"claude_cli failed after {retries} attempts: {last_error}")
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
pytest tests/test_claude_cli.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/claude_cli.py tests/test_claude_cli.py
git commit -m "feat(claude_cli): subprocess wrapper with JSON extraction + retry"
```

---

## Task 6: RSS Fetcher

**Files:**
- Create: `src/short_bot/fetcher.py`
- Create: `tests/fixtures/rss_son_dakika.xml`
- Test: `tests/test_fetcher.py`

- [ ] **Step 1: Create `tests/fixtures/rss_son_dakika.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Google News</title>
    <link>https://news.google.com</link>
    <description>tr</description>
    <item>
      <title>Merkez Bankası faizi 250 baz puan indirdi - Reuters TR</title>
      <link>https://news.google.com/articles/CBMxxx</link>
      <guid isPermaLink="false">CBMxxx</guid>
      <pubDate>Tue, 05 May 2026 13:42:00 GMT</pubDate>
      <description>&lt;p&gt;Karar piyasada şok etkisi yarattı.&lt;/p&gt;</description>
      <source url="https://reuters.com">Reuters TR</source>
      <media:thumbnail url="https://lh3.googleusercontent.com/proxy/abc.jpg" />
    </item>
    <item>
      <title>Dolar 41 lirayı geçti - Habertürk</title>
      <link>https://news.google.com/articles/CBMyyy</link>
      <guid isPermaLink="false">CBMyyy</guid>
      <pubDate>Tue, 05 May 2026 13:38:00 GMT</pubDate>
      <description>Borsa sert düştü.</description>
      <source url="https://haberturk.com">Habertürk</source>
    </item>
  </channel>
</rss>
```

- [ ] **Step 2: Write failing test**

`tests/test_fetcher.py`:
```python
from pathlib import Path
from unittest.mock import patch

from short_bot.fetcher import fetch_rss, build_rss_url


def test_build_rss_url_single_keyword():
    url = build_rss_url(["faiz"], "hl=tr&gl=TR&ceid=TR:tr")
    assert "q=faiz" in url
    assert "hl=tr&gl=TR&ceid=TR:tr" in url


def test_build_rss_url_multi_keyword_or_joined():
    url = build_rss_url(["faiz", "dolar", "deprem"], "hl=tr")
    assert "q=faiz+OR+dolar+OR+deprem" in url


def test_fetch_rss_parses_fixture():
    fixture = Path(__file__).parent / "fixtures" / "rss_son_dakika.xml"
    raw = fixture.read_bytes()
    with patch("short_bot.fetcher.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = raw
        items = fetch_rss(["faiz"], "hl=tr&gl=TR&ceid=TR:tr")
    assert len(items) == 2
    first = items[0]
    assert first.guid == "CBMxxx"
    assert first.source == "Reuters TR"
    assert first.thumb_url == "https://lh3.googleusercontent.com/proxy/abc.jpg"
    assert items[1].thumb_url is None


def test_fetch_rss_retries_on_failure():
    from requests.exceptions import ConnectionError
    with patch("short_bot.fetcher.requests.get",
               side_effect=[ConnectionError(), ConnectionError(),
                            type("R", (), {"status_code": 200, "content": b"<rss version='2.0'><channel></channel></rss>"})()]):
        items = fetch_rss(["x"], "hl=tr", max_retries=3, backoff=0)
    assert items == []
```

- [ ] **Step 3: Run test, verify FAIL**

```bash
pytest tests/test_fetcher.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `src/short_bot/fetcher.py`**

```python
"""Google News RSS fetcher."""
from __future__ import annotations

import time
from datetime import datetime
from urllib.parse import quote_plus

import feedparser
import requests
from dateutil import parser as dateparser

from short_bot.models import NewsItem

_BASE_URL = "https://news.google.com/rss/search"


def build_rss_url(keywords: list[str], locale: str) -> str:
    if not keywords:
        raise ValueError("keywords boş olamaz")
    q = "+OR+".join(quote_plus(k) for k in keywords)
    return f"{_BASE_URL}?q={q}&{locale}"


def fetch_rss(
    keywords: list[str],
    locale: str,
    *,
    max_retries: int = 3,
    backoff: float = 1.0,
    timeout: int = 15,
) -> list[NewsItem]:
    url = build_rss_url(keywords, locale)
    last_err: Exception | None = None

    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "short-bot/0.1"})
            r.raise_for_status()
            return _parse_feed(r.content)
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(backoff * (2 ** attempt))

    raise RuntimeError(f"RSS fetch failed for {url}: {last_err}")


def _parse_feed(raw: bytes) -> list[NewsItem]:
    parsed = feedparser.parse(raw)
    items: list[NewsItem] = []
    for e in parsed.entries:
        thumb = None
        if "media_thumbnail" in e and e.media_thumbnail:
            thumb = e.media_thumbnail[0].get("url")
        elif "media_content" in e and e.media_content:
            thumb = e.media_content[0].get("url")

        pub = None
        if e.get("published"):
            try:
                pub = dateparser.parse(e.published)
            except (ValueError, TypeError):
                pub = None

        title = e.get("title", "").strip()
        # Google News appends " - Source" to title; split off
        source = None
        if " - " in title:
            head, _, tail = title.rpartition(" - ")
            title = head.strip()
            source = tail.strip()
        if e.get("source"):
            try:
                source = e.source.get("title") or source
            except AttributeError:
                pass

        items.append(NewsItem(
            guid=e.get("id") or e.get("guid") or e.get("link", ""),
            title=title,
            link=e.get("link", ""),
            source=source,
            pub_date=pub,
            thumb_url=thumb,
            description=e.get("summary"),
        ))
    return items
```

- [ ] **Step 5: Run tests, verify PASS**

```bash
pytest tests/test_fetcher.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/fetcher.py tests/test_fetcher.py tests/fixtures/rss_son_dakika.xml
git commit -m "feat(fetcher): RSS fetch + parse with thumbnail extraction"
```

---

## Task 7: Dedup Filter

**Files:**
- Create: `src/short_bot/dedup.py`
- Test: `tests/test_dedup.py`

- [ ] **Step 1: Write failing test**

`tests/test_dedup.py`:
```python
from datetime import datetime

from short_bot.db import init_db, mark_processed
from short_bot.dedup import filter_new
from short_bot.models import NewsItem


def _item(guid: str, title: str) -> NewsItem:
    return NewsItem(guid=guid, title=title, link="http://x", source=None,
                    pub_date=None, thumb_url=None, description=None)


def test_filter_new_keeps_unseen(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    items = [_item("g1", "Faiz indirimi"), _item("g2", "Dolar rekoru")]
    out = filter_new(eng, items, "ch", fuzzy_threshold=0.85)
    assert {i.guid for i in out} == {"g1", "g2"}


def test_filter_new_drops_seen_guid(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, "g1", "Faiz indirimi", "ch")
    items = [_item("g1", "Faiz indirimi"), _item("g2", "Dolar rekoru")]
    out = filter_new(eng, items, "ch", fuzzy_threshold=0.85)
    assert [i.guid for i in out] == ["g2"]


def test_filter_new_drops_fuzzy_match(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, "g_old", "Merkez Bankası faizi 250 baz puan indirdi", "ch")
    items = [_item("g_new", "Merkez Bankası faizi 250 baz puan indirmiş")]
    out = filter_new(eng, items, "ch", fuzzy_threshold=0.85)
    assert out == []


def test_filter_new_isolated_per_channel(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, "g1", "Faiz", "ch_a")
    items = [_item("g1", "Faiz")]
    out = filter_new(eng, items, "ch_b", fuzzy_threshold=0.85)
    assert len(out) == 1
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
pytest tests/test_dedup.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/short_bot/dedup.py`**

```python
"""Dedup: GUID exact match + fuzzy title similarity (per channel)."""
from sqlalchemy.engine import Engine

from short_bot.db import is_processed, similar_title_exists
from short_bot.models import NewsItem


def filter_new(
    eng: Engine,
    items: list[NewsItem],
    channel: str,
    *,
    fuzzy_threshold: float,
) -> list[NewsItem]:
    out: list[NewsItem] = []
    for item in items:
        if is_processed(eng, item.guid, channel):
            continue
        if similar_title_exists(eng, item.title, channel, fuzzy_threshold):
            continue
        out.append(item)
    return out
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
pytest tests/test_dedup.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/dedup.py tests/test_dedup.py
git commit -m "feat(dedup): GUID + fuzzy title filter, per-channel isolated"
```

---

## Task 8: LLM Scorer

**Files:**
- Create: `src/short_bot/scorer.py`
- Test: `tests/test_scorer.py`

- [ ] **Step 1: Write failing test**

`tests/test_scorer.py`:
```python
from unittest.mock import patch
from datetime import datetime

import pytest

from short_bot.models import NewsItem, ScoredItem
from short_bot.scorer import score_items, build_scoring_prompt


def _item(guid, title):
    return NewsItem(guid=guid, title=title, link="http://x", source="S",
                    pub_date=datetime(2026, 5, 5), thumb_url=None, description=None)


def test_build_scoring_prompt_lists_items():
    items = [_item("g1", "A"), _item("g2", "B")]
    prompt = build_scoring_prompt(items)
    assert "g1" in prompt and "g2" in prompt
    assert "A" in prompt and "B" in prompt
    assert "JSON" in prompt or "json" in prompt


def test_score_items_parses_response():
    items = [_item("g1", "Faiz"), _item("g2", "Hava")]
    fake = {
        "scores": [
            {"guid": "g1", "score": 9.2, "reasoning": "kritik"},
            {"guid": "g2", "score": 4.0, "reasoning": "sıkıcı"},
        ]
    }
    with patch("short_bot.scorer.run_json") as m:
        from short_bot.scorer import _ScoreResponse
        m.return_value = _ScoreResponse.model_validate(fake)
        scored = score_items(items, claude_path="claude")
    assert len(scored) == 2
    assert scored[0].score == 9.2 and scored[0].item.guid == "g1"


def test_score_items_skips_unknown_guid():
    items = [_item("g1", "X")]
    fake = {"scores": [{"guid": "g_other", "score": 7, "reasoning": "y"}]}
    with patch("short_bot.scorer.run_json") as m:
        from short_bot.scorer import _ScoreResponse
        m.return_value = _ScoreResponse.model_validate(fake)
        scored = score_items(items, claude_path="claude")
    assert scored == []


def test_score_items_empty_returns_empty():
    assert score_items([], claude_path="claude") == []
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
pytest tests/test_scorer.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/short_bot/scorer.py`**

```python
"""LLM-based interestingness scorer (0-10) per news item."""
from pydantic import BaseModel, Field

from short_bot.claude_cli import run_json
from short_bot.models import NewsItem, ScoredItem


class _ItemScore(BaseModel):
    guid: str
    score: float = Field(ge=0, le=10)
    reasoning: str = Field(max_length=200)


class _ScoreResponse(BaseModel):
    scores: list[_ItemScore]


def build_scoring_prompt(items: list[NewsItem]) -> str:
    listing = "\n".join(f"- guid={i.guid} | {i.title}" for i in items)
    return (
        "Aşağıdaki Türkçe haber başlıklarını bir YouTube Shorts kanalı için "
        "ilginçlik/önem açısından 0-10 arası puanla. 9-10 = son dakika çok etkileyici "
        "(deprem, kritik karar, şok haber); 7-8 = önemli ama bekleyebilir; "
        "5-6 = ilginç ama derinliği yok; 0-4 = sıkıcı/teknik/lokal.\n\n"
        f"Başlıklar:\n{listing}\n\n"
        "SADECE şu JSON formatında yanıtla, başka metin yazma:\n"
        '{"scores": [{"guid": "<aynısı>", "score": <0-10>, "reasoning": "<≤200 char>"}, ...]}'
    )


def score_items(
    items: list[NewsItem],
    *,
    claude_path: str = "claude",
) -> list[ScoredItem]:
    if not items:
        return []
    prompt = build_scoring_prompt(items)
    response = run_json(prompt, _ScoreResponse, claude_path=claude_path)
    by_guid = {i.guid: i for i in items}
    out: list[ScoredItem] = []
    for s in response.scores:
        item = by_guid.get(s.guid)
        if item is None:
            continue
        out.append(ScoredItem(item=item, score=s.score, reasoning=s.reasoning))
    return out


def select_top(scored: list[ScoredItem], min_score: float, n: int = 1) -> list[ScoredItem]:
    above = [s for s in scored if s.score >= min_score]
    above.sort(key=lambda s: s.score, reverse=True)
    return above[:n]
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
pytest tests/test_scorer.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/scorer.py tests/test_scorer.py
git commit -m "feat(scorer): LLM-based interestingness scoring with select_top helper"
```

---

## Task 9: Article Extractor

**Files:**
- Create: `src/short_bot/extractor.py`
- Create: `tests/fixtures/article_basic.html`, `tests/fixtures/article_empty.html`
- Test: `tests/test_extractor.py`

- [ ] **Step 1: Create fixtures**

`tests/fixtures/article_basic.html`:
```html
<!DOCTYPE html>
<html lang="tr">
<head><title>Haber</title></head>
<body>
<header><nav>Site Menü</nav></header>
<main>
<article>
<h1>Merkez Bankası faizi 250 baz puan indirdi</h1>
<p>Türkiye Cumhuriyet Merkez Bankası bugün düzenlenen olağanüstü Para Politikası Kurulu toplantısında politika faizini 250 baz puan indirdi.</p>
<p>Karar, piyasalarda şok etkisi yarattı. Dolar/TL açıklamanın ardından 41,20 seviyesini görerek tarihi rekor kırdı.</p>
<p>BIST 100 endeksi ise yüzde 2,3 değer kaybetti. Analistler kararın enflasyon beklentilerini bozabileceğini söylüyor.</p>
</article>
</main>
<footer>Telif</footer>
</body>
</html>
```

`tests/fixtures/article_empty.html`:
```html
<!DOCTYPE html>
<html><body><div>Bu sayfayı görüntülemek için giriş yapın.</div></body></html>
```

- [ ] **Step 2: Write failing test**

`tests/test_extractor.py`:
```python
from pathlib import Path
from unittest.mock import patch, MagicMock

from short_bot.extractor import extract_article


def _resp(html: str, status: int = 200):
    r = MagicMock()
    r.status_code = status
    r.text = html
    r.content = html.encode("utf-8")
    return r


def test_extract_article_returns_clean_text():
    html = (Path(__file__).parent / "fixtures" / "article_basic.html").read_text(encoding="utf-8")
    with patch("short_bot.extractor.requests.get", return_value=_resp(html)):
        body = extract_article("http://example.com/x")
    assert body is not None
    assert "Türkiye Cumhuriyet Merkez Bankası" in body
    assert "Site Menü" not in body
    assert "Telif" not in body
    assert len(body) <= 2000


def test_extract_article_returns_none_when_empty():
    html = (Path(__file__).parent / "fixtures" / "article_empty.html").read_text(encoding="utf-8")
    with patch("short_bot.extractor.requests.get", return_value=_resp(html)):
        body = extract_article("http://x")
    assert body is None


def test_extract_article_returns_none_on_http_error():
    with patch("short_bot.extractor.requests.get", return_value=_resp("", status=403)):
        assert extract_article("http://x") is None


def test_extract_article_truncates_to_max_chars():
    big = "<html><body><article>" + ("Uzun bir cümle. " * 1000) + "</article></body></html>"
    with patch("short_bot.extractor.requests.get", return_value=_resp(big)):
        body = extract_article("http://x", max_chars=500)
    assert body is not None and len(body) <= 500
```

- [ ] **Step 3: Run test, verify FAIL**

```bash
pytest tests/test_extractor.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `src/short_bot/extractor.py`**

```python
"""Article body extractor — trafilatura with HTTP error / empty-body handling."""
from __future__ import annotations

import requests
import trafilatura


def extract_article(
    url: str,
    *,
    max_chars: int = 2000,
    timeout: int = 15,
) -> str | None:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "short-bot/0.1"})
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None

    text = trafilatura.extract(
        r.text,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text:
        return None

    text = text.strip()
    if len(text) < 30:                    # likely paywall/login wall
        return None
    if len(text) > max_chars:
        # truncate at last full sentence
        truncated = text[:max_chars]
        last = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
        if last > max_chars // 2:
            text = truncated[:last + 1]
        else:
            text = truncated
    return text
```

- [ ] **Step 5: Run tests, verify PASS**

```bash
pytest tests/test_extractor.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/extractor.py tests/test_extractor.py tests/fixtures/article_basic.html tests/fixtures/article_empty.html
git commit -m "feat(extractor): trafilatura article body with empty/paywall fallback"
```

---

## Task 10: Script Writer

**Files:**
- Create: `src/short_bot/script_writer.py`
- Test: `tests/test_script_writer.py`

- [ ] **Step 1: Write failing test**

`tests/test_script_writer.py`:
```python
from unittest.mock import patch
from datetime import datetime

import pytest

from short_bot.models import NewsItem, Script
from short_bot.script_writer import write_script, build_script_prompt


def _item():
    return NewsItem(guid="g", title="Faiz indirimi", link="http://x", source="Reuters",
                    pub_date=datetime(2026, 5, 5), thumb_url=None,
                    description="Karar şok yarattı.")


def test_build_script_prompt_includes_body_and_title():
    p = build_script_prompt(_item(), "Tam makale gövdesi metni")
    assert "Faiz indirimi" in p
    assert "Tam makale gövdesi metni" in p
    assert "header_top" in p
    assert "highlights" in p


def test_write_script_returns_script_model():
    fake = Script(
        header_top="FAİZ ŞOKU",
        header_bottom="BAŞLADI",
        photo_overlay="250 BAZ PUAN İNDİRİM",
        body_paragraph="Türkiye Cumhuriyet Merkez Bankası faizi 250 baz puan indirdi. Karar piyasada şok yarattı.",
        highlights=[{"text": "250 baz puan", "color": "yellow"}],
        category="EKONOMİ",
        mood="breaking",
    )
    with patch("short_bot.script_writer.run_json", return_value=fake):
        result = write_script(_item(), "Tam makale", claude_path="claude")
    assert isinstance(result, Script)
    assert result.header_top == "FAİZ ŞOKU"
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
pytest tests/test_script_writer.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/short_bot/script_writer.py`**

```python
"""LLM script writer: news item + body → Script (header / overlay / paragraph / highlights)."""
from short_bot.claude_cli import run_json
from short_bot.models import NewsItem, Script


def build_script_prompt(item: NewsItem, body: str) -> str:
    source = item.source or "kaynak"
    return f"""Aşağıdaki Türkçe haberi 30 saniyelik dikey YouTube Shorts için hazırla.

ORİJİNAL BAŞLIK: {item.title}
KAYNAK: {source}

MAKALE GÖVDESİ:
{body}

Görev: Bu haberi 3-katmanlı bir Short videoya dönüştür. SADECE aşağıdaki JSON formatında yanıtla, başka metin yazma:

{{
  "header_top":      "<üst satır, 1-3 kelime, BÜYÜK HARF, dikkat çekici>",
  "header_bottom":   "<alt satır, 1-3 kelime, BÜYÜK HARF>",
  "photo_overlay":   "<fotoğraf üzeri sarı bantta görünecek, 2-5 kelime, BÜYÜK HARF, somut sayı/etki>",
  "body_paragraph":  "<haberi 4-6 cümlede özetleyen Türkçe paragraf, 250-400 karakter, akıcı haber dili>",
  "highlights":      [{{"text": "<paragrafta birebir geçen ifade>", "color": "red"|"yellow"}}],
  "category":        "<EKONOMİ | SPOR | DÜNYA | TEKNOLOJİ | SAĞLIK | SİYASET | SON DAKİKA | ...>",
  "mood":            "breaking" | "neutral" | "upbeat"
}}

Kurallar:
- highlights[i].text MUTLAKA body_paragraph içinde birebir (kelimesi kelimesine) geçmelidir
- 1-4 highlight ekle: önemli sayı/oran/karar = yellow; uyarı/tehlike/şok = red
- header_top + header_bottom toplam 4-6 kelimeyi geçmesin
- Yazım Türkçe, diakritikler tam (ç, ğ, ı, ö, ş, ü)
"""


def write_script(item: NewsItem, body: str, *, claude_path: str = "claude") -> Script:
    prompt = build_script_prompt(item, body)
    return run_json(prompt, Script, claude_path=claude_path, retries=3)
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
pytest tests/test_script_writer.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/script_writer.py tests/test_script_writer.py
git commit -m "feat(script_writer): LLM prompt for 3-layer Script with substring highlights"
```

---

## Task 11: Asset Resolver

**Files:**
- Create: `src/short_bot/assets.py`
- Create: `tests/fixtures/thumb_sample.jpg`, `tests/fixtures/music_sample.mp3`
- Test: `tests/test_assets.py`

- [ ] **Step 1: Create fixture files**

```bash
# thumb_sample.jpg: any small JPG. Use a 200x200 solid color via Pillow.
python -c "from PIL import Image; Image.new('RGB',(400,300),(80,40,120)).save('tests/fixtures/thumb_sample.jpg', 'JPEG')"

# music_sample.mp3: 1-second silent MP3 via ffmpeg (must be on PATH)
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo -t 1 -q:a 9 tests/fixtures/music_sample.mp3
```

Verify:
```bash
ls -la tests/fixtures/thumb_sample.jpg tests/fixtures/music_sample.mp3
```

- [ ] **Step 2: Write failing test**

`tests/test_assets.py`:
```python
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.assets import download_and_blur_thumb, pick_music


def test_download_and_blur_thumb_writes_blurred(tmp_path):
    src = (Path(__file__).parent / "fixtures" / "thumb_sample.jpg").read_bytes()
    cache = tmp_path / "cache"
    with patch("short_bot.assets.requests.get") as m:
        r = MagicMock()
        r.status_code = 200
        r.content = src
        m.return_value = r
        out = download_and_blur_thumb("http://x/thumb.jpg", cache, blur_radius=8)
    assert out is not None
    assert out.exists()
    assert out.suffix == ".jpg"


def test_download_and_blur_thumb_returns_none_on_404(tmp_path):
    with patch("short_bot.assets.requests.get") as m:
        r = MagicMock()
        r.status_code = 404
        m.return_value = r
        assert download_and_blur_thumb("http://x", tmp_path) is None


def test_download_and_blur_thumb_returns_none_on_invalid_image(tmp_path):
    with patch("short_bot.assets.requests.get") as m:
        r = MagicMock()
        r.status_code = 200
        r.content = b"not an image"
        m.return_value = r
        assert download_and_blur_thumb("http://x", tmp_path) is None


def test_pick_music_returns_random_file(tmp_path):
    mood_dir = tmp_path / "music" / "breaking"
    mood_dir.mkdir(parents=True)
    src = Path(__file__).parent / "fixtures" / "music_sample.mp3"
    (mood_dir / "a.mp3").write_bytes(src.read_bytes())
    (mood_dir / "b.mp3").write_bytes(src.read_bytes())
    picked = pick_music(tmp_path / "music", mood="breaking")
    assert picked.name in {"a.mp3", "b.mp3"}


def test_pick_music_falls_back_to_neutral(tmp_path):
    neutral = tmp_path / "music" / "neutral"
    neutral.mkdir(parents=True)
    src = Path(__file__).parent / "fixtures" / "music_sample.mp3"
    (neutral / "n.mp3").write_bytes(src.read_bytes())
    picked = pick_music(tmp_path / "music", mood="upbeat")
    assert picked.name == "n.mp3"


def test_pick_music_raises_when_nothing_available(tmp_path):
    (tmp_path / "music").mkdir()
    with pytest.raises(FileNotFoundError):
        pick_music(tmp_path / "music", mood="breaking")
```

- [ ] **Step 3: Run test, verify FAIL**

```bash
pytest tests/test_assets.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `src/short_bot/assets.py`**

```python
"""Asset resolution: download+blur RSS thumbnail; pick mood-matched music."""
from __future__ import annotations

import hashlib
import io
import random
from pathlib import Path

import requests
from PIL import Image, ImageFilter, UnidentifiedImageError


def download_and_blur_thumb(
    url: str,
    cache_dir: Path,
    *,
    blur_radius: int = 8,
    timeout: int = 15,
) -> Path | None:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    cached = cache_dir / f"{key}.jpg"
    if cached.exists():
        return cached

    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "short-bot/0.1"})
    except requests.RequestException:
        return None
    if r.status_code != 200 or not r.content:
        return None

    try:
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
    except (UnidentifiedImageError, OSError):
        return None

    blurred = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    blurred.save(cached, "JPEG", quality=85)
    return cached


_MOOD_FALLBACK = {"breaking": ["breaking", "neutral"],
                  "neutral": ["neutral"],
                  "upbeat": ["upbeat", "neutral"]}


def pick_music(music_root: Path, mood: str) -> Path:
    music_root = Path(music_root)
    for try_mood in _MOOD_FALLBACK.get(mood, [mood, "neutral"]):
        d = music_root / try_mood
        if not d.is_dir():
            continue
        files = sorted(p for p in d.glob("*.mp3") if p.is_file())
        if files:
            return random.choice(files)
    raise FileNotFoundError(f"Mood '{mood}' (and fallback) için müzik bulunamadı: {music_root}")
```

- [ ] **Step 5: Run tests, verify PASS**

```bash
pytest tests/test_assets.py -v
```
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/assets.py tests/test_assets.py tests/fixtures/thumb_sample.jpg tests/fixtures/music_sample.mp3
git commit -m "feat(assets): thumb download+blur with cache, mood music picker with fallback"
```

---

## Task 12: HTML Renderer (Template + Playwright)

**Files:**
- Create: `templates/default.html.j2`
- Create: `src/short_bot/renderer.py`
- Test: `tests/test_renderer.py`

- [ ] **Step 1: Install Playwright Chromium browser (one-time)**

```bash
playwright install chromium
```
Expected: Downloads ~150MB Chromium.

- [ ] **Step 2: Create `templates/default.html.j2`**

```jinja2
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<title>Short</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { width: 1080px; height: 1920px; overflow: hidden; background: #000;
    font-family: 'Inter', -apple-system, sans-serif; color: #fff; }

  .stage { position: relative; width: 1080px; height: 1920px; }

  /* HEADER (top banner) */
  .header {
    background: linear-gradient(90deg, {{ colors.primary }}, {{ colors.primary_light }});
    padding: 70px 50px 60px;
    text-align: center;
    font-weight: 900;
    font-size: 130px;
    line-height: 1.0;
    letter-spacing: 1px;
    box-shadow: 0 12px 0 rgba(0,0,0,.4);
    position: relative;
  }
  .header .top { display: block; }
  .header .bot { display: block; margin-top: 8px; }
  .header .badge {
    position: absolute; top: 24px; right: 24px;
    background: #000; color: {{ colors.accent }};
    font-size: 28px; font-weight: 800; letter-spacing: 1px;
    padding: 10px 16px; border-radius: 8px;
  }

  /* PHOTO band */
  .photo {
    position: relative;
    height: 720px;
    background: linear-gradient(135deg, {{ colors.bg_gradient[0] }}, {{ colors.bg_gradient[1] }});
    overflow: hidden;
  }
  .photo .bg-img {
    position: absolute; inset: 0;
    background-image: url('{{ bg_image_url|default("") }}');
    background-size: cover; background-position: center;
    {% if not bg_image_url %}display: none;{% endif %}
  }
  .photo .vignette { position: absolute; inset: 0;
    background: radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,.55) 100%); }
  .photo .corner {
    position: absolute; top: 30px; left: 30px;
    background: rgba(0,0,0,.78); color: #fff;
    font-size: 30px; padding: 10px 18px; border-radius: 8px;
    font-weight: 700; letter-spacing: 1px;
  }
  .photo .yellow {
    position: absolute; bottom: 40px; left: 0; right: 0;
    background: linear-gradient(90deg, {{ colors.accent }}, #ffcc00);
    color: #000; padding: 28px 50px;
    font-weight: 900; font-size: 64px; line-height: 1.05;
    text-align: center;
    transform: skewY(-1.5deg);
    box-shadow: 0 8px 0 rgba(0,0,0,.4);
  }

  /* BODY paragraph */
  .body {
    background: linear-gradient(180deg, #1a1a2a, #0a0a1a);
    padding: 60px 60px 200px;
    font-size: 56px;
    line-height: 1.55;
    font-weight: 600;
    color: #fff;
  }
  .body .hl-r { background: {{ colors.primary }}; color: #fff;
    padding: 2px 14px; border-radius: 6px; font-weight: 700; }
  .body .hl-y { background: {{ colors.accent }}; color: #000;
    padding: 2px 14px; border-radius: 6px; font-weight: 700; }

  /* PROGRESS bar */
  .progress {
    position: absolute; left: 0; right: 0; bottom: 84px; height: 8px;
    background: rgba(255,255,255,.18);
  }
  .progress::after {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0;
    background: linear-gradient(90deg, {{ colors.accent }}, {{ colors.primary }});
    animation: fill {{ duration_s }}s linear forwards;
  }
  @keyframes fill { from { width: 0; } to { width: 100%; } }

  /* HANDLE */
  .handle {
    position: absolute; left: 0; right: 0; bottom: 30px;
    text-align: center; color: #fff; opacity: .9;
    font-size: 34px; font-weight: 600;
  }

  /* CTA overlay (last cta_duration_s seconds) */
  {% if cta.enabled %}
  .cta {
    position: absolute; left: 0; right: 0; bottom: 0;
    background: linear-gradient(180deg, transparent, rgba(0,0,0,.92) 30%);
    padding: 80px 60px 130px;
    text-align: center;
    opacity: 0;
    transform: translateY(40px);
    animation:
      cta-in 0.5s ease-out {{ duration_s - cta.duration_s }}s forwards,
      cta-out 0.5s ease-in {{ duration_s - 0.5 }}s forwards;
  }
  {% if cta.show_handle %}
  .cta .handle-line { font-size: 48px; font-weight: 800; margin-bottom: 18px;
    color: {{ colors.accent }}; }
  {% endif %}
  .cta .row {
    display: flex; align-items: center; justify-content: center;
    gap: 24px;
    background: linear-gradient(90deg, {{ colors.primary }}, #ff5050);
    padding: 28px 40px; border-radius: 16px;
    box-shadow: 0 10px 0 rgba(0,0,0,.4);
    font-size: 52px; font-weight: 900; letter-spacing: 1px;
  }
  .cta .icon { font-size: 64px; animation: pulse 0.9s infinite ease-in-out; }
  @keyframes pulse { 0%,100% { transform: scale(1); } 50% { transform: scale(1.18); } }
  @keyframes cta-in { to { opacity: 1; transform: translateY(0); } }
  @keyframes cta-out { to { opacity: 0; transform: translateY(-10px); } }
  /* Dim body during CTA so it's readable */
  .body { animation: dim 0.5s ease-in {{ duration_s - cta.duration_s }}s forwards; }
  @keyframes dim { to { opacity: 0.15; } }
  {% endif %}
</style>
</head>
<body>
<div class="stage">
  <div class="header">
    <span class="badge">{{ category|default("HABER") }}</span>
    <span class="top">{{ script.header_top }}</span>
    <span class="bot">{{ script.header_bottom }}</span>
  </div>

  <div class="photo">
    <div class="bg-img"></div>
    <div class="vignette"></div>
    <div class="corner">{{ script.category }}</div>
    <div class="yellow">{{ script.photo_overlay }}</div>
  </div>

  <div class="body">{{ body_html|safe }}</div>

  <div class="progress"></div>
  <div class="handle">{{ handle }}</div>

  {% if cta.enabled %}
  <div class="cta">
    {% if cta.show_handle %}<div class="handle-line">{{ handle }}</div>{% endif %}
    <div class="row">
      {% for icon in cta.icons %}<span class="icon">{{ icon }}</span>{% endfor %}
      <span>{{ cta.text }}</span>
    </div>
  </div>
  {% endif %}
</div>
</body>
</html>
```

- [ ] **Step 3: Write failing test**

`tests/test_renderer.py`:
```python
from pathlib import Path

import pytest

from short_bot.models import RenderJob, Script, Highlight
from short_bot.renderer import build_html, render_frames


def _job(tmp_path):
    script = Script(
        header_top="FAİZ ŞOKU", header_bottom="BAŞLADI",
        photo_overlay="250 BAZ PUAN İNDİRİM",
        body_paragraph="Türkiye Cumhuriyet Merkez Bankası faizi 250 baz puan indirdi. Karar piyasada şok yarattı.",
        highlights=[Highlight(text="250 baz puan", color="yellow"),
                    Highlight(text="şok yarattı", color="red")],
        category="EKONOMİ", mood="breaking",
    )
    return RenderJob(
        script=script,
        bg_image_path=None,
        music_path=tmp_path / "fake.mp3",
        channel_colors={"primary": "#c81e1e", "accent": "#ffea3b",
                         "bg_gradient": ["#1a3b6b", "#0a1a3b"]},
        handle="@HaberShortsTR", duration_s=30,
    )


def test_build_html_includes_script_text(tmp_path):
    template = Path("templates/default.html.j2")
    html = build_html(_job(tmp_path), template)
    assert "FAİZ ŞOKU" in html
    assert "BAŞLADI" in html
    assert "EKONOMİ" in html
    assert "@HaberShortsTR" in html
    assert "BEĞEN · ABONE OL · PAYLAŞ" in html


def test_build_html_wraps_highlights(tmp_path):
    template = Path("templates/default.html.j2")
    html = build_html(_job(tmp_path), template)
    assert '<span class="hl-y">250 baz puan</span>' in html
    assert '<span class="hl-r">şok yarattı</span>' in html


def test_build_html_uses_bg_image_when_provided(tmp_path):
    job = _job(tmp_path)
    bg = tmp_path / "bg.jpg"
    bg.write_bytes(b"fake")
    job.bg_image_path = bg
    template = Path("templates/default.html.j2")
    html = build_html(job, template)
    assert "url('file://" in html or "url('/" in html or "url('" in html  # set


@pytest.mark.slow
def test_render_frames_writes_pngs(tmp_path):
    template = Path("templates/default.html.j2")
    job = _job(tmp_path)
    job.duration_s = 2  # minimal: 2s × 30fps = 60 frames
    out_dir = tmp_path / "frames"
    n = render_frames(job, template, out_dir, fps=30, browser="chromium")
    assert n == 60
    pngs = sorted(out_dir.glob("*.png"))
    assert len(pngs) == 60
    # First frame should be ~1080x1920
    from PIL import Image
    with Image.open(pngs[0]) as im:
        assert im.size == (1080, 1920)
```

- [ ] **Step 4: Run quick tests first (skip slow), verify FAIL**

```bash
pytest tests/test_renderer.py -v -m "not slow"
```
Expected: ImportError.

- [ ] **Step 5: Implement `src/short_bot/renderer.py`**

```python
"""HTML render via Jinja2 → frame capture via Playwright."""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from short_bot.models import RenderJob

WIDTH = 1080
HEIGHT = 1920


def _wrap_highlights(paragraph: str, highlights) -> str:
    """Wrap each highlight.text in paragraph with <span class="hl-r/y">. Longest first to avoid partial overlap."""
    out = paragraph
    sorted_hl = sorted(highlights, key=lambda h: -len(h.text))
    for h in sorted_hl:
        cls = "hl-r" if h.color == "red" else "hl-y"
        # Replace only first occurrence (preserves user-visible order)
        out = out.replace(h.text, f'<span class="{cls}">{h.text}</span>', 1)
    return out


def _primary_light(primary_hex: str) -> str:
    """Lighten a hex color by ~15% for header gradient."""
    h = primary_hex.lstrip("#")
    if len(h) != 6:
        return primary_hex
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"#{min(255,r+40):02x}{min(255,g+30):02x}{min(255,b+30):02x}"


def build_html(job: RenderJob, template_path: Path) -> str:
    template_path = Path(template_path)
    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template(template_path.name)

    colors = dict(job.channel_colors)
    colors["primary_light"] = _primary_light(colors["primary"])

    bg_url = None
    if job.bg_image_path is not None:
        bg_url = job.bg_image_path.absolute().as_uri()

    body_html = _wrap_highlights(job.script.body_paragraph, job.script.highlights)

    return template.render(
        script=job.script,
        body_html=body_html,
        bg_image_url=bg_url,
        colors=colors,
        handle=job.handle,
        duration_s=job.duration_s,
        category=job.script.category,
        cta={
            "enabled": job.cta_enabled,
            "text": job.cta_text,
            "icons": job.cta_icons,
            "duration_s": job.cta_duration_s,
            "show_handle": job.cta_show_handle,
        },
    )


def render_frames(
    job: RenderJob,
    template_path: Path,
    out_dir: Path,
    *,
    fps: int = 30,
    browser: str = "chromium",
) -> int:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html = build_html(job, template_path)

    total_frames = job.duration_s * fps

    with sync_playwright() as p:
        browser_obj = getattr(p, browser).launch()
        page = browser_obj.new_page(viewport={"width": WIDTH, "height": HEIGHT},
                                     device_scale_factor=1)
        page.set_content(html, wait_until="networkidle")
        # Pause CSS animations so we can step them via clock
        page.add_init_script("document.getAnimations().forEach(a => a.pause());")

        for i in range(total_frames):
            t_ms = int((i / fps) * 1000)
            page.evaluate(
                "(t) => { document.getAnimations().forEach(a => { a.currentTime = t; }); }",
                t_ms,
            )
            page.screenshot(path=str(out_dir / f"frame_{i:05d}.png"), omit_background=False)

        browser_obj.close()

    return total_frames
```

- [ ] **Step 6: Run fast tests, verify PASS**

```bash
pytest tests/test_renderer.py -v -m "not slow"
```
Expected: 3 passed.

- [ ] **Step 7: Run slow Playwright test, verify PASS**

```bash
pytest tests/test_renderer.py::test_render_frames_writes_pngs -v
```
Expected: 1 passed (~10-30s).

- [ ] **Step 8: Commit**

```bash
git add templates/default.html.j2 src/short_bot/renderer.py tests/test_renderer.py
git commit -m "feat(renderer): Jinja2 template + Playwright frame capture (1080x1920 @ 30fps)"
```

---

## Task 13: Video Composer (FFmpeg)

**Files:**
- Create: `src/short_bot/composer.py`
- Test: `tests/test_composer.py`

- [ ] **Step 1: Verify FFmpeg available**

```bash
ffmpeg -version
```
Expected: ffmpeg version output (any).

- [ ] **Step 2: Write failing test**

`tests/test_composer.py`:
```python
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from short_bot.composer import compose_video


@pytest.fixture
def tiny_frames(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    for i in range(60):  # 2s @ 30fps
        Image.new("RGB", (1080, 1920), (i * 4, 100, 200)).save(frames / f"frame_{i:05d}.png")
    return frames


def test_compose_video_creates_mp4(tmp_path, tiny_frames):
    music = Path(__file__).parent / "fixtures" / "music_sample.mp3"
    out = tmp_path / "out.mp4"
    result = compose_video(tiny_frames, music, out, fps=30, ffmpeg_path="ffmpeg")
    assert result == out
    assert out.exists() and out.stat().st_size > 0


def test_compose_video_duration_matches_frames(tmp_path, tiny_frames):
    music = Path(__file__).parent / "fixtures" / "music_sample.mp3"
    out = tmp_path / "out.mp4"
    compose_video(tiny_frames, music, out, fps=30, ffmpeg_path="ffmpeg")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(out)],
        capture_output=True, text=True, check=True,
    )
    duration = float(probe.stdout.strip())
    assert 1.8 <= duration <= 2.2  # 60 frames / 30fps = 2s
```

- [ ] **Step 3: Run test, verify FAIL**

```bash
pytest tests/test_composer.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `src/short_bot/composer.py`**

```python
"""FFmpeg compose: PNG frames + music → mp4 (H.264, 9:16, AAC)."""
from __future__ import annotations

import subprocess
from pathlib import Path


def compose_video(
    frames_dir: Path,
    music_path: Path,
    out_path: Path,
    *,
    fps: int = 30,
    ffmpeg_path: str = "ffmpeg",
) -> Path:
    frames_dir = Path(frames_dir)
    music_path = Path(music_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not any(frames_dir.glob("frame_*.png")):
        raise FileNotFoundError(f"No frames in {frames_dir}")
    if not music_path.exists():
        raise FileNotFoundError(f"Music not found: {music_path}")

    cmd = [
        ffmpeg_path, "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-i", str(music_path),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",                 # cut audio at video end
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}): {proc.stderr[-1000:]}")
    return out_path
```

- [ ] **Step 5: Run tests, verify PASS**

```bash
pytest tests/test_composer.py -v
```
Expected: 2 passed (~5-15s).

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/composer.py tests/test_composer.py
git commit -m "feat(composer): ffmpeg PNG sequence + audio → H.264 mp4"
```

---

## Task 14: Pipeline Orchestrator

**Files:**
- Create: `src/short_bot/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing test**

`tests/test_pipeline.py`:
```python
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.config import ChannelConfig, Settings
from short_bot.models import NewsItem, ScoredItem, Script, Highlight, RenderJob
from short_bot.pipeline import run_pipeline


def _settings():
    return Settings(
        ffmpeg_path="ffmpeg", claude_cli_path="claude", playwright_browser="chromium",
        web_host="127.0.0.1", web_port=5000,
        fuzzy_dedup_threshold=0.85, log_level="INFO",
    )


def _channel(tmp_path):
    return ChannelConfig(
        slug="test", name="T", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="0 * * * *", duration_s=2, min_score=5.0,
        max_candidates_per_run=10, template="default",
        colors={"primary": "#c81e1e", "accent": "#ffea3b", "bg_gradient": ["#1a3b6b", "#0a1a3b"]},
        handle="@x", output_dir=str(tmp_path / "output"),
        enabled=True, cta_enabled=True, cta_text="A · B · C",
        cta_icons=["❤️", "🔔", "↗️"], cta_duration_s=1, cta_show_handle=True,
    )


def _script():
    return Script(
        header_top="X", header_bottom="Y", photo_overlay="Z",
        body_paragraph="Türkiye Cumhuriyet Merkez Bankası faizi indirdi. Karar şok yarattı.",
        highlights=[Highlight(text="şok yarattı", color="red")],
        category="EKONOMİ", mood="breaking",
    )


def test_pipeline_happy_path(tmp_path):
    item = NewsItem(guid="g1", title="Faiz indirimi", link="http://x", source="S",
                    pub_date=datetime(2026, 5, 5), thumb_url=None, description="d")
    settings = _settings()
    channel = _channel(tmp_path)
    db_path = tmp_path / "db.sqlite"
    music_root = tmp_path / "music"
    (music_root / "breaking").mkdir(parents=True)
    src_music = Path(__file__).parent / "fixtures" / "music_sample.mp3"
    (music_root / "breaking" / "a.mp3").write_bytes(src_music.read_bytes())

    def fake_compose(frames_dir, music_path, out_path, **kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"fake mp4 bytes")
        return Path(out_path)

    with patch("short_bot.pipeline.fetch_rss", return_value=[item]), \
         patch("short_bot.pipeline.score_items",
               return_value=[ScoredItem(item=item, score=9.0, reasoning="ok")]), \
         patch("short_bot.pipeline.extract_article", return_value="Tam makale gövdesi"), \
         patch("short_bot.pipeline.write_script", return_value=_script()), \
         patch("short_bot.pipeline.download_and_blur_thumb", return_value=None), \
         patch("short_bot.pipeline.render_frames", return_value=60), \
         patch("short_bot.pipeline.compose_video", side_effect=fake_compose):
        result = run_pipeline(
            channel=channel, settings=settings,
            db_path=db_path, music_root=music_root,
            templates_dir=Path("templates"), cache_dir=tmp_path / "cache",
            logs_dir=tmp_path / "logs", lock_dir=tmp_path / "locks",
            trigger="cli",
        )

    assert result.status == "success"
    assert result.short_path is not None
    assert result.short_path.exists()
    assert result.short_path.suffix == ".mp4"
    assert "test" in result.short_path.parent.name  # channel slug in path


def test_pipeline_no_candidates(tmp_path):
    settings = _settings()
    channel = _channel(tmp_path)
    db_path = tmp_path / "db.sqlite"

    with patch("short_bot.pipeline.fetch_rss", return_value=[]):
        result = run_pipeline(
            channel=channel, settings=settings,
            db_path=db_path, music_root=tmp_path / "music",
            templates_dir=Path("templates"), cache_dir=tmp_path / "cache",
            logs_dir=tmp_path / "logs", lock_dir=tmp_path / "locks",
            trigger="cli",
        )
    assert result.status == "no_candidates"


def test_pipeline_records_failure_on_render_error(tmp_path):
    item = NewsItem(guid="g1", title="X", link="http://x", source=None,
                    pub_date=None, thumb_url=None, description=None)
    settings = _settings()
    channel = _channel(tmp_path)
    db_path = tmp_path / "db.sqlite"
    music_root = tmp_path / "music"
    (music_root / "breaking").mkdir(parents=True)
    (music_root / "breaking" / "a.mp3").write_bytes(b"fake")

    with patch("short_bot.pipeline.fetch_rss", return_value=[item]), \
         patch("short_bot.pipeline.score_items",
               return_value=[ScoredItem(item=item, score=9.0, reasoning="ok")]), \
         patch("short_bot.pipeline.extract_article", return_value="body"), \
         patch("short_bot.pipeline.write_script", return_value=_script()), \
         patch("short_bot.pipeline.download_and_blur_thumb", return_value=None), \
         patch("short_bot.pipeline.render_frames", side_effect=RuntimeError("crash")):
        result = run_pipeline(
            channel=channel, settings=settings,
            db_path=db_path, music_root=music_root,
            templates_dir=Path("templates"), cache_dir=tmp_path / "cache",
            logs_dir=tmp_path / "logs", lock_dir=tmp_path / "locks",
            trigger="cli",
        )
    assert result.status == "failed"
    assert "crash" in result.error
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
pytest tests/test_pipeline.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/short_bot/pipeline.py`**

```python
"""Pipeline orchestrator: runs all 8 stages, persists to DB, writes per-run log."""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from filelock import FileLock, Timeout

from short_bot.config import ChannelConfig, Settings
from short_bot.db import (
    init_db, mark_processed, record_short, record_rss_item,
    start_run, finish_run,
)
from short_bot.models import RenderJob
from short_bot.fetcher import fetch_rss
from short_bot.dedup import filter_new
from short_bot.scorer import score_items, select_top
from short_bot.extractor import extract_article
from short_bot.script_writer import write_script
from short_bot.assets import download_and_blur_thumb, pick_music
from short_bot.renderer import render_frames
from short_bot.composer import compose_video


@dataclass
class RunResult:
    run_id: int
    status: str           # 'success' | 'failed' | 'no_candidates'
    short_path: Path | None
    error: str | None


def _slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len] or "haber"


def _setup_logger(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"shortbot.run.{log_path.stem}")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(sh)
    return logger


def run_pipeline(
    *,
    channel: ChannelConfig,
    settings: Settings,
    db_path: Path,
    music_root: Path,
    templates_dir: Path,
    cache_dir: Path,
    logs_dir: Path,
    lock_dir: Path | None = None,
    trigger: str = "cli",
) -> RunResult:
    eng = init_db(db_path)
    log_path = logs_dir / f"{datetime.utcnow():%Y%m%d_%H%M%S}_{channel.slug}.log"
    log_rel = str(log_path)
    log = _setup_logger(log_path)
    run_id = start_run(eng, channel.slug, trigger=trigger, log_path=log_rel)

    lock_dir = Path(lock_dir) if lock_dir else Path("data/locks")
    lock_path = lock_dir / f"{channel.slug}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_path), timeout=0)

    try:
        with lock:
            log.info(f"=== run {run_id} channel={channel.slug} trigger={trigger} ===")

            log.info("[1/8] fetch_rss")
            items = fetch_rss(channel.keywords, channel.rss_locale)
            log.info(f"  → {len(items)} items")

            log.info("[2/8] dedup")
            new_items = filter_new(eng, items, channel.slug,
                                    fuzzy_threshold=settings.fuzzy_dedup_threshold)
            log.info(f"  → {len(new_items)} new")
            for old in items:
                if old not in new_items:
                    record_rss_item(eng, guid=old.guid, channel=channel.slug,
                                    title=old.title, link=old.link, source=old.source,
                                    pub_date=old.pub_date, thumb_url=old.thumb_url,
                                    score=None, status="duplicate")

            if not new_items:
                log.info("no candidates → finish")
                finish_run(eng, run_id, status="no_candidates", short_id=None, error=None)
                return RunResult(run_id=run_id, status="no_candidates", short_path=None, error=None)

            log.info("[3/8] score_items")
            candidates = new_items[:channel.max_candidates_per_run]
            scored = score_items(candidates, claude_path=settings.claude_cli_path)
            for s in scored:
                record_rss_item(eng, guid=s.item.guid, channel=channel.slug,
                                title=s.item.title, link=s.item.link, source=s.item.source,
                                pub_date=s.item.pub_date, thumb_url=s.item.thumb_url,
                                score=s.score, status="below_threshold")
            top = select_top(scored, min_score=channel.min_score, n=1)
            if not top:
                log.info(f"no item ≥ {channel.min_score} → finish")
                finish_run(eng, run_id, status="no_candidates", short_id=None, error=None)
                return RunResult(run_id=run_id, status="no_candidates", short_path=None, error=None)
            picked = top[0]
            log.info(f"  → picked {picked.item.guid} (score={picked.score})")

            log.info("[4/8] extract_article")
            body = extract_article(picked.item.link)
            if body is None:
                body = picked.item.description or picked.item.title
                log.warning("  trafilatura empty → fallback description")
            log.info(f"  → body {len(body)} chars")

            log.info("[5/8] write_script")
            script = write_script(picked.item, body, claude_path=settings.claude_cli_path)
            log.info(f"  → {script.header_top} | {script.header_bottom}")

            log.info("[6/8] assets")
            bg = None
            if picked.item.thumb_url:
                bg = download_and_blur_thumb(picked.item.thumb_url, cache_dir)
            music = pick_music(music_root, mood=script.mood)
            log.info(f"  → bg={'cached' if bg else 'none'} music={music.name}")

            log.info("[7/8] render_frames")
            job = RenderJob(
                script=script,
                bg_image_path=bg,
                music_path=music,
                channel_colors=channel.colors,
                handle=channel.handle,
                duration_s=channel.duration_s,
                cta_enabled=channel.cta_enabled,
                cta_text=channel.cta_text,
                cta_icons=channel.cta_icons,
                cta_duration_s=channel.cta_duration_s,
                cta_show_handle=channel.cta_show_handle,
            )

            with tempfile.TemporaryDirectory() as tmpd:
                frames_dir = Path(tmpd) / "frames"
                t0 = time.perf_counter()
                template_path = templates_dir / f"{channel.template}.html.j2"
                render_frames(job, template_path, frames_dir,
                              fps=30, browser=settings.playwright_browser)

                log.info("[8/8] compose_video")
                out_dir = Path(channel.output_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                slug = _slugify(picked.item.title)
                out_path = out_dir / f"{datetime.utcnow():%Y-%m-%d}_{slug}.mp4"
                compose_video(frames_dir, music, out_path,
                              fps=30, ffmpeg_path=settings.ffmpeg_path)
                render_ms = int((time.perf_counter() - t0) * 1000)
                log.info(f"  → {out_path.name} ({render_ms}ms)")

            mark_processed(eng, picked.item.guid, picked.item.title, channel.slug)
            short_id = record_short(eng,
                channel=channel.slug, rss_item_guid=picked.item.guid,
                title=script.header_top + " " + script.header_bottom,
                file_path=str(out_path), duration_s=channel.duration_s,
                script_json=script.model_dump_json(), render_ms=render_ms,
            )
            record_rss_item(eng, guid=picked.item.guid, channel=channel.slug,
                            title=picked.item.title, link=picked.item.link,
                            source=picked.item.source, pub_date=picked.item.pub_date,
                            thumb_url=picked.item.thumb_url,
                            score=picked.score, status="selected")
            finish_run(eng, run_id, status="success", short_id=short_id, error=None)
            log.info(f"=== success short_id={short_id} ===")
            return RunResult(run_id=run_id, status="success", short_path=out_path, error=None)

    except Timeout:
        finish_run(eng, run_id, status="failed", short_id=None,
                   error="lock busy: pipeline already running for this channel")
        return RunResult(run_id=run_id, status="failed", short_path=None,
                         error="lock busy")
    except Exception as e:
        log.exception("pipeline failed")
        finish_run(eng, run_id, status="failed", short_id=None, error=str(e))
        return RunResult(run_id=run_id, status="failed", short_path=None, error=str(e))
```

- [ ] **Step 4: Run tests, verify PASS**

```bash
pytest tests/test_pipeline.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): orchestrator with per-run log, file lock, DB persistence"
```

---

## Task 15: CLI Entry Point

**Files:**
- Create: `src/short_bot/cli.py`, `src/short_bot/__main__.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing test**

`tests/test_cli.py`:
```python
import subprocess
import sys

import pytest


def test_module_invocation_prints_help():
    result = subprocess.run(
        [sys.executable, "-m", "short_bot", "--help"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0
    assert "run" in result.stdout
    assert "init" in result.stdout
    assert "list-channels" in result.stdout


def test_list_channels_subcommand(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    chans = tmp_path / "config" / "channels"
    chans.mkdir(parents=True)
    (chans / "demo.yaml").write_text(
        "slug: demo\nname: D\nkeywords: [x]\nrss_locale: hl=tr\n"
        "schedule_cron: '0 * * * *'\nduration_s: 30\nmin_score: 5\n"
        "max_candidates_per_run: 10\ntemplate: default\n"
        "colors: {primary: '#c81e1e', accent: '#ffea3b', bg_gradient: ['#1a3b6b', '#0a1a3b']}\n"
        "handle: '@d'\noutput_dir: output/demo\nenabled: true\n"
        "cta: {enabled: true, text: 'a', icons: ['x'], duration_s: 4, show_handle: true}\n",
        encoding="utf-8",
    )
    settings = tmp_path / "config" / "settings.yaml"
    settings.write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5000}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "short_bot", "list-channels"],
        capture_output=True, text=True, encoding="utf-8", cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "demo" in result.stdout
```

- [ ] **Step 2: Run test, verify FAIL**

```bash
pytest tests/test_cli.py -v
```
Expected: returncode != 0 (no entry point yet).

- [ ] **Step 3: Implement `src/short_bot/__main__.py`**

```python
from short_bot.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Implement `src/short_bot/cli.py`**

```python
"""CLI: `python -m short_bot {init,run,list-channels}`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from short_bot.config import load_settings, load_channel, list_channels as list_chans
from short_bot.db import init_db
from short_bot.pipeline import run_pipeline


def _add_run(sub):
    p = sub.add_parser("run", help="Run pipeline for a channel")
    p.add_argument("--channel", required=True, help="Channel slug")
    p.add_argument("--max", type=int, default=1, help="Max shorts per run (default 1)")
    p.add_argument("--config-dir", default="config", help="Config root (default ./config)")
    p.add_argument("--data-dir", default="data", help="Data root (SQLite, cache, locks)")
    p.add_argument("--music-root", default="assets/music")
    p.add_argument("--templates-dir", default="templates")
    p.add_argument("--logs-dir", default="logs/runs")
    p.set_defaults(func=_cmd_run)


def _add_init(sub):
    p = sub.add_parser("init", help="Create SQLite schema")
    p.add_argument("--db-path", default="data/short_bot.sqlite")
    p.set_defaults(func=_cmd_init)


def _add_list(sub):
    p = sub.add_parser("list-channels", help="List configured channels")
    p.add_argument("--config-dir", default="config")
    p.add_argument("--enabled-only", action="store_true")
    p.set_defaults(func=_cmd_list)


def _cmd_init(args) -> int:
    init_db(Path(args.db_path))
    print(f"DB initialized: {args.db_path}")
    return 0


def _cmd_list(args) -> int:
    chans = list_chans(Path(args.config_dir) / "channels", enabled_only=args.enabled_only)
    if not chans:
        print("(no channels)")
        return 0
    print(f"{'slug':<20} {'name':<24} {'enabled':<8} cron")
    print("-" * 70)
    for c in chans:
        print(f"{c.slug:<20} {c.name:<24} {str(c.enabled):<8} {c.schedule_cron}")
    return 0


def _cmd_run(args) -> int:
    config_dir = Path(args.config_dir)
    settings = load_settings(config_dir / "settings.yaml")
    channel = load_channel(config_dir / "channels" / f"{args.channel}.yaml")

    data_dir = Path(args.data_dir)
    db_path = data_dir / "short_bot.sqlite"

    for i in range(args.max):
        print(f"--- run {i+1}/{args.max} ---")
        result = run_pipeline(
            channel=channel,
            settings=settings,
            db_path=db_path,
            music_root=Path(args.music_root),
            templates_dir=Path(args.templates_dir),
            cache_dir=data_dir / "cache",
            lock_dir=data_dir / "locks",
            logs_dir=Path(args.logs_dir),
            trigger="cli",
        )
        print(f"status={result.status} short={result.short_path} error={result.error}")
        if result.status != "success":
            return 1 if result.status == "failed" else 0
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="short-bot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    _add_run(sub)
    _add_init(sub)
    _add_list(sub)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests, verify PASS**

```bash
pytest tests/test_cli.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/short_bot/cli.py src/short_bot/__main__.py tests/test_cli.py
git commit -m "feat(cli): argparse entry point (run/init/list-channels)"
```

---

## Task 16: First Manual Smoke Run + README polish

**Files:**
- Modify: `README.md` (add detailed first-run walkthrough)
- (No new code; this validates the full system end-to-end with real services)

- [ ] **Step 1: Run all unit tests one final time**

```bash
pytest -v
```
Expected: All previous tests pass (no regressions).

- [ ] **Step 2: Place real music files**

The user must add at least one MP3 to `assets/music/breaking/`. For initial testing, copy the sample fixture:

```bash
cp tests/fixtures/music_sample.mp3 assets/music/breaking/test.mp3
cp tests/fixtures/music_sample.mp3 assets/music/neutral/test.mp3
```
(Replace with real music later — these are 1-second silent stubs.)

- [ ] **Step 3: Initialize DB**

```bash
python -m short_bot init
```
Expected: `DB initialized: data/short_bot.sqlite`

- [ ] **Step 4: List channels**

```bash
python -m short_bot list-channels
```
Expected: `son-dakika` row visible.

- [ ] **Step 5: Run real end-to-end** (requires `claude` CLI logged in + internet)

```bash
python -m short_bot run --channel son-dakika --max 1
```
Expected output ends with `status=success short=output\son-dakika\<date>_<slug>.mp4`.

If it fails: check `logs/runs/<timestamp>_son-dakika.log` — common issues:
- `claude` CLI not on PATH → fix `config/settings.yaml` `claude_cli_path`
- `ffmpeg` not on PATH → fix `ffmpeg_path`
- `pick_music` FileNotFoundError → ensure `assets/music/breaking/*.mp3` exists
- Playwright timeout → re-run `playwright install chromium`

- [ ] **Step 6: Open the produced mp4 and verify visually**

Manual acceptance criteria (from spec §11):
- [ ] Yazı okunabilir, Türkçe diakritik tam (ç, ğ, ı, ö, ş, ü)
- [ ] Müzik bitişik kesilmiyor
- [ ] Fotoğraf veya gradient görünüyor
- [ ] Highlight'lar doğru renklerde (kırmızı/sarı)
- [ ] Son 4 saniyede CTA bandı (beğen/abone ol/paylaş) düzgün animasyonla görünür

If any criterion fails → file an issue and add a regression test.

- [ ] **Step 7: Update `README.md` with first-run walkthrough**

Replace the existing "İlk Çalıştırma" section with:

```markdown
## İlk Çalıştırma

### 1. Müzik dosyaları

`assets/music/{breaking,neutral,upbeat}/` klasörlerine **en az birer mp3** koyun.
Başlangıç için YouTube Audio Library'den 5-10 telifsiz parça indirin.

### 2. DB init

```bash
python -m short_bot init
```

### 3. Kanalları listele

```bash
python -m short_bot list-channels
```

### 4. İlk Short'u üret

```bash
python -m short_bot run --channel son-dakika --max 1
```

Çıktı: `output/son-dakika/<tarih>_<slug>.mp4`

Loglar: `logs/runs/<tarih>_<slug>.log`

### Sorun giderme

| Hata | Çözüm |
|---|---|
| `claude: command not found` | `config/settings.yaml` → `claude_cli_path: "C:\\path\\to\\claude.exe"` |
| `ffmpeg: command not found` | `ffmpeg`'i PATH'e ekleyin veya `ffmpeg_path` ayarlayın |
| `Mood 'breaking' için müzik bulunamadı` | `assets/music/breaking/` klasörüne mp3 koyun |
| `Playwright timeout` | `playwright install chromium` çalıştırın |
| Render uzun sürüyor | Normal: 30s short → 30-90s render (ilk koşumda Playwright cold-start) |
```

- [ ] **Step 8: Commit**

```bash
git add README.md
git commit -m "docs: detailed first-run walkthrough + troubleshooting"
```

- [ ] **Step 9 (final): Push or tag MVP**

```bash
git tag -a v0.1.0-pipeline -m "Phase 1 complete: pipeline + CLI"
git log --oneline | head -20
```

---

## Phase 1 Complete

**What works:**
- `python -m short_bot run --channel son-dakika` produces a 30s mp4 end-to-end
- 16 unit/integration tests cover every module
- Persistence: SQLite tracks dedup, runs, shorts, RSS items
- Per-channel file lock prevents concurrent runs
- Per-run log file for forensics

**Phase 2 (separate plan):** Web panel (Flask + HTMX) — Dashboard, Shorts gallery with video player, RSS table, channel editor, log viewer, APScheduler integration.
