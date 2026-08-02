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
    # ZORUNLU (default YOK): model boş/kısmi JSON ({}) dönerse model_validate ValidationError
    # atsın → run_json retry → hâlâ bozuksa detect None döner → gate FAIL-CLOSED reddeder. Eskiden
    # default False, boş yanıt 'temiz' sayılıp kirli klip GEÇİYORDU (denetim bulgusu, kritik).
    present: bool
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
    from short_bot.reel import _ffprobe_path
    probe = _ffprobe_path(ffmpeg_path)
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
            if not _storyboard_frames(clip, board, ffmpeg_path, cols=3, rows=2, frame_w=384):
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
            # TEMİZLİK = GÜVENLİK KAPISI: geçici vision hatası None döndürüp kirli klibi
            # (TikTok logolu) geçirmesin (short 968). Burst-throttle dalgasına karşı ek tur —
            # None yalnız GERÇEKTEN doğrulanamadığında dönsün (çağıran fail-CLOSED reddeder).
            last: Exception | None = None
            for _ in range(2):
                try:
                    return run_json(_DETECT_PROMPT, WatermarkDetect,
                                    claude_path=vision_call.claude_path, model=vision_call.model,
                                    backend=vision_call.backend, api_key=vision_call.api_key,
                                    image_path=board, retries=2, timeout_s=45)
                except Exception as e:  # noqa: BLE001 — geçici → tekrar dene
                    last = e
            log.info(f"  kürate[temizlik]: watermark tespiti doğrulanamadı ({last})")
            return None
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
    # ZORUNLU (bkz. WatermarkDetect.present): boş yanıt → ValidationError → None → kalite gate
    # FAIL-OPEN (üretir). Eskiden default engaging=False/score=5, boş yanıt iyi klibi 'sıradan'
    # sayıp REDDEDİP KALICI blacklist'liyordu (denetim bulgusu) — tek vision hıçkırığı = klip kaybı.
    engaging: bool           # gerçekten dikkat çekici / durdurur / paylaşılası mı
    score: int               # 1 (sıradan, kaydırılır) .. 10 (kesin viral, durdurur)
    # SES-YÜKÜ (kullanıcı: 'anlamsız videolar'): orijinal ses ATILIP Türkçe TTS basılıyor —
    # yükü seste olan klip (kahkaha/diyalog/müzik) sessiz izlenince sıradanlaşır. Default True
    # (eski/boş yanıt fail-open: alanı dönmeyen model klip kaybettirmesin).
    works_muted: bool = True  # klip SES OLMADAN da anlaşılır/etkileyici mi
    reason: str = ""


def _quality_prompt(tone: str, title: str = "") -> str:
    if tone == "duygu":
        lens = "GERÇEKTEN DOKUNAKLI/duygusal (içini ısıtan, gözünü dolduran)"
    elif tone == "karma":
        lens = ("GERÇEKTEN TATMİN EDİCİ bir KARMA/'oh olsun' — biri kaba/kuralsız/kibirli davranıp "
                "ANINDA hak ettiği HAFİF (kansız) karşılığı buluyor; ciddi yaralanma/şiddet varsa "
                "bu DÜŞÜKtür (tatmin değil, rahatsız edici)")
    else:
        lens = "GERÇEKTEN komik/şaşırtıcı/çarpıcı ('vay!', kahkaha, 'nasıl yani?!')"
    # BAŞLIK = OLAYIN KİMLİĞİ (tone-fit'e başlık besleme düzeltmesiyle aynı gerekçe).
    # Kapı başlıksızken kareyi ÇIPLAK yorumluyor: 'pistte koşan adam' → anlamsız → q=3.
    # Oysa aynı kare başlıkla 'geçit arabasını kapmaya koşan pilot' oluyor. Başlık kapının
    # GÖRDÜĞÜ eylemi ÇÖZMESİNİ sağlar — görsel çıtayı DÜŞÜRMEZ (aşağıdaki uyarı bunu bağlar).
    basliksiz = not (title or "").strip()
    baslik_blok = "" if basliksiz else (
        f"\nKLİBİN BAŞLIĞI (olayın kimliği): {title.strip()}\n"
        "BAŞLIK NE İÇİN, NE İÇİN DEĞİL:\n"
        "  • İÇİN: karede GÖRDÜĞÜN eylemi doğru ÇÖZMEK. Kim, neyi, neden yapıyor — bunu "
        "bilmeden sıradan görünen bir hareket (bir tokalaşmanın geri çevrilmesi, birinin "
        "aniden koşması, bir nesnenin kapılması) aslında olayın TEPESİ olabilir.\n"
        "  • İÇİN DEĞİL: GÖRSEL olarak ÖLÜ bir klibi kurtarmak. Başlık ne kadar ilginç olursa "
        "olsun, 9 karede İZLENECEK BİR ŞEY OLMUYORSA (konuşan kafalar, yürüyen insanlar, "
        "durağan sahne) bu yine DÜŞÜKTÜR — anlatım metni klibi kurtaramaz, izleyici görüntüyü "
        "görür. Başlığın vaat ettiği anı KARELERDE ARA; yoksa DÜŞÜK ver.\n")
    return (
        "Bu, bir kısa video klibinin GERÇEK 9 karesi (storyboard, zaman-sıralı, tek ızgara) — "
        "klibin BAŞTAN SONA ne olduğunu gösteriyor.\n"
        f"{baslik_blok}"
        f"Bu klip {lens} bir AN taşıyor mu — birini KAYDIRMAYI durdurup izleten, paylaştıran? "
        "Yoksa SIRADAN / rutin / unutulur mu?\n"
        "DÜŞÜK (score 1-4) sayılanlar: HİKÂYESİ OLMAYAN rutin spor/oyun anı (sıradan bir "
        "düşme, olağan bir müsabaka anı), sıradan tepki, 'olabilir ama özel değil', olayın ne "
        "olduğu belirsiz, izleyiciyi durduracak bir tepe YOK.\n"
        "YÜKSEK (score 7-10): net bir çarpıcı/komik/dokunaklı TEPE var, ilk 2 saniyede "
        "kanca, sonuna kadar 'ne olacak' merakı.\n"
        "DİKKAT: bir kapak aldatıcı olabilir — SEN 9 karenin TÜMÜNE bakıp GERÇEK olayı yargıla, "
        "'aksiyon gibi görünüyor'a kanma.\n"
        "ÖNEMLİ: bu video SESSİZ yayınlanacak (orijinal ses atılıp Türkçe anlatım basılıyor). "
        "Klibin etkisi SESE dayanıyorsa (kahkaha sesi, diyalog/konuşma esprisi, müzik/şarkı anı) "
        "ve görüntü TEK BAŞINA sıradansa → works_muted=false.\n"
        "- engaging: gerçekten durdurup izleten/paylaşılası mı?\n"
        "- score: 1-10 izlenme-değerliliği.\n"
        "- works_muted: SES OLMADAN da anlaşılır ve etkileyici mi?\n"
        'SADECE JSON: {"engaging": <bool>, "score": <1-10>, "works_muted": <bool>, '
        '"reason": "<çok kısa>"}'
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
    "Aşağıda bir video klibinin GERÇEK 9 karesi (storyboard, zaman-sıralı) ve o klip için "
    "yazılmış Türkçe bir ANLATIM var.\n"
    # BAŞLIK = poster'ın kendi tarifi. Kareler kişilerin KİM OLDUĞUNU (gelin mi kızı mı,
    # arkadaş mı akraba mı) söyleyemez — o bilgi yalnız başlıkta. Başlıksız yargıç rol
    # uydurmasını göremez (short 1140). Aynı kalıp judge_clip_quality/tone-fit'te de var.
    "KLİBİN KENDİ BAŞLIĞI (poster'ın tarifi — kişilerin KİM olduğu konusunda KARELERDEN "
    "daha güvenilir): {title}\n"
    # BAŞLIĞIN SINIRI (short 1164): başlık besleme kuralı fazla açıktı. Klip 18 saniye
    # boyunca kafeste miyavlayan bir kediden ibaretti (ne sahiplenme, ne çıkış, ne dönüş);
    # başlık 'Came for a dog and left with him' dediği için anlatım 'sonunda fark edildi,
    # köpek yerine onunla döndüler' yazdı ve kapı 'başlıkta var' diye geçirdi. İzleyici o
    # dönüşü GÖRMEDİĞİ için videodan hiçbir şey anlamadı.
    "BAŞLIĞIN SINIRI: başlık, ekranda GÖRÜNEN şeyi adlandırabilir/açıklayabilir (kim kimin "
    "nesi, elindeki nesne ne, olayın amacı ne). Ama ekranda HİÇ OLMAYAN bir olayı, SONUCU "
    "ya da devamını anlattıramaz. Başlıkta olsa BİLE karelerde karşılığı yoksa o olay "
    "anlatıma giremez — 'başlıkta yazıyor' bir savunma DEĞİLDİR.\n"
    "ANLATIM:\n---\n{narr}\n---\n"
    "Bu anlatım, karelerdeki ÖZNE ve TEMEL OLAYLA örtüşüyor mu? Şu 3 durumda 'faithful=false' de:\n"
    "  1) Tamamen FARKLI özne (anlatım 'köpek/futbol' der ama karelerde kedi var) VEYA\n"
    "  2) Ekranda AÇIKÇA olmayan büyük bir olay/ortam (anlatım 'denize dalıyor' der, deniz yok) VEYA\n"
    "  3) UYDURULMUŞ SOMUT VARLIK/OLAY: anlatım karelerde GÖRÜNMEYEN belirli bir CANLI / NESNE / "
    "KİŞİ ya da onun yaptığı bir eylem ekliyorsa (örn. 'yolda bir YENGEÇ buldu' ama karelerde "
    "yengeç yok; 'yavrusunu getirdi' ama yavru yok; 'ikinci bir köpek' ama tek köpek var). "
    "İkinci bir hayvan/nesne/kişi ve onunla ilgili alt-olay UYDURMAK = sadık DEĞİL.\n"
    "  4) GÖRÜNMEYEN DEĞİŞİM: anlatım bir DEĞİŞİM/GEÇİŞ ANI iddia ediyor ama karelerde o "
    "değişim YOK — durum baştan sona aynı. Sonuç durumundan GERİYE DÖNÜK olay uydurma: "
    "bir şey ilk kareden beri öyleyse, onu 'az önce oldu' diye anlatmak sadık DEĞİL "
    "(örn. anne ilk kareden beri cübbeli yatıyor ve oğlun kepi hiç başından çıkmıyorken "
    "'oğlu kepini çıkarıp annesine giydirdi' demek). Kareler o anı gösteriyorsa serbest.\n"
    "  5) UYDURMA ROL / AKRABALIK / KİMLİK: anlatım ekrandaki kişilere BAŞLIĞIN ve "
    "karelerin desteklemediği bir kimlik ya da ilişki atıyorsa sadık DEĞİL. Kişi SAYISI "
    "doğru olsa bile hikâye değişir. GERÇEK örnek-hata (short 1140): düğünde tekerlekli "
    "sandalyedeki DAMAT ve onunla dans eden GELİN var, başlık 'Have you some friends like "
    "he does' (onu kaldıranlar ARKADAŞLARI) — anlatım ise 'ayakta duramayan bir BABA, "
    "KIZININ kollarında dans etti' dedi ve ayrıca 'gelin ile damat' diye AYRI bir çift "
    "icat edip kendi içinde çelişti. Baba/kız, karı/koca, anne/oğul gibi akrabalık ya da "
    "'sağdıç/damat/gelin' gibi rol iddiaları BAŞLIK veya kareler AÇIKÇA gösteriyorsa "
    "serbest; göstermiyorsa UYDURMA. Anlatım aynı kişiyi iki farklı kimlikle anıyorsa "
    "(hem 'damat' hem 'baba') bu da sadık DEĞİL.\n"
    "  6) EYLEMİN YÖNÜ TERS: anlatım eylemi doğru adlandırıyor ama YÖNÜNÜ ters yazıyorsa "
    "sadık DEĞİL. İLK kareyle SON kareyi karşılaştır — ekranda ne ÇOĞALDI, ne EKSİLDİ? "
    "Ekleme/çıkarma, takma/sökme, açma/kapama, doldurma/boşaltma çiftlerinde yön hikâyenin "
    "tamamını belirler. GERÇEK örnek-hata (short 1156): duvar ilk karede gazeteyle kaplı, "
    "son karede gazete yok ve yerinde sarı notlar var → adam gazeteleri SÖKÜP altındaki "
    "sürprizi açıyor; anlatım 'kağıtları duvara yapıştırıyor' dedi → özne sürprizi "
    "HAZIRLAYAN sanıldı, oysa kendisine hazırlananı AÇAN taraf.\n"
    "  7) ABARTI SONUCU TERS ÇEVİRMİŞ: duygu/gerilim/benzetme serbesttir AMA olayın SONUCU "
    "karelerde ne ise odur. 'Neredeyse düştü' ≠ 'düştü', 'zorlandı' ≠ 'başaramadı', "
    "'sendeledi' ≠ 'yığıldı', 'kaçmaya çalıştı' ≠ 'kaçtı'. GERÇEK örnek-hata (short 1146): "
    "karelerde üç adam sendeleyip savruluyor ama ÜÇÜ DE AYAKTA KALIYOR ve gülüyor; anlatım "
    "'bacakları boşaldı, sarsılarak YIĞILDI' dedi → sadık DEĞİL. Denemenin başarılı mı "
    "başarısız mı bittiği, kimin ayakta kaldığı, bir şeyin düşüp düşmediği KARELERDEN "
    "okunur; anlatım bunun TERSİNİ söylüyorsa faithful=false.\n"
    "ŞUNLAR faithful=false YAPMAZ (SERBEST): mizah, abartı, lakap, benzetme, iç ses, öznenin ne "
    "'hissettiği', küçük sıra/aşama farkı — bunlar YORUM, yeni FİZİKSEL VARLIK değil. Ayrım: "
    "duygu/yorum serbest AMA ekranda olmayan somut bir şey/canlı EKLEMEK ya da olayın "
    "SONUCUNU tersine çevirmek yasak.\n"
    "Kareler küçük/belirsizse ve ANLATIMDA uydurma varlık YOKSA → faithful=TRUE (şüphede sadık).\n"
    "- faithful: özne+temel olay örtüşüyor VE uydurulmuş varlık/alt-olay/değişim/rol YOK mu?\n"
    "- mismatch: sadık değilse tek cümle (Türkçe) — özellikle uydurma varlığı ADIYLA söyle "
    "(örn. 'anlatımdaki yengeç ekranda yok').\n"
    'SADECE JSON: {{"faithful": <bool>, "mismatch": "<...>"}}'
)


def verify_curated_narration(clip, narration_text: str, *, vision_call,
                             ffmpeg_path: str = "ffmpeg", title: str = ""):
    """Storyboard (gerçek 9 kare) + anlatım → anlatım gerçek olaya sadık mı, uydurma olay
    var mı. Döner NarrationCheck ya da None (kare/vision hatası → fail-open, çağıran sadık
    sayar). Mizah/abartı serbest; yalnız uydurma OLAY yakalanır.

    ``title``: klibin kendi başlığı — kişilerin KİM olduğunu (arkadaş mı kızı mı) kareler
    söyleyemez, uydurma rol/akrabalık ancak başlıkla yargılanır (short 1140)."""
    from short_bot.claude_cli import run_json
    from short_bot.reel import _storyboard_frames
    if not (narration_text or "").strip():
        return None
    try:
        with tempfile.TemporaryDirectory() as td:
            board = Path(td) / "faith_board.jpg"
            # sadakat yargısı ince sıra/özne farkına bakar → daha net kare (short 962) +
            # 3×3=9 kare: seyrek örneklem uydurma/eksik özne yargısını yanıltıyordu (bkz. D).
            if not _storyboard_frames(clip, board, ffmpeg_path, cols=3, rows=3, frame_w=384):
                return None
            if not board.exists() or board.stat().st_size == 0:
                return None
            # SADAKAT KAPISI geçici vision hatasında None dönüp sessizce ATLANMASIN (short 976:
            # verify None döndü → kapı fail-open → uydurma anlatım geçti). Burst-throttle'a karşı
            # ek tur → None yalnız gerçekten doğrulanamayınca (kapı o zaman sadık sayar).
            last: Exception | None = None
            for _ in range(2):
                try:
                    return run_json(_FAITH_PROMPT.format(narr=narration_text[:900],
                                                         title=(title or "(başlık yok)")[:300]),
                                    NarrationCheck,
                                    claude_path=vision_call.claude_path, model=vision_call.model,
                                    backend=vision_call.backend, api_key=vision_call.api_key,
                                    image_path=board, retries=2, timeout_s=45)
                except Exception as e:  # noqa: BLE001 — geçici → tekrar dene
                    last = e
            log.info(f"  kürate[sadakat]: yargı doğrulanamadı ({last})")
            return None
    except Exception as e:  # noqa: BLE001
        log.info(f"  kürate[sadakat]: yargı hatası ({e})")
        return None


def judge_clip_quality(clip, *, vision_call, ffmpeg_path: str = "ffmpeg",
                       tone: str = "mizah", title: str = ""):
    """Storyboard (GERÇEK 9 kare) → klip izlenesi mi yoksa sıradan mı. Döner ClipQuality
    ya da None (kare/vision hatası → çağıran fail-open kararı verir).

    ``title``: klibin kaynak başlığı. Kapının kareyi ÇIPLAK yorumlamasını önler (bkz.
    _quality_prompt) — verilmezse prompt bire bir eski hâlinde kalır (sıfır regresyon)."""
    from short_bot.claude_cli import run_json
    from short_bot.reel import _storyboard_frames
    try:
        with tempfile.TemporaryDirectory() as td:
            board = Path(td) / "q_board.jpg"
            # 3×3=9 kare (6 değil): seyrek örneklem klibin asıl öznesini kaçırabiliyor
            # (çöpçü klibinde köpek 6 kareye hiç düşmedi → vision 'çamaşır sepeti' dedi).
            if not _storyboard_frames(clip, board, ffmpeg_path, cols=3, rows=3, frame_w=384):
                return None
            if not board.exists() or board.stat().st_size == 0:
                return None
            return run_json(_quality_prompt(tone, title), ClipQuality,
                            claude_path=vision_call.claude_path, model=vision_call.model,
                            backend=vision_call.backend, api_key=vision_call.api_key,
                            image_path=board, retries=1, timeout_s=45)
    except Exception as e:  # noqa: BLE001
        log.info(f"  kürate[kalite]: yargı hatası ({e})")
        return None


# ── FİNAL QA KAPISI (bitmiş ürünü kimse izlemiyordu) ─────────────────────────
# Kullanıcı: 'vision/senaryo tutarsızlığı, sahne senkronu → zevksiz/anlamsız videolar
# çıkabiliyor'. Tüm kapılar render ÖNCESİ proxy'lerde (ham klip + metin) çalışıyordu;
# render'ın eklediği bütün (kesim + altyazı çipleri + tempo + vurgular) hiçbir yargıdan
# geçmiyordu. Bu yargı BİTMİŞ videonun storyboard'ına + anlatım metnine bakıp 'yayınlanır
# mı' der — üst-akıştaki her hatayı (yanlış tarif, kopuk senaryo, ton kayması) tek noktada,
# gerçek ürün üzerinde yakalar.
class FinalVideoQA(BaseModel):
    """Bitmiş (render edilmiş) short'un storyboard yargısı — yayınlanabilir mi."""
    # ZORUNLU alanlar (bkz. ClipQuality): boş/yarım yanıt → ValidationError → None →
    # çağıran fail-open (tek vision hıçkırığı tamamlanmış renderı çöpe atmasın).
    watchable: bool          # izleyici sonuna kadar izler mi — bütün ANLAMLI mı
    score: int               # 1 (anlamsız/kopuk) .. 10 (kesin yayınlanır)
    sync_ok: bool = True     # anlatım/altyazı ekrandaki olayla örtüşüyor mu
    tone_ok: bool = True     # içerik kanal tonuna uygun mu
    reason: str = ""


def _final_qa_prompt(tone: str, narration_text: str) -> str:
    if tone == "duygu":
        lens = "DUYGUSAL/DOKUNAKLI (içini ısıtan, gözünü dolduran)"
    elif tone == "karma":
        lens = "KARMA/'oh olsun' (hak edilmiş, tatmin edici hafif comeuppance)"
    else:
        lens = "KOMİK/ŞAŞIRTICI (kahkaha, 'vay be', beklenmedik)"
    return (
        "Bu, YAYINLANMAK üzere üretilmiş DİKEY bir kısa videonun GERÇEK 9 karesi "
        "(storyboard, zaman-sıralı, tek ızgara). Videoya Türkçe anlatım altyazı çipleri ve "
        "görsel vurgular render EDİLMİŞ durumda — gördüğün, izleyicinin göreceği bitmiş ürün.\n"
        f"Videonun TÜM ANLATIM METNİ:\n---\n{narration_text}\n---\n"
        f"Kanalın tonu: {lens}.\n"
        "Yayın editörü gibi yargıla:\n"
        "- watchable: bir izleyici bunu SONUNA KADAR izler mi — görüntü + anlatım birlikte "
        "ANLAMLI, takip edilebilir bir bütün mü? (Kopuk/anlamsız/sıkıcıysa false.)\n"
        "- sync_ok: KARE KARE kontrol et — her karenin İÇİNDEKİ altyazı çipini oku ve O "
        "KAREDE görünenle karşılaştır. Altyazı o anda ekranda OLMAYAN bir olayı anlatıyorsa "
        "false — olay klipte daha geç ya da erken oluyor olsa bile (gerçek hata, short 1216: "
        "'öğrenciler etrafını sardı' altyazısı akarken ekranda adam TEK BAŞINA kutu "
        "açıyordu → bu sync_ok=false olmalıydı). Videonun bir bölümünde altyazının hiç "
        "anlatmadığı uzun bir olay akıyorsa da false.\n"
        "- tone_ok: içerik bu kanal tonuna oturuyor mu?\n"
        "- score: 1-10 genel yayın kalitesi (1=anlamsız/zevksiz, 10=kesin yayınlanır).\n"
        'SADECE JSON: {"watchable": <bool>, "score": <1-10>, "sync_ok": <bool>, '
        '"tone_ok": <bool>, "reason": "<çok kısa TR>"}'
    )


def judge_final_video(video_path, narration_text: str, *, vision_call,
                      ffmpeg_path: str = "ffmpeg", tone: str = "mizah", log=None):
    """BİTMİŞ videonun storyboard'ı (9 kare, altyazı/vurgular dahil) + anlatım metni →
    'yayınlanır mı' yargısı. Döner FinalVideoQA ya da None (kare/vision hatası →
    çağıran fail-open kararı verir; render tek hıçkırıkla çöpe atılmaz).

    ``log``: KOŞU logger'ı. Bu modülün kendi logger'ı koşu dosyasına bağlı DEĞİL —
    verilmezse yargıç arızası koşu logunda hiç görünmez (short 1077: yargılanmamış
    video 'kapıdan geçti' sanıldı)."""
    from short_bot.claude_cli import run_json
    from short_bot.reel import _storyboard_frames
    _log = log or globals()["log"]
    try:
        with tempfile.TemporaryDirectory() as td:
            board = Path(td) / "fqa_board.jpg"
            if not _storyboard_frames(video_path, board, ffmpeg_path,
                                      cols=3, rows=3, frame_w=384):
                _log.warning("  kürate[final-qa]: storyboard kurulamadı → yargı YOK")
                return None
            if not board.exists() or board.stat().st_size == 0:
                _log.warning("  kürate[final-qa]: storyboard boş → yargı YOK")
                return None
            # Geçici vision hatasına karşı ek tur (bkz. verify_curated_narration): None yalnız
            # gerçekten doğrulanamayınca dönsün.
            last: Exception | None = None
            for _ in range(2):
                try:
                    return run_json(_final_qa_prompt(tone, (narration_text or "")[:900]),
                                    FinalVideoQA,
                                    claude_path=vision_call.claude_path, model=vision_call.model,
                                    backend=vision_call.backend, api_key=vision_call.api_key,
                                    image_path=board, retries=2, timeout_s=45)
                except Exception as e:  # noqa: BLE001 — geçici → tekrar dene
                    last = e
            _log.warning(f"  kürate[final-qa]: yargı doğrulanamadı ({last})")
            return None
    except Exception as e:  # noqa: BLE001
        _log.warning(f"  kürate[final-qa]: yargı hatası ({e})")
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


# ── REVEAL ÇIPASI (ödül anı ses ile görüntüde AYNI saniyede olsun) ───────────
# SORUN (short 1078): klipte anne çocuğu ~%41'de tanıyıp sarılıyor; anlatım ödülü
# ~%61'de söylüyor. İzleyici kucaklaşmayı GÖRDÜKTEN sonra "kendi oğludur" cümlesini
# duyuyor → reveal ıskalanıyor, merak eğrisi düşüyor. detect_scene_split yalnız MEKÂN
# değişimini sayıyor (tek mekânda dönen bu klipte None döndü). Burada aranan şey farklı:
# mekân değil DURUM değişiyor (arama → kavuşma). Bulunan oran render'da fit_clip_with_anchor
# ile ses tarafındaki ödül cümlesine çakıştırılır.
class RevealAnchor(BaseModel):
    """Storyboard vision yargısı — klipte ödül/dönüm anı var mı, hangi karede başlıyor."""
    has_turn: bool = False
    turn_frame: int = 0      # dönümün İLK göründüğü kare (1..N); yoksa 0


_REVEAL_ANCHOR_PROMPT = (
    "Bu bir kısa video klibinin STORYBOARD'ı (zaman-sıralı {n} kare, soldan sağa, sonra "
    "alt sıra). Klibin ÖDÜL/DÖNÜM anını bul: kurulumun bitip olayın DEĞİŞTİĞİ an — "
    "aranan şeyin bulunduğu, kavuşmanın/yardımın/sürprizin/tepkinin BAŞLADIĞI ilk kare "
    "(örn. arama biter ve sarılma başlar; hayvan kurtarılır; şaka patlar).\n"
    "ÖNEMLİ: Kurulum karelerini (hazırlık, bekleme, arama) sayma — yalnız durumun "
    "değiştiği İLK kareyi ver. Kamera hareketi/zoom dönüm DEĞİLDİR. Baştan sona aynı "
    "durum sürüyorsa has_turn=false.\n"
    "- has_turn: net bir dönüm/ödül anı var mı?\n"
    "- turn_frame: dönümün İLK göründüğü kare numarası (1-{n}); yoksa 0.\n"
    'SADECE JSON: {{"has_turn": <bool>, "turn_frame": <int>}}'
)


def detect_reveal_anchor(clip, *, vision_call, ffmpeg_path: str = "ffmpeg",
                         cols: int = 3, rows: int = 3):
    """Storyboard → klipte ödül/dönüm anının ORANI (0-1) ya da None.

    None (çıpa yok, mevcut davranış): dönüm yok / kare uçlarda (1. veya son kare —
    kurulum ya da bitiş yok demektir, çıpa zorlamak görüntüyü bozar) / vision hatası."""
    from short_bot.claude_cli import run_json
    from short_bot.reel import _storyboard_frames
    n = cols * rows
    try:
        with tempfile.TemporaryDirectory() as td:
            board = Path(td) / "reveal_board.jpg"
            if not _storyboard_frames(clip, board, ffmpeg_path, cols=cols, rows=rows,
                                      frame_w=384):
                return None
            if not board.exists() or board.stat().st_size == 0:
                return None
            res = run_json(_REVEAL_ANCHOR_PROMPT.format(n=n), RevealAnchor,
                           claude_path=vision_call.claude_path, model=vision_call.model,
                           backend=vision_call.backend, api_key=vision_call.api_key,
                           image_path=board, retries=1, timeout_s=45)
    except Exception as e:  # noqa: BLE001
        log.info(f"  kürate[çıpa]: dönüm anı tespiti hatası ({e})")
        return None
    tf = res.turn_frame
    if not res.has_turn or tf < 2 or tf > n:
        return None
    # Kare k'nın ORTASI ≈ (k-0.5)/n oranı. [0.2, 0.8]'e sıkıştır: uçtaki çıpa
    # parçalardan birini aşırı gerer (hız sınırı zaten reddeder, boşuna vision harcanmasın).
    return max(0.2, min(0.8, (tf - 0.5) / n))


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


# ── ZAMAN-SIRALI BEAT SHEET (anlatım görüntünün zaman çizgisine oturur) ───────
# SORUN (short 990, kullanıcı: 'sahneler ile cümleler oturmuyor'): _describe_clip tüm klibi
# TEK BLOK özetliyor ('koşuculara yardım ediliyor') → zaman çizgisi kayboluyor, anlatıcı
# ödülü (yardım/kavuşma) ERKEN açıyor, görüntü hâlâ kurulumdayken (düşüş). Ayrıca tek blok
# 'kaç kişi/ne sırayla' detayını eritiyor ('ikisi' derken 3-4 kişi taşıyor).
# ÇÖZÜM (KANITLANDI: ücretsiz gemini-flash-lite bütünü verince olayları BİRLEŞTİRİYOR ama
# klibi ÜÇE bölüp AYRI sorunca her dilimi DOĞRU ve zaman-sıralı anlatıyor): klibi segment'lere
# böl, her segment'i ayrı tarif et → anlatıcıya 'BAŞTA X, SONRA Y, SONUNDA Z; ödülü sona sakla'
# beat listesi ver. Böylece cümleler ekrandaki ana denk gelir.
def describe_clip_beats(clip, *, vision_call, ffmpeg_path: str = "ffmpeg",
                        segments: int = 3, duration_s: float | None = None,
                        title: str = "") -> str:
    """Klibi ``segments`` eşit zaman dilimine böl, her dilimi AYRI storyboard'la tarif et →
    zaman-sıralı 'beat sheet' döndür (ör. 'BAŞ (0-12sn): …\\nORTA (12-23sn): …\\nSON …').
    Boş döner (fail-open): süre okunamaz / vision yok / tüm dilimler boş → çağıran tek-blok
    _describe_clip'e düşer.

    ``title``: klibin kaynak başlığı → dilim tarifçisine TANIMA bağlamı (short 1216: başlıksız
    vision 'yeni ayakkabıyı giyme'yi 'çanta karıştırma' diye okudu → SON dilimi anlatılamadı).
    Sadakat/kalite/netlik kapıları başlığı zaten alıyor; korumalı enjeksiyon describe_storyboard'da."""
    import subprocess
    from short_bot.footage_matcher import describe_storyboard
    from short_bot.reel import _ffprobe_path
    if duration_s is None:
        try:
            out = subprocess.run(
                [_ffprobe_path(ffmpeg_path), "-v", "error",
                 "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)],
                capture_output=True, text=True, timeout=30)
            duration_s = float((out.stdout or "").strip())
        except Exception:  # noqa: BLE001
            return ""
    if not duration_s or duration_s < 6 or segments < 2:
        return ""
    step = duration_s / segments
    labels = (["BAŞ", "ORTA", "SON"] if segments == 3
              else [f"B{i+1}" for i in range(segments)])
    beats: list[str] = []
    for i in range(segments):
        s0, s1 = i * step, min(duration_s, (i + 1) * step)
        try:
            with tempfile.TemporaryDirectory() as td:
                seg = Path(td) / f"seg{i}.mp4"
                board = Path(td) / f"segb{i}.jpg"
                r = subprocess.run(
                    [ffmpeg_path, "-v", "error", "-ss", f"{s0:.2f}", "-to", f"{s1:.2f}",
                     "-i", str(clip), "-c", "copy", str(seg)],
                    capture_output=True, timeout=60)
                if r.returncode != 0 or not seg.exists() or seg.stat().st_size == 0:
                    # -c copy anahtar-kare hizasında kesemezse yeniden-kodla (yavaş ama sağlam)
                    subprocess.run(
                        [ffmpeg_path, "-v", "error", "-ss", f"{s0:.2f}", "-to", f"{s1:.2f}",
                         "-i", str(clip), "-an", str(seg)],
                        capture_output=True, timeout=90)
                if not seg.exists() or seg.stat().st_size == 0:
                    continue
                from short_bot.reel import _storyboard_frames
                # 3×3=9 KARE (6 DEĞİL): seyrek örneklem dilim içindeki DEĞİŞİMİ kaçırıyor.
                # GERÇEK HATA (short 1154 klibi): BAŞ dilimi 20 saniye ve o dilimde adam
                # gazeteyi söküp altındaki SARI NOT duvarını açığa çıkarıyor; 6 kareyle
                # vision duvarı 'bare tan wall with a framed photograph' diye tarif etti,
                # notları hiç görmedi. Anlatım (DOĞRU olarak) 'notlar çıkıyor' deyince
                # netlik kapısı beat sheet'te yok diye UYDURMA sayıp reddetti — eksik beat
                # sheet İYİ anlatımı eledi. Sadakat/kalite yargıları aynı dersle zaten
                # 9 kareye geçmişti (bkz. _storyboard_frames çağrıları orada).
                if not _storyboard_frames(seg, board, ffmpeg_path, cols=3, rows=3,
                                          frame_w=384):
                    continue
                desc, _static = describe_storyboard(board, vision_call=vision_call,
                                                    n_frames=9, context=title)
                if desc and desc.strip():
                    lbl = labels[i] if i < len(labels) else f"B{i+1}"
                    beats.append(f"{lbl} ({int(s0)}-{int(s1)}sn): {desc.strip()}")
        except Exception as e:  # noqa: BLE001
            log.info(f"  kürate[beat]: segment {i} tarif hatası ({e})")
            continue
    return "\n".join(beats)


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
            # bandın DİKEY konumu hassas ölçülmeli → daha net kare
            if not _storyboard_frames(clip, board, ffmpeg_path, cols=cols, rows=rows, frame_w=384):
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


# Bandı YALNIZ üst ya da alt KENAR BÖLGESİNDE (%20) ise kır — tepede küçük boşluk olsa BİLE
# (short 967: caption y≈0.12, tepeye yapışık değil ama üst %20'de → eskiden 'ortada yüzüyor'
# sanılıp kırpılmıyordu; heavy-text kapısı da iyi klibi reddediyordu). Gerçekten ORTADA yüzen
# başlık (short 935 tembel-hayvan y≈0.48) temiz kırpılamaz (içerik kaybı) → dokunma.
_BANNER_TOP_MAX = 0.20    # bandın DİBİ üst %20 içindeyse (ya da TEPESİ alt %20'de) kırpılır
_BANNER_MAX_CUT = 0.24    # tek seferde en çok bu kadar kırp (içerik koru; %20 bölge + pay)


def crop_source_banner(clip, banner, *, ffmpeg_path: str = "ffmpeg", out_path):
    """Kaynağın gömülü yazı-bandını KIRP — bant üst ya da alt KENAR BÖLGESİNDE (%20) ise (temiz
    strip). Gerçekten ortada yüzen banda dokunmaz (None). Blur değil, crop (temiz)."""
    if banner is None or not banner.present:
        return None
    yc = float(banner.y_center or 0.5)
    f = max(0.0, min(0.30, float(banner.frac or 0.0)))
    if f < 0.05:
        return None                       # ihmal edilebilir — kırpmaya değmez
    top_edge = yc - f / 2.0                # bandın üst sınırı (0-1)
    bot_edge = yc + f / 2.0                # bandın alt sınırı (0-1)
    # ÜST bölge: bandın DİBİ üst %20 içinde → üstten bot_edge kadar at (tepedeki boşluğu da).
    if bot_edge <= _BANNER_TOP_MAX:
        cut = min(_BANNER_MAX_CUT, bot_edge + 0.02)
        vf = f"crop=iw:trunc(ih*(1-{cut:.3f})/2)*2:0:trunc(ih*{cut:.3f}/2)*2"
        where = "üst"
    # ALT bölge: bandın TEPESİ alt %20 içinde → alttan (1-top_edge) kadar at.
    elif top_edge >= (1.0 - _BANNER_TOP_MAX):
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


# ── GÖMÜLÜ-YAZI (editlenmiş repost) REDDİ ────────────────────────────────────
# Kullanıcı: 'sadece temiz görüntü olsun'. Watermark/köşe-logo (detect_watermark) ve tek
# üst/alt banner (detect_source_banner) ayrı ele alınıyor; bu detektör GENEL 'klip gömülü
# ALTYAZI/CAPTION ile mi DOLU' sorusunu yanıtlar (short 968: 'THIS IS JAPAN' banner +
# İngilizce/Japonca konuşma altyazıları — editlenmiş repost, hem kirli hem çoğu zaman
# sorunlu içerik). Doğal sahne yazısını (tabela/forma/etiket) editör katmanından AYIRIR.
class HeavyText(BaseModel):
    """Storyboard vision — klip TEMİZ çekim mi yoksa gömülü yazıyla dolu edit/repost mü."""
    # ZORUNLU (bkz. WatermarkDetect.present): boş yanıt → ValidationError → None → gate FAIL-CLOSED.
    heavy: bool                  # gömülü altyazı/caption/banner ile DOLU → temiz footage DEĞİL
    kinds: list[str] = []        # subtitle / caption / banner / watermark / branding
    note: str = ""


_HEAVY_TEXT_PROMPT = (
    "Bu bir kısa video klibinin STORYBOARD'ı (zaman-sıralı 6 kare, tek ızgara). Bu klip TEMİZ "
    "bir çekim mi, yoksa görüntüye SONRADAN BİNDİRİLMİŞ yazıyla mı DOLU (editlenmiş repost)?\n"
    "GÖMÜLÜ YAZI SAYILAN (editör/platform katmanı → temiz DEĞİL): konuşmayı çeviren ALTYAZI/"
    "CAPTION şeritleri, başlık/BANNER metni, kanal ya da @kullanıcı watermark'ı, ekrana basılmış "
    "açıklama/anlatı metni, meme yazısı.\n"
    "GÖMÜLÜ SAYILMAYAN (doğal sahne, sorun DEĞİL): tabela, dükkan adı, forma numarası, ürün "
    "etiketi, sokak levhası, arka planda GERÇEKTEN var olan yazılar.\n"
    "- heavy: klip gömülü ALTYAZI/CAPTION/BANNER/watermark ile DOLU mu? (birden çok karede "
    "editör yazı katmanı, konuşma altyazısı ya da kalıcı banner varsa → true. TEK küçük köşe "
    "etiketi ya da yalnız doğal sahne yazısı → false.)\n"
    "- kinds: hangileri (subtitle, caption, banner, watermark, branding).\n"
    'SADECE JSON: {"heavy": <bool>, "kinds": ["..."], "note": "<short English>"}'
)


def detect_heavy_text(clip, *, vision_call, ffmpeg_path: str = "ffmpeg"):
    """Storyboard → klip gömülü altyazı/caption/banner ile DOLU mu (editlenmiş repost).
    Döner HeavyText ya da None (DOĞRULANAMADI → çağıran güvenlik için fail-CLOSED reddeder).
    Burst-throttle'a karşı retry'lı (None yalnız gerçekten doğrulanamayınca)."""
    from short_bot.claude_cli import run_json
    from short_bot.reel import _storyboard_frames
    try:
        with tempfile.TemporaryDirectory() as td:
            board = Path(td) / "text_board.jpg"
            if not _storyboard_frames(clip, board, ffmpeg_path, cols=3, rows=2, frame_w=384):
                return None
            if not board.exists() or board.stat().st_size == 0:
                return None
            last: Exception | None = None
            for _ in range(2):
                try:
                    return run_json(_HEAVY_TEXT_PROMPT, HeavyText,
                                    claude_path=vision_call.claude_path, model=vision_call.model,
                                    backend=vision_call.backend, api_key=vision_call.api_key,
                                    image_path=board, retries=2, timeout_s=45)
                except Exception as e:  # noqa: BLE001 — geçici → tekrar dene
                    last = e
            log.info(f"  kürate[yazı]: gömülü-yazı tespiti doğrulanamadı ({last})")
            return None
    except Exception as e:  # noqa: BLE001
        log.info(f"  kürate[yazı]: gömülü-yazı tespiti hatası ({e})")
        return None
