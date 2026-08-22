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

from short_bot.config import (ChannelConfig, VoiceConfig, YoutubeChannelConfig, list_channels,
                              load_channel, save_channel)
from short_bot.formats import channel_format
from short_bot.narration_writer import YORUM_PERSONAS, default_yorum_persona
from short_bot.trends.verticals import VERTICAL_LABELS

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

# Dikey listesi: kanalın kimliği. Boş seçim = eski davranış (tüm havuz).
VERTICALS = sorted(VERTICAL_LABELS.items())

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


def _voice_from_form(old: VoiceConfig | None, language: str = "tr") -> VoiceConfig:
    return VoiceConfig(
        enabled=True,
        provider=(request.form.get("voice_provider") or (old.provider if old else "cartesia")),
        voice_id=(request.form.get("voice_id") or (old.voice_id if old else "")).strip(),
        speed=_form_float("voice_speed", old.speed if old else 1.05),
        # Persona kanalın DİLİNDE varsayılır. Türkçe personayı Almanca kanala
        # koymak sessiz bozulmadır: ses Almanca, metin Türkçe çıkar.
        persona=((request.form.get("voice_persona") or "").strip()
                 or (old.persona if old else "")
                 or default_yorum_persona(language)),
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


def _dikey_from_form(default: str | None) -> str | None:
    """Formdan dikey. Alan formda YOKSA eski değer korunur — başka bir kartın
    POST'u dikeyi sessizce silmesin (panel DNA palet tuzağının aynısı)."""
    if "trends_vertical" not in request.form:
        return default
    return (request.form.get("trends_vertical") or "").strip().lower() or None


def _cron_from_form(default: str) -> str:
    n = request.form.get("runs_per_day")
    if n and n.isdigit() and int(n) in RUNS_PER_DAY_CRON:
        return RUNS_PER_DAY_CRON[int(n)]
    return (request.form.get("schedule_cron") or default).strip() or default


@bp.route("/channels/new-yorum")
def new_form():
    return render_template("channels/new_yorum.html.j2", regions=REGIONS,
                           verticals=VERTICALS,
                           runs=sorted(RUNS_PER_DAY_CRON),
                           default_persona=default_yorum_persona("tr"),
                           personas=dict(YORUM_PERSONAS))


@bp.route("/channels/new-yorum", methods=["POST"])
def new_create():
    name = (request.form.get("name") or "").strip()
    language = (request.form.get("language") or "tr").strip().lower()
    if not name:
        flash("Kanal adı gerekli.", "error")
        return redirect(url_for("yorum.new_form"))
    try:
        voice = _voice_from_form(None, language)
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
        # Yorum formatı CEVAP verir: soru sorulan konu onun işi. Kart kanalı
        # "breaking" alır → iki format aynı olayı iki kez anlatmaz.
        trends_intent=(request.form.get("trends_intent") or "question"),
        trends_vertical=_dikey_from_form(None),
        youtube=YoutubeChannelConfig(auto_upload=False, ai_content=False, category_id="25",
                                     privacy_status="public", min_score_for_upload=6.0),
        voice=voice,
    )
    save_channel(channels_dir / f"{slug}.yaml", cfg)
    flash(f"'{name}' Gündem Yorum kanalı oluşturuldu. İlk videoyu 'Şimdi üret' ile dene.", "success")
    return redirect(url_for("channel_edit.edit", slug=slug))


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
def edit_eski(slug):
    """Eski yol — tek rotaya kalıcı yönlendirme.

    Kullanıcının kayıtlı sekmeleri ve tarayıcı geçmişi kırılmasın diye 301.
    Sayfayı artık channel_edit.edit çiziyor (formata göre `edit`i çağırarak)."""
    return redirect(url_for("channel_edit.edit", slug=slug), code=301)


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
    cslug = _yt_auth.creds_slug(c)
    yt_connected = bool(yt_root and _yt_auth.has_credentials(yt_root, cslug))
    yt_info = (_yt_auth.load_channel_info(yt_root, cslug)
               if yt_root and yt_connected else None)
    # ORTAK PARÇANIN SÖZLEŞMESİ: yt_has_secrets verilmezse Jinja onu FALSY
    # sayar ve sayfa client_secrets yüklendikten sonra bile hep 'yükle'
    # ekranında kalır — 'Bağla' düğmesi ASLA görünmez (2026-08-22 vakası).
    # Dosya kanalın KENDİ klasöründe aranır: yükleme oraya yazıyor.
    _sec_path = (yt_root / slug / 'client_secrets.json') if yt_root else None
    yt_has_secrets = bool(_sec_path and _sec_path.is_file())
    yt_secrets_abs = str((yt_root / slug).resolve()) if yt_root else ''
    # Bağlantısı olan diğer kanallar: aynı YouTube kanalına üreten formatlar
    # (6 sn kart + yorum) tek bağlantıyı paylaşabilsin.
    linkable, yt_clash = [], []
    if yt_root:
        all_slugs = [o.slug for o in list_channels(_channels_dir(), enabled_only=False)]
        for other in list_channels(_channels_dir(), enabled_only=False):
            if other.slug != slug and _yt_auth.has_credentials(yt_root, other.slug):
                info = _yt_auth.load_channel_info(yt_root, other.slug) or {}
                linkable.append({"slug": other.slug, "name": other.name,
                                 "yt": (info.get("snippet") or {}).get("title", ""),
                                 "connected": True})
        # SEÇİLİ DEĞER HER ZAMAN LİSTEDE OLMALI — henüz bağlanmamış olsa bile.
        # CANLI VAKA (2026-08-20): deutschland-klartext'in credentials_from'u
        # 'deutschland-kompakt' idi ama o kanal henüz OAuth'lanmamıştı, bu yüzden
        # açılırda HİÇ seçenek yoktu; tarayıcı boş değeri gönderdi ve ayar
        # SESSİZCE silindi. (Aynı aile: dil açılırının ilk seçeneğe düşmesi.)
        mevcut = (c.youtube.credentials_from if c.youtube else None)
        if mevcut and mevcut not in {l["slug"] for l in linkable}:
            baslik = next((o.name for o in list_channels(_channels_dir(), enabled_only=False)
                           if o.slug == mevcut), mevcut)
            linkable.insert(0, {"slug": mevcut, "name": baslik, "yt": "",
                                "connected": False})
        # Aynı YouTube kanalına bağlı başka slug var mı — paylaşım BEYAN EDİLMEMİŞSE
        # bu yanlış bağlantı demektir (Google hesap seçicisinde yanlış marka kanalı).
        declared = {(c.youtube.credentials_from if c.youtube else None), cslug, slug}
        yt_clash = [o for o in _yt_auth.same_youtube_channel(yt_root, cslug, all_slugs)
                    if o not in declared]
    return render_template("channels/edit_yorum.html.j2", c=c, regions=REGIONS,
                           verticals=VERTICALS,
                           runs=sorted(RUNS_PER_DAY_CRON), runs_now=runs_now,
                           recent=_recent(slug), yt_connected=yt_connected,
                           yt_info=yt_info, creds_slug=cslug, linkable=linkable,
                           yt_clash=yt_clash, yt_has_secrets=yt_has_secrets,
                           yt_secrets_abs=yt_secrets_abs,
                           default_persona=default_yorum_persona(c.language)
                           or default_yorum_persona("tr"))


@bp.route("/channels/<slug>/edit-yorum", methods=["POST"])
def edit_save(slug):
    import dataclasses
    path = _channels_dir() / f"{slug}.yaml"
    if not path.exists():
        abort(404)
    c = load_channel(path)
    try:
        voice = _voice_from_form(c.voice, c.language)
        region = _region_from_form(c.trends_region)
    except (ValidationError, ValueError) as e:
        first = e.errors()[0].get("msg", str(e)) if isinstance(e, ValidationError) and e.errors() else str(e)
        flash(f"Ayar geçersiz: {first}", "error")
        return redirect(url_for("channel_edit.edit", slug=slug))
    # Ortak alanlar (ad, handle, enabled, archived, YouTube bloğunun TAMAMI) tek
    # okuyucudan gelir. Bu sayfada eskiden yalnız `auto_upload` ve
    # `credentials_from` vardı; gizlilik, kategori, yükleme eşiği ve AI etiketi
    # UI'de HİÇ YOKTU — YAML'da olsalar bile panelden değiştirilemiyorlardı.
    from short_bot.web.core_fields import core_updates
    guncel = dict(
        # Bu formatta cron "günde kaç video"dan TÜRETİLİR; formda `schedule_cron`
        # alanı yok, bu yüzden core_updates ona dokunmaz.
        schedule_cron=_cron_from_form(c.schedule_cron),
        min_score=_form_float("min_score", c.min_score),
        trends_region=region,
        trends_min_volume=_form_int("trends_min_volume", c.trends_min_volume),
        trends_intent=(request.form.get("trends_intent") or c.trends_intent),
        brand_safety=(request.form.get("brand_safety") or c.brand_safety),
        trends_vertical=_dikey_from_form(c.trends_vertical),
        script_model=(request.form.get("script_model") or c.script_model or "").strip() or None,
        voice=voice,
    )
    guncel.update(core_updates(request.form, c))
    new_cfg = dataclasses.replace(c, **guncel)
    save_channel(path, new_cfg)
    flash("Gündem Yorum ayarları kaydedildi.", "success")
    return redirect(url_for("channel_edit.edit", slug=slug))


@bp.route("/channels/<slug>/compile-day", methods=["POST"])
def compile_day(slug):
    """Günün derlemesini elle üret (panel düğmesi). Süre eşiğin altındaysa uyarır;
    ``force=1`` ile yine de üretir (Shorts sayılacağını bilerek)."""
    from datetime import date

    from short_bot.compilation import MIN_TOTAL_S, pick_day_clips, produce_daily_compilation, total_seconds
    from short_bot.db import init_db
    path = _channels_dir() / f"{slug}.yaml"
    if not path.exists():
        abort(404)
    c = load_channel(path)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    settings = current_app.config["SHORTBOT_SETTINGS"]
    day = date.today()
    force = request.form.get("force") == "1"
    try:
        clips = pick_day_clips(eng, slug, day)
        total = total_seconds(clips)
        if not clips:
            flash("Bugün derlenecek klip yok.", "error")
            return redirect(url_for("channel_edit.edit", slug=slug))
        if total < MIN_TOTAL_S and not force:
            flash(f"Bugünkü {len(clips)} klip toplam {total:.0f} sn — 3 dk 10 sn altı YouTube'da Shorts "
                  f"sayılır. Daha fazla klip biriksin ya da 'yine de üret' için force=1 gönder.", "error")
            return redirect(url_for("channel_edit.edit", slug=slug))
        sid = produce_daily_compilation(
            c, eng=eng, day=day, templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
            output_root=current_app.config["SHORTBOT_OUTPUT_ROOT"], ffmpeg=settings.ffmpeg_path,
            browser=settings.playwright_browser, force=force)
    except Exception as e:  # noqa: BLE001 — panel düğmesi; hata kullanıcıya
        flash(f"Derleme başarısız: {e}", "error")
        return redirect(url_for("channel_edit.edit", slug=slug))
    flash(f"Günün derlemesi üretildi (short #{sid}, {total:.0f} sn). Yükleme elle.", "success")
    return redirect(url_for("shorts.detail", short_id=sid) if "shorts.detail" in current_app.view_functions
                    else url_for("yorum.edit", slug=slug))
