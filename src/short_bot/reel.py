"""Reel (footage-sürüklü) üretim orkestratörü.

Zincir: preflight → reel senaryosu → TTS → hizalama → footage eşleştirme →
montaj. Tüm dış bağımlılıklar ReelDeps üzerinden enjekte edilir.
TTS/footage/montaj başarısızsa net Türkçe hatayla durur (sessiz fallback yok).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from short_bot.audio_probe import probe_duration_s as _probe
from short_bot.audio_probe import trailing_silence_s as _tail
from short_bot.footage_matcher import FootageDeps, SubjectPos, download_banked
from short_bot.footage_matcher import locate_subject as _locate
from short_bot.footage_matcher import match_beat_clip as _match
from short_bot.footage_discovery import discover_subject as _discover_subject
from short_bot.footage_sources import build_footage_sources


def _download_candidate(src, cand, cache_dir):
    """Keşif adayını kendi kaynağından indir (test enjeksiyonu için ayrık)."""
    return src.download(cand, cache_dir)

from short_bot.reel_assembler import assemble_reel as _assemble
from short_bot.reel_markers import _marker_worthy_segs, build_markers
from short_bot.music_profile import (MUSIC_UNDER_SPEECH_DB, music_gain_db,
                                     profile_music, speech_lufs)
from short_bot.reel_models import build_reel_timeline
from short_bot.reel_pause import MIN_PAUSE_AT_S, REVEAL_PAUSE_S
from short_bot.reel_pause import insert_pause as _pause
from short_bot.reel_pause import shift_words
from short_bot.reel_punch import punch_times
from short_bot.reel_interrupt import (impact_cut_indices, select_interrupts,
                                      sfx_gains)
from short_bot.reel_tempo import plan_zones, remap_words, retimed_duration_s
from short_bot.reel_tempo import retime as _retime
from short_bot.reel_narration import write_reel_narration as _write_narr
from short_bot.reel_curiosity import write_curious_narration as _write_curious
from short_bot.reel_narration import write_footage_driven_narration as _write_fd_narr
from short_bot.reel_narration import footage_search_queries as _fd_queries
from short_bot.reel_numbers import find_numbers
from short_bot.reel_grade import MOTION_MIN, measure_motion
from short_bot.reel_pacing import clip_offsets, plan_subcuts, subcut_clip_index
from short_bot.reel_render import render_reel_overlay_frames as _render
from short_bot.reel_sfx import discover_sfx, pick_sfx_per_cut
from short_bot.tts.ai33_client import health_check as _health
from short_bot.tts.ai33_client import synthesize as _synth
from short_bot.tts.align import transcribe_words as _transcribe
from short_bot.tts.fidelity import worst_drop

log = logging.getLogger(__name__)


class RunCancelled(RuntimeError):
    """Kullanıcı koşuyu panelden iptal etti."""

# Belirteç konumları birbirinden BAĞIMSIZ vision çağrıları (~2-3sn) — paralel ölç.
# 15 alt-kesim sıralı ölçülünce 30 saniye yiyordu.
LOCATE_WORKERS = 5
# Kadrajı yalnız GÜVENLE bulunmuş özneye kaydır. Yanlış yere kaydırmak, merkez
# crop'tan BETERDİR (özne büsbütün kadraj dışında kalır).
FRAME_CONF_MIN = 0.6


def _probe_s(path, ffmpeg_path: str = "ffmpeg") -> float:
    """Ses dosyasının süresi. Riser'ın BİTİŞİ tepeye hizalanacağı için şart.
    Okunamazsa kütüphane varsayılanına düş (fail-open)."""
    import subprocess
    from short_bot.assets_library import MAX_RISER_S
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=15)
        return float(p.stdout.strip())
    except Exception:
        return MAX_RISER_S

_PREFLIGHT = {
    "no-key": "ai33 için AI33_API_KEY tanımlı değil (Ayarlar → API anahtarları).",
    "auth": "ai33 reddetti: AI33_API_KEY geçersiz ya da kredi bitmiş.",
    "no-voice": "reel.voice_id boş — panelden bir ses seç.",
    "stalled": "ai33 kuyruk takılı (preflight zaman aşımı); üretim iptal, kredi harcanmadı.",
    "error": "ai33 preflight başarısız — servis yanıt vermiyor.",
}
# GEÇİCİ hatalar: servis anlık yanıt vermiyor / kuyruk takılmış → yeniden dene.
# KALICI olanlar (auth/no-key/no-voice) burada YOK: beklemenin faydası olmaz.
_PREFLIGHT_TRANSIENT = {"error", "stalled"}
PREFLIGHT_RETRIES = 3
PREFLIGHT_BACKOFF_S = 8

# ai33 arada bir metnin bir öbeğini sessizce okumadan geçiyor (bkz. tts/fidelity).
# Arıza aralıklı olduğu için yeniden göndermek çoğu zaman düzeltiyor.
TTS_FIDELITY_RETRIES = 2
# Öbek düşürdüğünde ai33 dosyayı beklenen uzunluğa SESSİZLİKLE dolduruyor. Ölçüldü:
# sağlam seslendirmede sondaki sessizlik 0.00sn, öbek düşen üç koşuda 3.4 / 3.8 / 6.9sn.
# Bu işaret whisper'dan BAĞIMSIZ — ve gerekli: whisper sessizlikte metin uydurup
# sadakat denetimini kandırabiliyor (short 759'da tam olarak bunu yaptı).
TTS_MAX_TAIL_S = 1.5
# Kalması gereken nefes payı. Fazlası kesilir: 7 saniye ölü hava izleyiciye videonun
# bittiğini söyler ve döngüyü kırar.
TAIL_KEEP_S = 0.4


@dataclass(frozen=True)
class ReelDeps:
    write_reel_narration: Callable = _write_narr
    # GÖRÜNTÜ-ÖNCELİKLİ MOD (yalnız reel.footage_driven=True iken kullanılır)
    write_footage_driven_narration: Callable = _write_fd_narr
    # MERAK MİMARİSİ: 3 aday → yargıç → doktor (bkz. reel_curiosity)
    write_curious_narration: Callable = _write_curious
    footage_search_queries: Callable = _fd_queries
    # KEŞİF: konu stoktan doğar (kullanıcı önerisi 2026-07-16, bkz. footage_discovery)
    discover_subject: Callable = _discover_subject
    download_candidate: Callable = _download_candidate
    health_check: Callable = _health
    synthesize: Callable = _synth
    probe_duration_s: Callable = _probe
    trailing_silence_s: Callable = _tail
    transcribe_words: Callable = _transcribe
    retime: Callable = _retime
    insert_pause: Callable = _pause
    match_beat_clip: Callable = _match
    locate_subject: Callable = _locate
    render_reel_overlay_frames: Callable = _render
    assemble_reel: Callable = _assemble


def _match_with_fallback(d, query, *, topic_q, api_key, cache_dir, verify,
                         vision_call, footage_deps=None, topic_pool=None, anchor="",
                         ffmpeg_path="ffmpeg", budget=None, reuse_clips=None,
                         reuse_idx=0, exclude=None, context="", seen=None,
                         hook=False):
    """Footage eşleştirmeyi kademeli, KONUDA-KALAN yedeklerle dener.

    KAPI MERDİVENİ (hepsi vision'lı):
      1. KATI  — sorgunun ANA ÖZNESİ görünmeli: tam sorgu → ilk 2 kelime → konu
         tohumu → kanal çıpası.
      2. GEVŞEK — ana özne yoksa da BAĞLAMA UYAN destekleyici b-roll kabul (kondor
         videosunda süzülen kartal, And Dağları). Gerçek koşuda katı kapı hiçbir
         şey geçirmeyince vision'SIZ çöp alınıyordu (dağda yürüyen turist);
         bağlam-b-roll ondan çok daha iyidir.
      3. TEKRAR — bu videonun kabul edilmiş kliplerinden dönüşümlü biri.
      4. SON ÇARE — vision'sız arama. Artık neredeyse hiç ulaşılmaz.

    ``seen``: video-geneli vision yargı önbelleği → aynı aday iki kez yargılanmaz,
    bütçe yalnız YENİ adaylara harcanır.

    Dönüş: ``(clip, gated)`` — ``gated`` False ise klip vision kapısından GEÇMEDİ.
    Çağıran onu tekrar havuzuna KOYMAZ: gerçek hata short_id=171'de doğrulanmamış
    bir insan-anatomi illüstrasyonu tekrar çıpası olup videonun 22 saniyesini
    ele geçirmişti.
    """
    words = query.split()
    stages = [query]
    if len(words) > 2:
        stages.append(" ".join(words[:2]))
    if topic_q and topic_q.lower() not in (s.lower() for s in stages):
        stages.append(topic_q)
    if anchor and anchor.lower() not in (s.lower() for s in stages):
        stages.append(anchor)
    # Tarama bütçesi SEGMENT boyunca paylaşılır: tüm fallback aşamaları aynı
    # kovadan yer → tek segment onlarca Storyblocks indirmesiyle dakikalar yakamaz.
    b = budget if budget is not None else {"gate": 0, "dl": 0}
    # 1) KATI kapı: sorgunun ana öznesi görünmeli. Bu tarama sırasında, katı kapıdan
    # geçemeyen ama BAĞLAMDA + NET olan adaylar ``bank``'a not edilir.
    bank: list = []
    for q in stages:
        clip = d.match_beat_clip(q, api_key=api_key, cache_dir=cache_dir,
                                 verify=verify, vision_call=vision_call,
                                 deps=footage_deps, topic_pool=topic_pool,
                                 ffmpeg_path=ffmpeg_path, budget=b,
                                 exclude=exclude, context=context, seen=seen,
                                 bank=bank, hook=hook)
        if clip is not None:
            return clip, True
    # 1b) HOOK'ta hiçbir aday ÇARPICI çıkmadıysa: çarpıcılık şartını düşür ama
    # ALAKA + NETLİĞİ koru. Alakalı-ama-sıkıcı bir açılış karesi, ortam b-roll'ünden
    # iyidir. YARGILAR ÖNBELLEKTE → bu geçiş SIFIR vision çağrısına mal olur, yalnız
    # eşik değişir.
    if hook:
        for q in stages:
            clip = d.match_beat_clip(q, api_key=api_key, cache_dir=cache_dir,
                                     verify=verify, vision_call=vision_call,
                                     deps=footage_deps, topic_pool=topic_pool,
                                     ffmpeg_path=ffmpeg_path,
                                     budget={"gate": 0, "dl": 0},
                                     exclude=exclude, context=context, seen=seen,
                                     bank=bank, hook=False)
            if clip is not None:
                log.info(f"  footage: hook için ÇARPICI aday yok → alakalı+net "
                         f"klip kabul edildi ('{q[:30]}')")
                return clip, True
    # 2) BAĞLAM B-ROLL'Ü: ana özne yok ama konunun dünyasından, net bir klip.
    # YENİDEN ARAMA YOK, YENİDEN VISION YOK — adaylar katı taramada zaten yargılandı.
    # (Bunu ayrı bir ikinci tarama olarak kurmak canlı koşuda 121 vision çağrısına
    # çıkıp üretimi dakikalarca uzatmıştı.)
    if bank:
        clip = download_banked(bank, cache_dir=cache_dir, exclude=exclude)
        if clip is not None:
            log.info(f"  footage: '{query[:30]}' katı kapıdan geçmedi → "
                     f"BAĞLAMA UYAN b-roll kabul edildi ({len(bank)} aday notlanmıştı)")
            return clip, True
    # 3) TEKRAR: bu videoda ZATEN kabul edilmiş (konuda) bir klibi yeniden kullan —
    # tekrar, alakasızdan iyidir.
    if reuse_clips:
        # DÖNÜŞÜMLÜ seç, hep sonuncuyu DEĞİL: eski kod reuse_clips[-1] diyordu, bu
        # yüzden arka arkaya birkaç segment kapıdan geçemeyince hepsi AYNI klibi
        # alıyor ve video donuyordu (short_id=171: 8 kesim üst üste tek görüntü).
        pick = reuse_clips[reuse_idx % len(reuse_clips)]
        log.info(f"  footage: '{query[:30]}' için kapıdan geçen aday yok → "
                 f"kabul edilmiş '{pick.name}' tekrar kullanılıyor "
                 f"({reuse_idx % len(reuse_clips) + 1}/{len(reuse_clips)})")
        return pick, True
    # Hiç klip yoksa (ilk işlenen segment) — vision'sız ara ama SEGMENTİN KENDİ
    # sorgusuyla. Kanal çıpası ('science history') ÇÖP getiriyordu (gerçek hata:
    # 'autopsy table doctor' beat'i → çıpa → tablo/poster pazarı). Kendi sorgusu
    # hiç değilse konuya yakın bir şey getirir.
    for last_q in ([query]
                   + ([" ".join(words[:2])] if len(words) > 2 else [])
                   + ([anchor] if anchor else [])):
        clip = d.match_beat_clip(last_q, api_key=api_key, cache_dir=cache_dir,
                                 verify=False, vision_call=None, deps=footage_deps,
                                 topic_pool=None, ffmpeg_path=ffmpeg_path,
                                 budget={"gate": 0, "dl": 0})
        if clip is not None:
            log.info(f"  footage: '{query[:30]}' kapıdan geçmedi → vision'sız "
                     f"'{last_q[:30]}' klibi kullanıldı (DOĞRULANMADI)")
            return clip, False
    return None, False


def _footage_driven_clip_count(target_duration_s) -> int:
    """Görüntü-öncelikli modda kaç klip indirileceği. Klip başına ~11sn (bir beat).
    En az 3, en çok 6 (memory: N≈beat 3-6). 45-60sn → 5; 25-45 → 3."""
    lo, hi = target_duration_s
    return max(3, min(6, round((lo + hi) / 2 / 11)))


def _footage_driven_seg_clip(clips: list, si: int, n_segs: int):
    """beat=klip eşlemesi (görüntü-öncelikli): segment si → önden indirilmiş klip.

      seg 0 (hook)          → clips[0]
      seg 1+i (beat i)      → clips[i]  (i len(clips) aşarsa son klibe kelepçelenir)
      seg n_segs-1 (close)  → clips[-1]

    LLM'in yazdığı beat sayısı klip sayısından SAPSA bile her segment bir klip alır
    (build_footage_driven_prompt N beat ister ama garanti değil)."""
    last = len(clips) - 1
    if si == 0:
        return clips[0]
    if n_segs > 1 and si == n_segs - 1:
        return clips[last]
    beat_i = si - 1                       # seg 1 = beat 0
    return clips[min(beat_i, last)]


def _fd_motion_min(clip, ffmpeg_path: str = "ffmpeg") -> float:
    """Klibin BAŞ ve SON penceresinin hareket MİNİMUMU (görüntü-önce statik reddi).

    measure_motion yalnız ilk ~4sn'yi örnekler (fps=4, 16 kare). Görüntü-önce bir
    klip 2 segmenti (son beat + close, ~13sn) taşıyabilir ve alt-kesim offsetleri
    klibin SONUNA yayılır. GERÇEK HATA (okçu balığı repro): başı hareketli sonu
    durgun amber sürü klibi kapıdan geçti → kapanışta 8.1sn donuk kare.

    Kuyruk sondası YENİDEN-KODLAR (-c copy DEĞİL): GERÇEK HATA (keçi videosu,
    son 8sn 0.0000 donuk): -c copy keyframe sınırında boş/bozuk dosya verip
    fail-open 1.0 döndürüyordu → donmuş kuyruklu klip kapıdan geçiyordu.
    Kuyruk yine çıkarılamazsa baş ölçümü döner (fail-open)."""
    import subprocess
    import tempfile
    m1 = measure_motion(clip, ffmpeg_path)
    try:
        with tempfile.TemporaryDirectory() as td:
            t = Path(td) / "tail.mp4"
            subprocess.run([ffmpeg_path, "-v", "error", "-y", "-sseof", "-4",
                            "-i", str(clip), "-vf", "scale=64:64", "-an",
                            "-preset", "ultrafast", str(t)],
                           capture_output=True, timeout=60)
            if t.exists() and t.stat().st_size > 0:
                return min(m1, measure_motion(t, ffmpeg_path))
    except Exception:  # noqa: BLE001 — ölçüm hatası eleme yapmasın
        pass
    return m1


# Durgun pencere eşiği (ölçüldü, keçi videosu): bakışma/duran hayvan 0.002-0.005,
# gerçek hareket 0.03-0.18. Klip pencerelerinin yarıdan fazlası bu eşiğin
# altındaysa klip 'çoğunluğu durgun'dur — baş/son hareketli olsa bile izleyici
# uzun donuk bölüm görür (kullanıcı: '0:24'ten sonra donuyor').
_FD_STILL_WIN = 0.005
_FD_STATIC_FRAC_MAX = 0.5


def _fd_motion_profile(clip, ffmpeg_path: str = "ffmpeg") -> list[float]:
    """Klibin 2sn'lik pencere başına hareket profili (fps=2, 64x64 gri fark ort.).

    Hem durgunluk oranı (_fd_static_fraction) hem ofset düzeltmesi
    (_fd_fix_static_offsets) bunu kullanır. Okunamazsa [] (fail-open)."""
    import subprocess
    import tempfile
    try:
        from PIL import Image, ImageChops, ImageStat
    except Exception:  # noqa: BLE001
        return []
    try:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            subprocess.run(
                [ffmpeg_path, "-v", "error", "-i", str(clip),
                 "-vf", "fps=2,scale=64:64,format=gray",
                 "-frames:v", "120", str(td / "s%03d.png")],   # en çok 60sn
                capture_output=True, timeout=60)
            kareler = sorted(td.glob("*.png"))
            if len(kareler) < 5:
                return []
            imgs = [Image.open(k).convert("L") for k in kareler]
            diffs = [ImageStat.Stat(ImageChops.difference(a, b)).mean[0] / 255.0
                     for a, b in zip(imgs, imgs[1:])]
            return [sum(diffs[i:i + 4]) / len(diffs[i:i + 4])
                    for i in range(0, len(diffs), 4)]
    except Exception as e:  # noqa: BLE001 — ölçüm hatası üretimi düşürmesin
        log.info(f"  reel: hareket profili ölçülemedi ({clip}): {e}")
        return []


def _fd_static_fraction(clip, ffmpeg_path: str = "ffmpeg") -> float:
    """Klibin TAMAMI taranır: 2sn'lik pencerelerin ne kadarı durgun (0-1).

    _fd_motion_min yalnız baş+son 4sn'ye bakar — ORTASI 30sn bakışma olan klibi
    göremez (keçi videosu dersi). Okunamazsa 0.0 (fail-open: eleme yapma)."""
    prof = _fd_motion_profile(clip, ffmpeg_path)
    if not prof:
        return 0.0
    return sum(1 for m in prof if m < _FD_STILL_WIN) / len(prof)


def _fd_fix_static_offsets(clip_paths, subcuts, clip_starts, ffmpeg_path,
                           *, min_span_s: float = 3.0) -> list[float]:
    """Uzun alt-kesimlerin klip-içi ofsetini DURGUN pencereden HAREKETLİ pencereye kaydır.

    GERÇEK HATA (karınca videosu): kapı klibi bütün olarak geçirdi (durgunluk
    %40) ama kapanışın 5.6sn'lik alt-kesimi klip İÇİNDEKİ donmuş bekleme
    bölümüne denk geldi → son 6sn tamamen dondu. clip_offsets ofsetleri süreye
    eşit yayar, pencerelerin hareketinden habersizdir. Burada yalnız UZUN
    (>= min_span_s) alt-kesimler kontrol edilir: ofsetin düştüğü pencere
    durgunsa (< _FD_STILL_WIN) klibin EN HAREKETLİ penceresine kaydırılır.
    Profil okunamazsa dokunulmaz (fail-open)."""
    profiller: dict[str, list[float]] = {}
    yeni = list(clip_starts)
    for i, ((si, a, b), clip) in enumerate(zip(subcuts, clip_paths)):
        span = b - a
        if span < min_span_s or i >= len(yeni):
            continue
        key = str(clip)
        if key not in profiller:
            profiller[key] = _fd_motion_profile(clip, ffmpeg_path)
        prof = profiller[key]
        if not prof:
            continue
        w = min(int(yeni[i] / 2.0), len(prof) - 1)
        if prof[w] >= _FD_STILL_WIN:
            continue                     # ofset zaten hareketli pencerede
        en_iyi = max(range(len(prof)), key=lambda k: prof[k])
        if prof[en_iyi] < _FD_STILL_WIN:
            continue                     # klipte hareketli pencere yok (kapı kaçırdı)
        yeni[i] = en_iyi * 2.0
        log.info(f"  reel[görüntü-önce]: alt-kesim {i} ofseti durgun pencereden "
                 f"({clip_starts[i]:.1f}s) hareketliye ({yeni[i]:.1f}s) kaydırıldı")
    return yeni


def _fd_clip_ok(clip, ffmpeg_path: str = "ffmpeg") -> bool:
    """Görüntü-önce klip kapısı: baş/son hareketli VE çoğunluğu durgun değil."""
    if _fd_motion_min(clip, ffmpeg_path) < MOTION_MIN:
        return False
    return _fd_static_fraction(clip, ffmpeg_path) <= _FD_STATIC_FRAC_MAX


def _rotate_sources(footage_deps, si: int):
    """API sağlayıcılarını (Pexels/Pixabay) segment bazında DÖNDÜR — her segment
    farklı sağlayıcıdan BAŞLASIN (çeşitlilik).

    KULLANICI: 'neden tek sağlayıcıya bakıyor?'. Sistem ilk klibi bulunca duruyordu;
    Pexels havuzu kıtsa (ör. şempanze) aynı klipler TEKRAR ediyordu. Round-robin,
    farklı segmentleri farklı API'den beslediği için etkin havuzu genişletir."""
    srcs = list(getattr(footage_deps, "sources", None) or [])
    if len(srcs) < 2:
        return footage_deps            # döndürecek bir şey yok
    r = si % len(srcs)
    rotated = srcs[r:] + srcs[:r]
    return FootageDeps(sources=rotated, verify_footage=footage_deps.verify_footage)


def _describe_clip(clip, *, vision_call, ffmpeg_path: str,
                   tail_s: float | None = None) -> str:
    """Klipten bir kare çıkarıp vision ile İngilizce tarif eder (tür-tutarlılık için).

    ``tail_s`` verilirse kare klibin SONUNDAN alınır (-sseof). Görüntü-önce eleme
    baş+son iki kareyi karşılaştırır: derleme/kaydırma klibinde (short 846: telefon
    scroll klibi) baş ve son FARKLI sahnedir — tek kare bunu asla yakalayamaz."""
    import subprocess
    import tempfile
    from short_bot.footage_matcher import _describe_image_file
    seek = ["-sseof", f"-{tail_s}"] if tail_s else ["-ss", "1"]
    try:
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "probe.jpg"
            subprocess.run([ffmpeg_path, "-v", "error", "-y", *seek, "-i", str(clip),
                            "-frames:v", "1", "-vf", "scale=384:-1", str(f)],
                           capture_output=True, timeout=30)
            if f.exists():
                return _describe_image_file(f, vision_call=vision_call)
    except Exception as e:  # noqa: BLE001
        log.info(f"  klip tarifi çıkarılamadı ({clip}): {e}")
    return ""


def _repair_footage_types(clips_by_seg: dict, *, topic: str, seg_queries, d,
                          vision_call, footage_deps, topic_pool, anchor: str,
                          ffmpeg_path: str, pexels_api_key: str, clips_cache,
                          used_clips: set, seen: dict, verify: bool) -> None:
    """Render-ÖNCESİ tür-tutarlılık onarımı: seçilmiş klipleri topluca gör, konunun
    öznesinden farklı CANLI gösteren klibi YENİDEN SEÇ. clips_by_seg YERİNDE güncellenir.

    Ucuz düzeltme (render'dan önce): yalnız sapan klip değişir, senaryo/TTS/ses korunur.
    """
    from short_bot.claude_cli import run_json
    from short_bot.footage_matcher import find_footage_outliers

    # Benzersiz klipleri sırayla topla + tarif et.
    uniq: list = []
    seen_c: set = set()
    for si in sorted(clips_by_seg):
        for c in clips_by_seg[si]:
            if str(c) not in seen_c:
                seen_c.add(str(c))
                uniq.append(c)
    if len(uniq) < 2:
        return
    # PARALEL tarif (ucuzlatma): 25 klibi seri tarif etmek ~75sn ekliyordu;
    # LOCATE_WORKERS'la paralel → ~1/5 süre. Her tarif bağımsız (klip → vision).
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=LOCATE_WORKERS) as _ex:
        descs = list(_ex.map(
            lambda c: _describe_clip(c, vision_call=vision_call, ffmpeg_path=ffmpeg_path),
            uniq))

    def _inv(prompt, schema):
        return run_json(prompt, schema, claude_path=vision_call.claude_path,
                        model=vision_call.model, backend=vision_call.backend,
                        api_key=vision_call.api_key, retries=1, timeout_s=45)

    outliers = find_footage_outliers(descs, topic, invoke=_inv)
    if not outliers:
        log.info(f"  render-öncesi tür kontrolü: {len(uniq)} klip TUTARLI")
        return
    bad = {str(uniq[i]) for i in outliers}
    log.warning(f"  render-öncesi: {len(bad)}/{len(uniq)} yanlış-tür klip "
                f"({', '.join(descs[i][:30] for i in outliers)}) → yeniden seçiliyor")
    for i in outliers:
        used_clips.add(str(uniq[i]))   # sapan bir daha gelmesin
    for si in sorted(clips_by_seg):
        yeni = []
        for c in clips_by_seg[si]:
            if str(c) not in bad:
                yeni.append(c)
                continue
            q = seg_queries[si] if si < len(seg_queries) and seg_queries[si] else topic
            clip, _gated = _match_with_fallback(
                d, q, topic_q=topic, api_key=pexels_api_key, cache_dir=clips_cache,
                verify=verify, vision_call=vision_call, footage_deps=footage_deps,
                topic_pool=topic_pool, anchor=anchor, ffmpeg_path=ffmpeg_path,
                exclude=set(used_clips), seen=seen)
            if clip is not None and str(clip) not in bad:
                used_clips.add(str(clip))
                yeni.append(clip)
                log.info(f"  seg{si}: yanlış-tür klip yerine yenisi seçildi")
            else:
                yeni.append(c)   # yenisi bulunamadı → eskiyi tut (fail-open)
                log.info(f"  seg{si}: yanlış-tür yerine yeni bulunamadı → eski tutuldu")
        clips_by_seg[si] = yeni


def _prepare_footage_driven(*, topic: str, channel, reel, d, work_dir: Path,
                            pexels_api_key: str, pixabay_api_key: str,
                            footage_priority,
                            vision_call, ffmpeg_path: str,
                            llm_claude_path: str, llm_model: str,
                            llm_backend: str, llm_api_key: str | None,
                            seed: int = 0,
                            recent_titles: list[str] | None = None):
    """Görüntü-öncelikli hazırlık: konu → EN sorgu → N AYRIK klip indir → vision ile
    tarif et. Döner (clips, descriptions, queries) — üçü index-hizalı (beat=klip
    garantisinin temeli). Vision kapısı (tür doğru + net) hâlâ uygulanır; ama senaryo
    SONRA yazıldığı için tür-onarım/ikincil-özne/aksiyon-query GEREKSİZLEŞİR."""
    n_clips = _footage_driven_clip_count(reel.target_duration_s)
    sources = build_footage_sources(
        footage_priority or ["pexels"], pexels_key=pexels_api_key,
        pixabay_key=pixabay_api_key)
    footage_deps = FootageDeps(sources=sources)
    clips_cache = work_dir / "clips"
    clips: list[Path] = []
    used_queries: list[str] = []
    used: set[str] = set()
    seen: dict = {}
    kesif_yedek: list = []       # keşfin indirilmemiş adayları (eleme düşüşünde devreye girer)

    # --- KEŞİF: KONU STOKTAN DOĞAR (kullanıcı önerisi, 2026-07-16) ------------
    # Eski akış konuyu önce seçip stok arıyordu → kıt havuz = looplu video (858)
    # ya da üretim düşüşü. Keşif: stok taranır, >=4 ayrık klipli ÖZNE seçilir,
    # konu o kliplerden türetilir. Kurulamazsa eski konu-yoluna düşülür.
    if (getattr(reel, "footage_discovery", True) and vision_call is not None
            and d.discover_subject is not None):
        from short_bot.claude_cli import run_json as _rj

        def _disc_inv(prompt, schema):
            return _rj(prompt, schema, claude_path=llm_claude_path, model=llm_model,
                       backend=llm_backend, api_key=llm_api_key, retries=2)

        # İKİ deneme: ilk öznenin klipleri hareket kapısında erirse (thumbnail
        # hareketi gösteremez — mirket/kartal tünemiş poz dersi) ikinci turda o
        # özneden KAÇINARAK yeniden seçtirilir; o da olmazsa konu-yoluna düşülür.
        denenen_ozneler: list[str] = []
        for _kesif_tur in range(2):
            kesif = None
            try:
                kesif = d.discover_subject(
                    sources=sources, vision_call=vision_call, invoke=_disc_inv,
                    seed=seed + _kesif_tur, recent_titles=recent_titles,
                    avoid_subjects=denenen_ozneler or None)
            except Exception as e:  # noqa: BLE001 — keşif üretimi durdurmaz
                log.warning(f"  reel[keşif]: çöktü ({e}) → konu-yoluna düşülüyor")
            if kesif is None:
                break
            subj, adaylar = kesif
            denenen = 0
            for cand in adaylar:
                denenen += 1
                if len(clips) >= n_clips:
                    denenen -= 1
                    break
                src = next((x for x in sources
                            if getattr(x, "name", "") == cand.source), sources[0])
                try:
                    clip = d.download_candidate(src, cand, clips_cache)
                except Exception:  # noqa: BLE001 — tek aday akışı düşürmesin
                    clip = None
                if clip is None or str(clip) in used:
                    continue
                used.add(str(clip))
                if not _fd_clip_ok(clip, ffmpeg_path):
                    log.info(f"  reel[keşif]: statik/durgun aday atlandı ({clip.name})")
                    continue
                clips.append(clip)
                used_queries.append(subj.subject_en)
            if len(set(map(str, clips))) >= 3:
                topic = subj.topic_tr            # KONU ARTIK STOKTAN
                queries = [subj.subject_en]
                # İNDİRİLMEMİŞ adaylar YEDEK havuz: eleme klip düşürürse önce
                # buradan tamamlanır (panel koşusu dersi: eleme 2'ye düşürünce
                # yedek dururken üretim düşüyordu).
                kesif_yedek.extend(adaylar[denenen:])
                log.info(f"  reel[keşif]: {len(clips)} klip indirildi "
                         f"(+{len(kesif_yedek)} yedek aday) → konu: {topic}")
                break                            # özne oturdu
            denenen_ozneler.append(subj.subject_en)
            log.warning(f"  reel[keşif]: '{subj.subject_en}' yalnız "
                        f"{len(set(map(str, clips)))} ayrık klip verdi → "
                        f"{'ikinci özne denenecek' if _kesif_tur == 0 else 'konu-yoluna düşülüyor'}")
            clips, used_queries, used = [], [], set()
            kesif_yedek.clear()

    if not clips:
        queries = d.footage_search_queries(
            topic, n=n_clips, channel=channel, claude_path=llm_claude_path,
            model=llm_model, backend=llm_backend, api_key=llm_api_key)
        log.info(f"  reel[görüntü-önce]: {n_clips} klip hedefi, sorgular={queries}")

    from short_bot.reel_relevance import build_topic_pool, derive_footage_anchor
    anchor = (getattr(reel, "footage_anchor", "") or "").strip()
    if not anchor:
        tmpl = getattr(getattr(channel, "dna", None), "search_query_template", "") or ""
        anchor = derive_footage_anchor(tmpl)
    topic_pool = build_topic_pool(queries, anchor=anchor)
    topic_q = (topic.split(",")[0].strip()[:40] or "nature")
    context = topic.strip()[:200]

    # N AYRIK klip: sorguları döndürerek indir; exclude ile tekrar önlenir. Bir tam
    # tur boyunca (misses == len(queries)) yeni klip gelmezse havuz tükenmiştir → dur.
    # (Keşif klipleri indirdiyse bu döngü hiç koşmaz — clips zaten dolu.)
    misses = 0
    idx = 0
    max_attempts = n_clips * 4
    # STATİK RED (short 846): görüntü-önce prep'te hareket kontrolü YOKTU — eski
    # akışın reddi order-döngüsünde yaşıyor ve footage-driven onu atlıyor. Statik
    # mantis klibi kapanışta 8.1sn DONUK kare yaptı. Eski akışla aynı ilke: statik
    # atlanır, hiç hareketli çıkmazsa fail-open yedeği kabul edilir.
    statik_yedek: tuple | None = None
    kesif_doldu = bool(clips)     # keşif klipleri indirdiyse konu-yolu döngüsü koşmaz
    while (not kesif_doldu and len(clips) < n_clips
           and idx < max_attempts and misses < len(queries)):
        query = queries[idx % len(queries)]
        idx += 1
        clip, _gated = _match_with_fallback(
            d, query, topic_q=topic_q, api_key=pexels_api_key, cache_dir=clips_cache,
            verify=getattr(reel, "verify_footage", True), vision_call=vision_call,
            footage_deps=_rotate_sources(footage_deps, len(clips)),
            topic_pool=topic_pool, anchor=anchor, ffmpeg_path=ffmpeg_path,
            exclude=used, context=context, seen=seen)
        if clip is None or str(clip) in used:
            misses += 1
            continue
        misses = 0
        used.add(str(clip))
        if not _fd_clip_ok(clip, ffmpeg_path):
            if statik_yedek is None:
                statik_yedek = (clip, query)
            log.info(f"  reel[görüntü-önce]: statik/durgun klip atlandı ({clip.name})")
            continue
        clips.append(clip)
        used_queries.append(query)
    if not clips and statik_yedek is not None:
        clips.append(statik_yedek[0])
        used_queries.append(statik_yedek[1])
        log.warning("  reel[görüntü-önce]: hareketli klip yok → statik kabul "
                    "(donuk kuyruk riski, video yokluğundan yeğdir)")
    if not clips:
        raise RuntimeError(
            f"reel: görüntü-önce — '{topic}' için hiç footage bulunamadı")
    if len(clips) < n_clips:
        log.warning(f"  reel[görüntü-önce]: {len(clips)}/{n_clips} klip bulundu "
                    f"(havuz kıt) → mevcutlarla devam")

    # PARALEL tarif (LOCATE_WORKERS): her klip bağımsız bir vision çağrısı.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=LOCATE_WORKERS) as ex:
        descs = list(ex.map(
            lambda c: _describe_clip(c, vision_call=vision_call,
                                     ffmpeg_path=ffmpeg_path),
            clips))
    if not any(descs):
        log.warning("  reel[görüntü-önce]: vision tarifleri BOŞ (vision kapalı?) → "
                    "senaryo footage'a körlemesine yazılacak (uyum garantisi zayıflar)")
    # --- TARİF-SONRASI ELEME + YERİNE KOYMA (görüntü-önce kalite kapısı) -----
    # Senaryo bu tarifleri ANLATACAK: konu-dışı klip = konu-dışı beat.
    # GERÇEK HATA (short 846): 'bağlama uyan' bataklık b-roll'ü, telefon scroll
    # klibi ve mantis kapıdan geçti → senaryo çöpü anlatıp konudan koptu; boş
    # tarifli klip için beat UYDURULDU ('uydurma' yasağına rağmen). (short 845):
    # kapı 'örümcek ≈ atlayan örümcek' saydı → 3/5 klip ağ ören örümcekti.
    # Burada tarif düzeyinde elenir; yerine DÜZ ÖZNE sorgusuyla (queries[0],
    # sıkı kapı) klip aranır — 846'da q0 havuzunda 6 GERÇEK okçu balığı klibi
    # dururken çöp b-roll kabul edilmişti. Bulunamazsa klip DÜŞER: az ama konulu
    # klip, çok ama çöp klipten yeğdir (döngüsel tamamlama 3'ün altını önler).
    if vision_call is not None and any((x or "").strip() for x in descs):
        from short_bot.claude_cli import run_json
        from short_bot.footage_matcher import find_offsubject_clips
        with ThreadPoolExecutor(max_workers=LOCATE_WORKERS) as ex:
            tails = list(ex.map(
                lambda c: _describe_clip(c, vision_call=vision_call,
                                         ffmpeg_path=ffmpeg_path, tail_s=2.0),
                clips))

        def _inv(prompt, schema):
            return run_json(prompt, schema, claude_path=vision_call.claude_path,
                            model=vision_call.model, backend=vision_call.backend,
                            api_key=vision_call.api_key, retries=1, timeout_s=45)

        atilan = set(find_offsubject_clips(
            descs, tails, f"{topic} (EN: {queries[0]})", invoke=_inv))
        atilan |= {i for i, x in enumerate(descs) if not (x or "").strip()}
        def _yedekten_klip():
            """Keşfin indirilmemiş adaylarından bir sonraki KULLANILABİLİR klip.

            Panel koşusu dersi: eleme klipleri düşürünce yedek adaylar dururken
            üretim düşüyordu. Aynı özneden, zaten LLM'in seçtiği kliplerdir —
            düz-sorgu aramasından daha isabetli ve daha ucuz."""
            while kesif_yedek:
                cand = kesif_yedek.pop(0)
                src = next((x for x in sources
                            if getattr(x, "name", "") == cand.source), sources[0])
                try:
                    aday = d.download_candidate(src, cand, clips_cache)
                except Exception:  # noqa: BLE001 — tek aday akışı düşürmesin
                    aday = None
                if (aday is None or str(aday) in used
                        or not _fd_clip_ok(aday, ffmpeg_path)):
                    continue
                aday_desc = _describe_clip(aday, vision_call=vision_call,
                                           ffmpeg_path=ffmpeg_path)
                if not aday_desc.strip():
                    continue
                return aday, aday_desc
            return None, ""

        dusen: list[int] = []
        for i in sorted(atilan):
            log.info(f"  reel[görüntü-önce]: klip {i} konu-dışı/tarifsiz "
                     f"('{(descs[i] or '')[:40]}') → yenileniyor")
            # 1) Önce keşfin YEDEK adayları (aynı özneden, seçilmiş klipler).
            yeni, yeni_desc = _yedekten_klip()
            if yeni is not None:
                used.add(str(yeni))
                clips[i], descs[i], used_queries[i] = yeni, yeni_desc, queries[0]
                log.info(f"  reel[keşif]: klip {i} yedek adayla değiştirildi")
                continue
            # 2) Yedek yoksa düz özne sorgusuyla sıkı-kapılı arama.
            yeni = d.match_beat_clip(
                queries[0], api_key=pexels_api_key, cache_dir=clips_cache,
                verify=getattr(reel, "verify_footage", True),
                vision_call=vision_call, deps=footage_deps,
                topic_pool=topic_pool, ffmpeg_path=ffmpeg_path,
                budget={"gate": 0, "dl": 0}, exclude=used, context=context,
                seen=seen, bank=[], hook=False)
            yeni_desc = (_describe_clip(yeni, vision_call=vision_call,
                                        ffmpeg_path=ffmpeg_path)
                         if yeni is not None else "")
            if (yeni is not None and yeni_desc.strip()
                    and _fd_clip_ok(yeni, ffmpeg_path)):
                used.add(str(yeni))
                clips[i], descs[i], used_queries[i] = yeni, yeni_desc, queries[0]
            else:
                dusen.append(i)
        for i in reversed(dusen):
            log.warning(f"  reel[görüntü-önce]: klip {i} elendi, yerine konulu "
                        f"klip yok → düşürüldü (az ama konulu > çok ama çöp)")
            del clips[i]
            del descs[i]
            del used_queries[i]
        if not clips:
            raise RuntimeError(
                f"reel: görüntü-önce — '{topic}' için KONUDA klip kalmadı "
                f"(hepsi konu-dışı/tarifsiz elendi)")
    # MİN 3 AYRIK KLİP — YOKSA ÜRETİM DÜŞER. Eski kural klipleri döngüsel kopyalayıp
    # 3'e tamamlıyordu ('video yokluğundan yeğdir'). GERÇEK HATA (short 858, kullanıcı
    # yakaladı: 'aynı görüntü sürekli looplanmış'): havuz 1 klibe düşünce o tek klip
    # 15 alt-kesim boyunca loop'landı. Looplu video, video yokluğundan YEĞ DEĞİL —
    # izleyicide 'bozuk kanal' izlenimi bırakır. Net hatayla düş; konu/slot başka
    # koşuda taze konuyla değerlendirilir.
    MIN_FD_DISTINCT = 3
    ayrik = len(set(map(str, clips)))
    if ayrik < MIN_FD_DISTINCT:
        raise RuntimeError(
            f"reel: görüntü-önce — '{topic}' için yalnız {ayrik} ayrık konulu klip "
            f"bulundu (en az {MIN_FD_DISTINCT} gerekir). Tekrarlı/looplu video "
            f"üretmek yerine düşülüyor; stok havuzu bu konu için kıt.")
    log.info(f"  reel[görüntü-önce]: {len(clips)} klip tarif edildi ({ayrik} ayrık)")
    return clips, descs, used_queries, topic


def produce_reel_video(
    *, topic: str, channel, templates_dir: Path, work_dir: Path,
    out_path: Path, music_path: Path | None, ai33_api_key: str,
    pexels_api_key: str, pixabay_api_key: str = "",
    footage_priority: list | None = None,
    ffmpeg_path: str = "ffmpeg", fps: int = 30,
    browser: str = "chromium",
    llm_claude_path: str = "claude", llm_model: str = "default",
    llm_backend: str = "claude_cli", llm_api_key: str | None = None,
    whisper_quality: str = "auto", whisper_device: str = "auto",
    vision_call=None, seed: int = 0, deps: ReelDeps | None = None,
    cancel_check=None,   # panelden iptal edildiyse faz sınırında dur
    hook_patterns=None, assets_root: Path | None = None,
    episode=None,        # EpisodePlan — seri/cliffhanger mimarisi (bkz. reel_series)
    on_narration=None,   # callback(narration): açık kapıyı çağırana bildir (ark zinciri)
    recent_titles: list[str] | None = None,   # keşif tekrar-önleme (son video başlıkları)
) -> Path:
    reel = getattr(channel, "reel", None)
    if reel is None or not reel.enabled:
        raise ValueError("produce_reel_video: channel.reel etkin değil")
    d = deps or ReelDeps()
    work_dir = Path(work_dir); work_dir.mkdir(parents=True, exist_ok=True)
    # SFX/müzik/kurgu kütüphanesinin kökü. Paketlenmiş uygulamada music_root
    # taşınabilir olduğu için çağıran (pipeline) music_root.parent'ı geçirir.
    assets_root = Path(assets_root) if assets_root else Path("assets")

    # Varyasyon profili (deterministik: aynı seed → aynı profil). Reel etkin
    # kontrolünden SONRA hesaplanır; saf fonksiyon (çağrı zincirine girmez).
    from short_bot.reel_variation import build_variation_profile
    profile = build_variation_profile(channel, seed)

    # FEED KİMLİĞİ KİLİDİ: aksan rengi ve yerleşim per-video DÖNMESİN. Varyasyon
    # motoru bunları döndürüyordu (otomasyon parmak izini kırmak için) ama aynı
    # hamle TANINMAYI da siliyordu: yüzü olmayan bir kanalın kimliği FONT, RENK ve
    # YERLEŞİMDİR. Çeşitlilik ölmüyor — izleyicinin tanımak için kullanmadığı
    # alanlara (efekt/SFX/marker/müzik/tempo) taşınıyor.
    from short_bot.reel_identity import lock_profile
    if getattr(reel, "identity_lock", True):
        profile = lock_profile(profile, channel)

    # Abone bitleri. ``episode`` verilirse SERİ modu: bölüm numarası, ödenecek söz,
    # açılacak kapı ve TAKAS CTA'sı (bkz. reel_series).
    from short_bot.reel_subscribe import build_subscribe_bits
    bits = build_subscribe_bits(channel, seed, episode=episode)
    if episode is not None:
        log.info(f"  reel: BÖLÜM #{episode.episode_no} (ark {episode.arc_pos})"
                 + (f" — önceki sözü ödüyor: '{episode.continue_from[:60]}'"
                    if episode.continue_from else " — yeni ark"))

    # Faz zamanlayıcı: hangi aşama ne kadar sürdü (üretim yavaşlığı teşhisi).
    import time as _time
    _t0 = _time.perf_counter()
    _phase_t = {}

    def _phase(name: str) -> None:
        # İPTAL: kullanıcı panelden durdurduysa bir sonraki fazı BAŞLATMA. Footage
        # gibi uzun bir faz ortasında kesemeyiz ama sınırda durmak, yanan LLM/TTS/
        # vision kredisini ve dakikaları kurtarır.
        if cancel_check is not None and cancel_check():
            raise RunCancelled("üretim panelden iptal edildi")
        nonlocal _t0
        dt = _time.perf_counter() - _t0
        _phase_t[name] = dt
        _t0 = _time.perf_counter()
        log.info(f"  reel[süre] {name}: {dt:.1f}s")

    # 1) Preflight (LLM/TTS kredisi harcamadan). GEÇİCİ kesintiyi yeniden dene:
    # ai33 üç kez "yanıt vermiyor" deyip koşuyu düşürdü, hemen ardından elle
    # kontrolde SAĞLIKLI çıktı. "error"/"stalled" geçicidir; "auth"/"no-key"/
    # "no-voice" KALICIDIR — onlarda beklemenin faydası yok, anında dur.
    verdict = ""
    for attempt in range(1, PREFLIGHT_RETRIES + 1):
        verdict = d.health_check(voice_id=reel.voice_id, api_key=ai33_api_key,
                                 tmp_dir=work_dir)
        if verdict == "healthy" or verdict not in _PREFLIGHT_TRANSIENT:
            break
        if attempt < PREFLIGHT_RETRIES:
            wait = PREFLIGHT_BACKOFF_S * attempt
            log.warning(f"  reel: ai33 preflight '{verdict}' (deneme {attempt}/"
                        f"{PREFLIGHT_RETRIES}) → {wait}sn sonra yeniden")
            _time.sleep(wait)
    if verdict != "healthy":
        raise RuntimeError(_PREFLIGHT.get(verdict, f"ai33 preflight: {verdict}"))
    log.info("  reel: ai33 preflight healthy")
    _phase("preflight")

    # GÖRÜNTÜ-ÖNCELİKLİ MOD (flag; varsayılan KAPALI = SIFIR REGRESYON). Açıkken
    # footage ÖNCE indirilir + vision ile tarif edilir; senaryo o tariflere UYAR
    # (vision-ses uyumu matematiksel garanti). Kapalıyken bu blok ATLANIR ve akış
    # bugünküyle BİREBİR aynıdır (write_reel_narration + footage döngüsü).
    footage_driven = bool(getattr(reel, "footage_driven", False))
    fd_clips: list = []
    fd_descs: list = []
    fd_queries: list = []
    if footage_driven:
        log.info("  reel: GÖRÜNTÜ-ÖNCELİKLİ mod açık — footage önce, senaryo sonra")
        fd_clips, fd_descs, fd_queries, fd_topic = _prepare_footage_driven(
            topic=topic, channel=channel, reel=reel, d=d, work_dir=work_dir,
            pexels_api_key=pexels_api_key, pixabay_api_key=pixabay_api_key,
            footage_priority=footage_priority,
            vision_call=vision_call, ffmpeg_path=ffmpeg_path,
            llm_claude_path=llm_claude_path, llm_model=llm_model,
            llm_backend=llm_backend, llm_api_key=llm_api_key,
            seed=seed, recent_titles=recent_titles)
        # KEŞİF konuyu stoktan türettiyse senaryo/manşet/başlık o konudan yazılır.
        topic = fd_topic
        _phase("footage-önce(indir+tarif)")

    # 2) Senaryo
    if footage_driven:
        # Senaryo ELDEKİ footage tariflerine göre yazılır (beat=klip garanti).
        if getattr(reel, "curiosity_pipeline", True):
            # MERAK MİMARİSİ: 3 aday → yargıç → doktor. perm = beat→orijinal-klip
            # permütasyonu (dramaturji sırası); klipler ona göre yeniden dizilir.
            narration, _fd_perm = d.write_curious_narration(
                topic, fd_descs, fd_queries, channel=channel,
                claude_path=llm_claude_path, model=llm_model,
                backend=llm_backend, api_key=llm_api_key, seed=seed)
            if (_fd_perm != list(range(len(_fd_perm)))
                    and len(_fd_perm) == len(fd_clips)):
                fd_clips = [fd_clips[j] for j in _fd_perm]
                fd_descs = [fd_descs[j] for j in _fd_perm]
                fd_queries = [fd_queries[j] for j in _fd_perm]
        else:
            narration = d.write_footage_driven_narration(
                topic, fd_descs, fd_queries, channel=channel,
                claude_path=llm_claude_path, model=llm_model,
                backend=llm_backend, api_key=llm_api_key, seed=seed)
    else:
        narration = d.write_reel_narration(topic, channel=channel,
                                           claude_path=llm_claude_path, model=llm_model,
                                           backend=llm_backend, api_key=llm_api_key,
                                           hook_angle=profile.hook_angle,
                                           series_directive=bits.series_directive,
                                           comment_line=bits.comment_line,
                                           hook_patterns=hook_patterns, seed=seed)
    log.info(f"  reel: {narration.word_count()} kelime, {len(narration.beats)} beat")
    # Manşet KONUŞULMAZ (senaryo logunda görünmez) ama feed'in küçük resmi ODUR —
    # videonun izlenip izlenmeyeceğine orada karar veriliyor. Loglanmazsa sonradan
    # "o karede ne yazıyordu" sorusunu yanıtlayacak hiçbir kayıt kalmaz.
    if narration.cover_title:
        log.info(f"  reel: kare-sıfır manşeti: '{narration.cover_title}'")
    else:
        log.warning("  reel: manşet YOK → küçük resimde hook CÜMLESİ görünecek "
                    "(feed boyutunda okunmaz)")
    # AÇIK KAPI çağırana BURADA bildirilir — montaj başarısız olsa bile bir sonraki
    # bölümün konu tohumu kaybolmasın diye değil; tam tersine, çağıran onu ancak
    # üretim BAŞARILI olunca kaydeder (bkz. pipeline). Burada yalnız taşıyoruz.
    if episode is not None:
        if narration.open_loop:
            log.info(f"  reel: açık kapı → #{episode.next_no}: "
                     f"'{narration.open_loop}'"
                     + ("" if narration.open_loop_spoken()
                        else "  ⚠ VAAT KONUŞULMUYOR (abone takası çalışmayacak)"))
        else:
            log.warning("  reel: açık kapı KURULAMADI → bu bölüm seriyi ilerletmiyor, "
                        "abone isteği takas değil rica olarak düşecek")
    # Anlatım çağırana HER ZAMAN bildirilir (episode olsun olmasın): başlık + açık
    # kapı gibi anlatım-türevi alanlar seri-DIŞI reel'de de çağırana lazım (SEO
    # başlığı + dosya adı anlatımın 'title' alanından gelir).
    if on_narration is not None:
        on_narration(narration)
    _phase("senaryo(LLM)")

    # 2b) AI KURGUCU: anlatımı okuyup kurgu kararlarını verir (tempo, kesme efekti,
    # kesim başına SFX kategorisi, müzik ruh hali, marker, layout). Profil yeniden
    # kurulur — planın DOLU alanları seed-hash'i ezer, boş alanlar eskiye düşer.
    # Kurgucu kapalı / kütüphane boş / LLM hatası → plan None → tamamen eski davranış.
    edit_plan = None
    if getattr(reel, "ai_director", True):
        from short_bot.assets_library import load_library_index
        from short_bot.reel_director import plan_edit

        class _LC:   # plan_edit'in beklediği llm_call taşıyıcısı
            claude_path = llm_claude_path; model = llm_model
            backend = llm_backend; api_key = llm_api_key

        # Kesim sayısı ancak tempo seçildikten sonra netleşir; prompt için kaba
        # tahmin yeter (sfx_plan döngüsel kullanılır, uzunluk kritik değil).
        est_cuts = max(4, len(narration.beats) * 3)
        from short_bot.persona import channel_director_guidance
        edit_plan = plan_edit(narration, topic=topic, n_cuts=est_cuts,
                              library_index=load_library_index(assets_root),
                              llm_call=_LC(),
                              persona_hint=channel_director_guidance(
                                  getattr(reel, "persona", ""), channel.language))
        if edit_plan is not None:
            profile = build_variation_profile(channel, seed, edit_plan=edit_plan)
        _phase("kurgucu(LLM)")

    # 3) TTS + 4) süre/hizalama — SADAKAT DENETİMİ İKİSİNİ BİRBİRİNE BAĞLAR.
    # ai33 metnin bir öbeğini okumadan geçebiliyor: hata dönmüyor, ses geçerli,
    # süresi bile normal. Altyazılar senaryodan üretildiği için okunmamış kelimeler
    # ekranda görünmeye devam eder ve video ileri zıplamış gibi olur.
    #
    # İKİ BAĞIMSIZ İŞARETE bakılır, çünkü tek başına ikisi de kandırılabiliyor:
    #   • SONDAKİ SESSİZLİK — öbek düşünce ai33 dosyayı sessizlikle dolduruyor.
    #     Ölçüldü: sağlam 0.00sn, bozuk 3.4/3.8/6.9sn. whisper'dan bağımsızdır.
    #   • OKUNMAYAN ÖBEK — duyulan metin senaryoyla kıyaslanır (bkz. tts/fidelity).
    # İkincisi tek başına yetmedi: whisper sessizlikte metin UYDURUP denetimi
    # geçirdi (gerçek hata, short 759) — bu yüzden sessizlik ölçüsü şart.
    script = narration.full_text()
    mp3 = work_dir / "narration.mp3"
    # Senaryo ve duyulan metin LOGA yazılır: anlatım geçici dizinde üretilip silindiği
    # için, sonradan "video neyi söyledi, neyi söylemedi" sorusunu ancak log yanıtlar.
    log.info(f"  reel[ses] senaryo: {script}")
    for attempt in range(1, TTS_FIDELITY_RETRIES + 2):
        d.synthesize(script, voice_id=reel.voice_id, api_key=ai33_api_key,
                     out_path=mp3, speed=reel.speed)
        _phase("tts(ai33)")

        duration_s = d.probe_duration_s(mp3, ffprobe_path="ffprobe")
        tail = d.trailing_silence_s(mp3, duration_s=duration_s, ffmpeg_path=ffmpeg_path)
        words = d.transcribe_words(mp3, language=channel.language,
                                   quality=whisper_quality, device=whisper_device)
        _phase("whisper-hizalama")

        heard = " ".join(w.word for w in words)
        drop = worst_drop(script, heard, channel.language) if words else None
        log.info(f"  reel[ses] duyulan: {heard}")
        log.info(f"  reel[ses] sonda sessizlik: {tail:.1f}sn | en uzun bitişik kayıp: "
                 + (f"{drop.count} kelime" + (f" → '{drop.phrase}'" if drop.count else "")
                    if drop else "ölçülemedi (whisper kelime çıkaramadı)"))

        bad = tail > TTS_MAX_TAIL_S or (drop is not None and not drop.ok)
        if not bad:
            break
        why = (f"{tail:.1f}sn sessizlik bıraktı" if tail > TTS_MAX_TAIL_S
               else f"{drop.count} kelime okumadı ('{drop.phrase}')")
        if attempt <= TTS_FIDELITY_RETRIES:
            log.warning(f"  reel: TTS {why} → yeniden seslendiriliyor "
                        f"({attempt}/{TTS_FIDELITY_RETRIES})")
        else:
            # Üst üste başarısız: ses eksik ama video üretmemektense kusurlu üretmek
            # yeğdir. Ölü hava aşağıda yine de kesilir.
            log.warning(f"  reel: TTS sadakati sağlanamadı ({why}), mevcut ses kullanılıyor")

    # ÖLÜ HAVAYI KES: montaj -t duration_s ile hem videoyu hem sesi burada bitirir.
    # Konuşmasız saniyeler izleyiciye videonun bittiğini söyler ve döngüyü kırar;
    # ayrıca altyazılar o sessizliğe yayılıp sesin gerisine düşer.
    if tail > TAIL_KEEP_S:
        kirpilan = tail - TAIL_KEEP_S
        duration_s -= kirpilan
        log.info(f"  reel[ses] sondaki {kirpilan:.1f}sn ölü hava kesildi "
                 f"→ video {duration_s:.1f}sn")

    timeline = build_reel_timeline(narration, words, duration_s=duration_s)

    # TEMPO BÖLGELERİ: hook hızlı → gövde sabit → TEPE yavaş → gövde sabit.
    # TTS baştan sona tek hızda okur; insan anlatıcı okumaz. Açılışta hızlıdır
    # (izleyici ilk saniyede kalma kararını verir), açıklamada yavaşlar (ağırlık verir).
    # Yeniden seslendirmiyoruz: mp3'ü bölge bölge atempo'yla geriyoruz ve kelime
    # zamanlarını PARÇALI-DOĞRUSAL olarak kesin yeniden eşliyoruz (bkz. reel_tempo).
    # ASR ŞART — duraklamadaki gerekçenin aynısı: kelime zamanı yoksa bölge sınırları
    # oransal tahmindir ve hız değişimi bir hecenin ORTASINA düşer (duyulur bir kayma).
    # DURAKLAMADAN ÖNCE koşar: duraklama noktası bu yeni çizelgeden okunmalı.
    if words and getattr(reel, "tempo_zones", True):
        zones = plan_zones(timeline.seg_spans, peak_seg=narration.peak_segment(),
                           duration_s=duration_s)
        if zones:
            try:
                mp3 = d.retime(mp3, work_dir / "narration_tempo.mp3", zones,
                               ffmpeg_path=ffmpeg_path)
                words = remap_words(words, zones)
                yeni = retimed_duration_s(zones)
                log.info(f"  reel[ses] tempo bölgeleri: hook ×{zones[0].tempo:g}, "
                         f"tepe ×{zones[2].tempo:g} ({zones[2].start_s:.1f}-"
                         f"{zones[2].end_s:.1f}s) → süre {duration_s:.1f} → {yeni:.1f}sn")
                duration_s = yeni
                timeline = build_reel_timeline(narration, words, duration_s=duration_s)
            except Exception as e:   # tempo KOZMETİK — üretimi düşürmemeli
                log.warning(f"  reel: tempo bölgeleri uygulanamadı ({e}) → tek tempo")

    # TEPE ÖNCESİ DURAKLAMA. Anlatım baştan sona aynı tempoda akıyordu; insan
    # anlatıcı ise en büyük açıklamadan hemen önce SUSAR — o sessizlik "şimdi bir
    # şey gelecek" der. Kesintisiz ses vurguyu düzleştirir, tepe cümlelerin
    # arasında kaybolur.
    # Yeniden seslendirmiyoruz (her ek ai33 çağrısı kredi + yeni arıza yüzeyi):
    # mp3'e sessizlik enjekte edip kelime zamanlarını KESİN olarak kaydırıyoruz.
    # ASR ŞART: kelime zamanları yoksa segment sınırları ORANSAL TAHMİNDİR ve
    # sessizlik bir kelimenin ORTASINA düşebilir. Tahmine göre ses kesmeyiz.
    peak_seg = narration.peak_segment()
    pause_at = (timeline.seg_spans[peak_seg][0]
                if words and 0 < peak_seg < len(timeline.seg_spans) else 0.0)
    if pause_at >= MIN_PAUSE_AT_S:
        paused = work_dir / "narration_paced.mp3"
        try:
            mp3 = d.insert_pause(mp3, paused, at_s=pause_at,
                                 dur_s=REVEAL_PAUSE_S, ffmpeg_path=ffmpeg_path)
            words = shift_words(words, pause_at, REVEAL_PAUSE_S)
            duration_s += REVEAL_PAUSE_S
            timeline = build_reel_timeline(narration, words, duration_s=duration_s)
            log.info(f"  reel[ses] tepe öncesi {REVEAL_PAUSE_S:.2f}sn duraklama "
                     f"@ {pause_at:.1f}s (beat {narration.peak_beat})")
        except Exception as e:   # duraklama KOZMETİK — üretimi düşürmemeli
            log.warning(f"  reel: tepe duraklaması eklenemedi ({e}) → duraklamasız devam")

    log.info(f"  reel: ses {duration_s:.1f}s, {len(timeline.words)} kelime")

    # 5) Beat başına footage (+ belirteç-uygun segmentlerde nesne konumu)
    # Öncelik-sıralı kaynak zinciri (Pexels + opsiyonel Pixabay): biri bulamazsa
    # sıradaki denenir. Anahtarları olmayan kaynaklar atlanır.
    sources = build_footage_sources(
        footage_priority or ["pexels"],
        pexels_key=pexels_api_key, pixabay_key=pixabay_api_key)
    footage_deps = FootageDeps(sources=sources)
    # Konu-havuzu + kanal çıpası (footage alaka gate'i için). Çıpa boşsa
    # dna.search_query_template'ten İngilizce token türetilir (ör. "whale ocean").
    from short_bot.reel_relevance import build_topic_pool, derive_footage_anchor
    anchor = (getattr(reel, "footage_anchor", "") or "").strip()
    if not anchor:
        tmpl = getattr(getattr(channel, "dna", None), "search_query_template", "") or ""
        anchor = derive_footage_anchor(tmpl)
    topic_pool = build_topic_pool([b.visual_query for b in narration.beats], anchor=anchor)
    log.info(f"  reel: footage anchor='{anchor}' | queries={[b.visual_query for b in narration.beats]}")
    log.info(f"  reel: topic_pool={sorted(topic_pool) if topic_pool else None}")
    clips_cache = work_dir / "clips"
    seg_positions: list[SubjectPos] = []
    _first_q = next((q for q in timeline.seg_queries if q), "abstract background")
    _last_q = next((q for q in reversed(timeline.seg_queries) if q), _first_q)
    _topic_q = (topic.split(",")[0].strip()[:40] or "nature")
    # BAĞLAM: gate'e videonun GERÇEK konusu verilir. Anlatım metafor kullanınca
    # ("görünmez savaşçılar" = bakteriyofaj) sorgu metafora kayabiliyor ve stok
    # kütüphane kelimeyi düz anlıyor → bakteriyofaj videosuna ESKRİMCİ geldi.
    # Bağlamla vision "bu klip bu videoya ait mi?" diye de bakar.
    # BAĞLAM = KONU. Hook'u BURAYA KATMA: hook metaforik olabilir ("bir geminin
    # mürettebatı..." = tırtıl) ve içindeki kelime bağlama sızınca kapı GERÇEK BİR
    # GEMİYİ 'bağlamda' sayar — metaforu elemesi gereken mekanizma metaforu
    # MEŞRULAŞTIRIR (gerçek hata: short_id=745, 39sn'nin 13'ü Boğaz'da gemi).
    _video_context = topic.strip()[:200]
    # Belirteç-uygun segmentleri ÖNCE hesapla → yalnız onlarda vision konum çağır
    # (hook/close ve 'off'/kapalı durumda gereksiz vision maliyeti yok).
    n_segs = len(timeline.seg_queries)
    worthy = (set(_marker_worthy_segs(n_segs, reel.arrow_frequency))
              if reel.arrows_enabled else set())
    # SIRA: önce BEAT'ler, sonra hook + close. Böylece hook'un kendi sorgusu
    # kapıdan geçemezse konudaki bir beat klibine düşer — çıpa-çöpüne değil
    # (gerçek şikâyet: "ilk girişteki görüntü alakasız" → tablo pazarı).
    order = list(range(1, max(1, n_segs - 1))) + [0] + (
        [n_segs - 1] if n_segs > 1 else [])
    # ALT-KESİM PLANI footage'dan ÖNCE hesaplanır: bir segment kaç kesim alacaksa
    # o kadar klip çekilir. Eskiden hook/close'a KOŞULSUZ 1 klip veriliyordu; hook
    # 4 alt-kesime yayıldığında aynı görüntü 4 kesim üst üste ekranda kalıyordu.
    # MERAK RAMPASI: curiosity açıkken kesim temposu tepeye doğru sıkışır.
    _peak_ramp_s = None
    if footage_driven and getattr(reel, "curiosity_pipeline", True):
        _ps = narration.peak_segment()
        if 0 <= _ps < len(timeline.seg_spans):
            _peak_ramp_s = timeline.seg_spans[_ps][1]
    if getattr(reel, "fast_cuts", True):
        subcuts = plan_subcuts(timeline.seg_spans, timeline.words,
                               profile.cut_pacing, peak_s=_peak_ramp_s)
    else:
        subcuts = [(i, a, b) for i, (a, b) in enumerate(timeline.seg_spans)]
    cuts_in_seg: dict[int, int] = {}
    for si, _a, _b in subcuts:
        cuts_in_seg[si] = cuts_in_seg.get(si, 0) + 1
    # Segment başına en fazla 3 klip (tarama bütçesi): daha fazlası üretimi yavaşlatır.
    MAX_CLIPS_PER_SEG = 3 if getattr(reel, "fast_cuts", True) else 1
    clips_by_seg: dict[int, list[Path]] = {}
    pos_by_seg: dict[int, SubjectPos] = {}
    # KAPANIŞ visual_loop yalnız KISA kapanışlarda güvenli. Uzun kapanışta (ozan
    # imzası + close) tek hook klibi loop edilince DONUK kuyruk oluyor (short 821:
    # 12sn kapanış → 12sn freeze). Uzunsa visual_loop atlanır, kapanış KENDİ
    # hareketli kliplerini kullanır (loop hissini süreye feda et — donuk kabul edilemez).
    KAPANIS_LOOP_MAX_S = 5.0
    # Statik footage reddi bu eşiğin ÜSTÜNDEKİ klip-başına-sürede devreye girer
    # (donuk kuyruk uzun kliplerde görünür; kısa hızlı-kesim kliplerinde görünmez).
    # Reddi kısa kliplere uygulamak boşuna yeniden-indirme → footage darboğazı (short 826).
    STATIK_RED_MIN_S = 4.0
    _kap_span = (timeline.seg_spans[-1][1] - timeline.seg_spans[-1][0]
                 if len(timeline.seg_spans) > 1 else 0.0)
    _kapanis_loop = getattr(reel, "visual_loop", True) and _kap_span <= KAPANIS_LOOP_MAX_S
    # VİDEO GENELİNDE kullanılmış klipler. Eskiden bu küme her segmentin başında
    # sıfırlanıyordu; sorgular birbirine benzediği için arama HER segmentte aynı
    # "en iyi" klibi döndürüyordu → 6 klipli havuzdan 3 klip çıkıyor, video
    # tek görüntüye kilitleniyordu (short_id=171).
    used_clips: set[str] = set()
    # Tekrar havuzu: yalnız vision kapısından GEÇEN klipler. Doğrulanmamış son-çare
    # klibi buraya girmez — yoksa tek çöp görüntü tüm videonun çıpası olur.
    reuse_pool: list[Path] = []
    reuse_idx = 0
    # Video-geneli vision yargı önbelleği: aynı aday İKİ KEZ yargılanmaz. Gerçek
    # koşuda 67 vision çağrısının çoğu aynı martı/pelikan/kelebek döngüsüydü;
    # bütçe onlara gidince YENİ adaylara hiç sıra gelmiyordu.
    seen_verdicts: dict = {}
    # GÖRÜNTÜ-ÖNCELİKLİ: klipler ZATEN indirildi (senaryo öncesi). Her segmente
    # hazır klibi ata (beat=klip) ve segment döngüsünü ATLA (order boşaltılır).
    # Mevcut senaryo-önce döngüsü BİREBİR korunur — yalnızca boş order ile çalışmaz.
    if footage_driven:
        for si in range(n_segs):
            clips_by_seg[si] = [_footage_driven_seg_clip(fd_clips, si, n_segs)]
        log.info(f"  reel[görüntü-önce]: {n_segs} segment ↔ {len(fd_clips)} klip eşlendi")
        order = []
    for si in order:
        query = timeline.seg_queries[si]
        if query is None:
            # hook/close kendi sorgusunu vermediyse ilk/son beat'inkini ödünç al
            query = _first_q if si == 0 else _last_q
        _seg_t0 = _time.perf_counter()
        # Kapanış görsel-loop'ta hook'un klibini alacak → ona klip aramaya gerek yok.
        is_close = si == n_segs - 1 and n_segs > 1
        want = (1 if is_close and _kapanis_loop
                else min(MAX_CLIPS_PER_SEG, max(1, cuts_in_seg.get(si, 1))))
        got: list[Path] = []
        # STATİK KLİP REDDİ (short 818): hareketsiz footage uzun segmentte DONUK
        # kuyruk yapar (kapanış 14sn statik klip → 9sn freeze; Ken Burns kurtarmıyor).
        # AMA statik reddi YALNIZ UZUN KLİPLERDE gerekli: her red bir YENİ İNDİRME
        # tetikliyor; statik konularda (timsah pusu — hareketsiz footage) her segment
        # want+4 kez indiriyordu → footage aşaması 33 DK (ölçüldü, short 826). Hızlı
        # kesim segmentlerinde klip 2-3sn; statik olsa bile freeze GÖRÜNMEZ, o yüzden
        # reddedip yeniden indirmek boşuna. Reddi klip-başına-süre uzunsa (kapanış gibi)
        # uygula; kısa kliplerde İLK adayı kabul et (retry yok → darboğaz kalkar).
        _span = (timeline.seg_spans[si][1] - timeline.seg_spans[si][0]
                 if si < len(timeline.seg_spans) else 0.0)
        _klip_suresi = _span / max(1, want)
        _statik_red = _klip_suresi > STATIK_RED_MIN_S
        statik_yedek: Path | None = None
        deneme = 0
        while len(got) < want and deneme < (want + 4 if _statik_red else want):
            deneme += 1
            clip, gated = _match_with_fallback(
                d, query, topic_q=_topic_q, api_key=pexels_api_key,
                cache_dir=clips_cache, verify=reel.verify_footage,
                vision_call=vision_call,
                # Round-robin: her segment farklı API'den başlasın (çeşitlilik,
                # tekrar azalır).
                footage_deps=_rotate_sources(footage_deps, si),
                topic_pool=topic_pool, anchor=anchor, ffmpeg_path=ffmpeg_path,
                budget={"gate": 0, "dl": 0},
                reuse_clips=reuse_pool, reuse_idx=reuse_idx,
                exclude=set(used_clips),
                context=_video_context, seen=seen_verdicts,
                # HOOK: videonun en kritik karesi — ek "çarpıcılık" eşiği.
                # Alakalı+net ama SIKICI bir açılış karesi, TTS ilk kelimesini
                # söylemeden kaydırılır (gerçek hata: 4sn boyunca boş karanlık resif).
                hook=(si == 0))
            if clip is None or clip in got:
                break        # yeni klip gelmedi → mevcutlarla yetin (fail-open)
            used_clips.add(str(clip))   # denenen klip TEKRAR gelmesin (statik dahil)
            if _statik_red and measure_motion(clip, ffmpeg_path) < MOTION_MIN:
                if statik_yedek is None:
                    statik_yedek = clip   # hareketli çıkmazsa fail-open yedeği
                continue                  # statik → sıradaki adayı dene
            if clip in reuse_pool:
                reuse_idx += 1          # tekrar kullanıldı → sıradakine geç
            elif gated:
                reuse_pool.append(clip)  # yalnız doğrulanmış klip çıpa olabilir
            got.append(clip)
        if not got and statik_yedek is not None:
            got.append(statik_yedek)     # fail-open: hareketli yok → statik kabul
            log.warning(f"  seg{si}: hareketli footage bulunamadı → statik kabul "
                        f"(donuk kuyruk riski)")
        if not got:
            raise RuntimeError(f"reel: '{query}' için footage bulunamadı (segment {si}).")
        log.info(f"  reel[süre] footage seg{si} ('{query[:30]}'): {len(got)} klip, "
                 f"{_time.perf_counter() - _seg_t0:.1f}s")
        clips_by_seg[si] = got
    # RENDER-ÖNCESİ TÜR-TUTARLILIK DOĞRULAMASI (kullanıcı isteği): render pahalı;
    # seçilmiş klipleri TOPLUCA görüp yanlış TÜRÜ (great hornbill yerine turaco)
    # render'dan ÖNCE yakala + o klibi YENİDEN SEÇ. Klip-başına vision kapısı
    # 'hornbill'i geçiriyor ama tür-içi tutarlılığı görmüyordu (biri diğerini kilitlemez).
    if (not footage_driven and getattr(reel, "verify_footage", True)
            and vision_call is not None and len(clips_by_seg) >= 2):
        try:
            _repair_footage_types(
                clips_by_seg, topic=topic, seg_queries=timeline.seg_queries, d=d,
                vision_call=vision_call, footage_deps=footage_deps,
                topic_pool=topic_pool, anchor=anchor, ffmpeg_path=ffmpeg_path,
                pexels_api_key=pexels_api_key, clips_cache=clips_cache,
                used_clips=used_clips, seen=seen_verdicts, verify=reel.verify_footage)
        except Exception as e:  # noqa: BLE001 — doğrulama render'ı durdurmamalı
            log.warning(f"  render-öncesi tür doğrulaması atlandı ({e})")
    # GÖRSEL LOOP: kapanış klibi = hook klibi → video başa sarınca sahne zıplamaz.
    # (tür-onarımından SONRA: kapanış her zaman hook'un DOĞRULANMIŞ klibini alsın.)
    if not footage_driven and _kapanis_loop and n_segs > 1 and 0 in clips_by_seg:
        clips_by_seg[n_segs - 1] = [clips_by_seg[0][0]]
    _phase("footage+vision")

    # ALT-KESİM PLANI yukarıda (footage'dan önce) hesaplandı — klip sayısı ondan türedi.
    clip_idx = subcut_clip_index(
        subcuts, {si: len(cs) for si, cs in clips_by_seg.items()})
    clip_paths: list[Path] = [clips_by_seg[si][k]
                              for (si, _a, _b), k in zip(subcuts, clip_idx)]
    seg_spans = [(a, b) for (_si, a, b) in subcuts]
    # Aynı klibin farklı alt-kesimi FARKLI saniyeden başlasın (klip-içi çeşitlilik).
    # Ofsetler klibin GERÇEK süresine yayılır — eski formül min(6.0, 1.5*k) idi ve
    # k>=4'te DOYUYORDU (bkz. reel_pacing.clip_offsets: short 802'de videonun son
    # 11.4 saniyesi, %33'ü, donmuş tek kareydi).
    _durs: dict[str, float] = {}
    for c in set(map(str, clip_paths)):
        try:
            _durs[c] = d.probe_duration_s(Path(c), ffprobe_path="ffprobe")
        except Exception as e:      # süre okunamadı → ofset 0 (klibin başı), üretim düşmesin
            log.warning(f"  reel: klip süresi okunamadı, ofset 0 ({Path(c).name}): {e}")
    clip_starts = clip_offsets(clip_paths, subcuts, _durs)
    if footage_driven:
        # Uzun alt-kesim ofseti klip içindeki donmuş bölüme düşmesin (karınca dersi).
        clip_starts = _fd_fix_static_offsets(clip_paths, subcuts, clip_starts,
                                             ffmpeg_path)
    cut_times = [a for (_si, a, _b) in subcuts[1:]]
    log.info(f"  reel: {len(subcuts)} alt-kesim ({profile.cut_pacing} tempo), "
             f"{len(set(map(str, clip_paths)))} farklı klip")

    # SAYI VURGUSU: anlatımdaki sayılar ekranda büyük pop.
    numbers = (find_numbers(timeline.words)
               if getattr(reel, "number_pop", True) else [])
    if numbers:
        log.info(f"  reel: {len(numbers)} sayı vurgusu → {[n['text'] for n in numbers]}")

    # BELİRTEÇLER: konum ALT-KESİM BAŞINA ölçülür — o alt-kesimde GERÇEKTEN gösterilen
    # klipten ve onun GERÇEK başlangıç saniyesinden. Eskiden segmentin İLK klibinden
    # ölçülüp segment boyunca çiziliyordu; hızlı kesimde segment 3 farklı klip
    # gösterdiği için marker ölçülmediği kliplerin üstünde BOŞLUĞU işaretliyordu.
    # ÖZNE KONUMU — TEK ölçüm, İKİ kullanım:
    #   a) ÇERÇEVELEME: 16:9 → 9:16 kırpma öznenin ETRAFINDAN yapılır. Eskiden hep
    #      MERKEZDEN kesiyorduk; araştırma bunu otomatik faceless videonun "1 numaralı
    #      görsel ele veren işareti" diye adlandırıyor (özne kenardaysa yarısı kesilir).
    #      Konumu ZATEN ölçüyorduk ama yalnız marker'da kullanıyorduk.
    #   b) BELİRTEÇLER: (yalnız marker-uygun segmentlerde, güven eşiğiyle)
    markers = []
    subject_xs: list = [None] * len(subcuts)
    want_frame = getattr(reel, "subject_framing", True) and vision_call is not None
    want_marks = reel.arrows_enabled and bool(worthy)
    if want_frame or want_marks:
        _mk_t0 = _time.perf_counter()

        def _locate_at(i: int, si: int) -> SubjectPos:
            q = timeline.seg_queries[si] or _first_q
            return d.locate_subject(clip_paths[i], q, vision_call=vision_call,
                                    ffmpeg_path=ffmpeg_path,
                                    at_s=clip_starts[i] + 0.4)

        # PARALEL: her ölçüm bir vision çağrısı (~2-3sn); sıralıyken 30 saniye yiyordu.
        from concurrent.futures import ThreadPoolExecutor

        from short_bot.run_context import get_log_path, pool_initializer
        # Çerçeveleme açıksa TÜM alt-kesimler ölçülür; değilse yalnız marker'lılar.
        todo = [(i, si) for i, (si, _a, _b) in enumerate(subcuts)
                if want_frame or si in worthy]
        found: dict[int, SubjectPos] = {}
        if todo:
            with ThreadPoolExecutor(max_workers=LOCATE_WORKERS,
                                    initializer=pool_initializer,
                                    initargs=(get_log_path(),)) as ex:
                for (i, _si), pos in zip(todo, ex.map(lambda t: _locate_at(*t), todo)):
                    found[i] = pos
        positions = [found.get(i, SubjectPos(found=False))
                     for i in range(len(subcuts))]

        if want_frame:
            # Kadrajı yalnız GÜVENLE bulunmuş özneye kaydır. Emin değilsek merkez
            # (None) — yanlış yere kaydırmak, merkez-crop'tan beterdir.
            subject_xs = [(p.x if (p.found and p.confidence >= FRAME_CONF_MIN)
                           else None) for p in positions]
            n_fr = sum(1 for x in subject_xs if x is not None)
            log.info(f"  reel: {n_fr}/{len(subcuts)} alt-kesimde özne-farkında kadraj")

        if want_marks:
            markers = build_markers(subcuts, positions,
                                    marker_kit=profile.marker_kit,
                                    frequency=reel.arrow_frequency, seed=seed)
        log.info(f"  reel: {len(markers)} belirteç, {len(todo)} konum ölçümü, "
                 f"{_time.perf_counter() - _mk_t0:.1f}s")

    # AÇIK SORU ÇİPİ + REVEAL KORKULUĞU (merak mimarisi). reveal_beat=0 sızıntıdır
    # (payoff hook klibiyle aynı) → en az 1'e, yoksa peak_beat'e itilir.
    _question_text = ""
    _reveal_at_s = None
    if footage_driven and getattr(narration, "open_question", "").strip():
        rb = narration.reveal_beat if narration.reveal_beat >= 0 else narration.peak_beat
        rb = max(1, min(rb, len(narration.beats) - 1))
        _reveal_seg = rb + 1                     # segment 0 = hook
        if 0 <= _reveal_seg < len(timeline.seg_spans):
            _question_text = narration.open_question
            _reveal_at_s = timeline.seg_spans[_reveal_seg][0]
            log.info(f"  merak: soru çipi '{_question_text}' → reveal @ "
                     f"{_reveal_at_s:.1f}s (beat {rb})")

    # TEPE ANI: en büyük reveal'in bittiği saniye. Riser/impact sesi, koordineli
    # kesintiler ve punch-in zamanlaması buradan türer. (Beğeni/abone çipleri
    # 2026-07-16'da kaldırıldı — kullanıcı kararı; tepe artık yalnız ritim çıpası.)
    peak_seg = narration.peak_segment()
    peak_end_s = None
    if 0 <= peak_seg < len(timeline.seg_spans):
        peak_end_s = timeline.seg_spans[peak_seg][1]
        log.info(f"  reel: tepe = beat {narration.peak_beat} "
                 f"(segment {peak_seg}, {peak_end_s:.1f}s) → riser/impact çıpası")
    if not narration.close_echoes_hook():
        log.warning("  reel: kapanış hook'un sözcüklerini GERİ ÇAĞIRMIYOR → "
                    "video 'biter', izleyici döngüye girmez (loop kaybı)")


    # KOORDİNELİ KESİNTİ ANLARI: 3-5 beat sınırında dört kanal AYNI KAREDE ateşlenir
    # (vuruş sesi + tam güçlü uzun efekt + altyazı darbesi + görüntü punch'ı); diğer
    # kesimlerde SFX kısılır. Eskiden her kesimde her şey patlıyordu — uyaranın her
    # yerde olması, hiçbir yerde olmaması demek (bkz. reel_interrupt).
    interrupts: list[float] = []
    if getattr(reel, "interrupts", True):
        interrupts = select_interrupts(
            cut_times, [a for (a, _b) in timeline.seg_spans[1:]],
            duration_s=duration_s, peak_s=peak_end_s)
        if interrupts:
            log.info(f"  reel: {len(interrupts)} koordineli kesinti @ "
                     + ", ".join(f"{t:.1f}s" for t in interrupts))
        else:
            log.info("  reel: beat sınırına oturan kesim yok → kesinti anı seçilmedi")

    # 6) Overlay render
    frames_dir = work_dir / "frames"
    d.render_reel_overlay_frames(
        timeline, frames_dir, fps=fps, browser=browser, templates_dir=templates_dir,
        layout=profile.layout,
        highlight_color=profile.accent, arrow_color=reel.arrow_color,
        arrow_frequency=reel.arrow_frequency if reel.arrows_enabled else "off",
        cut_effect=profile.cut_effect, handle=channel.handle,
        badge=bits.badge,
        question_text=_question_text,
        reveal_at_s=_reveal_at_s,
        lang=channel.language,
        font=reel.font,
        markers=markers,
        numbers=numbers,
        interrupts=interrupts,
    )
    _phase("overlay-render")

    # 7) Montaj (cut_times alt-kesim planından geldi — segment sınırı DEĞİL)
    sfx_dir = assets_root / "sfx"
    # SFX kanal bayrağıyla açık/kapalı (per-video varyasyon setine bağlı DEĞİL).
    # Havuz kategori klasörlü; kurgucunun sfx_plan'ı kesim başına kategoriyi seçer,
    # ve AYNI SES bir videoda TEKRAR ÇALMAZ (kullanıcı: "aynı sfx" şikâyeti).
    pool = discover_sfx(sfx_dir) if reel.transitions_whoosh else {}
    # Kesinti anlarında kategori 'impact'e ZORLANIR (vuruş; whoosh onu taşımaz) ve
    # seviye yükselir; öteki kesimlerde seviye kısılır → kontrast.
    impact_at = impact_cut_indices(cut_times, interrupts)
    sfx_at_cut = pick_sfx_per_cut(pool, seed, len(cut_times),
                                  sfx_plan=profile.sfx_plan, impact_at=impact_at)
    cut_gains = sfx_gains(cut_times, interrupts) if interrupts else None
    n_uniq = len({str(p) for p in sfx_at_cut})
    log.info(f"  reel: {len(cut_times)} kesim, {n_uniq} farklı SFX"
             + (f", {len(impact_at)} kesinti vuruşu" if impact_at else "")
             + (f" (kurgucu: {'/'.join(dict.fromkeys(profile.sfx_plan))})"
                if profile.sfx_plan else ""))

    # RISER → IMPACT: reveal'den önce yükselen ses, tam tepe karesinde vuruş.
    # Riser bir TAHMİN MAKİNESİDİR — "bir şey geliyor" der ve kaydırma dürtüsünü
    # bastırır (çözülmeden gidemezsin); impact tahmini ÖDÜLLENDİRİR.
    riser = impact = None
    if peak_end_s:
        risers = sorted((assets_root / "riser").glob("*.mp3"))
        if risers:
            pick = risers[seed % len(risers)]
            riser = (pick, _probe_s(pick, ffmpeg_path))
        impacts = sorted((sfx_dir / "impact").glob("*.mp3"))
        # Kesimlerde ZATEN kullanılmış bir impact'i tepede tekrar çalma
        used = {str(p) for p in sfx_at_cut}
        fresh = [p for p in impacts if str(p) not in used] or impacts
        if fresh:
            impact = fresh[seed % len(fresh)]
        log.info(f"  reel: tepe sesi → riser={riser[0].name if riser else '-'} "
                 f"+ impact={impact.name if impact else '-'} @ {peak_end_s:.1f}s")

    # Müzik: kurgucu ruh hali önerdiyse yeniden seç (pipeline kanal ayarıyla seçmişti,
    # ama kurgucu anlatımı OKUDUKTAN sonra karar verir). Klasör yoksa eskisi kalır.
    if profile.music_mood:
        from short_bot.assets import pick_music
        try:
            music_path = pick_music(assets_root / "music", mood=profile.music_mood,
                                    channel_slug=channel.slug)
            log.info(f"  reel: müzik '{profile.music_mood}' → {music_path.name}")
        except (FileNotFoundError, OSError) as e:
            log.info(f"  reel: '{profile.music_mood}' müziği yok ({e}), mevcut müzik")

    # Müzik profili: sessiz girişi atla + kütüphane seviye farkını eşitle.
    # Ölçüldü — parçaları 0:00'dan başlatınca müzik konuşmanın 37 dB altında
    # kalıyordu (olması gereken ~12 dB): çoğu stok parça yavaş kuruluyor.
    # Profil çıkmazsa ESKİ davranış: kazanç yok, kanal çarpanı uygulanır.
    m_start, m_gain = 0.0, 0.0
    m_vol = reel.music_volume
    if music_path is not None:
        try:
            # Önbellek müzik köküne yazılır: work_dir geçici, her koşuda silinir —
            # ebur128 geçişini her videoda tekrarlamanın anlamı yok.
            mprof = profile_music(
                Path(music_path), ffmpeg_path=ffmpeg_path,
                cache_path=Path(music_path).parent.parent / "_profiles.json")
            konusma = speech_lufs(mp3, ffmpeg_path=ffmpeg_path)
            m_start = mprof.start_s
            m_gain = music_gain_db(mprof, konusma, reel.music_volume)
            # Kazanç hedefi ZATEN tutturuyor (kanal ayarının dokunuşu da içinde).
            # Üstüne bir de music_volume çarpmak ÇİFTE KISMA olur — gerçek hata:
            # log "-11 dB altına oturtuldu" derken müzik -29 dB altında kalıyordu.
            m_vol = 1.0
            log.info(f"  reel: müzik girişi {m_start:.1f}sn atlandı | "
                     f"konuşma {konusma if konusma is None else round(konusma,1)} LUFS, "
                     f"müzik {mprof.lufs:.1f} → {m_gain:+.1f} dB ile "
                     f"{MUSIC_UNDER_SPEECH_DB:+.0f} dB altına oturtuldu")
        except Exception as e:   # müzik KOZMETİK — ölçüm çıkmazsa ham parça
            log.warning(f"  reel: müzik dengelenemedi ({e}) → ham parça")

    # Görüntü punch'ı kesinti anlarında DA ateşlenir — dördüncü kanal. Ses vuruşuyla
    # aynı karede olduğu için izleyici ikisini tek bir "olay" olarak algılar.
    # AÇILIŞ SES İMZASI: kanala göre BİR KEZ seçilir, her bölümde aynı çalar. Seed'e
    # göre seçilseydi her videoda farklı olurdu — yani imza olmazdı.
    sting = None
    if getattr(reel, "sting_enabled", True):
        from short_bot.reel_identity import pick_sting
        sting = pick_sting(assets_root / "sting", channel.slug)
        if sting:
            log.info(f"  reel: açılış imzası → {sting.name}")

    punches = punch_times(numbers, peak_end_s, extra=interrupts)
    if punches:
        log.info(f"  reel: vurgu punch-in @ "
                 + ", ".join(f"{t:.1f}s" for t in punches))
    d.assemble_reel(
        clip_paths=clip_paths, seg_spans=seg_spans, frames_dir=frames_dir,
        narration_path=mp3, music_path=music_path, out_path=out_path,
        cut_times=cut_times, duration_s=duration_s, fps=fps, ffmpeg_path=ffmpeg_path,
        music_volume=m_vol,
        music_start_s=m_start, music_gain_db=m_gain,
        sfx_volume=getattr(reel, "sfx_volume", 0.22),
        music_duck=getattr(reel, "music_duck", True),
        riser=riser, impact=impact, reveal_s=peak_end_s,
        sfx_at_cut=sfx_at_cut,
        sfx_gains=cut_gains,
        sting=sting, sting_volume=getattr(reel, "sting_volume", 0.35),
        # VURGU PUNCH-IN: sayı söylenirken ve TEPE anında görüntü bir tık yaklaşır.
        # Kesme efektleri ritmi zamanlayıcıyla veriyordu; bu, ritmi İÇERİĞE bağlayan
        # tek hamle — insan kurgucunun yaptığı, otomasyonun yapmadığı şey.
        punch_at=punches,
        # MİZAH kanallarında yapay zoom YOK: Ken Burns/zoompan klişesi, izleyici
        # yapay bulur. Canlılık gerçek hareketli footage'tan (measure_motion) gelir.
        # Diğer kanallarda mevcut davranış (profile'a göre).
        zoom=(("zoom" in profile.transitions)
              and not getattr(reel, "persona", "")),
        subject_xs=subject_xs,
        color_grade=getattr(reel, "color_grade", True),
        seed=seed,
        clip_starts=clip_starts,
        hook_punch=True,
    )
    _phase("montaj(ffmpeg)")
    _total = sum(_phase_t.values())
    _brk = " | ".join(f"{k} {v:.0f}s(%{100 * v / max(_total, 1):.0f})"
                      for k, v in sorted(_phase_t.items(), key=lambda kv: -kv[1]))
    log.info(f"  reel[SÜRE ÖZET] toplam {_total / 60:.1f}dk → {_brk}")
    return out_path
