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
    _npx_command, _resolve_remotion_root, is_available,
    list_templates, render,
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


@pytest.mark.parametrize("template", ["newscast-basic", "stadium-basic", "stat-hero"])
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


def test_render_fails_when_node_modules_missing(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    # No node_modules → should error before subprocess
    with pytest.raises(RemotionRenderError, match="not installed"):
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
