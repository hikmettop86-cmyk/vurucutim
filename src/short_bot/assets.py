"""Asset resolution: download+blur RSS thumbnail; pick mood-matched music."""
from __future__ import annotations

import hashlib
import io
import random
from pathlib import Path

import requests
from PIL import Image, ImageFilter, UnidentifiedImageError


def download_and_blur_thumb(
    url: str,
    cache_dir: Path,
    *,
    blur_radius: int = 8,
    timeout: int = 15,
) -> Path | None:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
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

    blurred = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    blurred.save(cached, "JPEG", quality=85)
    return cached


_MOOD_FALLBACK = {"breaking": ["breaking", "neutral"],
                  "neutral": ["neutral"],
                  "upbeat": ["upbeat", "neutral"]}


def pick_music(music_root: Path, mood: str) -> Path:
    music_root = Path(music_root)
    for try_mood in _MOOD_FALLBACK.get(mood, [mood, "neutral"]):
        d = music_root / try_mood
        if not d.is_dir():
            continue
        files = sorted(p for p in d.glob("*.mp3") if p.is_file())
        if files:
            return random.choice(files)
    raise FileNotFoundError(f"Mood '{mood}' (and fallback) için müzik bulunamadı: {music_root}")
