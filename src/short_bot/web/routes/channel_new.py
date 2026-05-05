from flask import Blueprint

bp = Blueprint("channel_new", __name__)


@bp.route("/channels/new")
def new_view():
    return "Channel New (stub)"
