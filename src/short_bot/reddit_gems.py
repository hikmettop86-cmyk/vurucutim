"""Reddit 'cevher bulucu': persona-fit subreddit'lerden yüksek-upvote VIDEO klipleri
bulur (kürasyon adayı). Curated-clip modeli (2026-07-17 pivot): jenerik stok + uydurma
dram YERİNE, kitlenin ZATEN onayladığı (upvote) gerçek komik/tatmin edici anları getir,
persona ile yeniden-anlatılsın. Reddit OAuth (client_credentials, app-only) gerekir.

Yalnız DİSCOVERY + metrik + video-URL çıkarır; indirme yt-dlp'ye, onay kullanıcıya,
yeniden-senaryo mevcut reel hattına bırakılır.
"""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_API = "https://oauth.reddit.com"
_UA = "shortbot-gemfinder/0.1"

# Persona-fit (mahalle vahşisi = karakterli/kabadayı/şaşırtıcı hayvan): topluluk oyu
# (upvote) 'satisfying/komik' sinyalini zaten taşıyor.
DEFAULT_SUBS = [
    "AnimalsBeingJerks", "AnimalsBeingDerps", "likeus", "AnimalsBeingBros",
    "NatureIsFuckingLit", "Unexpected", "nextfuckinglevel", "holdmycatnip",
    "AnimalsBeingConfused", "sweatystartup",  # placeholder; kullanıcı listeyi düzenler
]

# İndirilebilir video kaynakları (yt-dlp bunları çözer).
_VIDEO_DOMAINS = ("v.redd.it", "redgifs.com", "gfycat.com", "streamable.com",
                  "i.imgur.com")


def get_token(client_id: str, client_secret: str, *, user_agent: str = _UA) -> str:
    """client_credentials (app-only) OAuth token — kullanıcı şifresi gerekmez."""
    r = requests.post(_TOKEN_URL,
                      auth=requests.auth.HTTPBasicAuth(client_id, client_secret),
                      data={"grant_type": "client_credentials"},
                      headers={"User-Agent": user_agent}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def _unwrap(post: dict) -> dict:
    """Crosspost ise asıl gönderiye in (video/medya orada)."""
    parents = post.get("crosspost_parent_list") or []
    return parents[0] if parents else post


def _video_of(post: dict):
    """(video_url, duration, width, height) ya da None. Native + external kapsar."""
    p = _unwrap(post)
    rv = (p.get("media") or {}).get("reddit_video") or \
        (p.get("preview") or {}).get("reddit_video_preview") or {}
    if rv.get("fallback_url"):
        return (rv["fallback_url"].split("?")[0], rv.get("duration", 0),
                rv.get("width"), rv.get("height"))
    # external (redgifs/gfycat/streamable/imgur-gifv) — yt-dlp indirir
    dom = (p.get("domain") or "").lower()
    url = p.get("url", "")
    if any(dom.endswith(d) for d in _VIDEO_DOMAINS) or url.endswith(".gifv"):
        return (url, 0, None, None)
    if p.get("post_hint") in ("hosted:video", "rich:video"):
        return (url, 0, None, None)
    return None


def fetch_top(subreddit: str, token: str, *, t: str = "week", limit: int = 25,
              user_agent: str = _UA) -> list[dict]:
    """Bir subreddit'in 'top' gönderilerini ham döndürür (children[].data)."""
    r = requests.get(f"{_API}/r/{subreddit}/top",
                     params={"t": t, "limit": limit},
                     headers={"Authorization": f"bearer {token}",
                              "User-Agent": user_agent}, timeout=20)
    r.raise_for_status()
    return [c["data"] for c in r.json()["data"]["children"]]


def find_gems(client_id: str, client_secret: str, *, subreddits=None,
              t: str = "week", per_sub: int = 25, min_ups: int = 500,
              max_duration: int = 90, user_agent: str = _UA) -> list[dict]:
    """Cevher adaylarını bulur: SFW video, süre ≤max, upvote ≥min; upvote sıralı.

    Döner: [{sub, ups, comments, title, duration, width, height, orient,
             video_url, permalink, over18}] — indirme/onay çağırana bırakılır.
    """
    subs = subreddits or DEFAULT_SUBS
    token = get_token(client_id, client_secret, user_agent=user_agent)
    seen: set[str] = set()
    gems: list[dict] = []
    for sub in subs:
        try:
            posts = fetch_top(sub, token, t=t, limit=per_sub, user_agent=user_agent)
        except Exception as e:  # noqa: BLE001 — tek sub düşerse diğerleri sürsün
            log.info(f"  cevher: r/{sub} çekilemedi ({e})")
            continue
        for p in posts:
            if p.get("over_18") or p.get("ups", 0) < min_ups:
                continue
            vid = _video_of(p)
            if vid is None:
                continue
            url, dur, w, h = vid
            if dur and dur > max_duration:
                continue
            key = url or p.get("permalink", "")
            if key in seen:
                continue
            seen.add(key)
            gems.append({
                "sub": sub, "ups": p.get("ups", 0),
                "comments": p.get("num_comments", 0),
                "title": (p.get("title") or "").strip(),
                "duration": dur, "width": w, "height": h,
                "orient": ("DİKEY" if (h and w and h > w) else "yatay" if w else "?"),
                "video_url": url,
                "permalink": "https://www.reddit.com" + p.get("permalink", ""),
                "over18": p.get("over_18", False),
            })
        time.sleep(0.3)
    gems.sort(key=lambda g: -g["ups"])
    return gems
