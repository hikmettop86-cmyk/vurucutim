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

# RISER: reveal'den önce yükselen ses. SFX havuzuna KARIŞMAZ — kesim başına çalarsa
# video uğultuya döner. Tek bir yerde, TEPEDEN hemen önce kullanılır.
RISER_CATEGORY = "riser"

# Kurgucunun kullanacağı ruh hali → Mixkit müzik kategorisi (hepsi doğrulandı)
MUSIC_MOODS = {
    "tense": "thriller",          # 20
    "curious": "ambient",         # 36
    "epic": "cinematic",          # 36
    "calm": "calm",               # 36
    "dark": "discover/dark",      # 15
    "upbeat": "happy",            # 36
}

# Kurgucuya SUNULABİLECEK müzik ruh halleri. assets/music/ altındaki HER klasör
# ruh hali DEĞİLDİR — pick_music orayı aynı zamanda kanal klasörü olarak kullanır
# (assets/music/<kanal-slug>/). Bu allowlist olmadan kurgucu bir bilim videosuna
# "galatasaray" müziği seçebilirdi. "breaking"/"neutral" eski jenerik moodlar.
MUSIC_MOOD_VOCAB = frozenset(MUSIC_MOODS) | {"breaking", "neutral"}

_SFX_URL = "https://mixkit.co/free-sound-effects/{cat}/"
_MUSIC_URL = "https://mixkit.co/free-stock-music/{cat}/"
_ASSET_RE = re.compile(r'https://assets\.mixkit\.co/[^"\s\\<>]+\.mp3')
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

MIN_BYTES = 8_000   # bozuk/boş indirme reddi (gerçek SFX ~70KB+)

# --- SFX ses hijyeni -------------------------------------------------------
# Mixkit "sfx" indirmelerinin bir kısmı SFX DEĞİL, ambiyans YATAĞI (technology/1000
# = 25.4sn). Kesimler ~2.5sn'de bir olduğu için 25 saniyelik bir ses AYNI ANDA 10
# SFX'in üst üste binmesine yol açıyordu — "sfx sesleri çok baskın" şikâyetinin ana
# kaynağı buydu. Ayrıca dosyalar arası seviye farkı 20.3 dB'ydi (cinematic -12.4 dB
# vs click -32.7 dB): bir vurgu fısıltı, diğeri patlama.
MAX_SFX_S = 1.5          # SFX bir VURGUDUR, yatak değil
SFX_FADE_S = 0.12        # kırpma tıkırtısı olmasın
SFX_TARGET_LUFS = -23    # anlatımın BELİRGİN altında (vurgu, yarış değil)

# RISER SFX'ten UZUN olmalı: 1.5sn'ye kırpılırsa YÜKSELİŞ yok olur, geriye bir uğultu
# kalır. Riser'ın işi tam da o yükseliş — beyne "bir şey geliyor" demesi.
MAX_RISER_S = 2.5
RISER_TARGET_LUFS = -20  # SFX'ten biraz önde: gerilimi taşıması gerek

# STING: kanalın AÇILIŞ SES İMZASI ("ses logosu"). Her bölümün ilk karesinde, HEP AYNI
# ses. Ayrı klasör: SFX havuzuna karışırsa kesim başına çalar ve imza olmaktan çıkar
# (bkz. reel_identity — imza ancak TEKRARLANINCA imza olur).
# Mixkit'in "cinematic" kategorisinden gelir: kısa, vurucu, marka hissi taşıyan sesler.
STING_CATEGORY = "cinematic"
MAX_STING_S = 1.8        # riser'dan kısa, SFX'ten uzun: tanınacak kadar var olmalı
STING_TARGET_LUFS = -20


def normalize_sfx(path, *, ffmpeg_path: str = "ffmpeg",
                  max_s: float = MAX_SFX_S,
                  target_lufs: float = SFX_TARGET_LUFS,
                  fade_out: bool = True) -> "Path | None":
    """SFX dosyasını yerinde VURGUYA çevir: kırp + fade + seviye eşitle.

    ``fade_out=False`` (riser): sondaki doruk KORUNUR — riser'ın işi tam da o
    yükseliş; sonunu söndürürsek geriye bir uğultu kalır.

    Idempotent (kütüphane tekrar taranabilir). Bozuk/çözülemeyen dosya → None,
    dosyaya DOKUNULMAZ (fail-open: tek bozuk dosya kurulumu düşürmez).
    """
    import os
    import shutil
    import subprocess
    import tempfile

    p = Path(path)
    fd, tmp_name = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)          # Windows: açık tanıtıcı ffmpeg'in yazmasını engeller
    tmp = Path(tmp_name)
    try:
        af = f"atrim=0:{max_s:g},asetpts=N/SR/TB,"
        if fade_out:
            af += (f"afade=t=out:st={max(0.0, max_s - SFX_FADE_S):g}:"
                   f"d={SFX_FADE_S:g},")
        af += f"loudnorm=I={target_lufs:g}:TP=-3:LRA=11"
        cmd = [
            ffmpeg_path, "-y", "-v", "error", "-i", str(p),
            "-af", af, "-ar", "44100", "-b:a", "128k", str(tmp),
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1000:
            log.info(f"assets_library: SFX normalize atlandı ({p.name})")
            return None
        shutil.move(str(tmp), str(p))
        return p
    except Exception as e:  # noqa: BLE001 — tek dosya tüm kurulumu düşürmesin
        log.info(f"assets_library: SFX normalize hatası ({p.name}): {e}")
        return None
    finally:
        tmp.unlink(missing_ok=True)


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
            if kind == "sfx":
                # İndirilen ham "sfx"in bir kısmı 25sn'lik ambiyans YATAĞI ve
                # dosyalar arası 20 dB seviye farkı var → kütüphaneye VURGU
                # olarak girsin (kırpılmış + seviyesi eşitlenmiş).
                normalize_sfx(out)
            elif kind == "riser":
                # Riser'ın DORUĞU sondadır → fade YOK, ve SFX'ten uzun kalır.
                normalize_sfx(out, max_s=MAX_RISER_S,
                              target_lufs=RISER_TARGET_LUFS, fade_out=False)
            elif kind == "sting":
                # Sting bir MARKA sesidir: kısa ama tanınacak kadar var, ve fade ile
                # temiz biter (kare sıfırda konuşmanın üstüne binmemeli).
                normalize_sfx(out, max_s=MAX_STING_S,
                              target_lufs=STING_TARGET_LUFS)
            added += 1
            if progress:
                progress(f"{kind}/{cat}: {have + added}/{want}")
    return added


def build_library(dest_root, *, per_sfx: int = 12, per_music: int = 8,
                  per_riser: int = 7, per_sting: int = 6,
                  http_get=None, progress=None) -> dict:
    """Kütüphaneyi kur/genişlet → assets/sfx/<kat>/ + assets/music/<mood>/ + manifest.

    Tek kategorinin hatası diğerlerini DURDURMAZ (fail-open). Var olan dosya
    yeniden indirilmez → düğmeye tekrar basmak kütüphaneyi büyütür.
    Dönüş: {"sfx": N, "music": M, "riser": R, "sting": S, "skipped": K}
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

    # RISER: ayrı klasör — SFX havuzuna karışırsa kesim başına çalar ve video
    # uğultuya döner. Tek bir yerde, TEPEDEN hemen önce kullanılır.
    n_riser = 0
    try:
        n_riser = _fill("riser", RISER_CATEGORY,
                        _SFX_URL.format(cat=RISER_CATEGORY),
                        root / "riser", per_riser, http_get, progress)
    except Exception as e:   # noqa: BLE001
        skipped += 1
        log.warning(f"assets_library: riser atlandı: {e}")

    # STING: kanalın açılış ses imzası. Ayrı klasör — SFX havuzuna karışırsa kesim
    # başına çalar ve imza olmaktan çıkar (bkz. reel_identity).
    n_sting = 0
    try:
        n_sting = _fill("sting", STING_CATEGORY,
                        _SFX_URL.format(cat=STING_CATEGORY),
                        root / "sting", per_sting, http_get, progress)
    except Exception as e:   # noqa: BLE001
        skipped += 1
        log.warning(f"assets_library: sting atlandı: {e}")

    for mood, cat in MUSIC_MOODS.items():
        try:
            n_music += _fill("music", mood, _MUSIC_URL.format(cat=cat),
                             root / "music" / mood, per_music, http_get, progress)
        except Exception as e:   # noqa: BLE001
            skipped += 1
            log.warning(f"assets_library: music/{mood} atlandı: {e}")

    idx = load_library_index(root, write_manifest=True)
    log.info(f"assets_library: +{n_sfx} sfx, +{n_music} müzik, +{n_sting} sting "
             f"(toplam sfx={sum(len(v) for v in idx['sfx'].values())}, "
             f"müzik={sum(len(v) for v in idx['music'].values())})")
    return {"sfx": n_sfx, "music": n_music, "riser": n_riser, "sting": n_sting,
            "skipped": skipped}


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
