"""One-off render of a verification frame using a fixed Script (no claude CLI)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from short_bot.models import RenderJob, Script, Highlight
from short_bot.renderer import build_html
from playwright.sync_api import sync_playwright


def main():
    script = Script(
        header_top="ARA ZAM",
        header_bottom="AÇIKLAMASI",
        photo_overlay="İKTİDARDAN NET YANIT",
        body_paragraph=(
            "Sendikalar düşen alım gücüne karşı ara zam çağrısı yaptı. "
            "Konuya ilişkin AKP cephesinden açıklama geldi. "
            "İktidar partisi, ara zam talebine ilişkin tutumunu netleştirdi. "
            "Çalışanlar ve emekliler kararı merakla bekliyordu. "
            "Hükümetin tutumu kamuoyunda tartışma yarattı."
        ),
        highlights=[
            Highlight(text="ara zam çağrısı", color="yellow"),
            Highlight(text="AKP cephesinden açıklama", color="red"),
        ],
        category="SİYASET",
        mood="breaking",
    )
    job = RenderJob(
        script=script,
        bg_image_path=None,
        music_path=Path("dummy.mp3"),
        channel_colors={
            "primary": "#c81e1e",
            "accent": "#ffea3b",
            "bg_gradient": ["#1a3b6b", "#0a1a3b"],
        },
        handle="@HaberShortsTR",
        duration_s=30,
        cta_enabled=True,
        cta_text="BEĞEN · ABONE OL · PAYLAŞ",
        cta_icons=["❤️", "🔔", "↗️"],
        cta_duration_s=4,
        cta_show_handle=True,
    )

    template = Path("templates/default.html.j2")
    html = build_html(job, template)

    out = Path("tmp/test_frame.png")
    out.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.set_content(html, wait_until="networkidle")
        # Pause animations and step to t=2500ms (after progress has advanced, before CTA at t=26s)
        page.add_init_script("document.getAnimations().forEach(a => a.pause());")
        page.evaluate(
            "(t) => { document.getAnimations().forEach(a => { a.currentTime = t; }); }",
            2500,
        )
        page.screenshot(path=str(out))
        browser.close()

    print(f"Saved: {out.resolve()}")


if __name__ == "__main__":
    main()
