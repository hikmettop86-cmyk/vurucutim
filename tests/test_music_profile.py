"""Müzik dengesi ARTIK KULLANICIYA BIRAKILMIYOR: ölçülüp yerleştiriliyor.

İKİ GERÇEK HATA:

1. Her parçayı 0:00'dan başlatıyorduk. Stok müziklerin çoğu yavaş kuruluyor —
   ölçüldü, 571.mp3 tam gücüne 60 SANİYEDE ulaşıyor (0sn: -55.7 dB → 60sn: -12.4).
   30 saniyelik bir shorts yalnız o sessiz girişi kullanıyor: gerçek videoda müzik
   konuşmanın 37 dB ALTINDA kaldı, yani hiç duyulmadı.

2. Seviye `music_volume` ÇARPANIYLA kanal başına elle tutturuluyordu. Ama doğru
   çarpan parçaya göre değişir — kütüphanede 24.9 dB yayılım var. Aynı ayar bir
   videoda müziği yok ediyor, ötekinde bağırtıyor; kullanıcının bunu bilmesi imkânsız.

Artık anlatımın seviyesi de ölçülüyor ve müzik ONA GÖRE yerleştiriliyor (kapalı
döngü). Kanal ayarı yalnız SINIRLI bir dokunuş — dengeyi bozamaz.
"""
import json
from pathlib import Path

import pytest

from short_bot.music_profile import (INTRO_TOL_LU, MAX_INTRO_SKIP_S, MAX_TRIM_DB,
                                     MUSIC_UNDER_SPEECH_DB, NEUTRAL_MUSIC_VOLUME,
                                     MusicProfile, loudness_curve, music_gain_db,
                                     profile_from_curve, profile_music, speech_lufs)


def _curve(vals):
    return [(i * 0.1, v) for i, v in enumerate(vals)]


# ——— sessiz girişi atla ———

def test_sessiz_giris_atlanir():
    p = profile_from_curve(_curve([-50] * 50 + [-16] * 200))
    assert p.start_s == pytest.approx(5.0, abs=0.2)


def test_dolu_baslayan_parca_atlanmaz():
    assert profile_from_curve(_curve([-16] * 300)).start_s == 0.0


def test_giris_atlama_sinirli():
    # Sonsuza kadar kurulan parçada müzik hiç başlamaz — üst sınır şart.
    c = _curve([-60] * 900 + [-14] * 100)
    assert profile_from_curve(c).start_s <= MAX_INTRO_SKIP_S


def test_seviye_KULLANILAN_bolumden_olculur():
    """Parçanın BÜTÜNÜNE bakmak yanıltır.

    30sn sessiz giriş + 15sn gövde: bütünün medyanı -50 (giriş çoğunlukta) →
    bütüne göre normalize etmek saçma bir kazanç verirdi. Video girişi ATLADIĞI
    için yalnız -24'lük gövdeyi duyar.
    """
    p = profile_from_curve(_curve([-50] * 300 + [-24] * 150))
    assert p.start_s == pytest.approx(30.0, abs=0.3)
    assert p.lufs == pytest.approx(-24, abs=1.0)


def test_bos_egri_uretimi_dusurmez():
    assert profile_from_curve([]).start_s == 0.0


def test_esik_makul():
    assert 3.0 <= INTRO_TOL_LU <= 9.0


# ——— kapalı döngü: müzik anlatıma göre yerleşir ———

def test_muzik_konusmanin_sabit_altina_oturur():
    p = MusicProfile(start_s=0.0, lufs=-24.0)
    g = music_gain_db(p, speech=-16.0, music_volume=NEUTRAL_MUSIC_VOLUME)
    # -24 + g = -16 + MUSIC_UNDER_SPEECH_DB
    assert -24.0 + g == pytest.approx(-16.0 + MUSIC_UNDER_SPEECH_DB, abs=0.1)


def test_kisik_ve_gur_parca_AYNI_yere_oturur():
    """Asıl mesele bu: parça ne olursa olsun sonuç aynı."""
    kisik = music_gain_db(MusicProfile(0.0, -30.0), -16.0)
    gur = music_gain_db(MusicProfile(0.0, -6.0), -16.0)
    assert -30.0 + kisik == pytest.approx(-6.0 + gur, abs=0.1)
    assert kisik > 0 > gur            # biri yükseltilir, öteki kısılır


def test_gur_anlatimda_muzik_da_yukselir():
    sessiz = music_gain_db(MusicProfile(0.0, -20.0), speech=-20.0)
    gur = music_gain_db(MusicProfile(0.0, -20.0), speech=-12.0)
    assert gur - sessiz == pytest.approx(8.0, abs=0.1)


def test_anlatim_olculemezse_yine_de_esitlenir():
    # Ölçüm patlarsa müzik hedefe normalize edilir: parçalar arası yayılım kapanır.
    a = music_gain_db(MusicProfile(0.0, -30.0), speech=None)
    b = music_gain_db(MusicProfile(0.0, -6.0), speech=None)
    assert -30.0 + a == pytest.approx(-6.0 + b, abs=0.1)


# ——— kanal ayarı dengeyi BOZAMAZ ———

def test_kanal_ayari_yalnizca_dokunus():
    p = MusicProfile(0.0, -20.0)
    notr = music_gain_db(p, -16.0, NEUTRAL_MUSIC_VOLUME)
    kisik = music_gain_db(p, -16.0, 0.10)
    assert kisik < notr
    assert notr - kisik <= MAX_TRIM_DB + 0.01, "eski ayar dengeyi yıkmamalı"


def test_eski_kanal_ayari_muzigi_yok_edemez():
    # 0.10 çarpanı ham hâlde -9.5 dB'ydi; kırpma onu MAX_TRIM_DB ile sınırlıyor.
    p = MusicProfile(0.0, -20.0)
    g = music_gain_db(p, -16.0, 0.10)
    sonuc = -20.0 + g              # müziğin oturduğu seviye
    assert sonuc >= -16.0 + MUSIC_UNDER_SPEECH_DB - MAX_TRIM_DB - 0.01


def test_notr_ayarda_dokunus_yok():
    p = MusicProfile(0.0, -20.0)
    assert music_gain_db(p, -16.0, NEUTRAL_MUSIC_VOLUME) == \
           music_gain_db(p, -16.0, NEUTRAL_MUSIC_VOLUME)
    # nötr değer hiçbir kayma getirmemeli
    ham = (-16.0 + MUSIC_UNDER_SPEECH_DB) - (-20.0)
    assert music_gain_db(p, -16.0, NEUTRAL_MUSIC_VOLUME) == pytest.approx(ham, abs=0.02)


# ——— gerçek ffmpeg + gerçek kütüphane ———

_MUS = sorted(Path("assets/music").rglob("*.mp3"))


@pytest.mark.skipif(not _MUS, reason="müzik kütüphanesi yok")
def test_gercek_parcanin_egrisi_okunuyor():
    c = loudness_curve(_MUS[0])
    assert len(c) > 20, "ebur128 eğrisi okunamadı"
    assert all(v <= 5 for _, v in c)
    assert max(v for _, v in c) > -40


@pytest.mark.skipif(not _MUS, reason="müzik kütüphanesi yok")
def test_konusma_seviyesi_olculuyor(tmp_path):
    import subprocess
    nar = tmp_path / "n.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=200:duration=6", "-af", "volume=0.5",
                    "-c:a", "libmp3lame", str(nar)], capture_output=True, check=True)
    v = speech_lufs(nar)
    assert v is not None and -40 < v < 0


@pytest.mark.skipif(not _MUS, reason="müzik kütüphanesi yok")
def test_onbellek_calisiyor(tmp_path):
    cache = tmp_path / "m.json"
    a = profile_music(_MUS[0], cache_path=cache)
    assert cache.exists() and len(json.loads(cache.read_text(encoding="utf-8"))) == 1
    assert profile_music(_MUS[0], cache_path=cache) == a


@pytest.mark.skipif(not _MUS, reason="müzik kütüphanesi yok")
def test_onbellek_bozuksa_uretim_dusmez(tmp_path):
    cache = tmp_path / "m.json"
    cache.write_text("{bozuk", encoding="utf-8")
    assert isinstance(profile_music(_MUS[0], cache_path=cache), MusicProfile)
