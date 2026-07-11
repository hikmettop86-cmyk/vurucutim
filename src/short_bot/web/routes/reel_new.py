import re
import threading
import unicodedata
import uuid
from pathlib import Path

from flask import (Blueprint, current_app, flash, redirect,
                   render_template, request, url_for)
from pydantic import ValidationError

from short_bot.config import (ChannelConfig, GeneratorConfig, ReelConfig,
                              load_channel, resolve_ai_call, save_channel)
from short_bot.dna import build_css_override, generate_dna
from short_bot.locale import RSS_LOCALES, SUPPORTED_LANGUAGES
from short_bot.pexels import load_secrets as _load_secrets
from short_bot.web.niche_finder import find_niches
from short_bot.web.runs import launch_pipeline

bp = Blueprint("reel_new", __name__)

# Hazır niş presetleri: çip etiketi + LLM'e verilecek konu tohumu (topic seed).
# Konu, generator üretimini bu sınırda tutar; kullanıcı yine de serbest yazabilir.
# Nişler NexLev verisiyle seçildi (2026-07): footage'lı ilginç-bilgiler alanında
# kârlı/büyüyen İngilizce formatlar; Türkçe'de rekabet ~yok (arbitraj fırsatı).
NICHE_PRESETS = [
    {"key": "insan-vucudu", "label": "🧠 İnsan Vücudu",
     "topic": "insan vücudu ve sağlık hakkında merak uyandıran gerçekler: vücut "
              "nasıl iyileşir, uykusuzlukta ne olur, uzayda hayatta kalabilir "
              "misin, beyin ve organların şaşırtıcı yetenekleri"},
    {"key": "savas-tarihi", "label": "⚔️ Savaş Tarihi",
     "topic": "askeri tarihten merak konuları: bir silahın, taktiğin, komutanın "
              "ya da savaşın arkasındaki bilinmeyen detaylar, antik ve modern "
              "savaşlardan şaşırtıcı gerçekler"},
    {"key": "nasil-calisir", "label": "⚙️ Nasıl Çalışır",
     "topic": "günlük hayattaki 'bu neden böyle / nasıl çalışır' merakları: uçakta "
              "neden kulak ağrır, köprüler neden titreşir, makineler ve icatlar "
              "nasıl çalışır, hayat kurtaran mühendislik harikaları"},
    {"key": "cografya", "label": "🗺️ Coğrafya",
     "topic": "coğrafya ve harita merakları: uçaklar neden bazı bölgelerden uçmaz, "
              "dünyanın en tehlikeli yerleri, ülkeler ve şehirler hakkında az "
              "bilinen şaşırtıcı gerçekler"},
    {"key": "hayvanlar", "label": "🐳 Hayvanlar",
     "topic": "hayvanlar ve vahşi yaşam hakkında şaşırtıcı gerçekler: en zeki "
              "canlılar, tuhaf hayvan davranışları, okyanus devleri, dokunamayacağın "
              "canlılar ve doğanın olağanüstü örnekleri"},
    {"key": "uzay", "label": "🌌 Uzay",
     "topic": "uzay, gezegenler, kara delikler, evrenin sırları, astronomi ve "
              "galaksiler hakkında merak uyandıran ilginç bilgiler"},
    {"key": "bilim", "label": "🔬 Bilim & Deney",
     "topic": "görsel bilim ve deney gerçekleri: kimya tepkimeleri, fizik olayları, "
              "'nasıl' ve 'neden' açıklamaları, günlük hayattaki şaşırtıcı bilim"},
    {"key": "ilginc", "label": "💡 İlginç Bilgiler",
     "topic": "günlük hayattan ve bilimden merak uyandıran ilginç gerçekler ve az "
              "bilinen bilgiler"},
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

    # Reel config'i ücretli DNA çağrısından ÖNCE kur: bozuk bir Literal değer
    # (ör. elle hazırlanmış cut_pacing) kredi harcamadan hızlıca hata versin.
    highlight = (request.form.get("highlight_color", "") or "").strip() or "#38bdf8"
    variation_on = request.form.get("variation_on") == "on"
    try:
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
    except ValidationError as e:
        flash(f"Reel ayarları geçersiz: {e}", "error")
        return redirect(url_for("reel_new.form"))

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
            flash(f"'{name}' oluşturuldu — ilk video arka planda üretiliyor.", "success")
        except Exception as e:
            flash(f"'{name}' oluşturuldu ama üretim başlatılamadı: {e}", "error")
    else:
        flash(f"'{name}' reel kanalı oluşturuldu.", "success")
    return redirect(url_for("channel_edit.edit", slug=slug))


# ── NexLev-destekli niş bulucu (arka plan iş + HTMX poll) ────────────────────
# Tek kullanıcılı masaüstü panel → bellek içi iş kaydı yeterli.
_niche_jobs: dict = {}
_niche_jobs_lock = threading.Lock()


def _set_job(job_id: str, **fields) -> None:
    with _niche_jobs_lock:
        _niche_jobs.setdefault(job_id, {}).update(fields)


def _get_job(job_id: str):
    with _niche_jobs_lock:
        job = _niche_jobs.get(job_id)
        return dict(job) if job else None


def _run_niche_job(job_id: str, query: str, claude_path: str) -> None:
    try:
        niches = find_niches(query, claude_path=claude_path)
        _set_job(job_id, status="done", niches=niches)
    except Exception as e:  # noqa: BLE001 — hata mesajı kullanıcıya gösterilir
        _set_job(job_id, status="error", error=str(e))


@bp.route("/channels/new-reel/find-niches", methods=["POST"])
def find_niches_start():
    query = (request.form.get("niche_query") or request.form.get("topic") or "").strip()
    settings = current_app.config["SHORTBOT_SETTINGS"]
    claude_path = getattr(settings, "claude_cli_path", "claude") or "claude"
    job_id = uuid.uuid4().hex
    _set_job(job_id, status="running", niches=None, error=None)
    threading.Thread(target=_run_niche_job, args=(job_id, query, claude_path),
                     daemon=True).start()
    return render_template("channels/_niche_results.html.j2",
                           job_id=job_id, status="running", niches=None, error=None)


@bp.route("/channels/new-reel/niche-status/<job_id>")
def find_niches_status(job_id):
    job = _get_job(job_id)
    if not job:
        return render_template("channels/_niche_results.html.j2",
                               job_id=job_id, status="error",
                               niches=None, error="Niş arama işi bulunamadı.")
    return render_template("channels/_niche_results.html.j2",
                           job_id=job_id, status=job.get("status"),
                           niches=job.get("niches"), error=job.get("error"))
