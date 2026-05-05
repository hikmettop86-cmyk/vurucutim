from flask import Blueprint, abort, current_app, render_template

from short_bot.config import list_channels
from short_bot.web.models import Run

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
