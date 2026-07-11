"""Reel SFX havuzu keşfi + deterministik per-cut seçim (saf)."""
from __future__ import annotations
import hashlib
from pathlib import Path


def discover_sfx(sfx_dir) -> list[Path]:
    d = Path(sfx_dir)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.mp3") if p.is_file())


def pick_sfx_per_cut(pool, seed: int, n_cuts: int) -> list[Path]:
    pool = list(pool)
    if not pool or n_cuts <= 0:
        return []
    out = []
    for k in range(n_cuts):
        h = int(hashlib.sha1(f"{seed}:sfx:{k}".encode()).hexdigest(), 16)
        out.append(pool[h % len(pool)])
    return out
