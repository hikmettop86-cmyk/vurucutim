"""Çoklu footage kaynağı: ortak protokol + Pexels/Pixabay (+ Faz 2 Storyblocks)."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

import requests
from pydantic import BaseModel

from short_bot.pexels import (PexelsCandidate, download_video as _pexels_download,
                              search_videos as _pexels_search)

log = logging.getLogger(__name__)


class FootageCandidate(BaseModel):
    url: str
    duration_s: int = 0
    image: str = ""
    source: str = ""
    ident: str = ""


@runtime_checkable
class FootageSource(Protocol):
    name: str
    def available(self) -> bool: ...
    def search(self, query: str, *, max_results: int, orientation: str) -> list[FootageCandidate]: ...
    def download(self, cand: FootageCandidate, cache_dir: Path) -> "Path | None": ...


class PexelsSource:
    name = "pexels"
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or ""
    def available(self) -> bool:
        return bool(self.api_key)
    def search(self, query, *, max_results, orientation):
        out = []
        for c in _pexels_search(query, self.api_key, max_results=max_results,
                                orientation=orientation, page=1):
            out.append(FootageCandidate(url=c.url, duration_s=c.duration_s,
                                        image=c.image, source="pexels", ident=c.url))
        return out
    def download(self, cand, cache_dir):
        return _pexels_download(cand.url, cache_dir)


class PixabaySource:
    name = "pixabay"
    _ENDPOINT = "https://pixabay.com/api/videos/"
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or ""
    def available(self) -> bool:
        return bool(self.api_key)
    def search(self, query, *, max_results, orientation):
        # Pixabay yatay/dikey: 'all' güvenli (reel cover-crop yapıyor zaten)
        try:
            r = requests.get(self._ENDPOINT, timeout=15, params={
                "key": self.api_key, "q": query, "per_page": max(3, min(50, max_results)),
                "safesearch": "true", "video_type": "film"})
            if r.status_code != 200:
                return []
            hits = (r.json() or {}).get("hits", []) or []
        except Exception as e:
            log.warning(f"pixabay arama hatası: {e}")
            return []
        out = []
        for h in hits:
            vids = h.get("videos", {}) or {}
            vd = vids.get("large") or vids.get("medium") or vids.get("small") or {}
            url = vd.get("url", "")
            if not url:
                continue
            out.append(FootageCandidate(
                url=url, duration_s=int(h.get("duration", 0) or 0),
                image=str(vd.get("thumbnail", "") or ""),
                source="pixabay", ident=str(h.get("id", ""))))
        return out
    def download(self, cand, cache_dir):
        return _pexels_download(cand.url, cache_dir)   # düz HTTP GET; URL agnostik


def build_footage_sources(priority, *, pexels_key="", pixabay_key="",
                          storyblocks_session=None):
    """`priority` sırasına göre, anahtarı olan (available) kaynakları döndürür.

    Hiçbiri kullanılamıyorsa geriye-uyum için [PexelsSource(pexels_key)] döner.
    ``storyblocks_session`` yoksa Storyblocks (available()=False) atlanır.
    """
    def _mk_storyblocks():
        # Fonksiyon-içi import: footage_sources import edilirken playwright/
        # storyblocks_source YÜKLENMESIN (circular + tembel tarayıcı).
        from short_bot.storyblocks_source import StoryblocksSource
        return StoryblocksSource(session_path=storyblocks_session)

    reg = {"pexels": lambda: PexelsSource(pexels_key),
           "pixabay": lambda: PixabaySource(pixabay_key),
           "storyblocks": _mk_storyblocks}
    out = []
    for name in (priority or ["pexels"]):
        mk = reg.get(name)
        if mk:
            s = mk()
            if s.available():
                out.append(s)
    if not out:
        out = [PexelsSource(pexels_key)]
    return out
