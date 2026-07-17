"""Reel şeffaf overlay: HTML üret + Playwright PNG dizisi (alfa)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from short_bot.reel_colors import contrast_text, ensure_bright
from short_bot.reel_models import ReelTimeline

log = logging.getLogger(__name__)

# BEĞENİ/ABONE ÇİPİ YOK (2026-07-16, kullanıcı kararı): "kullanıcı gerçekten
# içinden gelirse abone veya beğenme yapar" — ekranda hiçbir beğeni/abone istemi
# gösterilmez. (Eski mekanik: tepe-sonrası beğeni nabzı + abone çipi.)

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
    flash: bool = True, cut_effect: str = "flash",
    handle: str = "",
    badge: str = "",              # feed kimliği rozeti ("BİLİNMEYEN TARİH #47")
    question_text: str = "",      # açık-soru çipi metni ("" = çip yok; merak mimarisi)
    reveal_at_s: float | None = None,   # cevabın ödendiği saniye (çip ✓'ya döner)
    lang: str = "tr",             # CSS uppercase DİLE DUYARLI — lang'sız 'i' → 'I'
    font: str = "Montserrat",
    markers: list | None = None,
    numbers: list | None = None,
    interrupts: list | None = None,   # koordineli kesinti anları (bkz. reel_interrupt)
    templates_dir: Path | None = None,
    caption_color: str = "#fff",      # altyazı TABAN kelime rengi (kürate=solid sarı)
    caption_hot: str | None = None,   # aktif kelime rengi (None → hot_color; kürate=beyaz)
) -> str:
    if layout not in ("classic", "lower_left", "top_heavy"):
        layout = "classic"
    # cut_effect: kesmede uygulanan efekt TÜRÜ (flash/glitch/rgbsplit/lightleak/none).
    # flash: geriye-uyum ana anahtarı — flash=False iken hiçbir kesme efekti gösterilmez.
    if cut_effect not in ("flash", "glitch", "rgbsplit", "lightleak", "none"):
        cut_effect = "flash"
    if not flash:
        cut_effect = "none"
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
        caption_color=caption_color,
        caption_hot=(caption_hot or ensure_bright(highlight_color)),
        hook=timeline.hook, close=timeline.close, handle=handle,
        cover_title=getattr(timeline, "cover_title", "") or "",
        badge=badge, lang=lang,
        question_text=(question_text or "").strip()[:48],
        reveal_at=f"{(reveal_at_s or 0.0):.3f}",
        font=font, font_import=_FONT_IMPORTS.get(font, _FONT_IMPORTS["Montserrat"]),
        words=words, cards=cards, duration_s=f"{timeline.duration_s:.3f}",
        last_seg=last_seg, cuts=json.dumps(cuts),
        arrow_segs=json.dumps(arrow_segs), flash=flash, cut_effect=cut_effect,
        markers=json.dumps(markers or []),
        interrupts=json.dumps([round(float(t), 3) for t in (interrupts or [])]),
        nums=json.dumps(
            [{"text": n["text"], "s": f"{float(n['start_s']):.3f}",
              "e": f"{float(n['end_s']):.3f}"} for n in (numbers or [])],
            ensure_ascii=False),
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
        # Font @import ağ isteği yaptığı için networkidle'ı sınırla: yavaş/erişilemez
        # ağda bekleme render'ı ÇÖKERTMESİN — içerik yine yüklü, font sistem
        # fontuna düşer (kozmetik). 8sn yeterli, sonra devam.
        try:
            pg.set_content(html, wait_until="networkidle", timeout=8000)
        except Exception:
            pass  # DOM zaten set edildi; font yüklenemedIyse fallback font kullanılır

        # Metni kutusuna sığdır — FONTLAR OTURDUKTAN SONRA, ilk kareden ÖNCE.
        # Ölçüm gerçek fonta bağlı: yedek fontla ölçersek punto yanlış çıkar.
        # Bir kez çalışır, tüm kareler aynı puntoyu görür (kare-dedup bozulmaz).
        try:
            pg.evaluate("()=>document.fonts&&document.fonts.ready")
            pg.evaluate("()=>window.__fit&&window.__fit()")
        except Exception:
            pass  # __fit yoksa (eski şablon) eski davranış: sığdırma yapılmaz

        # KARE-DEDUP: overlay ardışık karelerde çoğu zaman DEĞİŞMEZ (karaoke kelimesi
        # ~0.4sn'de bir değişir). Şablonun __sig() imzası aynıysa screenshot (~137ms)
        # yerine önceki PNG kopyalanır (~1ms) → render 3-4x hızlanır. __sig yoksa
        # (eski şablon) imza None kalır ve her kare çekilir (eski davranış).
        import shutil
        prev_sig = None
        prev_path: Path | None = None
        shot = 0
        for i in range(total):
            pg.evaluate("(t)=>window.__seek(t)", int(i / fps * 1000))
            try:
                sig = pg.evaluate("()=>window.__sig?window.__sig():null")
            except Exception:
                sig = None
            path = out_dir / f"f_{i:05d}.png"
            if sig is not None and sig == prev_sig and prev_path is not None:
                shutil.copyfile(prev_path, path)
                continue
            # animations="disabled": marker CSS animasyonları duvar-saatiyle koşup
            # deterministikliği bozmasın (aynı seed → aynı kareler). Belirteçler
            # yerinde/görünür kalır; geçiş efektleri JS/seek güdümlü, etkilenmez.
            pg.screenshot(path=str(path), omit_background=True,
                          animations="disabled")
            shot += 1
            prev_sig, prev_path = sig, path
        b.close()
    log.info(f"  reel: overlay {total} kare ({shot} çekildi, "
             f"{total - shot} kopyalandı)")
    return total
