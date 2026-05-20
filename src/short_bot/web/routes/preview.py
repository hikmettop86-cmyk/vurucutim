import json
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, request

from short_bot.config import load_channel
from short_bot.locale import ui_labels_for
from short_bot.models import Highlight, RenderJob, Script
from short_bot.renderer import build_html
from short_bot.dna import build_css_override, DnaSpec, DnaPalette, DnaFonts, DnaTone

bp = Blueprint("preview", __name__)


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

    # Style knob overrides (Phase A2 "Stil Düzenle" tab)
    knob_update: dict = {}
    knob_specs = [
        ("banner_skew_deg",  float),
        ("header_padding_y", int),
        ("header_size_top",  int),
        ("header_size_bot",  int),
        ("photo_height",     int),
        ("photo_blur_px",    float),
        ("photo_saturation", float),
        ("body_font_size",   int),
        ("body_line_height", float),
        ("corner_radius",    int),
        ("letter_spacing",   float),
        ("shadow_intensity", float),
    ]
    for key, kind in knob_specs:
        raw = request.args.get(f"knob_{key}")
        if raw is None or raw == "":
            continue
        try:
            knob_update[key] = kind(raw)
        except (TypeError, ValueError):
            pass  # silently drop invalid input
    if knob_update:
        dna = dna.model_copy(update={"style_knobs": dna.style_knobs.model_copy(update=knob_update)})

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


# NOTE (v0.1.94): Remotion preview endpoint removed — entire Remotion
# subsystem was deprecated. HTML iframe preview above is the sole path.
