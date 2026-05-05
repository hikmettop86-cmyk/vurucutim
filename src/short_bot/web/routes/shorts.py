from flask import Blueprint, render_template, request

from short_bot.web.models import Short

bp = Blueprint("shorts", __name__)


@bp.route("/shorts")
def list_view():
    channel = request.args.get("channel", "").strip()
    q = request.args.get("q", "").strip()
    query = Short.query.filter(Short.deleted_at.is_(None))
    if channel:
        query = query.filter(Short.channel == channel)
    if q:
        query = query.filter(Short.title.ilike(f"%{q}%"))
    shorts = query.order_by(Short.created_at.desc()).limit(60).all()
    return render_template("shorts/list.html.j2",
                            channel=channel,
                            q=q,
                            shorts=shorts)


@bp.route("/shorts/grid")
def grid_partial():
    """HTMX partial: filter result grid swap."""
    channel = request.args.get("channel", "").strip()
    q = request.args.get("q", "").strip()
    query = Short.query.filter(Short.deleted_at.is_(None))
    if channel:
        query = query.filter(Short.channel == channel)
    if q:
        query = query.filter(Short.title.ilike(f"%{q}%"))
    shorts = query.order_by(Short.created_at.desc()).limit(60).all()
    return render_template("_partials/shorts_grid.html.j2", shorts=shorts)
