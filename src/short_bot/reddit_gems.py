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
from pydantic import BaseModel

log = logging.getLogger(__name__)

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_API = "https://oauth.reddit.com"
_UA = "shortbot-gemfinder/0.1"

# MİZAH (kaosdayi = genel kaos/komik). ÖLÇÜLDÜ 2026-07-19 (top?t=month, ups≥1000 VİDEO sayısı):
# eski liste hayvan-ağırlıklıydı (AnimalsBeingJerks 2 video); genel komik video-yoğun subler
# eklendi (therewasanattempt 79, funny 49, contagiouslaughter 57, WhatCouldGoWrong 26...).
DEFAULT_SUBS = [
    # Genel komik / beklenmedik / fail / kaos (video-yoğun, ölçüldü)
    "Unexpected", "funny", "WhatCouldGoWrong", "therewasanattempt", "instant_regret",
    "facepalm", "contagiouslaughter", "nonononoyes", "AbruptChaos", "maybemaybemaybe",
    "Wellthatsucks", "IdiotsInCars", "kidsarefuckingstupid", "holdmyredbull",
    "nextfuckinglevel", "interestingasfuck", "nevertellmetheodds",
    # Hayvan-komik (persona için)
    "AnimalsBeingDerps", "AnimalsBeingGeniuses", "funnycats", "FunnyAnimals", "likeus",
    "AnimalsBeingStupid",
]

# DUYGU kanalı havuzu (curated_tone='duygu'): dokunaklı/kurtarma/kavuşma. ÖLÇÜLDÜ 2026-07-19:
# eski 17-sub listenin YARISI RESİM-yoğun/ölüydü (rescuedogs/rescuecats/AnimalRescue/
# BeforeNAfterAdoption/Eyebleach/dogswithjobs/wholesomegifs/MadeMeCry ≈0 VİDEO!) → funnel'ı
# yanıltıyordu. Yalnız video-yoğun dokunaklı subler kaldı + Heartwarming(30)/wholesome(6) eklendi.
# Ton-uyum kapısı (judge_tone_fit) karışık sublerdeki (MadeMeSmile) komik klipleri zaten eler.
DEFAULT_DUYGU_SUBS = [
    "MadeMeSmile", "HumansBeingBros", "Heartwarming", "AnimalsBeingBros", "aww",
    "IllegallySmolCats", "AnimalsBeingGeniuses", "likeus", "wholesome", "rarepuppers",
]

# KARMA ('oh olsun') — hak edilmiş, TATMİN EDİCİ comeuppance video-yoğun sublar. Ciddi
# yaralanma/şiddet riski taşıyanlar (PublicFreakout vb.) BİLİNÇLİ olarak DIŞARIDA; kalan graphic
# klipler tone-fit/kalite/karma-skor kapılarında elenir (güvenlik).
DEFAULT_KARMA_SUBS = [
    "instant_regret", "instantkarma", "JusticeServed", "IdiotsInCars",
    "Whatcouldgowrong", "therewasanattempt", "facepalm", "Unexpected",
]

# İndirilebilir video kaynakları (yt-dlp bunları çözer).
# gfycat KALDIRILDI: servis 2023'te kapandı, tüm gfycat linkleri ölü. Listede durduğu
# sürece her taramada aday oluyor, indirilmeye çalışılıyor ve boşa yt-dlp çağrısı
# harcanıyordu (koşu 1339'da ölçüldü).
_VIDEO_DOMAINS = ("v.redd.it", "redgifs.com", "streamable.com", "i.imgur.com")
# RESİM uzantıları: i.imgur.com hem video (.gifv/.mp4) hem RESİM (.jpg/.png) barındırır.
# Domain eşleşmesi tek başına yetmiyordu — koşu 1339'da üç adayın ikisi .jpg'ydi ve
# 'klip indirilemedi' ile elendi (üstelik indirme hatası seen'e yazılmadığı için her
# koşuda yeniden deneniyorlardı).
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".avif")


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


def _thumb_of(post: dict) -> str:
    """Önizleme thumbnail'ı (vision temizlik/alaka kontrolü için; indirmeden ucuz)."""
    import html
    p = _unwrap(post)
    imgs = ((p.get("preview") or {}).get("images") or [])
    if imgs:
        u = (imgs[0].get("source") or {}).get("url", "")
        if u:
            return html.unescape(u)
    # .get(k, "") anahtar None DEĞERİYLE varsa None döner (default devreye girmez) →
    # None.startswith çöker. Reddit thumbnail'ı çoğu zaman None/'default'/'nsfw' olur.
    th = p.get("thumbnail") or ""
    return th if th.startswith("http") else ""


class DeadClipError(RuntimeError):
    """Klip KALICI olarak indirilemez (desteklenmeyen/kapanmış servis, silinmiş video).

    Çağıran bunu seen_clips'e 'gone' diye yazmalı — yoksa aynı ölü link HER taramada
    yeniden aday olup yeniden indirilmeye çalışılır (koşu 1339'da ölçüldü). Geçici
    hatalar (zaman aşımı, bağlantı, 5xx) bu sınıfa GİRMEZ: onlar tekrar denenmeli."""


# yt-dlp stderr'inde bu işaretler varsa hata KALICIDIR (tekrar denemenin faydası yok).
_DEAD_MARKERS = ("unsupported url", "video unavailable", "404", "not found",
                 "has been removed", "no longer available", "does not exist",
                 "account has been terminated", "private video")


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
    url = p.get("url") or ""      # None-güvenli (bkz. _thumb_of)
    # RESİM uzantısı → video DEĞİL (imgur aynı domainde ikisini de barındırır)
    if url.split("?")[0].lower().endswith(_IMAGE_EXTS):
        return None
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


def _rate_wait_s(r) -> float:
    """429 sonrası bekleme: Retry-After ya da X-Ratelimit-Reset (sn), [1,30]'a sıkıştır."""
    for h in ("Retry-After", "X-Ratelimit-Reset"):
        v = r.headers.get(h)
        if v:
            try:
                return min(30.0, max(1.0, float(v)))
            except ValueError:
                pass
    return 5.0


def _proactive_pace_s(r) -> float:
    """AKILLI (proaktif) pacing — Reddit'in KENDİ header'ından: kalan kota azsa reset'e doğru
    yavaşla, bolsa minimum. Sabit uyku yerine → 429'a hiç düşmeden mümkün olan en hızlı çekim."""
    try:
        remaining = float(r.headers.get("X-Ratelimit-Remaining", "100"))
        reset = float(r.headers.get("X-Ratelimit-Reset", "60"))
    except (ValueError, TypeError):
        return 0.4
    if remaining <= 2:
        return min(30.0, max(1.0, reset))              # kota bitti → reset'e kadar bekle
    if remaining <= 10:
        return min(3.0, reset / max(1.0, remaining))   # azalıyor → kalanı reset'e yay
    return 0.3                                          # bol → minimum


def _fetch_listing_paged(subreddit: str, token: str, listing: str, *, t: str = "month",
                         pages: int = 3, user_agent: str = _UA) -> list[dict]:
    """Bir subreddit listesini (top/hot) SAYFALAYARAK DERİN çeker (Reddit 'after' imleci,
    100/sayfa). find_gems'in 25-post sığ çekimini derinleştirir → funnel'daki 'kaynak yok'
    darboğazını açar (milyonlarca video var, biz sığ çekince aza düşüyordu). Reddit OAuth:
    100 item/istek, ~100 istek/dk — 17 sub × pages sayfa API sınırının çok altında."""
    out: list[dict] = []
    after: str | None = None
    for _ in range(max(1, pages)):
        params: dict = {"limit": 100, "raw_json": 1}
        if listing == "top":
            params["t"] = t
        if after:
            params["after"] = after
        r = None
        for _attempt in range(3):
            try:
                r = requests.get(f"{_API}/r/{subreddit}/{listing}", params=params,
                                 headers={"Authorization": f"bearer {token}",
                                          "User-Agent": user_agent}, timeout=20)
            except Exception:  # noqa: BLE001 — ağ hatası → bu sub'ı bırak
                r = None
                break
            if r.status_code == 429:   # Reddit RATE-LIMIT → header kadar bekle, TEKRAR DENE (veri kaybetme)
                time.sleep(_rate_wait_s(r))
                continue
            break
        if r is None or r.status_code != 200:
            break
        data = r.json().get("data", {})
        children = data.get("children", [])
        out.extend(c["data"] for c in children)
        after = data.get("after")
        if not after or not children:
            break
        time.sleep(_proactive_pace_s(r))   # AKILLI pacing: Reddit'in kalan-kota header'ına göre
    return out


def fetch_popular(client_id: str, client_secret: str, *, geo: str = "GLOBAL",
                  limit: int = 100, min_ups: int = 500, max_duration: int = 90,
                  listing: str = "hot", user_agent: str = _UA) -> list[dict]:
    """r/popular (tüm Reddit'te ANLIK trending, cross-sub) → video cevherleri. find_gems'in
    sabit subreddit listesi yerine trending feed'i tarar → bizim listede OLMAYAN sub'lardan
    da taze/yükselen klipler getirir. collect_pool'a EK keşif kaynağı; tona-skor + temizlik
    filtresi uygunluğu süzer. SFW + video + süre/upvote filtreli; find_gems ile AYNI şema.
    Ölçüldü 2026-07-18: hot ~30 uygun video/çekim (rising çok erken → 1)."""
    token = get_token(client_id, client_secret, user_agent=user_agent)
    params: dict = {"limit": min(100, max(1, limit)), "raw_json": 1}
    if geo:
        params["geo_filter"] = geo
    r = requests.get(f"{_API}/r/popular/{listing}", params=params,
                     headers={"Authorization": f"bearer {token}", "User-Agent": user_agent},
                     timeout=20)
    r.raise_for_status()
    posts = [c["data"] for c in r.json().get("data", {}).get("children", [])]
    seen: set[str] = set()
    gems: list[dict] = []
    for p in posts:
        if p.get("over_18") or p.get("ups", 0) < min_ups:
            continue
        built = _post_to_gem(p)
        if built is None:
            continue
        gem, url, dur = built
        if dur and dur > max_duration:
            continue
        key = url or p.get("permalink", "")
        if key in seen:
            continue
        seen.add(key)
        gems.append(gem)
    gems.sort(key=lambda g: -g["ups"])
    return gems


def find_gems(client_id: str, client_secret: str, *, subreddits=None,
              t: str = "week", per_sub: int = 25, min_ups: int = 500,
              max_duration: int = 90, pages: int = 3, listings=("top", "hot"),
              t_windows=None, user_agent: str = _UA) -> list[dict]:
    """Cevher adaylarını bulur: SFW video, süre ≤max, upvote ≥min; upvote sıralı.

    DERİN ÇEKİM (2026-07-19): her sub'dan SAYFALAYARAK ~pages×100 post × (top+hot) çeker —
    eski 25-post/sub sığ çekim funnel'ı daraltıp 'temiz cevher yok'a düşürüyordu (kaynak
    milyonlarca, biz aza bakıyorduk). ``per_sub`` artık yok sayılır (geriye-uyum). Reddit
    OAuth sınırı içinde (100 item/istek, ~100 istek/dk).

    Döner: [{sub, ups, comments, title, duration, width, height, orient,
             video_url, permalink, over18}] — indirme/onay çağırana bırakılır.
    """
    subs = subreddits or DEFAULT_SUBS
    token = get_token(client_id, client_secret, user_agent=user_agent)
    # PENCERE ROTASYONU: /top için birden çok zaman penceresi (month→year→all) — çağıran
    # elenen-hafızası büyüdükçe pencereyi genişletir → her koşu FARKLI/DAHA DERİN dilim keşfeder
    # (kullanıcı: 'aynılar geliyor'). t_windows verilmezse tek pencere (t). /hot her zaman taze.
    tws = list(t_windows) if t_windows else [t]
    seen: set[str] = set()
    gems: list[dict] = []
    for sub in subs:
        posts: list[dict] = []
        for _lst in listings:
            if _lst == "top":
                for _tw in tws:
                    posts += _fetch_listing_paged(sub, token, "top", t=_tw, pages=pages,
                                                  user_agent=user_agent)
            else:
                posts += _fetch_listing_paged(sub, token, _lst, pages=pages,
                                              user_agent=user_agent)
        if not posts:
            log.info(f"  cevher: r/{sub} çekilemedi/boş")
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
                "thumb": _thumb_of(p),
                "permalink": "https://www.reddit.com" + p.get("permalink", ""),
                "over18": p.get("over_18", False),
            })
        time.sleep(0.3)
    gems.sort(key=lambda g: -g["ups"])
    return gems


# Global keyword aramasında SUB-KISITLI ikinci tarama için video-zengin küratörlü havuz
# (kategori + duygu subreddit'lerinin birleşimi). Bu subreddit'lerde görsel oranı düşük,
# video yoğunluğu yüksek → keyword araması global'e ek olarak burada da tarayınca daha
# ÇOK VİDEO döner (Reddit araması BAŞLIK-metni eşler; bu subreddit'ler tema-yoğun).
VIDEO_RICH_SUBS = [
    "funny", "contagiouslaughter", "Unexpected", "Whatcouldgowrong", "AbruptChaos",
    "nextfuckinglevel", "interestingasfuck", "BeAmazed", "maybemaybemaybe",
    "oddlysatisfying", "instant_regret", "therewasanattempt", "aww", "MadeMeSmile",
    "HumansBeingBros", "AnimalsBeingBros", "nonononoyes", "holdmyredbull",
]


def _post_to_gem(p: dict):
    """Reddit post → cevher dict (video değilse/filtreye takılırsa None). find_gems ve
    search_gems AYNI şema; çağıran ayrıca over_18/min_ups/dedup uygular."""
    vid = _video_of(p)
    if vid is None:
        return None
    url, dur, w, h = vid
    return {
        "sub": p.get("subreddit", "?"), "ups": p.get("ups", 0),
        "comments": p.get("num_comments", 0),
        "title": (p.get("title") or "").strip(),
        "duration": dur, "width": w, "height": h,
        "orient": ("DİKEY" if (h and w and h > w) else "yatay" if w else "?"),
        "video_url": url,
        "thumb": _thumb_of(p),
        "permalink": "https://www.reddit.com" + p.get("permalink", ""),
        "over18": p.get("over_18", False),
    }, url, dur


def _collect_search(token, base, params, *, seen, gems, min_ups, max_duration,
                    pages, user_agent):
    """Bir arama endpoint'ini SAYFALAYARAK topla (Reddit 'after' imleci; sayfa=100).
    gems'e ekler (dedup: seen). Tek sayfa 100'de tavanlı → çok-sayfa daha çok video."""
    after = None
    for _ in range(max(1, pages)):
        p = dict(params)
        if after:
            p["after"] = after
        try:
            r = requests.get(base, params=p, timeout=20,
                             headers={"Authorization": f"bearer {token}",
                                      "User-Agent": user_agent})
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001 — bir sayfa düşerse eldekiyle devam
            log.info(f"  arama: sayfa çekilemedi ({e})")
            break
        data = r.json().get("data", {})
        children = data.get("children", [])
        for c in children:
            post = c.get("data", {})
            if post.get("over_18") or post.get("ups", 0) < min_ups:
                continue
            built = _post_to_gem(post)
            if built is None:
                continue
            gem, url, dur = built
            if dur and dur > max_duration:
                continue
            key = url or post.get("permalink", "")
            if key in seen:
                continue
            seen.add(key)
            gems.append(gem)
        after = data.get("after")
        if not after or not children:
            break


def search_gems(client_id: str, client_secret: str, query: str, *,
                t: str = "year", min_ups: int = 300, max_duration: int = 90,
                sort: str = "top", pages: int = 3, subreddits=None,
                user_agent: str = _UA) -> list[dict]:
    """GLOBAL + SUB-KISITLI Reddit keyword araması — panel MANUEL aramasında kullanılır.
    Reddit araması yapısal olarak sınırlı (BAŞLIK-metni eşler, video İÇERİĞİ değil; sayfa
    başına 100; ~yarısı görsel). Bunu üç kaldıraçla telafi eder:
      1) SAYFALAMA: ``pages`` sayfa (after imleci) → 100 yerine ~pages*100 ham sonuç.
      2) SUB-KISITLI ikinci tarama: ``subreddits`` (yoksa VIDEO_RICH_SUBS) içinde ara →
         görsel gürültüsü az, video yoğunluğu yüksek (tema-yoğun topluluklar).
      3) GENİŞ pencere: varsayılan t='year' (duygusal/komik içerik evergreen).
    İki tarama birleştirilip dedup'lanır. find_gems ile AYNI cevher şeması.
    """
    query = (query or "").strip()
    if not query:
        return []
    token = get_token(client_id, client_secret, user_agent=user_agent)
    seen: set[str] = set()
    gems: list[dict] = []
    base_params = {"q": query, "sort": sort, "t": t, "type": "link",
                   "limit": 100, "include_over_18": "off", "raw_json": 1}
    # 1) GLOBAL (tüm SFW Reddit), sayfalı
    _collect_search(token, f"{_API}/search", base_params, seen=seen, gems=gems,
                    min_ups=min_ups, max_duration=max_duration, pages=pages,
                    user_agent=user_agent)
    # 2) SUB-KISITLI (video-zengin havuz), sayfalı — restrict_sr=1 ile o subreddit'lerde ara
    subs = [s for s in (subreddits or VIDEO_RICH_SUBS) if s]
    if subs:
        sr = "+".join(list(dict.fromkeys(subs))[:25])   # Reddit çok-sub sınırı
        sr_params = dict(base_params); sr_params["restrict_sr"] = 1
        _collect_search(token, f"{_API}/r/{sr}/search", sr_params, seen=seen, gems=gems,
                        min_ups=min_ups, max_duration=max_duration, pages=pages,
                        user_agent=user_agent)
    gems.sort(key=lambda g: -g["ups"])
    return gems


# ── Vision eleme: hayvan mı + temiz mi (baked-in yazı/logo yok) ───────────────
class GemScreen(BaseModel):
    """Thumbnail vision yargısı — kürasyon ön-elemesi."""
    is_animal: bool = False        # ana özne hayvan mı (persona hayvan-odaklı)
    has_overlay_text: bool = False  # baked-in yazı/altyazı/logo/watermark VAR mı
    appealing: bool = False        # ilgi çekici/komik/tatmin edici bir an mı
    note: str = ""                 # kısa İngilizce tarif


_SCREEN_PROMPT = (
    "Bu, kısa bir video klibinin thumbnail'ı. Kürasyon için üç şeyi değerlendir:\n"
    "1) is_animal: ana ÖZNE bir HAYVAN mı? (insan/manzara/nesne ana özneyse false)\n"
    "2) has_overlay_text: görüntüye SONRADAN BİNDİRİLMİŞ yazı/altyazı/logo/watermark "
    "VAR mı? (doğal sahne yazısı değil — editörün eklediği metin/kaynak logosu). Emin "
    "değilsen true.\n"
    "3) appealing: ilgi çekici, komik ya da tatmin edici GÖRÜNEN bir an mı?\n"
    'SADECE JSON: {"is_animal": <bool>, "has_overlay_text": <bool>, '
    '"appealing": <bool>, "note": "<short English>"}'
)


def screen_gem(gem: dict, *, vision_call, timeout_s: int = 45):
    """Bir cevherin thumbnail'ını vision'la ele. Döner GemScreen ya da None (thumb yok/hata)."""
    import tempfile
    from pathlib import Path

    from short_bot.claude_cli import run_json
    url = gem.get("thumb", "")
    if not url:
        return None
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
        if r.status_code != 200 or not r.content:
            return None
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            tf.write(r.content)
            thumb = Path(tf.name)
    except Exception:  # noqa: BLE001
        return None
    try:
        return run_json(_SCREEN_PROMPT, GemScreen, claude_path=vision_call.claude_path,
                        model=vision_call.model, backend=vision_call.backend,
                        api_key=vision_call.api_key, image_path=thumb,
                        retries=1, timeout_s=timeout_s)
    except Exception as e:  # noqa: BLE001
        log.info(f"  cevher eleme vision hatası: {e}")
        return None
    finally:
        thumb.unlink(missing_ok=True)


def screen_gems(gems: list[dict], *, vision_call, max_check: int = 40,
                workers: int = 8) -> list[dict]:
    """Top-N cevheri paralel vision'la eler; HAYVAN + TEMİZ (yazısız) olanları döndürür.

    Her cevhere 'screen' alanı eklenir (GemScreen). Sıralama upvote korunur."""
    from concurrent.futures import ThreadPoolExecutor
    head = gems[:max_check]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        screens = list(ex.map(lambda g: screen_gem(g, vision_call=vision_call), head))
    out = []
    for g, s in zip(head, screens):
        if s is None:
            continue
        g = {**g, "screen": s}
        if s.is_animal and not s.has_overlay_text:
            out.append(g)
    return out


# ── Tek post çekme + klip indirme (SP3: onay → üretim) ──────────────────────
def fetch_post(url_or_permalink: str, client_id: str, client_secret: str,
               *, user_agent: str = _UA) -> dict | None:
    """Tek bir Reddit gönderisini permalink/URL'den çeker → gem dict (find_gems şeması).

    Kürate onayında kullanıcı bir permalink verdiğinde (ya da ızgaradan seçtiğinde)
    o postun güncel medya URL'sini + başlığını almak için. Video yoksa None."""
    from urllib.parse import urlparse
    token = get_token(client_id, client_secret, user_agent=user_agent)
    path = urlparse(url_or_permalink).path if url_or_permalink.startswith("http") \
        else url_or_permalink
    path = "/" + path.strip("/")
    r = requests.get(f"{_API}{path}", params={"raw_json": 1},
                     headers={"Authorization": f"bearer {token}",
                              "User-Agent": user_agent}, timeout=20)
    r.raise_for_status()
    data = r.json()
    children = (data[0] if isinstance(data, list) else data)["data"]["children"]
    if not children:
        return None
    post = children[0]["data"]
    p = _unwrap(post)
    vid = _video_of(post)
    if vid is None:
        return None
    url, dur, w, h = vid
    return {
        "sub": p.get("subreddit", ""), "ups": p.get("ups", 0),
        "comments": p.get("num_comments", 0), "title": (p.get("title") or "").strip(),
        "duration": dur, "width": w, "height": h,
        "orient": ("DİKEY" if (h and w and h > w) else "yatay" if w else "?"),
        "video_url": url, "thumb": _thumb_of(post),
        "permalink": "https://www.reddit.com" + p.get("permalink", ""),
        "over18": p.get("over_18", False),
    }


def fetch_top_comments(url_or_permalink: str, client_id: str, client_secret: str,
                       *, limit: int = 4, user_agent: str = _UA) -> list[str]:
    """Gönderinin EN ÜST yorumlarının metnini döndürür — izleyiciler videoyu AÇIKLAR.

    Vision tek storyboard'da aleti/olayı kaçırabiliyor (short 923: pipeti görmedi,
    'parmakla' dedi). Başlık + bu 'kalabalık açıklaması' olayın NE olduğunu anlamak için
    vision'a ALTERNATİF/tamamlayıcı gerçek sinyaldir. Hata/boşsa [] (fail-open)."""
    from urllib.parse import urlparse
    try:
        token = get_token(client_id, client_secret, user_agent=user_agent)
        path = urlparse(url_or_permalink).path if url_or_permalink.startswith("http") \
            else url_or_permalink
        path = "/" + path.strip("/")
        r = requests.get(f"{_API}{path}",
                         params={"raw_json": 1, "sort": "top", "limit": 20},
                         headers={"Authorization": f"bearer {token}",
                                  "User-Agent": user_agent}, timeout=20)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or len(data) < 2:
            return []
        out: list[str] = []
        for c in data[1]["data"]["children"]:
            if c.get("kind") != "t1":                 # yalnız yorum (t1), 'more' değil
                continue
            body = (c.get("data", {}).get("body") or "").strip()
            if (not body or body in ("[deleted]", "[removed]")
                    or len(body) < 15 or len(body) > 240):   # çok kısa/uzun ele
                continue
            out.append(" ".join(body.split()))         # newline/whitespace normalize
            if len(out) >= limit:
                break
        return out
    except Exception as e:  # noqa: BLE001 — yorum yoksa üretim sürsün
        log.info(f"  cevher: yorum çekilemedi ({e})")
        return []


def download_clip(video_url: str, out_path, *, user_agent: str = _UA) -> "Path":
    """Kürate klibi indir. v.redd.it fallback = doğrudan mp4 (video-only; orijinal ses
    zaten atılacak, Türkçe TTS basılacak). redgifs/streamable/gifv → yt-dlp.

    Döner out_path (Path). İndirilemezse RuntimeError (sessiz fallback yok)."""
    from pathlib import Path
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if "v.redd.it" in video_url or video_url.split("?")[0].endswith(".mp4"):
        r = requests.get(video_url, headers={"User-Agent": user_agent}, timeout=120)
        r.raise_for_status()
        if not r.content:
            raise RuntimeError(f"kürate: klip indirilemedi (boş yanıt): {video_url}")
        out_path.write_bytes(r.content)
        return out_path
    # external (redgifs/gfycat/streamable/imgur-gifv) → yt-dlp
    import subprocess
    try:
        subprocess.run(["yt-dlp", "-q", "-o", str(out_path), "-f",
                        "mp4/bestvideo+bestaudio/best", video_url],
                       capture_output=True, timeout=180, check=True)
    except FileNotFoundError as e:
        raise RuntimeError("kürate: yt-dlp kurulu değil (external klip indirilemez)") from e
    except subprocess.CalledProcessError as e:
        # KALICI mı GEÇİCİ mi: stderr'deki işarete bak. Kalıcıysa DeadClipError → çağıran
        # seen_clips'e yazar ve bu link bir daha aday olmaz; geçiciyse normal RuntimeError
        # (tekrar denensin, iyi klip haksız yere kara listeye girmesin).
        _err = (e.stderr or b"")
        _err = _err.decode("utf-8", "replace") if isinstance(_err, bytes) else str(_err)
        if any(m in _err.lower() for m in _DEAD_MARKERS):
            raise DeadClipError(
                f"kürate: klip kalıcı olarak indirilemiyor ({video_url}): "
                f"{_err.strip()[:160]}") from e
        raise RuntimeError(f"kürate: yt-dlp indirme başarısız: {e}") from e
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"kürate: klip indirilemedi: {video_url}")
    return out_path
