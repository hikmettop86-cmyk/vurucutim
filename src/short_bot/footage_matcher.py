"""Beat başına Pexels footage eşleştirme + opsiyonel vision doğrulama."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from short_bot.pexels import download_video as _download_video
from short_bot.pexels import search_videos as _search_videos

log = logging.getLogger(__name__)

MIN_CLIP_S = 2
MAX_CHECK = 5   # her sorguda en fazla kaç aday denenir


@dataclass(frozen=True)
class FootageDeps:
    search_videos: Callable = _search_videos
    download_video: Callable = _download_video
    verify_footage: Callable | None = None   # (url, query, vision_call) -> bool


def match_beat_clip(query: str, *, api_key: str, cache_dir: Path,
                    verify: bool = True, vision_call=None,
                    deps: FootageDeps | None = None) -> Path | None:
    """Sorguya uyan tek klibi indirip yolunu döndürür; bulunamazsa None."""
    d = deps or FootageDeps()
    cache_dir = Path(cache_dir)
    for orientation in ("portrait", "landscape"):
        cands = d.search_videos(query, api_key, max_results=MAX_CHECK,
                                orientation=orientation, page=1)
        cands = [c for c in cands if getattr(c, "duration_s", 0) >= MIN_CLIP_S]
        for c in cands:
            if verify and d.verify_footage is not None:
                try:
                    ok = d.verify_footage(c.url, query, vision_call=vision_call)
                except Exception as e:
                    log.warning(f"footage vision doğrulama hatası: {e}")
                    ok = True   # doğrulama patlarsa arama sırasına güven
                if not ok:
                    continue
            clip = d.download_video(c.url, cache_dir)
            if clip is not None:
                return clip
    return None
