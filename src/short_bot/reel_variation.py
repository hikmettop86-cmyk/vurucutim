"""Reel varyasyon motoru: per-video deterministik VariationProfile.

Otomasyon-tespitinden kaçınma: her video farklı layout/hook-açı/vurgu/geçiş
alır. Deterministik (aynı seed → aynı profil), saf fonksiyon.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

LAYOUTS = ("classic", "lower_left", "top_heavy")
HOOK_ANGLES = (
    "Açılışı bir SORU olarak kur (merak boşluğu).",
    "Açılışı ŞAŞIRTICI bir sayı/istatistikle yap.",
    "Açılışta yaygın bir YANLIŞ İNANIŞI çürüt.",
    "Açılışı beklenmedik bir KARŞILAŞTIRMAYLA yap.",
    "Açılışı 'çoğu insan bunu bilmez' tonuyla kur.",
)
# Geçiş kombinasyonları (marka enerjisi korunur, kurgu hissi değişir)
_TRANSITION_SETS = (
    ("flash", "whoosh", "zoom"),
    ("whoosh", "zoom"),
    ("flash", "zoom"),
    ("zoom",),
)
_CUT_PACINGS = ("medium", "fast", "medium", "slow")


@dataclass(frozen=True)
class VariationProfile:
    layout: str
    hook_angle: str
    accent: str
    transitions: tuple[str, ...]
    cut_pacing: str


def _idx(seed: int, salt: str, n: int) -> int:
    """Stabil, seed'e bağlı indeks (process-salt'lı hash() DEĞİL)."""
    h = hashlib.sha1(f"{seed}:{salt}".encode("utf-8")).hexdigest()
    return int(h, 16) % n


def _accent_variants(channel) -> tuple[str, ...]:
    from short_bot.reel_colors import ensure_bright, luminance
    reel = channel.reel
    colors = getattr(channel, "colors", {}) or {}
    cands = [reel.highlight_color, colors.get("accent"), colors.get("primary")]
    out: list[str] = []
    for c in cands:
        if c and c not in out and luminance(c) >= 0.30:
            out.append(c)
    if not out:
        out = [ensure_bright(reel.highlight_color)]
    return tuple(out)


def build_variation_profile(channel, seed: int) -> VariationProfile:
    reel = channel.reel

    if reel.layout == "auto":
        layout = LAYOUTS[_idx(seed, "layout", len(LAYOUTS))]
    else:
        layout = reel.layout if reel.layout in LAYOUTS else "classic"

    hook_angle = ""
    if getattr(reel, "hook_angle_vary", True):
        hook_angle = HOOK_ANGLES[_idx(seed, "hook", len(HOOK_ANGLES))]

    if getattr(reel, "accent_vary", True):
        av = _accent_variants(channel)
        accent = av[_idx(seed, "accent", len(av))]
    else:
        accent = reel.highlight_color

    if getattr(reel, "transition_vary", True):
        transitions = _TRANSITION_SETS[_idx(seed, "trans", len(_TRANSITION_SETS))]
    else:
        transitions = tuple(
            t for t, on in (("flash", reel.transitions_flash),
                            ("whoosh", reel.transitions_whoosh),
                            ("zoom", reel.transitions_zoom)) if on)

    if reel.cut_pacing == "auto":
        cut_pacing = _CUT_PACINGS[_idx(seed, "pace", len(_CUT_PACINGS))]
    else:
        cut_pacing = reel.cut_pacing

    return VariationProfile(layout=layout, hook_angle=hook_angle, accent=accent,
                            transitions=transitions, cut_pacing=cut_pacing)
