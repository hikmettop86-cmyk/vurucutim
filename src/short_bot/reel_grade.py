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

# KARANLIK KLİP KURTARMA — ve "kasten karanlık" olanı BOZMADAN.
#
# ÖLÇÜLDÜ (Almanca kanal, short 795, kare kare): videonun %29'u YAVG<40 (0.16) idi,
# TEPE NOKTASI dahil. Videonun en kritik anında ekran karanlıktı. Normal ±0.12 sınırı
# 0.11'lik bir klibi ancak 0.23'e çıkarır — hâlâ karanlık.
#
# AMA: "siyah zeminde parlayan mikroplar" gibi bir sahneyi kaldırmak onu GRİ BULAMACA
# çevirir; siyah zemin sanatın kendisidir. Ortalama parlaklık tek başına bu ikisini
# AYIRT EDEMEZ — ikisi de karanlıktır.
#
# AYRIM TEPE PARLAKLIKTA: mikroplu klipte PARLAK BİR ÖZNE VARDIR (peak yüksek).
# Kötü pozlanmış klipte HİÇBİR ŞEY parlak değildir (peak da düşük).
#
#   mikroplar/siyah zemin : luma 0.02  peak 0.98  → DOKUNMA (sanatsal)
#   kötü pozlanmış klip   : luma 0.11  peak 0.45  → KURTAR
DARK_FLOOR = 0.20            # bunun altı = karanlık
PEAK_FLOOR = 0.70            # tepe bunun ÜSTÜNDEYSE karanlık KASITLIDIR → dokunma
MAX_RESCUE_DELTA = 0.30      # kurtarma sınırı (normalin 2.5 katı)


def measure_levels(clip, ffmpeg_path: str = "ffmpeg") -> tuple[float, float]:
    """Klibin (ortalama, tepe) parlaklığı, 0-1. Okunamazsa (hedef, hedef) — fail-open:
    ölçemediğimiz klibe düzeltme UYGULAMAYIZ, bozmaktansa dokunma.

    TEPE ŞART: ortalama tek başına "siyah zeminde parlayan mikroplar" ile "kötü
    pozlanmış klip"i AYIRT EDEMEZ; ikisi de karanlıktır. Farkı tepe koyar.

    KLİBİN TAMAMINDAN ÖRNEKLE. Eskiden yalnız İLK 12 KARE ölçülüyordu — 30fps'de
    0,4 SANİYE. Karanlıktan açılan bir klip "zifiri siyah" ölçülür ve gereksiz yere
    kaldırılır; parlak başlayıp kararan bir klip ise hiç düzeltilmez.
    """
    try:
        # -v error KULLANMA: metadata=print INFO seviyesinde yazar, bastırılır.
        p = subprocess.run(
            [ffmpeg_path, "-i", str(clip),
             "-vf", "fps=2,signalstats,metadata=print",
             "-frames:v", "30", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30)
        avg = [float(m) for m in
               re.findall(r"lavfi\.signalstats\.YAVG=([\d.]+)", p.stderr)]
        peak = [float(m) for m in
                re.findall(r"lavfi\.signalstats\.YMAX=([\d.]+)", p.stderr)]
        if not avg:
            return GRADE_TARGET_LUMA, GRADE_TARGET_LUMA
        a = (sum(avg) / len(avg)) / 255.0
        pk = (sum(peak) / len(peak)) / 255.0 if peak else GRADE_TARGET_LUMA
        return a, pk
    except Exception as e:  # noqa: BLE001 — ölçüm hatası üretimi düşürmesin
        log.info(f"grade: parlaklık ölçülemedi ({clip}): {e}")
        return GRADE_TARGET_LUMA, GRADE_TARGET_LUMA


def measure_luma(clip, ffmpeg_path: str = "ffmpeg") -> float:
    """Yalnız ortalama parlaklık (geriye uyum)."""
    return measure_levels(clip, ffmpeg_path)[0]


def luma_delta(luma: float, peak: float | None = None) -> float:
    """Bu klibi ortak hedefe çekmek için parlaklık düzeltmesi.

    İKİ KADEMELİ SINIR:
      • Normal klip → ±MAX_BRIGHTNESS_DELTA.
      • KARANLIK **VE** TEPESİ DE SÖNÜK klip → MAX_RESCUE_DELTA. Böyle bir klipte
        hiçbir şey parlak değildir: kötü pozlanmıştır, sanat değildir. Ekranda siyah
        bir dikdörtgen görünür ve metin boşlukta yüzer.
        (ÖLÇÜLDÜ: bir videonun %29'u YAVG<40 çıktı, TEPE NOKTASI dahil.)

    KASTEN KARANLIK KORUNUR: tepesi PEAK_FLOOR üstündeyse (siyah zeminde parlayan
    mikroplar gibi) karanlık KASITLIDIR — normal sınırda kalır, gri bulamaca çevrilmez.

    ``peak`` verilmezse kurtarma UYGULANMAZ: emin olmadığımız klibi zorlamayız.
    """
    d = GRADE_TARGET_LUMA - luma
    kurtar = (peak is not None and luma < DARK_FLOOR and peak < PEAK_FLOOR)
    sinir = MAX_RESCUE_DELTA if kurtar else MAX_BRIGHTNESS_DELTA
    return max(-sinir, min(sinir, d))


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
    """Klibi ölç → ona özel normalize + ortak look. Kurtarılan klipleri LOGLAR."""
    luma, peak = measure_levels(Path(clip), ffmpeg_path)
    d = luma_delta(luma, peak)
    if luma < DARK_FLOOR:
        if peak < PEAK_FLOOR:
            log.info(f"  grade: KARANLIK klip kurtarıldı ({Path(clip).name}): "
                     f"luma {luma:.2f}, tepe {peak:.2f} → +{d:.2f}")
        else:
            log.info(f"  grade: karanlık ama tepesi parlak ({Path(clip).name}): "
                     f"luma {luma:.2f}, tepe {peak:.2f} → KASITLI sayıldı, "
                     f"normal sınır (+{d:.2f})")
    return grade_vf(d)
