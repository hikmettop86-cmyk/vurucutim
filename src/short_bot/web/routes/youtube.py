import json as _json
from pathlib import Path
from flask import (Blueprint, abort, current_app, flash, redirect,
                   request, send_from_directory, url_for)

from short_bot.config import load_channel
from short_bot.db import init_db, record_youtube_upload, get_rss_item_for_short
from short_bot.web.models import Short
from short_bot.youtube import auth as yt_auth
from short_bot.youtube.metadata_writer import generate_youtube_metadata
from short_bot.youtube.uploader import build_snippet, build_status, upload_video

bp = Blueprint("youtube", __name__)


def _yt_root() -> Path:
    return Path(current_app.config["SHORTBOT_YT_CREDS_DIR"])


def _redirect_uri() -> str:
    s = current_app.config["SHORTBOT_SETTINGS"]
    host = getattr(s, "web_host", "127.0.0.1")
    port = getattr(s, "web_port", 5005)
    return f"http://{host}:{port}/oauth/callback"


@bp.route("/youtube-avatars/<slug>")
def avatar(slug):
    """Serve cached channel avatar. Returns 404 if not yet downloaded."""
    yt_root = Path(current_app.config["SHORTBOT_YT_CREDS_DIR"]).resolve()
    target = yt_root / slug / "avatar.jpg"
    if not target.is_file():
        abort(404)
    return send_from_directory(yt_root, f"{slug}/avatar.jpg",
                                 mimetype="image/jpeg")


@bp.route("/channels/<slug>/youtube/connect", methods=["POST"])
def connect(slug):
    from flask import session
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not cfg_path.exists():
        abort(404)
    try:
        flow = yt_auth.build_flow(_yt_root(), slug, redirect_uri=_redirect_uri())
    except FileNotFoundError:
        flash(f"client_secrets.json eksik. Yere bırak: data/youtube_credentials/{slug}/client_secrets.json",
              "error")
        return redirect(url_for("channel_edit.edit", slug=slug))
    auth_url, _state = flow.authorization_url(
        state=slug, access_type="offline", prompt="consent",
    )
    # Persist PKCE code_verifier across the OAuth roundtrip — google-auth-oauthlib auto-generates
    # one at authorization_url() time and Google will require it back in fetch_token().
    session[f"yt_oauth_verifier:{slug}"] = flow.code_verifier
    session.permanent = True
    return redirect(auth_url)


@bp.route("/oauth/callback")
def callback():
    from flask import session
    state = request.args.get("state", "")
    code = request.args.get("code", "")
    if not state or not code:
        abort(400)
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{state}.yaml"
    if not cfg_path.exists():
        abort(404)
    try:
        flow = yt_auth.build_flow(_yt_root(), state, redirect_uri=_redirect_uri())
        # Restore the PKCE code_verifier saved during /connect.
        flow.code_verifier = session.pop(f"yt_oauth_verifier:{state}", None)
        flow.fetch_token(code=code)
        creds = flow.credentials
        yt_auth.save_credentials(_yt_root(), state, creds)
        info = yt_auth.fetch_and_save_channel_info(_yt_root(), state, creds)
        title = info.get("snippet", {}).get("title", state)
        flash(f"YouTube kanalı bağlandı: {title}", "success")
    except Exception as e:
        flash(f"YouTube bağlantı başarısız: {e}", "error")
    return redirect(url_for("channel_edit.edit", slug=state))


@bp.route("/channels/<slug>/youtube/disconnect", methods=["POST"])
def disconnect(slug):
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not cfg_path.exists():
        abort(404)
    yt_auth.delete_credentials(_yt_root(), slug)
    flash("YouTube bağlantısı kaldırıldı.", "success")
    return redirect(url_for("channel_edit.edit", slug=slug))


@bp.route("/shorts/<int:short_id>/upload-youtube", methods=["POST"])
def upload(short_id):
    s = Short.query.filter_by(id=short_id).first()
    if s is None or s.deleted_at is not None:
        abort(404)
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    cfg = load_channel(cfg_dir / "channels" / f"{s.channel}.yaml")

    creds = yt_auth.load_credentials(_yt_root(), s.channel)
    if creds is None:
        flash("Önce YouTube bağla (kanal edit sayfasından).", "error")
        return redirect(url_for("shorts.detail", short_id=short_id))

    yt_cfg = cfg.youtube
    category_id = yt_cfg.category_id if yt_cfg else "24"
    privacy = yt_cfg.privacy_status if yt_cfg else "public"
    ai = yt_cfg.ai_content if yt_cfg else True

    script = _json.loads(s.script_json or "{}")

    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])

    settings = current_app.config["SHORTBOT_SETTINGS"]
    rss_row = get_rss_item_for_short(eng, short_id=short_id)
    rss_source = rss_row.source if rss_row else None
    rss_link = rss_row.link if rss_row else None

    generated = None
    try:
        meta = generate_youtube_metadata(
            channel=cfg, script=script,
            rss_source=rss_source, rss_link=rss_link,
            claude_path=settings.claude_cli_path,
            model=settings.claude_models.get("default", "sonnet"),
        )
        generated = {"title": meta.title, "description": meta.description, "tags": meta.tags}
        current_app.logger.info("youtube: Sonnet metadata generated for short %s", short_id)
    except Exception as e:
        current_app.logger.warning(
            "youtube: Sonnet metadata failed for short %s, falling back: %s", short_id, e,
        )

    snippet = build_snippet(
        header_top=script.get("header_top", ""),
        header_bottom=script.get("header_bottom", ""),
        body_paragraph=script.get("body_paragraph", ""),
        handle=cfg.handle, keywords=cfg.keywords or [],
        category_id=category_id, language=cfg.language,
        generated=generated,
    )
    status = build_status(privacy_status=privacy, ai_content=ai)

    try:
        video_id = upload_video(
            credentials=creds, file_path=Path(s.file_path),
            snippet=snippet, status=status,
        )
        url = f"https://youtu.be/{video_id}"
        record_youtube_upload(
            eng, short_id=short_id, video_id=video_id, status="success",
            error=None, video_url=url,
        )
        flash(f"YouTube'a yüklendi: {url}", "success")
    except Exception as e:
        record_youtube_upload(
            eng, short_id=short_id, video_id=None, status="failed",
            error=str(e)[:1000], video_url=None,
        )
        flash(f"Yükleme başarısız: {e}", "error")
    return redirect(url_for("shorts.detail", short_id=short_id))


@bp.route("/channels/<slug>/youtube/reset", methods=["POST"])
def reset(slug):
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not cfg_path.exists():
        abort(404)
    yt_auth.purge_credentials(_yt_root(), slug)
    flash("YouTube'a ait tüm dosyalar silindi (token, kanal bilgisi, client_secrets).",
          "success")
    return redirect(url_for("channel_edit.edit", slug=slug))


@bp.route("/channels/<slug>/youtube/upload-secrets", methods=["POST"])
def upload_secrets(slug):
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not cfg_path.exists():
        abort(404)
    f = request.files.get("client_secrets")
    if f is None or not f.filename:
        flash("Dosya seçilmedi.", "error")
        return redirect(url_for("channel_edit.edit", slug=slug))
    raw = f.read()
    try:
        data = _json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        flash("Geçersiz JSON. Google Console'dan indirdiğin orijinal dosyayı yükle.",
              "error")
        return redirect(url_for("channel_edit.edit", slug=slug))
    if not isinstance(data, dict) or not ("web" in data or "installed" in data):
        flash("Bu OAuth client JSON'u gibi görünmüyor (web/installed anahtarı yok).",
              "error")
        return redirect(url_for("channel_edit.edit", slug=slug))
    target_dir = _yt_root() / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "client_secrets.json").write_bytes(raw)
    flash("client_secrets.json yüklendi. Şimdi 'YouTube Bağla' butonuna tıkla.",
          "success")
    return redirect(url_for("channel_edit.edit", slug=slug))
