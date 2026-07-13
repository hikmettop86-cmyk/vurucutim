"""Özne-farkında çerçeveleme + Ken Burns hareketi (saf fonksiyonlar).

İKİ KUSURU KAPATIR:

1. APTAL MERKEZ-CROP. 16:9 stok klibi 9:16'ya kırparken hep MERKEZDEN kesiyorduk —
   araştırma bunu otomatik faceless videonun "1 numaralı görsel ele veren işareti"
   diye adlandırıyor: özne kadrajın kenarındaysa yarısı kesiliyor. Oysa özne
   konumunu ZATEN BİLİYORUZ (``locate_subject``); onu yalnız marker'da kullanıyorduk.

2. HER KLİPTE AYNI HAREKET. Tek bir sabit zoom-push her klipte tekrarlanınca
   KENDİSİ bir örüntü olur — tam da kırmaya çalıştığımız otomasyon parmak izi.
   Hareket klip başına değişir (deterministik: aynı seed → aynı video).
"""
from __future__ import annotations

import hashlib

# Hareket havuzu. HİÇBİRİ SABİT DEĞİL: tamamen sabit kare "slayt gösterisi" okunur
# ve beyin "ucuz" diye işaretler. Zoom aralığı dar: aşırı zoom pikselleştirir.
KEN_BURNS_MOVES = (
    {"name": "push_in",   "z_start": 1.00, "z_end": 1.10, "pan": 0.0},
    {"name": "pull_out",  "z_start": 1.12, "z_end": 1.02, "pan": 0.0},
    {"name": "drift_r",   "z_start": 1.06, "z_end": 1.06, "pan": 0.05},
    {"name": "drift_l",   "z_start": 1.06, "z_end": 1.06, "pan": -0.05},
    {"name": "push_pan",  "z_start": 1.02, "z_end": 1.12, "pan": 0.03},
)

# Özneyi kadrajın TAM kenarına dayamayız: nefes payı bırak (kompozisyon).
SUBJECT_BIAS = 0.85


def crop_x(*, iw: int, ow: int, subject_x: float | None) -> int:
    """9:16 kırpma penceresinin yatay başlangıcı.

    ``subject_x``: öznenin normalize yatay konumu (0=sol, 1=sağ). None → MERKEZ
    (eski davranış; konum bilinmiyorsa tahmin yürütme).
    """
    room = max(0, iw - ow)
    if room == 0:
        return 0
    center = room // 2
    if subject_x is None:
        return center
    sx = min(1.0, max(0.0, float(subject_x)))
    # Öznenin merkezini kadrajın ortasına getir, sonra kenara dayanmasın diye
    # merkeze doğru biraz geri çek (SUBJECT_BIAS).
    want = sx * iw - ow / 2
    x = center + (want - center) * SUBJECT_BIAS
    return int(min(room, max(0, round(x))))


def ken_burns(*, seed: int, index: int) -> dict:
    """Bu klibin hareketi. Deterministik (aynı seed+index → aynı hareket)."""
    h = int(hashlib.sha1(f"{seed}:kb:{index}".encode()).hexdigest(), 16)
    return dict(KEN_BURNS_MOVES[h % len(KEN_BURNS_MOVES)])


def ken_burns_vf(move: dict, *, w: int, h: int, fps: int, frames: int,
                 subject_x: float | None = None) -> str:
    """Ken Burns hareketini zoompan filtresine çevir.

    zoompan kırpma penceresini TAMSAYIYA yuvarladığı için yavaş push'larda 1 piksel
    titrer; kaynağı ÖNCEDEN büyütmek bunu büyük ölçüde giderir (çağıran scale'ler).
    """
    n = max(1, frames)
    z0, z1 = move["z_start"], move["z_end"]
    zexpr = f"{z0:g}+({z1 - z0:g})*on/{n}"
    # Pan: kadraj ortasından başlayıp yatayda kayar; özne biliniyorsa ONUN etrafında.
    sx = 0.5 if subject_x is None else min(1.0, max(0.0, float(subject_x)))
    x0 = f"(iw-iw/zoom)*{sx:g}"
    xexpr = f"{x0}+(iw-iw/zoom)*({move['pan']:g})*on/{n}"
    return (f"zoompan=z='{zexpr}':x='{xexpr}':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={w}x{h}:fps={fps}")
