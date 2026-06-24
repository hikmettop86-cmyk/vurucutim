"""RSS Havuzu — feed ekleme/silme + manuel haber seçimi → video üretimi."""
import feedparser
import requests
from flask import (Blueprint, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.db import (
    init_db, add_feed, list_feeds, get_feed, delete_feed, set_feed_meta,
)
from short_bot.fetcher import fetch_feed_url

bp = Blueprint("feeds", __name__)


def _eng():
    return init_db(current_app.config["SHORTBOT_DB_PATH"])


@bp.route("/feeds")
def list_view():
    feeds = list_feeds(_eng())
    return render_template("feeds.html.j2", feeds=feeds)


@bp.route("/feeds/add", methods=["POST"])
def add():
    url = (request.form.get("url") or "").strip()
    if not url:
        flash("Feed URL'si boş olamaz.", "error")
        return redirect(url_for("feeds.list_view"))
    try:
        r = requests.get(url, timeout=15,
                         headers={"User-Agent": "short-bot/0.1"})
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
    except Exception as e:
        flash(f"Feed alınamadı: {e}", "error")
        return redirect(url_for("feeds.list_view"))
    if not parsed.entries:
        flash("Bu adres geçerli bir RSS/Atom feed'i değil (haber bulunamadı).",
              "error")
        return redirect(url_for("feeds.list_view"))
    title = (parsed.feed.get("title") if parsed.feed else None) or url
    try:
        add_feed(_eng(), url=url, title=title)
        flash(f"Feed eklendi: {title}", "success")
    except Exception:
        flash("Bu feed zaten ekli.", "error")
    return redirect(url_for("feeds.list_view"))


@bp.route("/feeds/<int:feed_id>/delete", methods=["POST"])
def delete(feed_id):
    delete_feed(_eng(), feed_id)
    flash("Feed silindi.", "success")
    return redirect(url_for("feeds.list_view"))
