import json
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, request

from short_bot.config import load_channel
from short_bot.locale import ui_labels_for
from short_bot.models import Highlight, RenderJob, Script
from short_bot.renderer import build_html
from short_bot.dna import build_css_override, DnaSpec, DnaPalette, DnaFonts, DnaTone

bp = Blueprint("preview", __name__)


def _load_sample_script(language: str) -> Script:
    fixtures = Path(__file__).resolve().parents[4] / "tests" / "fixtures"
    sample_path = fixtures / f"sample_script_{language}.json"
    if not sample_path.exists():
        sample_path = fixtures / "sample_script_tr.json"
    data = json.loads(sample_path.read_text(encoding="utf-8"))
    data["highlights"] = [Highlight(**h) for h in data.get("highlights", [])]
    return Script(**data)


def _default_dna_for(template: str, channel) -> DnaSpec:
    """Stub DnaSpec when channel has no DNA — uses channel.colors."""
    return DnaSpec(
        archetype=template if template in [
            "newscast", "tabloid", "magazine", "kinetic", "dark-tech", "stadium", "meme"
        ] else "newscast",
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

    # Apply query param overrides (color picker live tweaks)
    if request.args.get("primary"):
        dna = dna.model_copy(update={"palette": dna.palette.model_copy(
            update={"primary": request.args["primary"]})})
    if request.args.get("accent"):
        dna = dna.model_copy(update={"palette": dna.palette.model_copy(
            update={"accent": request.args["accent"]})})
    if request.args.get("font_headline"):
        dna = dna.model_copy(update={"fonts": dna.fonts.model_copy(
            update={"headline": request.args["font_headline"]})})

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
        language=cfg.language, cta_enabled=False,
    )
    dna_css = build_css_override(dna)
    template_path = current_app.config["SHORTBOT_TEMPLATES_DIR"] / f"{cfg.template}.html.j2"
    html = build_html(job, template_path,
                      ui_labels=ui_labels_for(cfg.language),
                      dna_css=dna_css)
    return Response(html, mimetype="text/html")
