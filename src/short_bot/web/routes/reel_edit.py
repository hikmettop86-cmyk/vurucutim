from dataclasses import replace
from pathlib import Path

import yaml as _yaml
from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.config import (GeneratorConfig, ReelConfig, YoutubeChannelConfig,
                              load_channel, save_channel)
from short_bot.locale import RSS_LOCALES, SUPPORTED_LANGUAGES

bp = Blueprint("reel_edit", __name__)


def _yaml_path(slug: str) -> Path:
    return current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"


def _is_reel(cfg) -> bool:
    return bool(cfg.reel and cfg.reel.enabled)


def _form_int(key, default):
    try:
        return int(request.form.get(key, default))
    except (TypeError, ValueError):
        return default


def _form_float(key, default):
    try:
        return float(request.form.get(key, default))
    except (TypeError, ValueError):
        return default


@bp.route("/channels/<slug>/edit-reel")
def edit_reel(slug):
    path = _yaml_path(slug)
    if not path.exists():
        abort(404)
    cfg = load_channel(path)
    if not _is_reel(cfg):
        return redirect(url_for("channel_edit.edit", slug=slug))

    secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
    pexels_key_set = False
    if secrets_path and Path(secrets_path).exists():
        try:
            s = _yaml.safe_load(Path(secrets_path).read_text(encoding="utf-8")) or {}
            pexels_key_set = bool(s.get("pexels_api_key"))
        except Exception:
            pexels_key_set = False

    yt_connected = False
    yt_info = None
    yt_has_secrets = False
    yt_secrets_abs = ""
    yt_root = current_app.config.get("SHORTBOT_YT_CREDS_DIR")
    if yt_root:
        try:
            from short_bot.youtube import auth as _yt_auth
            yt_connected = bool(_yt_auth.has_credentials(yt_root, slug))
            if yt_connected:
                yt_info = _yt_auth.load_channel_info(yt_root, slug)
            yt_has_secrets = (yt_root / slug / "client_secrets.json").is_file()
            yt_secrets_abs = str((yt_root / slug).resolve())
        except Exception:
            yt_info = None

    return render_template("channels/edit_reel.html.j2", c=cfg,
                           pexels_key_set=pexels_key_set, yt_connected=yt_connected,
                           yt_info=yt_info, yt_has_secrets=yt_has_secrets,
                           yt_secrets_abs=yt_secrets_abs)


@bp.route("/channels/<slug>/edit-reel", methods=["POST"])
def save_reel(slug):
    path = _yaml_path(slug)
    if not path.exists():
        abort(404)
    cfg = load_channel(path)
    if not _is_reel(cfg):
        return redirect(url_for("channel_edit.edit", slug=slug))

    r_id = (request.form.get("reel_voice_id") or "").strip()
    if not r_id:
        flash("Reel için bir ses seç (reel_voice_id boş).", "error")
        return redirect(url_for("reel_edit.edit_reel", slug=slug))

    old = cfg.reel
    try:
        new_reel = ReelConfig(
            enabled=True,
            voice_id=r_id,
            speed=_form_float("reel_speed", old.speed if old else 1.0),
            target_duration_s=(
                _form_int("reel_target_min", old.target_duration_s[0] if old else 25),
                _form_int("reel_target_max", old.target_duration_s[1] if old else 45)),
            cut_pacing=request.form.get("reel_cut_pacing", old.cut_pacing if old else "auto"),
            highlight_color=request.form.get("reel_highlight_color",
                                             old.highlight_color if old else "#ffd400"),
            arrows_enabled=request.form.get("reel_arrows_enabled") == "on",
            arrow_color=request.form.get("reel_arrow_color", old.arrow_color if old else "#ff2d2d"),
            arrow_frequency=request.form.get("reel_arrow_frequency",
                                             old.arrow_frequency if old else "beats"),
            transitions_flash=request.form.get("reel_flash") == "on",
            transitions_whoosh=request.form.get("reel_whoosh") == "on",
            transitions_zoom=request.form.get("reel_zoom") == "on",
            music_mood=request.form.get("reel_music_mood", old.music_mood if old else "upbeat"),
            font=request.form.get("reel_font", old.font if old else "Montserrat"),
            verify_footage=request.form.get("reel_verify_footage") == "on",
            # Retention kurgu katmanı
            fast_cuts=request.form.get("reel_fast_cuts") == "on",
            number_pop=request.form.get("reel_number_pop") == "on",
            visual_loop=request.form.get("reel_visual_loop") == "on",
            ai_director=request.form.get("reel_ai_director") == "on",
            layout=request.form.get("reel_layout", old.layout if old else "auto"),
            hook_angle_vary=request.form.get("reel_hook_angle_vary") == "on",
            accent_vary=request.form.get("reel_accent_vary") == "on",
            transition_vary=request.form.get("reel_transition_vary") == "on",
            series_enabled=request.form.get("reel_series_enabled") == "on",
            series_title=request.form.get("reel_series_title", old.series_title if old else ""),
            series_arc_length=_form_int("reel_series_arc_length",
                                        old.series_arc_length if old else 3),
            arc_mode=request.form.get("reel_arc_mode",
                                      old.arc_mode if old else "planned"),
            identity_lock=request.form.get("reel_identity_lock") == "on",
            sting_enabled=request.form.get("reel_sting_enabled") == "on",
            comment_question=request.form.get("reel_comment_question") == "on",
            music_volume=_form_float("reel_music_volume",
                                     old.music_volume if old else 0.30),
            sfx_volume=_form_float("reel_sfx_volume",
                                   old.sfx_volume if old else 0.22),
            music_duck=request.form.get("reel_music_duck") == "on",
            subject_framing=request.form.get("reel_subject_framing") == "on",
            color_grade=request.form.get("reel_color_grade") == "on",
            # Faz 2 kurgu katmanı. FORMDA OLMAYAN ALAN pydantic VARSAYILANINA döner —
            # yani kaydet'e basmak bunları sessizce sıfırlardı. Onay kutusu olarak
            # forma bağlıyoruz ki kullanıcı ayarı kaydetmekle ayarı KAYBETMESİN.
            tempo_zones=request.form.get("reel_tempo_zones") == "on",
            interrupts=request.form.get("reel_interrupts") == "on",
            # Persona ailesi bu formda YOK ama görüntü-önce kanalları persona
            # kanallarıdır; korunmazsa reel ayarı kaydı personayı SİLER (aynı desen:
            # channel_edit.py). old değerini taşı.
            persona=(old.persona if old else ""),
            mascot_name=(old.mascot_name if old else ""),
            mascot_animal=(old.mascot_animal if old else ""),
            mascot_trait=(old.mascot_trait if old else ""),
            footage_anchor=(old.footage_anchor if old else ""),
        )
    except Exception as e:  # pydantic ValidationError vb.
        flash(f"Reel ayarları geçersiz: {e}", "error")
        return redirect(url_for("reel_edit.edit_reel", slug=slug))

    language = (request.form.get("language", cfg.language) or cfg.language).strip()
    if language not in SUPPORTED_LANGUAGES:
        language = cfg.language
    rss_locale = RSS_LOCALES.get(language, cfg.rss_locale)

    new_generator = cfg.generator
    if cfg.content_source == "generator":
        topic = (request.form.get("generator_topic", "").strip()
                 or (cfg.generator.topic if cfg.generator else ""))
        if len(topic) < 10:
            flash("generator.topic en az 10 karakter olmalı.", "error")
            return redirect(url_for("reel_edit.edit_reel", slug=slug))
        new_generator = GeneratorConfig(
            topic=topic,
            forbidden_lookback=(cfg.generator.forbidden_lookback if cfg.generator else 50),
            max_retries=(cfg.generator.max_retries if cfg.generator else 3),
            fuzzy_threshold=(cfg.generator.fuzzy_threshold if cfg.generator else None),
        )

    new_youtube = cfg.youtube
    if any(k in request.form for k in ("yt_auto_upload", "yt_privacy_status",
                                       "yt_category_id", "yt_min_score_for_upload",
                                       "yt_cron_preset")):
        new_youtube = YoutubeChannelConfig(
            auto_upload=(request.form.get("yt_auto_upload") == "1"),
            ai_content=(cfg.youtube.ai_content if cfg.youtube else True),
            category_id=request.form.get("yt_category_id",
                                         cfg.youtube.category_id if cfg.youtube else "24"),
            privacy_status=request.form.get("yt_privacy_status",
                                            cfg.youtube.privacy_status if cfg.youtube else "private"),
            min_score_for_upload=_form_float("yt_min_score_for_upload",
                                             cfg.youtube.min_score_for_upload if cfg.youtube else 8.0),
            cron_preset=(request.form.get("yt_cron_preset") or None),
        )

    try:
        new_cfg = replace(
            cfg,
            name=request.form.get("name", cfg.name) or cfg.name,
            language=language,
            rss_locale=rss_locale,
            schedule_cron=request.form.get("schedule_cron", cfg.schedule_cron),
            handle=request.form.get("handle", cfg.handle),
            enabled=request.form.get("enabled") == "1",
            generator=new_generator,
            youtube=new_youtube,
            reel=new_reel,
        )
    except Exception as e:
        flash(f"Kanal ayarları geçersiz: {e}", "error")
        return redirect(url_for("reel_edit.edit_reel", slug=slug))

    save_channel(path, new_cfg)
    flash("Kanal güncellendi.", "success")
    return redirect(url_for("reel_edit.edit_reel", slug=slug))
