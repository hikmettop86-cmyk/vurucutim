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
# TARAMA BÜTÇESİ — vision DOĞRULUĞU maliyetten önemli (kullanıcı kararı).
# Eski değerler (10/5/3) çok dardı: kondor koşusunda bütçe daha ilk sorguda dolup
# YENİ adaylara hiç sıra gelmiyor, vision'sız çöpe düşülüyordu. Yargı önbelleği
# (``seen``) aynı adayın iki kez yargılanmasını zaten engellediği için yüksek
# tavan boşa çağrıya dönüşmez — sadece DAHA ÇOK FARKLI adaya bakılır.
MAX_GATE_CHECKS = 30   # en fazla kaç aday vision kapısından geçirilir
# MAX_DOWNLOADS, MAX_PER_SOURCE'tan BELİRGİN ŞEKİLDE BÜYÜK olmalı: thumbnail'ı
# olmayan kaynak (Storyblocks) her adayı yargılamak için İNDİRMEK zorunda; tavan
# dar olursa tek kaynak indirme bütçesini bitirip zincirdeki diğer kaynakları
# aç bırakır ve klip hiç bulunamaz.
MAX_DOWNLOADS = 20     # en fazla kaç klip indirilir
MAX_PER_SOURCE = 8     # tek kaynaktan en fazla kaç aday denenir (tekel olmasın)


class _FootageVerdict(BaseModel):
    """Vision'ın TEK çağrıda döndürdüğü tarif + KATI eşleşme + BAĞLAM + GÖRSEL KALİTE.

    ``matches`` (katı: sorgunun ANA ÖZNESİ var mı) ile ``in_context`` (gevşek: bu
    klip bu VİDEONUN b-roll'ü olabilir mi) AYRI alanlar. Tek çağrıda ikisi de
    alınır → gevşek kapı geçişi EKSTRA vision maliyeti getirmez.
    """
    content: str = ""
    matches: bool = False
    in_context: bool = False   # ana özne olmasa da videoya ait mi (destekleyici b-roll)
    clear: bool = True     # görüntü net/okunaklı mı (çok karanlık/bulanık DEĞİL)
    reason: str = ""


def _judge_prompt(query: str, context: str = "") -> str:
    # BAĞLAM (videonun gerçek konusu) KRİTİK: anlatım metafor kullanınca ("görünmez
    # savaşçılar" = bakteriyofaj) sorgu metafora kayabiliyor ve stok kütüphane
    # kelimeyi DÜZ anlıyor → bakteriyofaj videosuna ESKRİMCİ geldi. Bağlam verilince
    # vision "bu klip bu videoya ait mi?" diye de bakar ve konu-dışını eler.
    ctx = (f'\nVİDEONUN KONUSU: "{context}"\n') if context else ""
    return (
        f'Bu görüntüyü bir YouTube Shorts videosunda B-ROLL olarak kullanacağız.\n'
        f'{ctx}'
        f'ÜÇ BAĞIMSIZ SORU var. Birinin cevabı diğerini BELİRLEMEZ.\n\n'

        f'1) in_context — GENİŞ SORU: Bu görüntü videonun konusuyla AYNI DÜNYADAN mı '
        f'geliyor (aynı ortam / alan / tema)?\n'
        f'   Bu soruda CÖMERT OL. Kurgucular konuyu desteklemek için ana özneyi '
        f'göstermeyen b-roll kullanır: buzul erimesi videosunda kar, buz, su, kutup '
        f'manzarası; kondor videosunda süzülen herhangi bir yırtıcı kuş ya da dağ '
        f'manzarası; bakteriyofaj videosunda laboratuvar, mikroskop, doktor. '
        f'HEPSİ in_context=true.\n'
        f'   in_context=false YALNIZCA klip BAŞKA BİR DÜNYADAN geliyorsa: konu '
        f'"bakteriyofaj virüsü" iken arama "invisible warrior" diye ESKRİMCİ getirdi '
        f'(metafor tuzağı); kondor videosunda dağda yürüyen turist; balık videosunda '
        f'tavada kızaran balık; alakasız ofis/şehir/mutfak sahnesi.\n\n'

        f'2) matches — DAR SORU: "{query}" aramasının ANA ÖZNESİ görüntüde '
        f'gerçekten görünüyor mu?\n'
        f'   Burada KATI OL: "balina yavrusu" istenip insan bebeği, "kondor" istenip '
        f'martı/kartal varsa matches=false. İllüstrasyon/3D render/animasyon SAYILIR.\n'
        f'   ÖNEMLİ: matches=false olması in_context\'i ETKİLEMEZ. Bir klip aramanın '
        f'dar öznesini göstermeyip yine de konunun dünyasına ait olabilir — bu çok '
        f'YAYGINDIR. Örnek: konu buzul erimesi, arama "melting ice rivers", görüntü '
        f'"kar ve su karışımı kutup manzarası" → matches=false AMA in_context=TRUE.\n\n'

        f'3) clear — GÖRSEL KALİTE: Görüntü NET ve OKUNAKLI mı? İzleyici ne '
        f'gördüğünü anlayabiliyor mu? Şunlarda clear=false ver: neredeyse tamamen '
        f'karanlık/siyah, ne olduğu seçilemeyen bulanık kütle, aşırı pozlanmış, '
        f'boş/anlamsız kare, ağır filigran/yazı kaplı. (Karanlık AMA net bir sahne '
        f'— ör. siyah zeminde parlayan mikroplar — clear=true.)\n\n'

        f'Ayrıca gördüğünü 1 kısa İngilizce cümleyle tarif et.\n'
        f'SADECE JSON: {{"content": "<English description>", '
        f'"in_context": true|false, "matches": true|false, "clear": true|false, '
        f'"reason": "<kısa Türkçe gerekçe>"}}'
    )


def _judge_image_file(path: Path, query: str, *, vision_call,
                      context: str = "") -> "_FootageVerdict | None":
    """Yerel görüntüyü vision ile TARİF ET + sorgu/kalite/BAĞLAM yargısı ver.

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
        return run_json(_judge_prompt(query, context), _FootageVerdict,
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
                              ffmpeg_path: str = "ffmpeg", context: str = "",
                              relaxed: bool = False, seen: dict | None = None) -> bool:
    """Thumbnail'ı OLMAYAN kaynaklar (Storyblocks) için: indirilen klipten 9:16
    kare çıkar → vision yargısı ("bu kare '{query}' gösteriyor mu?").

    Eşik ``verify_clip_matches`` ile aynı merdiven: ``relaxed`` bağlam-b-roll'ü de
    kabul eder. ``seen`` klip yolu ile yargıyı önbelleğe alır.

    ``pool`` yok sayılır (geriye-uyum imzası). vision yok / kare çıkmadı / vision
    hatası → True (fail-open; üretim ASLA gate yüzünden bloklanmaz)."""
    if vision_call is None:
        return True

    def _decide(v: "_FootageVerdict") -> bool:
        return bool(v.clear) and bool(v.in_context if relaxed else v.matches)

    key = str(clip_path)
    if seen is not None and key in seen:
        return _decide(seen[key])
    frame: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            frame = Path(tf.name)
        if _extract_cropped_frame(Path(clip_path), ffmpeg_path, frame) is None:
            return True
        v = _judge_image_file(frame, query, vision_call=vision_call, context=context)
        if v is None:
            log.info(f"  footage frame-gate: vision yanıt vermedi → fail-open | q='{query}'")
            return True
        if seen is not None:
            seen[key] = v
        ok = _decide(v)
        tag = ("ok" if ok else
               "BULANIK/KARANLIK" if (v.matches or v.in_context) else "BAĞLAM DIŞI")
        if ok and relaxed and not v.matches:
            tag = "bağlam-broll"
        log.info(f"  footage frame-gate [{tag}] q='{query}': '{(v.content or '')[:60]}'"
                 + (f" ({v.reason[:40]})" if not ok and v.reason else ""))
        return ok
    except Exception as e:
        log.warning(f"clip frame gate hatası: {e}")
        return True
    finally:
        if frame is not None:
            frame.unlink(missing_ok=True)


def verify_clip_matches(image_url: str, query: str, *, vision_call=None, pool=None,
                        context: str = "", relaxed: bool = False,
                        seen: dict | None = None) -> bool:
    """Thumbnail bu sorguyu KARŞILIYOR MU — vision'ın katı per-sorgu yargısı.

    Eski kelime-havuzu kapısı KALDIRILDI: soyut alanlarda (anchor='science history')
    havuz {science,history} oluyordu ve hiçbir vision-tarifi bu kelimeleri
    içermediği için MÜKEMMEL klipler bile reddediliyordu (gerçek hata: "human brain
    anatomy" sorgusuna gelen 'glowing holographic brain' klibi off-topic sayıldı →
    tüm kaynaklar tarandı → 25dk üretim). Artık kararı vision veriyor: sorgunun
    ANA ÖZNESİ görünüyor mu.

    ``relaxed=False`` → KATI eşik (sorgunun ana öznesi görünmeli).
    ``relaxed=True``  → BAĞLAM eşiği (ana özne olmasa da videoya ait destekleyici
    b-roll kabul). Katı kapı hiçbir şey geçirmediğinde bu merdivene inilir; aksi
    hâlde vision'sız çöp alınıyordu (kondor videosuna dağda yürüyen turist).

    ``seen`` verilirse yargı image_url ile ÖNBELLEĞE alınır: aynı aday bir videoda
    İKİ KEZ vision'a sokulmaz. Bu israfı keser (doğruluğu değil) — gerçek koşuda
    67 vision çağrısının çoğu aynı martı/pelikan/kelebek döngüsüydü ve bütçe
    tükendiği için yeni adaylara hiç sıra gelmiyordu.

    ``pool`` geriye-uyum için durur (yok sayılır). vision/thumbnail yok ya da vision
    hatası → True (fail-open)."""
    if not image_url or vision_call is None:
        return True

    def _decide(v: "_FootageVerdict") -> bool:
        # clear HER İKİ eşikte de şart: konuya uysa bile KARANLIK/BULANIK klip
        # retention öldürür (gerçek hata: 6sn ne olduğu anlaşılmayan siyah kütle).
        return bool(v.clear) and bool(v.in_context if relaxed else v.matches)

    if seen is not None and image_url in seen:
        return _decide(seen[image_url])

    import requests
    thumb: Path | None = None
    try:
        r = requests.get(image_url, timeout=15)
        if r.status_code != 200 or not r.content:
            return True
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            tf.write(r.content)
            thumb = Path(tf.name)
        v = _judge_image_file(thumb, query, vision_call=vision_call, context=context)
        if v is None:
            log.info(f"  footage gate: vision yanıt vermedi → fail-open | q='{query}'")
            return True
        if seen is not None:
            seen[image_url] = v
        ok = _decide(v)
        tag = ("ok" if ok else
               "BULANIK/KARANLIK" if (v.matches or v.in_context) else
               "BAĞLAM DIŞI" if not v.in_context else "UYMUYOR")
        if ok and relaxed and not v.matches:
            tag = "bağlam-broll"
        log.info(f"  footage gate [{tag}] q='{query}': '{(v.content or '')[:60]}'"
                 + (f" ({v.reason[:40]})" if not ok and v.reason else ""))
        return ok
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


def _extract_cropped_frame(clip: Path, ffmpeg_path: str, out: Path,
                           at_s: float = 1.0) -> Path | None:
    """Klipten ``at_s`` anında 9:16 cover-crop'lu, ≤384px kare çıkarır."""
    import subprocess
    vf = ("scale=1080:1920:force_original_aspect_ratio=increase,"
          "crop=1080:1920,scale=384:-1")
    try:
        p = subprocess.run([ffmpeg_path, "-y", "-ss", f"{max(0.0, at_s):.3f}",
                            "-i", str(clip), "-vf", vf, "-frames:v", "1", str(out)],
                           capture_output=True, timeout=30)
        return out if out.exists() and out.stat().st_size > 0 else None
    except Exception:
        return None


def locate_subject(clip_path, query, *, vision_call=None, ffmpeg_path="ffmpeg",
                   at_s: float = 1.0) -> SubjectPos:
    """Klibin final-kare görünümünde ana nesnenin normalize (x,y) merkezini bulur.

    ``at_s``: kareyi klibin HANGİ saniyesinden al. Alt-kesim klibin ortasından
    başlıyorsa ve özne (uçan arı) hareket ediyorsa, sabit 1. saniyeden ölçülen
    konum ekranda BOŞLUĞU işaretler — çağıran o alt-kesimin gerçek başlangıcını
    geçmeli.

    vision yok/hata/found=false → SubjectPos(found=False)."""
    if vision_call is None:
        return SubjectPos(found=False)
    import tempfile
    frame: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            frame = Path(tf.name)
        if _extract_cropped_frame(Path(clip_path), ffmpeg_path, frame,
                                  at_s=at_s) is None:
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
                    exclude: set | None = None, context: str = "",
                    relaxed: bool = False, seen: dict | None = None) -> Path | None:
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

    ``exclude``: bu videoda ZATEN kullanılmış KLİP YOLLARI. (Eskiden aday URL'sine
    karşı denetleniyordu ama çağıran dosya yolları gönderiyordu → exclude üretimde
    HİÇ çalışmıyordu; her segment aynı klibi yeniden buluyordu.)

    ``seen``: video-geneli vision yargı önbelleği (image_url → verdict). Aynı aday
    iki kez yargılanmaz.  ``relaxed``: bkz. ``verify_clip_matches``.

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
                    continue    # aday URL'siyle dışlandı (çağıran URL de tutuyorsa)
                tried_from_source += 1
                thumb_url = getattr(c, "image", "") or ""
                # 1) Pre-download gate — THUMBNAIL varsa (ucuz, indirmeden ele).
                # Önbellekte olan aday vision'a YENİDEN gitmez → bütçe yalnız YENİ
                # adaylar için harcanır.
                if verify and d.verify_footage is not None and thumb_url:
                    cached = seen is not None and thumb_url in seen
                    if not cached:
                        b["gate"] = b.get("gate", 0) + 1
                    try:
                        ok = d.verify_footage(thumb_url, query,
                                              vision_call=vision_call, pool=topic_pool,
                                              context=context, relaxed=relaxed,
                                              seen=seen)
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
                # Bu videoda ZATEN kullanılmış klip mi? (kaynaklar içerik-adresli
                # cache kullanır: farklı aday AYNI dosyaya inebilir.) Silme, ATLA.
                if exclude and str(clip) in exclude:
                    continue
                # 2) Post-download gate — THUMBNAIL YOKSA klip karesinde doğrula
                # (Storyblocks kazıma thumb üretmez → aksi hâlde gate'i atlardı).
                if (verify and not thumb_url
                        and getattr(d, "verify_clip_frame", None) is not None):
                    if not (seen is not None and str(clip) in seen):
                        b["gate"] = b.get("gate", 0) + 1
                    try:
                        ok2 = d.verify_clip_frame(clip, query, vision_call=vision_call,
                                                  pool=topic_pool, ffmpeg_path=ffmpeg_path,
                                                  context=context, relaxed=relaxed,
                                                  seen=seen)
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
