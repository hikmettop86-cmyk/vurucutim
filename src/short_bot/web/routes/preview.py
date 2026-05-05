from flask import Blueprint

bp = Blueprint("preview", __name__)


@bp.route("/preview/<slug>")
def preview_view(slug):
    return f"Preview (stub): {slug}"
