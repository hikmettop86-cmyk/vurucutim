"""Remotion renderer wrapper.

Phase 0 (proof-of-concept): spawn `npx remotion render` as a subprocess.
The Remotion subproject lives at <project_root>/remotion/ — its package.json
+ src/ are independent from the Python codebase. Python writes the script
props as a JSON file, Remotion reads it via --props=, renders directly to
MP4, returns the path.

Future phases will move template selection into the Channel config (e.g.
`renderer: remotion`, `remotion_template: newscast-basic`). For now, only
newscast-basic is wired.

Key design choices:
  - Subprocess, not embedded: Remotion is a Node app; spawning it keeps the
    Python pipeline pure. The cost is process spawn latency (~1-2s) which is
    negligible against actual render time (~30-60s per short).
  - --port=3210 (not default 3000): avoids collision with Next.js / other
    dev servers users commonly have running.
  - No fallback to HTML inside this module: caller chooses HTML vs Remotion
    via channel.renderer. Keep paths cleanly separated.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _npx_command() -> str:
    """Resolve the npx executable. On Windows npx is a .cmd shim that Python's
    subprocess doesn't auto-suffix; we look for npx.cmd explicitly. On
    posix systems plain `npx` works."""
    if sys.platform == "win32":
        path = shutil.which("npx.cmd") or shutil.which("npx")
    else:
        path = shutil.which("npx")
    return path or "npx"

logger = logging.getLogger(__name__)

# Hardcoded list — kept in sync with remotion/src/Root.tsx Compositions.
# Phase 1 (2026-05-19): stadium-basic + stat-hero added. Future phases
# can move this to runtime discovery by scanning remotion/src/templates/.
_AVAILABLE_TEMPLATES = {"newscast-basic", "stadium-basic", "stat-hero"}

_REMOTION_PORT = 3210   # avoid colliding with default 3000


class RemotionRenderError(RuntimeError):
    """Raised when the Remotion subprocess fails or produces no output."""


@dataclass(frozen=True)
class RemotionRenderJob:
    """Subset of RenderJob fields shaped for Remotion props.

    Mirrors the Zod schema in remotion/src/templates/NewscastBasic.tsx —
    keep these in sync. Python -> JSON -> TypeScript: any field rename
    needs to change both ends.
    """
    template: str                # e.g. "newscast-basic"
    header_top: str
    header_bottom: str
    photo_overlay: str
    body_paragraph: str
    category: str
    handle: str
    duration_seconds: int
    bg_image_url: str = ""
    ui_breaking: str = "SON DAKİKA"
    primary: str = "#c8102e"
    accent: str = "#ffb81c"
    bg_grad_1: str = "#0a1733"
    bg_grad_2: str = "#1a2a4f"
    text_main: str = "#ffffff"
    text_muted: str = "#cccccc"

    def to_props_dict(self) -> dict[str, Any]:
        """Build the JSON payload Remotion's --props= flag expects.

        Field names use camelCase to match the TypeScript Zod schema."""
        return {
            "headerTop": self.header_top,
            "headerBottom": self.header_bottom,
            "photoOverlay": self.photo_overlay,
            "bodyParagraph": self.body_paragraph,
            "category": self.category,
            "handle": self.handle,
            "durationSeconds": int(self.duration_seconds),
            "bgImageUrl": self.bg_image_url,
            "uiBreaking": self.ui_breaking,
            "colors": {
                "primary": self.primary,
                "accent": self.accent,
                "bgGrad1": self.bg_grad_1,
                "bgGrad2": self.bg_grad_2,
                "textMain": self.text_main,
                "textMuted": self.text_muted,
            },
        }


def _resolve_remotion_root(explicit: Path | None = None) -> Path:
    """Find the remotion/ subproject. Override via env or arg."""
    if explicit is not None:
        return Path(explicit).resolve()
    # Project structure: src/short_bot/remotion_renderer.py → up 3 → project root
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "remotion"


def is_available(remotion_root: Path | None = None) -> bool:
    """Quick health check. Returns True when:
      - `node` is on PATH
      - remotion/ exists with node_modules already installed (npm install ran)

    Use this before offering the Remotion renderer in the channel-config UI.
    """
    if shutil.which("node") is None:
        return False
    root = _resolve_remotion_root(remotion_root)
    return (root / "package.json").is_file() and (root / "node_modules").is_dir()


def render(
    job: RemotionRenderJob,
    out_path: Path,
    *,
    remotion_root: Path | None = None,
    timeout_s: int = 300,
) -> Path:
    """Spawn `npx remotion render` and return the produced MP4 path.

    Raises RemotionRenderError on subprocess failure / unrecognized template /
    missing output. Caller's responsibility to fall back to another renderer
    or report the error to the run log.
    """
    if job.template not in _AVAILABLE_TEMPLATES:
        raise RemotionRenderError(
            f"unknown remotion template {job.template!r}; "
            f"available: {sorted(_AVAILABLE_TEMPLATES)}"
        )

    root = _resolve_remotion_root(remotion_root)
    if not root.is_dir():
        raise RemotionRenderError(f"remotion root not found: {root}")
    if not (root / "node_modules").is_dir():
        raise RemotionRenderError(
            f"remotion not installed — run `npm install` inside {root}"
        )

    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Write props as a temp JSON file beside the output.
    props_path = out_path.with_suffix(".props.json")
    props_path.write_text(
        json.dumps(job.to_props_dict(), ensure_ascii=False),
        encoding="utf-8",
    )

    cmd = [
        _npx_command(), "remotion", "render",
        "src/index.ts",
        job.template,
        f"--props={props_path}",
        f"--port={_REMOTION_PORT}",
        str(out_path),
    ]
    logger.info(f"[remotion] render {job.template} → {out_path.name}")
    try:
        proc = subprocess.run(
            cmd, cwd=str(root), timeout=timeout_s,
            capture_output=True, text=True, shell=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RemotionRenderError(
            f"remotion render timed out after {timeout_s}s"
        ) from e
    finally:
        try:
            props_path.unlink(missing_ok=True)
        except OSError:
            pass

    if proc.returncode != 0:
        # Last 1000 chars of stderr usually contain the meaningful error
        tail = (proc.stderr or "")[-1000:]
        raise RemotionRenderError(
            f"remotion exit {proc.returncode}\n{tail}"
        )
    if not out_path.is_file() or out_path.stat().st_size < 1024:
        raise RemotionRenderError(
            f"remotion exit 0 but output missing/empty: {out_path}"
        )
    return out_path


def list_templates() -> list[str]:
    """Phase 1+ will read these from disk by scanning remotion/src/templates/."""
    return sorted(_AVAILABLE_TEMPLATES)


def render_job_from_pipeline(
    *,
    script: Any,
    channel_colors: dict[str, Any],
    handle: str,
    duration_s: int,
    template: str,
    bg_image_path: Path | None,
    ui_breaking: str = "SON DAKİKA",
) -> RemotionRenderJob:
    """Build a RemotionRenderJob from the pipeline's Script + Channel state.

    Mirrors the field mapping the HTML renderer does. The `bg_image_path`
    becomes a file:// URL (or empty when None) so Remotion's <Img> can load it.
    """
    bg_url = ""
    if bg_image_path is not None and Path(bg_image_path).exists():
        bg_url = Path(bg_image_path).resolve().as_uri()

    bg_gradient = channel_colors.get("bg_gradient") or ["#0a1733", "#1a2a4f"]
    if isinstance(bg_gradient, (list, tuple)) and len(bg_gradient) >= 2:
        bg1, bg2 = bg_gradient[0], bg_gradient[1]
    else:
        bg1, bg2 = "#0a1733", "#1a2a4f"

    return RemotionRenderJob(
        template=template,
        header_top=script.header_top,
        header_bottom=script.header_bottom,
        photo_overlay=script.photo_overlay,
        body_paragraph=script.body_paragraph,
        category=getattr(script, "category", ""),
        handle=handle,
        duration_seconds=int(duration_s),
        bg_image_url=bg_url,
        ui_breaking=ui_breaking,
        primary=channel_colors.get("primary", "#c8102e"),
        accent=channel_colors.get("accent", "#ffb81c"),
        bg_grad_1=bg1,
        bg_grad_2=bg2,
    )
