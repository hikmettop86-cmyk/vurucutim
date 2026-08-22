"""Tempo bölgeleri: hook hızlansın, tepe yavaşlasın, altyazı sesle KALSIN.

Bu dosyadaki kritik test ``test_gercek_ses_bolge_bolge_yeniden_hizlaniyor``:
ffmpeg'i GERÇEKTEN koşturup çıkan sesin süresini ÖLÇER. Saf fonksiyonların doğru
olması yetmez — atempo/concat zincirinin gerçekten çalıştığını görmeliyiz.
"""
import shutil
import subprocess
from dataclasses import dataclass

import pytest

from short_bot.reel_tempo import (BODY_TEMPO, HOOK_TEMPO, MIN_ZONE_S, PEAK_TEMPO,
                                  Zone, map_time, plan_zones, remap_words, retime,
                                  retimed_duration_s)


@dataclass(frozen=True)
class _W:      # TimedWord ikizi (replace() ile taşınabilmeli → dataclass şart)
    word: str
    start_s: float
    end_s: float
    seg: int


# hook 0-4, beat0 4-12, beat1(TEPE) 12-22, beat2 22-30, close 30-36
_SPANS = [(0.0, 4.0), (4.0, 12.0), (12.0, 22.0), (22.0, 30.0), (30.0, 36.0)]


def test_dort_bolge_kuruluyor_hook_hizli_tepe_yavas():
    z = plan_zones(_SPANS, peak_seg=2, duration_s=36.0)
    assert [round(x.start_s, 1) for x in z] == [0.0, 4.0, 12.0, 22.0]
    assert [round(x.end_s, 1) for x in z] == [4.0, 12.0, 22.0, 36.0]
    assert [x.tempo for x in z] == [HOOK_TEMPO, BODY_TEMPO, PEAK_TEMPO, BODY_TEMPO]
    assert z[0].tempo > 1.0 > z[2].tempo, "hook hızlanmalı, tepe yavaşlamalı"


def test_yavaslama_TEPEDEN_SONRASINA_TASMAZ():
    """Kapanış çevik kalmalı: sürüklenen bir close, loop callback'ini öldürür.

    İlk kurulumda yavaş bölge tepeden videonun SONUNA kadar uzuyordu — ölçüm
    videoyu 1.5sn uzattığını ve kapanışı da yavaşlattığını gösterdi.
    """
    z = plan_zones(_SPANS, peak_seg=2, duration_s=36.0)
    yavas = [x for x in z if x.tempo < 1.0]
    assert len(yavas) == 1
    assert (yavas[0].start_s, yavas[0].end_s) == _SPANS[2], "yavaşlama = TAM tepe segmenti"
    assert z[-1].tempo == BODY_TEMPO, "tepeden sonrası normal tempoya dönmeli"


def test_bolgeler_sesi_KESINTISIZ_kapliyor():
    """Bölgeler [0, süre] aralığını boşluksuz kaplamalı — yoksa concat ses YER."""
    z = plan_zones(_SPANS, peak_seg=2, duration_s=36.0)
    assert z[0].start_s == 0.0
    assert z[-1].end_s == 36.0
    for a, b in zip(z, z[1:]):
        assert a.end_s == b.start_s, "bölgeler arasında boşluk var → ses kaybı"


def test_kisa_bolge_varsa_hic_bolge_kurulmaz():
    """Kısa dilimde atempo geçişi 'kayma' gibi duyulur — kazanç riski karşılamaz."""
    dar = [(0.0, 0.4), (0.4, 8.0), (8.0, 16.0), (16.0, 24.0), (24.0, 30.0)]
    assert plan_zones(dar, peak_seg=2, duration_s=30.0) == []
    # tepe hemen hook'un ardındaysa gövde bölgesi yok olur
    bitisik = [(0.0, 4.0), (4.0, 4.5), (4.5, 20.0), (20.0, 26.0), (26.0, 30.0)]
    assert plan_zones(bitisik, peak_seg=2, duration_s=30.0) == []


def test_gecersiz_tepe_bolge_kurmaz():
    assert plan_zones(_SPANS, peak_seg=0, duration_s=36.0) == []
    assert plan_zones(_SPANS, peak_seg=99, duration_s=36.0) == []
    assert plan_zones([], peak_seg=1, duration_s=36.0) == []
    # tepe SON segmentse ardından bölge kalmaz
    assert plan_zones(_SPANS, peak_seg=4, duration_s=36.0) == []


def test_yeni_sure_bolgelerin_toplami():
    z = plan_zones(_SPANS, peak_seg=2, duration_s=36.0)
    beklenen = (4.0 / HOOK_TEMPO + 8.0 / BODY_TEMPO
                + 10.0 / PEAK_TEMPO + 14.0 / BODY_TEMPO)
    assert retimed_duration_s(z) == pytest.approx(beklenen, abs=1e-9)
    # Yavaşlama yalnız tepe segmentine uygulandığı için süre 1 saniyeden az oynamalı
    # (kelime bütçesi, 45sn tavanı ve tepe-yüzdesi hesapları bozulmasın).
    assert abs(retimed_duration_s(z) - 36.0) < 1.0


def test_zaman_eslemesi_kesin_ve_artan():
    z = plan_zones(_SPANS, peak_seg=2, duration_s=36.0)
    assert map_time(0.0, z) == pytest.approx(0.0)
    assert map_time(4.0, z) == pytest.approx(4.0 / HOOK_TEMPO)
    assert map_time(12.0, z) == pytest.approx(4.0 / HOOK_TEMPO + 8.0)
    assert map_time(36.0, z) == pytest.approx(retimed_duration_s(z))
    # kesin ARTAN olmalı: altyazı zamanları asla geri gitmemeli
    onceki = -1.0
    for i in range(0, 361):
        t = map_time(i / 10, z)
        assert t >= onceki, f"{i / 10}s'de zaman geri gitti"
        onceki = t


def test_hook_kelimeleri_one_ceker_tepe_kelimeleri_yayilir():
    z = plan_zones(_SPANS, peak_seg=2, duration_s=36.0)
    w = [_W("hook_son", 3.5, 4.0, 0), _W("tepe_ilk", 12.0, 12.5, 2)]
    yeni = remap_words(w, z)
    assert yeni[0].start_s < 3.5, "hook kelimesi öne çekilmeli (hızlandı)"
    # tepe kelimesinin SÜRESİ uzamalı (yavaşladı) — başlangıcı hook'un kısalmasıyla öne kayar
    assert (yeni[1].end_s - yeni[1].start_s) > 0.5
    assert (yeni[0].end_s - yeni[0].start_s) < 0.5
    assert all(a.word == b.word and a.seg == b.seg for a, b in zip(w, yeni))


def test_bolge_yoksa_kelimeler_degismez():
    w = [_W("a", 1.0, 1.5, 0)]
    assert remap_words(w, []) == w
    assert map_time(7.0, []) == 7.0


# --- GERÇEK FFMPEG ÖLÇÜMÜ --------------------------------------------------

def _ffmpeg_var() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _sure(p) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(r.stdout.strip())


@pytest.mark.skipif(not _ffmpeg_var(), reason="ffmpeg/ffprobe yok")
def test_gercek_ses_bolge_bolge_yeniden_hizlaniyor(tmp_path):
    """ffmpeg'i GERÇEKTEN koştur: çıkan sesin süresi hesabı tutmalı.

    Saf fonksiyonların doğruluğu yetmez — atempo+concat zinciri sessizce
    çökebilir ya da bölgeleri yiyebilir. Ölçüyoruz.
    """
    src = tmp_path / "ses.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=f=440:d=36",
                    "-c:a", "libmp3lame", "-q:a", "2", str(src)],
                   capture_output=True, check=True)
    assert _sure(src) == pytest.approx(36.0, abs=0.2)

    zones = plan_zones(_SPANS, peak_seg=2, duration_s=36.0)
    out = retime(src, tmp_path / "tempo.mp3", zones)

    beklenen = retimed_duration_s(zones)
    olculen = _sure(out)
    # mp3 çerçeve kuantizasyonu ~0.03sn oynatır (4 bölge → 4 birleşme noktası);
    # 0.2sn tolerans bol bol yeter ve bir bölgenin (en kısası 4sn) düşmesini yakalar.
    assert olculen == pytest.approx(beklenen, abs=0.2), (
        f"beklenen {beklenen:.2f}sn, ölçülen {olculen:.2f}sn — bir bölge kayıp olabilir")


@pytest.mark.skipif(not _ffmpeg_var(), reason="ffmpeg/ffprobe yok")
def test_bolge_siniri_sesin_hicbir_parcasini_dusurmuyor(tmp_path):
    """Tempo=1.0'lık üç bölge, sesi BİREBİR yeniden kurmalı (kayıp yok)."""
    src = tmp_path / "ses.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=f=440:d=20",
                    "-c:a", "libmp3lame", "-q:a", "2", str(src)],
                   capture_output=True, check=True)
    notr = [Zone(0.0, 5.0, 1.0), Zone(5.0, 12.0, 1.0), Zone(12.0, 20.0, 1.0)]
    out = retime(src, tmp_path / "notr.mp3", notr)
    assert _sure(out) == pytest.approx(20.0, abs=0.15)


def test_min_zone_makul():
    assert 0.5 <= MIN_ZONE_S <= 2.0
