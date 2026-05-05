import re
import unicodedata

from flask import (Blueprint, abort, current_app, redirect, render_template,
                   request, session, url_for)

from short_bot.config import ChannelConfig, save_channel
from short_bot.dna import DnaSpec, build_css_override, generate_dna
from short_bot.locale import RSS_LOCALES, SUPPORTED_LANGUAGES

bp = Blueprint("channel_new", __name__)


def _slug_from_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return name or "channel"


@bp.route("/channels/new")
def form():
    return render_template("channels/new.html.j2")


@bp.route("/channels/new/generate", methods=["POST"])
def generate():
    name = request.form.get("name", "").strip()
    language = request.form.get("language", "tr").strip()
    if language not in SUPPORTED_LANGUAGES:
        abort(400)
    keywords = [k.strip() for k in request.form.get("keywords", "").split(",") if k.strip()]
    settings = current_app.config["SHORTBOT_SETTINGS"]
    try:
        dna = generate_dna(
            name=name, keywords=keywords, language=language,
            topic_hint=request.form.get("topic_hint", ""),
            target_audience=request.form.get("target_audience", ""),
            claude_path=settings.claude_cli_path,
            model=settings.claude_models.get("dna", "opus"),
        )
    except Exception as e:
        return render_template("_partials/dna_preview.html.j2",
                               error=str(e), dna=None, name=name, language=language)
    session["wizard_dna"] = dna.model_dump_json()
    session["wizard_name"] = name
    session["wizard_language"] = language
    return render_template("_partials/dna_preview.html.j2",
                           error=None, dna=dna, name=name, language=language)


@bp.route("/channels/new/save", methods=["POST"])
def save():
    if "wizard_dna" not in session:
        abort(400)
    dna = DnaSpec.model_validate_json(session["wizard_dna"])
    name = session.get("wizard_name", request.form.get("name", "Channel"))
    language = session.get("wizard_language", request.form.get("language", "tr"))
    keywords = [k.strip() for k in request.form.get("keywords", "").split(",") if k.strip()]
    slug = _slug_from_name(name)

    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    templates_dir = current_app.config["SHORTBOT_TEMPLATES_DIR"]
    yaml_path = cfg_dir / "channels" / f"{slug}.yaml"
    css_path = templates_dir / "css" / f"{slug}.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(build_css_override(dna), encoding="utf-8")

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
    )
    save_channel(yaml_path, cfg)
    session.pop("wizard_dna", None)
    session.pop("wizard_name", None)
    session.pop("wizard_language", None)
    return redirect(url_for("channel_edit.edit", slug=slug))
