"""Müziğin GİRİŞİNİ atla ve seviyesini eşitle.

GERÇEK HATA: her parçayı 0:00'dan başlatıyorduk. Ama stok müziklerin çoğu yavaş
bir kurulumla açılıyor — ölçüldü, `571.mp3` tam gücüne 60 SANİYEDE ulaşıyor
(0sn: -55.7 dB → 30sn: -21.0 dB → 60sn: -12.4 dB). 30 saniyelik bir shorts ise
parçanın yalnız o sessiz girişini kullanıyor. Sonuç: müzik videoda DUYULMUYORDU
(gerçek koşuda konuşmanın 37 dB altındaydı; olması gereken ~12 dB).

Üstelik kütüphanede 24.9 dB'lik seviye yayılımı var (-30.5 → -5.6 LUFS): aynı
ayarla bir video sessiz, öteki bağıran müzikle çıkıyor.

ÇÖZÜM İKİ PARÇALI:
  1. GİRİŞİ ATLA — parçanın tam enerjiye ulaştığı ana atla.
  2. SEVİYEYİ EŞİTLE — ama parçanın TAMAMINA göre değil, videonun GERÇEKTEN
     KULLANDIĞI bölüme göre. Bütüne göre normalize etmek işe yaramaz: sessiz
     girişli bir parçanın bütünü "gür" ölçülür ve normalize onu daha da kısar.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Anlatım mikste ~-16 dB oturuyor. Müziği burada eşitleyip kanal ayarındaki
# music_volume ile kısmak, ducking'le birlikte "duyulur ama bastırmaz" veriyor
# (ölçüldü: vol=0.3 ile duraklamada konuşmanın ~12 dB altı).
MUSIC_TARGET_LUFS = -16.0
# Video en fazla bu kadar sürüyor — seviye ölçümü YALNIZ bu pencereye bakmalı.
USED_WINDOW_S = 45.0
# Parça "tam enerjide" sayılır: zirvenin bu kadar altına kadar.
INTRO_TOL_LU = 6.0
# Girişi sonsuza kadar atlamayız: uzun süre kurulan parçada müzik hiç başlamaz.
MAX_INTRO_SKIP_S = 40.0

_M = re.compile(r"t:\s*([\d.]+)\s.*?M:\s*(-?[\d.]+|-inf)")


@dataclass(frozen=True)
class MusicProfile:
    start_s: float     # parçada nereden başlanacak
    gain_db: float     # kullanılan bölümü hedefe getiren kazanç


def loudness_curve(path: Path, ffmpeg_path: str = "ffmpeg") -> list[tuple[float, float]]:
    """(zaman, anlık yüksekliği) eğrisi — tek geçişte ebur128 ile."""
    p = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    out: list[tuple[float, float]] = []
    for m in _M.finditer(p.stderr or ""):
        t, v = m.group(1), m.group(2)
        if v == "-inf":
            continue
        out.append((float(t), float(v)))
    return out


def profile_from_curve(curve: list[tuple[float, float]]) -> MusicProfile:
    if not curve:
        return MusicProfile(0.0, 0.0)
    vals = sorted(v for _, v in curve)
    # "Tam enerji" = 90. yüzdelik (tek bir zirve tepesi ölçümü kaçırmasın).
    full = vals[int(len(vals) * 0.9)]
    start = 0.0
    for t, v in curve:
        if v >= full - INTRO_TOL_LU:
            start = min(t, MAX_INTRO_SKIP_S)
            break
    # Kazanç, videonun GERÇEKTEN kullandığı pencereye göre — bütüne göre değil.
    used = [v for t, v in curve if start <= t <= start + USED_WINDOW_S]
    if not used:
        used = [v for _, v in curve]
    used.sort()
    medyan = used[len(used) // 2]
    return MusicProfile(round(start, 2), round(MUSIC_TARGET_LUFS - medyan, 2))


def profile_music(path: Path, *, ffmpeg_path: str = "ffmpeg",
                  cache_path: Path | None = None) -> MusicProfile:
    """Parçanın giriş atlama noktası + kazancı. Sonuç diske önbelleklenir
    (ebur128 geçişi ~2-3sn; her videoda tekrarlamanın anlamı yok)."""
    key = str(Path(path).resolve())
    cache: dict = {}
    if cache_path and Path(cache_path).exists():
        try:
            cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    hit = cache.get(key)
    if isinstance(hit, dict) and "start_s" in hit and "gain_db" in hit:
        return MusicProfile(float(hit["start_s"]), float(hit["gain_db"]))

    prof = profile_from_curve(loudness_curve(Path(path), ffmpeg_path))
    if cache_path:
        cache[key] = {"start_s": prof.start_s, "gain_db": prof.gain_db}
        try:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            Path(cache_path).write_text(json.dumps(cache, ensure_ascii=False),
                                        encoding="utf-8")
        except Exception:
            pass   # önbellek KOZMETİK — yazılamazsa üretim sürer
    return prof
