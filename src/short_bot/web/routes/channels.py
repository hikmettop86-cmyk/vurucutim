from flask import Blueprint, current_app, render_template

from short_bot.config import list_channels

bp = Blueprint("channels", __name__)


@bp.route("/channels")
def list_view():
    config_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    channels = list_channels(config_dir / "channels", enabled_only=False)
    return render_template("channels/list.html.j2", channels=channels)
