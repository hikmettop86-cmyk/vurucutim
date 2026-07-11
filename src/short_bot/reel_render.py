"""Reel şeffaf overlay: HTML üret + Playwright PNG dizisi (alfa)."""
from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from short_bot.reel_colors import contrast_text, ensure_bright
from short_bot.reel_models import ReelTimeline

WIDTH, HEIGHT = 1080, 1920

# Kanal-bazlı overlay fontları (7 küratörlü Google font). Anahtarlar
# ReelConfig.font Literal'iyle birebir; her biri kalın/ağır ağırlık yükler.
_FONT_IMPORTS = {
    "Montserrat": "https://fonts.googleapis.com/css2?family=Montserrat:wght@900&display=swap",
    "Anton": "https://fonts.googleapis.com/css2?family=Anton&display=swap",
    "Bebas Neue": "https://fonts.googleapis.com/css2?family=Bebas+Neue&display=swap",
    "Oswald": "https://fonts.googleapis.com/css2?family=Oswald:wght@700&display=swap",
    "Poppins": "https://fonts.googleapis.com/css2?family=Poppins:wght@800&display=swap",
    "Inter": "https://fonts.googleapis.com/css2?family=Inter:wght@900&display=swap",
    "Archivo Black": "https://fonts.googleapis.com/css2?family=Archivo+Black&display=swap",
}


def build_reel_overlay_html(
    timeline: ReelTimeline, *, layout: str = "classic",
    highlight_color: str = "#ffd400",
    arrow_color: str = "#ff2d2d", arrow_frequency: str = "beats",
    flash: bool = True, handle: str = "", cta_text: str = "",
    font: str = "Montserrat",
    templates_dir: Path | None = None,
) -> str:
    if layout not in ("classic", "lower_left", "top_heavy"):
        layout = "classic"
    templates_dir = Path(templates_dir) if templates_dir else Path("templates")
    env = Environment(loader=FileSystemLoader(str(templates_dir)),
                      autoescape=select_autoescape(["html"]))
    tpl = env.get_template("reel_overlay.html.j2")

    last_seg = len(timeline.seg_spans) - 1
    words = [{"word": w.word, "start": f"{w.start_s:.3f}", "end": f"{w.end_s:.3f}",
              "seg": w.seg} for w in timeline.words]
    cards = [{"text": timeline.seg_keywords[i], "start": f"{timeline.seg_spans[i][0]:.3f}",
              "end": f"{timeline.seg_spans[i][1]:.3f}"}
             for i in range(len(timeline.seg_spans)) if timeline.seg_keywords[i]]
    cuts = [round(timeline.seg_spans[i][0], 3) for i in range(1, len(timeline.seg_spans))]
    # ok segmentleri: 'off'->hic, 'reveal'->tek beat, 'beats'->tum beat'ler
    beat_segs = list(range(1, last_seg))
    if arrow_frequency == "off":
        arrow_segs: list[int] = []
    elif arrow_frequency == "reveal":
        arrow_segs = beat_segs[1:2] or beat_segs[:1]
    else:
        arrow_segs = beat_segs

    return tpl.render(
        layout=layout,
        highlight_color=highlight_color, arrow_color=arrow_color,
        chip_text=contrast_text(highlight_color),
        hot_color=ensure_bright(highlight_color),
        hook=timeline.hook, close=timeline.close, handle=handle,
        cta_text=cta_text,
        font=font, font_import=_FONT_IMPORTS.get(font, _FONT_IMPORTS["Montserrat"]),
        words=words, cards=cards, duration_s=f"{timeline.duration_s:.3f}",
        last_seg=last_seg, cuts=json.dumps(cuts),
        arrow_segs=json.dumps(arrow_segs), flash=flash,
    )


def render_reel_overlay_frames(
    timeline: ReelTimeline, out_dir: Path, *, fps: int = 30,
    browser: str = "chromium", templates_dir: Path | None = None, **style,
) -> int:
    """Şeffaf overlay PNG dizisi üretir (omit_background=True). Kare sayısını döndürür."""
    from playwright.sync_api import sync_playwright
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    html = build_reel_overlay_html(timeline, templates_dir=templates_dir, **style)
    total = int(round(timeline.duration_s * fps))
    with sync_playwright() as p:
        b = getattr(p, browser).launch()
        pg = b.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        pg.set_content(html, wait_until="networkidle")
        for i in range(total):
            pg.evaluate("(t)=>window.__seek(t)", int(i / fps * 1000))
            pg.screenshot(path=str(out_dir / f"f_{i:05d}.png"), omit_background=True)
        b.close()
    return total
