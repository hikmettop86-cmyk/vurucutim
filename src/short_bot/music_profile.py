"""Müziği anlatıma göre OTOMATİK dengele: girişi atla, seviyeyi ölç, yerleştir.

İKİ GERÇEK HATA:

1. HER PARÇAYI 0:00'DAN BAŞLATIYORDUK. Stok müziklerin çoğu yavaş bir kurulumla
   açılıyor — ölçüldü, `571.mp3` tam gücüne 60 SANİYEDE ulaşıyor (0sn: -55.7 dB →
   60sn: -12.4 dB). 30 saniyelik bir shorts yalnız o sessiz girişi kullanıyor:
   gerçek videoda müzik konuşmanın 37 dB ALTINDA kaldı, yani hiç duyulmadı.

2. SEVİYE KULLANICIYA BIRAKILMIŞTI. `music_volume` bir ÇARPANDI: kanal başına elle
   tutturulması gerekiyordu. Ama doğru çarpan parçaya göre değişir — kütüphanede
   24.9 dB'lik yayılım var (-30.5 → -5.6 LUFS). Aynı ayar bir videoda müziği yok
   ediyor, ötekinde bağırtıyor. Kullanıcının bunu bilmesinin imkânı yok.

ÇÖZÜM KAPALI DÖNGÜ: anlatımın seviyesini de ölçüyoruz ve müziği ONA GÖRE
yerleştiriyoruz. Parça hangisi olursa olsun, müzik konuşmanın sabit bir mesafe
altına oturur. `music_volume` artık seviyeyi BELİRLEMEZ — yalnız isteğe bağlı bir
dokunuştur (nötr = 0.30, ReelConfig varsayılanı).
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Müzik konuşmanın bu kadar ALTINA oturur (ducking'den ÖNCE). Ölçülerek seçildi:
# bu değerle müzik duraklamada konuşmanın ~12-14 dB altında duyuluyor — var ama
# bastırmıyor. Daha azı anlatımı boğuyor, daha fazlası müziği yok ediyor.
MUSIC_UNDER_SPEECH_DB = -11.0
# Video en fazla bu kadar sürüyor — müziğin seviyesi YALNIZ bu pencerede ölçülmeli.
USED_WINDOW_S = 45.0
# Parça "tam enerjide" sayılır: zirvenin bu kadar altına kadar.
INTRO_TOL_LU = 6.0
# Girişi sonsuza kadar atlamayız: uzun kurulan parçada müzik hiç başlamaz.
MAX_INTRO_SKIP_S = 40.0
# music_volume'un NÖTR değeri (ReelConfig varsayılanı). Kanal bundan saparsa
# aradaki fark bir DOKUNUŞ olarak uygulanır — ama seviyeyi artık ölçüm belirler.
NEUTRAL_MUSIC_VOLUME = 0.30
# Dokunuş sınırı: eski/yanlış ayarlar dengeyi BOZAMASIN (0.1 → -9.5 dB olurdu).
MAX_TRIM_DB = 4.0

_M = re.compile(r"t:\s*([\d.]+)\s.*?M:\s*(-?[\d.]+|-inf)")


@dataclass(frozen=True)
class MusicProfile:
    start_s: float     # parçada nereden başlanacak (sessiz giriş atlanır)
    lufs: float        # KULLANILAN bölümün seviyesi (parçanın bütününün değil)


def loudness_curve(path: Path, ffmpeg_path: str = "ffmpeg") -> list[tuple[float, float]]:
    """(zaman, anlık yükseklik) eğrisi — tek ebur128 geçişiyle."""
    p = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-i", str(path), "-af", "ebur128",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    out: list[tuple[float, float]] = []
    for m in _M.finditer(p.stderr or ""):
        if m.group(2) == "-inf":
            continue
        out.append((float(m.group(1)), float(m.group(2))))
    return out


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    return s[len(s) // 2]


def speech_lufs(path: Path, ffmpeg_path: str = "ffmpeg") -> float | None:
    """Anlatımın KONUŞMA seviyesi.

    Medyan alınır çünkü ortalama, cümle aralarındaki sessizlikle aşağı çekilir —
    biz konuşmanın kendisinin ne kadar gür olduğunu istiyoruz.
    """
    c = loudness_curve(Path(path), ffmpeg_path)
    vals = [v for _, v in c if v > -50]        # sessizliği ele
    return _median(vals) if vals else None


def profile_from_curve(curve: list[tuple[float, float]]) -> MusicProfile:
    if not curve:
        return MusicProfile(0.0, MUSIC_UNDER_SPEECH_DB)
    vals = sorted(v for _, v in curve)
    # "Tam enerji" = 90. yüzdelik (tek bir zirve tepesi ölçümü kaçırmasın).
    full = vals[int(len(vals) * 0.9)]
    start = 0.0
    for t, v in curve:
        if v >= full - INTRO_TOL_LU:
            start = min(t, MAX_INTRO_SKIP_S)
            break
    # Seviye, videonun GERÇEKTEN duyduğu pencereden ölçülür. Parçanın bütününe
    # bakmak yanıltır: sessiz girişli bir parçanın bütünü "gür" ölçülür ve
    # normalize onu daha da kısar (gerçek hata: 571.mp3).
    used = [v for t, v in curve if start <= t <= start + USED_WINDOW_S]
    return MusicProfile(round(start, 2), round(_median(used or [v for _, v in curve]), 2))


def music_gain_db(profile: MusicProfile, speech: float | None,
                  music_volume: float = NEUTRAL_MUSIC_VOLUME) -> float:
    """Müziği anlatımın MUSIC_UNDER_SPEECH_DB kadar altına oturtan kazanç.

    Anlatım ölçülemezse (whisper/ebur128 patlarsa) müzik hedef LUFS'a normalize
    edilir — parçalar arası yayılım yine kapanır, yalnız anlatıma kilitlenmez.
    """
    hedef = (speech + MUSIC_UNDER_SPEECH_DB) if speech is not None \
        else MUSIC_UNDER_SPEECH_DB - 2.0
    gain = hedef - profile.lufs
    # Kanal ayarı artık seviyeyi BELİRLEMİYOR, yalnız dokunuyor — ve dokunuş
    # sınırlı: eski ayarlar (0.1 → -9.5 dB) dengeyi bozmasın.
    if music_volume > 0 and abs(music_volume - NEUTRAL_MUSIC_VOLUME) > 1e-6:
        trim = 20.0 * math.log10(music_volume / NEUTRAL_MUSIC_VOLUME)
        gain += max(-MAX_TRIM_DB, min(MAX_TRIM_DB, trim))
    return round(gain, 2)


def profile_music(path: Path, *, ffmpeg_path: str = "ffmpeg",
                  cache_path: Path | None = None) -> MusicProfile:
    """Parçanın giriş noktası + kullanılan bölümünün seviyesi. Diske önbelleklenir
    (ebur128 geçişi ~2-3sn; her videoda tekrarlamanın anlamı yok)."""
    key = str(Path(path).resolve())
    cache: dict = {}
    if cache_path and Path(cache_path).exists():
        try:
            cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    hit = cache.get(key)
    if isinstance(hit, dict) and "start_s" in hit and "lufs" in hit:
        return MusicProfile(float(hit["start_s"]), float(hit["lufs"]))

    prof = profile_from_curve(loudness_curve(Path(path), ffmpeg_path))
    if cache_path:
        cache[key] = {"start_s": prof.start_s, "lufs": prof.lufs}
        try:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            Path(cache_path).write_text(json.dumps(cache, ensure_ascii=False),
                                        encoding="utf-8")
        except Exception:
            pass   # önbellek KOZMETİK — yazılamazsa üretim sürer
    return prof
