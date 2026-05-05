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
