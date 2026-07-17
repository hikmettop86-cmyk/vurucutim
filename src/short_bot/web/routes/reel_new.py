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
from short_bot.locale import (LANGUAGE_NAMES, RSS_LOCALES, SUPPORTED_LANGUAGES)
from short_bot.pexels import load_secrets as _load_secrets
from short_bot.web.niche_finder import find_niches_ai, find_niches_data
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


@bp.route("/channels/new-reel", methods=["GET", "POST"])
def form():
    # Eski footage-sürüklü reel sihirbazı KALDIRILDI (2026-07-17, kürate pivotu) →
    # kürate kanal oluşturmaya yönlendir. Niş-bulucu route'ları (find-niches /
    # niche-status) edit_reel sayfası kullandığı için AŞAĞIDA durur.
    return redirect(url_for("curated.new_form"))


# ── Niş bulucu — Veri-Destekli + AI modları (arka plan iş + HTMX poll) ──────
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


def _run_niche_job(job_id: str, mode: str, query: str, language: str,
                   claude_path: str, or_model, or_key, api_keys=None) -> None:
    try:
        if mode == "ai":
            niches = find_niches_ai(query, language=language, claude_path=claude_path,
                                    openrouter_model=or_model, openrouter_key=or_key)
        else:
            niches = find_niches_data(query, language=language,
                                      api_keys=api_keys or [],
                                      claude_path=claude_path,
                                      openrouter_model=or_model,
                                      openrouter_key=or_key)
        _set_job(job_id, status="done", niches=niches)
    except Exception as e:  # noqa: BLE001 — hata mesajı kullanıcıya gösterilir
        _set_job(job_id, status="error", error=str(e))


@bp.route("/channels/new-reel/find-niches", methods=["POST"])
def find_niches_start():
    # "data": LLM adayları + YouTube outlier kanıtı (eski NexLev modunun yerine)
    mode = "ai" if request.form.get("mode") == "ai" else "data"
    query = (request.form.get("niche_query") or request.form.get("topic") or "").strip()
    language = request.form.get("language", "tr").strip()
    if language not in SUPPORTED_LANGUAGES:
        language = "tr"

    settings = current_app.config["SHORTBOT_SETTINGS"]
    claude_path = getattr(settings, "claude_cli_path", "claude") or "claude"
    # AI modunun OpenRouter fallback'i için model + anahtar (yapılandırıldıysa).
    secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
    secrets = _load_secrets(Path(secrets_path)) if secrets_path else {}
    or_key = secrets.get("openrouter_api_key") or None
    or_models = getattr(settings, "openrouter_models", {}) or {}
    or_model = or_models.get("default") or or_models.get("script") or or_models.get("dna")
    from short_bot.yt_outliers import resolve_youtube_api_keys
    api_keys = resolve_youtube_api_keys(secrets)

    job_id = uuid.uuid4().hex
    _set_job(job_id, status="running", niches=None, error=None, mode=mode)
    threading.Thread(
        target=_run_niche_job,
        args=(job_id, mode, query, language, claude_path, or_model, or_key,
              api_keys),
        daemon=True,
    ).start()
    return render_template("channels/_niche_results.html.j2",
                           job_id=job_id, status="running",
                           niches=None, error=None, mode=mode)


@bp.route("/channels/new-reel/niche-status/<job_id>")
def find_niches_status(job_id):
    job = _get_job(job_id)
    if not job:
        return render_template("channels/_niche_results.html.j2",
                               job_id=job_id, status="error", mode="data",
                               niches=None, error="Niş arama işi bulunamadı.")
    return render_template("channels/_niche_results.html.j2",
                           job_id=job_id, status=job.get("status"),
                           mode=job.get("mode", "data"),
                           niches=job.get("niches"), error=job.get("error"))
