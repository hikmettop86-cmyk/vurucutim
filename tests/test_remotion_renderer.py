"""Unit tests for short_bot.remotion_renderer.

Live render tests (test_live_render_*) marked @slow — they spin up Node +
Remotion and actually produce an MP4. Pure-Python tests (no subprocess) run
on every CI invocation.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from short_bot.remotion_renderer import (
    RemotionRenderError, RemotionRenderJob,
    _node_command, _npm_command_for_install, _npx_command,
    _resolve_remotion_root, ensure_remotion_installed,
    is_available, list_templates, render, render_job_from_pipeline,
)


# --- Props serialization ---------------------------------------------------

def test_to_props_dict_uses_camelcase_keys():
    """The Remotion Zod schema expects camelCase; mismatched keys would
    fail Zod validation at runtime."""
    job = RemotionRenderJob(
        template="newscast-basic",
        header_top="A", header_bottom="B",
        photo_overlay="C", body_paragraph="D",
        category="E", handle="@h", duration_seconds=6,
    )
    p = job.to_props_dict()
    # Top-level camelCase
    assert "headerTop" in p and "headerBottom" in p
    assert "photoOverlay" in p and "bodyParagraph" in p
    assert "durationSeconds" in p and "uiBreaking" in p
    # Nested colors
    assert "colors" in p
    assert "bgGrad1" in p["colors"]
    assert "textMain" in p["colors"]


def test_to_props_dict_preserves_unicode():
    job = RemotionRenderJob(
        template="newscast-basic",
        header_top="ŞAMPİYON", header_bottom="GALATASARAY",
        photo_overlay="x", body_paragraph="Türkçe metni",
        category="E", handle="@h", duration_seconds=6,
    )
    p = job.to_props_dict()
    j = json.dumps(p, ensure_ascii=False)
    assert "ŞAMPİYON" in j
    assert "Türkçe" in j


# --- Renderer discovery ----------------------------------------------------

def test_npx_command_returns_string():
    out = _npx_command()
    assert isinstance(out, str) and len(out) > 0


def test_resolve_remotion_root_explicit_override(tmp_path):
    assert _resolve_remotion_root(tmp_path) == tmp_path.resolve()


def test_resolve_remotion_root_default_uses_project_layout():
    """Default points at <project_root>/remotion. We don't require it to
    exist for this test — just that the path computation is correct."""
    root = _resolve_remotion_root()
    assert root.name == "remotion"


def test_list_templates_includes_newscast_basic():
    assert "newscast-basic" in list_templates()


def test_list_templates_includes_stadium_basic():
    assert "stadium-basic" in list_templates()


def test_list_templates_includes_stat_hero():
    assert "stat-hero" in list_templates()


def test_list_templates_includes_big_quote():
    """Phase 4: Remotion-only template, no HTML counterpart."""
    assert "big-quote" in list_templates()


def test_list_templates_includes_adaptive():
    """Phase 5: dimension-driven template — single .tsx, 27 combinations."""
    assert "adaptive" in list_templates()


def test_to_props_dict_includes_dimensions_when_set():
    from short_bot.remotion_renderer import RemotionRenderJob
    job = RemotionRenderJob(
        template="adaptive", header_top="A", header_bottom="B",
        photo_overlay="C", body_paragraph="D body", category="E",
        handle="@h", duration_seconds=4,
        dimensions={"headerStyle": "banner-skewed", "bodyStyle": "quote"},
    )
    p = job.to_props_dict()
    assert p["dimensions"] == {"headerStyle": "banner-skewed", "bodyStyle": "quote"}


def test_to_props_dict_omits_dimensions_when_none():
    from short_bot.remotion_renderer import RemotionRenderJob
    job = RemotionRenderJob(
        template="newscast-basic", header_top="A", header_bottom="B",
        photo_overlay="C", body_paragraph="D body", category="E",
        handle="@h", duration_seconds=4,
    )
    assert "dimensions" not in job.to_props_dict()


def test_adaptive_dimension_options_match_zod_enum():
    """Tripwire: if Adaptive.tsx adds a new option, ADAPTIVE_DIMENSION_OPTIONS
    must be updated too — UI dropdowns + form-validation depend on it."""
    from short_bot.remotion_renderer import ADAPTIVE_DIMENSION_OPTIONS
    assert "banner-flat" in ADAPTIVE_DIMENSION_OPTIONS["headerStyle"]
    assert "banner-skewed" in ADAPTIVE_DIMENSION_OPTIONS["headerStyle"]
    assert "hero-overlay" in ADAPTIVE_DIMENSION_OPTIONS["headerStyle"]
    assert "full-bleed" in ADAPTIVE_DIMENSION_OPTIONS["photoTreatment"]
    assert "banded" in ADAPTIVE_DIMENSION_OPTIONS["photoTreatment"]
    assert "blur-bg" in ADAPTIVE_DIMENSION_OPTIONS["photoTreatment"]
    assert "paragraph" in ADAPTIVE_DIMENSION_OPTIONS["bodyStyle"]
    assert "quote" in ADAPTIVE_DIMENSION_OPTIONS["bodyStyle"]
    assert "stat-hero" in ADAPTIVE_DIMENSION_OPTIONS["bodyStyle"]


def test_adaptive_dimensions_phase_6b_axes_present():
    """Phase 6b: motionPreset + typography axes registered. Also: 2 new
    photoTreatment values (polaroid-tilt, cutout-float)."""
    from short_bot.remotion_renderer import ADAPTIVE_DIMENSION_OPTIONS
    # New axes
    assert "motionPreset" in ADAPTIVE_DIMENSION_OPTIONS
    assert "typography" in ADAPTIVE_DIMENSION_OPTIONS
    # Motion options
    motion = ADAPTIVE_DIMENSION_OPTIONS["motionPreset"]
    for m in ("subtle", "dramatic", "sport", "news", "cinematic"):
        assert m in motion, f"missing motion preset: {m}"
    # Typography options
    typo = ADAPTIVE_DIMENSION_OPTIONS["typography"]
    for t in ("default", "authoritative", "tabloid", "editorial",
              "tech", "sport-bold", "cinematic-serif"):
        assert t in typo, f"missing typography pair: {t}"
    # New photo treatments
    photo = ADAPTIVE_DIMENSION_OPTIONS["photoTreatment"]
    assert "polaroid-tilt" in photo
    assert "cutout-float" in photo


def test_adaptive_dimensions_total_combinations():
    """Brief invariant — confirm we hit the advertised 1575 combination count.
    If this drifts unexpectedly, dimension counts changed without intent."""
    from short_bot.remotion_renderer import ADAPTIVE_DIMENSION_OPTIONS
    total = 1
    for opts in ADAPTIVE_DIMENSION_OPTIONS.values():
        total *= len(opts)
    assert total == 1575, f"expected 1575 combos, got {total}"


def test_render_still_uses_remotion_still_command(tmp_path):
    """Phase 6a: snapshot path must call `remotion still` (not `render`)
    so we hit the optimized single-frame codepath."""
    from short_bot.remotion_renderer import render_still
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    out_path = tmp_path / "snap.jpg"
    captured = {}

    job = RemotionRenderJob(
        template="adaptive", header_top="A", header_bottom="B",
        photo_overlay="C", body_paragraph="D body", category="E",
        handle="@h", duration_seconds=4,
    )

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out_path.write_bytes(b"\xff\xd8\xff" * 200)
        return MagicMock(returncode=0, stderr="")

    with patch("short_bot.remotion_renderer.subprocess.run", side_effect=fake_run):
        render_still(job, out_path, remotion_root=tmp_path, frame=30, port=3220)
    assert captured["cmd"][1:3] == ["remotion", "still"]
    assert any(a == "--frame=30" for a in captured["cmd"])
    assert any(a == "--port=3220" for a in captured["cmd"])


def test_render_still_rejects_unknown_template(tmp_path):
    from short_bot.remotion_renderer import render_still
    job = RemotionRenderJob(
        template="bogus-template", header_top="A", header_bottom="B",
        photo_overlay="C", body_paragraph="D", category="E",
        handle="@h", duration_seconds=4,
    )
    with pytest.raises(RemotionRenderError, match="unknown"):
        render_still(job, tmp_path / "snap.jpg", remotion_root=tmp_path)


def test_render_still_surfaces_subprocess_failure(tmp_path):
    from short_bot.remotion_renderer import render_still
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    job = RemotionRenderJob(
        template="newscast-basic", header_top="A", header_bottom="B",
        photo_overlay="C", body_paragraph="D body", category="E",
        handle="@h", duration_seconds=4,
    )
    with patch("short_bot.remotion_renderer.subprocess.run",
               return_value=MagicMock(returncode=2, stderr="explode")):
        with pytest.raises(RemotionRenderError, match="exit 2"):
            render_still(job, tmp_path / "snap.jpg", remotion_root=tmp_path)


def test_render_job_from_pipeline_passes_dimensions():
    from short_bot.remotion_renderer import render_job_from_pipeline

    class _FakeScript:
        header_top = "A"
        header_bottom = "B"
        photo_overlay = "C"
        body_paragraph = "D"
        category = "E"

    job = render_job_from_pipeline(
        script=_FakeScript(),
        channel_colors={"primary": "#000", "accent": "#fff",
                        "bg_gradient": ["#111", "#222"]},
        handle="@h", duration_s=6, template="adaptive",
        bg_image_path=None,
        dimensions={"headerStyle": "hero-overlay"},
    )
    assert job.dimensions == {"headerStyle": "hero-overlay"}


def test_list_templates_returns_sorted():
    """Stable ordering matters when surfacing the list in the UI dropdown."""
    out = list_templates()
    assert out == sorted(out)


# --- is_available ----------------------------------------------------------

def test_is_available_false_when_node_missing(tmp_path):
    with patch("short_bot.remotion_renderer.shutil.which", return_value=None):
        assert is_available(tmp_path) is False


def test_is_available_false_when_remotion_dir_missing(tmp_path):
    with patch("short_bot.remotion_renderer.shutil.which", return_value="/usr/bin/node"):
        assert is_available(tmp_path / "no-such-dir") is False


def test_is_available_true_when_node_and_remotion_present(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    with patch("short_bot.remotion_renderer.shutil.which", return_value="/usr/bin/node"):
        assert is_available(tmp_path) is True


# --- render error paths (no subprocess actually spawned) -------------------

def _basic_job():
    return RemotionRenderJob(
        template="newscast-basic",
        header_top="A", header_bottom="B",
        photo_overlay="C", body_paragraph="D body",
        category="E", handle="@h", duration_seconds=4,
    )


def test_render_rejects_unknown_template(tmp_path):
    job = RemotionRenderJob(
        template="totally-fake", header_top="A", header_bottom="B",
        photo_overlay="C", body_paragraph="D", category="E",
        handle="@h", duration_seconds=4,
    )
    with pytest.raises(RemotionRenderError, match="unknown"):
        render(job, tmp_path / "out.mp4", remotion_root=tmp_path)


@pytest.mark.parametrize("template", ["newscast-basic", "stadium-basic", "stat-hero", "big-quote"])
def test_render_accepts_known_template_passes_to_root_check(tmp_path, template):
    """All 3 registered templates pass the whitelist check — proves that
    template name typos in _AVAILABLE_TEMPLATES would be caught here. We
    block at the remotion root step rather than the template step."""
    job = RemotionRenderJob(
        template=template, header_top="A", header_bottom="B",
        photo_overlay="C", body_paragraph="D", category="E",
        handle="@h", duration_seconds=4,
    )
    with pytest.raises(RemotionRenderError, match="not found"):
        render(job, tmp_path / "out.mp4",
               remotion_root=tmp_path / "no-such-dir")


def test_render_fails_when_remotion_root_missing(tmp_path):
    with pytest.raises(RemotionRenderError, match="not found"):
        render(_basic_job(), tmp_path / "out.mp4",
               remotion_root=tmp_path / "no-such")


def test_render_fails_when_node_modules_and_node_both_missing(tmp_path, monkeypatch):
    """With Phase 3, missing node_modules triggers a lazy install — that
    install itself fails with a clear 'node executable' message when node
    is not bundled or on PATH. Replaces the pre-Phase-3 'not installed' check.
    """
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("VURUCUTIM_NODE_HOME", raising=False)
    with patch("short_bot.remotion_renderer.shutil.which", return_value=None):
        with pytest.raises(RemotionRenderError, match="node executable"):
            render(_basic_job(), tmp_path / "out.mp4", remotion_root=tmp_path)


def test_render_surfaces_subprocess_failure(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    fake_proc = MagicMock(returncode=1, stderr="something exploded")
    with patch("short_bot.remotion_renderer.subprocess.run",
               return_value=fake_proc):
        with pytest.raises(RemotionRenderError, match="exit 1"):
            render(_basic_job(), tmp_path / "out.mp4", remotion_root=tmp_path)


def test_render_complains_when_output_missing_despite_zero_exit(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    fake_proc = MagicMock(returncode=0, stderr="")
    with patch("short_bot.remotion_renderer.subprocess.run",
               return_value=fake_proc):
        with pytest.raises(RemotionRenderError, match="output missing"):
            # subprocess fake doesn't actually create the file
            render(_basic_job(), tmp_path / "out.mp4", remotion_root=tmp_path)


def test_render_inlines_file_uri_image_as_data_url(tmp_path):
    """Bug v0.1.75: file:// URIs in CSS background-image blocked by Chromium
    cross-origin policy → photo silent-fails. Fix: inline the file content as
    a base64 data URL — works in CSS url() without any cross-origin gymnastics."""
    import base64
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    bg_file = tmp_path / "src_bg.jpg"
    bg_bytes = b"\xff\xd8\xff" * 1000
    bg_file.write_bytes(bg_bytes)
    out_path = tmp_path / "out.mp4"
    captured = {}

    job = RemotionRenderJob(
        template="newscast-basic", header_top="A", header_bottom="B",
        photo_overlay="C", body_paragraph="D body", category="E",
        handle="@h", duration_seconds=4,
        bg_image_url=bg_file.resolve().as_uri(),
    )

    def fake_run(cmd, **kw):
        props_arg = next(a for a in cmd if a.startswith("--props="))
        props_path = Path(props_arg.removeprefix("--props="))
        captured["props"] = json.loads(props_path.read_text(encoding="utf-8"))
        out_path.write_bytes(b"\x00" * 2048)
        return MagicMock(returncode=0, stderr="")

    with patch("short_bot.remotion_renderer.subprocess.run", side_effect=fake_run):
        render(job, out_path, remotion_root=tmp_path)

    # bg got rewritten to a data URL
    bg = captured["props"]["bgImageUrl"]
    assert bg.startswith("data:image/jpeg;base64,") or bg.startswith("data:image/jpg;base64,")
    # Verify the data round-trips back to the original bytes
    decoded = base64.b64decode(bg.split(",", 1)[1])
    assert decoded == bg_bytes


def test_render_drops_bg_url_when_source_file_missing(tmp_path):
    """If the file:// path no longer exists, the bgImageUrl is dropped to ''
    rather than passing a broken URL to the renderer."""
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    out_path = tmp_path / "out.mp4"
    captured = {}

    # file:// URI to a non-existent path
    job = RemotionRenderJob(
        template="newscast-basic", header_top="A", header_bottom="B",
        photo_overlay="C", body_paragraph="D body", category="E",
        handle="@h", duration_seconds=4,
        bg_image_url=(tmp_path / "missing.jpg").resolve().as_uri(),
    )

    def fake_run(cmd, **kw):
        props_arg = next(a for a in cmd if a.startswith("--props="))
        captured["props"] = json.loads(
            Path(props_arg.removeprefix("--props=")).read_text(encoding="utf-8")
        )
        out_path.write_bytes(b"\x00" * 2048)
        return MagicMock(returncode=0, stderr="")

    with patch("short_bot.remotion_renderer.subprocess.run", side_effect=fake_run):
        render(job, out_path, remotion_root=tmp_path)
    assert captured["props"]["bgImageUrl"] == ""


def test_render_skips_staging_for_http_urls(tmp_path):
    """Non-file:// URLs (e.g. https://cdn/...) pass through untouched."""
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    out_path = tmp_path / "out.mp4"
    captured = {}

    job = RemotionRenderJob(
        template="newscast-basic", header_top="A", header_bottom="B",
        photo_overlay="C", body_paragraph="D body", category="E",
        handle="@h", duration_seconds=4,
        bg_image_url="https://cdn.example.com/img.jpg",
    )

    def fake_run(cmd, **kw):
        props_arg = next(a for a in cmd if a.startswith("--props="))
        captured["props"] = json.loads(
            Path(props_arg.removeprefix("--props=")).read_text(encoding="utf-8")
        )
        out_path.write_bytes(b"\x00" * 2048)
        return MagicMock(returncode=0, stderr="")

    with patch("short_bot.remotion_renderer.subprocess.run", side_effect=fake_run):
        render(job, out_path, remotion_root=tmp_path)
    assert captured["props"]["bgImageUrl"] == "https://cdn.example.com/img.jpg"
    assert not (tmp_path / "public").exists()


def test_render_writes_props_json_before_subprocess(tmp_path):
    """Verify the subprocess is invoked with --props pointing to a real file
    containing the camelCase payload."""
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    out_path = tmp_path / "out.mp4"
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        # Inspect the props file at the moment subprocess would have read it
        props_arg = next(a for a in cmd if a.startswith("--props="))
        props_path = Path(props_arg.removeprefix("--props="))
        captured["props_payload"] = json.loads(
            props_path.read_text(encoding="utf-8")
        )
        # Simulate Remotion writing the output file
        out_path.write_bytes(b"\x00" * 2048)
        return MagicMock(returncode=0, stderr="")

    with patch("short_bot.remotion_renderer.subprocess.run", side_effect=fake_run):
        render(_basic_job(), out_path, remotion_root=tmp_path)
    assert captured["cmd"][1:3] == ["remotion", "render"]
    assert captured["props_payload"]["headerTop"] == "A"
    assert captured["props_payload"]["durationSeconds"] == 4
    assert captured["props_payload"]["colors"]["primary"] == "#c8102e"


# --- render_job_from_pipeline mapper --------------------------------------

class _FakeScript:
    """Minimal stand-in for short_bot.models.Script — keep this test independent
    of the Script Pydantic schema so renames there don't cascade here."""
    def __init__(self, **kw):
        self.header_top = kw.get("header_top", "TOP")
        self.header_bottom = kw.get("header_bottom", "BOTTOM")
        self.photo_overlay = kw.get("photo_overlay", "OVERLAY")
        self.body_paragraph = kw.get("body_paragraph", "Body text here.")
        self.category = kw.get("category", "GENERAL")


def test_render_job_from_pipeline_copies_script_fields():
    job = render_job_from_pipeline(
        script=_FakeScript(),
        channel_colors={"primary": "#111", "accent": "#222",
                        "bg_gradient": ["#aaa", "#bbb"]},
        handle="@x", duration_s=8,
        template="stadium-basic", bg_image_path=None,
    )
    assert job.template == "stadium-basic"
    assert job.header_top == "TOP"
    assert job.header_bottom == "BOTTOM"
    assert job.body_paragraph == "Body text here."
    assert job.category == "GENERAL"
    assert job.handle == "@x"
    assert job.duration_seconds == 8


def test_render_job_from_pipeline_threads_channel_colors():
    job = render_job_from_pipeline(
        script=_FakeScript(),
        channel_colors={"primary": "#abcdef", "accent": "#fedcba",
                        "bg_gradient": ["#111111", "#222222"]},
        handle="@h", duration_s=6,
        template="newscast-basic", bg_image_path=None,
    )
    assert job.primary == "#abcdef"
    assert job.accent == "#fedcba"
    assert job.bg_grad_1 == "#111111"
    assert job.bg_grad_2 == "#222222"


def test_render_job_from_pipeline_bg_path_becomes_file_uri(tmp_path):
    bg = tmp_path / "thumb.jpg"
    bg.write_bytes(b"\xff\xd8\xff")  # JPEG SOI marker

    job = render_job_from_pipeline(
        script=_FakeScript(),
        channel_colors={"primary": "#c8102e", "accent": "#ffb81c",
                        "bg_gradient": ["#0a1733", "#1a2a4f"]},
        handle="@x", duration_s=6,
        template="newscast-basic", bg_image_path=bg,
    )
    # file:// URI lets Remotion's <Img src=...> load the local file
    assert job.bg_image_url.startswith("file://")
    assert "thumb.jpg" in job.bg_image_url


def test_render_job_from_pipeline_missing_bg_yields_empty_url(tmp_path):
    """Caller may pass a path that no longer exists (race with cleanup) —
    the mapper must gracefully degrade to '' (empty src) so Remotion just
    renders without a photo rather than crashing the pipeline."""
    job = render_job_from_pipeline(
        script=_FakeScript(),
        channel_colors={"primary": "#000", "accent": "#fff",
                        "bg_gradient": ["#111", "#222"]},
        handle="@h", duration_s=6,
        template="newscast-basic",
        bg_image_path=tmp_path / "no-such-thumb.jpg",
    )
    assert job.bg_image_url == ""


def test_render_job_from_pipeline_falls_back_on_missing_gradient():
    """Defensive: legacy channels without bg_gradient (key absent) must
    still produce a valid RemotionRenderJob — Zod would fail on missing
    colors otherwise."""
    job = render_job_from_pipeline(
        script=_FakeScript(),
        channel_colors={"primary": "#abc", "accent": "#def"},  # no gradient
        handle="@h", duration_s=6,
        template="newscast-basic", bg_image_path=None,
    )
    assert job.bg_grad_1 and job.bg_grad_2  # defaults filled in


# --- VURUCUTIM_NODE_HOME bundled-Node resolution (Phase 3) -----------------

@pytest.mark.skipif(
    __import__("sys").platform != "win32", reason="Windows-specific resolution"
)
def test_npx_command_prefers_bundled_node_home(tmp_path, monkeypatch):
    bundled_npx = tmp_path / "npx.cmd"
    bundled_npx.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setenv("VURUCUTIM_NODE_HOME", str(tmp_path))
    out = _npx_command()
    assert out == str(bundled_npx), (
        f"expected bundled npx at {bundled_npx}, got {out}"
    )


def test_npx_command_falls_back_to_path_when_env_unset(monkeypatch):
    monkeypatch.delenv("VURUCUTIM_NODE_HOME", raising=False)
    # Should still return a string (PATH lookup or "npx" fallback)
    out = _npx_command()
    assert isinstance(out, str) and len(out) > 0


def test_npx_command_falls_back_when_bundled_missing(tmp_path, monkeypatch):
    """If VURUCUTIM_NODE_HOME points at a non-existent dir, we still
    fall through to PATH instead of crashing."""
    monkeypatch.setenv("VURUCUTIM_NODE_HOME", str(tmp_path / "no-such"))
    out = _npx_command()
    assert isinstance(out, str) and len(out) > 0
    assert "no-such" not in out


@pytest.mark.skipif(
    __import__("sys").platform != "win32", reason="Windows-specific resolution"
)
def test_node_command_resolves_bundled(tmp_path, monkeypatch):
    bundled = tmp_path / "node.exe"
    bundled.write_bytes(b"")
    monkeypatch.setenv("VURUCUTIM_NODE_HOME", str(tmp_path))
    out = _node_command()
    assert out == str(bundled)


def test_node_command_returns_none_when_neither_present(monkeypatch):
    """When env var unset and PATH has no node, returns None (so callers can
    surface a clean 'install Node' error instead of trying to spawn nothing)."""
    monkeypatch.delenv("VURUCUTIM_NODE_HOME", raising=False)
    with patch("short_bot.remotion_renderer.shutil.which", return_value=None):
        assert _node_command() is None


# --- VURUCUTIM_REMOTION_HOME env override ---------------------------------

def test_resolve_remotion_root_uses_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("VURUCUTIM_REMOTION_HOME", str(tmp_path))
    out = _resolve_remotion_root()
    assert out == tmp_path.resolve()


def test_resolve_remotion_root_env_var_overridden_by_explicit_arg(tmp_path, monkeypatch):
    """Explicit argument always wins — tests / wizard flows depend on it."""
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("VURUCUTIM_REMOTION_HOME", str(tmp_path / "from-env"))
    out = _resolve_remotion_root(other)
    assert out == other.resolve()


def test_resolve_remotion_root_empty_env_falls_through(tmp_path, monkeypatch):
    """Empty string env var should be treated as unset (Electron may set
    it to '' when bundled Node is not yet downloaded)."""
    monkeypatch.setenv("VURUCUTIM_REMOTION_HOME", "")
    out = _resolve_remotion_root()
    # Falls through to project_root/remotion default
    assert out.name == "remotion"


# --- ensure_remotion_installed --------------------------------------------

def test_ensure_remotion_installed_noop_when_already_installed(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    # Should NOT spawn npm install — node_modules already there
    with patch("short_bot.remotion_renderer.subprocess.run") as mock_run:
        out = ensure_remotion_installed(remotion_root=tmp_path)
    assert out == tmp_path.resolve()
    assert not mock_run.called


def test_ensure_remotion_installed_raises_when_no_package_json(tmp_path):
    with pytest.raises(RemotionRenderError, match="package.json"):
        ensure_remotion_installed(remotion_root=tmp_path)


def test_ensure_remotion_installed_runs_npm_install(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    # Pretend node is available via env (bundled)
    monkeypatch.setenv("VURUCUTIM_NODE_HOME", str(tmp_path))
    # Need node executable for _node_command to return something
    node_exe = tmp_path / ("node.exe" if __import__("sys").platform == "win32" else "node")
    node_exe.write_bytes(b"")
    npm_exe = tmp_path / ("npm.cmd" if __import__("sys").platform == "win32" else "npm")
    npm_exe.write_bytes(b"")

    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["cwd"] = kw.get("cwd")
        # Simulate successful install
        (tmp_path / "node_modules").mkdir()
        return MagicMock(returncode=0, stderr="")

    with patch("short_bot.remotion_renderer.subprocess.run", side_effect=fake_run):
        ensure_remotion_installed(remotion_root=tmp_path)
    assert captured["cmd"][1] == "install"
    assert captured["cwd"] == str(tmp_path)


def test_ensure_remotion_installed_surfaces_install_failure(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("VURUCUTIM_NODE_HOME", str(tmp_path))
    node_exe = tmp_path / ("node.exe" if __import__("sys").platform == "win32" else "node")
    node_exe.write_bytes(b"")
    npm_exe = tmp_path / ("npm.cmd" if __import__("sys").platform == "win32" else "npm")
    npm_exe.write_bytes(b"")
    with patch("short_bot.remotion_renderer.subprocess.run",
               return_value=MagicMock(returncode=1, stderr="network error")):
        with pytest.raises(RemotionRenderError, match="exit 1"):
            ensure_remotion_installed(remotion_root=tmp_path)


def test_ensure_remotion_installed_errors_when_node_missing(tmp_path, monkeypatch):
    """Clean error message when bundled node hasn't been fetched yet."""
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("VURUCUTIM_NODE_HOME", raising=False)
    with patch("short_bot.remotion_renderer.shutil.which", return_value=None):
        with pytest.raises(RemotionRenderError, match="node executable"):
            ensure_remotion_installed(remotion_root=tmp_path)


def test_render_triggers_ensure_install_when_node_modules_missing(tmp_path, monkeypatch):
    """End-to-end: missing node_modules should trigger install via render()."""
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("VURUCUTIM_NODE_HOME", str(tmp_path))
    node_exe = tmp_path / ("node.exe" if __import__("sys").platform == "win32" else "node")
    node_exe.write_bytes(b"")
    npm_exe = tmp_path / ("npm.cmd" if __import__("sys").platform == "win32" else "npm")
    npm_exe.write_bytes(b"")
    npx_exe = tmp_path / ("npx.cmd" if __import__("sys").platform == "win32" else "npx")
    npx_exe.write_bytes(b"")

    call_log = []

    def fake_run(cmd, **kw):
        call_log.append(cmd[:2])  # [exe, first-arg]
        if cmd[1] == "install":
            (tmp_path / "node_modules").mkdir()
            return MagicMock(returncode=0, stderr="")
        else:  # remotion render
            out_path = Path([a for a in cmd if str(a).endswith(".mp4")][-1])
            out_path.write_bytes(b"\x00" * 2048)
            return MagicMock(returncode=0, stderr="")

    job = RemotionRenderJob(
        template="newscast-basic", header_top="A", header_bottom="B",
        photo_overlay="C", body_paragraph="D body", category="E",
        handle="@h", duration_seconds=4,
    )
    with patch("short_bot.remotion_renderer.subprocess.run", side_effect=fake_run):
        render(job, tmp_path / "out.mp4", remotion_root=tmp_path)
    # First call should have been npm install, then npx remotion
    assert call_log[0][1] == "install"
    assert call_log[1][1] == "remotion"
