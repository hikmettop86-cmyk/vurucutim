"""Asset resolution: download+blur RSS thumbnail; pick mood-matched music."""
from __future__ import annotations

import hashlib
import io
import random
from pathlib import Path

import requests
from PIL import Image, ImageFilter, UnidentifiedImageError


# Kart genişliği (px). `blur_radius` bu ölçüde tanımlıdır.
_KART_GENISLIK = 1080


def download_and_blur_thumb(
    url: str,
    cache_dir: Path,
    *,
    blur_radius: int = 0,
    timeout: int = 15,
    min_width: int = 600,
) -> Path | None:
    """Download a publisher og:image to cache. Crisp by default.

    blur_radius: 0 = no blur (default since v0.6.3). Templates that want
      bg blur should do it in CSS (filter: blur(...) on .bg-img), not bake
      it into the cached jpeg.
    min_width: reject thumbnails smaller than this so we don't upscale a
      300px og:image into 1080×1920 (which is what made publisher photos
      look mushy). Caller falls back to Pexels search when None returned.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    # ANAHTAR BLUR'U DA İÇERİR. İçermezse ayar SESSİZCE UYGULANMAZ: kanalın
    # blur değeri değiştirilir, ama daha önce indirilmiş her URL önbellekten
    # ESKİ (bulanıklaştırılmamış) hâliyle döner ve fark yalnız YENİ haberlerde
    # görülür. Yarısı bulanık yarısı net bir kanal, hiç bulanık olmayandan
    # daha kötüdür.
    key = hashlib.sha1(
        f"{url}|blur={blur_radius}".encode("utf-8")).hexdigest()[:16]
    cached = cache_dir / f"{key}.jpg"
    if cached.exists():
        return cached

    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "short-bot/0.1"})
    except requests.RequestException:
        return None
    if r.status_code != 200 or not r.content:
        return None

    try:
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
    except (UnidentifiedImageError, OSError):
        return None

    # Reject tiny thumbnails — upscaling a 320×180 og:image into 1080×1920
    # produces blocky/mushy frames. Let the pipeline fall back to Pexels.
    if img.width < min_width:
        return None

    if blur_radius > 0:
        # BULANIKLIK KART ÖLÇÜSÜNDE TANIMLIDIR, kaynak ölçüsünde değil.
        #
        # Görsel karta `background-size: cover` ile ölçeklenir. Ham çözünürlükte
        # uygulanan sabit bir yarıçap, ölçekten sonra kaynak boyutuna göre
        # BAMBAŞKA görünür: 600 piksellik bir görsel karta BÜYÜTÜLÜR (blur de
        # büyür), 2000 piksellik KÜÇÜLTÜLÜR (blur kaybolur). Aynı ayarla bir
        # video buğulu, öteki net çıkardı.
        #
        # Yarıçap `_KART_GENISLIK` referansına göre ölçeklenir; böylece
        # `blur_radius` "kartta kaç piksel" demektir ve kaynaktan bağımsızdır.
        etkin = blur_radius * (img.width / _KART_GENISLIK)
        img = img.filter(ImageFilter.GaussianBlur(radius=max(0.5, etkin)))
    img.save(cached, "JPEG", quality=92)
    return cached


_MOOD_FALLBACK = {"breaking": ["breaking", "neutral"],
                  "neutral": ["neutral"],
                  "upbeat": ["upbeat", "neutral"]}


def pick_music(music_root: Path, mood: str,
               channel_slug: str | None = None) -> Path:
    """Pick a random mp3 for the given mood.

    Lookup order:
      1. ``music_root/<channel_slug>/<mood>/*.mp3``   (per-channel + mood)
      2. ``music_root/<channel_slug>/*.mp3``          (per-channel, flat — drop any mp3 here)
      3. ``music_root/<mood>/*.mp3``                  (default per-mood)
      4. ``music_root/<fallback_mood>/*.mp3``         (e.g. breaking → neutral)

    A user opting in to per-channel music just creates ``assets/music/<slug>/``
    and drops mp3 files in. No subfolders required. Empty folder → default.
    """
    music_root = Path(music_root)
    fallback_moods = _MOOD_FALLBACK.get(mood, [mood, "neutral"])

    # 1 & 2: per-channel
    if channel_slug:
        ch_dir = music_root / channel_slug
        if ch_dir.is_dir():
            for try_mood in fallback_moods:
                d = ch_dir / try_mood
                if d.is_dir():
                    files = sorted(p for p in d.glob("*.mp3") if p.is_file())
                    if files:
                        return random.choice(files)
            flat = sorted(p for p in ch_dir.glob("*.mp3") if p.is_file())
            if flat:
                return random.choice(flat)

    # 3 & 4: default mood folders
    for try_mood in fallback_moods:
        d = music_root / try_mood
        if not d.is_dir():
            continue
        files = sorted(p for p in d.glob("*.mp3") if p.is_file())
        if files:
            return random.choice(files)
    raise FileNotFoundError(f"Mood '{mood}' (and fallback) için müzik bulunamadı: {music_root}")
