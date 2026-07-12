"""Beat başına Pexels footage eşleştirme + opsiyonel vision doğrulama."""
from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from short_bot.claude_cli import run_json
from short_bot.footage_sources import PexelsSource

log = logging.getLogger(__name__)

MIN_CLIP_S = 2
MAX_CHECK = 5   # her sorguda en fazla kaç aday denenir


class _FootageDescription(BaseModel):
    content: str = ""


_DESCRIBE_PROMPT = (
    "Bu görüntü NE gösteriyor? SADECE gördüğün somut nesneleri/sahneyi "
    "1-2 kısa İngilizce cümleyle tarif et. Genel kategori değil SPESİFİK ol "
    "(ör. 'a kitchen counter' değil 'a person chopping onions on a wooden "
    "board'). İngilizce yaz.\n"
    'SADECE JSON: {"content": "<English description>"}'
)


def _describe_image_file(path: Path, *, vision_call) -> str:
    """Yerel bir görüntü dosyasını vision ile İngilizce tarif eder (≤384px küçültür)."""
    from short_bot.claude_cli import run_json
    try:
        try:  # maliyeti dipte tutmak için ≤384px'e küçült
            from PIL import Image
            im = Image.open(path)
            im.thumbnail((384, 384))
            im.convert("RGB").save(path, "JPEG")
        except Exception:
            pass
        v = run_json(_DESCRIBE_PROMPT, _FootageDescription,
                     claude_path=vision_call.claude_path, model=vision_call.model,
                     backend=vision_call.backend, api_key=vision_call.api_key,
                     image_path=path, retries=1, timeout_s=45)
        return (v.content or "").strip()
    except Exception as e:
        log.warning(f"footage describe hatası: {e}")
        return ""


def describe_footage(image_url: str, *, vision_call=None) -> str:
    """Thumbnail'ın NE gösterdiğini vision ile İngilizce tarif eder (yes/no DEĞİL).

    Katı: genel kategori değil, gördüğü SPESİFİK nesne/sahne. vision yok / thumbnail
    yok / hata → "" (çağıran gate'i 'no-vision' ile pasif bırakır — üretim durmaz).
    """
    if not image_url or vision_call is None:
        return ""
    import requests
    thumb: Path | None = None
    try:
        r = requests.get(image_url, timeout=15)
        if r.status_code != 200 or not r.content:
            return ""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            tf.write(r.content)
            thumb = Path(tf.name)
        return _describe_image_file(thumb, vision_call=vision_call)
    except Exception as e:
        log.warning(f"footage describe hatası: {e}")
        return ""
    finally:
        if thumb is not None:
            thumb.unlink(missing_ok=True)


def verify_clip_frame_matches(clip_path, query: str, *, vision_call=None, pool=None,
                              ffmpeg_path: str = "ffmpeg") -> bool:
    """Thumbnail'ı OLMAYAN kaynaklar (ör. Storyblocks kazıma) için: indirilen
    klibin ~ortasından 9:16 kare çıkar → describe → analyze_scene(pool) off-topic mi.

    vision yok / pool yok / kare çıkmadı / tarif boş / hata → True (fail-open;
    üretim ASLA gate yüzünden bloklanmaz). Off-topic ise False (çağıran klibi siler)."""
    if vision_call is None or not pool:
        return True
    frame: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            frame = Path(tf.name)
        if _extract_cropped_frame(Path(clip_path), ffmpeg_path, frame) is None:
            return True
        desc = _describe_image_file(frame, vision_call=vision_call)
        if not desc:
            log.info(f"  footage frame-gate: tarif BOŞ → fail-open | q='{query}'")
            return True
        from short_bot.reel_relevance import analyze_scene
        res = analyze_scene(desc, pool)
        tag = "OFF-TOPIC" if res["off_topic"] else "ok"
        log.info(f"  footage frame-gate [{tag}] hits={res['hits']} q='{query}': '{desc[:70]}'")
        return not res["off_topic"]
    except Exception as e:
        log.warning(f"clip frame gate hatası: {e}")
        return True
    finally:
        if frame is not None:
            frame.unlink(missing_ok=True)


def verify_clip_matches(image_url: str, query: str, *, vision_call=None, pool=None) -> bool:
    """Thumbnail off-topic mi: describe_footage → analyze_scene(desc, pool).

    ``pool`` verilmemişse (ya da vision/thumbnail yoksa) True — arama sırasına güven
    (fail-open; footage üretimi ASLA gate yüzünden bloklanmaz). ``query`` imza
    uyumu için durur; asıl karar tarif↔havuz örtüşmesine dayanır.
    """
    if not image_url or vision_call is None:
        return True
    desc = describe_footage(image_url, vision_call=vision_call)
    if not desc:
        log.info(f"  footage gate: tarif BOŞ (vision hata/timeout) → fail-open kabul | q='{query}'")
        return True
    if not pool:
        return True
    from short_bot.reel_relevance import analyze_scene
    res = analyze_scene(desc, pool)
    tag = "OFF-TOPIC" if res["off_topic"] else "ok"
    log.info(f"  footage gate [{tag}] hits={res['hits']} q='{query}': '{desc[:70]}'")
    return not res["off_topic"]


class SubjectPos(BaseModel):
    found: bool = False
    discrete: bool = False
    confidence: float = 0.0
    x: float = 0.5
    y: float = 0.5


class _LocateVerdict(BaseModel):
    found: bool = False
    discrete: bool = False
    confidence: float = 0.0
    x: float = 0.5
    y: float = 0.5


def _extract_cropped_frame(clip: Path, ffmpeg_path: str, out: Path) -> Path | None:
    """Klibin ~ortasından 9:16 cover-crop'lu, ≤384px kare çıkarır."""
    import subprocess
    vf = ("scale=1080:1920:force_original_aspect_ratio=increase,"
          "crop=1080:1920,scale=384:-1")
    try:
        p = subprocess.run([ffmpeg_path, "-y", "-ss", "1", "-i", str(clip),
                            "-vf", vf, "-frames:v", "1", str(out)],
                           capture_output=True, timeout=30)
        return out if out.exists() and out.stat().st_size > 0 else None
    except Exception:
        return None


def locate_subject(clip_path, query, *, vision_call=None, ffmpeg_path="ffmpeg") -> SubjectPos:
    """Klibin final-kare görünümünde ana nesnenin normalize (x,y) merkezini bulur.
    vision yok/hata/found=false → SubjectPos(found=False)."""
    if vision_call is None:
        return SubjectPos(found=False)
    import tempfile
    frame: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            frame = Path(tf.name)
        if _extract_cropped_frame(Path(clip_path), ffmpeg_path, frame) is None:
            return SubjectPos(found=False)
        prompt = (
            f'Bu 9:16 karede TEK, net, işaret-edilebilir bir ANA nesne var mı: '
            f'"{query}"? Manzara / geniş sahne / dağınık / çok-uzak / belirsiz ise '
            f'discrete=false ver. Varsa nesnenin MERKEZİNİ normalize koordinatla '
            f'(sol-üst 0,0; sağ-alt 1,1) ve 0..1 güven ver.\n'
            f'SADECE JSON: {{"found": true|false, "discrete": true|false, '
            f'"confidence": 0.0..1.0, "x": 0.0..1.0, "y": 0.0..1.0}}'
        )
        v = run_json(prompt, _LocateVerdict, claude_path=vision_call.claude_path,
                     model=vision_call.model, backend=vision_call.backend,
                     api_key=vision_call.api_key, image_path=frame,
                     retries=1, timeout_s=45)
        x = min(1.0, max(0.0, float(v.x))); y = min(1.0, max(0.0, float(v.y)))
        conf = min(1.0, max(0.0, float(v.confidence)))
        return SubjectPos(found=bool(v.found), discrete=bool(v.discrete),
                          confidence=conf, x=x, y=y)
    except Exception as e:
        log.warning(f"locate_subject hatası: {e}")
        return SubjectPos(found=False)
    finally:
        if frame is not None:
            frame.unlink(missing_ok=True)


@dataclass(frozen=True)
class FootageDeps:
    # Öncelik-sıralı kaynak zinciri; ilki bulamazsa sıradaki denenir.
    sources: list = field(default_factory=lambda: [PexelsSource()])
    verify_footage: Callable = verify_clip_matches   # (image_url, query, *, vision_call, pool) -> bool
    verify_clip_frame: Callable = verify_clip_frame_matches  # thumbnail'sız kaynak için kare-gate
    locate_subject: Callable = locate_subject


def match_beat_clip(query: str, *, api_key: str = "", cache_dir: Path,
                    verify: bool = True, vision_call=None,
                    deps: FootageDeps | None = None, topic_pool=None,
                    ffmpeg_path: str = "ffmpeg") -> Path | None:
    """Sorguya uyan tek klibi kaynak zincirinden indirip yolunu döndürür.

    Kaynakları ``deps.sources`` öncelik sırasında dener: kullanılamayanı atlar,
    her kaynak için portrait+landscape yönelimini dener, süresi ``MIN_CLIP_S``
    altındakileri eler, ilk başarılı indirmeyi döndürür. Hepsi tükenirse None.

    ALAKA GATE iki yollu: THUMBNAIL varsa indirmeden ÖNCE thumbnail üstünde
    doğrular (ucuz); thumbnail YOKSA (ör. Storyblocks kazıma) indirdikten SONRA
    klip KARESİ üstünde doğrular (off-topic → sil, sıradaki aday). Böylece
    thumbnail'sız kaynaklar gate'i ATLAYAMAZ.

    ``api_key`` parametresi geriye-uyum için durur; anahtarları kaynaklar taşır.
    """
    d = deps or FootageDeps()
    cache_dir = Path(cache_dir)
    for source in d.sources:
        try:
            if not source.available():
                continue
        except Exception:
            continue
        for orientation in ("portrait", "landscape"):
            try:
                cands = source.search(query, max_results=MAX_CHECK,
                                      orientation=orientation)
            except Exception as e:
                log.warning(f"{getattr(source, 'name', '?')} arama hatası: {e}")
                cands = []
            cands = [c for c in cands if getattr(c, "duration_s", 0) >= MIN_CLIP_S]
            for c in cands:
                thumb_url = getattr(c, "image", "") or ""
                # 1) Pre-download gate — THUMBNAIL varsa (ucuz, indirmeden ele)
                if verify and d.verify_footage is not None and thumb_url:
                    try:
                        ok = d.verify_footage(thumb_url, query,
                                              vision_call=vision_call, pool=topic_pool)
                    except Exception as e:
                        log.warning(f"footage vision doğrulama hatası: {e}")
                        ok = True   # doğrulama patlarsa arama sırasına güven
                    if not ok:
                        continue
                try:
                    clip = source.download(c, cache_dir)
                except Exception as e:
                    log.warning(f"{getattr(source, 'name', '?')} indirme hatası: {e}")
                    clip = None
                if clip is None:
                    continue
                # 2) Post-download gate — THUMBNAIL YOKSA klip karesinde doğrula
                # (Storyblocks kazıma thumb üretmez → aksi hâlde gate'i atlardı).
                if (verify and not thumb_url and topic_pool
                        and getattr(d, "verify_clip_frame", None) is not None):
                    try:
                        ok2 = d.verify_clip_frame(clip, query, vision_call=vision_call,
                                                  pool=topic_pool, ffmpeg_path=ffmpeg_path)
                    except Exception as e:
                        log.warning(f"clip frame gate hatası: {e}")
                        ok2 = True
                    if not ok2:
                        # Klibi SİLME: Storyblocks/Pexels içerik-adresli cache'i
                        # beat'ler arası paylaşılır; silmek başka beat'in tuttuğu
                        # dosyanın referansını koparır (FileNotFoundError). Sadece atla.
                        continue
                return clip
    return None
