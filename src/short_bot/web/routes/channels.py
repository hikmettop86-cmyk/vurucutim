from flask import Blueprint

bp = Blueprint("channels", __name__)


@bp.route("/channels")
def list_view():
    return "Channels (stub)"
