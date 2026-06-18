import re
import unicodedata
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, session, url_for)

from short_bot.config import ChannelConfig, resolve_ai_call, save_channel
from short_bot.dna import DnaSpec, build_css_override, generate_dna
from short_bot.pexels import load_secrets as _load_secrets
from short_bot.dna_smoke import smoke_render_dna
from short_bot.locale import RSS_LOCALES, SUPPORTED_LANGUAGES

bp = Blueprint("channel_new", __name__)


def _slug_from_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return name or "channel"


@bp.route("/channels/new")
def form():
    import yaml as _yaml
    secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
    pexels_key_set = False
    if secrets_path and Path(secrets_path).exists():
        try:
            secrets = _yaml.safe_load(Path(secrets_path).read_text(encoding="utf-8")) or {}
            pexels_key_set = bool(secrets.get("pexels_api_key"))
        except Exception:
            pexels_key_set = False
    return render_template("channels/new.html.j2", pexels_key_set=pexels_key_set)


@bp.route("/channels/new/generate", methods=["POST"])
def generate():
    name = request.form.get("name", "").strip()
    language = request.form.get("language", "tr").strip()
    if language not in SUPPORTED_LANGUAGES:
        abort(400)
    keywords_raw = request.form.get("keywords", "")
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    content_source = request.form.get("content_source", "rss")
    generator_topic = request.form.get("generator_topic", "").strip()
    settings = current_app.config["SHORTBOT_SETTINGS"]
    secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
    secrets = _load_secrets(Path(secrets_path)) if secrets_path else {}
    dna_call = resolve_ai_call(settings, secrets, "dna")
    try:
        dna = generate_dna(
            name=name, keywords=keywords, language=language,
            topic_hint=request.form.get("topic_hint", ""),
            target_audience=request.form.get("target_audience", ""),
            claude_path=dna_call.claude_path,
            model=dna_call.model,
            backend=dna_call.backend,
            api_key=dna_call.api_key,
        )
    except Exception as e:
        return render_template("_partials/dna_preview.html.j2",
                               error=str(e), dna=None, name=name, language=language)
    session["wizard_dna"] = dna.model_dump_json()
    session["wizard_name"] = name
    session["wizard_language"] = language
    session["wizard_keywords"] = keywords_raw
    session["wizard_content_source"] = content_source
    session["wizard_generator_topic"] = generator_topic
    # Stash bg_video form values in session for the save step
    bg_v_enabled = request.form.get("bg_video_enabled") == "on"
    if bg_v_enabled:
        session["wizard_bg_video"] = {
            "enabled": True,
            "scale_raw": request.form.get("bg_video_scale", "0.88"),
            "blur_raw":  request.form.get("bg_video_blur_px", "30"),
            "dim_raw":   request.form.get("bg_video_dim", "0.4"),
        }
    else:
        session.pop("wizard_bg_video", None)
    return render_template("_partials/dna_preview.html.j2",
                           error=None, dna=dna, name=name, language=language)


@bp.route("/channels/new/save", methods=["POST"])
def save():
    if "wizard_dna" not in session:
        abort(400)
    dna = DnaSpec.model_validate_json(session["wizard_dna"])
    name = session.get("wizard_name", request.form.get("name", "Channel"))
    language = session.get("wizard_language", request.form.get("language", "tr"))
    content_source = session.get("wizard_content_source",
                                  request.form.get("content_source", "rss"))
    keywords_raw = session.get("wizard_keywords", request.form.get("keywords", ""))
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    generator_topic_in = session.get("wizard_generator_topic",
                                       request.form.get("generator_topic", "")).strip()
    slug = _slug_from_name(name)

    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    templates_dir = current_app.config["SHORTBOT_TEMPLATES_DIR"]
    yaml_path = cfg_dir / "channels" / f"{slug}.yaml"
    css_path = templates_dir / "css" / f"{slug}.css"

    # Smoke render check — refuse to persist DNA that breaks the layout
    settings = current_app.config["SHORTBOT_SETTINGS"]
    ok, reason = smoke_render_dna(
        dna,
        channel_template=dna.archetype,
        templates_dir=templates_dir,
        settings=settings,
        language=language,
    )
    if not ok:
        flash(f"DNA render testi başarısız: {reason}. Tekrar üretmeyi dene.", "error")
        return redirect(url_for("channel_new.form"))

    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(build_css_override(dna), encoding="utf-8")

    generator = None
    if content_source == "generator":
        from short_bot.config import GeneratorConfig
        if len(generator_topic_in) < 10:
            flash("generator.topic en az 10 karakter olmalı.", "error")
            return redirect(url_for("channel_new.form"))
        generator = GeneratorConfig(topic=generator_topic_in)

    # Build BgVideoConfig from session (if user enabled bg_video in step 1)
    bg_video = None
    bg_v_data = session.get("wizard_bg_video")
    if bg_v_data and bg_v_data.get("enabled"):
        from short_bot.config import BgVideoConfig
        try:
            scale = float(bg_v_data.get("scale_raw", "0.88"))
            if scale not in (0.88, 0.80):
                scale = 0.88
        except (TypeError, ValueError):
            scale = 0.88
        try:
            blur = int(bg_v_data.get("blur_raw", "30"))
        except (TypeError, ValueError):
            blur = 30
        try:
            dim = float(bg_v_data.get("dim_raw", "0.4"))
        except (TypeError, ValueError):
            dim = 0.4
        bg_video = BgVideoConfig(enabled=True, scale=scale, blur_px=blur, dim=dim)

    cfg = ChannelConfig(
        slug=slug, name=name, keywords=keywords,
        rss_locale=RSS_LOCALES[language],
        schedule_cron="0 8,14,20 * * *",
        duration_s=6, min_score=6.0, max_candidates_per_run=10,
        template=dna.archetype,
        colors={"primary": dna.palette.primary,
                "accent": dna.palette.accent,
                "bg_gradient": dna.palette.bg_gradient},
        handle=f"@{slug}", output_dir=f"output/{slug}",
        enabled=True,
        cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language=language, dna=dna, script_model=None,
        content_source=content_source,
        generator=generator,
        bg_video=bg_video,
    )
    save_channel(yaml_path, cfg)
    for k in ("wizard_dna", "wizard_name", "wizard_language",
              "wizard_keywords", "wizard_content_source", "wizard_generator_topic",
              "wizard_bg_video"):
        session.pop(k, None)
    return redirect(url_for("channel_edit.edit", slug=slug))
