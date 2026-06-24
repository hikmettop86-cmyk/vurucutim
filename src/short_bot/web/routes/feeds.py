"""RSS Havuzu — feed ekleme/silme + manuel haber seçimi → video üretimi."""
import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import feedparser
import requests
from flask import (Blueprint, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.db import (
    init_db, add_feed, list_feeds, get_feed, delete_feed, set_feed_meta,
)
from short_bot.fetcher import fetch_feed_url
from short_bot.extractor import extract_og_image_url
from short_bot.web.runs import launch_pipeline
from short_bot.config import load_channel, list_channels
from short_bot.models import NewsItem

bp = Blueprint("feeds", __name__)

_IMG_SRC_RE = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.IGNORECASE)


def _first_img_in_html(html):
    """RSS description HTML'inden ilk <img src> değerini çıkar (yoksa None).
    Çoğu feed media:thumbnail vermez ama description gövdesinde görsel taşır;
    bu sayede haber önizlemesinde mümkün olduğunca gerçek görsel gösterilir."""
    if not html:
        return None
    m = _IMG_SRC_RE.search(html)
    return m.group(1) if m else None


@lru_cache(maxsize=512)
def _og_image_cached(link):
    """Makale sayfasından og:image çek (sonuç — None dahil — cache'lenir, böylece
    aynı feed tekrar açıldığında ve başarısız fetch'lerde yeniden indirme olmaz)."""
    if not link:
        return None
    try:
        return extract_og_image_url(link, timeout=8)
    except Exception:
        return None


def _resolve_item_image(n):
    """Haber önizleme görseli: feed thumbnail → açıklama görseli → makale og:image.
    İlk ikisi HTTP gerektirmez; og:image makale sayfasını indirir (paralel çağrılır)."""
    return (n.thumb_url or _first_img_in_html(n.description)
            or _og_image_cached(n.link))


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


@bp.route("/feeds/<int:feed_id>/items")
def items(feed_id):
    from flask import abort
    from datetime import datetime, timezone
    from short_bot.db import is_processed, similar_title_exists
    eng = _eng()
    feed = get_feed(eng, feed_id)
    if feed is None:
        abort(404)
    try:
        news = fetch_feed_url(feed.url)
        set_feed_meta(eng, feed_id, last_fetched_at=datetime.now(timezone.utc),
                      last_error="")
    except Exception as e:
        set_feed_meta(eng, feed_id, last_error=str(e))
        news = []
    channels = list_channels(current_app.config["SHORTBOT_CONFIG_DIR"] / "channels")
    # Görselleri paralel çöz: og:image fallback makale sayfasını indirir, tek tek
    # yapmak haber sayısı kadar seri HTTP demek olurdu. lru_cache tekrar açılışı hızlandırır.
    with ThreadPoolExecutor(max_workers=10) as ex:
        images = list(ex.map(_resolve_item_image, news))
    enriched = []
    for n, image in zip(news, images):
        done = any(is_processed(eng, n.guid, c.slug) or
                   similar_title_exists(eng, n.title, c.slug, threshold=0.85)
                   for c in channels)
        enriched.append({"item": n, "done": done, "image": image})
    return render_template("_feed_items.html.j2", feed=feed,
                           items=enriched, channels=channels)


@bp.route("/feeds/items/produce", methods=["POST"])
def produce():
    from flask import abort
    slug = (request.form.get("channel_slug") or "").strip()
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    channel_path = cfg_dir / "channels" / f"{slug}.yaml"
    if not slug or not channel_path.exists():
        abort(404)
    channel = load_channel(channel_path)

    pub_date = None
    raw_pub = (request.form.get("pub_date") or "").strip()
    if raw_pub:
        from datetime import datetime
        try:
            pub_date = datetime.fromisoformat(raw_pub)
        except ValueError:
            pub_date = None

    item = NewsItem(
        guid=request.form.get("guid", ""),
        title=request.form.get("title", ""),
        link=request.form.get("link", ""),
        source=(request.form.get("source") or None),
        pub_date=pub_date,
        thumb_url=(request.form.get("thumb_url") or None),
        description=(request.form.get("description") or None),
    )

    launch_pipeline(
        channel=channel,
        settings=current_app.config["SHORTBOT_SETTINGS"],
        db_path=current_app.config["SHORTBOT_DB_PATH"],
        music_root=current_app.config["SHORTBOT_MUSIC_ROOT"],
        templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
        cache_dir=current_app.config["SHORTBOT_CACHE_DIR"],
        lock_dir=current_app.config["SHORTBOT_LOCK_DIR"],
        logs_dir=current_app.config["SHORTBOT_LOGS_DIR"],
        trigger="manual_feed",
        preselected_item=item,
    )
    flash(f"Video üretimi başladı: {item.title[:60]} → {channel.name}. "
          f"İlerlemeyi Loglar sayfasından takip et.", "success")
    return redirect(url_for("feeds.list_view"))
