"""Kürate klip TEMİZLEME (SP4, geliştirildi): watermark/logo/kaynak-etiketi tespit +
ffmpeg `delogo` ile silme. TikTok watermark'ları HAREKETLİ (ekranda gezer) olduğu için
tek kareyle tek bölge silmek YETMEZ (kullanıcı: 'tiktoktan alınmış, temizlik çalışmıyor').

Çözüm: klipten STORYBOARD (zaman-sıralı 6 kare, tek ızgara) çıkar → tek vision çağrısında
watermark'ın gezdiği TÜM bölgeleri topla → hepsini delogo'la. Ağır KAPLAYAN (özneyi örten)
yazı temizlenmez (artefakt). Çok fazla bölge (watermark her yerde) → temizlenmez.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger(__name__)

# Bölge → (x, y, w, h) normalize (0-1) delogo kutusu. Köşeler + kenar şeritleri +
# orta-kenarlar (TikTok watermark'ı sol-orta / sağ-alt gibi gezer).
_REGION_BOX = {
    "top-left":     (0.00, 0.00, 0.42, 0.14),
    "top-right":    (0.58, 0.00, 0.42, 0.14),
    "top":          (0.00, 0.00, 1.00, 0.14),
    "bottom-left":  (0.00, 0.86, 0.42, 0.14),
    "bottom-right": (0.58, 0.86, 0.42, 0.14),
    "bottom":       (0.00, 0.86, 1.00, 0.14),
    "mid-left":     (0.00, 0.38, 0.34, 0.24),
    "mid-right":    (0.66, 0.38, 0.34, 0.24),
    "left":         (0.00, 0.08, 0.24, 0.84),   # sol kenar boyunca gezen watermark
    "right":        (0.76, 0.08, 0.24, 0.84),   # sağ kenar boyunca gezen watermark
    "center":       (0.30, 0.40, 0.40, 0.20),
}
_MAX_REGIONS = 4   # bundan fazla bölge = watermark her yerde → temizlenmez (aşırı blur)


class WatermarkDetect(BaseModel):
    """Storyboard vision yargısı — watermark tüm karelerde nerelerde görünüyor."""
    present: bool = False
    # watermark'ın GÖRÜNDÜĞÜ TÜM bölgeler (hareketliyse birden çok): _REGION_BOX etiketleri
    regions: list[str] = []
    # yazı ana ÖZNEYİ mi kaplıyor (ağır → temizlenemez) yoksa kenar/köşede mi
    covers_subject: bool = False
    # TikTok/Instagram PLATFORM watermark'ı mı (logo + @kullanıcı)? Bunlar TANIMI GEREĞİ
    # ekranda zıplar → tek delogo yetmez → temizlenemez say (bölge sayısından bağımsız).
    moving: bool = False
    note: str = ""


_DETECT_PROMPT = (
    "Bu bir kısa video klibinin STORYBOARD'ı (zaman-sıralı 6 kare, tek ızgara). Görüntüye "
    "SONRADAN BİNDİRİLMİŞ watermark / logo / kaynak-etiketi (TikTok, Instagram, "
    "kullanıcı-adı @...) var mı? (doğal sahne yazısı DEĞİL — platform/editör katmanı).\n"
    "ÖNEMLİ: TikTok watermark'ı HAREKETLİDİR — karelerde FARKLI köşe/kenarlarda görünebilir. "
    "Karelerin HEPSİNE bak ve watermark'ın göründüğü TÜM konumları listele.\n"
    "- present: böyle bir katman VAR mı?\n"
    "- regions: göründüğü TÜM bölgeler (şunlardan): top-left, top-right, top, bottom-left, "
    "bottom-right, bottom, mid-left, mid-right, left, right, center. Hareketliyse birden çok yaz.\n"
    "- moving: bu bir TikTok/Instagram PLATFORM watermark'ı mı — yani 'TikTok' logosu/yazısı "
    "ya da '@kullanıcıadı' etiketi mi? (Öyleyse TANIMI GEREĞİ ekranda zıplar → true. "
    "TEK bir karede bile TikTok logosu/@kullanıcı görürsen moving=true yaz.)\n"
    "- covers_subject: katman ana ÖZNENİN ÜSTÜNÜ mü kaplıyor (true=ağır) yoksa kenar/köşede mi (false)?\n"
    'SADECE JSON: {"present": <bool>, "regions": ["<...>", ...], "moving": <bool>, '
    '"covers_subject": <bool>, "note": "<short English>"}'
)


def _dims(clip, ffmpeg_path: str = "ffmpeg") -> tuple[int, int]:
    probe = "ffprobe" if ffmpeg_path in ("ffmpeg", "") else ffmpeg_path.replace("ffmpeg", "ffprobe")
    try:
        out = subprocess.run(
            [probe, "-v", "error", "-select_streams", "v", "-show_entries",
             "stream=width,height", "-of", "csv=p=0:s=x", str(clip)],
            capture_output=True, text=True, timeout=20)
        w, h = (out.stdout or "0x0").strip().split("x")[:2]
        return int(w), int(h)
    except Exception:  # noqa: BLE001
        return 0, 0


def detect_watermark(clip, *, vision_call, ffmpeg_path: str = "ffmpeg"):
    """Storyboard (6 zaman-sıralı kare) → tek vision çağrısı: watermark'ın gezdiği TÜM
    bölgeler. Döner WatermarkDetect ya da None (kare/vision hatası → temizlenmez)."""
    from short_bot.claude_cli import run_json
    from short_bot.reel import _storyboard_frames
    try:
        with tempfile.TemporaryDirectory() as td:
            board = Path(td) / "wm_board.jpg"
            if not _storyboard_frames(clip, board, ffmpeg_path, cols=3, rows=2):
                # storyboard kurulamazsa tek kareye düş (klibin ortası)
                from short_bot.reel import _clip_duration_s
                dur = _clip_duration_s(clip, ffmpeg_path)
                t = max(0.5, dur / 2) if dur > 0 else 1.0
                board = Path(td) / "wm.jpg"
                subprocess.run([ffmpeg_path, "-v", "error", "-y", "-ss", f"{t:.2f}",
                                "-i", str(clip), "-frames:v", "1", "-vf", "scale=480:-1",
                                str(board)], capture_output=True, timeout=30)
            if not board.exists() or board.stat().st_size == 0:
                return None
            return run_json(_DETECT_PROMPT, WatermarkDetect,
                            claude_path=vision_call.claude_path, model=vision_call.model,
                            backend=vision_call.backend, api_key=vision_call.api_key,
                            image_path=board, retries=1, timeout_s=45)
    except Exception as e:  # noqa: BLE001
        log.info(f"  kürate[temizlik]: watermark tespiti hatası ({e})")
        return None


# delogo YALNIZ tek SABİT KÖŞE watermark'ında temiz sonuç verir. TikTok gibi HAREKETLİ
# (birden çok bölge) watermark'ta delogo çirkin blur bırakır + watermark yine kalır →
# hiç dokunma; o klip SEÇİMDE elenmeli (bkz. watermark_uncleanable + auto_produce_curated).
_CORNERS = {"top-left", "top-right", "bottom-left", "bottom-right"}


def watermark_uncleanable(detection) -> bool:
    """Bu watermark delogo ile TEMİZ silinemez mi? True ise klip ideal değildir — seçimde
    elenmeli. Temizlenemez sayılanlar: TikTok/IG platform logosu (zıplar), özneyi kaplayan,
    birden çok bölge, ya da köşe-dışı kenar-strip."""
    if detection is None or not detection.present:
        return False
    # TikTok/IG platform watermark'ı: TANIMI GEREĞİ zıplar → tek delogo yetmez (short 937:
    # vision tek 'bottom-right' gördü ama logo sağ-ORTA'daydı, gezdiği için delogo ıskaladı).
    if getattr(detection, "moving", False):
        return True
    if detection.covers_subject:
        return True
    regions = {r.lower() for r in (detection.regions or []) if (r or "").lower() in _REGION_BOX}
    # Tek sabit köşe → temizlenebilir; birden çok bölge / köşe-dışı kenar-strip → hareketli.
    return not (len(regions) == 1 and next(iter(regions)) in _CORNERS)


def clean_clip(clip, detection, *, ffmpeg_path: str = "ffmpeg", out_path):
    """YALNIZ tek SABİT KÖŞE watermark'ını delogo ile sil (temiz sonuç). Hareketli
    (birden çok bölge) / özneyi kaplayan / köşe-dışı → None (delogo bozar, dokunma)."""
    if watermark_uncleanable(detection):
        log.info(f"  kürate[temizlik]: watermark temizlenemez (hareketli/kaplayan: "
                 f"{getattr(detection, 'regions', None)}) → dokunulmuyor (klip ideal değil)")
        return None
    regions = {r.lower() for r in (detection.regions or []) if (r or "").lower() in _REGION_BOX}
    if len(regions) != 1:
        return None
    r = next(iter(regions))
    w, h = _dims(clip, ffmpeg_path)
    if w <= 0 or h <= 0:
        return None
    fx, fy, fw, fh = _REGION_BOX[r]
    x = max(1, int(fx * w)); y = max(1, int(fy * h))
    bw = min(int(fw * w), w - x - 1); bh = min(int(fh * h), h - y - 1)
    if bw < 8 or bh < 8:
        return None
    out_path = Path(out_path)
    try:
        subprocess.run([ffmpeg_path, "-v", "error", "-y", "-i", str(clip),
                        "-vf", f"delogo=x={x}:y={y}:w={bw}:h={bh}", "-an",
                        "-preset", "veryfast", str(out_path)],
                       capture_output=True, timeout=180)
        if out_path.exists() and out_path.stat().st_size > 0:
            log.info(f"  kürate[temizlik]: '{r}' sabit köşe watermark'ı delogo ile silindi")
            return out_path
    except Exception as e:  # noqa: BLE001
        log.info(f"  kürate[temizlik]: delogo hatası ({e}) → orijinal kullanılıyor")
    return None


def clean_if_needed(clip, *, vision_call, ffmpeg_path: str = "ffmpeg", out_path):
    """Tespit + temizle tek adımda. Watermark yoksa/ağırsa/hatada orijinal klip döner."""
    det = detect_watermark(clip, vision_call=vision_call, ffmpeg_path=ffmpeg_path)
    if det is None or not det.present:
        return clip, det
    cleaned = clean_clip(clip, det, ffmpeg_path=ffmpeg_path, out_path=out_path)
    return (cleaned or clip), det


# ── STORYBOARD KALİTE KAPISI (thumbnail körlüğünü kapat) ──────────────────────
# Skorlama TITLE + tek KAPAK karesinden yargılıyor → 'maybe maybe maybe' gibi bilgisiz
# başlıklı + aksiyon gibi görünen kapaklı SIRADAN klipler yüksek skor alıp havuza giriyor
# (short 957: kadın-futbolu pile-up, skor 8, ama izlenmez). ÇÖZÜM: havuza koymadan önce
# klibi indirip GERÇEK 6 kareyle (storyboard) yargıla — sıradan/rutin olanı ELE.
class ClipQuality(BaseModel):
    """Storyboard vision yargısı — klip GERÇEKTEN izlenesi mi (kapak değil, içerik)."""
    engaging: bool = False   # gerçekten dikkat çekici / durdurur / paylaşılası mı
    score: int = 5           # 1 (sıradan, kaydırılır) .. 10 (kesin viral, durdurur)
    reason: str = ""


def _quality_prompt(tone: str) -> str:
    lens = ("GERÇEKTEN DOKUNAKLI/duygusal (içini ısıtan, gözünü dolduran)"
            if tone == "duygu" else
            "GERÇEKTEN komik/şaşırtıcı/çarpıcı ('vay!', kahkaha, 'nasıl yani?!')")
    return (
        "Bu, bir kısa video klibinin GERÇEK 6 karesi (storyboard, zaman-sıralı, tek ızgara) — "
        "klibin BAŞTAN SONA ne olduğunu gösteriyor.\n"
        f"Bu klip {lens} bir AN taşıyor mu — birini KAYDIRMAYI durdurup izleten, paylaştıran? "
        "Yoksa SIRADAN / rutin / unutulur mu?\n"
        "DÜŞÜK (score 1-4) sayılanlar: rutin spor anı/düşmesi, sıradan tepki, 'olabilir ama "
        "özel değil', olayın ne olduğu belirsiz, izleyiciyi durduracak bir tepe YOK.\n"
        "YÜKSEK (score 7-10): net bir çarpıcı/komik/dokunaklı TEPE var, ilk 2 saniyede "
        "kanca, sonuna kadar 'ne olacak' merakı.\n"
        "DİKKAT: bir kapak aldatıcı olabilir — SEN 6 karenin TÜMÜNE bakıp GERÇEK olayı yargıla, "
        "'aksiyon gibi görünüyor'a kanma.\n"
        "- engaging: gerçekten durdurup izleten/paylaşılası mı?\n"
        "- score: 1-10 izlenme-değerliliği.\n"
        'SADECE JSON: {"engaging": <bool>, "score": <1-10>, "reason": "<çok kısa>"}'
    )


# ── ANLATIM SADAKAT KAPISI (anlatım gerçek videoyu mu anlatıyor) ─────────────
# Kullanıcı: 'her video böyle mi olacak, bunu teyit edecek bir yapı lazım'. Anlatım
# yazıldıktan SONRA storyboard'a (gerçek kareler) + anlatıma bakıp uydurma olay/sıra var mı
# yargıla (short 962: kedi yavruyu baştan sona taşırken anlatım 'bırakıldı→geri döndü' uydurdu).
# Uydurmuşsa çağıran GERİ BİLDİRİMLE yeniden yazdırır. Prompt yamamak yerine OTOMATİK teyit.
class NarrationCheck(BaseModel):
    """Storyboard + anlatım vision yargısı — anlatım gerçek olaya sadık mı."""
    faithful: bool = True    # anlatım ekrandaki gerçek olaya sadık mı (uydurma olay YOK)
    mismatch: str = ""       # sadık değilse en büyük uyumsuzluk (tek cümle, TR)


_FAITH_PROMPT = (
    "Aşağıda bir video klibinin GERÇEK 6 karesi (storyboard, zaman-sıralı) ve o klip için "
    "yazılmış Türkçe bir ANLATIM var.\n"
    "ANLATIM:\n---\n{narr}\n---\n"
    "Bu anlatım, karelerdeki ÖZNE ve TEMEL OLAYLA örtüşüyor mu?\n"
    "MUHAFAZAKÂR OL — yalnız KABA/NET bir uyumsuzluk varsa 'faithful=false' de:\n"
    "  * Tamamen FARKLI özne (anlatım 'köpek/futbol' der ama karelerde kedi var) VEYA\n"
    "  * Ekranda AÇIKÇA olmayan büyük bir olay/ortam (anlatım 'denize dalıyor' der, deniz yok).\n"
    "ŞUNLAR faithful=false YAPMAZ (hepsi SERBEST): mizah, abartı, lakap, benzetme, iç ses, "
    "küçük sıra/aşama farkı, yorumla eklenen ayrıntı, öznenin ne 'hissettiği'. Kareler "
    "küçük/belirsizse ya da EMİN DEĞİLSEN → faithful=TRUE (şüphede sadık say).\n"
    "- faithful: özne + temel olay örtüşüyor mu (KABA uyumsuzluk YOK)?\n"
    "- mismatch: yalnız KABA uyumsuzlukta tek cümle yaz (Türkçe); değilse boş.\n"
    'SADECE JSON: {{"faithful": <bool>, "mismatch": "<...>"}}'
)


def verify_curated_narration(clip, narration_text: str, *, vision_call,
                             ffmpeg_path: str = "ffmpeg"):
    """Storyboard (gerçek 6 kare) + anlatım → anlatım gerçek olaya sadık mı, uydurma olay
    var mı. Döner NarrationCheck ya da None (kare/vision hatası → fail-open, çağıran sadık
    sayar). Mizah/abartı serbest; yalnız uydurma OLAY yakalanır."""
    from short_bot.claude_cli import run_json
    from short_bot.reel import _storyboard_frames
    if not (narration_text or "").strip():
        return None
    try:
        with tempfile.TemporaryDirectory() as td:
            board = Path(td) / "faith_board.jpg"
            if not _storyboard_frames(clip, board, ffmpeg_path):
                return None
            if not board.exists() or board.stat().st_size == 0:
                return None
            return run_json(_FAITH_PROMPT.format(narr=narration_text[:900]), NarrationCheck,
                            claude_path=vision_call.claude_path, model=vision_call.model,
                            backend=vision_call.backend, api_key=vision_call.api_key,
                            image_path=board, retries=1, timeout_s=45)
    except Exception as e:  # noqa: BLE001
        log.info(f"  kürate[sadakat]: yargı hatası ({e})")
        return None


def judge_clip_quality(clip, *, vision_call, ffmpeg_path: str = "ffmpeg",
                       tone: str = "mizah"):
    """Storyboard (GERÇEK 6 kare) → klip izlenesi mi yoksa sıradan mı. Döner ClipQuality
    ya da None (kare/vision hatası → çağıran fail-open kararı verir)."""
    from short_bot.claude_cli import run_json
    from short_bot.reel import _storyboard_frames
    try:
        with tempfile.TemporaryDirectory() as td:
            board = Path(td) / "q_board.jpg"
            if not _storyboard_frames(clip, board, ffmpeg_path):
                return None
            if not board.exists() or board.stat().st_size == 0:
                return None
            return run_json(_quality_prompt(tone), ClipQuality,
                            claude_path=vision_call.claude_path, model=vision_call.model,
                            backend=vision_call.backend, api_key=vision_call.api_key,
                            image_path=board, retries=1, timeout_s=45)
    except Exception as e:  # noqa: BLE001
        log.info(f"  kürate[kalite]: yargı hatası ({e})")
        return None


# ── SAHNE-BÖLÜNME (ses-görüntü senkron) ──────────────────────────────────────
# Kürate montajı tek klibi baştan sona oynatır; anlatım TTS hızıyla bağımsız akar.
# Klip 2 sahneli (örn. poster odası → banyo) ve sahne dağılımı eşit değilse (poster
# %70, banyo %30), anlatım hikâyeyi eşit böldüğü için "banyoda" kelimeleri görüntü
# banyoya geçmeden ~3sn önce söyleniyordu (kullanıcı yakaladı). Çözüm: klibin sahne
# geçişini vision ile tespit et → anlatım prompt'una "sahne1 klibin %X'i, kelimeleri
# ona göre dağıt" bilgisini ver (bkz. build_curated_prompt scene_split).
class SceneSplit(BaseModel):
    """Storyboard vision yargısı — klip belirgin bir ikinci sahneye geçiyor mu, nerede."""
    multi_scene: bool = False
    # yeni sahnenin İLK göründüğü kare (1..N); tek sahneyse 0
    transition_frame: int = 0


_SCENE_SPLIT_PROMPT = (
    "Bu bir kısa video klibinin STORYBOARD'ı (zaman-sıralı {n} kare, soldan sağa, "
    "sonra alt sıra). Klip BELİRGİN biçimde YENİ bir sahneye/mekâna geçiyor mu "
    "(arka plan/ortam TAMAMEN değişiyor mu — örn. odadan banyoya)?\n"
    "ÖNEMLİ: Küçük kamera hareketi, zoom, ya da öznenin aynı ortamda yer değiştirmesi "
    "SAHNE DEĞİŞİMİ DEĞİLDİR. Yalnız net mekân/kurulum değişimini say.\n"
    "- multi_scene: net bir İKİNCİ sahne (farklı mekân) var mı?\n"
    "- transition_frame: yeni sahnenin İLK göründüğü kare numarası (1-{n}); tek sahneyse 0.\n"
    'SADECE JSON: {{"multi_scene": <bool>, "transition_frame": <int>}}'
)


def detect_scene_split(clip, *, vision_call, ffmpeg_path: str = "ffmpeg",
                       cols: int = 3, rows: int = 2):
    """Storyboard (zaman-sıralı kare) → vision: klip yeni bir sahneye geçiyor mu ve
    kaçıncı karede? Döner: geçiş ORANI (0-1, İLK sahnenin bittiği klip oranı) ya da
    None (tek sahne / tespit hatası → özel tempo yok, mevcut davranış)."""
    from short_bot.claude_cli import run_json
    from short_bot.reel import _storyboard_frames
    n = cols * rows
    try:
        with tempfile.TemporaryDirectory() as td:
            board = Path(td) / "scene_board.jpg"
            if not _storyboard_frames(clip, board, ffmpeg_path, cols=cols, rows=rows):
                return None
            if not board.exists() or board.stat().st_size == 0:
                return None
            res = run_json(_SCENE_SPLIT_PROMPT.format(n=n), SceneSplit,
                           claude_path=vision_call.claude_path, model=vision_call.model,
                           backend=vision_call.backend, api_key=vision_call.api_key,
                           image_path=board, retries=1, timeout_s=45)
    except Exception as e:  # noqa: BLE001
        log.info(f"  kürate[sahne]: sahne-bölünme tespiti hatası ({e})")
        return None
    tf = res.transition_frame
    if not res.multi_scene or tf < 2 or tf > n:
        return None
    # Kare k'da yeni sahne İLK görünüyorsa geçiş ~ (k-0.5)/n oranında olmuştur; İLK
    # sahne klibin bu kadarını kaplar. [0.15, 0.85]'e sıkıştır (uç değer tempoyu bozmasın).
    frac = (tf - 0.5) / n
    return max(0.15, min(0.85, frac))


# ── KAYNAK YAZI-BANDI (repost başlığı) KIRPMA ────────────────────────────────
# Reddit/TikTok repost klipleri sık sık üstte/altta gömülü bir BAŞLIK ŞERİDİ taşır
# (örn. 'The way her mom said thank you… 🥺'). Watermark değil; delogo silmez. Bizim
# Türkçe altyazımızla üst üste binip kalabalık yapar → o şeridi KIRP (crop). Köşe
# logosu/hareketli watermark için detect_watermark ayrı (bkz. yukarı).
class SourceBanner(BaseModel):
    """Storyboard vision yargısı — kaynağın gömülü yazı-bandı var mı, DİKEY nerede, ne kadar."""
    present: bool = False
    y_center: float = 0.5    # bandın DİKEY merkezi (0.0=en üst, 1.0=en alt)
    frac: float = 0.0        # bandın kapladığı YÜKSEKLİK oranı (0-1)


_BANNER_PROMPT = (
    "Bu bir kısa video klibinin STORYBOARD'ı (zaman-sıralı 6 kare, tek ızgara). Görüntüye "
    "SONRADAN BİNDİRİLMİŞ, videonun kendi içeriğinden OLMAYAN bir YAZI BANDI / BAŞLIK ŞERİDİ "
    "var mı? (Reddit/TikTok repost başlığı gibi bir metin kutusu. Doğal sahne yazısı, tabela "
    "ya da köşe watermark'ı DEĞİL.)\n"
    "- present: böyle bir başlık/metin kutusu VAR mı?\n"
    "- y_center: DİKEY merkezi (0.0=karenin en ÜSTÜ, 0.5=tam ORTA, 1.0=en ALTI). DİKKATLİ ölç.\n"
    "- frac: kapladığı YÜKSEKLİK oranı, kabaca (0.05-0.25).\n"
    'SADECE JSON: {"present": <bool>, "y_center": <0.0-1.0>, "frac": <0.05-0.25>}'
)


def detect_source_banner(clip, *, vision_call, ffmpeg_path: str = "ffmpeg",
                         cols: int = 3, rows: int = 2):
    """Storyboard → vision: kaynağın gömülü üst/alt yazı-bandı. Döner SourceBanner ya da
    None (kare/vision hatası → dokunma, fail-open)."""
    from short_bot.claude_cli import run_json
    from short_bot.reel import _storyboard_frames
    try:
        with tempfile.TemporaryDirectory() as td:
            board = Path(td) / "banner_board.jpg"
            if not _storyboard_frames(clip, board, ffmpeg_path, cols=cols, rows=rows):
                return None
            if not board.exists() or board.stat().st_size == 0:
                return None
            return run_json(_BANNER_PROMPT, SourceBanner,
                            claude_path=vision_call.claude_path, model=vision_call.model,
                            backend=vision_call.backend, api_key=vision_call.api_key,
                            image_path=board, retries=1, timeout_s=45)
    except Exception as e:  # noqa: BLE001
        log.info(f"  kürate[bant]: yazı-bandı tespiti hatası ({e})")
        return None


# Bandı YALNIZ kenara yapışıksa kır — üst/alt kenardan bu kadar içeri girmiş olabilir.
# Ortada yüzen/kayan başlık (bkz. short 935 tembel-hayvan: y_center≈0.48) temiz
# kırpılamaz (içerik kaybettirir) → dokunma, orijinali kullan.
_BANNER_EDGE_GAP = 0.06   # kenara yapışıklık toleransı
_BANNER_MAX_CUT = 0.22    # tek seferde en çok bu kadar kırp (içerik koru)


def crop_source_banner(clip, banner, *, ffmpeg_path: str = "ffmpeg", out_path):
    """Kaynağın gömülü yazı-bandını KIRP — SADECE üst ya da alt kenara yapışıksa (temiz
    strip). Ortada yüzen banda dokunmaz (None). Blur değil, crop (temiz)."""
    if banner is None or not banner.present:
        return None
    yc = float(banner.y_center or 0.5)
    f = max(0.0, min(0.30, float(banner.frac or 0.0)))
    if f < 0.05:
        return None                       # ihmal edilebilir — kırpmaya değmez
    top_edge = yc - f / 2.0                # bandın üst sınırı (0-1)
    bot_edge = yc + f / 2.0                # bandın alt sınırı (0-1)
    # ÜST kenara yapışık (bandın tepesi ~0'da) → üstten bot_edge kadar at.
    if top_edge <= _BANNER_EDGE_GAP and bot_edge <= 0.40:
        cut = min(_BANNER_MAX_CUT, bot_edge + 0.02)
        vf = f"crop=iw:trunc(ih*(1-{cut:.3f})/2)*2:0:trunc(ih*{cut:.3f}/2)*2"
        where = "üst"
    # ALT kenara yapışık (bandın dibi ~1'de) → alttan (1-top_edge) kadar at.
    elif bot_edge >= (1.0 - _BANNER_EDGE_GAP) and top_edge >= 0.60:
        cut = min(_BANNER_MAX_CUT, (1.0 - top_edge) + 0.02)
        vf = f"crop=iw:trunc(ih*(1-{cut:.3f})/2)*2:0:0"
        where = "alt"
    else:
        log.info(f"  kürate[bant]: banda dokunulmadı (ortada yüzüyor, "
                 f"y_center≈{yc:.2f}) — temiz kırpılamaz")
        return None
    out_path = Path(out_path)
    try:
        subprocess.run(
            [ffmpeg_path, "-v", "error", "-y", "-i", str(clip), "-vf", vf,
             "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             str(out_path)],
            capture_output=True, timeout=180)
        if out_path.exists() and out_path.stat().st_size > 0:
            log.info(f"  kürate[bant]: kaynak yazı-bandı ({where} kenar, "
                     f"%{round(cut * 100)}) kırpıldı")
            return out_path
    except Exception as e:  # noqa: BLE001
        log.info(f"  kürate[bant]: kırpma hatası ({e}) → orijinal klip")
    return None
