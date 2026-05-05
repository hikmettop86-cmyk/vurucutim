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
        colors=cfg.colors,
        handle=request.form.get("handle", cfg.handle),
        output_dir=cfg.output_dir,
        enabled=request.form.get("enabled") == "1",
        cta_enabled=cfg.cta_enabled,
        cta_text=cfg.cta_text,
        cta_icons=cfg.cta_icons,
        cta_duration_s=cfg.cta_duration_s,
        cta_show_handle=cfg.cta_show_handle,
        language=cfg.language,
        dna=cfg.dna,
        script_model=cfg.script_model,
    )
    save_channel(path, new_cfg)
    return redirect(url_for("channel_edit.edit", slug=slug))
