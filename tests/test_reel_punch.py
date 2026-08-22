"""Vurgu punch-in: ritmi zamanlayıcıya değil İÇERİĞE bağlar.

Kesme efektleri ve Ken Burns videoya ritim veriyordu ama hiçbiri içeriğe bağlı
değildi — hepsi zamanlayıcıyla dönüyordu. İnsan kurgucu kamerayı vurucu kelimede
ittirir: "tam YETMİŞ kanserojen" derken görüntü bir tık yaklaşır.
"""
import subprocess

import pytest
from PIL import Image

from short_bot.reel_punch import (MAX_PUNCHES, MIN_GAP_S, PUNCH_AMOUNT,
                                  PUNCH_DECAY_S, punch_times, punch_vf,
                                  select_punches)


def test_darbe_yoksa_filtre_de_yok():
    # Darbe olmadan boş bir crop/scale eklemek gereksiz bir yeniden kodlamadır.
    assert punch_vf([]) == ""


def test_darbe_zamani_filtreye_giriyor():
    vf = punch_vf([12.5])
    assert "12.500" in vf
    assert vf.startswith("zoompan=")
    assert "s=1080x1920" in vf


def test_cok_yakin_darbeler_atilir():
    # Üst üste binen darbeler zoom'u titretir.
    out = select_punches([10.0, 10.2, 10.5])
    assert out == [10.0]


def test_uzak_darbeler_korunur():
    out = select_punches([10.0, 10.0 + MIN_GAP_S + 0.1])
    assert len(out) == 2


def test_darbe_sayisi_sinirli():
    out = select_punches([i * 2.0 for i in range(30)])
    assert len(out) == MAX_PUNCHES


def test_sayilar_ve_tepe_darbe_olur():
    nums = [{"text": "70", "start_s": 12.0, "end_s": 12.4}]
    assert punch_times(nums, 20.0) == [12.0, 20.0]


def test_tepe_yoksa_sadece_sayilar():
    nums = [{"text": "70", "start_s": 12.0, "end_s": 12.4}]
    assert punch_times(nums, None) == [12.0]


def test_sayi_yoksa_sadece_tepe():
    assert punch_times([], 18.0) == [18.0]


def test_ffmpeg_ifadeyi_kabul_ediyor(tmp_path):
    """İfade GEÇERLİ olmalı — hatalı bir filtre grafiği tüm montajı düşürür."""
    out = tmp_path / "o.mp4"
    vf = punch_vf([1.0, 3.0])
    p = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=4",
         "-vf", vf, "-frames:v", "60", "-c:v", "libx264", "-preset", "ultrafast",
         str(out)],
        capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-600:]
    assert out.exists() and out.stat().st_size > 0


def _en_iyi_olcek(kare, ref):
    """kare, ref'in kaç katı büyütülmüş hâline en çok benziyor? (MERKEZDEN)

    Zoom'un MERKEZLİ olduğunu doğrulamanın tek yolu bu. "Görüntü değişti mi"
    ölçmek YETMEZ: gerçek hata tam olarak buydu — zoom oluyordu ama SOL-ÜST
    KÖŞEYE çakılıydı (crop'un iw'si bağlantının sabit genişliğini görüyordu).
    Kaba testler onu geçirdi; merkez-eşleşmesi yakaladı.
    """
    np = pytest.importorskip("numpy")
    h, w = ref.shape
    en, hata = 1.0, 1e18
    for i in range(0, 71):
        s = 1.0 + i * 0.002
        nh, nw = int(h * s), int(w * s)
        buyuk = np.asarray(Image.fromarray(ref).resize((nw, nh), Image.BILINEAR),
                           dtype=np.float32)
        oy, ox = (nh - h) // 2, (nw - w) // 2
        d = float(np.abs(kare - buyuk[oy:oy + h, ox:ox + w]).mean())
        if d < hata:
            hata, en = d, s
    return en - 1.0, hata


def test_zoom_MERKEZDEN_ve_dogru_oranda(tmp_path):
    """Darbe: merkezden %6 yaklaşma, 0.35sn'de doğrusal sönüm."""
    np = pytest.importorskip("numpy")
    W, H, FPS = 270, 480, 30
    # DONDURULMUŞ kare: içerik zamanla değişmesin ki fark yalnız ZOOM'dan gelsin.
    # (Hareketli testsrc2 ile ölçüm sapıtıyor — denendi.)
    still = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate=1",
                    "-frames:v", "1", str(still)], capture_output=True, check=True)
    src = tmp_path / "s.mp4"
    subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", str(still), "-t", "3",
                    "-r", str(FPS), "-c:v", "libx264", "-preset", "ultrafast",
                    "-crf", "5", "-pix_fmt", "yuv420p", str(src)],
                   capture_output=True, check=True)
    out = tmp_path / "p.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-i", str(src), "-vf",
                        punch_vf([1.0], w=W, h=H, fps=FPS),
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "5",
                        str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]

    def kare(t):
        p = tmp_path / f"k{t}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(out), "-vf",
                        f"select=eq(n\\,{int(t * FPS)})", "-vframes", "1", str(p)],
                       capture_output=True, check=True)
        return np.asarray(Image.open(p).convert("L"), dtype=np.float32)

    ref = kare(2.5)                              # darbe çoktan bitti → zoomsuz
    tepe, h_tepe = _en_iyi_olcek(kare(1.0), ref)   # darbenin tepesi
    orta, _ = _en_iyi_olcek(kare(1.175), ref)      # yarı yol (yaklaşık yarı zoom)
    once, _ = _en_iyi_olcek(kare(0.5), ref)        # darbeden önce

    assert h_tepe < 5.0, f"merkez-zoom eşleşmesi zayıf ({h_tepe:.1f}) → zoom merkezli değil"
    assert abs(tepe - PUNCH_AMOUNT) < 0.02, f"darbe %{tepe*100:.1f}, beklenen %{PUNCH_AMOUNT*100:.0f}"
    assert 0.2 * PUNCH_AMOUNT < orta < 0.8 * PUNCH_AMOUNT, "sönüm doğrusal değil"
    assert once < 0.01, "darbeden ÖNCE zoom olmamalı"


def test_darbe_orani_makul():
    # Fazlası pikselleştirir ve "ucuz" görünür; azı fark edilmez.
    assert 0.03 <= PUNCH_AMOUNT <= 0.10
    assert 0.2 <= PUNCH_DECAY_S <= 0.6
