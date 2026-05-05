# Custom DNA CSS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `DnaSpec.custom_css` field that Opus fills with free-form CSS during DNA generation, plus a smoke-render test that catches broken layouts before saving.

**Architecture:** Single new Pydantic field on `DnaSpec`. Prompt extension in `build_dna_prompt` lists what's allowed/forbidden. `build_css_override` appends `custom_css` after the existing structural CSS so Opus can override colors and add decorations. New `dna_smoke.py` module renders one frame via Playwright after DNA generation; checks file size + pixel stddev to catch blank/broken renders. Wizard save and `regenerate_dna` endpoint invoke the smoke check and refuse to persist failing DNA.

**Tech Stack:** Python 3.11+, Pydantic 2, Jinja2, Playwright (chromium headless), Pillow (PIL.ImageStat). No new dependencies.

**Spec:** [docs/superpowers/specs/2026-05-06-custom-dna-css-design.md](../specs/2026-05-06-custom-dna-css-design.md)

---

## File Structure

**New files:**
- `src/short_bot/dna_smoke.py` — `smoke_render_dna(dna, *, channel_template, templates_dir, settings, language="tr") -> tuple[bool, str]`
- `tests/test_dna_smoke.py` — 3 tests for the smoke helper

**Modified files:**
- `src/short_bot/dna.py` — add `custom_css` field to `DnaSpec`; extend `build_dna_prompt` with the "ÖZGÜR CSS" section + JSON schema entry; append `custom_css` in `build_css_override`
- `src/short_bot/web/routes/channel_new.py` — call `smoke_render_dna` between `generate_dna` and `save_channel`; flash + redirect on failure
- `src/short_bot/web/routes/channel_edit.py` — same wiring inside `regenerate_dna`
- `tests/test_dna.py` — extend with `custom_css` field + prompt + override append tests
- `tests/test_web_channel_new_generator.py` — extend with smoke fail assertion (skip on Playwright unavailable)

**Important constraint:** PIL is already used elsewhere in the project (e.g. `tests/test_renderer_snapshot.py` calls `Image.open(...).getdata()`). Confirmed dependency, no install needed.

---

## Task 1: `DnaSpec.custom_css` field

**Files:**
- Modify: `src/short_bot/dna.py` (add field to DnaSpec)
- Test: `tests/test_dna.py` (extend)

- [ ] **Step 1.1: Write failing tests**

Append to `tests/test_dna.py`:

```python
def test_dna_custom_css_default_empty():
    """custom_css defaults to empty string when not provided."""
    dna = DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b","#0a1a3b"],
                           body_bg=["#1a1a2a","#0a0a1a"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
    )
    assert dna.custom_css == ""


def test_dna_custom_css_accepts_value():
    dna = DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b","#0a1a3b"],
                           body_bg=["#1a1a2a","#0a0a1a"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
        custom_css="body { background: url(data:image/svg+xml,...); }",
    )
    assert "background:" in dna.custom_css


def test_dna_custom_css_max_length_enforced():
    long_css = "/* x */" * 1500   # ~9000 chars, exceeds 8000 limit
    with pytest.raises(ValidationError):
        DnaSpec(
            archetype="newscast",
            palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                               bg_gradient=["#1a3b6b","#0a1a3b"],
                               body_bg=["#1a1a2a","#0a0a1a"]),
            fonts=DnaFonts(),
            tone=DnaTone(voice="x", style="y"),
            persona_summary="x",
            custom_css=long_css,
        )
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dna.py::test_dna_custom_css_default_empty tests/test_dna.py::test_dna_custom_css_accepts_value tests/test_dna.py::test_dna_custom_css_max_length_enforced -v`
Expected: 3 fails — `AttributeError: 'DnaSpec' object has no attribute 'custom_css'` and `ValidationError` not raised on long input.

- [ ] **Step 1.3: Add `custom_css` field to `DnaSpec`**

In `src/short_bot/dna.py`, find the `DnaSpec` class (around line 51). Append `custom_css` field at the end:

```python
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
    custom_css: str = Field(default="", max_length=8000)
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dna.py::test_dna_custom_css_default_empty tests/test_dna.py::test_dna_custom_css_accepts_value tests/test_dna.py::test_dna_custom_css_max_length_enforced -v`
Expected: 3 passed

- [ ] **Step 1.5: Run full suite to confirm no regression**

Run: `python -m pytest -q`
Expected: 241 passed (existing 238 + 3 new)

- [ ] **Step 1.6: Commit**

```bash
git add src/short_bot/dna.py tests/test_dna.py
git commit -m "feat(dna): add custom_css field to DnaSpec (max 8000 chars)

Defaults to empty string for backward compat — existing channels load
unchanged. Phase 6 free-form CSS field for Opus-generated visual richness."
```

---

## Task 2: Extend `build_dna_prompt` with "ÖZGÜR CSS" section

**Files:**
- Modify: `src/short_bot/dna.py` (extend `build_dna_prompt`)
- Test: `tests/test_dna.py`

- [ ] **Step 2.1: Write failing tests**

Append to `tests/test_dna.py`:

```python
def test_build_dna_prompt_includes_custom_css_section():
    p = build_dna_prompt(name="Test", keywords=["x"], language="tr")
    assert "ÖZGÜR CSS" in p
    assert "custom_css" in p


def test_build_dna_prompt_lists_forbidden_css_properties():
    p = build_dna_prompt(name="Test", keywords=["x"], language="tr")
    assert "position" in p
    assert "YASAKLI" in p
    assert ".header" in p
    assert ".body" in p
    assert ".persistent" in p


def test_build_dna_prompt_json_schema_includes_custom_css():
    p = build_dna_prompt(name="Test", keywords=["x"], language="tr")
    assert '"custom_css"' in p
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dna.py -k "custom_css" -v`
Expected: 3 fails (3 from Task 1 still pass; the new prompt tests fail).

- [ ] **Step 2.3: Read current `build_dna_prompt` to find insertion point**

Run: `grep -n "persona_summary" D:/short/src/short_bot/dna.py | head`

You'll see the JSON schema lines listing the output fields. The schema currently ends with `"persona_summary": "..."`. We'll add `"custom_css": "..."` after it.

- [ ] **Step 2.4: Extend `build_dna_prompt`**

In `src/short_bot/dna.py`, find the multi-line return string of `build_dna_prompt`. Two changes:

**A.** Find the section ending with `SEARCH_QUERY_TEMPLATE:` block. AFTER that block (and before `ÇIKTI: SADECE...` line), insert this new section:

```
ÖZGÜR CSS (custom_css):
Yapısal alanları (palette, fonts, banner_shape, vb.) yukarıda doldurduktan sonra,
kanala özel görsel zenginlik için ek bir CSS bloğu yaz.

✓ İZİNLİ:
- background-image / repeating gradient / pattern (body, .stage, ::before, ::after)
- ::before / ::after dekoratif elementler (HER selector için)
- text-shadow, -webkit-text-stroke, gradient text (.header .top, .header .bot, .body)
- filter / mix-blend-mode / box-shadow / border-radius
- photo treatment (.photo border, mask, filter)
- chip dekorasyonu (.persistent ::before/::after, decorative borders)
- Custom @keyframes (sadece YENİ dekoratif elementler için)

✗ YASAKLI (KESİNLİKLE DOKUNMA — render bozar):
- position / top / bottom / left / right / width / height değerleri
  .header, .body, .persistent, .progress, .handle, .stage selector'larında
- z-index 100'den büyük (CTA layer çakışmaması için)
- mevcut @keyframes'leri (fill, ken-burns vb) override etme

ÖRNEK:
- Magazine: bg radial-gradient + .photo polaroid frame + .body italic
- Tech: bg scanline pattern + .header text-stroke + .persistent neon glow
- Romance: bg pink gradient + heart pattern overlay + script font shadow

Çıktı: 1500-3000 karakter arası ham CSS, başka açıklama yazma. Boş bırakma.
```

**B.** In the JSON schema near the end of the same prompt string, find the line:

```
  "persona_summary": "..."
}}
```

Change it to:

```
  "persona_summary": "...",
  "custom_css": "<1500-3000 karakter ham CSS>"
}}
```

- [ ] **Step 2.5: Run tests to verify they pass**

Run: `python -m pytest tests/test_dna.py -k "custom_css" -v`
Expected: 6 passed (3 from Task 1 + 3 new)

- [ ] **Step 2.6: Commit**

```bash
git add src/short_bot/dna.py tests/test_dna.py
git commit -m "feat(dna): prompt asks Opus for custom_css with explicit allow/deny lists

Phase 6 prompt extension: lists allowed CSS properties (background,
text-shadow, filter, etc.) and forbidden properties (position/top/etc.
on locked-layout selectors). JSON schema gains custom_css field."
```

---

## Task 3: Append `custom_css` in `build_css_override`

**Files:**
- Modify: `src/short_bot/dna.py` (extend `build_css_override`)
- Test: `tests/test_dna.py`

- [ ] **Step 3.1: Write failing tests**

Append to `tests/test_dna.py`:

```python
def test_build_css_appends_custom_css_when_present():
    dna = _sample_dna(custom_css="body { background: red; }")
    css = build_css_override(dna)
    assert "/* Channel custom_css (Opus-generated) */" in css
    assert "body { background: red; }" in css
    # Ordering: custom_css must come AFTER structural rules
    assert css.index("--primary") < css.index("/* Channel custom_css")


def test_build_css_omits_custom_css_section_when_empty():
    dna = _sample_dna(custom_css="")
    css = build_css_override(dna)
    assert "Channel custom_css" not in css


def test_build_css_omits_custom_css_section_when_whitespace_only():
    dna = _sample_dna(custom_css="   \n\n  ")
    css = build_css_override(dna)
    assert "Channel custom_css" not in css
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dna.py -k "appends_custom_css or omits_custom_css" -v`
Expected: 3 fails (function doesn't append yet).

- [ ] **Step 3.3: Modify `build_css_override`**

In `src/short_bot/dna.py`, find `build_css_override`. The function currently ends with `return css`. Replace the last `return css` line with:

```python
    if dna.custom_css.strip():
        css += f"\n/* Channel custom_css (Opus-generated) */\n{dna.custom_css}\n"
    return css
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dna.py -v`
Expected: all DNA tests pass (existing + 9 custom_css-related)

- [ ] **Step 3.5: Run full suite**

Run: `python -m pytest -q`
Expected: 244 passed (241 + 3)

- [ ] **Step 3.6: Commit**

```bash
git add src/short_bot/dna.py tests/test_dna.py
git commit -m "feat(dna): append custom_css to build_css_override output

Custom CSS rendered AFTER structural rules so Opus can override
colors/decorations. Empty/whitespace-only custom_css is omitted entirely."
```

---

## Task 4: `dna_smoke` module

**Files:**
- Create: `src/short_bot/dna_smoke.py`
- Create: `tests/test_dna_smoke.py`

- [ ] **Step 4.1: Write failing tests**

```python
# tests/test_dna_smoke.py
"""Tests for the DNA smoke-render helper.

These tests use Playwright + chromium. They are skipped if Playwright
isn't installed or the browser binary is missing.
"""
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright

from short_bot.config import Settings
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
from short_bot.dna_smoke import smoke_render_dna


def _settings():
    return Settings(
        ffmpeg_path="ffmpeg", claude_cli_path="claude",
        playwright_browser="chromium", web_host="127.0.0.1",
        web_port=5005, fuzzy_dedup_threshold=0.85,
        log_level="INFO", claude_models={"dna": "opus", "default": "haiku"},
    )


def _dna(custom_css: str = "") -> DnaSpec:
    return DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#c81e1e", accent="#ffea3b",
                           bg_gradient=["#1a3b6b","#0a1a3b"],
                           body_bg=["#1a1a2a","#0a0a1a"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
        custom_css=custom_css,
    )


def _ensure_chromium():
    """Skip the test if chromium binary is not installed."""
    try:
        with sync_playwright() as p:
            try:
                p.chromium.launch().close()
            except Exception as e:
                pytest.skip(f"chromium not installed: {e}")
    except Exception as e:
        pytest.skip(f"playwright unavailable: {e}")


def test_smoke_render_passes_for_default_dna():
    _ensure_chromium()
    templates = Path(__file__).resolve().parents[1] / "templates"
    ok, reason = smoke_render_dna(
        _dna(), channel_template="newscast",
        templates_dir=templates, settings=_settings(),
        language="tr",
    )
    assert ok, f"expected pass, got: {reason}"


def test_smoke_render_passes_with_decorative_custom_css():
    _ensure_chromium()
    templates = Path(__file__).resolve().parents[1] / "templates"
    css = """
    body::before {
      content: '';
      position: absolute; inset: 0;
      background: radial-gradient(circle at 30% 30%, rgba(255,255,255,.1), transparent 70%);
      pointer-events: none;
    }
    """
    ok, reason = smoke_render_dna(
        _dna(custom_css=css), channel_template="newscast",
        templates_dir=templates, settings=_settings(),
        language="tr",
    )
    assert ok, f"expected pass with decorative CSS, got: {reason}"


def test_smoke_render_fails_when_custom_css_blacks_out_layout():
    _ensure_chromium()
    templates = Path(__file__).resolve().parents[1] / "templates"
    # CSS that paints the entire stage solid black — pixel stddev should be ~0
    css = """
    .stage::after {
      content: '';
      position: absolute; inset: 0;
      background: #000000;
      z-index: 99;
    }
    """
    ok, reason = smoke_render_dna(
        _dna(custom_css=css), channel_template="newscast",
        templates_dir=templates, settings=_settings(),
        language="tr",
    )
    assert not ok
    assert "blank" in reason.lower() or "stddev" in reason.lower()
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dna_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'short_bot.dna_smoke'`
(or all skip if Playwright/chromium missing — that's OK, real CI will run them.)

- [ ] **Step 4.3: Create `dna_smoke.py`**

```python
# src/short_bot/dna_smoke.py
"""Smoke-render a single DNA preview frame to catch render-breaking custom_css."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image, ImageStat

from short_bot.config import Settings
from short_bot.dna import DnaSpec, build_css_override
from short_bot.locale import ui_labels_for
from short_bot.models import RenderJob, Script
from short_bot.renderer import render_frames


_SMOKE_SCRIPT = Script(
    header_top="TEST", header_bottom="DNA",
    photo_overlay="Smoke",
    body_paragraph="Bu metin smoke render testi içindir. Layout korumalı mı kontrol ediyoruz.",
    highlights=[],
    category="test", mood="neutral",
)


def smoke_render_dna(
    dna: DnaSpec, *,
    channel_template: str,
    templates_dir: Path,
    settings: Settings,
    language: str = "tr",
) -> tuple[bool, str]:
    """Render 1 frame at fps=1 (so duration_s frames total), inspect the middle one.

    Returns (success, reason).

    Checks:
    1. Frame produced (PNG > 5KB)
    2. Pixel stddev across RGB channels > 5 (not solid color = layout broken)
    """
    job = RenderJob(
        script=_SMOKE_SCRIPT,
        bg_image_path=None,
        music_path=Path("dummy.mp3"),  # never read by render_frames
        channel_colors={
            "primary": dna.palette.primary,
            "accent": dna.palette.accent,
            "bg_gradient": dna.palette.bg_gradient,
        },
        handle="@smoke",
        duration_s=6,
        language=language,
        cta_enabled=False,
    )
    template_path = Path(templates_dir) / f"{channel_template}.html.j2"
    if not template_path.exists():
        return (False, f"template missing: {template_path.name}")
    dna_css = build_css_override(dna)
    ui_labels = ui_labels_for(language)

    with tempfile.TemporaryDirectory() as tmpd:
        frames_dir = Path(tmpd) / "frames"
        try:
            render_frames(job, template_path, frames_dir,
                          fps=1, browser=settings.playwright_browser,
                          ui_labels=ui_labels, dna_css=dna_css)
        except Exception as e:
            return (False, f"render exception: {e}")

        pngs = sorted(frames_dir.glob("*.png"))
        if not pngs:
            return (False, "no frames produced")
        mid = pngs[len(pngs) // 2]
        if mid.stat().st_size < 5000:
            return (False, f"frame too small: {mid.stat().st_size} bytes (likely blank)")
        try:
            img = Image.open(mid).convert("RGB")
            stats = ImageStat.Stat(img)
            if max(stats.stddev) < 5:
                return (False, f"frame appears blank/solid: stddev={stats.stddev}")
        except Exception as e:
            return (False, f"PIL inspect failed: {e}")

    return (True, "ok")
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dna_smoke.py -v`
Expected: 3 passed (or skipped if chromium not installed locally)

- [ ] **Step 4.5: Run full suite**

Run: `python -m pytest -q`
Expected: 247 passed (244 + 3) OR 244 passed + 3 skipped

- [ ] **Step 4.6: Commit**

```bash
git add src/short_bot/dna_smoke.py tests/test_dna_smoke.py
git commit -m "feat(dna): smoke_render_dna helper — Playwright 1-frame sanity check

Renders one mid-duration frame after DNA generation. Returns False if
PNG is undersized (<5KB) or pixel stddev <5 (solid color = broken
layout). Tests skip cleanly when chromium binary unavailable."
```

---

## Task 5: Wire smoke check into wizard save + regenerate-dna endpoint

**Files:**
- Modify: `src/short_bot/web/routes/channel_new.py`
- Modify: `src/short_bot/web/routes/channel_edit.py`
- Test: `tests/test_web_channel_new_generator.py` (extend)
- Test: `tests/test_web_channel_edit_generator.py` (extend)

- [ ] **Step 5.1: Write failing tests**

Append to `tests/test_web_channel_new_generator.py`:

```python
def test_smoke_fail_blocks_channel_save(tmp_path, monkeypatch):
    """When smoke_render returns False, save() flashes error and skips YAML write."""
    c = _client(tmp_path, monkeypatch)
    fake_dna = _fake_dna()

    with patch("short_bot.web.routes.channel_new.generate_dna",
               return_value=fake_dna), \
         patch("short_bot.web.routes.channel_new.smoke_render_dna",
               return_value=(False, "render exception: layout broke")):
        c.post("/channels/new/generate", data={
            "name": "Smoke Fail", "language": "tr",
            "content_source": "rss", "keywords": "x",
        })
        r = c.post("/channels/new/save", data={
            "name": "Smoke Fail", "language": "tr",
            "content_source": "rss", "keywords": "x",
        })

    # Save was skipped → no YAML file created
    assert not (tmp_path / "config" / "channels" / "smoke-fail.yaml").exists()
    # Should redirect back to wizard form (not edit page)
    assert r.status_code in (200, 302)


def test_smoke_pass_allows_channel_save(tmp_path, monkeypatch):
    """When smoke_render returns True, save() proceeds normally."""
    c = _client(tmp_path, monkeypatch)
    fake_dna = _fake_dna()

    with patch("short_bot.web.routes.channel_new.generate_dna",
               return_value=fake_dna), \
         patch("short_bot.web.routes.channel_new.smoke_render_dna",
               return_value=(True, "ok")):
        c.post("/channels/new/generate", data={
            "name": "Smoke Pass", "language": "tr",
            "content_source": "rss", "keywords": "x",
        })
        c.post("/channels/new/save", data={
            "name": "Smoke Pass", "language": "tr",
            "content_source": "rss", "keywords": "x",
        })

    assert (tmp_path / "config" / "channels" / "smoke-pass.yaml").exists()
```

Append to `tests/test_web_channel_edit_generator.py`:

```python
def test_regenerate_dna_blocks_save_on_smoke_fail(app, tmp_path):
    """regenerate_dna must preserve old DNA when smoke_render returns False."""
    from unittest.mock import patch
    from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec

    c = app.test_client()
    new_dna = DnaSpec(
        archetype="kinetic",
        palette=DnaPalette(primary="#abcabc", accent="#defdef",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="new", style="new"),
        persona_summary="new persona",
    )
    with patch("short_bot.web.routes.channel_edit.generate_dna",
               return_value=new_dna), \
         patch("short_bot.web.routes.channel_edit.smoke_render_dna",
               return_value=(False, "blank frame")):
        r = c.post("/channels/sevgi/regenerate-dna")

    assert r.status_code in (200, 302)

    # Verify old DNA preserved in YAML — persona_summary should still be "x"
    import yaml
    yaml_data = yaml.safe_load(
        (tmp_path / "config" / "channels" / "sevgi.yaml").read_text(encoding="utf-8")
    )
    assert yaml_data["dna"]["persona_summary"] == "x"
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_channel_new_generator.py tests/test_web_channel_edit_generator.py -k "smoke" -v`
Expected: 3 fails — `smoke_render_dna` not yet imported / called.

- [ ] **Step 5.3: Wire into `channel_new.py:save()`**

Read `src/short_bot/web/routes/channel_new.py`. Add to imports:

```python
from short_bot.dna_smoke import smoke_render_dna
```

In `save()`, find the existing block (after `dna = DnaSpec.model_validate_json(session["wizard_dna"])` and before `cfg = ChannelConfig(...)`). Insert smoke check after computing `slug` and BEFORE writing CSS / YAML:

```python
    # Smoke render check — refuse to persist DNA that breaks the layout
    settings = current_app.config["SHORTBOT_SETTINGS"]
    ok, reason = smoke_render_dna(
        dna,
        channel_template=dna.archetype,
        templates_dir=templates_dir,
        settings=settings,
        language=language,
    )
    if not ok:
        flash(f"DNA render testi başarısız: {reason}. Tekrar üretmeyi dene.", "error")
        return redirect(url_for("channel_new.form"))
```

(Note: `templates_dir` is already computed earlier in `save()`. Don't shadow it.)

- [ ] **Step 5.4: Wire into `channel_edit.py:regenerate_dna()`**

Read `src/short_bot/web/routes/channel_edit.py`. Add to imports:

```python
from short_bot.dna_smoke import smoke_render_dna
```

In `regenerate_dna()`, find the existing block where `new_dna` is produced from `generate_dna(...)`. Insert smoke check IMMEDIATELY AFTER `new_dna = generate_dna(...)` and BEFORE the CSS rebuild / save_channel call:

```python
    settings = current_app.config["SHORTBOT_SETTINGS"]
    templates_dir = current_app.config["SHORTBOT_TEMPLATES_DIR"]
    ok, reason = smoke_render_dna(
        new_dna,
        channel_template=new_dna.archetype,
        templates_dir=templates_dir,
        settings=settings,
        language=cfg.language,
    )
    if not ok:
        flash(f"DNA render testi başarısız: {reason}. Mevcut DNA korundu.", "error")
        return redirect(url_for("channel_edit.edit", slug=slug))
```

(Note: existing code already computes `templates_dir` later for the CSS write — you can move that line up or duplicate; duplicating is fine since both reference the same config dict.)

- [ ] **Step 5.5: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_channel_new_generator.py tests/test_web_channel_edit_generator.py -k "smoke" -v`
Expected: 3 passed

- [ ] **Step 5.6: Run full suite**

Run: `python -m pytest -q`
Expected: 250 passed (247 + 3) OR 247 passed + 3 skipped

- [ ] **Step 5.7: Commit**

```bash
git add src/short_bot/web/routes/channel_new.py src/short_bot/web/routes/channel_edit.py tests/test_web_channel_new_generator.py tests/test_web_channel_edit_generator.py
git commit -m "feat(web): smoke-render DNA before save (wizard + regenerate)

Both channel_new.save() and channel_edit.regenerate_dna() now invoke
smoke_render_dna between generate_dna and save_channel. On failure,
flash + redirect; YAML is not written and existing DNA is preserved."
```

- [ ] **Step 5.8: Tag**

```bash
git tag -a v0.5.0-custom-dna-css -m "Custom DNA CSS — Opus-generated visual richness layer

DnaSpec.custom_css field (max 8000 chars) lets Opus emit free-form CSS
during DNA generation. Layout selectors stay locked via prompt allow/deny
lists. New smoke_render_dna helper runs a 1-frame Playwright check after
DNA generation; failure aborts save and preserves old DNA."
```

---

## Spec Coverage Self-Review

| Spec | Task |
|---|---|
| §1 Veri modeli — DnaSpec.custom_css | Task 1 |
| §2 Opus prompt — ÖZGÜR CSS section | Task 2 |
| §3 CSS injection — append in build_css_override | Task 3 |
| §4 Smoke render test — dna_smoke module | Task 4 |
| §5 Wiring (channel_new + channel_edit) | Task 5 |
| §6 UI değişikliği yok | Task 5 (only flash messaging) |
| §7 Test stratejisi (5 test categories) | Tasks 1-5 cover all 5 |
| §8 Geriye uyumluluk | Task 1 (default empty) + Task 3 (omit when empty) |
| §10 Kabul kriterleri | All 6 covered by Tasks 1-5 |
| §11 Implementation notları | Honored in Task 4 (sample script inline) |

All 11 spec sections covered. No placeholders. Type names consistent (`DnaSpec`, `custom_css`, `smoke_render_dna`). `_SMOKE_SCRIPT` is inlined as a constant matching Section 11's note ("küçük; isteyene fixtures okuyabilir").

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-06-custom-dna-css.md`.** Two execution options:

**1. Subagent-Driven (recommended)** — Fresh subagent per task, two-stage review (spec compliance + code quality) between tasks.

**2. Inline Execution** — Tasks executed in this session with batch commits.

Hangisi?
