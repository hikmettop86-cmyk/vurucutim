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


def _slug_from_name(name: str) -> str:
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
