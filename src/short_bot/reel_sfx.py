"""Reel SFX havuzu keşfi + kategori-farkında, VİDEO-İÇİ TEKRARSIZ seçim (saf).

SORUN: havuz 3 dosyaydı ve seçim seed-hash'liydi → 18 kesimlik videoda aynı
"whoosh" ~6 kez çalıyordu (otomasyon parmak izi). Artık kütüphane kategori
klasörlerinde (assets/sfx/<kategori>/) ve seçim aynı dosyayı bir videoda TEKRAR
KULLANMAZ; kurgucu plan verdiyse kesim başına kategori ondan gelir.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

_ROOT_CAT = "_root"   # eski düz kütüphane (assets/sfx/*.mp3) bu kategoriye düşer


def discover_sfx(sfx_dir) -> dict[str, list[Path]]:
    """Kategori → dosyalar. Alt klasörler kategori; düz mp3'ler ``_root``."""
    d = Path(sfx_dir)
    out: dict[str, list[Path]] = {}
    if not d.is_dir():
        return out
    root_files = sorted(p for p in d.glob("*.mp3") if p.is_file())
    if root_files:
        out[_ROOT_CAT] = root_files
    for sub in sorted(p for p in d.iterdir() if p.is_dir()):
        files = sorted(f for f in sub.glob("*.mp3") if f.is_file())
        if files:
            out[sub.name] = files
    return out


def _flatten(pool) -> list[Path]:
    if isinstance(pool, dict):
        return [p for cat in sorted(pool) for p in pool[cat]]
    return list(pool or [])


IMPACT_CAT = "impact"


def pick_sfx_per_cut(pool, seed: int, n_cuts: int,
                     sfx_plan: "list[str] | tuple[str, ...]" = (),
                     impact_at: "set[int] | frozenset[int]" = frozenset()) -> list:
    """Kesim başına SFX seç. AYNI DOSYA bir videoda tekrar KULLANILMAZ.

    ``sfx_plan`` (kurgucudan) varsa kesim k için o kategoriden seçilir; yoksa tüm
    havuzdan seed-hash. Plan gerçek kesim sayısından kısaysa DÖNGÜSEL kullanılır —
    kurgucu tempoyu da belirlediği için kesin kesim sayısı plandan sonra netleşir.
    Kategori/havuz tükenirse tekrar serbest kalır (çökmez).
    ``pool`` dict (yeni) ya da düz liste (eski çağıranlar) olabilir.

    ``impact_at``: KESİNTİ anlarına denk gelen kesimlerin indeksleri (bkz.
    reel_interrupt). Oralarda kategori kurgucunun planını EZER ve 'impact' olur:
    kesinti bir VURUŞTUR, "whoosh" geçiş sesi onu taşıyamaz. Havuzda impact
    kategorisi yoksa plan/eski davranış aynen sürer (fail-open).
    """
    if n_cuts <= 0:
        return []
    by_cat = pool if isinstance(pool, dict) else {_ROOT_CAT: list(pool or [])}
    by_cat = {k: list(v) for k, v in by_cat.items() if v}
    if not by_cat:
        return []
    flat = _flatten(by_cat)
    used: set[str] = set()
    out: list[Path] = []

    for k in range(n_cuts):
        cat = None
        if k in impact_at and IMPACT_CAT in by_cat:
            cat = IMPACT_CAT
        elif sfx_plan:
            want = sfx_plan[k % len(sfx_plan)]
            if want in by_cat:
                cat = want
        cands = by_cat[cat] if cat else flat
        fresh = [p for p in cands if str(p) not in used]
        if not fresh:
            # kategori/havuz tükendi → tekrar serbest (ama deterministik)
            fresh = cands or flat
        h = int(hashlib.sha1(f"{seed}:sfx:{k}".encode()).hexdigest(), 16)
        pick = fresh[h % len(fresh)]
        used.add(str(pick))
        out.append(pick)
    return out
