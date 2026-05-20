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

ARCHETYPES = ["newscast", "stadium"]
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
        # Wait for auto-fit JS to finish font-size shrink — otherwise the
        # screenshot fires mid-shrink and pixel positions drift between runs.
        page.evaluate("window.__autoFitDone || Promise.resolve()")
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
