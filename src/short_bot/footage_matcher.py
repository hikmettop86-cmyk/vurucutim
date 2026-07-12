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
MAX_CHECK = 5   # her sorguda kaynak başına en fazla kaç aday çekilir

# TARAMA BÜTÇESİ (segment başına) — kullanıcı isteği + gerçek 25dk yavaşlık:
# gate her adayı reddedince tüm kaynaklar/yönelimler taranıp Storyblocks'tan
# onlarca klip TARAYICIYLA indiriliyordu. Bütçe dolunca eşleştirme durur.
MAX_GATE_CHECKS = 10   # en fazla kaç aday vision kapısından geçirilir
MAX_DOWNLOADS = 5      # en fazla kaç klip indirilir (thumbnail'siz kaynak pahalı)
MAX_PER_SOURCE = 3     # tek kaynaktan en fazla kaç aday denenir (Storyblocks tekel olmasın)


class _FootageVerdict(BaseModel):
    """Vision'ın TEK çağrıda döndürdüğü tarif + KATI eşleşme yargısı."""
    content: str = ""
    matches: bool = False
    reason: str = ""


def _judge_prompt(query: str) -> str:
    return (
        f'Bu görüntü şu aramayı KARŞILIYOR MU: "{query}"?\n'
        f'KATI OL: sorgunun ANA ÖZNESİ görüntüde gerçekten görünmeli. Yalnızca '
        f'genel kategori uyuyorsa HAYIR de — ör. "balina yavrusu" istenip insan '
        f'bebeği, "beyin anatomisi" istenip rastgele bir el görülüyorsa false.\n'
        f'İllüstrasyon/3D render/animasyon da SAYILIR (konuyu gösteriyorsa true).\n'
        f'Ayrıca gördüğünü 1 kısa İngilizce cümleyle tarif et.\n'
        f'SADECE JSON: {{"content": "<English description>", '
        f'"matches": true|false, "reason": "<kısa Türkçe gerekçe>"}}'
    )


def _judge_image_file(path: Path, query: str, *, vision_call) -> "_FootageVerdict | None":
    """Yerel görüntüyü vision ile TARİF ET + sorguya KATI eşleşme yargısı ver.

    Hata/vision yok → None (çağıran fail-open ile kabul eder — üretim durmaz)."""
    from short_bot.claude_cli import run_json
    try:
        try:  # maliyeti dipte tutmak için ≤384px'e küçült
            from PIL import Image
            im = Image.open(path)
            im.thumbnail((384, 384))
            im.convert("RGB").save(path, "JPEG")
        except Exception:
            pass
        return run_json(_judge_prompt(query), _FootageVerdict,
                        claude_path=vision_call.claude_path,
                        model=vision_call.model, backend=vision_call.backend,
                        api_key=vision_call.api_key, image_path=path,
                        retries=1, timeout_s=45)
    except Exception as e:
        log.warning(f"footage vision yargı hatası: {e}")
        return None


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
    """Thumbnail'ı OLMAYAN kaynaklar (Storyblocks) için: indirilen klipten 9:16
    kare çıkar → vision KATI yargısı ("bu kare '{query}' gösteriyor mu?").

    ``pool`` yok sayılır (geriye-uyum imzası). vision yok / kare çıkmadı / vision
    hatası → True (fail-open; üretim ASLA gate yüzünden bloklanmaz)."""
    if vision_call is None:
        return True
    frame: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            frame = Path(tf.name)
        if _extract_cropped_frame(Path(clip_path), ffmpeg_path, frame) is None:
            return True
        v = _judge_image_file(frame, query, vision_call=vision_call)
        if v is None:
            log.info(f"  footage frame-gate: vision yanıt vermedi → fail-open | q='{query}'")
            return True
        tag = "ok" if v.matches else "UYMUYOR"
        log.info(f"  footage frame-gate [{tag}] q='{query}': '{(v.content or '')[:60]}'"
                 + (f" ({v.reason[:40]})" if not v.matches and v.reason else ""))
        return bool(v.matches)
    except Exception as e:
        log.warning(f"clip frame gate hatası: {e}")
        return True
    finally:
        if frame is not None:
            frame.unlink(missing_ok=True)


def verify_clip_matches(image_url: str, query: str, *, vision_call=None, pool=None) -> bool:
    """Thumbnail bu sorguyu KARŞILIYOR MU — vision'ın katı per-sorgu yargısı.

    Eski kelime-havuzu kapısı KALDIRILDI: soyut alanlarda (anchor='science history')
    havuz {science,history} oluyordu ve hiçbir vision-tarifi bu kelimeleri
    içermediği için MÜKEMMEL klipler bile reddediliyordu (gerçek hata: "human brain
    anatomy" sorgusuna gelen 'glowing holographic brain' klibi off-topic sayıldı →
    tüm kaynaklar tarandı → 25dk üretim). Artık kararı vision veriyor: sorgunun
    ANA ÖZNESİ görünüyor mu.

    ``pool`` geriye-uyum için durur (yok sayılır). vision/thumbnail yok ya da vision
    hatası → True (fail-open)."""
    if not image_url or vision_call is None:
        return True
    import requests
    thumb: Path | None = None
    try:
        r = requests.get(image_url, timeout=15)
        if r.status_code != 200 or not r.content:
            return True
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            tf.write(r.content)
            thumb = Path(tf.name)
        v = _judge_image_file(thumb, query, vision_call=vision_call)
        if v is None:
            log.info(f"  footage gate: vision yanıt vermedi → fail-open | q='{query}'")
            return True
        tag = "ok" if v.matches else "UYMUYOR"
        log.info(f"  footage gate [{tag}] q='{query}': '{(v.content or '')[:60]}'"
                 + (f" ({v.reason[:40]})" if not v.matches and v.reason else ""))
        return bool(v.matches)
    except Exception as e:
        log.warning(f"footage gate hatası: {e}")
        return True
    finally:
        if thumb is not None:
            thumb.unlink(missing_ok=True)


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
                    ffmpeg_path: str = "ffmpeg", budget: dict | None = None,
                    exclude: set | None = None) -> Path | None:
    """Sorguya uyan tek klibi kaynak zincirinden indirip yolunu döndürür.

    Kaynakları ``deps.sources`` öncelik sırasında dener; her kaynak için
    portrait+landscape yönelimi, süresi ``MIN_CLIP_S`` altındakiler elenir; ilk
    KAPIDAN GEÇEN klip döner. Hepsi tükenir ya da BÜTÇE dolarsa None.

    ALAKA GATE iki yollu: THUMBNAIL varsa indirmeden ÖNCE (ucuz); YOKSA
    (Storyblocks) indirdikten SONRA klip karesinde. İkisi de vision'ın katı
    per-sorgu yargısıdır.

    TARAMA BÜTÇESİ (``budget`` dict — segment boyunca paylaşılır, çağıran verir):
    ``gate`` (vision kapısı sayısı), ``dl`` (indirme sayısı). Kaynak başına
    ``MAX_PER_SOURCE`` aday. Bütçe olmadan tek kaynak (Storyblocks) tüm süreyi
    yiyordu — gerçek 25dk üretim hatası.

    ``api_key``/``topic_pool`` geriye-uyum için durur (topic_pool artık yok sayılır).
    """
    d = deps or FootageDeps()
    cache_dir = Path(cache_dir)
    b = budget if budget is not None else {"gate": 0, "dl": 0}

    def _budget_left() -> bool:
        return (b.get("gate", 0) < MAX_GATE_CHECKS
                and b.get("dl", 0) < MAX_DOWNLOADS)

    for source in d.sources:
        if not _budget_left():
            log.info("  footage: tarama bütçesi doldu → sıradaki sorguya/kaynağa geç")
            return None
        try:
            if not source.available():
                continue
        except Exception:
            continue
        src_name = getattr(source, "name", "?")
        tried_from_source = 0
        for orientation in ("portrait", "landscape"):
            if tried_from_source >= MAX_PER_SOURCE or not _budget_left():
                break
            try:
                cands = source.search(query, max_results=MAX_CHECK,
                                      orientation=orientation)
            except Exception as e:
                log.warning(f"{src_name} arama hatası: {e}")
                cands = []
            cands = [c for c in cands if getattr(c, "duration_s", 0) >= MIN_CLIP_S]
            for c in cands:
                if tried_from_source >= MAX_PER_SOURCE or not _budget_left():
                    break
                if exclude and (getattr(c, "url", "") in exclude):
                    continue    # bu klip bu beat için ZATEN alındı (çoklu klip)
                tried_from_source += 1
                thumb_url = getattr(c, "image", "") or ""
                # 1) Pre-download gate — THUMBNAIL varsa (ucuz, indirmeden ele)
                if verify and d.verify_footage is not None and thumb_url:
                    b["gate"] = b.get("gate", 0) + 1
                    try:
                        ok = d.verify_footage(thumb_url, query,
                                              vision_call=vision_call, pool=topic_pool)
                    except Exception as e:
                        log.warning(f"footage vision doğrulama hatası: {e}")
                        ok = True   # doğrulama patlarsa arama sırasına güven
                    if not ok:
                        continue
                b["dl"] = b.get("dl", 0) + 1
                try:
                    clip = source.download(c, cache_dir)
                except Exception as e:
                    log.warning(f"{src_name} indirme hatası: {e}")
                    clip = None
                if clip is None:
                    continue
                # 2) Post-download gate — THUMBNAIL YOKSA klip karesinde doğrula
                # (Storyblocks kazıma thumb üretmez → aksi hâlde gate'i atlardı).
                if (verify and not thumb_url
                        and getattr(d, "verify_clip_frame", None) is not None):
                    b["gate"] = b.get("gate", 0) + 1
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
