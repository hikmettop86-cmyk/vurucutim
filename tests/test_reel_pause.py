"""Tepe öncesi dramatik duraklama.

Anlatım baştan sona AYNI tempoda akıyordu. İnsan anlatıcı en büyük açıklamadan
hemen önce SUSAR — o sessizlik "şimdi bir şey gelecek" der. Kesintisiz ses vurguyu
düzleştirir: tepe, diğer cümlelerin arasında kaybolur.

Yeniden seslendirmek yerine mp3'e sessizlik enjekte ediliyor. Kritik nokta SENKRON:
saf sessizlik konuşmanın hiçbir yerini bozmaz, dolayısıyla öncesi yerinde kalır,
sonrası TAM OLARAK duraklama kadar kayar — bu kaydırma kesindir, tahmin değil.
"""
import subprocess

import pytest

from short_bot.audio_probe import probe_duration_s
from short_bot.reel_models import TimedWord
from short_bot.reel_pause import (MIN_PAUSE_AT_S, REVEAL_PAUSE_S, insert_pause,
                                  shift_words)


def _w(word, s, e):
    return TimedWord(word=word, start_s=s, end_s=e, seg=0)


def test_duraklamadan_onceki_kelimeler_yerinde_kalir():
    ws = [_w("a", 0.0, 0.5), _w("b", 1.0, 1.4), _w("c", 3.0, 3.4)]
    out = shift_words(ws, at_s=3.0, dur_s=0.45)
    assert out[0].start_s == 0.0 and out[1].start_s == 1.0


def test_duraklamadan_sonraki_kelimeler_tam_duraklama_kadar_kayar():
    ws = [_w("a", 0.0, 0.5), _w("c", 3.0, 3.4), _w("d", 4.0, 4.6)]
    out = shift_words(ws, at_s=3.0, dur_s=0.45)
    assert out[1].start_s == pytest.approx(3.45)
    assert out[1].end_s == pytest.approx(3.85)
    assert out[2].start_s == pytest.approx(4.45)


def test_kelime_sirasi_ve_sayisi_korunur():
    ws = [_w(f"w{i}", i * 1.0, i * 1.0 + 0.5) for i in range(6)]
    out = shift_words(ws, at_s=3.0, dur_s=0.45)
    assert [w.word for w in out] == [w.word for w in ws]
    assert all(a.start_s < a.end_s for a in out)
    assert all(out[i].start_s <= out[i + 1].start_s for i in range(len(out) - 1))


def test_duraklama_hookun_icine_dusmez():
    # Açılışta sessizlik izleyiciyi KAÇIRIR — eşik bunun için var.
    assert MIN_PAUSE_AT_S >= 1.5


def test_duraklama_suresi_makul():
    # Kısası fark edilmez, uzunu "ses kesildi mi?" dedirtir.
    assert 0.3 <= REVEAL_PAUSE_S <= 0.7


# ——— gerçek ffmpeg ———

def _ses(path, sn=4.0, sr=44100):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={sn}:sample_rate={sr}",
         "-c:a", "libmp3lame", "-q:a", "2", str(path)],
        capture_output=True, check=True)


def test_sessizlik_gercekten_ekleniyor(tmp_path):
    src, out = tmp_path / "a.mp3", tmp_path / "b.mp3"
    _ses(src, 4.0)
    once = probe_duration_s(src)
    insert_pause(src, out, at_s=2.0, dur_s=0.45)
    sonra = probe_duration_s(out)
    assert sonra - once == pytest.approx(0.45, abs=0.08), f"{once:.2f} → {sonra:.2f}"


def test_sessizlik_DOGRU_ANA_ekleniyor(tmp_path):
    """Sessizlik 2.0sn'de olmalı — başka bir yerde değil.

    Ölçüm: kaynak sürekli bir ton. Çıktıda 2.0-2.45 arası SESSİZ, dışı DOLU olmalı.
    """
    src, out = tmp_path / "a.mp3", tmp_path / "b.mp3"
    _ses(src, 4.0)
    insert_pause(src, out, at_s=2.0, dur_s=0.45)

    def rms(t0, t1):
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-ss", f"{t0}", "-t", f"{t1 - t0}",
             "-i", str(out), "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True)
        for ln in p.stderr.splitlines():
            if "mean_volume:" in ln:
                return float(ln.split("mean_volume:")[1].split("dB")[0])
        raise AssertionError(p.stderr[-300:])

    onces = rms(1.2, 1.8)      # duraklamadan önce → ton var
    bosluk = rms(2.05, 2.40)   # duraklama → sessiz
    sonra = rms(2.7, 3.3)      # duraklamadan sonra → ton geri gelmiş
    assert bosluk < onces - 30, f"boşluk sessiz değil ({bosluk:.1f} dB)"
    assert sonra > bosluk + 30, f"duraklamadan sonra ses geri gelmemiş ({sonra:.1f} dB)"


def test_stereo_kaynakta_da_calisir(tmp_path):
    # Sessizliğin biçimi kaynakla BİREBİR uyuşmalı, yoksa concat girdileri
    # birleştiremez ve üretim düşer.
    src, out = tmp_path / "s.mp3", tmp_path / "o.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-ac", "2", "-c:a", "libmp3lame", "-q:a", "2", str(src)],
        capture_output=True, check=True)
    insert_pause(src, out, at_s=1.5, dur_s=0.45)
    assert probe_duration_s(out) == pytest.approx(3.45, abs=0.08)
