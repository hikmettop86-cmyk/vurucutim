"""Çoklu footage kaynağı: ortak protokol + Pexels/Pixabay."""
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
        # Reel 9:16 → dikey/kare footage tercih. Pixabay'in orientation param'ı
        # güvenilmez, o yüzden GERÇEK en/boy oranıyla filtreleriz: portrait pass'te
        # yatay (w>h) klipleri ATLA (cover-crop yatayı ağır keser → "kesik" görüntü).
        # Landscape pass (yedek) hepsini alır.
        want_portrait = (orientation == "portrait")
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
            try:  # bozuk tek bir hit tüm sayfayı düşürmesin
                if not isinstance(h, dict):
                    continue
                vids = h.get("videos", {}) or {}
                vd = vids.get("large") or vids.get("medium") or vids.get("small") or {}
                url = vd.get("url", "")
                if not url:
                    continue
                w, ht = int(vd.get("width", 0) or 0), int(vd.get("height", 0) or 0)
                if want_portrait and w and ht and w > ht:
                    continue   # yatay klibi portrait pass'te atla
                out.append(FootageCandidate(
                    url=url, duration_s=int(h.get("duration", 0) or 0),
                    image=str(vd.get("thumbnail", "") or ""),
                    source="pixabay", ident=str(h.get("id", ""))))
            except Exception:
                continue
        return out
    def download(self, cand, cache_dir):
        return _pexels_download(cand.url, cache_dir)   # düz HTTP GET; URL agnostik


def build_footage_sources(priority, *, pexels_key="", pixabay_key=""):
    """`priority` sırasına göre, anahtarı olan (available) kaynakları döndürür.

    Hiçbiri kullanılamıyorsa geriye-uyum için [PexelsSource(pexels_key)] döner.
    Tanınmayan kaynak adları (ör. eski config'lerdeki 'storyblocks' — 2026-07-16'da
    KALDIRILDI: yavaş Playwright kazıması + ücretli plan) sessizce atlanır.
    """
    reg = {"pexels": lambda: PexelsSource(pexels_key),
           "pixabay": lambda: PixabaySource(pixabay_key)}
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
