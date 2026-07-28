"""REVEAL ÇIPASI: klibin dönüm anı, anlatımın ödül cümlesine DENK GELMELİ.

GERÇEK HATA (short 1078): klipte anne çocuğu ~%41'de tanıyıp sarılıyor; anlatım bu
ödülü ~%61'de söylüyor. İzleyici kucaklaşmayı GÖRDÜKTEN 5 saniye sonra "karşısındaki
kendi oğludur" cümlesini duyuyor — merak eğrisi çöküyor, reveal ıskalanıyor.

KÖK: klip videoya TEK, sabit bir setpts katsayısıyla oturtuluyor (contiguous). Ses
tarafında ödülün nerede olduğunu BİLİYORUZ (timeline.seg_spans[peak_segment]), klip
tarafında dönüm anını vision veriyor — ama ikisi birbirine BAĞLANMIYOR.

ÇÖZÜM: klibi çıpadan İKİYE böl, her parçayı kendi hedef süresine oturt. Dönüm anı
ödül cümlesinin üstüne oturur; her parça KENDİ İÇİNDE sabit hızda kalır (doğal görünür).
Katsayı mevcut sınırların (CURATED_MAX_SPEEDUP/SLOWDOWN) dışına çıkarsa çıpa
UYGULANMAZ (None → çağıran tek-katsayılı eski yola düşer): görüntüyü bozmaktansa
çıpasız kal.
"""
import subprocess

import pytest

from short_bot.reel import _clip_duration_s, fit_clip_with_anchor


def _two_tone_clip(path, first_s=6, second_s=6):
    """İlk yarısı SİYAH, ikinci yarısı BEYAZ klip → geçişin nereye düştüğü ölçülebilir."""
    p1, p2 = path.parent / "_black.mp4", path.parent / "_white.mp4"
    for out, color, dur in ((p1, "black", first_s), (p2, "white", second_s)):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                        "-i", f"color=c={color}:s=360x640:d={dur}:r=30",
                        "-pix_fmt", "yuv420p", str(out)], capture_output=True, timeout=120)
    lst = path.parent / "_list.txt"
    lst.write_text(f"file '{p1.as_posix()}'\nfile '{p2.as_posix()}'\n", encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(path)], capture_output=True, timeout=120)
    return path.exists() and path.stat().st_size > 0


def _marked_opening_clip(path, open_s=2, setup_s=10, payoff_s=8):
    """Açılışı İŞARETLİ klip: ilk ``open_s`` KIRMIZI, sonra siyah kurulum, sonra beyaz ödül.

    Kırmızı bant = anlatımın 1. cümlesinin anlattığı AÇILIŞ ANI (short 1140: gelin
    tekerlekli sandalyedeki damadı kucaklıyor). Çıktının t=0'ında kırmızı yoksa o an
    KIRPILMIŞ demektir — anlatım ekranda olmayan bir şeyi anlatıyor."""
    parts = []
    for i, (color, dur) in enumerate((("red", open_s), ("black", setup_s), ("white", payoff_s))):
        p = path.parent / f"_m{i}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                        "-i", f"color=c={color}:s=360x640:d={dur}:r=30",
                        "-pix_fmt", "yuv420p", str(p)], capture_output=True, timeout=120)
        parts.append(p)
    lst = path.parent / "_mlist.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(path)], capture_output=True, timeout=120)
    return path.exists() and path.stat().st_size > 0


def _rgb_at(clip, t, tmp_path):
    """t saniyesindeki karenin ortalama (R, G, B) değeri."""
    from PIL import Image
    fp = tmp_path / f"rgb_{t}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(clip),
                    "-frames:v", "1", str(fp)], capture_output=True, timeout=60)
    if not fp.exists():
        return None
    with Image.open(fp) as im:
        px = list(im.convert("RGB").getdata())
    n = len(px)
    return tuple(sum(c[i] for c in px) / n for i in range(3))


def _is_red(rgb):
    return rgb is not None and rgb[0] > 100 and rgb[1] < 80 and rgb[2] < 80


def _brightness_at(clip, t, tmp_path):
    """t saniyesindeki karenin ortalama parlaklığı (0=siyah, 255=beyaz)."""
    from PIL import Image
    fp = tmp_path / f"probe_{t}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(clip),
                    "-frames:v", "1", str(fp)], capture_output=True, timeout=60)
    if not fp.exists():
        return None
    with Image.open(fp) as im:
        px = list(im.convert("L").getdata())
    return sum(px) / len(px)


@pytest.fixture
def two_tone(tmp_path):
    clip = tmp_path / "two_tone.mp4"
    if not _two_tone_clip(clip):
        pytest.skip("ffmpeg yok / klip üretilemedi")
    return clip


def test_anchor_moves_transition_to_narration_reveal(two_tone, tmp_path):
    """Klipte 6. saniyedeki dönüm, ödül cümlesi 4. saniyedeyse ORAYA çekilir.

    (6→4 = 1.5× hızlanma; 1.8× sınırının içinde. Daha agresif çıpa REDDEDİLİR —
    bkz. test_anchor_declined_when_speed_would_be_extreme.)"""
    out = tmp_path / "fitted.mp4"
    res = fit_clip_with_anchor(two_tone, target_s=12.0, anchor_src_s=6.0,
                               anchor_dst_s=4.0, ffmpeg_path="ffmpeg", out_path=out)
    assert res is not None, "çıpa uygulanabilir olmalıydı"

    before = _brightness_at(res, 3.0, tmp_path)
    after = _brightness_at(res, 5.0, tmp_path)
    assert before is not None and after is not None
    assert before < 60, f"çıpadan ÖNCE hâlâ ilk sahne (siyah) olmalı, parlaklık={before}"
    assert after > 195, f"çıpadan SONRA ikinci sahne (beyaz) olmalı, parlaklık={after}"


def test_anchor_fit_keeps_total_duration(two_tone, tmp_path):
    """Toplam süre hedefte kalmalı — ses uzunluğu değişmiyor."""
    out = tmp_path / "fitted2.mp4"
    res = fit_clip_with_anchor(two_tone, target_s=10.0, anchor_src_s=6.0,
                               anchor_dst_s=4.0, ffmpeg_path="ffmpeg", out_path=out)
    assert res is not None
    assert abs(_clip_duration_s(res, "ffmpeg") - 10.0) < 0.6


def test_anchor_declined_when_speed_would_be_extreme(two_tone, tmp_path):
    """Çıpa için gereken hız sınırların dışındaysa UYGULAMA (None) — görüntü bozulmasın."""
    out = tmp_path / "fitted3.mp4"
    # 6 saniyelik ilk parçayı 0.5 saniyeye sıkıştırmak = 12× hızlanma → reddedilmeli
    res = fit_clip_with_anchor(two_tone, target_s=12.0, anchor_src_s=6.0,
                               anchor_dst_s=0.5, ffmpeg_path="ffmpeg", out_path=out)
    assert res is None


def test_anchor_never_trims_clip_head(tmp_path):
    """Dönüm çok GEÇSE bile klibin BAŞINI KIRPMA — çıpadan vazgeç (None).

    GERÇEK HATA (short 1140, kullanıcı: 'görüntü ses ve senaryoda uyumsuzluk'):
    klip 54.5s, dönüm 33.3s, ödül cümlesi 15.5s → çıpa hız sınırına sığsın diye
    kurulumun ilk 5.4 saniyesi KIRPILDI. Kırpılan o bölüm, anlatımın 1. cümlesinin
    anlattığı açılış anıydı (gelin tekerlekli sandalyedeki damadı kucaklıyor) →
    izleyici 'gelin…' altyazısını okurken ekranda gelin YOKTU.

    KÖK: anlatım KIRPILMAMIŞ klipten yazılıyor, kırpma render'da sonradan yapılıyor
    ve anlatıma geri bildirilmiyor. Çıpa KOZMETİK (zamanlama), anlatım-görüntü
    sözleşmesi ise ÜRÜNÜN kendisi → çıpalı oturtma İÇERİK ATAMAZ.
    Klibi ödül anına göre yazdırmak artık anlatım tarafının işi (bkz.
    build_curated_prompt REVEAL-SENKRON kuralı)."""
    clip = tmp_path / "late_turn.mp4"
    if not _marked_opening_clip(clip, open_s=2, setup_s=10, payoff_s=6):
        pytest.skip("ffmpeg yok")

    out = tmp_path / "trimmed.mp4"
    # dönüm 12s → ödül 5s: sadece hızla 2.4× gerekir (sınır 1.8). Eskiden kurulumun
    # başından 3s kırpılıp çıpa uygulanıyordu; artık vazgeçilir.
    res = fit_clip_with_anchor(clip, target_s=12.0, anchor_src_s=12.0,
                               anchor_dst_s=5.0, ffmpeg_path="ffmpeg", out_path=out)
    assert res is None, "çıpa için klibin başı kırpıldı — açılış anı (anlatımın 1. cümlesi) yok edilir"


def test_anchor_keeps_opening_moment_when_applied(tmp_path):
    """Çıpa UYGULANDIĞINDA da klibin ilk karesi yerinde kalmalı (kırpma yok)."""
    clip = tmp_path / "keep_open.mp4"
    if not _marked_opening_clip(clip, open_s=2, setup_s=10, payoff_s=6):
        pytest.skip("ffmpeg yok")

    out = tmp_path / "kept.mp4"
    # dönüm 12s → ödül 7s: 1.71× gerekir, sınır içinde → çıpa uygulanır, kırpma gerekmez
    res = fit_clip_with_anchor(clip, target_s=14.0, anchor_src_s=12.0,
                               anchor_dst_s=7.0, ffmpeg_path="ffmpeg", out_path=out)
    assert res is not None, "sınır içindeki çıpa uygulanmalıydı"
    assert _is_red(_rgb_at(res, 0.2, tmp_path)), \
        "klibin AÇILIŞ anı kırpılmış — anlatımın 1. cümlesi ekranda karşılığını bulamaz"
    assert _brightness_at(res, 8.0, tmp_path) > 195, "çıpadan sonra ödül sahnesi olmalı"


def test_anchor_trims_tail_when_clip_runs_long_after_turn(tmp_path):
    """Dönümden SONRASI hedeften uzunsa kuyruğu kırp — ödül sonrası fazlalık harcanabilir."""
    clip = tmp_path / "long_tail.mp4"
    if not _two_tone_clip(clip, first_s=5, second_s=25):
        pytest.skip("ffmpeg yok")

    out = tmp_path / "tail.mp4"
    res = fit_clip_with_anchor(clip, target_s=14.0, anchor_src_s=5.0,
                               anchor_dst_s=5.0, ffmpeg_path="ffmpeg", out_path=out)
    assert res is not None, "kuyruk kırpılarak ulaşılabilir çıpa reddedildi"
    assert abs(_clip_duration_s(res, "ffmpeg") - 14.0) < 0.6
    assert _brightness_at(res, 6.5, tmp_path) > 195, "çıpadan sonra ikinci sahne olmalı"


def test_anchor_declines_when_setup_would_be_gutted(tmp_path):
    """Kurulumun YARISINDAN fazlasını kırpmak gerekiyorsa VAZGEÇ — izleyici olayı kaçırır."""
    clip = tmp_path / "very_late.mp4"
    if not _two_tone_clip(clip, first_s=20, second_s=6):
        pytest.skip("ffmpeg yok")

    out = tmp_path / "gutted.mp4"
    # 20sn kurulumu 2sn'ye sığdırmak: hız sınırıyla en çok 3.6sn kaynak alınabilir →
    # %82 kırpma gerekir → reddedilmeli.
    assert fit_clip_with_anchor(clip, target_s=12.0, anchor_src_s=20.0,
                                anchor_dst_s=2.0, ffmpeg_path="ffmpeg",
                                out_path=out) is None


def test_detect_reveal_anchor_maps_frame_to_fraction(two_tone, tmp_path, monkeypatch):
    """Vision 'dönüm 5. karede başlıyor' derse → klibin ~%50'si (9 karede kare ortası)."""
    import short_bot.claude_cli as cli
    from short_bot.curated_clean import RevealAnchor, detect_reveal_anchor

    monkeypatch.setattr(cli, "run_json",
                        lambda *a, **k: RevealAnchor(has_turn=True, turn_frame=5))

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    frac = detect_reveal_anchor(two_tone, vision_call=_V(), ffmpeg_path="ffmpeg")
    assert frac is not None and abs(frac - 0.5) < 0.06


def test_detect_reveal_anchor_none_when_no_turn(two_tone, tmp_path, monkeypatch):
    """Dönüm yoksa None → çıpa uygulanmaz, mevcut davranış korunur."""
    import short_bot.claude_cli as cli
    from short_bot.curated_clean import RevealAnchor, detect_reveal_anchor

    monkeypatch.setattr(cli, "run_json",
                        lambda *a, **k: RevealAnchor(has_turn=False, turn_frame=0))

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    assert detect_reveal_anchor(two_tone, vision_call=_V(), ffmpeg_path="ffmpeg") is None


def test_detect_reveal_anchor_rejects_edge_frames(two_tone, tmp_path, monkeypatch):
    """İLK karede 'dönüm' olmaz (kurulum yok demektir) → None; çıpa zorlanmasın."""
    import short_bot.claude_cli as cli
    from short_bot.curated_clean import RevealAnchor, detect_reveal_anchor

    monkeypatch.setattr(cli, "run_json",
                        lambda *a, **k: RevealAnchor(has_turn=True, turn_frame=1))

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    assert detect_reveal_anchor(two_tone, vision_call=_V(), ffmpeg_path="ffmpeg") is None


def test_anchor_declined_when_anchor_outside_clip(two_tone, tmp_path):
    """Çıpa klibin dışındaysa/uçtaysa sessizce None."""
    out = tmp_path / "fitted4.mp4"
    assert fit_clip_with_anchor(two_tone, target_s=12.0, anchor_src_s=0.0,
                                anchor_dst_s=3.0, ffmpeg_path="ffmpeg",
                                out_path=out) is None
    assert fit_clip_with_anchor(two_tone, target_s=12.0, anchor_src_s=99.0,
                                anchor_dst_s=3.0, ffmpeg_path="ffmpeg",
                                out_path=out) is None


def test_curated_reveal_pause_closes_anchor_gap():
    """SES TARAFI HİZALAMA: ödül cümlesinden önceki duraklama, çıpayı hız sınırına
    SOKACAK kadar uzatılır.

    GERÇEK KOŞU (short 1145): klipte dönüm 33.3s, sesteki ödül anı 17.8s → çıpa için
    33.3/1.8 = 18.5s gerekiyordu, yani 0.73sn eksikti. Sabit 0.45sn duraklama bunu
    kapatmadı ve çıpa 'hız sınırı dışında' diye düştü — ödül ~2.4sn kaydı.

    Duraklamanın TEK BAŞINA farkı kapatamayacağını unutma: eklenen her saniye videoyu
    da uzattığı için dönüm anı da öteleniyor (net kazanç yalnız 1-reveal_frac kadar).
    Bu yüzden hedef 'farkı kapatmak' değil, çıpayı UYGULANABİLİR kılmak; tam hizayı
    çıpa kurar."""
    from short_bot.reel import curated_reveal_pause_s

    p = curated_reveal_pause_s(clip_reveal_s=33.26, reveal_dst_s=17.75,
                               base_s=0.45, max_s=1.5)
    assert abs(p - 0.73) < 0.05, f"çıpayı sınıra sokan duraklama hesaplanmadı: {p}"

    # ses zaten yeterince geç → taban duraklama (dramatik nefes) korunur
    assert curated_reveal_pause_s(clip_reveal_s=20.0, reveal_dst_s=15.0,
                                  base_s=0.45, max_s=1.5) == 0.45
    # fark çok büyük → tavan; izleyiciyi kaçıracak sessizlik yok (çıpa yine düşer,
    # klip kırpılmadan tek katsayıyla oynar)
    assert curated_reveal_pause_s(clip_reveal_s=60.0, reveal_dst_s=5.0,
                                  base_s=0.45, max_s=1.5) == 1.5
