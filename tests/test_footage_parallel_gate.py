"""Vision kapısı adayları PARALEL yargılamalı — sıralı yargı üretimi boğuyor.

GERÇEK ÖLÇÜM (short_id=747): 161 vision çağrısı, her biri ~3sn, HEPSİ SIRALI →
footage aşaması 832 saniye = üretimin %82'si, toplam 16.9 dakika.

Vision DOĞRULUĞU maliyetten önemli (kullanıcı kararı) — ama aynı doğruluğu paralel
çağrılarla 3-4 kat hızlı alabiliriz. Çağrı SAYISI aynı kalır, yalnız BEKLEME
üst üste biner.

Sözleşme KORUNMALI: kabul edilen klip, arama sırasındaki İLK uygun aday olmalı
(paralellik sırayı bozmamalı) — yoksa aynı sorgu her koşuda farklı klip getirir.
"""
from pathlib import Path

from short_bot.footage_matcher import (FootageDeps, _seen_key,
                                       match_beat_clip)
from short_bot.footage_sources import FootageCandidate


class _Src:
    name = "stub"

    def __init__(self, cands):
        self._cands = cands
        self.downloaded = []

    def available(self):
        return True

    def search(self, q, *, max_results, orientation):
        return self._cands if orientation == "portrait" else []

    def download(self, cand, cache_dir):
        self.downloaded.append(cand.url)
        p = Path(cache_dir) / cand.url.split("/")[-1]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"mp4")
        return p


def _cands(*names):
    return [FootageCandidate(url=f"https://x/{n}.mp4", image=f"https://x/{n}.jpg",
                             duration_s=10) for n in names]


def test_candidates_are_judged_concurrently(tmp_path):
    """Aynı partideki adaylar AYNI ANDA vision'a gitmeli."""
    import threading
    import time

    src = _Src(_cands("a", "b", "c", "d"))
    inflight = {"now": 0, "max": 0}
    lock = threading.Lock()

    def verify(url, query, **kw):
        with lock:
            inflight["now"] += 1
            inflight["max"] = max(inflight["max"], inflight["now"])
        time.sleep(0.05)          # vision çağrısını taklit et
        with lock:
            inflight["now"] -= 1
        return False              # hiçbiri geçmesin → hepsi yargılansın

    d = FootageDeps(sources=[src], verify_footage=verify)
    match_beat_clip("q", cache_dir=tmp_path, verify=True, vision_call=object(),
                    deps=d, seen={})
    assert inflight["max"] > 1, (
        f"adaylar SIRALI yargılandı (en fazla {inflight['max']} eşzamanlı) — "
        f"161 çağrı × 3sn = 8 dakika bekleme")


def test_first_matching_candidate_in_search_order_wins(tmp_path):
    """Paralellik SIRAYI bozmamalı: 'b' ve 'c' geçse bile 'b' seçilmeli.

    Yoksa aynı sorgu her koşuda farklı klip getirir (deterministiklik kaybı).
    """
    src = _Src(_cands("a", "b", "c"))

    def verify(url, query, **kw):
        return "/b." in url or "/c." in url

    d = FootageDeps(sources=[src], verify_footage=verify)
    clip = match_beat_clip("q", cache_dir=tmp_path, verify=True,
                           vision_call=object(), deps=d, seen={})
    assert clip is not None and clip.name == "b.mp4"


def test_only_the_winner_is_downloaded(tmp_path):
    """Paralel YARGI ≠ paralel İNDİRME. Sadece kazanan indirilir (bant genişliği)."""
    src = _Src(_cands("a", "b", "c"))
    d = FootageDeps(sources=[src], verify_footage=lambda u, q, **kw: "/c." in u)
    match_beat_clip("q", cache_dir=tmp_path, verify=True, vision_call=object(),
                    deps=d, seen={})
    assert src.downloaded == ["https://x/c.mp4"]


def test_cached_verdicts_still_skip_the_vision_call(tmp_path):
    """Önbellek paralel yolda da çalışmalı — aynı aday iki kez yargılanmaz."""
    judged = []
    src = _Src(_cands("a", "b"))

    def verify(url, query, *, seen=None, **kw):
        k = _seen_key(query, url)
        if seen is not None and k in seen:
            return seen[k]
        judged.append(url)
        if seen is not None:
            seen[k] = False
        return False

    d = FootageDeps(sources=[src], verify_footage=verify)
    seen: dict = {}
    match_beat_clip("q", cache_dir=tmp_path, verify=True, vision_call=object(),
                    deps=d, seen=seen)
    n = len(judged)
    match_beat_clip("q", cache_dir=tmp_path, verify=True, vision_call=object(),
                    deps=d, seen=seen)
    assert len(judged) == n, "önbellekteki aday yeniden yargılandı"
