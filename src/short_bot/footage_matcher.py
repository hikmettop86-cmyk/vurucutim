"""Beat başına Pexels footage eşleştirme + opsiyonel vision doğrulama."""
from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from short_bot.pexels import download_video as _download_video
from short_bot.pexels import search_videos as _search_videos

log = logging.getLogger(__name__)

MIN_CLIP_S = 2
MAX_CHECK = 5   # her sorguda en fazla kaç aday denenir


class _FootageVerdict(BaseModel):
    match: bool
    reason: str = ""


def verify_clip_matches(image_url: str, query: str, *, vision_call=None) -> bool:
    """Thumbnail'in sorguyu (konuyu) gösterip göstermediğini vision ile doğrular.

    ai33 için değil — OpenRouter/Claude vision (ör. Gemini Flash-Lite, ~$0.0001).
    ``vision_call`` yoksa ya da thumbnail yoksa True döner (arama sırasına güven).
    Ağ/model hatasında da True (footage üretimini bloklamamak için).
    """
    if not image_url or vision_call is None:
        return True
    import requests

    from short_bot.claude_cli import run_json
    thumb: Path | None = None
    try:
        r = requests.get(image_url, timeout=15)
        if r.status_code != 200 or not r.content:
            return True
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            tf.write(r.content)
            thumb = Path(tf.name)
        try:  # maliyeti dipte tutmak için ≤384px'e küçült
            from PIL import Image
            im = Image.open(thumb)
            im.thumbnail((384, 384))
            im.convert("RGB").save(thumb, "JPEG")
        except Exception:
            pass
        prompt = (
            f'Bu görüntü şu konuyu/nesneyi net biçimde gösteriyor mu: "{query}"?\n'
            f'GEVŞEK ol — konuyla açıkça ilişkiliyse yeterli. Tamamen alakasızsa '
            f'(ör. "asma köprü" istenip mutfak görüntüsü) false.\n'
            f'SADECE JSON: {{"match": true|false, "reason": "<kısa Türkçe>"}}'
        )
        v = run_json(prompt, _FootageVerdict, claude_path=vision_call.claude_path,
                     model=vision_call.model, backend=vision_call.backend,
                     api_key=vision_call.api_key, image_path=thumb,
                     retries=1, timeout_s=45)
        return bool(v.match)
    except Exception as e:
        log.warning(f"footage vision doğrulama hatası: {e}")
        return True
    finally:
        if thumb is not None:
            thumb.unlink(missing_ok=True)


@dataclass(frozen=True)
class FootageDeps:
    search_videos: Callable = _search_videos
    download_video: Callable = _download_video
    verify_footage: Callable = verify_clip_matches   # (image_url, query, *, vision_call) -> bool


def match_beat_clip(query: str, *, api_key: str, cache_dir: Path,
                    verify: bool = True, vision_call=None,
                    deps: FootageDeps | None = None) -> Path | None:
    """Sorguya uyan tek klibi indirip yolunu döndürür; bulunamazsa None.

    Vision doğrulama klibin THUMBNAIL'ı (poster) üstünde yapılır — mp4 değil.
    """
    d = deps or FootageDeps()
    cache_dir = Path(cache_dir)
    for orientation in ("portrait", "landscape"):
        cands = d.search_videos(query, api_key, max_results=MAX_CHECK,
                                orientation=orientation, page=1)
        cands = [c for c in cands if getattr(c, "duration_s", 0) >= MIN_CLIP_S]
        for c in cands:
            if verify and d.verify_footage is not None:
                thumb_url = getattr(c, "image", "") or c.url
                try:
                    ok = d.verify_footage(thumb_url, query, vision_call=vision_call)
                except Exception as e:
                    log.warning(f"footage vision doğrulama hatası: {e}")
                    ok = True   # doğrulama patlarsa arama sırasına güven
                if not ok:
                    continue
            clip = d.download_video(c.url, cache_dir)
            if clip is not None:
                return clip
    return None
