"""Mixkit ses kütüphanesi toplayıcı — otomasyon parmak izini kırmak için.

SORUN: SFX havuzu 3 dosyaydı (ding/pop/whoosh) → 18 kesimlik videoda aynı ses ~6
kez çalıyordu; müzik 4 parçaydı. Her video aynı duyuluyordu = otomasyon parmak izi.

KAYNAK SEÇİMİ (hepsi canlı denendi, 2026-07-13):
- Storyblocks ses: indirme ÜCRETLİ Audio Plan istiyor ("Add Audio Plan to Download")
- ai33/ElevenLabs SFX üretimi: /v1/sound-effects → 404 (uç yok)
- Pixabay ses API: /api/audio/ → 403 (anahtarımız kapsamıyor)
- Freesound: yeni ücretsiz API anahtarı gerekir
- **Mixkit: SEÇİLDİ** — anahtarsız, atıfsız, ticari kullanıma serbest, düz HTTP.

Tarayıcı/oturum/anahtar GEREKMEZ. ``http_get`` enjekte edilebilir (testler ağa çıkmaz).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Mixkit SFX kategorileri (canlı ölçüm: whoosh 20, diğerleri ~36 dosya)
SFX_CATEGORIES = ("whoosh", "impact", "click", "game", "technology", "cinematic")

# Kurgucunun kullanacağı ruh hali → Mixkit müzik kategorisi (hepsi doğrulandı)
MUSIC_MOODS = {
    "tense": "thriller",          # 20
    "curious": "ambient",         # 36
    "epic": "cinematic",          # 36
    "calm": "calm",               # 36
    "dark": "discover/dark",      # 15
    "upbeat": "happy",            # 36
}

_SFX_URL = "https://mixkit.co/free-sound-effects/{cat}/"
_MUSIC_URL = "https://mixkit.co/free-stock-music/{cat}/"
_ASSET_RE = re.compile(r'https://assets\.mixkit\.co/[^"\s\\<>]+\.mp3')
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

MIN_BYTES = 8_000   # bozuk/boş indirme reddi (gerçek SFX ~70KB+)


def _default_get(url, **kw):
    import requests
    return requests.get(url, headers=_UA, timeout=kw.get("timeout", 20))


def scrape_urls(page_url: str, *, http_get=None) -> list[str]:
    """Mixkit kategori sayfasından benzersiz mp3 URL'leri (sıra korunur)."""
    http_get = http_get or _default_get
    r = http_get(page_url)
    if getattr(r, "status_code", 200) != 200:
        return []
    return list(dict.fromkeys(_ASSET_RE.findall(getattr(r, "text", "") or "")))


def download(url: str, out_path, *, http_get=None) -> "Path | None":
    """mp3 indir. MIN_BYTES altı (bozuk/boş) → None. Hata → None (fail-open)."""
    http_get = http_get or _default_get
    out = Path(out_path)
    try:
        r = http_get(url)
        data = getattr(r, "content", b"") or b""
        if len(data) < MIN_BYTES:
            return None
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return out
    except Exception as e:
        log.info(f"assets_library: indirme atlandı ({url[:60]}): {e}")
        return None


def _slug(url: str) -> str:
    """URL → dosya adı (Mixkit: .../sfx/1489/1489-preview.mp3 → 1489-preview.mp3)."""
    name = url.rstrip("/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
    return name or "asset.mp3"


def _fill(kind: str, cat: str, page_url: str, dest_dir: Path, want: int,
          http_get, progress) -> int:
    """Bir kategoriyi doldur. Var olan dosya YENİDEN indirilmez (idempotent)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    have = len(list(dest_dir.glob("*.mp3")))
    if have >= want:
        return 0
    urls = scrape_urls(page_url, http_get=http_get)
    if not urls:
        log.info(f"assets_library: {kind}/{cat} — sayfada ses bulunamadı")
        return 0
    added = 0
    for u in urls:
        if have + added >= want:
            break
        out = dest_dir / _slug(u)
        if out.exists():
            continue
        if download(u, out, http_get=http_get) is not None:
            added += 1
            if progress:
                progress(f"{kind}/{cat}: {have + added}/{want}")
    return added


def build_library(dest_root, *, per_sfx: int = 12, per_music: int = 8,
                  http_get=None, progress=None) -> dict:
    """Kütüphaneyi kur/genişlet → assets/sfx/<kat>/ + assets/music/<mood>/ + manifest.

    Tek kategorinin hatası diğerlerini DURDURMAZ (fail-open). Var olan dosya
    yeniden indirilmez → düğmeye tekrar basmak kütüphaneyi büyütür.
    Dönüş: {"sfx": N, "music": M, "skipped": K}
    """
    root = Path(dest_root)
    http_get = http_get or _default_get
    n_sfx = n_music = skipped = 0

    for cat in SFX_CATEGORIES:
        try:
            n_sfx += _fill("sfx", cat, _SFX_URL.format(cat=cat),
                           root / "sfx" / cat, per_sfx, http_get, progress)
        except Exception as e:   # noqa: BLE001 — bir kategori tüm kurulumu düşürmesin
            skipped += 1
            log.warning(f"assets_library: sfx/{cat} atlandı: {e}")

    for mood, cat in MUSIC_MOODS.items():
        try:
            n_music += _fill("music", mood, _MUSIC_URL.format(cat=cat),
                             root / "music" / mood, per_music, http_get, progress)
        except Exception as e:   # noqa: BLE001
            skipped += 1
            log.warning(f"assets_library: music/{mood} atlandı: {e}")

    idx = load_library_index(root, write_manifest=True)
    log.info(f"assets_library: +{n_sfx} sfx, +{n_music} müzik "
             f"(toplam sfx={sum(len(v) for v in idx['sfx'].values())}, "
             f"müzik={sum(len(v) for v in idx['music'].values())})")
    return {"sfx": n_sfx, "music": n_music, "skipped": skipped}


def load_library_index(root, *, write_manifest: bool = False) -> dict:
    """Kütüphane envanteri: {"sfx": {kat: [dosya...]}, "music": {mood: [...]}}.

    Klasörleri TARAYARAK kurar — manifest bozuk/eksik olsa da doğru çalışır.
    """
    root = Path(root)
    idx: dict = {"sfx": {}, "music": {}}
    for kind in ("sfx", "music"):
        base = root / kind
        if not base.is_dir():
            continue
        for sub in sorted(p for p in base.iterdir() if p.is_dir()):
            files = sorted(f.name for f in sub.glob("*.mp3"))
            if files:
                idx[kind][sub.name] = files
    if write_manifest:
        idx_out = dict(idx)
        idx_out["built_at"] = datetime.now(timezone.utc).isoformat()
        try:
            (root / "library.json").write_text(
                json.dumps(idx_out, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            log.info(f"assets_library: manifest yazılamadı: {e}")
        return idx_out
    return idx
