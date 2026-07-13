"""Master renk grade — 12 alakasız stok klibi TEK BİR FİLM gibi okutur.

EN GÖRÜNÜR OTOMASYON PARMAK İZİ BUYDU. Pexels/Pixabay/Storyblocks'tan gelen klipler
farklı renk sıcaklığı, pozlama ve kontrasta sahip; klipten klibe renk ZIPLAMASI
"bunu bir script birleştirdi" diye bağırır. Şu ana kadar hiçbir renk işlemimiz yoktu.

İKİ AŞAMA — SIRA ÖNEMLİ:
  1. NORMALİZE (klip başına): parlaklığı ortak hedefe yaklaştır. ÖNCE bu olmalı,
     yoksa ortak grade uyumsuzluğu BÜYÜTÜR.
  2. LOOK (hepsine AYNI): grade + vignette + grain. Tutarlılık > zekâ; video başına
     TEK grade, klip başına DEĞİL.

Platform telafisi: YouTube transcode'u kontrast/doygunluğu yiyor, o yüzden hedeften
biraz FAZLA veriyoruz.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

GRADE_TARGET_LUMA = 0.45     # ortak parlaklık hedefi (0-1)
# Düzeltme SINIRLI: kasten karanlık bir sahneyi (siyah zeminde parlayan mikroplar)
# gri bir bulamaca çevirmek, renk zıplamasından beter olur.
MAX_BRIGHTNESS_DELTA = 0.12


def measure_luma(clip, ffmpeg_path: str = "ffmpeg") -> float:
    """Klibin ortalama parlaklığı (0-1). Okunamazsa hedefi döndür (fail-open:
    ölçemediğimiz klibe düzeltme UYGULAMAYIZ, bozmaktansa dokunma)."""
    try:
        # -v error KULLANMA: metadata=print INFO seviyesinde yazar, bastırılır.
        p = subprocess.run(
            [ffmpeg_path, "-i", str(clip),
             "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
             "-frames:v", "12", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30)
        vals = [float(m) for m in
                re.findall(r"lavfi\.signalstats\.YAVG=([\d.]+)", p.stderr)]
        if not vals:
            return GRADE_TARGET_LUMA
        return (sum(vals) / len(vals)) / 255.0
    except Exception as e:  # noqa: BLE001 — ölçüm hatası üretimi düşürmesin
        log.info(f"grade: parlaklık ölçülemedi ({clip}): {e}")
        return GRADE_TARGET_LUMA


def luma_delta(luma: float) -> float:
    """Bu klibi ortak hedefe çekmek için parlaklık düzeltmesi (sınırlı)."""
    d = GRADE_TARGET_LUMA - luma
    return max(-MAX_BRIGHTNESS_DELTA, min(MAX_BRIGHTNESS_DELTA, d))


def grade_vf(brightness_delta: float = 0.0) -> str:
    """Master grade filtre zinciri.

    - eq: kontrast/doygunluk + klibe özel parlaklık düzeltmesi. Platform transcode'u
      yediği için hedeften biraz FAZLA veriyoruz.
    - colorbalance: gölgelerde hafif teal, ışıklarda hafif sıcak — farklı kaynakları
      ortak bir sıcaklıkta buluşturan şey bu.
    - curves: siyahlar KALDIRILMIŞ (0'a ezilmemiş) + ışıklar yumuşatılmış → "dijital"
      görünmeyi kırar.
    - vignette + grain: sinema hissi. Grain fark edilirse fazladır; "gördüğünden çok
      hissettiğin doku" olmalı.
    """
    b = f"{brightness_delta:.3f}".rstrip("0").rstrip(".") or "0"
    return (
        f"eq=contrast=1.10:saturation=1.08:brightness={b},"
        "colorbalance=rs=-0.025:bs=0.045:rh=0.030:bh=-0.030,"
        "curves=all='0/0.02 0.5/0.5 1/0.97',"
        "vignette=PI/5,"
        "noise=alls=4:allf=t+u"
    )


def grade_for_clip(clip, ffmpeg_path: str = "ffmpeg") -> str:
    """Klibi ölç → ona özel normalize + ortak look."""
    return grade_vf(luma_delta(measure_luma(Path(clip), ffmpeg_path)))
