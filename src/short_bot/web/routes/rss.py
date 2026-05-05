from datetime import datetime, timedelta

from flask import Blueprint, render_template, request

from short_bot.web.models import RssItem

bp = Blueprint("rss", __name__)


@bp.route("/rss")
def list_view():
    cutoff = datetime.utcnow() - timedelta(hours=24)
    items = (RssItem.query
              .filter(RssItem.fetched_at >= cutoff)
              .order_by(RssItem.score.desc().nullslast(), RssItem.fetched_at.desc())
              .limit(200).all())
    return render_template("rss.html.j2", items=items)
