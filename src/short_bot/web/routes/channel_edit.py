import re
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)

from short_bot.config import ChannelConfig, load_channel, save_channel
from short_bot.dna import build_css_override, generate_dna
from short_bot.formats import channel_format as _channel_format
from short_bot.dna_smoke import smoke_render_dna
from short_bot.pexels import load_secrets
from short_bot.tts.ai33_client import list_voices, resolve_ai33_api_key
from short_bot.trends.verticals import VERTICAL_LABELS

bp = Blueprint("channel_edit", __name__)


def _yaml_path(slug: str):
    return current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"


@bp.route("/channels/<slug>/edit", methods=["GET"])
def edit(slug):
    path = _yaml_path(slug)
    if not path.exists():
        abort(404)
    cfg = load_channel(path)
    # TEK DÜZENLEME ROTASI. Eskiden dört yol vardı (edit, edit-yorum,
    # edit-curated, edit-reel) ve her biri kendi eksik YouTube bloğunu
    # çiziyordu. Artık yol tek; hangi sayfanın çizileceğine format karar verir.
    _fmt = _channel_format(cfg)
    if _fmt == "yorum":
        from short_bot.web.routes.yorum import edit as _yorum_edit
        return _yorum_edit(slug)
    if _fmt == "curated":
        from short_bot.web.routes.curated import edit_curated as _kurate_edit
        return _kurate_edit(slug)
    from short_bot.dna import ARCHETYPES
    from short_bot.web.cron_describe import describe_cron
    from short_bot.web.models import Run
    runs = (Run.query.filter_by(channel=slug)
            .order_by(Run.started_at.desc()).limit(20).all())
    music_root = current_app.config["SHORTBOT_MUSIC_ROOT"]
    ch_music_dir = music_root / slug
    music_info = {
        "abs_path": str(ch_music_dir.resolve()),
        "exists": ch_music_dir.is_dir(),
        "mp3_count": (sum(1 for _ in ch_music_dir.rglob("*.mp3"))
                      if ch_music_dir.is_dir() else 0),
    }
    from short_bot.youtube import auth as _yt_auth
    yt_root = current_app.config.get("SHORTBOT_YT_CREDS_DIR")
    _cslug = _yt_auth.creds_slug(cfg)
    yt_connected = bool(yt_root and _yt_auth.has_credentials(yt_root, _cslug))
    yt_info = _yt_auth.load_channel_info(yt_root, _cslug) if yt_root and yt_connected else None
    yt_secrets_path = (yt_root / slug / "client_secrets.json") if yt_root else None
    yt_has_secrets = bool(yt_secrets_path and yt_secrets_path.is_file())
    # Bağlantı paylaşımı: aynı YouTube kanalına üreten iki format tek bağlantıyı,
    # tek kotayı, tek istatistik geçmişini paylaşır. Bu liste kart sayfasında HİÇ
    # YOKTU — `gundem` ile `gundem-yorum` aynı kanala üretiyor ama seçenek yalnız
    # yorum ekranında vardı.
    from short_bot.config import list_channels
    from short_bot.web.core_fields import linkable_channels
    _digerleri = list_channels(current_app.config["SHORTBOT_CONFIG_DIR"] / "channels",
                               enabled_only=False)
    linkable = linkable_channels(
        cfg, others=_digerleri,
        has_credentials=(lambda s: bool(yt_root) and _yt_auth.has_credentials(yt_root, s)),
        channel_info=(lambda s: _yt_auth.load_channel_info(yt_root, s) if yt_root else None))
    yt_clash = []
    if yt_root:
        _beyan = {(cfg.youtube.credentials_from if cfg.youtube else None), _cslug, slug}
        yt_clash = [o for o in _yt_auth.same_youtube_channel(
            yt_root, _cslug, [o.slug for o in _digerleri]) if o not in _beyan]
    from short_bot.web.cron_preset import cron_to_preset
    current_cron_preset = (cfg.youtube.cron_preset
                            if (cfg.youtube and cfg.youtube.cron_preset)
                            else cron_to_preset(cfg.schedule_cron))
    # Check if Pexels API key is configured (for bg_video UI hint)
    import yaml as _yaml
    secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
    pexels_key_set = False
    if secrets_path and Path(secrets_path).exists():
        try:
            secrets = _yaml.safe_load(Path(secrets_path).read_text(encoding="utf-8")) or {}
            pexels_key_set = bool(secrets.get("pexels_api_key"))
        except Exception:
            pexels_key_set = False
    from short_bot.db import get_channel_stats_history, init_db, get_quota_used_today
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    yt_history = get_channel_stats_history(eng, channel=slug, days=30)
    yt_quota_today = get_quota_used_today(eng, channel=slug)
    # Mevcut proxy URL'i secrets.yaml'dan oku (UI'da göstermek için)
    from short_bot.youtube.proxy import load_channel_proxy_url
    proxy_url = load_channel_proxy_url(slug, secrets_path) if secrets_path else None
    from short_bot.db import list_feeds
    all_feeds = list_feeds(eng)
    return render_template("channels/edit.html.j2", c=cfg,
                           verticals=sorted(VERTICAL_LABELS.items()),
                           archetypes=ARCHETYPES,
                           cron_human=describe_cron(cfg.schedule_cron),
                           runs=runs,
                           music_info=music_info,
                           yt_connected=yt_connected, yt_info=yt_info,
                           creds_slug=_cslug, linkable=linkable, yt_clash=yt_clash,
                           yt_has_secrets=yt_has_secrets,
                           yt_secrets_abs=str((yt_root / slug).resolve()) if yt_root else "",
                           current_cron_preset=current_cron_preset,
                           pexels_key_set=pexels_key_set,
                           yt_history=yt_history,
                           yt_quota_today=yt_quota_today,
                           proxy_url=proxy_url or "",
                           all_feeds=all_feeds)


@bp.route("/api/ai33/voices", methods=["GET"])
def ai33_voices():
    """ai33 ses kütüphanesini JSON döndürür (arayüzdeki datalist'i doldurmak için).

    `?language=tr` verilirse YALNIZ o dilde konuşan sesler döner ve liste
    SAYFALANARAK çekilir. Eskiden tek sayfa çekiliyordu: 121 sesin 72'si
    İngilizce, yalnız 3'ü Türkçe / 11'i İspanyolcaydı (kütüphanede 23 ve 77 var).
    Yani kullanıcı kanalına ses seçmek istediğinde aradığı ses listede YOKTU ve
    bunu hiçbir uyarı söylemiyordu — ekranda "121 ses yüklendi" yazıyordu.

    Anahtar yoksa 200 + boş liste + hata mesajı döner ki arayüz kullanıcıya
    anlaşılır bir uyarı gösterebilsin. ``health_check`` ÇAĞIRMAZ — o kredi harcar.
    """
    secrets_path = Path(current_app.config.get("SHORTBOT_SECRETS_PATH")
                        or "data/secrets.yaml")
    secrets = load_secrets(secrets_path)
    key = resolve_ai33_api_key(secrets)
    if not key:
        return jsonify({"voices": [], "error": "AI33_API_KEY tanımlı değil"})

    from short_bot.locale import LANGUAGE_NAMES
    from short_bot.voice_picker import fetch_all_voices

    language = (request.args.get("language") or "").strip().lower()
    voices = fetch_all_voices(api_key=key)
    if language:
        eslesen = [v for v in voices
                   if str(v.get("language") or "").lower() == language]
        if not eslesen:
            ad = LANGUAGE_NAMES.get(language, language)
            return jsonify({"voices": [], "error":
                            f"ai33 kütüphanesinde {ad} konuşan ses bulunamadı "
                            f"({len(voices)} ses tarandı)"})
        voices = eslesen
    out = [
        {
            "voice_id": v.get("voice_id", ""),
            "name": v.get("name", ""),
            "language": v.get("language", ""),
        }
        for v in voices
    ]
    return jsonify({"voices": out})


@bp.route("/channels/<slug>/music/init", methods=["POST"])
def music_init(slug):
    """Create channel music directory (+ mood subdirs)."""
    music_root = current_app.config["SHORTBOT_MUSIC_ROOT"]
    base = music_root / slug
    base.mkdir(parents=True, exist_ok=True)
    for mood in ("breaking", "neutral", "upbeat"):
        (base / mood).mkdir(parents=True, exist_ok=True)
    flash(f"Müzik klasörleri hazır: {base.resolve()}", "ok")
    return redirect(url_for("channel_edit.edit", slug=slug) + "#music")


@bp.route("/channels/<slug>/music/open", methods=["POST"])
def music_open(slug):
    """Open the channel music dir in Windows Explorer (creates it first if needed)."""
    import subprocess, sys
    music_root = current_app.config["SHORTBOT_MUSIC_ROOT"]
    base = music_root / slug
    base.mkdir(parents=True, exist_ok=True)
    abs_path = str(base.resolve())
    try:
        if sys.platform == "win32":
            # explorer.exe is more reliable than os.startfile in spawned child processes.
            subprocess.Popen(["explorer", abs_path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", abs_path])
        else:
            subprocess.Popen(["xdg-open", abs_path])
        flash(f"Klasör açıldı: {abs_path}", "ok")
    except Exception as e:
        flash(f"Klasör açılamadı: {e} ({abs_path})", "err")
    return redirect(url_for("channel_edit.edit", slug=slug) + "#music")


def _dikey_from_form(default: str | None) -> str | None:
    """Formdan dikey. Alan formda YOKSA eski değer korunur — başka bir kartın
    POST'u dikeyi sessizce silmesin (panel DNA palet tuzağının aynısı)."""
    if "trends_vertical" not in request.form:
        return default
    return (request.form.get("trends_vertical") or "").strip().lower() or None


def _form_get_int(key: str, default):
    try:
        return int(request.form.get(key, default))
    except (TypeError, ValueError):
        return default


def _form_get_float(key: str, default: float) -> float:
    try:
        return float(request.form.get(key, default))
    except (TypeError, ValueError):
        return default


def _form_get_list(key: str) -> list[str]:
    return [x.strip() for x in request.form.get(key, "").split(",") if x.strip()]


@bp.route("/channels/<slug>/edit", methods=["POST"])
def save(slug):
    path = _yaml_path(slug)
    if not path.exists():
        abort(404)
    cfg = load_channel(path)
    # Tek rota, formata göre kaydedici. Kart/sesli kaydedicisi DNA'yı ve içerik
    # kaynağını yeniden kuruyor; yorum ve kürate formlarından gelen bir POST'u
    # ona vermek o kanalların ayarlarını bozardı (savunma derinliği).
    _fmt = _channel_format(cfg)
    if _fmt == "yorum":
        from short_bot.web.routes.yorum import edit_save as _yorum_save
        return _yorum_save(slug)
    if _fmt == "curated":
        from short_bot.web.routes.curated import edit_curated_save as _kurate_save
        return _kurate_save(slug)

    keywords = _form_get_list("keywords") or list(cfg.keywords)

    new_dna = cfg.dna
    if cfg.dna:
        # Apply DNA tweaks from form
        bg1 = request.form.get("dna_bg_grad_1", cfg.dna.palette.bg_gradient[0])
        bg2 = request.form.get("dna_bg_grad_2", cfg.dna.palette.bg_gradient[1])
        body1 = request.form.get("dna_body_bg_1", cfg.dna.palette.body_bg[0])
        body2 = request.form.get("dna_body_bg_2", cfg.dna.palette.body_bg[1])

        new_dna = cfg.dna.model_copy(update={
            "archetype": request.form.get("dna_archetype", cfg.dna.archetype),
            "palette": cfg.dna.palette.model_copy(update={
                "primary": request.form.get("dna_primary", cfg.dna.palette.primary),
                "accent": request.form.get("dna_accent", cfg.dna.palette.accent),
                "bg_gradient": [bg1, bg2],
                "body_bg": [body1, body2],
                "text_main": request.form.get("dna_text_main", cfg.dna.palette.text_main),
                "text_muted": request.form.get("dna_text_muted", cfg.dna.palette.text_muted),
                # Default to "" so toggle-off (disabled input not submitted)
                # actually CLEARS a previously set override.
                "header_top_color": request.form.get("dna_header_top_color", ""),
                "header_bottom_color": request.form.get("dna_header_bottom_color", ""),
            }),
            "fonts": cfg.dna.fonts.model_copy(update={
                "headline": request.form.get("dna_font_headline", cfg.dna.fonts.headline),
                "body": request.form.get("dna_font_body", cfg.dna.fonts.body),
                "size_headline_top": _form_get_int("dna_size_headline_top", None),
                "size_headline_bottom": _form_get_int("dna_size_headline_bot", None),
            }),
            "tone": cfg.dna.tone.model_copy(update={
                "voice": request.form.get("dna_voice", cfg.dna.tone.voice) or cfg.dna.tone.voice,
                "style": request.form.get("dna_style", cfg.dna.tone.style) or cfg.dna.tone.style,
                "forbidden": _form_get_list("dna_forbidden") or cfg.dna.tone.forbidden,
                "sentence_max_words": _form_get_int("dna_sentence_max_words",
                                                     cfg.dna.tone.sentence_max_words),
                "body_max_chars": _form_get_int("dna_body_max_chars", cfg.dna.tone.body_max_chars),
                "headline_style_hint": request.form.get("dna_headline_style_hint",
                                                         cfg.dna.tone.headline_style_hint),
            }),
            "banner_shape": request.form.get("dna_banner_shape", cfg.dna.banner_shape),
            "highlight_style": request.form.get("dna_highlight_style", cfg.dna.highlight_style),
            "chip_style": request.form.get("dna_chip_style", cfg.dna.chip_style),
            "category_icon": request.form.get("dna_category_icon", cfg.dna.category_icon),
            "search_query_template": request.form.get("dna_search_query_template",
                                                       cfg.dna.search_query_template),
            "ui_badge": request.form.get("dna_ui_badge", cfg.dna.ui_badge),
        })
        # Rebuild CSS
        templates_dir = current_app.config["SHORTBOT_TEMPLATES_DIR"]
        css_path = templates_dir / "css" / f"{slug}.css"
        css_path.parent.mkdir(parents=True, exist_ok=True)
        css_path.write_text(build_css_override(new_dna), encoding="utf-8")

    new_template = (new_dna.archetype if new_dna else cfg.template)

    new_generator = cfg.generator
    if cfg.content_source == "generator":
        from short_bot.config import GeneratorConfig
        topic = (request.form.get("generator_topic", "").strip()
                 or (cfg.generator.topic if cfg.generator else ""))
        if len(topic) < 10:
            flash("generator.topic en az 10 karakter olmalı.", "error")
            return redirect(url_for("channel_edit.edit", slug=slug))
        try:
            forbidden_lookback = int(request.form.get("generator_forbidden_lookback",
                                                       cfg.generator.forbidden_lookback))
        except (TypeError, ValueError):
            forbidden_lookback = cfg.generator.forbidden_lookback
        try:
            max_retries = int(request.form.get("generator_max_retries",
                                               cfg.generator.max_retries))
        except (TypeError, ValueError):
            max_retries = cfg.generator.max_retries
        ft_raw = request.form.get("generator_fuzzy_threshold", "").strip()
        fuzzy_threshold = float(ft_raw) if ft_raw else None
        new_generator = GeneratorConfig(
            topic=topic, forbidden_lookback=forbidden_lookback,
            max_retries=max_retries, fuzzy_threshold=fuzzy_threshold,
        )

    # ORTAK ÇEKİRDEK (ad, handle, cron, enabled, archived, YouTube bloğu) TEK
    # okuyucudan gelir — bkz. web/core_fields.py. Buradaki eski YouTube kurucusu
    # `YoutubeChannelConfig(...)` ile bloğu sıfırdan kuruyordu ve
    # `credentials_from` her kaydette düşüyordu (kart sayfasında o alan zaten
    # hiç yoktu, dolayısıyla sessiz bir veri kaybıydı).
    from short_bot.web.core_fields import core_updates
    ortak = core_updates(request.form, cfg)

    # Proxy URL — secrets.yaml'a yazilir (kanal yaml'a degil — credentials guvenligi)
    yt_proxy_url = (request.form.get("yt_proxy_url") or "").strip() or None
    from short_bot.secrets_io import update_channel_proxy
    secrets_path = Path(current_app.config.get("SHORTBOT_SECRETS_PATH") or "data/secrets.yaml")
    update_channel_proxy(secrets_path, cfg.slug, yt_proxy_url)

    bg_v_enabled = request.form.get("bg_video_enabled") == "on"
    if bg_v_enabled:
        from short_bot.config import BgVideoConfig
        try:
            scale = float(request.form.get("bg_video_scale", "0.88"))
            if scale not in (0.88, 0.80):
                scale = 0.88
        except (TypeError, ValueError):
            scale = 0.88
        try:
            blur = int(request.form.get("bg_video_blur_px", "30"))
        except (TypeError, ValueError):
            blur = 30
        try:
            dim = float(request.form.get("bg_video_dim", "0.4"))
        except (TypeError, ValueError):
            dim = 0.4
        new_bg_video = BgVideoConfig(enabled=True, scale=scale,
                                       blur_px=blur, dim=dim)
    else:
        new_bg_video = None

    # Trend boost — read form, build TrendBoostConfig (None when nothing set
    # so YAML stays clean for channels that never used the feature).
    from short_bot.config import TrendBoostConfig
    tb_enabled = request.form.get("tb_enabled") == "1"
    tb_form_present = any(k in request.form for k in (
        "tb_enabled", "tb_max_boost", "tb_min_term_length",
        "tb_fuzzy_threshold", "tb_region_override",
        "tb_src_google_daily", "tb_src_youtube", "tb_exclude_terms",
    ))
    if tb_form_present:
        tb_sources: list[str] | None = []
        if request.form.get("tb_src_google_daily") == "1":
            tb_sources.append("google_daily")
        if request.form.get("tb_src_youtube") == "1":
            tb_sources.append("youtube")
        if not tb_sources:
            tb_sources = None  # inherit settings default
        tb_region = (request.form.get("tb_region_override", "").strip().upper()
                     or None)
        tb_excl = _form_get_list("tb_exclude_terms")
        new_trend_boost = TrendBoostConfig(
            enabled=tb_enabled,
            max_boost=_form_get_float(
                "tb_max_boost",
                (cfg.trend_boost.max_boost if cfg.trend_boost else 2.0),
            ),
            sources=tb_sources,
            min_term_length=_form_get_int(
                "tb_min_term_length",
                (cfg.trend_boost.min_term_length if cfg.trend_boost else 4),
            ),
            fuzzy_threshold=_form_get_int(
                "tb_fuzzy_threshold",
                (cfg.trend_boost.fuzzy_threshold if cfg.trend_boost else 85),
            ),
            exclude_terms=tb_excl,
            region_override=tb_region,
        )
    else:
        new_trend_boost = cfg.trend_boost

    # Voice (seslendirme). Şablon text/number voice alanlarını (voice_id,
    # voice_speed, ...) HER ZAMAN gönderir — boş olsalar bile. Bu yüzden
    # "form alanı var mı" kontrolü yanıltıcıdır: sessiz bir kanala boş bir
    # voice bloğu enjekte eder. Bunun yerine kullanıcının seslendirmeyi
    # GERÇEKTEN kullandığı duruma bağlanırız: checkbox açık VEYA bir ses
    # seçilmiş VEYA kanalın zaten bir voice bloğu var. Aksi hâlde bloğa
    # dokunmayız (None ise None kalır — YAML kirlenmez).
    from short_bot.config import VoiceConfig
    v_enabled = request.form.get("voice_enabled") == "on"
    v_id = (request.form.get("voice_id") or "").strip()
    if v_enabled and not v_id:
        flash("Seslendirmeyi açmak için bir ses seç (voice_id boş).", "error")
        return redirect(url_for("channel_edit.edit", slug=slug))
    if v_enabled or v_id or cfg.voice is not None:
        from pydantic import ValidationError as _VErr
        old = cfg.voice
        try:
          new_voice = VoiceConfig(
            enabled=v_enabled,
            # Sağlayıcı formdan; gelmezse eski değer (başka bir kartın POST'u
            # kanalı sessizce ai33'e döndürmesin).
            provider=(request.form.get("voice_provider") or (old.provider if old else "ai33")),
            model=(request.form.get("voice_model") if "voice_model" in request.form
                   else (old.model if old else "")) or "",
            volume=_form_get_float("voice_volume", old.volume if old else 1.0),
            emotion=(request.form.get("voice_emotion") if "voice_emotion" in request.form
                     else (old.emotion if old else "")) or "",
            voice_id=v_id or (old.voice_id if old else ""),
            speed=_form_get_float("voice_speed", old.speed if old else 1.0),
            persona=(request.form.get("voice_persona") or "").strip()
                    or (old.persona if old else "enerjik, meraklı anlatıcı"),
            target_duration_s=(
                _form_get_int("voice_target_min",
                              old.target_duration_s[0] if old else 45),
                _form_get_int("voice_target_max",
                              old.target_duration_s[1] if old else 60),
            ),
            # Arka plan müziği formdan okunur; eskiden yalnız mevcut değer
            # korunuyordu, yani panelden HİÇ değiştirilemiyordu.
            music_volume=_form_get_float("voice_music_volume",
                                         old.music_volume if old else 0.12),
          )
        except _VErr as e:
            first = e.errors()[0] if e.errors() else {}
            flash(f"Seslendirme ayarı geçersiz: {first.get('msg', e)}", "error")
            return redirect(url_for("channel_edit.edit", slug=slug))
    else:
        new_voice = cfg.voice

    # Reel formatı — form hiç reel alanı göndermediyse mevcut blok korunur.
    from short_bot.config import ReelConfig
    reel_form_present = any(k in request.form for k in (
        "reel_enabled", "reel_voice_id", "reel_cut_pacing", "reel_music_mood",
        "reel_target_min", "reel_target_max", "reel_highlight_color",
        "reel_arrows_enabled", "reel_verify_footage",
    ))
    r_enabled = request.form.get("reel_enabled") == "on"
    r_id = (request.form.get("reel_voice_id") or "").strip()
    if reel_form_present and (r_enabled or r_id or cfg.reel is not None):
        if r_enabled and not r_id:
            flash("Reel'i açmak için bir ses seç (reel_voice_id boş).", "error")
            return redirect(url_for("channel_edit.edit", slug=slug))
        old = cfg.reel
        new_reel = ReelConfig(
            enabled=r_enabled,
            voice_id=r_id or (old.voice_id if old else ""),
            speed=_form_get_float("reel_speed", old.speed if old else 1.0),
            target_duration_s=(
                _form_get_int("reel_target_min", old.target_duration_s[0] if old else 25),
                _form_get_int("reel_target_max", old.target_duration_s[1] if old else 45)),
            cut_pacing=request.form.get("reel_cut_pacing", old.cut_pacing if old else "medium"),
            highlight_color=request.form.get("reel_highlight_color",
                                             old.highlight_color if old else "#ffd400"),
            arrows_enabled=request.form.get("reel_arrows_enabled") == "on"
                           if reel_form_present else (old.arrows_enabled if old else True),
            arrow_color=request.form.get("reel_arrow_color", old.arrow_color if old else "#ff2d2d"),
            arrow_frequency=request.form.get("reel_arrow_frequency",
                                             old.arrow_frequency if old else "beats"),
            transitions_flash=request.form.get("reel_flash") == "on" if reel_form_present
                              else (old.transitions_flash if old else True),
            transitions_whoosh=request.form.get("reel_whoosh") == "on" if reel_form_present
                               else (old.transitions_whoosh if old else True),
            transitions_zoom=request.form.get("reel_zoom") == "on" if reel_form_present
                             else (old.transitions_zoom if old else True),
            music_mood=request.form.get("reel_music_mood", old.music_mood if old else "upbeat"),
            music_volume=(old.music_volume if old else 0.10),
            verify_footage=request.form.get("reel_verify_footage") == "on" if reel_form_present
                           else (old.verify_footage if old else True),
            layout=request.form.get("reel_layout", old.layout if old else "auto"),
            hook_angle_vary=request.form.get("reel_hook_angle_vary") == "on",
            accent_vary=request.form.get("reel_accent_vary") == "on",
            transition_vary=request.form.get("reel_transition_vary") == "on",
            series_enabled=request.form.get("reel_series_enabled") == "on",
            series_title=request.form.get("reel_series_title", old.series_title if old else ""),
            comment_question=request.form.get("reel_comment_question") == "on",
            # PERSONA formda YOK ama korunmalı: eski değeri taşı, yoksa ses/renk
            # kaydında mizah personası SESSİZCE siliniyordu (gerçek hata: kullanıcı
            # panelden ses seçti, persona="" oldu, kanal düz belgesele döndü).
            persona=(old.persona if old else ""),
            # MASKOT alanları da formda YOK — persona ile aynı gerekçe, koru.
            mascot_name=(old.mascot_name if old else ""),
            mascot_animal=(old.mascot_animal if old else ""),
            mascot_trait=(old.mascot_trait if old else ""),
        )
    else:
        new_reel = cfg.reel

    new_content_source = request.form.get("content_source", cfg.content_source)
    if new_content_source not in ("rss", "generator", "feed", "trends"):
        new_content_source = cfg.content_source
    auto_feed_ids = [int(x) for x in request.form.getlist("auto_feed_ids")
                     if x.strip().isdigit()]
    if new_content_source == "feed" and not auto_feed_ids:
        flash("Feed modu için en az bir feed seçmelisin.", "error")
        return redirect(url_for("channel_edit.edit", slug=slug))
    # trends_region yalnız trends kaynağında anlamlı; formdan gelmezse eski
    # değer korunur (başka bir kartın POST'u bölgeyi sessizce silmesin).
    new_trends_region = cfg.trends_region
    if new_content_source == "trends":
        if "trends_region" in request.form:
            raw_region = request.form.get("trends_region", "").strip().upper()
            if raw_region and not re.fullmatch(r"[A-Z]{2}", raw_region):
                flash("Trend bölgesi iki harfli ISO kodu olmalı (TR, DE, ES…).", "error")
                return redirect(url_for("channel_edit.edit", slug=slug))
            new_trends_region = raw_region or None
    else:
        new_trends_region = None

    # `dataclasses.replace` — ESKİDEN `ChannelConfig(...)` idi ve kanalı SIFIRDAN
    # kuruyordu. Burada sayılmayan her alan varsayılana düşüyordu: ölçüldü,
    # tek bir "Kaydet" tıklaması saga sınırını (1.5 → 0.0), saga penceresini,
    # `categories`, `category_quota_per_day`, `reference_channels` ve `archived`
    # değerlerini siliyordu — formda o alanlar HİÇ olmadığı hâlde.
    # trends_min_volume aynı sebeple 5000'den 1000'e iniyordu ve tek tek
    # yamanmıştı; `replace` bu hata sınıfının tamamını kapatır.
    import dataclasses
    guncel = dict(
        keywords=keywords,
        duration_s=_form_get_int("duration_s", cfg.duration_s),
        min_score=_form_get_float("min_score", cfg.min_score),
        max_candidates_per_run=_form_get_int("max_candidates_per_run", cfg.max_candidates_per_run),
        max_age_hours=_form_get_int("max_age_hours", cfg.max_age_hours),
        bg_image_blur=_form_get_int("bg_image_blur", cfg.bg_image_blur),
        dynamic_dna=("dynamic_dna" in request.form),
        negative_keywords=_form_get_list("negative_keywords"),
        template=new_template,
        colors={
            "primary": new_dna.palette.primary if new_dna else cfg.colors["primary"],
            "accent": new_dna.palette.accent if new_dna else cfg.colors["accent"],
            "bg_gradient": (list(new_dna.palette.bg_gradient) if new_dna
                            else cfg.colors["bg_gradient"]),
        },
        dna=new_dna,
        content_source=new_content_source,
        trends_region=new_trends_region,
        trends_min_volume=_form_get_int("trends_min_volume", cfg.trends_min_volume),
        trends_intent=(request.form.get("trends_intent", cfg.trends_intent)
                       if "trends_intent" in request.form else cfg.trends_intent),
        brand_safety=(request.form.get("brand_safety") or cfg.brand_safety),
        trends_vertical=(_dikey_from_form(cfg.trends_vertical)
                         if new_content_source == "trends" else None),
        auto_feed_ids=auto_feed_ids,
        generator=new_generator,
        bg_video=new_bg_video,
        trend_boost=new_trend_boost,
        voice=new_voice,
        reel=new_reel,
    )
    guncel.update(ortak)          # ad, handle, cron, enabled, archived, youtube
    new_cfg = dataclasses.replace(cfg, **guncel)
    save_channel(path, new_cfg)
    flash("Kanal güncellendi.", "success")
    return redirect(url_for("channel_edit.edit", slug=slug))


@bp.route("/channels/<slug>/regenerate-dna", methods=["POST"])
def regenerate_dna(slug):
    """Re-run Opus DNA generation for an existing channel and rebuild CSS."""
    path = _yaml_path(slug)
    if not path.exists():
        abort(404)
    cfg = load_channel(path)
    settings = current_app.config["SHORTBOT_SETTINGS"]
    try:
        new_dna = generate_dna(
            name=cfg.name,
            keywords=cfg.keywords,
            language=cfg.language,
            claude_path=settings.claude_cli_path,
            model=settings.claude_models.get("dna", "opus"),
        )
    except Exception as e:
        flash(f"DNA üretimi başarısız: {e}", "error")
        return redirect(url_for("channel_edit.edit", slug=slug))

    settings = current_app.config["SHORTBOT_SETTINGS"]
    templates_dir = current_app.config["SHORTBOT_TEMPLATES_DIR"]
    ok, reason = smoke_render_dna(
        new_dna,
        channel_template=new_dna.archetype,
        templates_dir=templates_dir,
        settings=settings,
        language=cfg.language,
    )
    if not ok:
        flash(f"DNA render testi başarısız: {reason}. Mevcut DNA korundu.", "error")
        return redirect(url_for("channel_edit.edit", slug=slug))

    # Rebuild css with new DNA
    css_path = templates_dir / "css" / f"{slug}.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(build_css_override(new_dna), encoding="utf-8")

    new_cfg = type(cfg)(**{
        **cfg.__dict__,
        "template": new_dna.archetype,
        "colors": {
            "primary": new_dna.palette.primary,
            "accent": new_dna.palette.accent,
            "bg_gradient": new_dna.palette.bg_gradient,
        },
        "dna": new_dna,
    })
    save_channel(path, new_cfg)
    flash(f"DNA yeniden üretildi (archetype: {new_dna.archetype}).", "success")
    return redirect(url_for("channel_edit.edit", slug=slug))
