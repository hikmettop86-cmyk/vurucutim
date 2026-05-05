from flask import Blueprint

bp = Blueprint("channel_edit", __name__)


@bp.route("/channels/<slug>/edit")
def edit_view(slug):
    return f"Channel Edit (stub): {slug}"
