from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.config import ChannelConfig, load_channel, save_channel
from short_bot.dna import build_css_override, generate_dna
from short_bot.dna_smoke import smoke_render_dna

bp = Blueprint("channel_edit", __name__)


def _yaml_path(slug: str):
    return current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"


@bp.route("/channels/<slug>/edit", methods=["GET"])
def edit(slug):
    path = _yaml_path(slug)
    if not path.exists():
        abort(404)
    cfg = load_channel(path)
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
    yt_connected = bool(yt_root and _yt_auth.has_credentials(yt_root, slug))
    yt_info = _yt_auth.load_channel_info(yt_root, slug) if yt_root and yt_connected else None
    yt_secrets_path = (yt_root / slug / "client_secrets.json") if yt_root else None
    yt_has_secrets = bool(yt_secrets_path and yt_secrets_path.is_file())
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
    return render_template("channels/edit.html.j2", c=cfg,
                           archetypes=ARCHETYPES,
                           cron_human=describe_cron(cfg.schedule_cron),
                           runs=runs,
                           music_info=music_info,
                           yt_connected=yt_connected, yt_info=yt_info,
                           yt_has_secrets=yt_has_secrets,
                           yt_secrets_abs=str((yt_root / slug).resolve()) if yt_root else "",
                           current_cron_preset=current_cron_preset,
                           pexels_key_set=pexels_key_set)


def _form_get_int(key: str, default: int) -> int:
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

    from short_bot.config import YoutubeChannelConfig
    new_youtube = cfg.youtube
    yt_present = any(k in request.form for k in
                      ("yt_auto_upload", "yt_ai_content", "yt_category_id",
                       "yt_privacy_status", "yt_min_score_for_upload",
                       "yt_cron_preset"))
    if yt_present:
        try:
            yt_min = float(request.form.get("yt_min_score_for_upload", "8.0"))
        except (TypeError, ValueError):
            yt_min = 8.0
        new_youtube = YoutubeChannelConfig(
            auto_upload=(request.form.get("yt_auto_upload") == "1"),
            ai_content=(request.form.get("yt_ai_content") == "1"),
            category_id=request.form.get("yt_category_id", "24"),
            privacy_status=request.form.get("yt_privacy_status", "public"),
            min_score_for_upload=yt_min,
            cron_preset=(request.form.get("yt_cron_preset") or None),
        )

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

    new_cfg = ChannelConfig(
        slug=cfg.slug,
        name=cfg.name,
        keywords=keywords,
        rss_locale=cfg.rss_locale,
        schedule_cron=request.form.get("schedule_cron", cfg.schedule_cron),
        duration_s=_form_get_int("duration_s", cfg.duration_s),
        min_score=_form_get_float("min_score", cfg.min_score),
        max_candidates_per_run=_form_get_int("max_candidates_per_run", cfg.max_candidates_per_run),
        template=new_template,
        colors={
            "primary": new_dna.palette.primary if new_dna else cfg.colors["primary"],
            "accent": new_dna.palette.accent if new_dna else cfg.colors["accent"],
            "bg_gradient": (list(new_dna.palette.bg_gradient) if new_dna
                            else cfg.colors["bg_gradient"]),
        },
        handle=request.form.get("handle", cfg.handle),
        output_dir=cfg.output_dir,
        enabled=request.form.get("enabled") == "1",
        cta_enabled=request.form.get("cta_enabled") == "1",
        cta_text=request.form.get("cta_text", cfg.cta_text),
        cta_icons=_form_get_list("cta_icons") or cfg.cta_icons,
        cta_duration_s=_form_get_int("cta_duration_s", cfg.cta_duration_s),
        cta_show_handle=request.form.get("cta_show_handle") == "1",
        language=cfg.language,
        dna=new_dna,
        script_model=cfg.script_model,
        content_source=cfg.content_source,
        generator=new_generator,
        youtube=new_youtube,
        bg_video=new_bg_video,
    )
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
