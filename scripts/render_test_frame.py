"""Render verification frames at multiple timestamps (badge fix + CTA corners)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from short_bot.models import RenderJob, Script, Highlight
from short_bot.renderer import build_html
from playwright.sync_api import sync_playwright


def main():
    script = Script(
        header_top="ASGARİ ÜCRETE",
        header_bottom="ARA ZAM MI?",
        photo_overlay="MİLYONLARCA ÇALIŞAN BEKLİYOR",
        body_paragraph=(
            "Asgari ücrete temmuzda ara zam gelip gelmeyeceği milyonlarca çalışanı "
            "yakından ilgilendiriyor. Yüksek enflasyon nedeniyle alım gücü eridi ve ara zam "
            "talepleri yeniden gündemde. Hükümet kanadından henüz net bir karar açıklanmadı. "
            "Sendikalar acil müdahale beklerken işveren tarafı temkinli. Karar yıl ortasında netleşecek."
        ),
        highlights=[
            Highlight(text="ara zam", color="yellow"),
            Highlight(text="milyonlarca çalışanı", color="yellow"),
            Highlight(text="alım gücü eridi", color="red"),
        ],
        category="EKONOMİ",
        mood="neutral",
    )

    bg = Path("data/cache/images/6f73555c59ac6026.jpg")
    if not bg.exists():
        candidates = sorted(Path("data/cache/images").glob("*.jpg"))
        bg = candidates[-1] if candidates else None

    job = RenderJob(
        script=script,
        bg_image_path=bg,
        music_path=Path("dummy.mp3"),
        channel_colors={
            "primary": "#c81e1e",
            "accent": "#ffea3b",
            "bg_gradient": ["#1a3b6b", "#0a1a3b"],
        },
        handle="@HaberShortsTR",
        duration_s=6,
        cta_enabled=False,
        cta_text="BEĞEN · ABONE OL · PAYLAŞ",
        cta_icons=["❤️", "🔔", "↗️"],
        cta_duration_s=3,
        cta_show_handle=True,
    )

    template = Path("templates/default.html.j2")
    html = build_html(job, template)

    out_dir = Path("tmp")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 3 timestamps: early (1s), mid (3.5s), end (5.8s) — should all look identical now
    timestamps_ms = {
        "v1_1000ms.png": 1000,
        "v1_3500ms.png": 3500,
        "v1_5800ms.png": 5800,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.add_init_script("document.getAnimations().forEach(a => a.pause());")
        page.set_content(html, wait_until="networkidle")
        for name, t_ms in timestamps_ms.items():
            page.evaluate(
                "(t) => { document.getAnimations().forEach(a => { a.currentTime = t; }); }",
                t_ms,
            )
            out = out_dir / name
            page.screenshot(path=str(out))
            print(f"{name} → {out.resolve()}")
        browser.close()


if __name__ == "__main__":
    main()
