"""HTML render via Jinja2 → frame capture via Playwright."""
from __future__ import annotations

import base64
import mimetypes
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
        # Embed as base64 data URI so Playwright's about:blank origin can load it
        # (file:// URLs are blocked under set_content security context)
        mime, _ = mimetypes.guess_type(str(job.bg_image_path))
        mime = mime or "image/jpeg"
        data = base64.b64encode(job.bg_image_path.read_bytes()).decode("ascii")
        bg_url = f"data:{mime};base64,{data}"

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
