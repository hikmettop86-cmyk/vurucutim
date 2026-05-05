# Channel DNA + Multi-Language Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-channel visual + content "DNA" (7 archetypes + LLM-generated CSS overrides + tone-of-voice + 5-language support) so multiple channels are visually distinguishable instead of sharing one template.

**Architecture:** 7 hand-curated archetype templates (newscast/tabloid/magazine/kinetic/dark-tech/stadium/meme) + per-channel CSS override generated deterministically from a `DnaSpec` (Pydantic model written by Claude Opus once at channel creation). Multi-language via `locale.py` dictionaries (RSS_LOCALES, UI_LABELS, LANGUAGE_NAMES). Script writer + image picker + renderer all become channel-aware, picking template/CSS/labels/prompt-instruction by channel's archetype + language.

**Tech Stack:** Python 3.11+, Pydantic 2, Jinja2, Playwright (chromium), claude CLI (subprocess; `--model opus|haiku`), pytest.

**Spec reference:** `docs/superpowers/specs/2026-05-05-channel-dna-design.md`

**Phase 1 status:** complete (`v0.1.0-pipeline` tag, 86+ tests). This plan adds on top.

---

## File Structure

**New files (created by this plan):**
```
src/short_bot/
├── locale.py                # RSS_LOCALES, LANGUAGE_NAMES, UI_LABELS
└── dna.py                   # DnaSpec models + generate_dna + build_css_override

templates/
├── newscast.html.j2         # rename of default.html.j2
├── tabloid.html.j2          # NEW
├── magazine.html.j2         # NEW
├── kinetic.html.j2          # NEW
├── dark-tech.html.j2        # NEW
├── stadium.html.j2          # NEW
├── meme.html.j2             # NEW
└── css/
    └── <slug>.css           # generated per channel by build_css_override

tests/
├── test_locale.py
├── test_dna.py
├── test_cli_create_channel.py
└── fixtures/snapshots/
    ├── newscast.png         # snapshot tests for renderer
    ├── tabloid.png
    └── ...                  # 7 snapshots
```

**Modified files:**
- `src/short_bot/claude_cli.py` — add `--model` flag
- `src/short_bot/config.py` — `Settings.claude_models`, `ChannelConfig.{language, template, dna, script_model}`, validator, `save_channel` extension, backward-compat loader
- `src/short_bot/fetcher.py` — `fetch_rss(keywords, language)` (locale auto-derive)
- `src/short_bot/script_writer.py` — `ARCHETYPE_PROMPTS` dict, `build_script_prompt(item, body, channel)` channel-aware
- `src/short_bot/image_picker.py` — `build_search_query(script, channel)` template-driven
- `src/short_bot/renderer.py` — `RenderJob.language`, `build_html(..., ui_labels, dna_css)`
- `src/short_bot/pipeline.py` — pass language/dna/ui_labels/dna_css through
- `src/short_bot/cli.py` — `create-channel`, `regenerate-dna`, `rebuild-css`, `migrate-channel` subcommands
- `config/settings.yaml` — `claude_models` block
- `config/channels/son-dakika.yaml` — schema migration
- `templates/default.html.j2` — renamed to `newscast.html.j2`

**Total: 23 tasks.** TDD per task: failing test → impl → passing test → commit.

---

## Task 1: claude_cli --model flag + Settings.claude_models

**Files:**
- Modify: `src/short_bot/claude_cli.py`
- Modify: `src/short_bot/config.py` (Settings dataclass)
- Test: `tests/test_claude_cli.py`, `tests/test_config.py`

- [ ] **Step 1: Write failing test (`tests/test_claude_cli.py`, append)**

```python
def test_run_json_passes_model_flag():
    payload = {"score": 7.0, "why": "ok"}
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _fake_proc(json.dumps(payload))

    with patch("short_bot.claude_cli.subprocess.run", side_effect=fake_run):
        run_json("p", _Out, claude_path="claude", model="opus", retries=1)
    assert "--model" in captured["cmd"]
    assert "opus" in captured["cmd"]


def test_run_json_default_model_omits_flag():
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _fake_proc(json.dumps({"score": 5, "why": "x"}))

    with patch("short_bot.claude_cli.subprocess.run", side_effect=fake_run):
        run_json("p", _Out, claude_path="claude", model="default", retries=1)
    assert "--model" not in captured["cmd"]
```

- [ ] **Step 2: Run, expect FAIL**

```bash
python -m pytest tests/test_claude_cli.py::test_run_json_passes_model_flag -v
```
Expected: FAIL — `model` is not a parameter of `run_json`.

- [ ] **Step 3: Implement (`src/short_bot/claude_cli.py`)**

Find `def run_json(...)` signature and update to:

```python
def run_json(
    prompt: str,
    schema: type[T],
    *,
    claude_path: str = "claude",
    model: str = "default",
    retries: int = 2,
    timeout_s: int = 90,
) -> T:
```

In the function body, find the line:
```python
            proc = subprocess.run(
                [claude_path, "-p", prompt, "--output-format", "text"],
```

Replace with:
```python
            cmd = [claude_path, "-p", prompt, "--output-format", "text"]
            if model != "default":
                cmd += ["--model", model]
            proc = subprocess.run(
                cmd,
```

Update the docstring `Args:` section to mention `model`.

- [ ] **Step 4: Run, expect PASS**

```bash
python -m pytest tests/test_claude_cli.py -v
```
Expected: 9 passed (7 existing + 2 new).

- [ ] **Step 5: Add Settings.claude_models field**

Edit `src/short_bot/config.py`. Add to `Settings` dataclass:

```python
@dataclass(frozen=True)
class Settings:
    ffmpeg_path: str
    claude_cli_path: str
    playwright_browser: str
    web_host: str
    web_port: int
    fuzzy_dedup_threshold: float
    log_level: str
    claude_models: dict           # NEW: {"dna": "opus", "default": "haiku"}
```

Update `load_settings()`:

Find:
```python
    return Settings(
        ffmpeg_path=data["ffmpeg_path"],
        ...
        log_level=data.get("log_level", "INFO"),
    )
```

Replace with:
```python
    return Settings(
        ffmpeg_path=data["ffmpeg_path"],
        claude_cli_path=data["claude_cli_path"],
        playwright_browser=data.get("playwright_browser", "chromium"),
        web_host=web.get("host", "127.0.0.1"),
        web_port=int(web.get("port", 5000)),
        fuzzy_dedup_threshold=float(data.get("fuzzy_dedup_threshold", 0.85)),
        log_level=data.get("log_level", "INFO"),
        claude_models=dict(data.get("claude_models", {"dna": "opus", "default": "haiku"})),
    )
```

- [ ] **Step 6: Add test for Settings.claude_models default**

Append to `tests/test_config.py`:

```python
def test_load_settings_default_claude_models(tmp_path):
    (tmp_path / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5000}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n",
        encoding="utf-8",
    )
    s = load_settings(tmp_path / "settings.yaml")
    assert s.claude_models == {"dna": "opus", "default": "haiku"}


def test_load_settings_custom_claude_models(tmp_path):
    (tmp_path / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5000}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: sonnet\n",
        encoding="utf-8",
    )
    s = load_settings(tmp_path / "settings.yaml")
    assert s.claude_models["default"] == "sonnet"
```

Update existing `test_load_settings` (the one that builds a custom settings with all required fields) — add `claude_models` if it explicitly checks all Settings fields. (Look at the existing test; if it just checks a subset, no change needed.)

- [ ] **Step 7: Update `config/settings.yaml`**

Read the current file, append at the end:

```yaml
claude_models:
  dna: opus              # creative, 1× per channel
  default: haiku         # scoring, script, image verify
```

- [ ] **Step 8: Run all tests, expect PASS**

```bash
python -m pytest -v
```
Expected: 88+ passed (86 existing + 2 new claude_cli + 2 new config).

- [ ] **Step 9: Commit**

```bash
git add src/short_bot/claude_cli.py src/short_bot/config.py config/settings.yaml tests/test_claude_cli.py tests/test_config.py
git commit -m "feat(claude_cli): --model flag + Settings.claude_models config"
```

---

## Task 2: locale.py module

**Files:**
- Create: `src/short_bot/locale.py`
- Test: `tests/test_locale.py`

- [ ] **Step 1: Write failing test (`tests/test_locale.py`)**

```python
import pytest

from short_bot.locale import (
    RSS_LOCALES, LANGUAGE_NAMES, UI_LABELS, SUPPORTED_LANGUAGES,
    rss_locale_for, ui_labels_for, language_name,
)


def test_supported_languages_set():
    assert SUPPORTED_LANGUAGES == ["tr", "en", "de", "es", "fr"]


def test_rss_locales_cover_all_languages():
    for lang in SUPPORTED_LANGUAGES:
        assert lang in RSS_LOCALES
        loc = RSS_LOCALES[lang]
        assert "hl=" in loc and "ceid=" in loc


def test_ui_labels_cover_all_languages_with_4_keys():
    expected_keys = {"like", "subscribe", "share", "breaking"}
    for lang in SUPPORTED_LANGUAGES:
        assert lang in UI_LABELS
        assert set(UI_LABELS[lang].keys()) == expected_keys


def test_language_names_cover_all_languages():
    for lang in SUPPORTED_LANGUAGES:
        assert lang in LANGUAGE_NAMES
        assert len(LANGUAGE_NAMES[lang]) >= 2


def test_rss_locale_for_helper():
    assert rss_locale_for("tr") == RSS_LOCALES["tr"]
    with pytest.raises(KeyError):
        rss_locale_for("xx")


def test_ui_labels_for_helper():
    labels = ui_labels_for("de")
    assert labels["subscribe"] == "ABONNIEREN"


def test_language_name_helper():
    assert language_name("fr") == "Français"
```

- [ ] **Step 2: Run, expect FAIL**

```bash
python -m pytest tests/test_locale.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement (`src/short_bot/locale.py`)**

```python
"""Locale dictionaries: RSS URL hints + UI labels + prompt language names.

Multi-language support for short-bot. Each language maps to:
- An RSS URL fragment (hl/gl/ceid params for Google News)
- A human-readable language name (used in LLM prompts)
- A small UI vocabulary (BEĞEN/SUBSCRIBE/SHARE/BREAKING)
"""
from __future__ import annotations

SUPPORTED_LANGUAGES = ["tr", "en", "de", "es", "fr"]


RSS_LOCALES: dict[str, str] = {
    "tr": "hl=tr&gl=TR&ceid=TR:tr",
    "en": "hl=en-US&gl=US&ceid=US:en",
    "de": "hl=de&gl=DE&ceid=DE:de",
    "es": "hl=es&gl=ES&ceid=ES:es",
    "fr": "hl=fr&gl=FR&ceid=FR:fr",
}


LANGUAGE_NAMES: dict[str, str] = {
    "tr": "Türkçe",
    "en": "English",
    "de": "Deutsch",
    "es": "Español",
    "fr": "Français",
}


UI_LABELS: dict[str, dict[str, str]] = {
    "tr": {"like": "BEĞEN",       "subscribe": "ABONE OL",   "share": "PAYLAŞ",   "breaking": "SON DAKİKA"},
    "en": {"like": "LIKE",        "subscribe": "SUBSCRIBE",  "share": "SHARE",    "breaking": "BREAKING"},
    "de": {"like": "GEFÄLLT MIR", "subscribe": "ABONNIEREN", "share": "TEILEN",   "breaking": "EILMELDUNG"},
    "es": {"like": "ME GUSTA",    "subscribe": "SUSCRIBIRSE","share": "COMPARTIR","breaking": "ÚLTIMA HORA"},
    "fr": {"like": "J'AIME",      "subscribe": "S'ABONNER",  "share": "PARTAGER", "breaking": "DERNIÈRE MINUTE"},
}


def rss_locale_for(language: str) -> str:
    """Return the Google News RSS URL fragment for `language`. Raises KeyError if unknown."""
    return RSS_LOCALES[language]


def ui_labels_for(language: str) -> dict[str, str]:
    """Return the UI label dict for `language`. Raises KeyError if unknown."""
    return UI_LABELS[language]


def language_name(language: str) -> str:
    """Return the human-readable language name (e.g. 'Türkçe' for 'tr'). Raises KeyError."""
    return LANGUAGE_NAMES[language]
```

- [ ] **Step 4: Run, expect PASS**

```bash
python -m pytest tests/test_locale.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/locale.py tests/test_locale.py
git commit -m "feat(locale): RSS_LOCALES + UI_LABELS + LANGUAGE_NAMES for 5 languages"
```

---

## Task 3: ChannelConfig.language with rss_locale auto-derive (backward-compat)

**Files:**
- Modify: `src/short_bot/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests (`tests/test_config.py`, append)**

```python
def test_load_channel_with_language_field(tmp_path):
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nkeywords: [a]\nlanguage: de\n"
        "schedule_cron: '0 * * * *'\nduration_s: 30\nmin_score: 8.0\n"
        "max_candidates_per_run: 30\ntemplate: newscast\n"
        "colors:\n  primary: '#c81e1e'\n  accent: '#ffea3b'\n  bg_gradient: ['#1a3b6b', '#0a1a3b']\n"
        "handle: '@x'\noutput_dir: output/test\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.language == "de"
    # rss_locale field auto-derived from language
    assert c.rss_locale == "hl=de&gl=DE&ceid=DE:de"


def test_load_channel_backward_compat_rss_locale_only(tmp_path):
    """Legacy YAML with rss_locale but no language field should still work."""
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nkeywords: [a]\nrss_locale: hl=tr&gl=TR&ceid=TR:tr\n"
        "schedule_cron: '0 * * * *'\nduration_s: 30\nmin_score: 8.0\n"
        "max_candidates_per_run: 30\ntemplate: default\n"
        "colors:\n  primary: '#c81e1e'\n  accent: '#ffea3b'\n  bg_gradient: ['#1a3b6b', '#0a1a3b']\n"
        "handle: '@x'\noutput_dir: output/test\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.language == "tr"  # default when not set
    assert c.rss_locale == "hl=tr&gl=TR&ceid=TR:tr"


def test_load_channel_invalid_language_raises(tmp_path):
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nkeywords: []\nlanguage: xx\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: newscast\n"
        "colors: {primary: '#000', accent: '#fff', bg_gradient: ['#0','#1']}\n"
        "handle: '@x'\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="language"):
        load_channel(tmp_path / "ch.yaml")
```

- [ ] **Step 2: Run, expect FAIL**

```bash
python -m pytest tests/test_config.py::test_load_channel_with_language_field -v
```
Expected: FAIL — `language` attribute doesn't exist.

- [ ] **Step 3: Implement — modify `src/short_bot/config.py`**

Add import at the top:
```python
from short_bot.locale import RSS_LOCALES, SUPPORTED_LANGUAGES
```

Update `ChannelConfig` dataclass — add `language` and keep `rss_locale` (now possibly auto-derived):

```python
@dataclass(frozen=True)
class ChannelConfig:
    slug: str
    name: str
    keywords: list[str]
    rss_locale: str          # auto-derived from language if not in YAML; legacy YAMLs may set explicitly
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
    language: str = "tr"     # NEW; default 'tr' for backward-compat
```

Update `load_channel()`. Find the slug-validation block (right after `data = yaml.safe_load(...)`). After slug validation, add language resolution BEFORE constructing `ChannelConfig`:

```python
    # Resolve language (with backward-compat for legacy rss_locale-only YAMLs)
    language = data.get("language", "tr")
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language '{language}': must be one of {SUPPORTED_LANGUAGES}"
        )
    rss_locale = data.get("rss_locale") or RSS_LOCALES[language]
```

In the `ChannelConfig(...)` constructor call, replace `rss_locale=data["rss_locale"]` with `rss_locale=rss_locale` and add `language=language`.

Also update `save_channel()` to write `language` field (and STOP writing `rss_locale` since it's auto-derived):

Find in `save_channel()`:
```python
        "rss_locale": cfg.rss_locale,
```

Replace with:
```python
        "language": cfg.language,
```

Update the existing `test_load_channel` test to include `language: tr` in its YAML and the channel-edit YAML in `test_save_channel_round_trips`. (Read those tests first to find the YAML strings; add `"language: tr\n"` in both.)

- [ ] **Step 4: Run all config tests, expect PASS**

```bash
python -m pytest tests/test_config.py -v
```
Expected: 13+ passed (existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/config.py tests/test_config.py
git commit -m "feat(config): ChannelConfig.language field + rss_locale auto-derive (backward-compat)"
```

---

## Task 4: dna.py — DnaSpec Pydantic models

**Files:**
- Create: `src/short_bot/dna.py`
- Test: `tests/test_dna.py`

- [ ] **Step 1: Write failing tests (`tests/test_dna.py`)**

```python
import pytest
from pydantic import ValidationError

from short_bot.dna import (
    ARCHETYPES, DnaSpec, DnaPalette, DnaFonts, DnaTone,
)


def test_archetypes_list_has_seven():
    assert len(ARCHETYPES) == 7
    assert "newscast" in ARCHETYPES
    assert "tabloid" in ARCHETYPES
    assert "magazine" in ARCHETYPES
    assert "kinetic" in ARCHETYPES
    assert "dark-tech" in ARCHETYPES
    assert "stadium" in ARCHETYPES
    assert "meme" in ARCHETYPES


def test_palette_validates_hex():
    DnaPalette(primary="#c81e1e", accent="#ffea3b",
               bg_gradient=["#1a3b6b", "#0a1a3b"], body_bg=["#1a1a2a", "#0a0a1a"])
    with pytest.raises(ValidationError):
        DnaPalette(primary="red", accent="#ffea3b",
                   bg_gradient=["#000","#111"], body_bg=["#000","#111"])
    with pytest.raises(ValidationError):
        DnaPalette(primary="#cc", accent="#ffea3b",  # too short
                   bg_gradient=["#000","#111"], body_bg=["#000","#111"])


def test_palette_normalizes_hex_to_lowercase():
    p = DnaPalette(primary="#C81E1E", accent="#FFEA3B",
                   bg_gradient=["#000000","#111111"], body_bg=["#000000","#111111"])
    assert p.primary == "#c81e1e"
    assert p.accent == "#ffea3b"


def test_palette_gradient_must_have_two_entries():
    with pytest.raises(ValidationError):
        DnaPalette(primary="#000000", accent="#ffffff",
                   bg_gradient=["#000000"], body_bg=["#000","#111"])


def test_tone_defaults():
    t = DnaTone(voice="formal", style="concise")
    assert t.sentence_max_words == 18
    assert t.paragraph_sentences == (3, 5)
    assert t.body_max_chars == 350


def test_tone_voice_required():
    with pytest.raises(ValidationError):
        DnaTone(voice="", style="x")


def test_dna_full_validates():
    dna = DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b","#0a1a3b"],
                           body_bg=["#1a1a2a","#0a0a1a"]),
        fonts=DnaFonts(headline="Inter", body="Inter"),
        tone=DnaTone(voice="formal", style="concise"),
        category_icon="📰",
        persona_summary="Resmi haber kanalı.",
    )
    assert dna.archetype == "newscast"
    assert dna.banner_shape == "flat"   # default
    assert dna.highlight_style == "bg-flat"
    assert dna.chip_style == "rounded"


def test_dna_archetype_must_be_valid():
    with pytest.raises(ValidationError):
        DnaSpec(
            archetype="random-thing",
            palette=DnaPalette(primary="#000000", accent="#ffffff",
                               bg_gradient=["#000","#111"], body_bg=["#000","#111"]),
            fonts=DnaFonts(),
            tone=DnaTone(voice="x", style="y"),
            persona_summary="x",
        )


def test_dna_banner_shape_validates():
    with pytest.raises(ValidationError):
        DnaSpec(
            archetype="newscast",
            palette=DnaPalette(primary="#000000", accent="#ffffff",
                               bg_gradient=["#000","#111"], body_bg=["#000","#111"]),
            fonts=DnaFonts(),
            tone=DnaTone(voice="x", style="y"),
            persona_summary="x",
            banner_shape="bouncy",  # not in Literal
        )
```

- [ ] **Step 2: Run, expect FAIL**

```bash
python -m pytest tests/test_dna.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement (`src/short_bot/dna.py`)**

```python
"""Channel DNA: Pydantic models for visual + content identity (archetype + palette + tone)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


ARCHETYPES = ["newscast", "tabloid", "magazine", "kinetic", "dark-tech", "stadium", "meme"]


class DnaPalette(BaseModel):
    primary: str
    accent: str
    bg_gradient: list[str] = Field(min_length=2, max_length=2)
    body_bg: list[str] = Field(min_length=2, max_length=2)
    text_main: str = "#ffffff"
    text_muted: str = "#cccccc"

    @field_validator("primary", "accent", "text_main", "text_muted")
    @classmethod
    def _validate_hex(cls, v: str) -> str:
        if not (v.startswith("#") and len(v) == 7):
            raise ValueError(f"Invalid hex color: {v!r} (expected #RRGGBB)")
        try:
            int(v[1:], 16)
        except ValueError as e:
            raise ValueError(f"Invalid hex color: {v!r}") from e
        return v.lower()


class DnaFonts(BaseModel):
    headline: str = "Inter"
    body: str = "Inter"
    google_imports: list[str] = Field(default_factory=list)


class DnaTone(BaseModel):
    voice: str = Field(min_length=1, max_length=200)
    style: str = Field(min_length=1, max_length=200)
    forbidden: list[str] = Field(default_factory=list, max_length=10)
    sentence_max_words: int = Field(ge=4, le=40, default=18)
    paragraph_sentences: tuple[int, int] = (3, 5)
    body_max_chars: int = Field(ge=50, le=800, default=350)
    headline_style_hint: str = Field(default="", max_length=200)


class DnaSpec(BaseModel):
    archetype: Literal["newscast", "tabloid", "magazine", "kinetic", "dark-tech", "stadium", "meme"]
    palette: DnaPalette
    fonts: DnaFonts
    tone: DnaTone
    banner_shape: Literal["flat", "ribbon", "slanted", "sharp"] = "flat"
    highlight_style: Literal["bg-flat", "underline", "marker", "neon"] = "bg-flat"
    chip_style: Literal["rounded", "sharp", "pill"] = "rounded"
    category_icon: str = ""
    search_query_template: str = "{header_top} {header_bottom} {category}"
    persona_summary: str = Field(max_length=400)
```

- [ ] **Step 4: Run, expect PASS**

```bash
python -m pytest tests/test_dna.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/dna.py tests/test_dna.py
git commit -m "feat(dna): DnaSpec Pydantic models (archetype + palette + fonts + tone)"
```

---

## Task 5: dna.py — generate_dna (Opus call)

**Files:**
- Modify: `src/short_bot/dna.py`
- Test: `tests/test_dna.py`

- [ ] **Step 1: Write failing tests (`tests/test_dna.py`, append)**

```python
from unittest.mock import patch

from short_bot.dna import generate_dna, build_dna_prompt


def test_build_dna_prompt_includes_inputs():
    p = build_dna_prompt(
        name="Spor Şort", keywords=["Bundesliga", "Bayern"],
        language="de", topic_hint="Hardcore taraftar", target_audience="Genç erkek",
    )
    assert "Spor Şort" in p
    assert "Bundesliga" in p
    assert "Deutsch" in p             # LANGUAGE_NAMES[de] resolved
    assert "Hardcore" in p
    assert "Genç erkek" in p


def test_generate_dna_returns_dnaspec():
    fake = DnaSpec(
        archetype="stadium",
        palette=DnaPalette(primary="#0a4d2a", accent="#ffd700",
                           bg_gradient=["#1a8b3a","#0a4d1a"],
                           body_bg=["#0a1a0a","#000000"]),
        fonts=DnaFonts(headline="Bebas Neue", body="Inter",
                       google_imports=["Bebas+Neue"]),
        tone=DnaTone(voice="leidenschaftlich", style="dynamisch", body_max_chars=280),
        banner_shape="slanted", highlight_style="marker", chip_style="pill",
        category_icon="⚽", persona_summary="...",
    )
    with patch("short_bot.dna.run_json", return_value=fake) as m:
        result = generate_dna(name="x", keywords=["y"], language="de",
                              claude_path="claude", model="opus")
    assert result.archetype == "stadium"
    # Verify the model parameter was passed through
    assert m.call_args.kwargs["model"] == "opus"


def test_generate_dna_default_model_is_opus():
    fake = DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000","#111"], body_bg=["#000","#111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="z",
    )
    with patch("short_bot.dna.run_json", return_value=fake) as m:
        generate_dna(name="x", keywords=["y"], language="tr")
    assert m.call_args.kwargs["model"] == "opus"
```

- [ ] **Step 2: Run, expect FAIL**

```bash
python -m pytest tests/test_dna.py::test_build_dna_prompt_includes_inputs -v
```
Expected: ImportError.

- [ ] **Step 3: Implement — append to `src/short_bot/dna.py`**

```python
from short_bot.claude_cli import run_json
from short_bot.locale import LANGUAGE_NAMES


def build_dna_prompt(
    name: str,
    keywords: list[str],
    language: str,
    topic_hint: str = "",
    target_audience: str = "",
) -> str:
    lang_name = LANGUAGE_NAMES.get(language, language)
    return f"""Sen bir YouTube Shorts kanalının görsel/içerik kimliğini (DNA) tasarlıyorsun.

KANAL BİLGİLERİ:
- İsim: {name}
- Dil: {lang_name}
- Keyword'ler: {", ".join(keywords)}
- Konu ipucu: {topic_hint}
- Hedef kitle: {target_audience}

GÖREV: Bu kanal için bir DNA üret. Kararlarını kanalın konusuna ve dilin
kültürel bağlamına göre yap.

ARCHETYPE SEÇİMİ (1 tane seç):
- newscast → resmi haber, politika, ekonomi, son dakika kritik
- tabloid → magazin, sansasyon, ünlü, skandal, viral dedikodu
- magazine → kültür, sanat, lifestyle, weekend, romantik, zarif
- kinetic → istatistik, alıntı, motivasyon, tek-vurgu, özlü söz
- dark-tech → teknoloji, AI, oyun, hacker, fütürist, cyber
- stadium → spor (futbol/basketbol/F1/...), heyecan, dinamik
- meme → mizah, komedi, troll, viral video, gençlik

DİL UYUMU:
- voice/style/forbidden alanlarını {lang_name} dilinde yaz
- headline_style_hint da o dilde
- persona_summary tamamen o dilde

PALETTE KARARLARI (archetype'a uygun ama kanala özgü override yapabilirsin):
- newscast: kırmızı/lacivert/altın
- tabloid: sarı/kırmızı/siyah, yüksek kontrast
- magazine: bej/krem/burgundy/altın, sıcak
- kinetic: tek vurgu rengi (neon yeşil/mor/mavi) + siyah
- dark-tech: cyan/magenta/yeşil neon + koyu mor/siyah
- stadium: takım/spor renkleri (yeşil/sarı, kırmızı/lacivert vb.)
- meme: parlak mavi/sarı/pembe, Impact-vibe

FONT KARARLARI:
- headline: archetype'a uygun (newscast→Inter, tabloid→Bebas Neue,
  magazine→Playfair Display, kinetic→Anton, dark-tech→JetBrains Mono,
  stadium→Oswald, meme→Impact)
- body: okunabilir genelci (Inter veya Roboto)
- google_imports: Google Fonts URL fragment formatında ("Inter:wght@400;700;900",
  "Bebas+Neue", "Playfair+Display:ital@1")

TONE KARARLARI:
- voice: 2-5 sıfat dizisi
- style: 2-4 sıfat dizisi
- forbidden: bu kanalda ASLA olmayacak 3-7 yaklaşım
- sentence_max_words: archetype'a göre 8-22 arası
- paragraph_sentences: [min, max], magazine için (5,7), tabloid için (2,3) gibi
- body_max_chars: 50 (kinetic) — 600 (magazine) arası
- headline_style_hint: bu kanalın tipik başlık formatı (1 cümle açıklama)

BANNER/HIGHLIGHT/CHIP:
- banner_shape: flat | ribbon | slanted | sharp
- highlight_style: bg-flat | underline | marker | neon
- chip_style: rounded | sharp | pill

CATEGORY_ICON:
- 1 emoji veya kısa unicode (örn. 💼 / 🎬 / ⚽ / 💻)

SEARCH_QUERY_TEMPLATE:
- DDG image search format string
- Default: "{{header_top}} {{header_bottom}} {{category}}"
- Spor için: "{{header_top}} {{category}} football match"
- Tech için: "{{header_top}} technology"

ÇIKTI: SADECE aşağıdaki JSON formatında yanıtla, başka metin yazma:
{{
  "archetype": "...",
  "palette": {{"primary": "#...", "accent": "#...", "bg_gradient": ["#...","#..."],
              "body_bg": ["#...","#..."], "text_main": "#...", "text_muted": "#..."}},
  "fonts": {{"headline": "...", "body": "...", "google_imports": [...]}},
  "tone": {{"voice": "...", "style": "...", "forbidden": [...],
           "sentence_max_words": <int>, "paragraph_sentences": [<int>,<int>],
           "body_max_chars": <int>, "headline_style_hint": "..."}},
  "banner_shape": "...",
  "highlight_style": "...",
  "chip_style": "...",
  "category_icon": "...",
  "search_query_template": "...",
  "persona_summary": "..."
}}
"""


def generate_dna(
    *,
    name: str,
    keywords: list[str],
    language: str,
    topic_hint: str = "",
    target_audience: str = "",
    claude_path: str = "claude",
    model: str = "opus",
) -> DnaSpec:
    prompt = build_dna_prompt(name, keywords, language, topic_hint, target_audience)
    return run_json(
        prompt, DnaSpec,
        claude_path=claude_path, model=model,
        retries=2, timeout_s=180,
    )
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
python -m pytest tests/test_dna.py -v
```
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/dna.py tests/test_dna.py
git commit -m "feat(dna): generate_dna via Opus + build_dna_prompt"
```

---

## Task 6: dna.py — build_css_override (pure Python)

**Files:**
- Modify: `src/short_bot/dna.py`
- Test: `tests/test_dna.py`

- [ ] **Step 1: Write failing tests (`tests/test_dna.py`, append)**

```python
from short_bot.dna import (
    build_css_override, _banner_shape_css, _highlight_css, _chip_css,
)


def _sample_dna(**overrides):
    base = dict(
        archetype="newscast",
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b","#0a1a3b"],
                           body_bg=["#1a1a2a","#0a0a1a"]),
        fonts=DnaFonts(headline="Bebas Neue", body="Inter",
                       google_imports=["Bebas+Neue", "Inter:wght@400;700;900"]),
        tone=DnaTone(voice="x", style="y"),
        category_icon="📰", persona_summary="x",
    )
    base.update(overrides)
    return DnaSpec(**base)


def test_build_css_includes_google_import():
    css = build_css_override(_sample_dna())
    assert "fonts.googleapis.com" in css
    assert "Bebas+Neue" in css


def test_build_css_includes_root_variables():
    css = build_css_override(_sample_dna())
    assert "--primary: #c81e1e" in css
    assert "--accent: #ffea3b" in css
    assert "--bg-grad-1: #1a3b6b" in css
    assert "--font-headline: 'Bebas Neue'" in css


def test_build_css_no_google_imports_skips_import_line():
    dna = _sample_dna(fonts=DnaFonts(headline="Inter", body="Inter", google_imports=[]))
    css = build_css_override(dna)
    assert "@import" not in css


def test_banner_shape_helpers_return_unique_strings():
    flat = _banner_shape_css("flat")
    ribbon = _banner_shape_css("ribbon")
    slanted = _banner_shape_css("slanted")
    sharp = _banner_shape_css("sharp")
    assert len({flat, ribbon, slanted, sharp}) == 4


def test_highlight_styles_return_distinct_css():
    bg = _highlight_css("bg-flat", "#ff0000", "#ffffff")
    underline = _highlight_css("underline", "#ff0000", "#ffffff")
    marker = _highlight_css("marker", "#ff0000", "#ffffff")
    neon = _highlight_css("neon", "#ff0000", "#ffffff")
    assert len({bg, underline, marker, neon}) == 4
    # underline should mention text-decoration
    assert "underline" in underline.lower() or "text-decoration" in underline.lower()


def test_chip_styles_return_distinct_border_radius():
    rounded = _chip_css("rounded")
    sharp = _chip_css("sharp")
    pill = _chip_css("pill")
    assert "border-radius" in rounded
    assert rounded != sharp != pill
```

- [ ] **Step 2: Run, expect FAIL**

```bash
python -m pytest tests/test_dna.py::test_build_css_includes_root_variables -v
```
Expected: ImportError.

- [ ] **Step 3: Implement — append to `src/short_bot/dna.py`**

```python
def _banner_shape_css(shape: str) -> str:
    """Return CSS rule string for the given banner shape."""
    return {
        "flat":    "border-radius: 0; clip-path: none;",
        "ribbon":  "clip-path: polygon(0 0, 100% 0, 100% 80%, 50% 100%, 0 80%);",
        "slanted": "transform: skewY(-1deg); transform-origin: top left;",
        "sharp":   "clip-path: polygon(0 0, 100% 0, 95% 100%, 5% 100%);",
    }.get(shape, "")


def _highlight_css(style: str, bg_color: str, fg_color: str) -> str:
    """Return CSS rule string for the given highlight style."""
    if style == "bg-flat":
        return f"background: {bg_color}; color: {fg_color}; padding: 2px 14px; border-radius: 6px; font-weight: 700;"
    if style == "underline":
        return f"color: {bg_color}; text-decoration: underline; text-decoration-thickness: 6px; text-underline-offset: 4px; font-weight: 700;"
    if style == "marker":
        return f"background: linear-gradient(180deg, transparent 50%, {bg_color} 50%); color: {fg_color}; padding: 0 8px; font-weight: 700;"
    if style == "neon":
        return f"color: {bg_color}; text-shadow: 0 0 8px {bg_color}, 0 0 16px {bg_color}; font-weight: 700;"
    return ""


def _chip_css(style: str) -> str:
    """Return CSS rule string for the given chip style (border-radius only)."""
    return {
        "rounded": "border-radius: 12px;",
        "sharp":   "border-radius: 2px;",
        "pill":    "border-radius: 999px;",
    }.get(style, "border-radius: 12px;")


def build_css_override(dna: DnaSpec) -> str:
    """Generate templates/css/<slug>.css content from DNA. Pure Python, no LLM."""
    google = ""
    if dna.fonts.google_imports:
        google = (
            "@import url('https://fonts.googleapis.com/css2?"
            + "&".join(f"family={x}" for x in dna.fonts.google_imports)
            + "&display=swap');\n"
        )
    p = dna.palette
    css = f"""{google}:root {{
  --primary: {p.primary};
  --accent: {p.accent};
  --bg-grad-1: {p.bg_gradient[0]};
  --bg-grad-2: {p.bg_gradient[1]};
  --body-bg-1: {p.body_bg[0]};
  --body-bg-2: {p.body_bg[1]};
  --text-main: {p.text_main};
  --text-muted: {p.text_muted};
  --font-headline: '{dna.fonts.headline}', sans-serif;
  --font-body: '{dna.fonts.body}', sans-serif;
}}
.header {{ {_banner_shape_css(dna.banner_shape)} }}
.body .hl-r {{ {_highlight_css(dna.highlight_style, p.primary, "#fff")} }}
.body .hl-y {{ {_highlight_css(dna.highlight_style, p.accent, "#000")} }}
.persistent {{ {_chip_css(dna.chip_style)} }}
"""
    return css
```

- [ ] **Step 4: Run, expect PASS**

```bash
python -m pytest tests/test_dna.py -v
```
Expected: 18 passed (12 + 6 new).

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/dna.py tests/test_dna.py
git commit -m "feat(dna): build_css_override + style helpers (pure Python, deterministic)"
```

---

## Task 7: ChannelConfig.template + dna + script_model fields

**Files:**
- Modify: `src/short_bot/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests (`tests/test_config.py`, append)**

```python
def test_load_channel_with_dna_block(tmp_path):
    yaml_text = """slug: test
name: Test
language: de
keywords: [a]
schedule_cron: '0 * * * *'
duration_s: 30
min_score: 8.0
max_candidates_per_run: 30
template: stadium
colors:
  primary: '#0a4d2a'
  accent: '#ffd700'
  bg_gradient: ['#1a8b3a','#0a4d1a']
handle: '@x'
output_dir: output/test
enabled: true
cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}
dna:
  archetype: stadium
  palette:
    primary: '#0a4d2a'
    accent: '#ffd700'
    bg_gradient: ['#1a8b3a','#0a4d1a']
    body_bg: ['#0a1a0a','#000000']
  fonts:
    headline: 'Bebas Neue'
    body: 'Inter'
    google_imports: ['Bebas+Neue']
  tone:
    voice: 'leidenschaftlich'
    style: 'dynamisch'
    forbidden: []
    sentence_max_words: 14
    paragraph_sentences: [3, 4]
    body_max_chars: 280
    headline_style_hint: ''
  banner_shape: slanted
  highlight_style: marker
  chip_style: pill
  category_icon: '⚽'
  search_query_template: '{header_top} football'
  persona_summary: 'Spor kanalı'
"""
    (tmp_path / "ch.yaml").write_text(yaml_text, encoding="utf-8")
    c = load_channel(tmp_path / "ch.yaml")
    assert c.template == "stadium"
    assert c.dna is not None
    assert c.dna.archetype == "stadium"
    assert c.dna.palette.primary == "#0a4d2a"
    assert c.dna.tone.body_max_chars == 280


def test_load_channel_no_dna_block_returns_none(tmp_path):
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nlanguage: tr\nkeywords: []\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: newscast\n"
        "colors: {primary: '#000000', accent: '#ffffff', bg_gradient: ['#000000','#111111']}\n"
        "handle: '@x'\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.dna is None
    assert c.template == "newscast"


def test_load_channel_template_dna_archetype_mismatch_raises(tmp_path):
    yaml_text = """slug: test
name: Test
language: tr
keywords: []
schedule_cron: ''
duration_s: 30
min_score: 0
max_candidates_per_run: 1
template: newscast
colors: {primary: '#000000', accent: '#ffffff', bg_gradient: ['#000000','#111111']}
handle: '@x'
output_dir: x
enabled: true
cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}
dna:
  archetype: tabloid
  palette:
    primary: '#ffea3b'
    accent: '#c81e1e'
    bg_gradient: ['#ffea3b','#ff9999']
    body_bg: ['#ffffff','#eeeeee']
  fonts: {headline: Inter, body: Inter, google_imports: []}
  tone: {voice: x, style: y, forbidden: [], sentence_max_words: 14, paragraph_sentences: [2,3], body_max_chars: 200, headline_style_hint: ''}
  banner_shape: flat
  highlight_style: bg-flat
  chip_style: rounded
  category_icon: ''
  search_query_template: '{header_top}'
  persona_summary: ''
"""
    (tmp_path / "ch.yaml").write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ValueError, match="template.*archetype"):
        load_channel(tmp_path / "ch.yaml")


def test_load_channel_legacy_template_default_maps_to_newscast(tmp_path):
    """Backward-compat: 'template: default' should be loaded as 'newscast'."""
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nlanguage: tr\nkeywords: []\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: default\n"
        "colors: {primary: '#000000', accent: '#ffffff', bg_gradient: ['#000000','#111111']}\n"
        "handle: '@x'\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.template == "newscast"


def test_load_channel_with_script_model_override(tmp_path):
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nlanguage: tr\nkeywords: []\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: newscast\nscript_model: sonnet\n"
        "colors: {primary: '#000000', accent: '#ffffff', bg_gradient: ['#000000','#111111']}\n"
        "handle: '@x'\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.script_model == "sonnet"
```

- [ ] **Step 2: Run, expect FAIL**

```bash
python -m pytest tests/test_config.py::test_load_channel_with_dna_block -v
```
Expected: FAIL — `dna` attribute doesn't exist.

- [ ] **Step 3: Implement — modify `src/short_bot/config.py`**

Add import:
```python
from short_bot.dna import DnaSpec
```

Add to `ChannelConfig`:
```python
@dataclass(frozen=True)
class ChannelConfig:
    # ... existing fields above ...
    language: str = "tr"
    dna: DnaSpec | None = None        # NEW
    script_model: str | None = None   # NEW: per-channel override; None = use settings.default
```

Update `load_channel()`. Find the slug validation block. Right before constructing ChannelConfig, add:

```python
    # Backward-compat: 'template: default' → 'newscast'
    template = data.get("template", "newscast")
    if template == "default":
        template = "newscast"

    # Optional DNA block
    dna_data = data.get("dna")
    dna = DnaSpec.model_validate(dna_data) if dna_data else None
    if dna is not None and dna.archetype != template:
        raise ValueError(
            f"channel.template ({template!r}) must match dna.archetype ({dna.archetype!r})"
        )
```

In the `ChannelConfig(...)` constructor, replace `template=data["template"]` with `template=template`, and add `dna=dna` and `script_model=data.get("script_model")`.

Update `save_channel()` to write `dna` block when present and `script_model` when set:

Find the data dict in `save_channel`:
```python
    data = {
        "slug": cfg.slug,
        ...
    }
```

After all existing keys, add (before `Path(path).write_text(...)`):

```python
    if cfg.script_model:
        data["script_model"] = cfg.script_model
    if cfg.dna is not None:
        # mode='json' → tuple becomes list, ready for YAML round-trip
        data["dna"] = cfg.dna.model_dump(mode="json")
```

- [ ] **Step 4: Run config tests**

```bash
python -m pytest tests/test_config.py -v
```
Expected: 18+ passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/config.py tests/test_config.py
git commit -m "feat(config): ChannelConfig.template + dna + script_model fields with validator"
```

---

## Task 8: fetcher — derive RSS locale from language

**Files:**
- Modify: `src/short_bot/fetcher.py`
- Test: `tests/test_fetcher.py`

- [ ] **Step 1: Write failing test (`tests/test_fetcher.py`, append)**

```python
def test_build_rss_url_uses_language_param():
    from short_bot.fetcher import build_rss_url_for_language
    url = build_rss_url_for_language(["x"], "de")
    assert "hl=de" in url
    assert "gl=DE" in url


def test_build_rss_url_for_language_invalid():
    from short_bot.fetcher import build_rss_url_for_language
    with pytest.raises(KeyError):
        build_rss_url_for_language(["x"], "xx")
```

- [ ] **Step 2: Run, expect FAIL**

```bash
python -m pytest tests/test_fetcher.py::test_build_rss_url_uses_language_param -v
```
Expected: ImportError.

- [ ] **Step 3: Implement — append to `src/short_bot/fetcher.py`**

```python
from short_bot.locale import RSS_LOCALES


def build_rss_url_for_language(keywords: list[str], language: str) -> str:
    """Convenience: build the RSS URL using the locale for `language`."""
    return build_rss_url(keywords, RSS_LOCALES[language])
```

- [ ] **Step 4: Run, expect PASS**

```bash
python -m pytest tests/test_fetcher.py -v
```
Expected: 6+ passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/fetcher.py tests/test_fetcher.py
git commit -m "feat(fetcher): build_rss_url_for_language helper"
```

---

## Task 9: Rename default.html.j2 → newscast.html.j2

**Files:**
- Rename: `templates/default.html.j2` → `templates/newscast.html.j2`
- Modify: `scripts/render_test_frame.py` (any reference)

- [ ] **Step 1: Rename file**

```bash
git mv templates/default.html.j2 templates/newscast.html.j2
```

- [ ] **Step 2: Update test references**

Search for any test that hardcodes `templates/default.html.j2`:

```bash
grep -rn "default.html.j2" src/ tests/ scripts/
```

For any matches, change `default.html.j2` → `newscast.html.j2` in those files.

(`scripts/render_test_frame.py` likely needs an update.)

- [ ] **Step 3: Run all tests**

```bash
python -m pytest -v
```
Expected: still passing (the loader's `template: default` → `newscast` mapping from Task 7 covers existing son-dakika.yaml).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(templates): rename default.html.j2 → newscast.html.j2"
```

---

## Task 10: RenderJob.language + build_html ui_labels & dna_css

**Files:**
- Modify: `src/short_bot/models.py`
- Modify: `src/short_bot/renderer.py`
- Test: `tests/test_renderer.py`

- [ ] **Step 1: Write failing test (`tests/test_renderer.py`, append)**

```python
def test_build_html_includes_ui_labels_when_provided(tmp_path):
    template = Path("templates/newscast.html.j2")
    job = _job(tmp_path)
    job.language = "de"
    html = build_html(job, template,
                      ui_labels={"like": "GEFÄLLT MIR", "subscribe": "ABONNIEREN",
                                 "share": "TEILEN", "breaking": "EILMELDUNG"})
    assert "GEFÄLLT MIR" in html
    assert "ABONNIEREN" in html
    assert "EILMELDUNG" in html


def test_build_html_includes_dna_css_when_provided(tmp_path):
    template = Path("templates/newscast.html.j2")
    job = _job(tmp_path)
    css = "/* DNA */ :root { --primary: #abcdef; }"
    html = build_html(job, template,
                      ui_labels={"like": "L", "subscribe": "S", "share": "SH", "breaking": "B"},
                      dna_css=css)
    assert "#abcdef" in html
    assert "/* DNA */" in html


def test_build_html_default_ui_labels_when_omitted(tmp_path):
    template = Path("templates/newscast.html.j2")
    job = _job(tmp_path)
    # If ui_labels not passed, defaults to Turkish labels for backward-compat
    html = build_html(job, template)
    assert "BEĞEN" in html
    assert "ABONE OL" in html
```

Also update `_job(tmp_path)` helper to set `language="tr"` (since RenderJob now requires the field).

- [ ] **Step 2: Run, expect FAIL**

```bash
python -m pytest tests/test_renderer.py::test_build_html_includes_ui_labels_when_provided -v
```
Expected: FAIL.

- [ ] **Step 3: Add language to RenderJob (`src/short_bot/models.py`)**

Find the `RenderJob` dataclass:

```python
@dataclass
class RenderJob:
    script: Script
    bg_image_path: Path | None
    music_path: Path
    channel_colors: dict
    handle: str
    duration_s: int
    cta_enabled: bool = True
    ...
```

Add `language: str = "tr"` (right after `handle`):

```python
@dataclass
class RenderJob:
    script: Script
    bg_image_path: Path | None
    music_path: Path
    channel_colors: dict
    handle: str
    duration_s: int
    language: str = "tr"        # NEW
    cta_enabled: bool = True
    cta_text: str = "BEĞEN · ABONE OL · PAYLAŞ"
    cta_icons: list[str] = field(default_factory=lambda: ["❤️", "🔔", "↗️"])
    cta_duration_s: int = 4
    cta_show_handle: bool = True
```

- [ ] **Step 4: Update `build_html` (`src/short_bot/renderer.py`)**

Replace the `build_html` function signature and body:

```python
DEFAULT_UI_LABELS_TR = {"like": "BEĞEN", "subscribe": "ABONE OL",
                         "share": "PAYLAŞ", "breaking": "SON DAKİKA"}


def build_html(
    job: RenderJob,
    template_path: Path,
    *,
    ui_labels: dict[str, str] | None = None,
    dna_css: str = "",
) -> str:
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
        mime, _ = mimetypes.guess_type(str(job.bg_image_path))
        mime = mime or "image/jpeg"
        data = base64.b64encode(job.bg_image_path.read_bytes()).decode("ascii")
        bg_url = f"data:{mime};base64,{data}"

    body_html = _wrap_highlights(job.script.body_paragraph, job.script.highlights)

    labels = ui_labels or DEFAULT_UI_LABELS_TR

    return template.render(
        script=job.script,
        body_html=body_html,
        bg_image_url=bg_url,
        colors=colors,
        handle=job.handle,
        duration_s=job.duration_s,
        category=job.script.category,
        language=job.language,
        ui_breaking=labels["breaking"],
        ui_like=labels["like"],
        ui_subscribe=labels["subscribe"],
        ui_share=labels["share"],
        dna_css=dna_css,
        cta={
            "enabled": job.cta_enabled,
            "text": job.cta_text,
            "icons": job.cta_icons,
            "duration_s": job.cta_duration_s,
            "show_handle": job.cta_show_handle,
        },
    )
```

- [ ] **Step 5: Update `templates/newscast.html.j2` to use the new variables**

Find:
```jinja
  <div class="stage-badge">SON DAKİKA</div>
```

Replace with:
```jinja
  <div class="stage-badge">{{ ui_breaking }}</div>
```

Find the persistent chips:
```jinja
  <div class="persistent like"><span class="ic">❤️</span><span>BEĞEN</span></div>
  <div class="persistent sub"><span class="ic">🔔</span><span>ABONE OL</span></div>
```

Replace with:
```jinja
  <div class="persistent like"><span class="ic">❤️</span><span>{{ ui_like }}</span></div>
  <div class="persistent sub"><span class="ic">🔔</span><span>{{ ui_subscribe }}</span></div>
```

Find the `<style>` opening tag:
```jinja
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
```

After the `@import` line, add:
```jinja
  /* DNA OVERRIDE (per-channel CSS variables, fonts, banner shape, etc.) */
  {{ dna_css|safe }}
```

Update `<html lang="tr">` to `<html lang="{{ language }}">`.

- [ ] **Step 6: Run renderer tests**

```bash
python -m pytest tests/test_renderer.py -v -m "not slow"
```
Expected: PASS for all updated tests.

- [ ] **Step 7: Commit**

```bash
git add src/short_bot/models.py src/short_bot/renderer.py templates/newscast.html.j2 tests/test_renderer.py
git commit -m "feat(renderer): build_html accepts ui_labels + dna_css; RenderJob.language"
```

---

## Task 11: script_writer — ARCHETYPE_PROMPTS + channel-aware build_script_prompt

**Files:**
- Modify: `src/short_bot/script_writer.py`
- Test: `tests/test_script_writer.py`

- [ ] **Step 1: Write failing tests (`tests/test_script_writer.py`, append)**

```python
from short_bot.script_writer import ARCHETYPE_PROMPTS, build_script_prompt_for_channel
from short_bot.config import ChannelConfig
from short_bot.dna import DnaSpec, DnaPalette, DnaFonts, DnaTone


def _channel(language="tr", template="newscast", dna=None):
    return ChannelConfig(
        slug="test", name="T", keywords=["x"],
        rss_locale="hl=tr&gl=TR&ceid=TR:tr",
        schedule_cron="0 * * * *", duration_s=30, min_score=8.0,
        max_candidates_per_run=10, template=template,
        colors={"primary": "#c81e1e", "accent": "#ffea3b",
                 "bg_gradient": ["#1a3b6b", "#0a1a3b"]},
        handle="@x", output_dir="output/test",
        enabled=True, cta_enabled=False, cta_text="",
        cta_icons=[], cta_duration_s=0, cta_show_handle=False,
        language=language, dna=dna,
    )


def test_archetype_prompts_cover_all_seven():
    expected = {"newscast", "tabloid", "magazine", "kinetic", "dark-tech", "stadium", "meme"}
    assert set(ARCHETYPE_PROMPTS.keys()) == expected


def test_build_script_prompt_includes_archetype_instructions():
    item = _item()
    p = build_script_prompt_for_channel(item, "body text", _channel(template="tabloid"))
    assert "tabloid" in p.lower()
    # Tabloid signature word from prompt
    assert "provocative" in p.lower() or "sensational" in p.lower()


def test_build_script_prompt_includes_language_name():
    p = build_script_prompt_for_channel(_item(), "body", _channel(language="de"))
    assert "Deutsch" in p


def test_build_script_prompt_includes_tone_block_when_dna_present():
    dna = DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000","#111"], body_bg=["#000","#111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="formal, data-driven", style="concise",
                     forbidden=["clickbait"], sentence_max_words=12,
                     paragraph_sentences=(3,4), body_max_chars=300),
        persona_summary="x",
    )
    p = build_script_prompt_for_channel(_item(), "body", _channel(dna=dna))
    assert "formal, data-driven" in p
    assert "clickbait" in p
    assert "12" in p   # sentence_max_words


def test_build_script_prompt_no_tone_block_when_no_dna():
    p = build_script_prompt_for_channel(_item(), "body", _channel(dna=None))
    # No tone-block heading should be present
    assert "TONE OF VOICE" not in p
```

- [ ] **Step 2: Run, expect FAIL**

```bash
python -m pytest tests/test_script_writer.py::test_archetype_prompts_cover_all_seven -v
```
Expected: ImportError.

- [ ] **Step 3: Implement — modify `src/short_bot/script_writer.py`**

Add at top of file:
```python
from short_bot.config import ChannelConfig
from short_bot.locale import LANGUAGE_NAMES
```

Add module-level constant (place after imports, before any function):

```python
ARCHETYPE_PROMPTS = {
    "newscast": """ARCHETYPE: newscast — formal news presentation
- header_top + header_bottom: 4-6 words total, formal capital news headline
- photo_overlay: 2-5 words, key fact (number, decision, action)
- body_paragraph: 4-5 sentences, neutral journalistic tone
- highlights: red=warning/risk/casualty, yellow=stat/decision/key actor
- mood: breaking for crisis, neutral default, upbeat for positive resolution
""",
    "tabloid": """ARCHETYPE: tabloid — provocative, sensational
- header_top: provocative question or exclamation
- header_bottom: short follow-up phrase
- photo_overlay: gossip-style claim ("EXPOSED!" / "SHOCK!")
- body_paragraph: 2-3 punchy sentences, sensational tone
- highlights: red=scandal, yellow=name/place
- mood: usually breaking
""",
    "magazine": """ARCHETYPE: magazine — elegant, longform
- header_top: poetic 2-4 word title
- header_bottom: subtitle phrase or attribution
- photo_overlay: thoughtful sub-tagline
- body_paragraph: 5-7 sentences, elegant, descriptive
- highlights: yellow=key idea, red sparingly
- mood: usually neutral or upbeat
""",
    "kinetic": """ARCHETYPE: kinetic — typography-led, single-focus
- header_top: 1-2 PUNCHY words OR a number
- header_bottom: 1 short phrase OR empty
- photo_overlay: brief context (≤5 words)
- body_paragraph: 1-2 short sentences (max 80 chars total)
- highlights: 0-1, neon style
- mood: any, often upbeat for stat/insight
""",
    "dark-tech": """ARCHETYPE: dark-tech — terminal, codified
- header_top: codified-style "> NEWS_DROP" or "[ALERT]"
- header_bottom: tech topic descriptor
- photo_overlay: 3-6 words technical claim
- body_paragraph: 3-4 sentences, factual, can include code-flavored terms
- highlights: green/cyan=key tech, red=vulnerability/risk
- mood: usually breaking for vulnerabilities, upbeat for releases
""",
    "stadium": """ARCHETYPE: stadium — sports broadcast energy
- header_top: SCORE format ("TEAM 2-1 TEAM") OR action word
- header_bottom: event/stage ("90+3", "FINAL")
- photo_overlay: dramatic moment description
- body_paragraph: 3-4 sentences, energetic sports-broadcast tone
- highlights: red=goal/critical event, yellow=player name/stat
- mood: breaking for last-minute, upbeat for victory
""",
    "meme": """ARCHETYPE: meme — Impact-style top/bottom text
- header_top: TOP TEXT (Impact-meme, ALL CAPS, ≤5 words)
- header_bottom: BOTTOM TEXT (≤5 words, punchline)
- photo_overlay: empty OR a short tag
- body_paragraph: 1 short caption (≤60 chars)
- highlights: 0-1, edgy
- mood: usually upbeat
""",
}


def build_script_prompt_for_channel(item: NewsItem, body: str, channel: ChannelConfig) -> str:
    """Channel-aware prompt: includes archetype instructions + tone block + language."""
    lang_name = LANGUAGE_NAMES.get(channel.language, channel.language)
    arch_instructions = ARCHETYPE_PROMPTS.get(channel.template, ARCHETYPE_PROMPTS["newscast"])

    tone_text = ""
    if channel.dna is not None:
        t = channel.dna.tone
        tone_text = f"""
TONE OF VOICE:
- Voice: {t.voice}
- Style: {t.style}
- Forbidden: {", ".join(t.forbidden) if t.forbidden else "(none)"}
- Sentence max: {t.sentence_max_words} words
- Paragraph: {t.paragraph_sentences[0]}-{t.paragraph_sentences[1]} sentences
- Body max: {t.body_max_chars} characters
- Headline style: {t.headline_style_hint}
"""

    source = item.source or "—"
    return f"""You are writing a {lang_name} YouTube Shorts script.

ORIGINAL HEADLINE: {item.title}
SOURCE: {source}

ARTICLE BODY:
{body}

{arch_instructions}
{tone_text}
TASK: Convert this news into a 3-layer Short script. Output language: {lang_name}.
Output STRICT JSON only:
{{
  "header_top":      "...",
  "header_bottom":   "...",
  "photo_overlay":   "...",
  "body_paragraph":  "...",
  "highlights":      [{{"text": "<exact substring of body>", "color": "red"|"yellow"}}],
  "category":        "...",
  "mood":            "breaking" | "neutral" | "upbeat"
}}

Rules:
- All text in {lang_name}, with proper diacritics
- highlights[i].text must appear verbatim in body_paragraph
- Stay within tone constraints if specified above
"""
```

Also update `write_script(item, body, *, claude_path)` to accept a `channel` and `model` and use the channel-aware prompt builder when available:

Find:
```python
def write_script(item: NewsItem, body: str, *, claude_path: str = "claude") -> Script:
    prompt = build_script_prompt(item, body)
    return run_json(prompt, Script, claude_path=claude_path, retries=3)
```

Replace with:
```python
def write_script(
    item: NewsItem,
    body: str,
    *,
    claude_path: str = "claude",
    channel: ChannelConfig | None = None,
    model: str = "default",
) -> Script:
    prompt = (build_script_prompt_for_channel(item, body, channel)
              if channel is not None else build_script_prompt(item, body))
    return run_json(prompt, Script, claude_path=claude_path, model=model, retries=3)
```

- [ ] **Step 4: Run, expect PASS**

```bash
python -m pytest tests/test_script_writer.py -v
```
Expected: 6+ passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/script_writer.py tests/test_script_writer.py
git commit -m "feat(script_writer): ARCHETYPE_PROMPTS + channel-aware prompt + model param"
```

---

## Task 12: image_picker — search_query_template

**Files:**
- Modify: `src/short_bot/image_picker.py`
- Test: `tests/test_image_picker.py`

- [ ] **Step 1: Write failing test (`tests/test_image_picker.py`, append)**

```python
from short_bot.image_picker import build_search_query_for_channel
from short_bot.config import ChannelConfig


def _channel_with_template(template_str=None):
    dna = None
    if template_str is not None:
        from short_bot.dna import DnaSpec, DnaPalette, DnaFonts, DnaTone
        dna = DnaSpec(
            archetype="stadium",
            palette=DnaPalette(primary="#000000", accent="#ffffff",
                               bg_gradient=["#000","#111"], body_bg=["#000","#111"]),
            fonts=DnaFonts(),
            tone=DnaTone(voice="x", style="y"),
            search_query_template=template_str,
            persona_summary="x",
        )
    return ChannelConfig(
        slug="t", name="T", keywords=[], rss_locale="hl=tr",
        schedule_cron="", duration_s=30, min_score=0,
        max_candidates_per_run=1, template="stadium" if dna else "newscast",
        colors={"primary":"#000","accent":"#fff","bg_gradient":["#000","#111"]},
        handle="@x", output_dir="x", enabled=True,
        cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language="tr", dna=dna,
    )


def test_build_search_query_uses_dna_template_when_present():
    ch = _channel_with_template("{header_top} {category} sports")
    q = build_search_query_for_channel(_script(), ch)
    assert "ARA ZAM" in q
    assert "SİYASET" in q
    assert "sports" in q


def test_build_search_query_default_when_no_dna():
    ch = _channel_with_template(None)
    q = build_search_query_for_channel(_script(), ch)
    assert "ARA ZAM" in q
    assert "AÇIKLAMASI" in q
    assert "SİYASET" in q
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement — append to `src/short_bot/image_picker.py`**

```python
from short_bot.config import ChannelConfig


def build_search_query_for_channel(script: Script, channel: ChannelConfig) -> str:
    """Build DDG image search query using channel.dna.search_query_template if set."""
    template = (
        channel.dna.search_query_template if channel.dna is not None
        else "{header_top} {header_bottom} {category}"
    )
    return template.format(
        header_top=script.header_top,
        header_bottom=script.header_bottom,
        category=script.category,
        photo_overlay=script.photo_overlay,
    ).strip()
```

- [ ] **Step 4: Update `pick_image_for_script` to accept channel and use channel-aware query**

Find in `src/short_bot/image_picker.py`:

```python
def pick_image_for_script(
    script: Script,
    cache_dir: Path,
    *,
    claude_path: str = "claude",
    max_candidates: int = 3,
) -> Path | None:
```

Replace with:

```python
def pick_image_for_script(
    script: Script,
    cache_dir: Path,
    *,
    claude_path: str = "claude",
    max_candidates: int = 3,
    channel: ChannelConfig | None = None,
) -> Path | None:
```

Inside the function, find:
```python
    query = build_search_query(script)
```

Replace with:
```python
    query = (build_search_query_for_channel(script, channel)
             if channel is not None else build_search_query(script))
```

- [ ] **Step 5: Add test for channel-aware pick_image_for_script**

Append to `tests/test_image_picker.py`:

```python
def test_pick_image_uses_channel_aware_query_when_channel_provided(tmp_path):
    ch = _channel_with_template("{header_top} ONLY")
    candidates = [_cand("https://example.com/a.jpg")]

    captured = {}
    def fake_search(query, **kwargs):
        captured["query"] = query
        return candidates

    with patch("short_bot.image_picker.search_images", side_effect=fake_search), \
         patch("short_bot.image_picker._download", return_value=True), \
         patch("short_bot.image_picker._verify_with_claude",
               return_value=_Verdict(appropriate=True, reason="ok")):
        pick_image_for_script(_script(), tmp_path / "img",
                              claude_path="claude", channel=ch)
    assert "ONLY" in captured["query"]
    assert "ARA ZAM" in captured["query"]   # header_top from _script()
```

- [ ] **Step 6: Run, expect PASS**

```bash
python -m pytest tests/test_image_picker.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/short_bot/image_picker.py tests/test_image_picker.py
git commit -m "feat(image_picker): channel-aware search query template"
```

---

## Task 13: pipeline integration (language, dna_css, ui_labels, model)

**Files:**
- Modify: `src/short_bot/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing test (`tests/test_pipeline.py`, append)**

```python
def test_pipeline_passes_channel_aware_args(tmp_path):
    """Pipeline must call write_script with channel + model from settings.claude_models."""
    item = NewsItem(guid="g1", title="T", link="http://x", source="S",
                    pub_date=datetime(2026, 5, 5), thumb_url=None, description="d")
    settings = Settings(
        ffmpeg_path="ffmpeg", claude_cli_path="claude", playwright_browser="chromium",
        web_host="127.0.0.1", web_port=5000,
        fuzzy_dedup_threshold=0.85, log_level="INFO",
        claude_models={"dna": "opus", "default": "haiku"},
    )
    channel = _channel(tmp_path)
    db_path = tmp_path / "db.sqlite"
    music_root = tmp_path / "music"
    (music_root / "breaking").mkdir(parents=True)
    src_music = Path(__file__).parent / "fixtures" / "music_sample.mp3"
    (music_root / "breaking" / "a.mp3").write_bytes(src_music.read_bytes())

    def fake_compose(frames_dir, music_path, out_path, **kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"x")
        return Path(out_path)

    with patch("short_bot.pipeline.fetch_rss", return_value=[item]), \
         patch("short_bot.pipeline.score_items",
               return_value=[ScoredItem(item=item, score=9.0, reasoning="ok")]), \
         patch("short_bot.pipeline.extract_article", return_value="body"), \
         patch("short_bot.pipeline.write_script", return_value=_script()) as m_script, \
         patch("short_bot.pipeline.download_and_blur_thumb", return_value=None), \
         patch("short_bot.image_picker.pick_image_for_script", return_value=None), \
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
    # Verify write_script was called with channel and model="haiku"
    assert m_script.call_args.kwargs.get("channel") is channel
    assert m_script.call_args.kwargs.get("model") == "haiku"
```

(Update `_channel(tmp_path)` to set `language="tr"` if not already; the pipeline should pass through.)

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Update pipeline (`src/short_bot/pipeline.py`)**

Find the `[5/8] write_script` block:

```python
            log.info("[5/8] write_script")
            script = write_script(picked.item, body, claude_path=settings.claude_cli_path)
            log.info(f"  → {script.header_top} | {script.header_bottom}")
```

Replace with:

```python
            log.info("[5/8] write_script")
            script_model = channel.script_model or settings.claude_models.get("default", "default")
            script = write_script(
                picked.item, body,
                claude_path=settings.claude_cli_path,
                channel=channel,
                model=script_model,
            )
            log.info(f"  → {script.header_top} | {script.header_bottom}")
```

Find the `[6/8] assets` block. Find:
```python
            if bg is None:
                # Fallback: search DDG + verify with Claude vision
                from short_bot.image_picker import pick_image_for_script
                images_cache = cache_dir / "images"
                bg = pick_image_for_script(script, images_cache,
                                            claude_path=settings.claude_cli_path)
```

Replace with (pass channel for channel-aware search query):
```python
            if bg is None:
                # Fallback: search DDG + verify with Claude vision (channel-aware query)
                from short_bot.image_picker import pick_image_for_script
                images_cache = cache_dir / "images"
                bg = pick_image_for_script(script, images_cache,
                                            claude_path=settings.claude_cli_path,
                                            channel=channel)
```

Now find the `[7/8] render_frames` block. Find:
```python
            job = RenderJob(
                script=script,
                bg_image_path=bg,
                music_path=music,
                channel_colors=channel.colors,
                handle=channel.handle,
                duration_s=channel.duration_s,
                cta_enabled=channel.cta_enabled,
                ...
            )
```

Add `language=channel.language,` after `handle=channel.handle,` (or anywhere convenient):

```python
            job = RenderJob(
                script=script,
                bg_image_path=bg,
                music_path=music,
                channel_colors=channel.colors,
                handle=channel.handle,
                duration_s=channel.duration_s,
                language=channel.language,                  # NEW
                cta_enabled=channel.cta_enabled,
                ...
            )
```

Now find `render_frames(job, template_path, frames_dir, ...)`. Right before that, load the DNA CSS and UI labels:

Find:
```python
            with tempfile.TemporaryDirectory() as tmpd:
                frames_dir = Path(tmpd) / "frames"
                t0 = time.perf_counter()
                template_path = templates_dir / f"{channel.template}.html.j2"
                render_frames(job, template_path, frames_dir,
                              fps=30, browser=settings.playwright_browser)
```

Replace with:
```python
            with tempfile.TemporaryDirectory() as tmpd:
                frames_dir = Path(tmpd) / "frames"
                t0 = time.perf_counter()
                template_path = templates_dir / f"{channel.template}.html.j2"
                # Load per-channel CSS override + UI labels
                from short_bot.locale import ui_labels_for
                ui_labels = ui_labels_for(channel.language)
                dna_css_path = templates_dir / "css" / f"{channel.slug}.css"
                dna_css = dna_css_path.read_text(encoding="utf-8") if dna_css_path.exists() else ""
                render_frames(
                    job, template_path, frames_dir,
                    fps=30, browser=settings.playwright_browser,
                    ui_labels=ui_labels, dna_css=dna_css,
                )
```

Update `render_frames` in `src/short_bot/renderer.py` to forward these args:

Find `def render_frames(job, template_path, out_dir, *, fps=30, browser="chromium")`:

Replace with:
```python
def render_frames(
    job: RenderJob,
    template_path: Path,
    out_dir: Path,
    *,
    fps: int = 30,
    browser: str = "chromium",
    ui_labels: dict[str, str] | None = None,
    dna_css: str = "",
) -> int:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html = build_html(job, template_path, ui_labels=ui_labels, dna_css=dna_css)
    # ... rest unchanged ...
```

- [ ] **Step 4: Run all tests, expect PASS**

```bash
python -m pytest -v
```
Expected: 95+ passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/pipeline.py src/short_bot/renderer.py tests/test_pipeline.py
git commit -m "feat(pipeline): pass language + DNA css + ui_labels + script_model through"
```

---

## Task 14: CLI — create-channel command

**Files:**
- Modify: `src/short_bot/cli.py`
- Create: `tests/test_cli_create_channel.py`

- [ ] **Step 1: Write failing tests (`tests/test_cli_create_channel.py`)**

```python
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from short_bot.cli import _cmd_create_channel
from short_bot.dna import DnaSpec, DnaPalette, DnaFonts, DnaTone


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config" / "channels").mkdir(parents=True)
    (tmp_path / "templates" / "css").mkdir(parents=True)
    (tmp_path / "config" / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5000}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: haiku\n",
        encoding="utf-8",
    )
    return tmp_path


def _fake_dna(archetype="newscast"):
    return DnaSpec(
        archetype=archetype,
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b","#0a1a3b"],
                           body_bg=["#1a1a2a","#0a0a1a"]),
        fonts=DnaFonts(headline="Inter", body="Inter"),
        tone=DnaTone(voice="x", style="y"),
        category_icon="📰",
        persona_summary="z",
    )


def test_create_channel_writes_yaml_and_css(cli_env):
    fake = _fake_dna(archetype="newscast")
    args = type("Args", (), {
        "name": "Test Kanal", "language": "tr",
        "keywords": "a,b,c", "topic_hint": "", "target_audience": "",
        "config_dir": "config", "templates_dir": "templates",
        "force": False,
    })()
    with patch("short_bot.cli.generate_dna", return_value=fake):
        rc = _cmd_create_channel(args)
    assert rc == 0
    yaml_path = cli_env / "config" / "channels" / "test-kanal.yaml"
    css_path = cli_env / "templates" / "css" / "test-kanal.css"
    assert yaml_path.exists()
    assert css_path.exists()
    txt = yaml_path.read_text(encoding="utf-8")
    assert "language: tr" in txt
    assert "Test Kanal" in txt
    css = css_path.read_text(encoding="utf-8")
    assert "--primary: #c81e1e" in css


def test_create_channel_existing_slug_without_force_returns_error(cli_env):
    yaml_path = cli_env / "config" / "channels" / "existing.yaml"
    yaml_path.write_text("slug: existing\n", encoding="utf-8")
    args = type("Args", (), {
        "name": "Existing", "language": "tr", "keywords": "a",
        "topic_hint": "", "target_audience": "",
        "config_dir": "config", "templates_dir": "templates", "force": False,
    })()
    with patch("short_bot.cli.generate_dna", return_value=_fake_dna()):
        rc = _cmd_create_channel(args)
    assert rc != 0


def test_create_channel_invalid_language_returns_error(cli_env):
    args = type("Args", (), {
        "name": "X", "language": "xx", "keywords": "a",
        "topic_hint": "", "target_audience": "",
        "config_dir": "config", "templates_dir": "templates", "force": False,
    })()
    rc = _cmd_create_channel(args)
    assert rc != 0
```

- [ ] **Step 2: Run, expect FAIL**

```bash
python -m pytest tests/test_cli_create_channel.py -v
```
Expected: ImportError on `_cmd_create_channel`.

- [ ] **Step 3: Implement — modify `src/short_bot/cli.py`**

Add at top:
```python
import re as _re
from short_bot.config import save_channel, ChannelConfig
from short_bot.dna import generate_dna, build_css_override
from short_bot.locale import SUPPORTED_LANGUAGES, RSS_LOCALES
```

Add new subcommand registration (find the `_add_*` functions and add):

```python
def _add_create_channel(sub):
    p = sub.add_parser("create-channel", help="Create a new channel via Opus DNA generation")
    p.add_argument("--name", required=True, help='Display name (e.g. "Spor Şort DE")')
    p.add_argument("--language", required=True, help="One of: tr,en,de,es,fr")
    p.add_argument("--keywords", required=True, help="Comma-separated keyword list")
    p.add_argument("--topic-hint", default="", help="Free-form topic brief")
    p.add_argument("--target-audience", default="", help="Free-form audience brief")
    p.add_argument("--config-dir", default="config")
    p.add_argument("--templates-dir", default="templates")
    p.add_argument("--force", action="store_true", help="Overwrite existing channel")
    p.set_defaults(func=_cmd_create_channel)
```

Add helper for slug derivation (somewhere near `_add_create_channel`):

```python
def _slug_from_name(name: str) -> str:
    import unicodedata
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = _re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return name or "channel"
```

Add the command handler:

```python
def _cmd_create_channel(args) -> int:
    if args.language not in SUPPORTED_LANGUAGES:
        print(f"Error: --language must be one of {SUPPORTED_LANGUAGES}", file=sys.stderr)
        return 2
    config_dir = Path(args.config_dir)
    templates_dir = Path(args.templates_dir)
    slug = _slug_from_name(args.name)
    yaml_path = config_dir / "channels" / f"{slug}.yaml"
    css_path = templates_dir / "css" / f"{slug}.css"

    if yaml_path.exists() and not args.force:
        print(f"Error: channel '{slug}' already exists at {yaml_path}. "
              f"Use --force to overwrite.", file=sys.stderr)
        return 3

    settings = load_settings(config_dir / "settings.yaml")
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    print(f"Generating DNA via {settings.claude_models['dna']}... (this can take 30-60s)")
    try:
        dna = generate_dna(
            name=args.name, keywords=keywords, language=args.language,
            topic_hint=args.topic_hint, target_audience=args.target_audience,
            claude_path=settings.claude_cli_path,
            model=settings.claude_models.get("dna", "opus"),
        )
    except Exception as e:
        print(f"Error: DNA generation failed: {e}", file=sys.stderr)
        return 4

    print(f"  → archetype={dna.archetype}")
    print(f"  → palette: primary={dna.palette.primary} accent={dna.palette.accent}")
    print(f"  → fonts: headline={dna.fonts.headline} body={dna.fonts.body}")

    css = build_css_override(dna)
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(css, encoding="utf-8")
    print(f"  wrote {css_path}")

    cfg = ChannelConfig(
        slug=slug, name=args.name, keywords=keywords,
        rss_locale=RSS_LOCALES[args.language],
        schedule_cron="0 8,14,20 * * *",
        duration_s=6, min_score=6.0, max_candidates_per_run=10,
        template=dna.archetype,
        colors={
            "primary": dna.palette.primary,
            "accent": dna.palette.accent,
            "bg_gradient": dna.palette.bg_gradient,
        },
        handle=f"@{slug}", output_dir=f"output/{slug}",
        enabled=True,
        cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language=args.language, dna=dna, script_model=None,
    )
    save_channel(yaml_path, cfg)
    print(f"  wrote {yaml_path}")
    print(f"\nChannel '{slug}' created. Try:\n  python -m short_bot run --channel {slug} --max 1")
    return 0
```

In `main()`, register the subcommand. Find `_add_init(sub); _add_list(sub)` and add:
```python
    _add_create_channel(sub)
```

- [ ] **Step 4: Run, expect PASS**

```bash
python -m pytest tests/test_cli_create_channel.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/cli.py tests/test_cli_create_channel.py
git commit -m "feat(cli): create-channel subcommand (Opus DNA + CSS override + YAML)"
```

---

## Task 15: CLI — regenerate-dna, rebuild-css, migrate-channel

**Files:**
- Modify: `src/short_bot/cli.py`
- Test: `tests/test_cli_create_channel.py`

- [ ] **Step 1: Write failing tests (`tests/test_cli_create_channel.py`, append)**

```python
def test_regenerate_dna_overwrites_yaml_and_css(cli_env):
    # First, create a channel
    yaml_path = cli_env / "config" / "channels" / "demo.yaml"
    css_path = cli_env / "templates" / "css" / "demo.css"
    yaml_path.write_text(
        "slug: demo\nname: Demo\nlanguage: tr\nkeywords: [a]\nrss_locale: hl=tr&gl=TR&ceid=TR:tr\n"
        "schedule_cron: '0 * * * *'\nduration_s: 30\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#c81e1e', accent: '#ffea3b', bg_gradient: ['#1a3b6b','#0a1a3b']}\n"
        "handle: '@demo'\noutput_dir: output/demo\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )

    new_dna = _fake_dna(archetype="tabloid")
    args = type("Args", (), {
        "channel": "demo", "config_dir": "config", "templates_dir": "templates",
    })()
    from short_bot.cli import _cmd_regenerate_dna
    with patch("short_bot.cli.generate_dna", return_value=new_dna):
        rc = _cmd_regenerate_dna(args)
    assert rc == 0
    assert "tabloid" in yaml_path.read_text(encoding="utf-8")
    assert css_path.exists()


def test_rebuild_css_no_llm_call(cli_env):
    """rebuild-css regenerates CSS from existing DNA YAML, no LLM."""
    # Create channel with DNA in YAML
    yaml_path = cli_env / "config" / "channels" / "demo.yaml"
    yaml_text = """slug: demo
name: Demo
language: tr
keywords: [a]
rss_locale: hl=tr&gl=TR&ceid=TR:tr
schedule_cron: '0 * * * *'
duration_s: 30
min_score: 6.0
max_candidates_per_run: 10
template: newscast
colors: {primary: '#aabbcc', accent: '#ffea3b', bg_gradient: ['#1a3b6b','#0a1a3b']}
handle: '@demo'
output_dir: output/demo
enabled: true
cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}
dna:
  archetype: newscast
  palette:
    primary: '#aabbcc'
    accent: '#ffea3b'
    bg_gradient: ['#1a3b6b','#0a1a3b']
    body_bg: ['#1a1a2a','#0a0a1a']
  fonts: {headline: Inter, body: Inter, google_imports: []}
  tone: {voice: x, style: y, forbidden: [], sentence_max_words: 14, paragraph_sentences: [3,5], body_max_chars: 350, headline_style_hint: ''}
  banner_shape: flat
  highlight_style: bg-flat
  chip_style: rounded
  category_icon: ''
  search_query_template: '{header_top}'
  persona_summary: ''
"""
    yaml_path.write_text(yaml_text, encoding="utf-8")
    args = type("Args", (), {
        "channel": "demo", "config_dir": "config", "templates_dir": "templates",
    })()
    from short_bot.cli import _cmd_rebuild_css
    rc = _cmd_rebuild_css(args)
    assert rc == 0
    css_path = cli_env / "templates" / "css" / "demo.css"
    assert css_path.exists()
    assert "#aabbcc" in css_path.read_text(encoding="utf-8")


def test_migrate_channel_adds_language_field(cli_env):
    yaml_path = cli_env / "config" / "channels" / "legacy.yaml"
    yaml_path.write_text(
        "slug: legacy\nname: Legacy\nkeywords: [a]\nrss_locale: hl=tr&gl=TR&ceid=TR:tr\n"
        "schedule_cron: '0 * * * *'\nduration_s: 30\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: default\n"
        "colors: {primary: '#c81e1e', accent: '#ffea3b', bg_gradient: ['#1a3b6b','#0a1a3b']}\n"
        "handle: '@legacy'\noutput_dir: output/legacy\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    args = type("Args", (), {
        "slug": "legacy", "with_dna": False,
        "config_dir": "config", "templates_dir": "templates",
    })()
    from short_bot.cli import _cmd_migrate_channel
    rc = _cmd_migrate_channel(args)
    assert rc == 0
    txt = yaml_path.read_text(encoding="utf-8")
    assert "language: tr" in txt
    assert "template: newscast" in txt   # default → newscast
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement — append to `src/short_bot/cli.py`**

```python
def _add_regenerate_dna(sub):
    p = sub.add_parser("regenerate-dna", help="Regenerate DNA + CSS for an existing channel")
    p.add_argument("--channel", required=True)
    p.add_argument("--config-dir", default="config")
    p.add_argument("--templates-dir", default="templates")
    p.set_defaults(func=_cmd_regenerate_dna)


def _add_rebuild_css(sub):
    p = sub.add_parser("rebuild-css", help="Rebuild CSS from current DNA YAML (no LLM)")
    p.add_argument("--channel", required=True)
    p.add_argument("--config-dir", default="config")
    p.add_argument("--templates-dir", default="templates")
    p.set_defaults(func=_cmd_rebuild_css)


def _add_migrate_channel(sub):
    p = sub.add_parser("migrate-channel", help="Migrate legacy YAML to new schema")
    p.add_argument("--slug", required=True)
    p.add_argument("--with-dna", action="store_true",
                   help="Generate DNA via Opus during migration")
    p.add_argument("--config-dir", default="config")
    p.add_argument("--templates-dir", default="templates")
    p.set_defaults(func=_cmd_migrate_channel)


def _cmd_regenerate_dna(args) -> int:
    config_dir = Path(args.config_dir)
    templates_dir = Path(args.templates_dir)
    yaml_path = config_dir / "channels" / f"{args.channel}.yaml"
    if not yaml_path.exists():
        print(f"Error: channel '{args.channel}' not found at {yaml_path}", file=sys.stderr)
        return 1

    cfg = load_channel(yaml_path)
    settings = load_settings(config_dir / "settings.yaml")

    print(f"Regenerating DNA via {settings.claude_models['dna']}...")
    try:
        dna = generate_dna(
            name=cfg.name, keywords=cfg.keywords, language=cfg.language,
            claude_path=settings.claude_cli_path,
            model=settings.claude_models.get("dna", "opus"),
        )
    except Exception as e:
        print(f"Error: DNA generation failed: {e}", file=sys.stderr)
        return 4

    print(f"  → new archetype={dna.archetype}")
    css = build_css_override(dna)
    css_path = templates_dir / "css" / f"{cfg.slug}.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(css, encoding="utf-8")

    # Replace the channel's dna + template
    new_cfg = ChannelConfig(
        slug=cfg.slug, name=cfg.name, keywords=cfg.keywords,
        rss_locale=cfg.rss_locale, schedule_cron=cfg.schedule_cron,
        duration_s=cfg.duration_s, min_score=cfg.min_score,
        max_candidates_per_run=cfg.max_candidates_per_run,
        template=dna.archetype,
        colors={
            "primary": dna.palette.primary,
            "accent": dna.palette.accent,
            "bg_gradient": dna.palette.bg_gradient,
        },
        handle=cfg.handle, output_dir=cfg.output_dir, enabled=cfg.enabled,
        cta_enabled=cfg.cta_enabled, cta_text=cfg.cta_text,
        cta_icons=cfg.cta_icons, cta_duration_s=cfg.cta_duration_s,
        cta_show_handle=cfg.cta_show_handle,
        language=cfg.language, dna=dna, script_model=cfg.script_model,
    )
    save_channel(yaml_path, new_cfg)
    print(f"  wrote {yaml_path} + {css_path}")
    return 0


def _cmd_rebuild_css(args) -> int:
    config_dir = Path(args.config_dir)
    templates_dir = Path(args.templates_dir)
    yaml_path = config_dir / "channels" / f"{args.channel}.yaml"
    if not yaml_path.exists():
        print(f"Error: channel '{args.channel}' not found", file=sys.stderr)
        return 1
    cfg = load_channel(yaml_path)
    if cfg.dna is None:
        print(f"Error: channel '{args.channel}' has no DNA; run create-channel or "
              f"regenerate-dna first", file=sys.stderr)
        return 5
    css = build_css_override(cfg.dna)
    css_path = templates_dir / "css" / f"{cfg.slug}.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(css, encoding="utf-8")
    print(f"Rebuilt {css_path}")
    return 0


def _cmd_migrate_channel(args) -> int:
    config_dir = Path(args.config_dir)
    templates_dir = Path(args.templates_dir)
    yaml_path = config_dir / "channels" / f"{args.slug}.yaml"
    if not yaml_path.exists():
        print(f"Error: channel '{args.slug}' not found", file=sys.stderr)
        return 1
    cfg = load_channel(yaml_path)   # loader handles backward-compat (template:default→newscast, language default tr)
    if args.with_dna:
        settings = load_settings(config_dir / "settings.yaml")
        print(f"Generating DNA via {settings.claude_models['dna']}...")
        dna = generate_dna(
            name=cfg.name, keywords=cfg.keywords, language=cfg.language,
            claude_path=settings.claude_cli_path,
            model=settings.claude_models.get("dna", "opus"),
        )
        css = build_css_override(dna)
        css_path = templates_dir / "css" / f"{cfg.slug}.css"
        css_path.parent.mkdir(parents=True, exist_ok=True)
        css_path.write_text(css, encoding="utf-8")
        cfg = ChannelConfig(
            slug=cfg.slug, name=cfg.name, keywords=cfg.keywords,
            rss_locale=cfg.rss_locale, schedule_cron=cfg.schedule_cron,
            duration_s=cfg.duration_s, min_score=cfg.min_score,
            max_candidates_per_run=cfg.max_candidates_per_run,
            template=dna.archetype,
            colors=cfg.colors, handle=cfg.handle, output_dir=cfg.output_dir,
            enabled=cfg.enabled, cta_enabled=cfg.cta_enabled, cta_text=cfg.cta_text,
            cta_icons=cfg.cta_icons, cta_duration_s=cfg.cta_duration_s,
            cta_show_handle=cfg.cta_show_handle,
            language=cfg.language, dna=dna, script_model=cfg.script_model,
        )
    save_channel(yaml_path, cfg)
    print(f"Migrated {yaml_path} (language={cfg.language}, template={cfg.template})")
    return 0
```

In `main()`, register:
```python
    _add_regenerate_dna(sub)
    _add_rebuild_css(sub)
    _add_migrate_channel(sub)
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
python -m pytest tests/test_cli_create_channel.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/short_bot/cli.py tests/test_cli_create_channel.py
git commit -m "feat(cli): regenerate-dna + rebuild-css + migrate-channel subcommands"
```

---

## Task 16: Migrate son-dakika.yaml + verify

**Files:**
- Modify: `config/channels/son-dakika.yaml`

- [ ] **Step 1: Run migration**

```bash
python -m short_bot migrate-channel --slug son-dakika
```
Expected: prints `Migrated config/channels/son-dakika.yaml (language=tr, template=newscast)`.

- [ ] **Step 2: Verify YAML still loadable**

```bash
python -m short_bot list-channels
```
Expected: `son-dakika` listed correctly.

- [ ] **Step 3: Verify still runs end-to-end (full pipeline test)**

```bash
python -m short_bot run --channel son-dakika --max 1
```
Expected: succeeds with archetype=newscast, language=tr.

- [ ] **Step 4: Commit migration**

```bash
git add config/channels/son-dakika.yaml
git commit -m "chore(channels): migrate son-dakika to new schema (language + template)"
```

---

## Task 17: templates/tabloid.html.j2

**Files:**
- Create: `templates/tabloid.html.j2`

- [ ] **Step 1: Write the template**

```html
<!DOCTYPE html>
<html lang="{{ language }}">
<head>
<meta charset="utf-8">
<title>Short — Tabloid</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@600;800;900&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --primary: #c81e1e;
    --accent: #ffea3b;
    --bg-grad-1: #1a3b6b;
    --bg-grad-2: #0a1a3b;
    --body-bg-1: #1a1a2a;
    --body-bg-2: #0a0a1a;
    --text-main: #ffffff;
    --text-muted: #cccccc;
    --font-headline: 'Bebas Neue', Impact, sans-serif;
    --font-body: 'Inter', sans-serif;
  }
  html, body { width: 1080px; height: 1920px; overflow: hidden;
    background: var(--accent); font-family: var(--font-body); color: #000; }
  .stage { position: relative; width: 1080px; height: 1920px; }

  .stage-badge {
    position: absolute; top: 20px; left: 50%; transform: translateX(-50%) rotate(-3deg);
    background: #000; color: var(--accent);
    font-size: 28px; font-weight: 900; letter-spacing: 2px;
    padding: 8px 20px;
    z-index: 10;
  }

  .header {
    padding: 110px 40px 40px;
    text-align: center;
    font-family: var(--font-headline);
    color: var(--primary);
    font-size: 180px;
    line-height: .92;
    -webkit-text-stroke: 2px #000;
    text-shadow: 6px 6px 0 #000;
    transform: rotate(-1deg);
  }
  .header .top { display: block; font-style: italic; }
  .header .bot { display: block; font-style: italic; transform: rotate(2deg); }

  .photo {
    position: relative;
    height: 760px;
    background: linear-gradient(135deg, var(--bg-grad-1), var(--bg-grad-2));
    overflow: hidden;
    border-top: 6px solid #000; border-bottom: 6px solid #000;
  }
  .photo .bg-img {
    position: absolute; inset: 0;
    background-image: url('{{ bg_image_url|default("") }}');
    background-size: cover; background-position: center;
    {% if not bg_image_url %}display: none;{% endif %}
    filter: contrast(1.1) saturate(1.2);
  }
  .photo .yellow {
    position: absolute; top: 50%; left: 0; right: 0;
    transform: translateY(-50%) rotate(-4deg);
    background: var(--accent);
    color: #000;
    font-family: var(--font-headline);
    padding: 30px 40px;
    font-size: 96px; line-height: 1;
    text-align: center;
    -webkit-text-stroke: 1px #000;
    border: 4px solid #000;
    box-shadow: 8px 8px 0 #000;
  }

  .body {
    background: var(--accent);
    padding: 30px 40px 220px;
    color: #000;
    font-size: 44px;
    line-height: 1.3;
    font-weight: 800;
    font-style: italic;
    display: -webkit-box;
    -webkit-line-clamp: 8;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .body .hl-r { background: var(--primary); color: #fff; padding: 2px 12px; font-weight: 900; }
  .body .hl-y { background: #000; color: var(--accent); padding: 2px 12px; font-weight: 900; }

  .progress {
    position: absolute; left: 0; right: 0; bottom: 84px; height: 8px;
    background: rgba(0,0,0,.2);
  }
  .progress::after {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0;
    background: var(--primary);
    animation: fill {{ duration_s }}s linear forwards;
  }
  @keyframes fill { from { width: 0; } to { width: 100%; } }

  .handle {
    position: absolute; left: 0; right: 0; bottom: 30px;
    text-align: center; color: #000;
    font-size: 32px; font-weight: 900;
  }

  /* persistent corner chips */
  .persistent {
    position: absolute;
    display: flex; align-items: center; gap: 10px;
    font-weight: 900; font-size: 32px;
    padding: 10px 18px;
    border-radius: 6px;
    color: #fff; background: #000;
    z-index: 35;
    border: 3px solid var(--accent);
  }
  .persistent .ic { font-size: 38px; }
  .persistent.like { bottom: 110px; left: 24px; transform: rotate(-3deg); }
  .persistent.sub  { bottom: 110px; right: 24px; transform: rotate(3deg); background: var(--primary); }

  /* DNA OVERRIDE */
  {{ dna_css|safe }}
</style>
</head>
<body>
<div class="stage">
  <div class="stage-badge">{{ ui_breaking }}</div>
  <div class="header">
    <span class="top">{{ script.header_top }}</span>
    <span class="bot">{{ script.header_bottom }}</span>
  </div>

  <div class="photo">
    <div class="bg-img"></div>
    <div class="yellow">{{ script.photo_overlay }}</div>
  </div>

  <div class="body">{{ body_html|safe }}</div>

  <div class="progress"></div>
  <div class="handle">{{ handle }}</div>

  <div class="persistent like"><span class="ic">❤️</span><span>{{ ui_like }}</span></div>
  <div class="persistent sub"><span class="ic">🔔</span><span>{{ ui_subscribe }}</span></div>
</div>
</body>
</html>
```

- [ ] **Step 2: Verify by render test (manual quick check)**

Update `scripts/render_test_frame.py` to point to `templates/tabloid.html.j2`, run:

```bash
python scripts/render_test_frame.py
```

Open `tmp/v1_1000ms.png` — should see yellow background with red bold italic header, blue photo band, yellow body.

- [ ] **Step 3: Commit**

```bash
git add templates/tabloid.html.j2
git commit -m "feat(templates): tabloid archetype (yellow/red, italic, exclamation style)"
```

---

## Task 18: templates/magazine.html.j2

**Files:**
- Create: `templates/magazine.html.j2`

- [ ] **Step 1: Write the template**

```html
<!DOCTYPE html>
<html lang="{{ language }}">
<head>
<meta charset="utf-8">
<title>Short — Magazine</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;1,400;1,700&family=Inter:wght@400;600&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --primary: #6b3b1a;
    --accent: #d4a056;
    --bg-grad-1: #f5f0e8;
    --bg-grad-2: #e8dfd3;
    --body-bg-1: #faf6ee;
    --body-bg-2: #efe7d8;
    --text-main: #1a1a1a;
    --text-muted: #6b6b6b;
    --font-headline: 'Playfair Display', Georgia, serif;
    --font-body: 'Inter', sans-serif;
  }
  html, body { width: 1080px; height: 1920px; overflow: hidden;
    background: linear-gradient(180deg, var(--bg-grad-1), var(--bg-grad-2));
    font-family: var(--font-body); color: var(--text-main); }
  .stage { position: relative; width: 1080px; height: 1920px; }

  .stage-badge {
    position: absolute; top: 30px; right: 30px;
    background: var(--primary); color: var(--bg-grad-1);
    font-size: 18px; font-weight: 600; letter-spacing: 4px;
    padding: 6px 14px;
    z-index: 10;
  }

  .header {
    padding: 70px 80px 30px;
    color: var(--text-main);
  }
  .header .kicker {
    font-size: 22px; letter-spacing: 5px;
    color: var(--primary);
    margin-bottom: 30px;
    font-weight: 600;
  }
  .header .top, .header .bot {
    display: block;
    font-family: var(--font-headline);
    font-style: italic;
    font-size: 110px;
    line-height: .98;
    color: var(--text-main);
    font-weight: 400;
  }

  .photo {
    position: relative;
    margin: 30px 60px;
    height: 540px;
    background: linear-gradient(135deg, #aaa, #555);
    overflow: hidden;
    border: 14px solid #fff;
    box-shadow: 0 14px 40px rgba(0,0,0,.25);
  }
  .photo .bg-img {
    position: absolute; inset: 0;
    background-image: url('{{ bg_image_url|default("") }}');
    background-size: cover; background-position: center;
    {% if not bg_image_url %}display: none;{% endif %}
  }
  .photo .caption {
    position: absolute; bottom: 0; left: 0; right: 0;
    background: rgba(255,255,255,.92);
    padding: 14px 20px;
    font-family: var(--font-headline);
    font-style: italic;
    font-size: 28px;
    color: var(--text-main);
  }

  .body {
    padding: 30px 80px 220px;
    font-family: var(--font-headline);
    font-size: 38px;
    line-height: 1.55;
    color: var(--text-main);
    font-style: normal;
    display: -webkit-box;
    -webkit-line-clamp: 8;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .body .hl-r { color: var(--primary); text-decoration: underline; text-decoration-thickness: 4px; text-underline-offset: 6px; font-weight: 700; }
  .body .hl-y { color: var(--accent); text-decoration: underline; text-decoration-thickness: 4px; text-underline-offset: 6px; font-weight: 700; }

  .progress {
    position: absolute; left: 0; right: 0; bottom: 84px; height: 4px;
    background: rgba(107,59,26,.15);
  }
  .progress::after {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0;
    background: var(--primary);
    animation: fill {{ duration_s }}s linear forwards;
  }
  @keyframes fill { from { width: 0; } to { width: 100%; } }

  .handle {
    position: absolute; left: 0; right: 0; bottom: 30px;
    text-align: center; color: var(--primary);
    font-size: 26px; letter-spacing: 4px; font-weight: 600;
  }

  .persistent {
    position: absolute;
    display: flex; align-items: center; gap: 10px;
    font-family: var(--font-body); font-weight: 600; font-size: 24px;
    padding: 10px 18px;
    border-radius: 50px;
    color: var(--text-main);
    background: rgba(255,255,255,.95);
    border: 1px solid var(--primary);
    z-index: 35;
    box-shadow: 0 4px 16px rgba(0,0,0,.1);
  }
  .persistent .ic { font-size: 28px; }
  .persistent.like { bottom: 120px; left: 30px; }
  .persistent.sub  { bottom: 120px; right: 30px; background: var(--primary); color: var(--bg-grad-1); }

  /* DNA OVERRIDE */
  {{ dna_css|safe }}
</style>
</head>
<body>
<div class="stage">
  <div class="stage-badge">{{ ui_breaking }}</div>
  <div class="header">
    <div class="kicker">{{ script.category }}</div>
    <span class="top">{{ script.header_top }}</span>
    <span class="bot">{{ script.header_bottom }}</span>
  </div>

  <div class="photo">
    <div class="bg-img"></div>
    <div class="caption">{{ script.photo_overlay }}</div>
  </div>

  <div class="body">{{ body_html|safe }}</div>

  <div class="progress"></div>
  <div class="handle">{{ handle }}</div>

  <div class="persistent like"><span class="ic">❤️</span><span>{{ ui_like }}</span></div>
  <div class="persistent sub"><span class="ic">🔔</span><span>{{ ui_subscribe }}</span></div>
</div>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/magazine.html.j2
git commit -m "feat(templates): magazine archetype (beige, serif italic, polaroid frame)"
```

---

## Task 19: templates/kinetic.html.j2

**Files:**
- Create: `templates/kinetic.html.j2`

- [ ] **Step 1: Write the template**

```html
<!DOCTYPE html>
<html lang="{{ language }}">
<head>
<meta charset="utf-8">
<title>Short — Kinetic</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;700&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --primary: #00ff88;
    --accent: #ffffff;
    --bg-grad-1: #0a0a0a;
    --bg-grad-2: #000000;
    --body-bg-1: #0a0a0a;
    --body-bg-2: #000000;
    --text-main: #ffffff;
    --text-muted: #888888;
    --font-headline: 'Anton', Impact, sans-serif;
    --font-body: 'Inter', sans-serif;
  }
  html, body { width: 1080px; height: 1920px; overflow: hidden;
    background: var(--bg-grad-1); font-family: var(--font-body); color: var(--text-main); }
  .stage { position: relative; width: 1080px; height: 1920px; }

  .stage-badge {
    position: absolute; top: 50px; left: 50%; transform: translateX(-50%);
    background: transparent; color: var(--primary);
    font-size: 24px; font-weight: 700; letter-spacing: 8px;
    padding: 6px 14px;
    border: 2px solid var(--primary);
    z-index: 10;
  }

  .header {
    position: absolute; top: 25%; left: 0; right: 0;
    text-align: center;
    font-family: var(--font-headline);
  }
  .header .top {
    display: block;
    font-size: 320px;
    line-height: .9;
    color: var(--primary);
    text-shadow: 0 0 40px rgba(0,255,136,.6), 0 0 80px rgba(0,255,136,.3);
  }
  .header .bot {
    display: block;
    font-size: 80px;
    color: var(--text-main);
    letter-spacing: 14px;
    margin-top: 20px;
  }

  .photo {
    display: none;
  }

  .body {
    position: absolute; bottom: 240px; left: 60px; right: 60px;
    text-align: center;
    font-size: 38px;
    color: var(--text-muted);
    line-height: 1.4;
    font-weight: 400;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .body .hl-r {
    color: var(--primary);
    text-shadow: 0 0 8px var(--primary);
    font-weight: 700;
  }
  .body .hl-y {
    color: var(--accent);
    text-shadow: 0 0 8px var(--accent);
    font-weight: 700;
  }

  .progress {
    position: absolute; left: 0; right: 0; bottom: 84px; height: 2px;
    background: rgba(255,255,255,.15);
  }
  .progress::after {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0;
    background: var(--primary);
    box-shadow: 0 0 16px var(--primary);
    animation: fill {{ duration_s }}s linear forwards;
  }
  @keyframes fill { from { width: 0; } to { width: 100%; } }

  .handle {
    position: absolute; left: 0; right: 0; bottom: 30px;
    text-align: center; color: var(--text-muted);
    font-size: 24px; letter-spacing: 4px; font-weight: 700;
  }

  .persistent {
    position: absolute;
    display: flex; align-items: center; gap: 8px;
    font-weight: 700; font-size: 22px; letter-spacing: 2px;
    padding: 8px 14px;
    border-radius: 2px;
    color: var(--text-main);
    background: transparent;
    border: 2px solid var(--primary);
    z-index: 35;
  }
  .persistent .ic { font-size: 26px; }
  .persistent.like { bottom: 120px; left: 30px; }
  .persistent.sub  { bottom: 120px; right: 30px; background: var(--primary); color: #000; border: 2px solid var(--primary); }

  /* DNA OVERRIDE */
  {{ dna_css|safe }}
</style>
</head>
<body>
<div class="stage">
  <div class="stage-badge">{{ ui_breaking }}</div>
  <div class="header">
    <span class="top">{{ script.header_top }}</span>
    <span class="bot">{{ script.header_bottom }}</span>
  </div>

  <div class="body">{{ body_html|safe }}</div>

  <div class="progress"></div>
  <div class="handle">{{ handle }}</div>

  <div class="persistent like"><span class="ic">❤️</span><span>{{ ui_like }}</span></div>
  <div class="persistent sub"><span class="ic">🔔</span><span>{{ ui_subscribe }}</span></div>
</div>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/kinetic.html.j2
git commit -m "feat(templates): kinetic archetype (typography-led, neon, no photo)"
```

---

## Task 20: templates/dark-tech.html.j2

**Files:**
- Create: `templates/dark-tech.html.j2`

- [ ] **Step 1: Write the template**

```html
<!DOCTYPE html>
<html lang="{{ language }}">
<head>
<meta charset="utf-8">
<title>Short — Dark Tech</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@400;700&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --primary: #ff00ff;
    --accent: #00ffff;
    --bg-grad-1: #1a0a3a;
    --bg-grad-2: #0a0a1a;
    --body-bg-1: #0a0a14;
    --body-bg-2: #000000;
    --text-main: #ffffff;
    --text-muted: #00ff88;
    --font-headline: 'JetBrains Mono', 'Courier New', monospace;
    --font-body: 'JetBrains Mono', 'Courier New', monospace;
  }
  html, body { width: 1080px; height: 1920px; overflow: hidden;
    background: radial-gradient(ellipse at top, var(--bg-grad-1), var(--bg-grad-2) 70%);
    font-family: var(--font-body); color: var(--text-main); }
  .stage { position: relative; width: 1080px; height: 1920px; }

  .stage-badge {
    position: absolute; top: 24px; right: 24px;
    background: var(--accent); color: #000;
    font-family: var(--font-headline);
    font-size: 18px; font-weight: 700; letter-spacing: 1px;
    padding: 4px 10px;
    z-index: 10;
  }

  .header {
    padding: 60px 50px 30px;
    font-family: var(--font-headline);
  }
  .header .top {
    display: block;
    color: var(--accent);
    font-size: 56px;
    font-weight: 700;
    margin-bottom: 14px;
  }
  .header .bot {
    display: block;
    color: var(--text-main);
    font-size: 90px;
    line-height: 1.05;
    border-left: 6px solid var(--primary);
    padding-left: 24px;
    font-weight: 700;
  }

  .photo {
    position: relative;
    margin: 30px 50px;
    height: 460px;
    background: linear-gradient(135deg, var(--bg-grad-1), var(--bg-grad-2));
    overflow: hidden;
    border: 1px solid var(--accent);
  }
  .photo .bg-img {
    position: absolute; inset: 0;
    background-image: url('{{ bg_image_url|default("") }}');
    background-size: cover; background-position: center;
    {% if not bg_image_url %}display: none;{% endif %}
    filter: hue-rotate(45deg) saturate(.8) brightness(.7);
  }
  .photo::after {
    content: '';
    position: absolute; inset: 0;
    background: repeating-linear-gradient(0deg, transparent 0, transparent 3px, rgba(0,255,255,.05) 3px, rgba(0,255,255,.05) 4px);
    pointer-events: none;
  }
  .photo .label {
    position: absolute; bottom: 10px; left: 14px;
    font-family: var(--font-headline);
    font-size: 22px;
    color: var(--accent);
    background: rgba(0,0,0,.7);
    padding: 4px 10px;
  }

  .body {
    padding: 30px 50px 220px;
    font-family: var(--font-headline);
    font-size: 36px;
    line-height: 1.4;
    color: var(--text-main);
    display: -webkit-box;
    -webkit-line-clamp: 8;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .body .hl-r {
    color: var(--primary);
    text-shadow: 0 0 6px var(--primary);
    font-weight: 700;
  }
  .body .hl-y {
    color: var(--accent);
    text-shadow: 0 0 6px var(--accent);
    font-weight: 700;
  }

  .progress {
    position: absolute; left: 0; right: 0; bottom: 84px; height: 4px;
    background: rgba(0,255,255,.15);
  }
  .progress::after {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0;
    background: var(--accent);
    box-shadow: 0 0 12px var(--accent);
    animation: fill {{ duration_s }}s linear forwards;
  }
  @keyframes fill { from { width: 0; } to { width: 100%; } }

  .handle {
    position: absolute; left: 0; right: 0; bottom: 30px;
    text-align: center; color: var(--text-muted);
    font-family: var(--font-headline);
    font-size: 22px; font-weight: 700;
  }

  .persistent {
    position: absolute;
    display: flex; align-items: center; gap: 8px;
    font-family: var(--font-headline);
    font-weight: 700; font-size: 22px;
    padding: 6px 14px;
    border-radius: 2px;
    color: var(--text-main);
    background: rgba(0,0,0,.85);
    border: 1px solid var(--accent);
    z-index: 35;
  }
  .persistent .ic { font-size: 26px; }
  .persistent.like { bottom: 120px; left: 30px; }
  .persistent.sub  { bottom: 120px; right: 30px; background: var(--primary); color: #fff; border: 1px solid var(--primary); }

  /* DNA OVERRIDE */
  {{ dna_css|safe }}
</style>
</head>
<body>
<div class="stage">
  <div class="stage-badge">{{ ui_breaking }}</div>
  <div class="header">
    <span class="top">{{ script.header_top }}</span>
    <span class="bot">{{ script.header_bottom }}</span>
  </div>

  <div class="photo">
    <div class="bg-img"></div>
    <div class="label">{{ script.photo_overlay }}</div>
  </div>

  <div class="body">{{ body_html|safe }}</div>

  <div class="progress"></div>
  <div class="handle">{{ handle }}</div>

  <div class="persistent like"><span class="ic">❤️</span><span>{{ ui_like }}</span></div>
  <div class="persistent sub"><span class="ic">🔔</span><span>{{ ui_subscribe }}</span></div>
</div>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/dark-tech.html.j2
git commit -m "feat(templates): dark-tech archetype (cyber, monospace, neon, scanlines)"
```

---

## Task 21: templates/stadium.html.j2

**Files:**
- Create: `templates/stadium.html.j2`

- [ ] **Step 1: Write the template**

```html
<!DOCTYPE html>
<html lang="{{ language }}">
<head>
<meta charset="utf-8">
<title>Short — Stadium</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Oswald:wght@400;700&family=Inter:wght@600;800&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --primary: #0a4d2a;
    --accent: #ffd700;
    --bg-grad-1: #1a8b3a;
    --bg-grad-2: #0a4d1a;
    --body-bg-1: #0a1a0a;
    --body-bg-2: #000000;
    --text-main: #ffffff;
    --text-muted: #aaffaa;
    --font-headline: 'Oswald', Impact, sans-serif;
    --font-body: 'Inter', sans-serif;
  }
  html, body { width: 1080px; height: 1920px; overflow: hidden;
    background: linear-gradient(180deg, var(--body-bg-1), var(--body-bg-2));
    font-family: var(--font-body); color: var(--text-main); }
  .stage { position: relative; width: 1080px; height: 1920px; }

  .stage-badge {
    position: absolute; top: 16px; right: 16px;
    background: var(--accent); color: var(--primary);
    font-family: var(--font-headline);
    font-size: 22px; font-weight: 700; letter-spacing: 2px;
    padding: 5px 12px;
    z-index: 10;
  }

  .header {
    background: linear-gradient(135deg, var(--primary), var(--bg-grad-2));
    padding: 50px 40px 40px;
    text-align: center;
    font-family: var(--font-headline);
    color: var(--accent);
    border-bottom: 8px solid var(--accent);
  }
  .header .top {
    display: block;
    font-size: 200px;
    line-height: .95;
    letter-spacing: 8px;
    text-shadow: 6px 6px 0 #000;
    -webkit-text-stroke: 2px #000;
  }
  .header .bot {
    display: block;
    font-size: 60px;
    color: var(--text-main);
    letter-spacing: 6px;
    margin-top: 14px;
  }

  .photo {
    position: relative;
    height: 580px;
    background: linear-gradient(180deg, var(--bg-grad-1), var(--bg-grad-2));
    overflow: hidden;
  }
  .photo .bg-img {
    position: absolute; inset: 0;
    background-image: url('{{ bg_image_url|default("") }}');
    background-size: cover; background-position: center;
    {% if not bg_image_url %}display: none;{% endif %}
  }
  .photo::after {
    content: '';
    position: absolute; inset: 0;
    background: linear-gradient(180deg, transparent 60%, rgba(0,0,0,.8));
  }
  .photo .yellow {
    position: absolute; bottom: 30px; left: 30px; right: 30px;
    background: var(--accent);
    color: var(--primary);
    font-family: var(--font-headline);
    padding: 22px 30px;
    font-size: 64px;
    text-align: center;
    letter-spacing: 2px;
    transform: skewX(-10deg);
    box-shadow: 0 8px 0 #000;
    z-index: 1;
  }

  .body {
    padding: 40px 50px 220px;
    font-size: 42px;
    line-height: 1.4;
    font-weight: 600;
    color: var(--text-main);
    display: -webkit-box;
    -webkit-line-clamp: 7;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .body .hl-r {
    background: var(--accent);
    color: var(--primary);
    padding: 2px 12px;
    font-weight: 800;
  }
  .body .hl-y {
    color: var(--accent);
    text-shadow: 0 0 4px var(--accent);
    font-weight: 800;
  }

  .progress {
    position: absolute; left: 0; right: 0; bottom: 84px; height: 8px;
    background: rgba(255,255,255,.15);
  }
  .progress::after {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0;
    background: var(--accent);
    animation: fill {{ duration_s }}s linear forwards;
  }
  @keyframes fill { from { width: 0; } to { width: 100%; } }

  .handle {
    position: absolute; left: 0; right: 0; bottom: 30px;
    text-align: center; color: var(--accent);
    font-family: var(--font-headline);
    font-size: 32px; letter-spacing: 4px;
  }

  .persistent {
    position: absolute;
    display: flex; align-items: center; gap: 10px;
    font-weight: 800; font-size: 28px; letter-spacing: 1px;
    padding: 10px 18px;
    border-radius: 999px;
    color: var(--text-main);
    background: rgba(0,0,0,.85);
    border: 3px solid var(--accent);
    z-index: 35;
  }
  .persistent .ic { font-size: 32px; }
  .persistent.like { bottom: 120px; left: 30px; }
  .persistent.sub  { bottom: 120px; right: 30px; background: var(--accent); color: var(--primary); border-color: var(--primary); }

  /* DNA OVERRIDE */
  {{ dna_css|safe }}
</style>
</head>
<body>
<div class="stage">
  <div class="stage-badge">{{ ui_breaking }}</div>
  <div class="header">
    <span class="top">{{ script.header_top }}</span>
    <span class="bot">{{ script.header_bottom }}</span>
  </div>

  <div class="photo">
    <div class="bg-img"></div>
    <div class="yellow">{{ script.photo_overlay }}</div>
  </div>

  <div class="body">{{ body_html|safe }}</div>

  <div class="progress"></div>
  <div class="handle">{{ handle }}</div>

  <div class="persistent like"><span class="ic">❤️</span><span>{{ ui_like }}</span></div>
  <div class="persistent sub"><span class="ic">🔔</span><span>{{ ui_subscribe }}</span></div>
</div>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/stadium.html.j2
git commit -m "feat(templates): stadium archetype (sports, green field, score banner)"
```

---

## Task 22: templates/meme.html.j2

**Files:**
- Create: `templates/meme.html.j2`

- [ ] **Step 1: Write the template**

```html
<!DOCTYPE html>
<html lang="{{ language }}">
<head>
<meta charset="utf-8">
<title>Short — Meme</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@600;800;900&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --primary: #3b8bff;
    --accent: #ffea3b;
    --bg-grad-1: #3b8bff;
    --bg-grad-2: #ffea3b;
    --body-bg-1: #ffffff;
    --body-bg-2: #f0f0f0;
    --text-main: #ffffff;
    --text-muted: #000000;
    --font-headline: Impact, 'Arial Black', 'Inter', sans-serif;
    --font-body: 'Inter', sans-serif;
  }
  html, body { width: 1080px; height: 1920px; overflow: hidden;
    background: linear-gradient(180deg, var(--bg-grad-1) 50%, var(--bg-grad-2) 50%);
    font-family: var(--font-body); color: var(--text-main); }
  .stage { position: relative; width: 1080px; height: 1920px; }

  .stage-badge {
    position: absolute; top: 20px; right: 20px;
    background: #fff; color: #000;
    font-family: var(--font-headline);
    font-size: 22px; font-weight: 900; letter-spacing: 2px;
    padding: 6px 14px;
    border: 3px solid #000;
    z-index: 10;
  }

  .header {
    position: absolute; top: 90px; left: 0; right: 0;
    text-align: center;
    font-family: var(--font-headline);
    color: #fff;
    -webkit-text-stroke: 5px #000;
    paint-order: stroke fill;
  }
  .header .top {
    display: block;
    font-size: 160px;
    line-height: 1;
    letter-spacing: 2px;
  }
  .header .bot {
    display: none;
  }

  .photo {
    position: absolute; top: 30%; left: 60px; right: 60px;
    height: 700px;
    background: #fff;
    overflow: hidden;
    border: 8px solid #000;
    box-shadow: 12px 12px 0 #000;
  }
  .photo .bg-img {
    position: absolute; inset: 0;
    background-image: url('{{ bg_image_url|default("") }}');
    background-size: cover; background-position: center;
    {% if not bg_image_url %}display: none;{% endif %}
  }
  .photo .overlay-text {
    position: absolute; bottom: 14px; left: 14px; right: 14px;
    background: #fff;
    color: #000;
    font-family: var(--font-body);
    font-weight: 800;
    padding: 8px 14px;
    text-align: center;
    font-size: 26px;
  }

  .body {
    position: absolute; bottom: 240px; left: 0; right: 0;
    text-align: center;
    font-family: var(--font-headline);
    color: #fff;
    font-size: 110px;
    line-height: 1;
    -webkit-text-stroke: 4px #000;
    paint-order: stroke fill;
    padding: 0 40px;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .body .hl-r { color: #ff3b3b; }
  .body .hl-y { color: var(--accent); }

  .progress {
    position: absolute; left: 0; right: 0; bottom: 84px; height: 10px;
    background: rgba(0,0,0,.4);
    border-top: 2px solid #000; border-bottom: 2px solid #000;
  }
  .progress::after {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0;
    background: var(--accent);
    animation: fill {{ duration_s }}s linear forwards;
  }
  @keyframes fill { from { width: 0; } to { width: 100%; } }

  .handle {
    position: absolute; left: 0; right: 0; bottom: 30px;
    text-align: center; color: #000;
    font-family: var(--font-headline);
    font-size: 28px; letter-spacing: 2px;
  }

  .persistent {
    position: absolute;
    display: flex; align-items: center; gap: 8px;
    font-family: var(--font-headline);
    font-weight: 900; font-size: 28px;
    padding: 8px 16px;
    border-radius: 6px;
    color: #fff;
    background: #000;
    border: 3px solid var(--accent);
    z-index: 35;
  }
  .persistent .ic { font-size: 32px; }
  .persistent.like { bottom: 120px; left: 24px; }
  .persistent.sub  { bottom: 120px; right: 24px; background: var(--accent); color: #000; border-color: #000; }

  /* DNA OVERRIDE */
  {{ dna_css|safe }}
</style>
</head>
<body>
<div class="stage">
  <div class="stage-badge">{{ ui_breaking }}</div>
  <div class="header">
    <span class="top">{{ script.header_top }}</span>
  </div>

  <div class="photo">
    <div class="bg-img"></div>
    {% if script.photo_overlay %}<div class="overlay-text">{{ script.photo_overlay }}</div>{% endif %}
  </div>

  <div class="body">{{ script.header_bottom }}</div>

  <div class="progress"></div>
  <div class="handle">{{ handle }}</div>

  <div class="persistent like"><span class="ic">❤️</span><span>{{ ui_like }}</span></div>
  <div class="persistent sub"><span class="ic">🔔</span><span>{{ ui_subscribe }}</span></div>
</div>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add templates/meme.html.j2
git commit -m "feat(templates): meme archetype (Impact, top/bottom text, comic vibe)"
```

---

## Task 23: Snapshot tests + final smoke

**Files:**
- Create: `tests/test_renderer_snapshot.py`
- Create: `tests/fixtures/snapshots/<archetype>.png` (generated)

- [ ] **Step 1: Write snapshot test (`tests/test_renderer_snapshot.py`)**

```python
"""Render snapshot tests: each archetype rendered with a fixed Script must match a stored PNG.

Snapshots are generated on first run with SAVE_SNAPSHOTS=1 env var. On normal runs they're
compared (PIL pixel diff < 5%).
"""
import os
from pathlib import Path

import pytest
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

from short_bot.models import Script, Highlight, RenderJob
from short_bot.renderer import build_html

ARCHETYPES = ["newscast", "tabloid", "magazine", "kinetic", "dark-tech", "stadium", "meme"]
SNAPSHOT_DIR = Path(__file__).parent / "fixtures" / "snapshots"
DIFF_THRESHOLD = 0.05  # 5% pixel diff allowed


def _fixed_script():
    return Script(
        header_top="ARA ZAM",
        header_bottom="GELDİ Mİ?",
        photo_overlay="MİLYONLARCA ÇALIŞAN BEKLİYOR",
        body_paragraph=(
            "Asgari ücrete temmuzda ara zam gelip gelmeyeceği milyonlarca çalışanı "
            "yakından ilgilendiriyor. Yüksek enflasyon nedeniyle alım gücü eridi."
        ),
        highlights=[Highlight(text="ara zam", color="yellow")],
        category="EKONOMİ",
        mood="neutral",
    )


def _render_to_png(archetype: str, out_path: Path):
    job = RenderJob(
        script=_fixed_script(),
        bg_image_path=None,
        music_path=Path("dummy.mp3"),
        channel_colors={"primary": "#c81e1e", "accent": "#ffea3b",
                         "bg_gradient": ["#1a3b6b", "#0a1a3b"]},
        handle="@TestKanal", duration_s=6,
        language="tr", cta_enabled=False,
    )
    template = Path(f"templates/{archetype}.html.j2")
    html = build_html(job, template, ui_labels={
        "like": "BEĞEN", "subscribe": "ABONE OL",
        "share": "PAYLAŞ", "breaking": "SON DAKİKA",
    })
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.add_init_script("document.getAnimations().forEach(a => a.pause());")
        page.set_content(html, wait_until="networkidle")
        page.evaluate(
            "(t) => { document.getAnimations().forEach(a => { a.currentTime = t; }); }",
            500,
        )
        page.screenshot(path=str(out_path))
        b.close()


@pytest.mark.slow
@pytest.mark.parametrize("archetype", ARCHETYPES)
def test_archetype_renders_close_to_snapshot(archetype, tmp_path):
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snap = SNAPSHOT_DIR / f"{archetype}.png"
    actual = tmp_path / f"{archetype}.png"
    _render_to_png(archetype, actual)

    if os.environ.get("SAVE_SNAPSHOTS") == "1" or not snap.exists():
        # First-run capture mode
        snap.write_bytes(actual.read_bytes())
        pytest.skip(f"Saved snapshot {snap}")

    img1 = Image.open(snap).convert("RGB")
    img2 = Image.open(actual).convert("RGB")
    assert img1.size == img2.size, f"Size mismatch: {img1.size} vs {img2.size}"
    diff = ImageChops.difference(img1, img2)
    bbox = diff.getbbox()
    if bbox is None:
        return
    diff_pixels = sum(1 for px in diff.getdata() if px != (0,0,0))
    total_pixels = img1.size[0] * img1.size[1]
    diff_ratio = diff_pixels / total_pixels
    assert diff_ratio < DIFF_THRESHOLD, (
        f"{archetype}: diff_ratio={diff_ratio:.3f} > threshold={DIFF_THRESHOLD}"
    )
```

- [ ] **Step 2: Generate baseline snapshots**

```bash
SAVE_SNAPSHOTS=1 python -m pytest tests/test_renderer_snapshot.py -v
```
Expected: 7 SKIP (saving snapshots); `tests/fixtures/snapshots/` now has 7 PNGs.

- [ ] **Step 3: Run again to confirm snapshots match**

```bash
python -m pytest tests/test_renderer_snapshot.py -v
```
Expected: 7 PASSED.

- [ ] **Step 4: Final test sweep**

```bash
python -m pytest -v
```
Expected: ~135 passed (86 baseline + ~50 new).

- [ ] **Step 5: Manual end-to-end smoke**

Create a 2nd channel in a different language + archetype:

```bash
python -m short_bot create-channel \
    --name "Spor Short DE" --language de \
    --keywords "Bundesliga,Bayern" \
    --topic-hint "Almanca futbol kanalı"
```

Wait for Opus call. Then:

```bash
python -m short_bot run --channel spor-short-de --max 1
```

Open the produced mp4, compare with son-dakika output:
- [ ] Different layout (newscast vs stadium)
- [ ] Different colors (red/blue vs green/gold)
- [ ] German text in chips ("ABONNIEREN") vs Turkish ("ABONE OL")
- [ ] Body paragraph in German

- [ ] **Step 6: Commit snapshots + final**

```bash
git add tests/test_renderer_snapshot.py tests/fixtures/snapshots/
git commit -m "test(snapshots): per-archetype render baseline + smoke"

git tag -a v0.2.0-channel-dna -m "Phase 2 partial: Channel DNA + multi-language"
```

---

## Phase Complete

**What works after this plan:**
- `python -m short_bot create-channel` generates a unique channel via Opus DNA
- 5 languages supported (TR, EN, DE, ES, FR)
- 7 visual archetypes + per-channel CSS overrides
- Existing `son-dakika` migrated to new schema, still works
- Per-channel script tone, search query template, UI label localization
- `regenerate-dna`, `rebuild-css`, `migrate-channel` for ops

**Next phase (separate spec/plan):** Web panel (Flask + HTMX + APScheduler) for browser-based channel management.
