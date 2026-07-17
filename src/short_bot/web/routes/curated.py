"""Kürate-klip keşfi + onay UI (pivot 2026-07-17, SP2).

Reddit'te topluluğun onayladığı (upvote) gerçek viral klipleri kanalın subreddit
listesinden çeker, panelde ızgara olarak gösterir; kullanıcı görüp seçer. Arka-plan
iş + HTMX poll deseni (reel_new niş-bulucu ile aynı — tek kullanıcılı masaüstü panel,
bellek-içi iş kaydı yeter). Seçilen cevherin ÜRETİME bağlanması SP3'te
(indir → vision-anla → yeniden-senaryo → montaj).
"""
import threading
import uuid
from pathlib import Path

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)

from short_bot.config import list_channels, load_channel
from short_bot.pexels import load_secrets as _load_secrets

bp = Blueprint("curated", __name__)

_TIME_WINDOWS = ("hour", "day", "week", "month", "year", "all")

# Bellek-içi iş kaydı (reel_new deseni). Tek kullanıcılı panel → kalıcılık gerekmez.
_jobs: dict = {}
_jobs_lock = threading.Lock()


def _set_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(fields)


def _get_job(job_id: str):
    with _jobs_lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def _curated_channels():
    """Cevher hedefi olabilecek kanallar: reel etkin (persona-fit) olanlar."""
    chans = list_channels(current_app.config["SHORTBOT_CONFIG_DIR"] / "channels")
    return [c for c in chans if getattr(c, "reel", None) and c.reel.enabled]


def _secrets() -> dict:
    sp = current_app.config.get("SHORTBOT_SECRETS_PATH")
    return _load_secrets(Path(sp)) if sp else {}


def _run_fetch_job(job_id: str, *, client_id: str, client_secret: str,
                   subreddits, t: str, min_ups: int, max_duration: int) -> None:
    from short_bot.reddit_gems import find_gems
    try:
        gems = find_gems(client_id, client_secret, subreddits=subreddits or None,
                         t=t, min_ups=min_ups, max_duration=max_duration)
        _set_job(job_id, status="done", gems=gems)
    except Exception as e:  # noqa: BLE001 — hata mesajı kullanıcıya gösterilir
        _set_job(job_id, status="error", error=str(e))


@bp.route("/curated")
def index():
    channels = _curated_channels()
    sec = _secrets()
    have_creds = bool(sec.get("reddit_client_id") and sec.get("reddit_client_secret"))
    return render_template("curated/index.html.j2",
                           channels=channels, have_creds=have_creds)


@bp.route("/curated/fetch", methods=["POST"])
def fetch():
    slug = (request.form.get("channel_slug") or "").strip()
    t = (request.form.get("t") or "week").strip()
    if t not in _TIME_WINDOWS:
        t = "week"

    # Kanal ayarları: subreddit listesi + kürate eşikleri. Formda min_ups verilmişse
    # o öncelikli; yoksa kanalın curated_min_ups'i.
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    channel_path = cfg_dir / "channels" / f"{slug}.yaml"
    subreddits, max_duration = [], 90
    min_ups = 500
    form_min = (request.form.get("min_ups") or "").strip()
    if slug and channel_path.exists():
        ch = load_channel(channel_path)
        if getattr(ch, "reel", None):
            subreddits = list(ch.reel.subreddits)
            max_duration = ch.reel.curated_max_duration
            min_ups = ch.reel.curated_min_ups
    if form_min:
        try:
            min_ups = int(form_min)
        except ValueError:
            pass

    sec = _secrets()
    cid = sec.get("reddit_client_id")
    csec = sec.get("reddit_client_secret")
    job_id = uuid.uuid4().hex
    if not (cid and csec):
        # Kimlik yoksa iş başlatma; hatayı DOĞRUDAN render et (poll gereksiz).
        return render_template("curated/_results.html.j2", job_id=job_id,
                               status="error", gems=None,
                               error="Reddit API kimliği yok (data/secrets.yaml: "
                                     "reddit_client_id / reddit_client_secret).",
                               slug=slug)
    _set_job(job_id, status="running", gems=None, error=None, slug=slug)
    threading.Thread(
        target=_run_fetch_job, args=(job_id,),
        kwargs=dict(client_id=cid, client_secret=csec, subreddits=subreddits,
                    t=t, min_ups=min_ups, max_duration=max_duration),
        daemon=True).start()
    # DAİMA 'running' render et: iş anında bitse bile poll sonucu (done/error) çeker.
    # (status geri-okuması yarış: mock find_gems thread'i render'dan önce bitebilir.)
    return render_template("curated/_results.html.j2", job_id=job_id,
                           status="running", gems=None, error=None, slug=slug)


@bp.route("/curated/status/<job_id>")
def status(job_id):
    job = _get_job(job_id)
    if not job:
        return render_template("curated/_results.html.j2", job_id=job_id,
                               status="error", gems=None,
                               error="Cevher arama işi bulunamadı.", slug="")
    return render_template("curated/_results.html.j2", job_id=job_id,
                           status=job.get("status"), gems=job.get("gems"),
                           error=job.get("error"), slug=job.get("slug", ""))


@bp.route("/curated/produce", methods=["POST"])
def produce():
    # SP2: seçim alınır ve doğrulanır; ÜRETİM hattına bağlama SP3'te (indir →
    # vision-anla → yeniden-senaryo → montaj). Burada henüz launch_pipeline yok.
    slug = (request.form.get("channel_slug") or "").strip()
    title = (request.form.get("title") or "").strip()[:80]
    if not slug:
        flash("Kanal seçili değil.", "error")
    else:
        flash(f"Cevher seçildi: “{title}” → {slug}. Üretim hattı SP3'te bağlanacak.",
              "success")
    return redirect(url_for("curated.index"))
