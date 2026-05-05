from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for

from short_bot.config import ChannelConfig, load_channel, save_channel

bp = Blueprint("channel_edit", __name__)


def _yaml_path(slug: str):
    return current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"


@bp.route("/channels/<slug>/edit", methods=["GET"])
def edit(slug):
    path = _yaml_path(slug)
    if not path.exists():
        abort(404)
    cfg = load_channel(path)
    return render_template("channels/edit.html.j2", c=cfg)


@bp.route("/channels/<slug>/edit", methods=["POST"])
def save(slug):
    path = _yaml_path(slug)
    if not path.exists():
        abort(404)
    cfg = load_channel(path)

    keywords = [k.strip() for k in request.form.get("keywords", "").split(",") if k.strip()]

    new_dna = cfg.dna
    if cfg.dna and request.form.get("dna_primary"):
        # Apply DNA tweaks from form
        from short_bot.dna import build_css_override
        new_dna = cfg.dna.model_copy(update={
            "palette": cfg.dna.palette.model_copy(update={
                "primary": request.form.get("dna_primary", cfg.dna.palette.primary),
                "accent": request.form.get("dna_accent", cfg.dna.palette.accent),
            }),
            "fonts": cfg.dna.fonts.model_copy(update={
                "headline": request.form.get("dna_font_headline", cfg.dna.fonts.headline),
                "body": request.form.get("dna_font_body", cfg.dna.fonts.body),
            }),
            "banner_shape": request.form.get("dna_banner_shape", cfg.dna.banner_shape),
            "highlight_style": request.form.get("dna_highlight_style", cfg.dna.highlight_style),
            "chip_style": request.form.get("dna_chip_style", cfg.dna.chip_style),
            "category_icon": request.form.get("dna_category_icon", cfg.dna.category_icon),
        })
        # Rebuild CSS
        templates_dir = current_app.config["SHORTBOT_TEMPLATES_DIR"]
        css_path = templates_dir / "css" / f"{slug}.css"
        css_path.parent.mkdir(parents=True, exist_ok=True)
        css_path.write_text(build_css_override(new_dna), encoding="utf-8")

    new_cfg = ChannelConfig(
        slug=cfg.slug,
        name=cfg.name,
        keywords=keywords,
        rss_locale=cfg.rss_locale,
        schedule_cron=request.form.get("schedule_cron", cfg.schedule_cron),
        duration_s=int(request.form.get("duration_s", cfg.duration_s)),
        min_score=float(request.form.get("min_score", cfg.min_score)),
        max_candidates_per_run=cfg.max_candidates_per_run,
        template=cfg.template,
        colors={
            "primary": new_dna.palette.primary if new_dna else cfg.colors["primary"],
            "accent": new_dna.palette.accent if new_dna else cfg.colors["accent"],
            "bg_gradient": cfg.colors["bg_gradient"],
        },
        handle=request.form.get("handle", cfg.handle),
        output_dir=cfg.output_dir,
        enabled=request.form.get("enabled") == "1",
        cta_enabled=cfg.cta_enabled,
        cta_text=cfg.cta_text,
        cta_icons=cfg.cta_icons,
        cta_duration_s=cfg.cta_duration_s,
        cta_show_handle=cfg.cta_show_handle,
        language=cfg.language,
        dna=new_dna,
        script_model=cfg.script_model,
    )
    save_channel(path, new_cfg)
    return redirect(url_for("channel_edit.edit", slug=slug))
