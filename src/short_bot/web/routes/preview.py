import hashlib
import json
import logging
import os
import random
import socket
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, request, send_file

from short_bot.config import load_channel
from short_bot.locale import ui_labels_for
from short_bot.models import Highlight, RenderJob, Script
from short_bot.renderer import build_html
from short_bot.dna import build_css_override, DnaSpec, DnaPalette, DnaFonts, DnaTone

bp = Blueprint("preview", __name__)
_log = logging.getLogger(__name__)


@bp.route("/api/dna/defaults")
def dna_defaults():
    """Return the default palette + fonts for a given archetype.

    Used by the channel-edit page to auto-fill DNA fields when the user picks
    a different archetype from the dropdown.
    """
    from short_bot.dna import ARCHETYPE_DEFAULTS, ARCHETYPES
    archetype = request.args.get("archetype", "").strip()
    if archetype not in ARCHETYPES:
        return {"error": f"unknown archetype: {archetype!r}"}, 400
    defaults = ARCHETYPE_DEFAULTS.get(archetype)
    if not defaults:
        return {"error": f"no defaults defined for {archetype!r}"}, 404
    return {"archetype": archetype, **defaults}


def _load_sample_script(language: str) -> Script:
    samples = Path(__file__).resolve().parents[1] / "sample_scripts"
    sample_path = samples / f"sample_script_{language}.json"
    if not sample_path.exists():
        sample_path = samples / "sample_script_tr.json"
    data = json.loads(sample_path.read_text(encoding="utf-8"))
    data["highlights"] = [Highlight(**h) for h in data.get("highlights", [])]
    return Script(**data)


def _default_dna_for(template: str, channel) -> DnaSpec:
    """Stub DnaSpec when channel has no DNA — uses channel.colors."""
    from short_bot.dna import ARCHETYPES
    return DnaSpec(
        archetype=template if template in ARCHETYPES else "newscast",
        palette=DnaPalette(
            primary=channel.colors["primary"],
            accent=channel.colors["accent"],
            bg_gradient=channel.colors["bg_gradient"],
            body_bg=["#1a1a2a", "#0a0a1a"],
        ),
        fonts=DnaFonts(),
        tone=DnaTone(voice="neutral", style="concise"),
        persona_summary="default",
    )


@bp.route("/preview/<slug>")
def preview(slug):
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not cfg_path.exists():
        abort(404)
    cfg = load_channel(cfg_path)

    dna = cfg.dna or _default_dna_for(cfg.template, cfg)

    # Apply query param overrides (color picker / dropdown / pill live tweaks)
    palette_update = {}
    if request.args.get("primary"):
        palette_update["primary"] = request.args["primary"]
    if request.args.get("accent"):
        palette_update["accent"] = request.args["accent"]
    bg1 = request.args.get("bg_grad_1")
    bg2 = request.args.get("bg_grad_2")
    if bg1 or bg2:
        palette_update["bg_gradient"] = [
            bg1 or dna.palette.bg_gradient[0],
            bg2 or dna.palette.bg_gradient[1],
        ]
    body1 = request.args.get("body_bg_1")
    body2 = request.args.get("body_bg_2")
    if body1 or body2:
        palette_update["body_bg"] = [
            body1 or dna.palette.body_bg[0],
            body2 or dna.palette.body_bg[1],
        ]
    if request.args.get("text_main"):
        palette_update["text_main"] = request.args["text_main"]
    if request.args.get("text_muted"):
        palette_update["text_muted"] = request.args["text_muted"]
    # Optional headline overrides ("" means "use template default")
    if "header_top_color" in request.args:
        palette_update["header_top_color"] = request.args["header_top_color"]
    if "header_bottom_color" in request.args:
        palette_update["header_bottom_color"] = request.args["header_bottom_color"]
    if palette_update:
        dna = dna.model_copy(update={"palette": dna.palette.model_copy(update=palette_update)})

    fonts_update = {}
    if request.args.get("font_headline"):
        fonts_update["headline"] = request.args["font_headline"]
    if request.args.get("font_body"):
        fonts_update["body"] = request.args["font_body"]
    if fonts_update:
        dna = dna.model_copy(update={"fonts": dna.fonts.model_copy(update=fonts_update)})

    # Top-level Literal fields — use the canonical ARCHETYPES list (single source of truth)
    from short_bot.dna import ARCHETYPES
    valid_archetypes = set(ARCHETYPES)
    top_update = {}
    if request.args.get("archetype") in valid_archetypes:
        top_update["archetype"] = request.args["archetype"]
    if request.args.get("banner_shape") in {"flat", "ribbon", "slanted", "sharp"}:
        top_update["banner_shape"] = request.args["banner_shape"]
    if request.args.get("highlight_style") in {"bg-flat", "underline", "marker", "neon"}:
        top_update["highlight_style"] = request.args["highlight_style"]
    if request.args.get("chip_style") in {"rounded", "sharp", "pill"}:
        top_update["chip_style"] = request.args["chip_style"]
    if request.args.get("category_icon") is not None:
        top_update["category_icon"] = request.args["category_icon"][:4]
    if top_update:
        dna = dna.model_copy(update=top_update)

    # Template comes from archetype override if present, else channel default
    template_name = (request.args.get("archetype")
                     if request.args.get("archetype") in valid_archetypes
                     else cfg.template)

    # CTA params (override channel's saved values for live preview)
    cta_enabled_str = request.args.get("cta_enabled", "")
    cta_enabled = cta_enabled_str == "1" if cta_enabled_str else False
    cta_text = request.args.get("cta_text", "").strip() or (cfg.cta_text or "BEĞEN · ABONE OL · PAYLAŞ")
    cta_show_handle_str = request.args.get("cta_show_handle", "")
    cta_show_handle = cta_show_handle_str == "1" if cta_show_handle_str else cfg.cta_show_handle
    # RSS source preview (so user sees "Kaynak: NTV" overlay positioning before saving)
    rss_source = request.args.get("rss_source", "").strip() or None

    script = _load_sample_script(cfg.language)
    job = RenderJob(
        script=script, bg_image_path=None,
        music_path=Path("dummy.mp3"),
        channel_colors={
            "primary": dna.palette.primary,
            "accent": dna.palette.accent,
            "bg_gradient": dna.palette.bg_gradient,
        },
        handle=cfg.handle, duration_s=cfg.duration_s,
        language=cfg.language,
        cta_enabled=cta_enabled,
        cta_text=cta_text,
        cta_icons=list(cfg.cta_icons or ["❤️", "🔔", "↗️"]),
        cta_duration_s=cfg.cta_duration_s or 4,
        cta_show_handle=cta_show_handle,
        rss_source=rss_source,
    )
    # sanitize_palette = yaml-original (custom_css o palette ile yazıldı);
    # dna.palette = canlı override (renk picker'lar) — :root override'a girer.
    original_palette = cfg.dna.palette if cfg.dna else dna.palette
    dna_css = build_css_override(dna, sanitize_palette=original_palette)
    template_path = current_app.config["SHORTBOT_TEMPLATES_DIR"] / f"{template_name}.html.j2"
    html = build_html(job, template_path,
                      ui_labels=ui_labels_for(cfg.language),
                      dna_css=dna_css)
    return Response(html, mimetype="text/html")


# ── Remotion live snapshot preview (Phase 6a) ──────────────────────────────

def _remotion_preview_cache_dir() -> Path:
    """Cache previews under the configured cache dir so they survive across
    pipeline runs but don't litter the project tree."""
    cache_root = current_app.config.get("SHORTBOT_CACHE_DIR") or Path("data/cache")
    out = Path(cache_root) / "remotion-previews"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _load_sample_script_for_remotion(language: str, channel) -> tuple[str, str, str, str, str]:
    """Return (header_top, header_bottom, photo_overlay, body, handle) for
    the snapshot. Uses the same sample as the HTML preview so changing
    renderers shows the same content."""
    s = _load_sample_script(language)
    return (
        s.header_top, s.header_bottom, s.photo_overlay,
        s.body_paragraph, channel.handle,
    )


@bp.route("/preview/<slug>/remotion-frame")
def remotion_frame_preview(slug):
    """Return one rendered frame of the channel's Remotion template with
    the query-param overrides applied. Used by the channel-edit Remotion
    tab for live-update preview as the user changes dimensions/colors.
    """
    from short_bot.remotion_renderer import (
        render_still, render_job_from_pipeline,
        ADAPTIVE_DIMENSION_OPTIONS, RemotionRenderError,
    )
    from types import SimpleNamespace

    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not cfg_path.exists():
        abort(404)
    cfg = load_channel(cfg_path)

    # Color overrides from query (mirror HTML preview semantics)
    primary = request.args.get("primary") or cfg.colors.get("primary", "#c8102e")
    accent  = request.args.get("accent")  or cfg.colors.get("accent", "#ffb81c")
    bg_grad = cfg.colors.get("bg_gradient", ["#0a1733", "#1a2a4f"])
    bg1 = request.args.get("bg_grad_1") or (bg_grad[0] if len(bg_grad) > 0 else "#0a1733")
    bg2 = request.args.get("bg_grad_2") or (bg_grad[1] if len(bg_grad) > 1 else "#1a2a4f")

    # Template selection — query overrides channel default for live tweaking
    template = (
        request.args.get("remotion_template")
        or cfg.remotion_template
        or cfg.resolved_remotion_template
    )

    # Adaptive dimensions: form may push partial overrides
    dimensions = dict(cfg.remotion_dimensions or {})
    for axis, valid in ADAPTIVE_DIMENSION_OPTIONS.items():
        v = request.args.get(f"dim_{axis}", "").strip()
        if v:
            if v in valid:
                dimensions[axis] = v
            # invalid value silently dropped — preview still works
    if template != "adaptive":
        dimensions = {}  # other templates don't read this prop

    headline, sub, overlay, body, handle = _load_sample_script_for_remotion(
        cfg.language, cfg
    )
    script = SimpleNamespace(
        header_top=headline, header_bottom=sub,
        photo_overlay=overlay or "Test",
        body_paragraph=body or "Önizleme için örnek metin.",
        category=request.args.get("category", "GENEL"),
    )

    job = render_job_from_pipeline(
        script=script,
        channel_colors={"primary": primary, "accent": accent,
                        "bg_gradient": [bg1, bg2]},
        handle=handle,
        duration_s=6,
        template=template,
        bg_image_path=None,
        dimensions=dimensions or None,
    )

    # Cache key: hash of all props that affect the rendered output.
    cache_key_blob = json.dumps(job.to_props_dict(), sort_keys=True, ensure_ascii=False)
    cache_key = hashlib.sha256(cache_key_blob.encode("utf-8")).hexdigest()[:16]
    cache_dir = _remotion_preview_cache_dir()
    cached = cache_dir / f"{cache_key}.jpg"

    if not cached.exists():
        # Pick a random free port in 3220-3299. Shuffle grid renders 6
        # thumbnails in parallel; if they all targeted port 3220 they'd
        # collide (port-in-use → exit 1 silent failure). Each call gets
        # its own port so Remotion can spin up its bundler concurrently.
        port = _pick_free_port_in_range(3220, 3300)
        try:
            render_still(job, cached, frame=30, port=port, timeout_s=60)
        except RemotionRenderError as e:
            _log.warning(f"remotion preview failed: {e}")
            return Response(f"preview failed: {e}", status=500, mimetype="text/plain")

    return send_file(str(cached), mimetype="image/jpeg",
                      max_age=0, conditional=True)


def _pick_free_port_in_range(low: int, high: int, attempts: int = 10) -> int:
    """Try to find a free TCP port in [low, high). Falls back to a random
    port in range after `attempts` tries — Remotion will fail loudly if it
    can't bind, which is more diagnostic than a silent collision."""
    for _ in range(attempts):
        p = random.randint(low, high - 1)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", p))
            s.close()
            return p
        except OSError:
            try: s.close()
            except OSError: pass
            continue
    return random.randint(low, high - 1)
