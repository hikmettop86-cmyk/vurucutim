import json as _json
import json as _json_m
from datetime import datetime, timezone
from pathlib import Path
import requests
from flask import (Blueprint, abort, current_app, flash, has_request_context,
                   jsonify, redirect, render_template, request,
                   send_from_directory, url_for)

from short_bot.config import load_channel, resolve_ai_call
from short_bot.db import init_db, record_youtube_upload, get_rss_item_for_short
from short_bot.pexels import load_secrets as _load_secrets
from short_bot.web.models import Short
from short_bot.youtube import auth as yt_auth
from short_bot.youtube.metadata_writer import generate_youtube_metadata
from short_bot.youtube.proxy import (
    _redact_err, build_proxied_http, build_proxied_requests_session,
    load_channel_proxy_url,
)
from short_bot.youtube.uploader import build_snippet, build_status, upload_video

bp = Blueprint("youtube", __name__)


def _yt_root() -> Path:
    return Path(current_app.config["SHORTBOT_YT_CREDS_DIR"])


def _redirect_uri() -> str:
    # Gerçek isteğin host:port'unu kullan (sabit settings.web_port DEĞİL). Böylece
    # /connect ve /callback DAİMA aynı panele döner — iki panel açıkken ya da port
    # tarama (Electron 5005→5006) durumunda callback yanlış panele düşmez. loopback
    # istemcilerinde Google herhangi bir 127.0.0.1 portuna izin verir.
    if has_request_context() and request.host:
        return f"{request.scheme}://{request.host}/oauth/callback"
    s = current_app.config["SHORTBOT_SETTINGS"]
    host = getattr(s, "web_host", "127.0.0.1")
    port = getattr(s, "web_port", 5005)
    return f"http://{host}:{port}/oauth/callback"


def _oauth_pending_dir():
    """Server-side storage for in-flight OAuth code_verifier values.

    Used instead of Flask session so that the callback (which may come
    from a DIFFERENT browser than the one that started /connect) can still
    retrieve the verifier.
    """
    d = current_app.config["SHORTBOT_DB_PATH"].parent / "oauth_pending"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_oauth_verifier(slug: str, code_verifier: str) -> None:
    p = _oauth_pending_dir() / f"{slug}.json"
    p.write_text(_json_m.dumps({"code_verifier": code_verifier}), encoding="utf-8")


def _read_oauth_verifier(slug: str) -> str | None:
    """Verifier'ı OKUR ama SİLMEZ — token değişimi başarılınca _delete ile silinir.
    Böylece token değişimi başka bir sebeple patlarsa verifier'ı erken silip
    yanıltıcı 'code_verifier bulunamadı' hatası vermeyiz."""
    p = _oauth_pending_dir() / f"{slug}.json"
    if not p.exists():
        return None
    try:
        return _json_m.loads(p.read_text(encoding="utf-8")).get("code_verifier")
    except Exception:
        return None


def _delete_oauth_verifier(slug: str) -> None:
    try:
        (_oauth_pending_dir() / f"{slug}.json").unlink()
    except OSError:
        pass


@bp.route("/youtube-avatars/<slug>")
def avatar(slug):
    """Serve cached channel avatar. Returns 404 if not yet downloaded."""
    yt_root = Path(current_app.config["SHORTBOT_YT_CREDS_DIR"]).resolve()
    target = yt_root / slug / "avatar.jpg"
    if not target.is_file():
        abort(404)
    return send_from_directory(yt_root, f"{slug}/avatar.jpg",
                                 mimetype="image/jpeg")


@bp.route("/channels/<slug>/youtube/connect", methods=["POST", "GET"])
def connect(slug):
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
        state=slug, access_type="offline", prompt="select_account consent",
    )
    # Save PKCE code_verifier server-side so callback can retrieve it
    # even if it arrives from a DIFFERENT browser (multi-Gmail use case).
    _save_oauth_verifier(slug, flow.code_verifier)
    return render_template("youtube/connect.html.j2", slug=slug, auth_url=auth_url)


@bp.route("/oauth/callback")
def callback():
    state = request.args.get("state", "")
    code = request.args.get("code", "")
    if not state or not code:
        abort(400)
    cfg_path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{state}.yaml"
    if not cfg_path.exists():
        abort(404)
    try:
        flow = yt_auth.build_flow(_yt_root(), state, redirect_uri=_redirect_uri())
        # Retrieve PKCE code_verifier from server-side file (NOT Flask session).
        # OKU ama silme — token değişimi başarılınca aşağıda sileriz.
        flow.code_verifier = _read_oauth_verifier(state)
        if flow.code_verifier is None:
            raise RuntimeError(
                "OAuth code_verifier bulunamadı — /connect tekrar başlat"
            )
        flow.fetch_token(code=code)
        creds = flow.credentials
        yt_auth.save_credentials(_yt_root(), state, creds)
        _delete_oauth_verifier(state)   # başarı: verifier'ı temizle
        info = yt_auth.fetch_and_save_channel_info(_yt_root(), state, creds)
        title = info.get("snippet", {}).get("title", state)
        return f"""
        <html><body style="font-family: system-ui; padding: 40px; text-align: center;">
        <h1>&#10003; YouTube kanalı bağlandı: {title}</h1>
        <p style="color: #666;">Bu pencereyi kapatabilirsiniz. VurucuTim otomatik güncellendi.</p>
        <p style="margin-top: 24px;"><small>Eğer VurucuTim hala "bekleniyor" gösteriyorsa pencereyi yenileyin.</small></p>
        </body></html>
        """
    except Exception as e:
        return f"""
        <html><body style="font-family: system-ui; padding: 40px;">
        <h1>&#10007; YouTube bağlantı başarısız</h1>
        <pre>{e}</pre>
        </body></html>
        """, 400


@bp.route("/channels/<slug>/youtube/status", methods=["GET"])
def status(slug):
    """Poll endpoint for connect.html.j2 — returns connected:bool."""
    yt_root = _yt_root()
    if yt_root is None:
        return jsonify(connected=False)
    return jsonify(connected=yt_auth.has_credentials(yt_root, slug))


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

    # Resolve proxy (if configured) — same as auto_upload.run_auto_upload pattern
    secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
    proxy_url = (
        load_channel_proxy_url(s.channel, secrets_path)
        if secrets_path else None
    )
    proxy_session = build_proxied_requests_session(proxy_url) if proxy_url else None
    proxy_http = build_proxied_http(proxy_url) if proxy_url else None

    try:
        creds = yt_auth.load_credentials(
            _yt_root(), s.channel, proxy_session=proxy_session,
        )
    except (requests.exceptions.ProxyError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout) as e:
        eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
        err = f"proxy fail (token refresh, {s.channel}): {_redact_err(e)}"
        record_youtube_upload(
            eng, short_id=short_id, video_id=None,
            status="proxy_failed", error=err[:1000], video_url=None,
        )
        flash(f"Yükleme başarısız: proxy bağlantısı kurulamadı. {_redact_err(e)}", "error")
        return redirect(url_for("shorts.detail", short_id=short_id))

    if creds is None:
        flash("Önce YouTube bağla (kanal edit sayfasından).", "error")
        return redirect(url_for("shorts.detail", short_id=short_id))

    yt_cfg = cfg.youtube
    category_id = yt_cfg.category_id if yt_cfg else "24"
    privacy = yt_cfg.privacy_status if yt_cfg else "public"
    ai = yt_cfg.ai_content if yt_cfg else True
    # Manuel yükleme opsiyonları (form). Hiçbiri yoksa kanal varsayılanı korunur.
    form_privacy = (request.form.get("privacy") or "").strip().lower()
    if form_privacy in {"public", "unlisted", "private"}:
        privacy = form_privacy
    publish_at = (request.form.get("publish_at") or "").strip() or None
    if publish_at:
        try:
            # Tarayıcıdan UTC ISO gelir: "...Z" -> +00:00
            publish_dt = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
            if publish_dt.tzinfo is None:
                publish_dt = publish_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            flash("Zamanlama tarihi geçersiz.", "error")
            return redirect(url_for("shorts.detail", short_id=short_id))
        if publish_dt <= datetime.now(timezone.utc):
            flash("Zamanlama tarihi gelecekte olmalı.", "error")
            return redirect(url_for("shorts.detail", short_id=short_id))
        publish_at = publish_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    script = _json.loads(s.script_json or "{}")

    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])

    settings = current_app.config["SHORTBOT_SETTINGS"]
    rss_row = get_rss_item_for_short(eng, short_id=short_id)
    rss_source = rss_row.source if rss_row else None
    rss_link = rss_row.link if rss_row else None

    # Resolve the active AI backend (claude_cli default; openrouter when configured)
    # — same as auto_upload.run_auto_upload's metadata path.
    secrets = _load_secrets(Path(secrets_path)) if secrets_path else {}
    call = resolve_ai_call(settings, secrets, "default")

    generated = None
    try:
        meta = generate_youtube_metadata(
            channel=cfg, script=script,
            rss_source=rss_source, rss_link=rss_link,
            claude_path=call.claude_path,
            model=call.model,
            backend=call.backend,
            api_key=call.api_key,
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
    status = build_status(privacy_status=privacy, ai_content=ai,
                          publish_at=publish_at)

    try:
        video_id = upload_video(
            credentials=creds, file_path=Path(s.file_path),
            snippet=snippet, status=status,
            http=proxy_http,
        )
        url = f"https://youtu.be/{video_id}"
        record_youtube_upload(
            eng, short_id=short_id, video_id=video_id, status="success",
            error=None, video_url=url,
        )
        if publish_at:
            flash(f"YouTube'a yüklendi — {publish_at} (UTC) tarihinde yayınlanacak "
                  f"(şimdilik gizli): {url}", "success")
        else:
            flash(f"YouTube'a yüklendi: {url}", "success")
    except Exception as e:
        # Categorize: proxy transport fail vs API fail
        is_proxy_fail = proxy_url is not None and isinstance(
            e, (requests.exceptions.ProxyError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                ConnectionError, OSError),
        )
        status_str = "proxy_failed" if is_proxy_fail else "failed"
        record_youtube_upload(
            eng, short_id=short_id, video_id=None, status=status_str,
            error=_redact_err(e)[:1000], video_url=None,
        )
        if is_proxy_fail:
            flash(f"Yükleme başarısız: proxy bağlantısı kurulamadı. {_redact_err(e)}", "error")
        else:
            flash(f"Yükleme başarısız: {_redact_err(e)}", "error")
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


@bp.post("/channels/<slug>/test-proxy")
def test_proxy(slug):
    """Test a proxy URL by fetching public IP via api.ipify.org.

    Body: {"proxy_url": "..."}.
    Response: {"ok": True, "ip": "...", "country": "..."} or
              {"ok": False, "error": "..."} (redacted).
    """
    payload = request.get_json(silent=True) or {}
    proxy_url = (payload.get("proxy_url") or "").strip()
    if not proxy_url:
        return jsonify(ok=False, error="proxy URL bos"), 400
    try:
        sess = build_proxied_requests_session(proxy_url)
        r = sess.get("https://api.ipify.org?format=json", timeout=10)
        ip = r.json().get("ip")
        country = None
        try:
            r2 = sess.get(
                f"https://ipapi.co/{ip}/country_name/", timeout=5,
            )
            if r2.status_code == 200:
                country = r2.text.strip()
        except Exception:
            pass
        return jsonify(ok=True, ip=ip, country=country)
    except Exception as e:
        return jsonify(ok=False, error=_redact_err(e)[:200])
