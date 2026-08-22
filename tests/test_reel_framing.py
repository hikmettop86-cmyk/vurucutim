"""Özne-farkında çerçeveleme + Ken Burns tabanı.

İKİ KUSUR:

1. APTAL MERKEZ-CROP: 16:9 stok klibi 9:16'ya kırparken hep MERKEZDEN kesiyorduk.
   Araştırma bunu otomatik faceless videonun "1 numaralı görsel ele veren işareti"
   diye adlandırıyor: özne kadrajın kenarındaysa YARISI KESİLİYOR. Oysa özne
   konumunu ZATEN BİLİYORUZ (locate_subject) — yalnız marker'da kullanıyorduk.

2. HER KLİPTE AYNI HAREKET: _ZOOMPAN tek bir sabit hareket. Aynı push her klipte
   tekrarlanınca kendisi bir ÖRÜNTÜ olur. Yön klip başına DEĞİŞMELİ (deterministik).
"""
from short_bot.reel_framing import KEN_BURNS_MOVES, crop_x, ken_burns


def test_center_crop_when_subject_is_unknown():
    """Konum bilinmiyorsa eski davranış: merkez (regresyon yok)."""
    assert crop_x(iw=1920, ow=1080, subject_x=None) == (1920 - 1080) // 2


def test_crop_follows_the_subject():
    """Özne sağdaysa kadraj SAĞA kayar — kafasını kesme."""
    center = crop_x(iw=1920, ow=1080, subject_x=0.5)
    right = crop_x(iw=1920, ow=1080, subject_x=0.85)
    left = crop_x(iw=1920, ow=1080, subject_x=0.15)
    assert left < center < right


def test_crop_never_leaves_the_frame():
    """Kenardaki özne için bile kadraj görüntünün DIŞINA taşmamalı (siyah bant)."""
    for sx in (0.0, 0.02, 0.98, 1.0):
        x = crop_x(iw=1920, ow=1080, subject_x=sx)
        assert 0 <= x <= 1920 - 1080


def test_no_crop_room_is_handled():
    """Zaten 9:16 olan klipte kırpılacak yer yok — 0 dönmeli, negatif değil."""
    assert crop_x(iw=1080, ow=1080, subject_x=0.9) == 0


def test_ken_burns_move_varies_by_clip():
    """Aynı hareket her klipte tekrarlanırsa KENDİSİ bir örüntü olur."""
    moves = {ken_burns(seed=7, index=i)["name"] for i in range(len(KEN_BURNS_MOVES))}
    assert len(moves) > 1


def test_ken_burns_is_deterministic():
    a = ken_burns(seed=7, index=2)
    b = ken_burns(seed=7, index=2)
    assert a == b


def test_every_clip_gets_motion():
    """HİÇBİR kare tamamen sabit kalmamalı — sabit kare 'slayt gösterisi' okunur."""
    for i in range(8):
        m = ken_burns(seed=3, index=i)
        assert m["z_start"] != m["z_end"] or m["pan"] != 0.0


def test_zoom_stays_within_safe_headroom():
    """Aşırı zoom kadrajı bozar / pikselleştirir."""
    for i in range(8):
        m = ken_burns(seed=5, index=i)
        for z in (m["z_start"], m["z_end"]):
            assert 1.0 <= z <= 1.25
