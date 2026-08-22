"""Ses miksi: müzik konuşma ALTINDA kısılır, BOŞLUKLARDA yükselir + master normalize.

Şu anki miks: müzik sabit 0.10'da gömülü, anlatım 1.0. Müzik hiçbir zaman enerji
taşımıyor — sadece "orada". Ducking olmadan müziği yükseltmek de mümkün değil,
çünkü konuşmayı boğar → izleyici kelime ayıklamak için çaba harcar → sürtünme →
kaydırma.

Ducking (sidechain) ile: müzik boşluklarda GERÇEKTEN duyulur, konuşma başlayınca
otomatik çekilir. Kısa formatta enerjiyi taşıyan şey budur.
"""
import subprocess
from pathlib import Path

import pytest

from short_bot import reel_assembler
from short_bot.reel_assembler import assemble_reel


def _has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def _graph(tmp_path, monkeypatch, **over):
    """assemble_reel'i çalıştırmadan filtre grafiğini yakala."""
    clips = [tmp_path / "c0.mp4"]; clips[0].write_bytes(b"x")
    music = tmp_path / "m.mp3"; music.write_bytes(b"m")
    narration = Path(__file__).parent / "fixtures" / "music_sample_2s.mp3"
    cmds = []
    monkeypatch.setattr(reel_assembler, "_run",
                        lambda cmd: (cmds.append(list(cmd)),
                                     subprocess.CompletedProcess(cmd, 0, "", ""))[1])
    kw = dict(clip_paths=clips, seg_spans=[(0.0, 2.0)], frames_dir=tmp_path / "f",
              narration_path=narration, music_path=music,
              out_path=tmp_path / "out.mp4", cut_times=[], duration_s=2.0, zoom=False)
    kw.update(over)
    assemble_reel(**kw)
    final = next(c for c in cmds if "-filter_complex" in c)
    return final[final.index("-filter_complex") + 1]


def test_music_is_ducked_under_the_narration(tmp_path, monkeypatch):
    """Müzik, ANLATIMI yan-zincir alan bir kompresörden geçmeli."""
    fc = _graph(tmp_path, monkeypatch)
    assert "sidechaincompress" in fc, "ducking yok — müzik sabit seviyede gömülü"
    # yan zincir ANLATIM olmalı (müziğin kendisi değil)
    assert "asplit" in fc, "anlatım hem mikse hem yan-zincire dallanmalı"


def test_master_iki_gecisli_sabit_kazanc(tmp_path, monkeypatch):
    """Master DİNAMİK loudnorm ile DEĞİL, ölçüp sabit kazançla yapılmalı.

    GERÇEK HATA: loudnorm'un tek-geçiş dinamik modu NaN/Inf örnek üretiyor, AAC
    kodlayıcı o kareleri REDDEDİYOR ve ffmpeg onları SESSİZCE DÜŞÜRÜP çıkış kodu 0
    veriyor. Ölçüldü: iki üretilmiş videoda 310 ve 158 ses karesi (6.6sn / 3.4sn)
    düşmüştü — ses ortadan atlıyor ve sonda kesiliyordu. alimiter kurtarmıyor:
    limiter NaN'ı kırpmaz, geçirir. Sabit kazanç NaN ÜRETEMEZ.
    """
    fc = _graph(tmp_path, monkeypatch)
    assert "loudnorm" not in fc, "dinamik loudnorm ses karesi düşürüyor"
    assert "amix" in fc


def test_ducking_can_be_disabled(tmp_path, monkeypatch):
    """Kanal ayarı ducking'i kapatabilmeli (eski davranış)."""
    fc = _graph(tmp_path, monkeypatch, music_duck=False)
    assert "sidechaincompress" not in fc


def test_no_music_means_no_sidechain(tmp_path, monkeypatch):
    """Müzik yoksa ducking grafiği hiç kurulmamalı (bozuk filtre grafiği olmasın)."""
    fc = _graph(tmp_path, monkeypatch, music_path=None)
    assert "sidechaincompress" not in fc
    assert "amix" in fc


def test_ducked_music_is_padded_so_it_never_dies_at_the_end(tmp_path, monkeypatch):
    """sidechaincompress çıkışı girişten ~0.3sn KISA (iç gecikme).

    Pad olmazsa videonun SONUNDA müzik kesilir — ve sonda susan müzik LOOP'U BOZAR:
    izleyici videonun bittiğini DUYAR ve başa dönmez. Oysa her tekrar oynatma ayrı
    bir izlenme sayılıyor ve faceless format loop'ta yapısal olarak avantajlı.
    """
    fc = _graph(tmp_path, monkeypatch)
    assert "sidechaincompress" in fc
    sc = fc.split("sidechaincompress")[1].split("[bgm]")[0]
    assert "apad" in sc, "ducked müzik pad'lenmemiş → sonda susar → loop ölür"


def _sfx_volumes(fc: str) -> list[float]:
    """Filtre grafiğindeki kesim-SFX seviyelerini oku ([wh0], [wh1], ...)."""
    out = []
    for parca in fc.split(";"):
        if "[wh" in parca and "volume=" in parca:
            out.append(float(parca.split("volume=")[1].split("[")[0]))
    return out


def test_kesinti_sfx_i_yuksek_otekiler_kisik_calinir(tmp_path, monkeypatch):
    """KONTRAST montajda GERÇEKTEN uygulanmalı — yoksa kesinti anı sıradanlaşır.

    Orkestratör kazançları hesaplasa da montaj onları filtre grafiğine yazmazsa
    hiçbir şey değişmez. Ölçtüğümüz şey grafiğin kendisi.
    """
    from short_bot.reel_interrupt import LOUD_SFX_GAIN, QUIET_SFX_GAIN
    sfx = tmp_path / "s.mp3"; sfx.write_bytes(b"s")
    fc = _graph(tmp_path, monkeypatch, cut_times=[0.5, 1.0, 1.5],
                sfx_at_cut=[sfx, sfx, sfx], sfx_volume=0.2,
                sfx_gains=[QUIET_SFX_GAIN, LOUD_SFX_GAIN, QUIET_SFX_GAIN])
    vols = _sfx_volumes(fc)
    assert len(vols) == 3, f"3 kesim SFX'i bekleniyordu, {len(vols)} bulundu"
    assert vols[1] > vols[0] and vols[1] > vols[2], "kesinti komşularından yüksek değil"
    assert vols[1] / vols[0] == pytest.approx(LOUD_SFX_GAIN / QUIET_SFX_GAIN, rel=1e-3)
    assert vols[0] == pytest.approx(0.2 * QUIET_SFX_GAIN, rel=1e-3)


def test_kazanc_verilmezse_eski_seviye_aynen_kalir(tmp_path, monkeypatch):
    """Geriye uyum: sfx_gains yoksa seviye tam olarak sfx_volume olmalı."""
    sfx = tmp_path / "s.mp3"; sfx.write_bytes(b"s")
    fc = _graph(tmp_path, monkeypatch, cut_times=[0.5], sfx_at_cut=[sfx],
                sfx_volume=0.22)
    assert _sfx_volumes(fc) == [pytest.approx(0.22)]


def test_sting_t_sifirda_calar(tmp_path, monkeypatch):
    """AÇILIŞ SES İMZASI: gecikmesiz, yani t=0'da — kare sıfırın sesi odur.

    adelay VERİLMEZ: sting videonun ilk karesinde başlamalı. Gecikirse imza,
    imza olmaktan çıkıp sıradan bir efekte döner.
    """
    st = tmp_path / "sting.mp3"; st.write_bytes(b"s")
    fc = _graph(tmp_path, monkeypatch, sting=st, sting_volume=0.4)
    assert "[sting]" in fc, "sting miks grafiğine hiç girmedi"
    parca = next(p for p in fc.split(";") if "[sting]" in p and "volume=" in p)
    assert "adelay" not in parca, "sting geciktirilmiş → kare sıfırda duyulmaz"
    assert "volume=0.4" in parca


def test_sting_yoksa_grafik_kirilmaz(tmp_path, monkeypatch):
    fc = _graph(tmp_path, monkeypatch, sting=None)
    assert "[sting]" not in fc
    assert "amix" in fc


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg yok")
def test_duck_really_lowers_music_under_speech(tmp_path):
    """GERÇEK ffmpeg: müzik, konuşma anında konuşma BOŞLUĞUNDAKİNDEN sessiz olmalı.

    Sentetik ses: anlatım = 0-1sn sessiz, 1-2sn ton. Müzik = sürekli ton.
    Ducking çalışıyorsa müzik 1-2sn aralığında belirgin şekilde kısılır.
    """
    nar = tmp_path / "nar.wav"
    mus = tmp_path / "mus.wav"
    # anlatım: 1sn sessizlik + 1sn ton
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=300:duration=2",
                    "-af", "volume=enable='lt(t,1)':volume=0", str(nar)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=900:duration=2", str(mus)], check=True)

    out = tmp_path / "mix.wav"      # SADECE ducked müzik (anlatım mikse girmez ki
    from short_bot.reel_assembler import (DUCK_ATTACK_MS, DUCK_RATIO,
                                          DUCK_RELEASE_MS, DUCK_THRESHOLD)
    subprocess.run([                # ölçüm müziği izole görsün)
        "ffmpeg", "-y", "-v", "error", "-i", str(mus), "-i", str(nar),
        "-filter_complex",
        f"[0:a][1:a]sidechaincompress=threshold={DUCK_THRESHOLD:g}:"
        f"ratio={DUCK_RATIO:g}:attack={DUCK_ATTACK_MS:g}:release={DUCK_RELEASE_MS:g},"
        f"apad[bgm]",
        "-map", "[bgm]", "-t", "2", str(out)], check=True)

    def rms(t0, t1):
        # -v error KULLANMA: volumedetect çıktısını da bastırır.
        # -t (süre), -to (mutlak an) yerine: bazı ffmpeg sürümlerinde -ss ile
        # birleşince -to boş aralık verip ölçümü sessizce düşürüyor.
        r = subprocess.run(["ffmpeg", "-ss", str(t0), "-t", str(t1 - t0),
                            "-i", str(out), "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True)
        for line in r.stderr.splitlines():
            if "mean_volume:" in line:
                return float(line.split("mean_volume:")[1].split()[0])
        raise AssertionError(f"seviye okunamadı (rc={r.returncode}):\n"
                             f"{r.stderr[-400:]}")

    gap = rms(0.1, 0.9)      # konuşma YOK → müzik açık
    speech = rms(1.2, 1.9)   # konuşma VAR → müzik kısılmalı
    # Ölçülen hedef ~11 dB. 8 dB'nin altına düşerse müzik konuşmayı boğmaya başlar.
    assert gap - speech > 8.0, (
        f"ducking yetersiz: boşlukta {gap:.1f} dB, konuşmada {speech:.1f} dB "
        f"(fark {gap - speech:.1f} dB, en az 8 dB bekleniyor)")
