import json
from datetime import datetime, timedelta, timezone

from flask import (Blueprint, abort, current_app, flash, make_response,
                   redirect, render_template, request, url_for)

from short_bot.config import load_channel
from short_bot.web.extensions import db
from short_bot.web.models import Short, YoutubeUpload
from short_bot.web.runs import launch_pipeline

bp = Blueprint("shorts", __name__)


def _simdi() -> datetime:
    """Naif UTC — `shorts.created_at` ile AYNI eksen.

    (`datetime.utcnow()` Python 3.12'den beri kullanımdan kalktı; `db._utcnow`
    ile aynı gövde.)
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _yerel_gun_basi_utc() -> datetime:
    """Yerel günün başlangıcı, tablodaki naif-UTC eksenine çevrilmiş."""
    yerel = datetime.now().astimezone()
    bas = yerel.replace(hour=0, minute=0, second=0, microsecond=0)
    return bas.astimezone(timezone.utc).replace(tzinfo=None)


def _apply_filters(query, *, channel, q, since, youtube):
    """Apply optional filters used by both /shorts and /shorts/grid."""
    if channel:
        query = query.filter(Short.channel == channel)
    if q:
        query = query.filter(Short.title.ilike(f"%{q}%"))
    if since == "1h":
        query = query.filter(Short.created_at >= _simdi() - timedelta(hours=1))
    elif since == "today":
        # "Bugün" YEREL gündür. Eskiden UTC gece yarısından sayılıyordu ve
        # Türkiye'de (UTC+3) gece 00:00-03:00 arasında üretilen videolar
        # "bugün" süzgecine HİÇ girmiyordu — cron 00:00'da koştuğu için tam
        # o pencereye düşen üretim vardı. `compilation.day_bounds_utc` aynı
        # işi zaten doğru yapıyor.
        query = query.filter(Short.created_at >= _yerel_gun_basi_utc())
    elif since == "week":
        query = query.filter(Short.created_at >= _simdi() - timedelta(days=7))
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
    if s is None:
        abort(404)
    # SİLİNMİŞ VİDEO 404 DEĞİL. `deleted_at` operatörün gelen-kutusu
    # kararıdır, kaydın yok sayılması değil: beğendiğini YÜKLEYİP
    # listeden siliyor. Akış sayfası, YouTube hata olayları ve dışarıya
    # verilmiş bağlantılar bu id'ye gidiyor ve hepsi 404 alıyordu —
    # yayına çıkmış bir videonun sayfası açılmıyordu. Sayfa açılır,
    # üstünde durumu söyleyen bir şerit çıkar.
    silinmis = s.deleted_at is not None
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
                           silinmis=silinmis,
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
                           # 6 SANİYELİK KART FORMATI: ekranda görünen her şey
                           # manşet/foto şeridi/gövdedir ve yabancı dilli kanalda
                           # operatör bunları okuyamıyordu. Seslendirmeli formatın
                           # `body_paragraph_tr`si burada yok — kartın konuşulan
                           # metni yok ki. Kutu YALNIZ yabancı dilli kanalda çıkar.
                           kart_tr=(script.get("kart_tr") or None),
                           kart_dil=_dil_adi(s.channel, current_app),
                           # Elle yükleyecek operatör için: başlık/açıklama/etiket.
                           # Kayıtlıysa gösterilir; yoksa sayfada "üret" düğmesi
                           # çıkar — her açılışta LLM çağırmak hem para harcar
                           # hem her seferinde başka bir başlık gösterirdi.
                           yt_meta=(script.get("youtube_meta") or None),
                           default_privacy=default_privacy)


@bp.route("/shorts/<int:short_id>/metadata", methods=["POST"])
def metadata(short_id):
    """YouTube başlığı/açıklaması/etiketlerini üret (ve sakla).

    Videoyu indirip ELLE yükleyen operatör için. Üretilen metin, otomatik
    yüklemenin göndereceğinin AYNISIDIR (aynı üretici + aynı yedek birleşimi).
    """
    s = Short.query.filter_by(id=short_id).first()
    if s is None or s.deleted_at is not None:
        abort(404)
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{s.channel}.yaml"
    if not cfg_path.exists():
        return render_template("shorts/_yt_meta.html.j2", s=s, yt_meta=None,
                               meta_error="Kanal yapılandırması bulunamadı.")
    from short_bot.web.routes.youtube import snippet_for_short
    try:
        meta = snippet_for_short(s, load_channel(cfg_path),
                                 force=request.form.get("force") == "1")
    except Exception as e:  # noqa: BLE001 — kutu hata gösterir, sayfa düşmez
        current_app.logger.warning("metadata üretilemedi (short %s): %s", short_id, e)
        return render_template("shorts/_yt_meta.html.j2", s=s, yt_meta=None,
                               meta_error=str(e)[:200])
    return render_template("shorts/_yt_meta.html.j2", s=s, yt_meta=meta,
                           meta_error=None)


def _dil_adi(slug: str, app) -> str:
    """Kanalın dili ("İspanyolca" gibi) — kutu neden var olduğunu söylesin."""
    try:
        cfg = load_channel(app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml")
    except Exception:  # noqa: BLE001 — yapılandırma yoksa kutu yine çalışır
        return ""
    from short_bot.locale import LANGUAGE_NAMES
    return "" if cfg.language == "tr" else LANGUAGE_NAMES.get(cfg.language, cfg.language)


@bp.route("/shorts/<int:short_id>/turkce", methods=["POST"])
def kart_turkcesi_uret(short_id):
    """Kartın ekran metnini Türkçeye çevir (ve sakla).

    Üretim sırasında otomatik yazılıyor (`pipeline._kart_turkcesini_yaz`); bu
    rota ESKİ shortlar ve yeniden çeviri için. `youtube_meta` ile aynı kalıp:
    sonuç script_json'a yazılır, her açılışta yeni çağrı yapılmaz.
    """
    s = Short.query.filter_by(id=short_id).first()
    if s is None or s.deleted_at is not None:
        abort(404)
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{s.channel}.yaml"
    if not cfg_path.exists():
        return render_template("shorts/_kart_tr.html.j2", s=s, kart_tr=None,
                               kart_tr_error="Kanal yapılandırması bulunamadı.")
    cfg = load_channel(cfg_path)
    if cfg.language == "tr":
        return render_template("shorts/_kart_tr.html.j2", s=s, kart_tr=None,
                               kart_tr_error="Kanal zaten Türkçe.")

    script = json.loads(s.script_json or "{}")
    if request.form.get("force") != "1" and script.get("kart_tr"):
        return render_template("shorts/_kart_tr.html.j2", s=s,
                               kart_tr=script["kart_tr"], kart_tr_error=None)

    from pathlib import Path as _Path
    from short_bot.config import resolve_ai_call
    from short_bot.db import init_db, store_kart_turkcesi
    from short_bot.lang_review import kart_turkcesi
    from short_bot.pexels import load_secrets as _load_secrets
    try:
        secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
        secrets = _load_secrets(_Path(secrets_path)) if secrets_path else {}
        call = resolve_ai_call(current_app.config["SHORTBOT_SETTINGS"], secrets, "default")
        tr = kart_turkcesi(
            header_top=script.get("header_top", ""),
            header_bottom=script.get("header_bottom", ""),
            photo_overlay=script.get("photo_overlay", ""),
            body=script.get("body_paragraph", ""),
            language=cfg.language, backend=call.backend, model=call.model,
            api_key=call.api_key, claude_path=call.claude_path,
            # Panelde sebep GÖRÜNSÜN: havuz tükenmesi, model reddi ve ağ kopması
            # fail-open'da aynı boş cümleye çıkıyordu.
            strict=True)
    except Exception as e:  # noqa: BLE001 — kutu hata gösterir, sayfa düşmez
        current_app.logger.warning("kart Türkçesi üretilemedi (short %s): %s", short_id, e)
        return render_template("shorts/_kart_tr.html.j2", s=s, kart_tr=None,
                               kart_tr_error=str(e)[:200])
    if tr is None:
        return render_template("shorts/_kart_tr.html.j2", s=s, kart_tr=None,
                               kart_tr_error="Çeviri boş döndü.")
    veri = tr.model_dump()
    try:
        store_kart_turkcesi(init_db(current_app.config["SHORTBOT_DB_PATH"]), s.id, veri)
    except Exception:  # noqa: BLE001 — saklayamamak göstermeyi engellemesin
        pass
    return render_template("shorts/_kart_tr.html.j2", s=s, kart_tr=veri,
                           kart_tr_error=None)


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
    s.deleted_at = _simdi()
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
    now = _simdi()
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
