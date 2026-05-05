from flask import Blueprint

bp = Blueprint("shorts", __name__)


@bp.route("/shorts")
def list_view():
    return "Shorts (stub)"
