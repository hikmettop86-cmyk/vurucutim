import re
import unicodedata
from pathlib import Path

from flask import (Blueprint, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.config import (ChannelConfig, GeneratorConfig, ReelConfig,
                              load_channel, resolve_ai_call, save_channel)
from short_bot.dna import build_css_override, generate_dna
from short_bot.locale import RSS_LOCALES, SUPPORTED_LANGUAGES
from short_bot.pexels import load_secrets as _load_secrets
from short_bot.web.runs import launch_pipeline

bp = Blueprint("reel_new", __name__)

# Hazır niş presetleri: çip etiketi + LLM'e verilecek konu tohumu (topic seed).
# Konu, generator üretimini bu sınırda tutar; kullanıcı yine de serbest yazabilir.
NICHE_PRESETS = [
    {"key": "balinalar", "label": "🐳 Balinalar",
     "topic": "balinalar ve deniz memelileri hakkında ilginç bilgiler: mavi balina, "
              "katil balina (orka), balina göçü, ekolokasyon, balina şarkıları, "
              "derin deniz dalışı ve okyanus yaşamı"},
    {"key": "uzay", "label": "🌌 Uzay",
     "topic": "uzay, gezegenler, kara delikler, evrenin sırları, astronomi ve "
              "galaksiler hakkında merak uyandıran ilginç bilgiler"},
    {"key": "tarih", "label": "🏛️ Tarih",
     "topic": "tarihten ilginç olaylar, antik uygarlıklar, kayıp şehirler, ünlü "
              "figürler ve az bilinen tarihi gerçekler"},
    {"key": "bilim", "label": "🔬 Bilim",
     "topic": "günlük hayattaki bilim, fizik, kimya ve biyolojiden şaşırtıcı "
              "gerçekler ve 'nasıl çalışır' açıklamaları"},
    {"key": "doga", "label": "🌿 Doğa",
     "topic": "doğa, vahşi yaşam, hayvanlar, bitkiler ve gezegenimizin olağanüstü "
              "olayları hakkında ilginç bilgiler"},
    {"key": "muhendislik", "label": "⚙️ Mühendislik",
     "topic": "mühendislik harikaları, dev yapılar, makineler, teknoloji ve bunların "
              "nasıl inşa edildiğine dair ilginç bilgiler"},
    {"key": "ilginc", "label": "💡 İlginç Bilgiler",
     "topic": "bilim, doğa, uzay ve mühendislikten merak uyandıran ilginç gerçekler "
              "ve az bilinen bilgiler"},
]


_TR_MAP = str.maketrans({
    "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ç": "c", "Ç": "c", "ö": "o", "Ö": "o", "ü": "u", "Ü": "u",
})


def _slug_from_name(name: str) -> str:
    name = name.translate(_TR_MAP)
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return name or "channel"


def _unique_slug(base: str, channels_dir: Path) -> str:
    slug = base
    n = 2
    while (channels_dir / f"{slug}.yaml").exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _pexels_key_set() -> bool:
    secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
    if not secrets_path or not Path(secrets_path).exists():
        return False
    try:
        secrets = _load_secrets(Path(secrets_path))
        return bool(secrets.get("pexels_api_key"))
    except Exception:
        return False


@bp.route("/channels/new-reel")
def form():
    return render_template("channels/new_reel.html.j2",
                           pexels_key_set=_pexels_key_set(),
                           niche_presets=NICHE_PRESETS)


@bp.route("/channels/new-reel", methods=["POST"])
def create():
    name = request.form.get("name", "").strip()
    topic = request.form.get("topic", "").strip()
    voice_id = request.form.get("voice_id", "").strip()
    language = request.form.get("language", "tr").strip()
    if language not in SUPPORTED_LANGUAGES:
        language = "tr"

    if not name:
        flash("Kanal adı gerekli.", "error")
        return redirect(url_for("reel_new.form"))
    if len(topic) < 10:
        flash("Konu en az 10 karakter olmalı.", "error")
        return redirect(url_for("reel_new.form"))
    if not voice_id:
        flash("Reel kanalı için bir ses seç (voice_id boş).", "error")
        return redirect(url_for("reel_new.form"))

    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    templates_dir = current_app.config["SHORTBOT_TEMPLATES_DIR"]
    channels_dir = cfg_dir / "channels"
    slug = _unique_slug(_slug_from_name(name), channels_dir)

    settings = current_app.config["SHORTBOT_SETTINGS"]
    secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
    secrets = _load_secrets(Path(secrets_path)) if secrets_path else {}
    dna_call = resolve_ai_call(settings, secrets, "dna")
    try:
        dna = generate_dna(
            name=name, keywords=[], language=language,
            topic_hint=topic, target_audience="",
            claude_path=dna_call.claude_path, model=dna_call.model,
            backend=dna_call.backend, api_key=dna_call.api_key,
        )
    except Exception as e:
        flash(f"DNA üretimi başarısız: {e}", "error")
        return redirect(url_for("reel_new.form"))

    highlight = (request.form.get("highlight_color", "") or "").strip() or "#38bdf8"
    variation_on = request.form.get("variation_on") == "on"
    reel = ReelConfig(
        enabled=True,
        voice_id=voice_id,
        highlight_color=highlight,
        cut_pacing=request.form.get("cut_pacing", "auto"),
        music_mood=request.form.get("music_mood", "upbeat"),
        hook_angle_vary=variation_on,
        accent_vary=variation_on,
        transition_vary=variation_on,
        cta_enabled=request.form.get("cta_enabled") == "on",
        comment_question=request.form.get("comment_question") == "on",
        series_enabled=request.form.get("series_enabled") == "on",
    )

    # DNA CSS override (arketip önizlemesi için; reel çıktısı kullanmaz ama parite)
    css_path = templates_dir / "css" / f"{slug}.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(build_css_override(dna), encoding="utf-8")

    cfg = ChannelConfig(
        slug=slug, name=name, keywords=[],
        rss_locale=RSS_LOCALES[language],
        schedule_cron="0 10 * * *",
        duration_s=40, min_score=7.0, max_candidates_per_run=3,
        template=dna.archetype,
        colors={"primary": dna.palette.primary,
                "accent": highlight,
                "bg_gradient": dna.palette.bg_gradient},
        handle=f"@{slug}", output_dir=f"output/{slug}",
        enabled=True,
        cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language=language, dna=dna, script_model=None,
        content_source="generator",
        generator=GeneratorConfig(topic=topic),
        reel=reel,
    )
    yaml_path = channels_dir / f"{slug}.yaml"
    save_channel(yaml_path, cfg)

    if request.form.get("produce_now") == "1":
        try:
            channel = load_channel(yaml_path)
            launch_pipeline(
                channel=channel,
                settings=settings,
                db_path=current_app.config["SHORTBOT_DB_PATH"],
                music_root=current_app.config["SHORTBOT_MUSIC_ROOT"],
                templates_dir=templates_dir,
                cache_dir=current_app.config["SHORTBOT_CACHE_DIR"],
                lock_dir=current_app.config["SHORTBOT_LOCK_DIR"],
                logs_dir=current_app.config["SHORTBOT_LOGS_DIR"],
                trigger="manual",
            )
            flash(f"'{name}' oluşturuldu — ilk video arka planda üretiliyor.", "ok")
        except Exception as e:
            flash(f"'{name}' oluşturuldu ama üretim başlatılamadı: {e}", "error")
    else:
        flash(f"'{name}' reel kanalı oluşturuldu.", "ok")
    return redirect(url_for("channel_edit.edit", slug=slug))
