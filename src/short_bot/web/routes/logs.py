from flask import Blueprint

bp = Blueprint("logs", __name__)


@bp.route("/logs")
def list_view():
    return "Logs (stub)"
