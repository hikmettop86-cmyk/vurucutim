"""Kürate-klip keşfi + onay UI (pivot 2026-07-17, SP2/SP3).

Reddit'te topluluğun onayladığı (upvote) gerçek viral klipleri KATEGORİYE göre çeker,
"bize uygun en iyi" sıraya dizer (dikey + upvote + süre), üretilmiş olanları işaretler,
son aramayı cache'ler (sekme değişince kaybolmaz). Onaylanan klip run_pipeline üzerinden
üretilir → Akış'ta canlı görünür + /shorts'ta durur + yüklenebilir.
"""
import json
import threading
import uuid
from pathlib import Path

from flask import Blueprint, current_app, render_template, request

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
                  "AnimalsBeingGeniuses", "funnycats", "IllegallySmolCats"],
    "Tatmin edici": ["oddlysatisfying", "Satisfyingasfuck", "nevertellmetheodds"],
    "İnanılmaz": ["nextfuckinglevel", "BeAmazed", "interestingasfuck",
                  "Damnthatsinteresting"],
    "Fail / komik": ["Whatcouldgowrong", "instant_regret", "Wellthatsucks",
                     "facepalm"],
    "Doğa": ["NatureIsFuckingLit", "natureismetal", "BeAmazed"],
    "Şaşırtıcı anlar": ["Unexpected", "unexpected", "holdmyredbull"],
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
    """'Bize uygun en iyi' skoru: DİKEY (Shorts için ideal) + upvote + makul süre."""
    s = float(gem.get("ups", 0) or 0)
    orient = gem.get("orient")
    if orient == "DİKEY":
        s *= 2.5                       # dikey klip 9:16'ya tam oturur
    elif orient == "yatay":
        s *= 0.7                       # yatay kırpılınca içerik kaybı
    d = gem.get("duration") or 0
    if d and not (5 <= d <= 60):
        s *= 0.6                       # çok kısa/uzun (loop ya da sıkışma riski)
    return s


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
                   min_ups, max_duration, slug, category) -> None:
    from short_bot.reddit_gems import find_gems
    try:
        gems = find_gems(client_id, client_secret, subreddits=subreddits or None,
                         t=t, min_ups=min_ups, max_duration=max_duration)
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
    _set_job(job_id, status="running", gems=None, error=None, slug=slug)
    threading.Thread(
        target=_run_fetch_job, args=(job_id,),
        kwargs=dict(client_id=cid, client_secret=csec, subreddits=subreddits,
                    t=t, min_ups=min_ups, max_duration=max_duration, slug=slug,
                    category=category),
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
