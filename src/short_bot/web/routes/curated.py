"""Kürate-klip keşfi + onay UI (pivot 2026-07-17, SP2/SP3).

Reddit'te topluluğun onayladığı (upvote) gerçek viral klipleri KATEGORİYE göre çeker,
"bize uygun en iyi" sıraya dizer (dikey + upvote + süre), üretilmiş olanları işaretler,
son aramayı cache'ler (sekme değişince kaybolmaz). Onaylanan klip run_pipeline üzerinden
üretilir → Akış'ta canlı görünür + /shorts'ta durur + yüklenebilir.
"""
import json
import re
import threading
import uuid
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from short_bot.config import list_channels, load_channel
from short_bot.pexels import load_secrets as _load_secrets
from short_bot.web.runs import launch_pipeline

bp = Blueprint("curated", __name__)

_TIME_WINDOWS = ("hour", "day", "week", "month", "year", "all")

# KATEGORİLER: niş = subreddit kümesi. Kullanıcı kategori seçer (kanalın kendi
# subreddit listesi yerine). "Kanal ayarı" = kanalın reel.subreddits (ya da DEFAULT_SUBS).
CATEGORIES: dict[str, list[str]] = {
    "Hayvanlar": ["AnimalsBeingJerks", "AnimalsBeingDerps", "likeus",
                  "AnimalsBeingBros", "holdmycatnip", "AnimalsBeingConfused",
                  "AnimalsBeingGeniuses", "funnycats", "IllegallySmolCats",
                  "humansbeingbros"],
    # YÜKSEK-MERAK (doğrulandı: video-zengin + yüksek upvote 2026-07-17). 'Bunu
    # izlemeliyim' dedirten beklenmedik/gerilim anları — merak skorunu besler.
    "Kaos / beklenmedik": ["AbruptChaos", "maybemaybemaybe", "nonononoyes",
                           "Unexpected", "holdmyredbull", "nevertellmetheodds"],
    "Kahkaha / komik": ["contagiouslaughter", "therewasanattempt", "funnycats",
                        "instant_regret", "facepalm"],
    "Tatmin edici": ["oddlysatisfying", "Satisfyingasfuck", "nevertellmetheodds"],
    "İnanılmaz": ["nextfuckinglevel", "BeAmazed", "interestingasfuck",
                  "Damnthatsinteresting", "blackmagicfuckery", "toptalent"],
    "Fail / komik": ["Whatcouldgowrong", "instant_regret", "Wellthatsucks",
                     "facepalm", "therewasanattempt"],
    "Doğa": ["NatureIsFuckingLit", "natureismetal", "BeAmazed"],
    "Şaşırtıcı anlar": ["Unexpected", "holdmyredbull", "AbruptChaos",
                        "maybemaybemaybe", "nonononoyes"],
}

# Bellek-içi iş kaydı + son arama cache'i (tek kullanıcılı panel).
_jobs: dict = {}
_jobs_lock = threading.Lock()
_last_search: dict = {}          # {"gems": [...], "slug": str, "category": str}
_last_lock = threading.Lock()


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(fields)


def _get_job(job_id: str):
    with _jobs_lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def _curated_channels():
    chans = list_channels(current_app.config["SHORTBOT_CONFIG_DIR"] / "channels")
    return [c for c in chans if getattr(c, "reel", None) and c.reel.enabled]


def _secrets() -> dict:
    sp = current_app.config.get("SHORTBOT_SECRETS_PATH")
    return _load_secrets(Path(sp)) if sp else {}


def _rank_score(gem: dict) -> float:
    """Sıralama skoru: vision MERAK skoru işlendiyse final_score (engagement×merak),
    yoksa engagement (upvote + yorum-etkileşimi + yön + süre). Bkz. curated_rank."""
    if gem.get("final_score") is not None:
        return float(gem["final_score"])
    from short_bot.curated_rank import engagement_score
    return engagement_score(gem)


def _clip_key(video_url: str) -> str:
    """Klibin STABİL dedup anahtarı — varyant (CMAF/DASH) ve crosspost'tan bağımsız.
    v.redd.it/<id>/<variant> → vreddit:<id>; external → sorgu-suz url."""
    import re
    u = (video_url or "").split("?")[0]
    m = re.search(r"v\.redd\.it/([a-z0-9]+)", u)
    return "vreddit:" + m.group(1) if m else u


def _produced_keys(db_path) -> set:
    """Üretilmiş kliplerin dedup anahtarları (permalink + video-ID). produce_curated
    Short'un script_json'ına source_permalink + source_video_url yazar."""
    from sqlalchemy import select

    from short_bot.db import init_db, shorts
    keys: set = set()
    try:
        eng = init_db(db_path)
        with eng.connect() as c:
            for r in c.execute(select(shorts.c.script_json)):
                try:
                    d = json.loads(r.script_json or "{}")
                except Exception:  # noqa: BLE001
                    continue
                if d.get("source_permalink"):
                    keys.add(d["source_permalink"])
                if d.get("source_video_url"):
                    keys.add(_clip_key(d["source_video_url"]))
    except Exception:  # noqa: BLE001 — dedup yoksa da liste gösterilir
        pass
    return keys


def _is_produced(gem: dict, keys: set) -> bool:
    return (gem.get("permalink") in keys) or (_clip_key(gem.get("video_url", "")) in keys)


def _decorate(gems: list, db_path) -> list:
    """Gem'leri 'bize uygun' sıraya diz + üretilmiş olanları işaretle (dedup)."""
    produced = _produced_keys(db_path)
    out = [{**g, "produced": _is_produced(g, produced)} for g in gems]
    out.sort(key=lambda g: (g["produced"], -_rank_score(g)))  # üretilenler sona
    return out


def _run_fetch_job(job_id: str, *, client_id, client_secret, subreddits, t,
                   min_ups, max_duration, slug, category, vision_call=None) -> None:
    from short_bot.curated_rank import score_curiosity
    from short_bot.reddit_gems import find_gems
    try:
        gems = find_gems(client_id, client_secret, subreddits=subreddits or None,
                         t=t, min_ups=min_ups, max_duration=max_duration)
        # MERAK SKORU: en iyi adayların başlık+kapağını vision ile skorla → sıradan
        # değil, gerçekten izletici klipler öne çıkar (google_studio ücretsiz havuz).
        gems = score_curiosity(gems, vision_call=vision_call)
        _set_job(job_id, status="done", gems=gems)
        with _last_lock:                        # sekme değişince kaybolmasın
            _last_search.clear()
            _last_search.update(gems=gems, slug=slug, category=category)
    except Exception as e:  # noqa: BLE001
        _set_job(job_id, status="error", error=str(e))


@bp.route("/curated")
def index():
    channels = _curated_channels()
    sec = _secrets()
    have_creds = bool(sec.get("reddit_client_id") and sec.get("reddit_client_secret"))
    # Son aramayı cache'ten göster (sekme değişip geri gelince kaybolmaz).
    with _last_lock:
        last = dict(_last_search) if _last_search.get("gems") else None
    last_gems = None
    if last:
        last_gems = _decorate(last["gems"], current_app.config["SHORTBOT_DB_PATH"])
    return render_template("curated/index.html.j2", channels=channels,
                           have_creds=have_creds, categories=list(CATEGORIES),
                           last_gems=last_gems,
                           last_slug=(last or {}).get("slug", ""),
                           last_category=(last or {}).get("category", ""))


@bp.route("/curated/fetch", methods=["POST"])
def fetch():
    slug = (request.form.get("channel_slug") or "").strip()
    category = (request.form.get("category") or "").strip()
    t = (request.form.get("t") or "week").strip()
    if t not in _TIME_WINDOWS:
        t = "week"

    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    channel_path = cfg_dir / "channels" / f"{slug}.yaml"
    subreddits, max_duration, min_ups = [], 90, 500
    if slug and channel_path.exists():
        ch = load_channel(channel_path)
        if getattr(ch, "reel", None):
            subreddits = list(ch.reel.subreddits)
            max_duration = ch.reel.curated_max_duration
            min_ups = ch.reel.curated_min_ups
    # Kategori seçildiyse onun subreddit'leri kanal ayarını EZER.
    if category in CATEGORIES:
        subreddits = CATEGORIES[category]
    form_min = (request.form.get("min_ups") or "").strip()
    if form_min:
        try:
            min_ups = int(form_min)
        except ValueError:
            pass

    sec = _secrets()
    cid, csec = sec.get("reddit_client_id"), sec.get("reddit_client_secret")
    job_id = uuid.uuid4().hex
    if not (cid and csec):
        return render_template("curated/_results.html.j2", job_id=job_id,
                               status="error", gems=None,
                               error="Reddit API kimliği yok (data/secrets.yaml: "
                                     "reddit_client_id / reddit_client_secret).",
                               slug=slug)
    # VISION (merak skoru için): hibrit backend'de google_studio ücretsiz havuz.
    vision_call = None
    try:
        from short_bot.pipeline import resolve_ai_call
        vision_call = resolve_ai_call(current_app.config["SHORTBOT_SETTINGS"], sec, "vision")
    except Exception:  # noqa: BLE001 — vision yoksa engagement sırası (fail-open)
        vision_call = None
    _set_job(job_id, status="running", gems=None, error=None, slug=slug)
    threading.Thread(
        target=_run_fetch_job, args=(job_id,),
        kwargs=dict(client_id=cid, client_secret=csec, subreddits=subreddits,
                    t=t, min_ups=min_ups, max_duration=max_duration, slug=slug,
                    category=category, vision_call=vision_call),
        daemon=True).start()
    return render_template("curated/_results.html.j2", job_id=job_id,
                           status="running", gems=None, error=None, slug=slug)


@bp.route("/curated/status/<job_id>")
def status(job_id):
    job = _get_job(job_id)
    if not job:
        return render_template("curated/_results.html.j2", job_id=job_id,
                               status="error", gems=None,
                               error="Cevher arama işi bulunamadı.", slug="")
    gems = job.get("gems")
    if gems is not None:
        gems = _decorate(gems, current_app.config["SHORTBOT_DB_PATH"])
    return render_template("curated/_results.html.j2", job_id=job_id,
                           status=job.get("status"), gems=gems,
                           error=job.get("error"), slug=job.get("slug", ""))


@bp.route("/curated/produce", methods=["POST"])
def produce():
    # SP3: seçilen cevheri run_pipeline üzerinden üret → Akış'ta canlı görünür,
    # /shorts'ta durur, yüklenebilir. (Çıplak thread DEĞİL — Akış kaydı olsun diye.)
    slug = (request.form.get("channel_slug") or "").strip()
    video_url = (request.form.get("video_url") or "").strip()
    title = (request.form.get("title") or "").strip()
    permalink = (request.form.get("permalink") or "").strip()
    cfg = current_app.config
    channel_path = cfg["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not slug or not channel_path.exists() or not video_url:
        return render_template("curated/_produce.html.j2", status="error", title=title,
                               error="Kanal ya da klip seçili değil.")
    channel = load_channel(channel_path)
    gem = {"video_url": video_url, "title": title, "permalink": permalink}
    launch_pipeline(
        channel=channel, settings=cfg["SHORTBOT_SETTINGS"],
        db_path=cfg["SHORTBOT_DB_PATH"], music_root=cfg["SHORTBOT_MUSIC_ROOT"],
        templates_dir=cfg["SHORTBOT_TEMPLATES_DIR"], cache_dir=cfg["SHORTBOT_CACHE_DIR"],
        lock_dir=cfg["SHORTBOT_LOCK_DIR"], logs_dir=cfg["SHORTBOT_LOGS_DIR"],
        trigger="manual_curated", curated_gem=gem)
    return render_template("curated/_produce.html.j2", status="started", title=title)


# ── Kürate kanal OLUŞTURMA (eski footage-sürüklü reel sihirbazının yerine) ────
def _slug_from_name(name: str) -> str:
    from short_bot.text_normalize import strip_non_turkish_diacritics
    s = strip_non_turkish_diacritics(name).lower()
    s = (s.replace("ç", "c").replace("ğ", "g").replace("ı", "i").replace("ö", "o")
         .replace("ş", "s").replace("ü", "u"))
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "kanal"


def _unique_slug(base: str, channels_dir: Path) -> str:
    slug, i = base, 2
    while (channels_dir / f"{slug}.yaml").exists():
        slug, i = f"{base}-{i}", i + 1
    return slug


@bp.route("/channels/new-curated")
def new_form():
    from short_bot.lang_pack import load_pack
    try:
        personas = list((load_pack("tr").personas or {}).keys())
    except Exception:  # noqa: BLE001
        personas = []
    return render_template("channels/new_curated.html.j2",
                           personas=personas, categories=list(CATEGORIES))


@bp.route("/channels/new-curated", methods=["POST"])
def new_create():
    from pydantic import ValidationError

    from short_bot.config import ChannelConfig, ReelConfig, save_channel
    from short_bot.lang_pack import load_pack
    name = (request.form.get("name") or "").strip()
    voice_id = (request.form.get("voice_id") or "").strip()
    language = (request.form.get("language") or "tr").strip()
    persona = (request.form.get("persona") or "").strip()
    category = (request.form.get("category") or "").strip()
    subs_raw = (request.form.get("subreddits") or "").strip()

    if not name:
        flash("Kanal adı gerekli.", "error")
        return redirect(url_for("curated.new_form"))
    if not voice_id:
        flash("Kürate kanalı için bir ses seç (voice_id boş).", "error")
        return redirect(url_for("curated.new_form"))
    # Dil paketi ŞART (persona + altyazı doğru dilde basılsın).
    try:
        load_pack(language)
    except RuntimeError:
        flash(f"'{language}' dil paketi henüz üretilmedi — Diller sayfasından üret.",
              "error")
        return redirect(url_for("curated.new_form"))

    # Subreddit listesi: kategori seçildiyse onun listesi, yoksa textarea ayrıştırılır.
    if category in CATEGORIES:
        subreddits = list(CATEGORIES[category])
    else:
        subreddits = [s.strip().removeprefix("r/").strip()
                      for s in re.split(r"[\s,]+", subs_raw) if s.strip()]

    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    channels_dir = cfg_dir / "channels"
    slug = _unique_slug(_slug_from_name(name), channels_dir)
    try:
        reel = ReelConfig(
            enabled=True, voice_id=voice_id, persona=persona,
            mascot_name=(request.form.get("mascot_name") or "").strip(),
            mascot_animal=(request.form.get("mascot_animal") or "").strip(),
            mascot_trait=(request.form.get("mascot_trait") or "").strip(),
            subreddits=subreddits,
            humor_style=(request.form.get("humor_style") or "").strip(),
            highlight_color=(request.form.get("highlight_color") or "#38bdf8").strip(),
            music_mood=(request.form.get("music_mood") or "upbeat").strip())
    except ValidationError as e:
        flash(f"Reel ayarları geçersiz: {e}", "error")
        return redirect(url_for("curated.new_form"))

    # Kürate kanalı: content_source='curated', dna YOK (reel çıktısı kullanmıyor),
    # generator bloğu YOK (konu Reddit'ten gelir). template placeholder (kürate overlay
    # kanal template'ini değil reel_overlay'i kullanır).
    cfg = ChannelConfig(
        slug=slug, name=name, keywords=[], rss_locale="",
        schedule_cron="0 10 * * *", duration_s=20, min_score=7.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#0ea5e9", "accent": "#38bdf8",
                "bg_gradient": ["#0f172a", "#020617"]},
        handle=f"@{slug}", output_dir=f"output/{slug}", enabled=True,
        language=language, dna=None, content_source="curated", reel=reel)
    save_channel(channels_dir / f"{slug}.yaml", cfg)
    flash(f"'{name}' kürate kanalı oluşturuldu. Cevher'den klip seçip üret.", "success")
    return redirect(url_for("curated.edit_curated", slug=slug))


# ── Kürate kanal DÜZENLEME (temiz — eski konu/seri/niş/footage baggage YOK) ───
@bp.route("/channels/<slug>/edit-curated")
def edit_curated(slug):
    from short_bot.lang_pack import load_pack
    path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not path.exists():
        abort(404)
    ch = load_channel(path)
    try:
        personas = list((load_pack("tr").personas or {}).keys())
    except Exception:  # noqa: BLE001
        personas = []
    # YouTube bağlantı context'i — generic /channels/<slug>/youtube/* route'ları
    # (connect/disconnect/reset/upload-secrets) her kanal slug'ı için çalışır.
    from short_bot.youtube import auth as _yt_auth
    yt_root = current_app.config.get("SHORTBOT_YT_CREDS_DIR")
    yt_connected = bool(yt_root and _yt_auth.has_credentials(yt_root, slug))
    yt_info = (_yt_auth.load_channel_info(yt_root, slug)
               if yt_root and yt_connected else None)
    yt_secrets_path = (yt_root / slug / "client_secrets.json") if yt_root else None
    yt_has_secrets = bool(yt_secrets_path and yt_secrets_path.is_file())
    return render_template("channels/edit_curated.html.j2", ch=ch,
                           personas=personas, categories=list(CATEGORIES),
                           yt_connected=yt_connected, yt_info=yt_info,
                           yt_has_secrets=yt_has_secrets,
                           yt_secrets_abs=(str((yt_root / slug).resolve())
                                           if yt_root else ""))


@bp.route("/channels/<slug>/edit-curated", methods=["POST"])
def edit_curated_save(slug):
    import dataclasses

    from short_bot.config import YoutubeChannelConfig, save_channel
    path = current_app.config["SHORTBOT_CONFIG_DIR"] / "channels" / f"{slug}.yaml"
    if not path.exists():
        abort(404)
    ch = load_channel(path)

    category = (request.form.get("category") or "").strip()
    if category in CATEGORIES:
        subreddits = list(CATEGORIES[category])
    else:
        subreddits = [s.strip().removeprefix("r/").strip()
                      for s in re.split(r"[\s,]+", request.form.get("subreddits") or "")
                      if s.strip()]

    def _int(field, default):
        try:
            return int(request.form.get(field) or default)
        except ValueError:
            return default

    reel = ch.reel.model_copy(update=dict(
        voice_id=(request.form.get("voice_id") or ch.reel.voice_id).strip(),
        persona=(request.form.get("persona") or "").strip(),
        mascot_name=(request.form.get("mascot_name") or "").strip(),
        mascot_animal=(request.form.get("mascot_animal") or "").strip(),
        mascot_trait=(request.form.get("mascot_trait") or "").strip(),
        subreddits=subreddits,
        humor_style=(request.form.get("humor_style") or "").strip(),
        highlight_color=(request.form.get("highlight_color") or ch.reel.highlight_color).strip(),
        music_mood=(request.form.get("music_mood") or ch.reel.music_mood).strip(),
        curated_min_ups=_int("curated_min_ups", ch.reel.curated_min_ups),
        curated_time=(request.form.get("curated_time") or ch.reel.curated_time).strip(),
        curated_clean=(request.form.get("curated_clean") == "on"),
    ))
    yt = (ch.youtube or YoutubeChannelConfig()).model_copy(
        update=dict(auto_upload=(request.form.get("auto_upload") == "on")))
    ch = dataclasses.replace(
        ch, name=(request.form.get("name") or ch.name).strip(),
        schedule_cron=(request.form.get("schedule_cron") or ch.schedule_cron).strip(),
        enabled=(request.form.get("enabled") == "on"), reel=reel, youtube=yt)
    save_channel(path, ch)
    flash(f"'{ch.name}' kürate kanalı güncellendi.", "success")
    return redirect(url_for("curated.edit_curated", slug=slug))
