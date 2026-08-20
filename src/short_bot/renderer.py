"""HTML render via Jinja2 → frame capture via Playwright."""
from __future__ import annotations

import base64
import mimetypes
import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from short_bot.models import RenderJob

log = logging.getLogger(__name__)

# Tarayıcı kopmasında kaç kez yeniden açılacağı. Sınırlı: her oturum anında
# koparsa (gerçek arıza) sonsuza kadar denemek üretimi asar. Kareler diskte
# birikerek ilerlediği için her yeniden açılış işi ileri taşır.
_RENDER_MAX_RESTARTS = 4

WIDTH = 1080
HEIGHT = 1920

# like/subscribe/share etiketleri KALDIRILDI (2026-07-16, kullanıcı kararı) —
# şablonlarda beğeni/abone öğesi kalmadı.
DEFAULT_UI_LABELS_TR: dict[str, str] = {
    "breaking": "SON DAKİKA",
}


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


def build_html(
    job: RenderJob,
    template_path: Path,
    *,
    ui_labels: dict[str, str] | None = None,
    dna_css: str = "",
    animation_style: str = "none",
    now: datetime | None = None,
) -> str:
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

    labels = DEFAULT_UI_LABELS_TR.copy()
    if ui_labels:
        labels.update(ui_labels)

    return template.render(
        script=job.script,
        body_html=body_html,
        bg_image_url=bg_url,
        colors=colors,
        handle=job.handle,
        duration_s=job.duration_s,
        category=job.script.category,
        language=job.language,
        ui_breaking=labels["breaking"],
        ui_source=labels.get("source", "Source"),
        dna_css=dna_css,
        animation_style=animation_style,
        rss_source=job.rss_source,
        narration=job.narration,
        ticker_items=list(job.ticker_items),
        # now: şablonun kendi biçiminde damgalayabilmesi için (Almanca haber
        # dilinde "Stand: 20.08.2026, 14:32 Uhr" standarttır — tarihsiz bir
        # haber kartı Alman izleyiciye eksik görünür). Şablonlar isterse
        # kullanır; kullanmayan hiçbir şablon etkilenmez.
        now=now or datetime.now(),
    )


def _total_frames(job: RenderJob, fps: int) -> int:
    """Voiced işlerde süre sesten, değilse kanal ayarından gelir."""
    if job.narration is not None:
        return int(round(job.narration.duration_s * fps))
    return job.duration_s * fps


def render_frames(
    job: RenderJob,
    template_path: Path,
    out_dir: Path,
    *,
    fps: int = 30,
    browser: str = "chromium",
    ui_labels: dict[str, str] | None = None,
    dna_css: str = "",
    animation_style: str = "none",
) -> int:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html = build_html(job, template_path, ui_labels=ui_labels, dna_css=dna_css,
                      animation_style=animation_style)

    total_frames = _total_frames(job, fps)

    # TARAYICI ORTADA KAPANIRSA İŞİ TERK ETME (canlı vaka: koşu #1587 ve iki CLI
    # koşusu "Page.screenshot: Target page ... has been closed" ile düştü).
    # Makinede başka bir otomasyon da Playwright kullanıyor; 6sn'lik videolar
    # 180 karede aradan sıyrılıyordu ama seslendirmeli videolar 1000+ kare
    # sürdüğü için o pencereye yakalanıp TÜM üretimi kaybettiriyordu — oysa o
    # ana kadar basılmış yüzlerce kare diskte hazır. Tarayıcıyı yeniden açıp
    # KALDIĞIMIZ KAREDEN devam ediyoruz (ai33 poll'ündeki geçici-hata felsefesi).
    basilan = 0
    kopma = 0
    while basilan < total_frames:
        try:
            with sync_playwright() as p:
                browser_obj = getattr(p, browser).launch()
                page = browser_obj.new_page(
                    viewport={"width": WIDTH, "height": HEIGHT},
                    device_scale_factor=1)
                page.set_content(html, wait_until="networkidle")
                # Wait for auto-fit script to finish — it awaits document.fonts.ready
                # so we don't screenshot mid-resize. Templates without auto-fit set
                # __autoFitDone to undefined; Promise.resolve() handles that case.
                page.evaluate("() => window.__autoFitDone || Promise.resolve()")
                # Pause CSS animations so we can step them via clock
                page.add_init_script(
                    "document.getAnimations().forEach(a => a.pause());")

                for i in range(basilan, total_frames):
                    t_ms = int((i / fps) * 1000)
                    page.evaluate(
                        "(t) => { document.getAnimations().forEach(a => "
                        "{ a.currentTime = t; }); }",
                        t_ms,
                    )
                    if job.narration is not None:
                        page.evaluate("(t) => window.__seek && window.__seek(t)",
                                      t_ms)
                    page.screenshot(path=str(out_dir / f"frame_{i:05d}.png"),
                                    omit_background=False)
                    basilan = i + 1

                browser_obj.close()
        except Exception as e:  # noqa: BLE001 — kopma sınıfı sürücüye göre değişir
            kopma += 1
            if kopma > _RENDER_MAX_RESTARTS:
                raise RuntimeError(
                    f"render {kopma} kez koptu ve ilerleyemedi "
                    f"(kare {basilan}/{total_frames}): {e}") from e
            log.warning(
                f"  render kesintisi ({e.__class__.__name__}) — kare "
                f"{basilan}/{total_frames}'da tarayıcı yeniden açılıyor "
                f"({kopma}/{_RENDER_MAX_RESTARTS})")

    return total_frames
