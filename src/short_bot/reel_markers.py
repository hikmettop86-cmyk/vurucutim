"""Reel belirteçleri: vision konumuna göre per-segment marker seçimi (saf)."""
from __future__ import annotations
import hashlib

MARKER_TYPES = ("arrow", "ring", "pulse", "box", "spotlight", "underline")
MARKER_CONF_MIN = 0.55   # marker yalnız güvenle bulunmuş TEKİL nesnede çıkar


def _marker_worthy_segs(n_segs: int, frequency: str) -> list[int]:
    # reel_render.build_reel_overlay_html'deki arrow_segs mantığının aynısı:
    beat_segs = list(range(1, n_segs - 1))
    if frequency == "off":
        return []
    if frequency == "reveal":
        return beat_segs[1:2] or beat_segs[:1]
    return beat_segs


def build_markers(seg_positions, *, marker_kit, frequency="beats", seed=0) -> list[dict]:
    kit = tuple(marker_kit) or ("arrow",)
    worthy = set(_marker_worthy_segs(len(seg_positions), frequency))
    out = []
    for i, pos in enumerate(seg_positions):
        if i not in worthy:
            continue
        if not (getattr(pos, "found", False)
                and getattr(pos, "discrete", False)
                and getattr(pos, "confidence", 0.0) >= MARKER_CONF_MIN):
            continue
        h = int(hashlib.sha1(f"{seed}:mk:{i}".encode()).hexdigest(), 16)
        out.append({"seg": i, "type": kit[h % len(kit)],
                    "x": round(float(pos.x), 4), "y": round(float(pos.y), 4)})
    return out
