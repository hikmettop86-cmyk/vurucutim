"""Reel belirteçleri: vision konumuna göre ALT-KESİM başına marker seçimi (saf).

Eskiden marker SEGMENT başına üretiliyordu ve konum segmentin İLK klibinden
ölçülüyordu. Hızlı kesim açıkken bir segmentte 3 FARKLI klip gösterildiği için
marker, ölçülmediği kliplerin üstünde de çiziliyor ve BOŞLUĞU işaretliyordu
(gerçek şikâyet: arı videosunda kırmızı işaretçi havada duruyor).

Artık konum, gösterilen KLİBİN kendisinden ve o alt-kesimin gerçek başlangıç
saniyesinden ölçülür; marker yalnız o alt-kesim penceresinde görünür.
"""
from __future__ import annotations

import hashlib

MARKER_TYPES = ("arrow", "ring", "pulse", "box", "spotlight", "underline")
MARKER_CONF_MIN = 0.55   # marker yalnız güvenle bulunmuş TEKİL nesnede çıkar


def marker_worthy_segs(n_segs: int, frequency: str) -> list[int]:
    """Hangi segmentler marker alabilir (hook/kapanış ASLA: kart ekranı kaplar)."""
    beat_segs = list(range(1, n_segs - 1))
    if frequency == "off":
        return []
    if frequency == "reveal":
        return beat_segs[1:2] or beat_segs[:1]
    return beat_segs


# Geriye-uyum takma adı (eski çağıranlar/testler)
_marker_worthy_segs = marker_worthy_segs


def build_markers(subcuts, positions, *, marker_kit, frequency="beats",
                  seed=0) -> list[dict]:
    """Alt-kesim başına ölçülmüş konumlardan marker listesi üret.

    ``subcuts``   : [(segment_index, t0, t1), ...] — zaman sırasında
    ``positions`` : subcuts ile HİZALI SubjectPos listesi (o alt-kesimin KENDİ
                    klibinden, KENDİ başlangıç saniyesinden ölçülmüş)

    Segment başına EN FAZLA BİR marker: her alt-kesime koymak görsel gürültü olur.
    Aynı segmentte birden çok güvenli ölçüm varsa en YÜKSEK güvenli seçilir.

    Dönüş: [{"seg", "t0", "t1", "type", "x", "y"}, ...]
    """
    kit = tuple(marker_kit) or ("arrow",)
    n_segs = (max(si for si, _a, _b in subcuts) + 1) if subcuts else 0
    worthy = set(marker_worthy_segs(n_segs, frequency))

    best: dict[int, tuple] = {}   # seg -> (conf, t0, t1, x, y)
    for (si, t0, t1), pos in zip(subcuts, positions):
        if si not in worthy:
            continue
        conf = float(getattr(pos, "confidence", 0.0) or 0.0)
        if not (getattr(pos, "found", False) and getattr(pos, "discrete", False)
                and conf >= MARKER_CONF_MIN):
            continue
        cand = (conf, t0, t1, float(pos.x), float(pos.y))
        if si not in best or cand[0] > best[si][0]:
            best[si] = cand

    out = []
    for si in sorted(best):
        conf, t0, t1, x, y = best[si]
        h = int(hashlib.sha1(f"{seed}:mk:{si}".encode()).hexdigest(), 16)
        out.append({"seg": si, "t0": round(t0, 3), "t1": round(t1, 3),
                    "type": kit[h % len(kit)],
                    "x": round(x, 4), "y": round(y, 4)})
    return out
