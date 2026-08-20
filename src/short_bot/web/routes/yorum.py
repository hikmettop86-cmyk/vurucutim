"""Gündem Yorum formatı — kurulum sihirbazı ve düzenleme sayfası.

6 sn karttan BAĞIMSIZ kurulum (kullanıcı isteği): bu sayfalarda DNA/palet/overflow
kartları yok; yalnız formatın alanları — kaynak (Trends bölgesi, min hacim, tempo),
yorumcu personası, Cartesia sesi, hedef süre, müzik. Kanal listesi
``formats.channel_format`` ile bu sayfaya yönlendirir.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from pydantic import ValidationError

from short_bot.config import ChannelConfig, VoiceConfig, YoutubeChannelConfig, load_channel, save_channel
from short_bot.formats import channel_format
from short_bot.narration_writer import YORUM_PERSONA_TR

bp = Blueprint("yorum", __name__)

# Günde N koşu → cron. Trend ömrü kısa; gün içine yayılır, 6 sn kartla çakışmasın
# diye :30'da.
RUNS_PER_DAY_CRON: dict[int, str] = {
    2: "30 9,18 * * *",
    3: "30 9,14,19 * * *",
    4: "30 8,12,16,20 * * *",
    5: "30 8-20/3 * * *",
    6: "30 7-22/3 * * *",
    8: "30 7-21/2 * * *",
}
REGIONS = [("TR", "Türkiye"), ("DE", "Almanya"), ("ES", "İspanya"), ("US", "ABD"),
           ("FR", "Fransa"), ("JP", "Japonya"), ("GB", "Birleşik Krallık"), ("AT", "Avusturya")]

_DEFAULT_COLORS = {"primary": "#d0021b", "accent": "#ffe600", "bg_gradient": ["#3a3a3a", "#141414"]}


def _channels_dir() -> Path:
    return current_app.config["SHORTBOT_CONFIG_DIR"] / "channels"


def _slug_from_name(name: str) -> str:
    s = name.lower()
    for a, b in (("ç", "c"), ("ğ", "g"), ("ı", "i"), ("ö", "o"), ("ş", "s"), ("ü", "u")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "yorum"


def _unique_slug(base: str, channels_dir: Path) -> str:
    slug, i = base, 2
    while (channels_dir / f"{slug}.yaml").exists():
        slug, i = f"{base}-{i}", i + 1
    return slug


def _template_dna():
    """Flaş kimliği: varsa gundem kanalının DNA'sı kopyalanır, yoksa arketip varsayılanı."""
    src = _channels_dir() / "gundem.yaml"
    if src.exists():
        try:
            return copy.deepcopy(load_channel(src).dna)
        except Exception:  # noqa: BLE001
            return None
    return None


def _form_int(name, default):
    try:
        return int(request.form.get(name, default))
    except (TypeError, ValueError):
        return default


def _form_float(name, default):
    try:
        return float(request.form.get(name, default))
    except (TypeError, ValueError):
        return default


def _voice_from_form(old: VoiceConfig | None) -> VoiceConfig:
    return VoiceConfig(
        enabled=True,
        provider=(request.form.get("voice_provider") or (old.provider if old else "cartesia")),
        voice_id=(request.form.get("voice_id") or (old.voice_id if old else "")).strip(),
        speed=_form_float("voice_speed", old.speed if old else 1.05),
        persona=(request.form.get("voice_persona") or "").strip() or (old.persona if old else YORUM_PERSONA_TR),
        target_duration_s=(_form_int("voice_target_min", old.target_duration_s[0] if old else 35),
                           _form_int("voice_target_max", old.target_duration_s[1] if old else 50)),
        music_volume=_form_float("voice_music_volume", old.music_volume if old else 0.05),
        model=(request.form.get("voice_model") if "voice_model" in request.form
               else (old.model if old else "")) or "",
        volume=_form_float("voice_volume", old.volume if old else 1.0),
        emotion=(request.form.get("voice_emotion") if "voice_emotion" in request.form
                 else (old.emotion if old else "")) or "",
    )


def _region_from_form(default: str | None) -> str | None:
    raw = (request.form.get("trends_region") or "").strip().upper()
    if not raw:
        return default
    if not re.fullmatch(r"[A-Z]{2}", raw):
        raise ValueError("Bölge iki harfli ISO kodu olmalı (TR, DE, ES…).")
    return raw


def _cron_from_form(default: str) -> str:
    n = request.form.get("runs_per_day")
    if n and n.isdigit() and int(n) in RUNS_PER_DAY_CRON:
        return RUNS_PER_DAY_CRON[int(n)]
    return (request.form.get("schedule_cron") or default).strip() or default


@bp.route("/channels/new-yorum")
def new_form():
    return render_template("channels/new_yorum.html.j2", regions=REGIONS,
                           runs=sorted(RUNS_PER_DAY_CRON), default_persona=YORUM_PERSONA_TR)


@bp.route("/channels/new-yorum", methods=["POST"])
def new_create():
    name = (request.form.get("name") or "").strip()
    language = (request.form.get("language") or "tr").strip().lower()
    if not name:
        flash("Kanal adı gerekli.", "error")
        return redirect(url_for("yorum.new_form"))
    try:
        voice = _voice_from_form(None)
        region = _region_from_form("TR")
    except (ValidationError, ValueError) as e:
        flash(f"Ayar geçersiz: {e}", "error")
        return redirect(url_for("yorum.new_form"))
    if not voice.voice_id:
        flash("Bir Cartesia sesi seç (voice_id boş).", "error")
        return redirect(url_for("yorum.new_form"))
    channels_dir = _channels_dir()
    slug = _unique_slug(_slug_from_name(name), channels_dir)
    dna = _template_dna()
    cfg = ChannelConfig(
        slug=slug, name=name, keywords=[f"{name} gündemi", "son dakika"],
        rss_locale="", schedule_cron=_cron_from_form(RUNS_PER_DAY_CRON[5]),
        duration_s=6, min_score=6.0, max_candidates_per_run=25, max_age_hours=24,
        template="flas", colors=dict(_DEFAULT_COLORS),
        handle=(request.form.get("handle") or f"@{slug}").strip(),
        output_dir=f"output/{slug}", enabled=True, language=language,
        dna=dna, script_model=(request.form.get("script_model") or "opus").strip() or None,
        content_source="trends", trends_region=region,
        trends_min_volume=_form_int("trends_min_volume", 5000),
        youtube=YoutubeChannelConfig(auto_upload=False, ai_content=False, category_id="25",
                                     privacy_status="public", min_score_for_upload=6.0),
        voice=voice,
    )
    save_channel(channels_dir / f"{slug}.yaml", cfg)
    flash(f"'{name}' Gündem Yorum kanalı oluşturuldu. İlk videoyu 'Şimdi üret' ile dene.", "success")
    return redirect(url_for("yorum.edit", slug=slug))


def _recent(slug: str, limit: int = 10):
    """Son üretimler + anlatım metni (operatör okuyup yükler — insan incelemesi)."""
    import json

    from short_bot.web.models import Short
    rows = (Short.query.filter_by(channel=slug).filter(Short.deleted_at.is_(None))
            .order_by(Short.created_at.desc()).limit(limit).all())
    out = []
    for r in rows:
        narr = ""
        try:
            narr = (json.loads(r.script_json or "{}") or {}).get("narration_text", "") or ""
        except ValueError:
            narr = ""
        out.append({"id": r.id, "title": r.title, "created_at": r.created_at,
                    "duration_s": r.duration_s, "narration": narr,
                    "file": Path(r.file_path).name if r.file_path else ""})
    return out


@bp.route("/channels/<slug>/edit-yorum")
def edit(slug):
    path = _channels_dir() / f"{slug}.yaml"
    if not path.exists():
        abort(404)
    c = load_channel(path)
    if channel_format(c) != "yorum":
        return redirect(url_for("channel_edit.edit", slug=slug))
    runs_now = next((n for n, cron in RUNS_PER_DAY_CRON.items() if cron == c.schedule_cron), None)
    from short_bot.youtube import auth as _yt_auth
    yt_root = current_app.config.get("SHORTBOT_YT_CREDS_DIR")
    yt_connected = bool(yt_root and _yt_auth.has_credentials(yt_root, slug))
    return render_template("channels/edit_yorum.html.j2", c=c, regions=REGIONS,
                           runs=sorted(RUNS_PER_DAY_CRON), runs_now=runs_now,
                           recent=_recent(slug), yt_connected=yt_connected,
                           default_persona=YORUM_PERSONA_TR)


@bp.route("/channels/<slug>/edit-yorum", methods=["POST"])
def edit_save(slug):
    import dataclasses
    path = _channels_dir() / f"{slug}.yaml"
    if not path.exists():
        abort(404)
    c = load_channel(path)
    try:
        voice = _voice_from_form(c.voice)
        region = _region_from_form(c.trends_region)
    except (ValidationError, ValueError) as e:
        first = e.errors()[0].get("msg", str(e)) if isinstance(e, ValidationError) and e.errors() else str(e)
        flash(f"Ayar geçersiz: {first}", "error")
        return redirect(url_for("yorum.edit", slug=slug))
    yt = c.youtube or YoutubeChannelConfig()
    yt = yt.model_copy(update={"auto_upload": request.form.get("auto_upload") == "on"})
    new_cfg = dataclasses.replace(
        c,
        name=(request.form.get("name") or c.name).strip(),
        handle=(request.form.get("handle") or c.handle).strip(),
        enabled=(request.form.get("enabled") == "1"),
        schedule_cron=_cron_from_form(c.schedule_cron),
        min_score=_form_float("min_score", c.min_score),
        trends_region=region,
        trends_min_volume=_form_int("trends_min_volume", c.trends_min_volume),
        script_model=(request.form.get("script_model") or c.script_model or "").strip() or None,
        voice=voice, youtube=yt,
    )
    save_channel(path, new_cfg)
    flash("Gündem Yorum ayarları kaydedildi.", "success")
    return redirect(url_for("yorum.edit", slug=slug))
