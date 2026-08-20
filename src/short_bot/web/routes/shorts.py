import json
from datetime import datetime, timedelta

from flask import (Blueprint, abort, current_app, flash, make_response,
                   redirect, render_template, request, url_for)

from short_bot.config import load_channel
from short_bot.web.extensions import db
from short_bot.web.models import Short, YoutubeUpload
from short_bot.web.runs import launch_pipeline

bp = Blueprint("shorts", __name__)


def _apply_filters(query, *, channel, q, since, youtube):
    """Apply optional filters used by both /shorts and /shorts/grid."""
    if channel:
        query = query.filter(Short.channel == channel)
    if q:
        query = query.filter(Short.title.ilike(f"%{q}%"))
    if since == "1h":
        query = query.filter(Short.created_at >= datetime.utcnow() - timedelta(hours=1))
    elif since == "today":
        today_start = datetime.combine(datetime.utcnow().date(), datetime.min.time())
        query = query.filter(Short.created_at >= today_start)
    elif since == "week":
        query = query.filter(Short.created_at >= datetime.utcnow() - timedelta(days=7))
    if youtube == "yes":
        query = (query.join(YoutubeUpload, YoutubeUpload.short_id == Short.id)
                       .filter(YoutubeUpload.status == "success")
                       .distinct())
    elif youtube == "no":
        success_subq = (db.session.query(YoutubeUpload.short_id)
                         .filter(YoutubeUpload.status == "success"))
        query = query.filter(~Short.id.in_(success_subq))
    return query


def _read_filter_args():
    """Read filter params from query string OR POST form (form-encoded
    bulk-delete posts the same fieldnames as hidden inputs)."""
    def _get(name: str) -> str:
        return (request.args.get(name) or request.form.get(name, "")).strip()
    return {
        "channel": _get("channel"),
        "q":       _get("q"),
        "since":   _get("since"),
        "youtube": _get("youtube"),
    }


@bp.route("/shorts")
def list_view():
    from short_bot.config import list_channels
    f = _read_filter_args()
    query = Short.query.filter(Short.deleted_at.is_(None))
    query = _apply_filters(query, **f)
    shorts = query.order_by(Short.created_at.desc()).limit(60).all()
    all_channels = list_channels(
        current_app.config["SHORTBOT_CONFIG_DIR"] / "channels", enabled_only=False
    )
    return render_template("shorts/list.html.j2",
                            shorts=shorts,
                            all_channels=all_channels,
                            **f)


@bp.route("/shorts/grid")
def grid_partial():
    """HTMX partial: filter result grid swap."""
    f = _read_filter_args()
    query = Short.query.filter(Short.deleted_at.is_(None))
    query = _apply_filters(query, **f)
    shorts = query.order_by(Short.created_at.desc()).limit(60).all()
    return render_template("_partials/shorts_grid.html.j2", shorts=shorts)


@bp.route("/shorts/<int:short_id>")
def detail(short_id):
    s = Short.query.filter_by(id=short_id).first()
    if s is None or s.deleted_at is not None:
        abort(404)
    from short_bot.youtube import auth as _yt_auth
    from short_bot.web.models import YoutubeUpload
    yt_root = current_app.config.get("SHORTBOT_YT_CREDS_DIR")
    # Bağlantı, kanalın KENDİ slug'ında olmayabilir (youtube.credentials_from ile
    # başka bir kanalınkini paylaşıyor olabilir) — yapılandırmadan çöz.
    _cslug = s.channel
    try:
        from short_bot.config import load_channel as _load_ch
        _cpath = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{s.channel}.yaml"
        if _cpath.exists():
            _cslug = _yt_auth.creds_slug(_load_ch(_cpath))
    except Exception:  # noqa: BLE001 — panel sayfası bağlantı yüzünden düşmesin
        pass
    yt_connected = bool(yt_root and _yt_auth.has_credentials(yt_root, _cslug))
    yt_upload = (YoutubeUpload.query.filter_by(short_id=s.id)
                 .order_by(YoutubeUpload.uploaded_at.desc()).first())
    from short_bot.db import get_video_stats_for_short, init_db
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    yt_video_stats = get_video_stats_for_short(eng, short_id=s.id, days=30)
    try:
        cfg = load_channel(
            current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{s.channel}.yaml"
        )
        default_privacy = cfg.youtube.privacy_status if cfg.youtube else "public"
    except Exception:
        default_privacy = "public"
    # Anlatım + (yabancı dilli kanalda) Türkçe geri çevirisi. Ham script_json aşağıda
    # zaten dökülüyor ama operatör onu okumaz; yayın kararı için ikisi YAN YANA lazım.
    try:
        script = json.loads(s.script_json or "{}")
    except Exception:  # noqa: BLE001 — bozuk JSON detay sayfasını çökertmesin
        script = {}
    return render_template("shorts/detail.html.j2", s=s,
                           yt_connected=yt_connected, yt_upload=yt_upload,
                           yt_video_stats=yt_video_stats,
                           # Seslendirmeli üretimde KONUŞULAN metin `narration_text`tir;
                           # `body_paragraph` ekrandaki haber yazısıdır. Eskiden ikincisi
                           # "Anlatım" diye gösteriliyordu ve altındaki Türkçe geri çeviri
                           # BAŞKA bir metnin çevirisi oluyordu — yan yana konunca iki
                           # metin tutmuyordu. Sessiz kanallarda narration_text boştur,
                           # eski davranışa düşer.
                           narration=(script.get("narration_text")
                                      or script.get("body_paragraph") or ""),
                           narration_tr=(script.get("body_paragraph_tr") or ""),
                           default_privacy=default_privacy)


@bp.route("/shorts/run-now", methods=["POST"])
def run_now():
    """HTMX action: launch pipeline for the given channel slug and return status partial."""
    slug = request.form.get("slug", "").strip()
    if not slug:
        abort(400)
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    channel_path = cfg_dir / "channels" / f"{slug}.yaml"
    if not channel_path.exists():
        abort(404)
    channel = load_channel(channel_path)
    launch_pipeline(
        channel=channel,
        settings=current_app.config["SHORTBOT_SETTINGS"],
        db_path=current_app.config["SHORTBOT_DB_PATH"],
        music_root=current_app.config["SHORTBOT_MUSIC_ROOT"],
        templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
        cache_dir=current_app.config["SHORTBOT_CACHE_DIR"],
        lock_dir=current_app.config["SHORTBOT_LOCK_DIR"],
        logs_dir=current_app.config["SHORTBOT_LOGS_DIR"],
        trigger="manual",
    )
    flash(f"'{slug}' için pipeline başlatıldı (arka planda).", "success")
    if request.headers.get("HX-Request"):
        resp = make_response("", 200)
        resp.headers["HX-Refresh"] = "true"
        return resp
    return render_template("_partials/run_status.html.j2", status="running", run_id=None)


@bp.route("/shorts/<int:short_id>/regenerate", methods=["POST"])
def regenerate(short_id):
    """Aynı başlıkla YENİDEN üret.

    Kanalı normal çalıştırmak başka bir konu getirir (başlığı LLM seçer). Burada
    başlık ZORLANIR — kusurlu çıkan bir videoyu düzeltilmiş boru hattıyla yeniden
    üretmenin tek yolu bu.

    Eskisini SİLMEZ: yeni bir short olarak üretilir, karşılaştırıp eskisini elle
    silebilirsin (üretim 8-11 dk sürüyor; üzerine yazıp geri dönüşü yok etmek
    kötü bir takas olurdu).
    """
    s = Short.query.filter_by(id=short_id).first()
    if s is None or s.deleted_at is not None:
        abort(404)
    channel_path = (current_app.config["SHORTBOT_CONFIG_DIR"] / "channels"
                    / f"{s.channel}.yaml")
    if not channel_path.exists():
        abort(404)
    launch_pipeline(
        channel=load_channel(channel_path),
        settings=current_app.config["SHORTBOT_SETTINGS"],
        db_path=current_app.config["SHORTBOT_DB_PATH"],
        music_root=current_app.config["SHORTBOT_MUSIC_ROOT"],
        templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
        cache_dir=current_app.config["SHORTBOT_CACHE_DIR"],
        lock_dir=current_app.config["SHORTBOT_LOCK_DIR"],
        logs_dir=current_app.config["SHORTBOT_LOGS_DIR"],
        trigger="manual",
        forced_topic=s.title,
    )
    flash(f"'{s.title[:60]}' aynı başlıkla yeniden üretiliyor (arka planda, ~10 dk). "
          f"Bittiğinde yeni bir short olarak listeye düşecek.", "success")
    if request.headers.get("HX-Request"):
        resp = make_response("", 200)
        resp.headers["HX-Redirect"] = url_for("shorts.list_view")
        return resp
    return redirect(url_for("shorts.list_view"))


@bp.route("/shorts/<int:short_id>/delete", methods=["POST"])
def delete(short_id):
    """Soft-delete a short by setting deleted_at timestamp."""
    s = Short.query.filter_by(id=short_id).first()
    if s is None or s.deleted_at is not None:
        abort(404)
    s.deleted_at = datetime.utcnow()
    db.session.commit()
    flash(f"'{s.title}' silindi.", "success")
    if request.headers.get("HX-Request"):
        resp = make_response("", 200)
        resp.headers["HX-Redirect"] = url_for("shorts.list_view")
        return resp
    return redirect(url_for("shorts.list_view"))


@bp.route("/shorts/delete-all", methods=["POST"])
def delete_all():
    """Bulk soft-delete shorts. Honors the same filter args as the list view
    (channel/q/since/youtube) so the user can scope deletion to whatever was
    visible. With no filters this clears EVERY non-deleted short for the
    user — frontend MUST send a confirm dialog first."""
    f = _read_filter_args()
    query = Short.query.filter(Short.deleted_at.is_(None))
    query = _apply_filters(query, **f)
    matched = query.all()
    now = datetime.utcnow()
    count = 0
    for s in matched:
        s.deleted_at = now
        count += 1
    db.session.commit()
    flash(f"{count} short silindi.", "success" if count else "info")
    if request.headers.get("HX-Request"):
        resp = make_response("", 200)
        resp.headers["HX-Redirect"] = url_for("shorts.list_view")
        return resp
    return redirect(url_for("shorts.list_view"))


@bp.route("/shorts/count", methods=["GET"])
def count():
    """Tiny JSON endpoint for the bulk-delete confirm dialog — returns the
    number of shorts that the current filters would delete."""
    from flask import jsonify
    f = _read_filter_args()
    query = Short.query.filter(Short.deleted_at.is_(None))
    query = _apply_filters(query, **f)
    return jsonify({"count": query.count()})
