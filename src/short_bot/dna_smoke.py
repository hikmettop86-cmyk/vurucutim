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
