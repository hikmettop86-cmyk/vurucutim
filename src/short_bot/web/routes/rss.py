from flask import Blueprint

bp = Blueprint("rss", __name__)


@bp.route("/rss")
def list_view():
    return "RSS (stub)"
