import shutil
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, make_response,
                   redirect, render_template, request, url_for)

from short_bot.config import list_channels, load_channel, save_channel
from short_bot.web.models import Run


def _htmx_redirect(url: str):
    """HTMX-aware redirect: uses HX-Redirect header for HTMX, regular redirect otherwise."""
    if request.headers.get("HX-Request"):
        resp = make_response("", 200)
        resp.headers["HX-Redirect"] = url
        return resp
    return redirect(url)

bp = Blueprint("channels", __name__)


@bp.route("/channels")
def list_view():
    config_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    channels = list_channels(config_dir / "channels", enabled_only=False)
    return render_template("channels/list.html.j2", channels=channels)


@bp.route("/runs/<int:run_id>/status")
def run_status(run_id):
    """HTMX polling endpoint: returns the run_status partial for the given run."""
    run = Run.query.filter_by(id=run_id).first()
    if run is None:
        abort(404)
    return render_template("_partials/run_status.html.j2", status=run.status, run_id=run.id)


@bp.route("/runs/<int:run_id>/cancel", methods=["POST"])
def cancel_run(run_id):
    """Mark a running job as cancelled. The underlying daemon thread will finish but UI reflects cancellation."""
    from datetime import datetime
    from short_bot.web.extensions import db
    run = Run.query.filter_by(id=run_id).first()
    if run is None:
        abort(404)
    if run.status not in {"running", None}:
        flash(f"Run zaten '{run.status}' durumunda.", "error")
    else:
        run.status = "cancelled"
        run.ended_at = datetime.utcnow()
        db.session.commit()
        flash(f"Run #{run_id} iptal işaretlendi.", "success")
    return _htmx_redirect(request.referrer or url_for("channels.list_view"))


@bp.route("/channels/<slug>/delete", methods=["POST"])
def delete(slug):
    """Delete a channel: removes yaml + css + output dir."""
    cfg_dir: Path = current_app.config["SHORTBOT_CONFIG_DIR"]
    yaml_path = cfg_dir / "channels" / f"{slug}.yaml"
    if not yaml_path.exists():
        abort(404)
    css_path = current_app.config["SHORTBOT_TEMPLATES_DIR"] / "css" / f"{slug}.css"
    output_dir: Path = current_app.config["SHORTBOT_OUTPUT_ROOT"] / slug

    yaml_path.unlink(missing_ok=True)
    css_path.unlink(missing_ok=True)
    if output_dir.exists() and output_dir.is_dir():
        shutil.rmtree(output_dir, ignore_errors=True)

    flash(f"Kanal '{slug}' silindi.", "success")
    return _htmx_redirect(url_for("channels.list_view"))


@bp.route("/channels/<slug>/toggle", methods=["POST"])
def toggle(slug):
    """Quick enable/disable toggle from list view."""
    cfg_dir: Path = current_app.config["SHORTBOT_CONFIG_DIR"]
    yaml_path = cfg_dir / "channels" / f"{slug}.yaml"
    if not yaml_path.exists():
        abort(404)
    cfg = load_channel(yaml_path)
    new_cfg = type(cfg)(**{**cfg.__dict__, "enabled": not cfg.enabled})
    save_channel(yaml_path, new_cfg)
    state = "açıldı" if new_cfg.enabled else "kapatıldı"
    flash(f"'{slug}' {state}.", "success")
    if request.headers.get("HX-Request"):
        # Return updated row for HTMX swap
        return render_template("_partials/channel_row.html.j2", c=new_cfg)
    return redirect(url_for("channels.list_view"))


@bp.route("/channels/<slug>/clone", methods=["POST"])
def clone(slug):
    """Duplicate a channel as <slug>-copy (yaml + css)."""
    cfg_dir: Path = current_app.config["SHORTBOT_CONFIG_DIR"]
    src_yaml = cfg_dir / "channels" / f"{slug}.yaml"
    if not src_yaml.exists():
        abort(404)
    cfg = load_channel(src_yaml)

    # Find an available slug (slug-copy, slug-copy-2, ...)
    base = f"{slug}-copy"
    new_slug = base
    n = 2
    while (cfg_dir / "channels" / f"{new_slug}.yaml").exists():
        new_slug = f"{base}-{n}"
        n += 1

    new_cfg = type(cfg)(**{**cfg.__dict__,
                           "slug": new_slug,
                           "name": f"{cfg.name} (kopya)",
                           "enabled": False,
                           "output_dir": f"output/{new_slug}",
                           "handle": f"@{new_slug}"})
    save_channel(cfg_dir / "channels" / f"{new_slug}.yaml", new_cfg)

    # Copy CSS if exists
    src_css = current_app.config["SHORTBOT_TEMPLATES_DIR"] / "css" / f"{slug}.css"
    if src_css.exists():
        dst_css = current_app.config["SHORTBOT_TEMPLATES_DIR"] / "css" / f"{new_slug}.css"
        shutil.copy2(src_css, dst_css)

    flash(f"Kanal kopyalandı: {new_slug}", "success")
    return _htmx_redirect(url_for("channel_edit.edit", slug=new_slug))
