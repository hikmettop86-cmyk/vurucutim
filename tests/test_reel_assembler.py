import subprocess
from pathlib import Path

import pytest
from PIL import Image

import short_bot.reel_assembler as reel_assembler
from short_bot.reel_assembler import assemble_reel


def _clip(path, secs=3, color=(80, 120, 60)):
    """Küçük gerçek mp4 üret (renkli, sessiz)."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"color=c=0x{color[0]:02x}{color[1]:02x}{color[2]:02x}:s=640x360:d={secs}:r=30",
         "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, check=True)
    return path


def _frames(d, n):
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        img = Image.new("RGBA", (1080, 1920), (255, 255, 255, 0))
        img.save(d / f"f_{i:05d}.png")
    return d


def test_assemble_produces_video_with_audio(tmp_path):
    clips = [_clip(tmp_path / f"c{i}.mp4", color=(i*30, 100, 80)) for i in range(3)]
    spans = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]
    frames = _frames(tmp_path / "frames", 90)   # 3s @ 30fps
    music = Path(__file__).parent / "fixtures" / "music_sample_2s.mp3"
    narration = music
    out = tmp_path / "out.mp4"

    result = assemble_reel(
        clip_paths=clips, seg_spans=spans, frames_dir=frames,
        narration_path=narration, music_path=music, out_path=out,
        cut_times=[1.0, 2.0], duration_s=3.0, fps=30,
        music_volume=0.1, sfx_at_cut=None, zoom=True,
    )
    assert result == out and out.exists() and out.stat().st_size > 0

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "default=nw=1", str(out)],
        capture_output=True, text=True, check=True)
    assert "audio" in probe.stdout
    dur = float([l for l in probe.stdout.splitlines() if l.startswith("duration=")][0].split("=")[1])
    assert 2.7 <= dur <= 3.3


def test_assemble_missing_clip_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        assemble_reel(
            clip_paths=[tmp_path / "yok.mp4"], seg_spans=[(0.0, 1.0)],
            frames_dir=_frames(tmp_path / "f", 30),
            narration_path=Path(__file__).parent / "fixtures" / "music_sample_2s.mp3",
            music_path=None, out_path=tmp_path / "o.mp4",
            cut_times=[], duration_s=1.0)


def test_assemble_mixes_sfx_per_cut(tmp_path, monkeypatch):
    """sfx_at_cut'taki her SFX kesme anına adelay + AYARLANABİLİR volume ile mixlenir.

    Seviye eskiden SABİT 0.6'ydı (anlatım 1.0) → "sfx sesleri çok baskın".
    Artık ReelConfig.sfx_volume'dan gelir (varsayılan 0.22 = konuşmanın ~14 dB altı).
    """
    clips = []
    for i in range(3):
        c = tmp_path / f"c{i}.mp4"
        c.write_bytes(b"x")
        clips.append(c)
    narration = Path(__file__).parent / "fixtures" / "music_sample_2s.mp3"
    sfx_a = tmp_path / "a.mp3"; sfx_a.write_bytes(b"a")
    sfx_b = tmp_path / "b.mp3"; sfx_b.write_bytes(b"b")

    cmds = []

    def fake_run(cmd):
        cmds.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(reel_assembler, "_run", fake_run)

    assemble_reel(
        clip_paths=clips, seg_spans=[(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)],
        frames_dir=tmp_path / "frames", narration_path=narration,
        music_path=None, out_path=tmp_path / "out.mp4",
        cut_times=[1.0, 2.0], duration_s=3.0,
        sfx_at_cut=[sfx_a, sfx_b], zoom=False,
    )

    final = next(c for c in cmds if "-filter_complex" in c)
    # her SFX final montaj komutunda -i girdisi olarak yer alır
    assert str(sfx_a) in final and str(sfx_b) in final
    fc = final[final.index("-filter_complex") + 1]
    assert "adelay=1000|1000,volume=0.22" in fc     # varsayılan seviye
    assert "adelay=2000|2000,volume=0.22" in fc
    # SFX anlatımdan BELİRGİN alta gömülü olmalı (vurgu, yarış değil)
    assert "volume=1[nar]" in fc


def test_sfx_volume_is_configurable(tmp_path, monkeypatch):
    """Kanal ayarı seviyeyi ezebilmeli — kullanıcı kulakla ince ayar yapabilsin."""
    clips = [tmp_path / "c0.mp4"]; clips[0].write_bytes(b"x")
    narration = Path(__file__).parent / "fixtures" / "music_sample_2s.mp3"
    sfx = tmp_path / "s.mp3"; sfx.write_bytes(b"s")
    cmds = []
    monkeypatch.setattr(reel_assembler, "_run",
                        lambda cmd: (cmds.append(list(cmd)),
                                     subprocess.CompletedProcess(cmd, 0, "", ""))[1])
    assemble_reel(
        clip_paths=clips, seg_spans=[(0.0, 2.0)], frames_dir=tmp_path / "frames",
        narration_path=narration, music_path=None, out_path=tmp_path / "out.mp4",
        cut_times=[1.0], duration_s=2.0, sfx_at_cut=[sfx], zoom=False,
        sfx_volume=0.05,
    )
    final = next(c for c in cmds if "-filter_complex" in c)
    fc = final[final.index("-filter_complex") + 1]
    assert "volume=0.05" in fc and "volume=0.22" not in fc


def test_assemble_skips_none_sfx(tmp_path, monkeypatch):
    """sfx_at_cut'ta None olan kesme atlanır; diğer SFX yine mixlenir."""
    clips = []
    for i in range(3):
        c = tmp_path / f"c{i}.mp4"
        c.write_bytes(b"x")
        clips.append(c)
    narration = Path(__file__).parent / "fixtures" / "music_sample_2s.mp3"
    sfx_b = tmp_path / "b.mp3"; sfx_b.write_bytes(b"b")

    cmds = []

    def fake_run(cmd):
        cmds.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(reel_assembler, "_run", fake_run)

    assemble_reel(
        clip_paths=clips, seg_spans=[(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)],
        frames_dir=tmp_path / "frames", narration_path=narration,
        music_path=None, out_path=tmp_path / "out.mp4",
        cut_times=[1.0, 2.0], duration_s=3.0,
        sfx_at_cut=[None, sfx_b], zoom=False,
    )

    final = next(c for c in cmds if "-filter_complex" in c)
    fc = final[final.index("-filter_complex") + 1]
    assert str(sfx_b) in final
    assert "adelay=1000|1000" not in fc      # ilk kesme (None) atlandı
    assert "adelay=2000|2000,volume=0.22" in fc


def test_assemble_zoom_fallback_on_failure(tmp_path, monkeypatch):
    """zoompan patlarsa düz crop'a düşer, yine üretir."""
    clips = [_clip(tmp_path / "c0.mp4")]
    frames = _frames(tmp_path / "frames", 30)
    music = Path(__file__).parent / "fixtures" / "music_sample_2s.mp3"
    out = tmp_path / "out.mp4"
    result = assemble_reel(
        clip_paths=clips, seg_spans=[(0.0, 1.0)], frames_dir=frames,
        narration_path=music, music_path=None, out_path=out,
        cut_times=[], duration_s=1.0, zoom=True)
    assert out.exists()


def test_ses_butunluk_denetimi_dusen_kareleri_yakalar():
    """ffmpeg ses karesi düşürdüğünde ÇIKIŞ KODU 0 verir — bozulma sessizdir.

    Gerçek hata: üretilen iki videoda zaman damgaları 32sn'ye gidiyordu ama seste
    yalnız 25sn'lik örnek vardı. Ses ortadan atlıyor, sonda kesiliyordu. Hiçbir şey
    bunu fark etmiyordu: kullanıcı fark etti.
    """
    import subprocess
    from short_bot.reel_assembler import MAX_AUDIO_GAP_S, audio_gap_s

    # 3sn'lik gerçek bir mp4 üret — sesi tam.
    import tempfile
    from pathlib import Path as _P
    td = _P(tempfile.mkdtemp())
    v = td / "ok.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-t", "3", str(v)], capture_output=True, check=True)
    assert audio_gap_s(v, 3.0) <= MAX_AUDIO_GAP_S, "sağlam video kusurlu sayıldı"
    # Beklenen süreyi şişirince (ses eksikmiş gibi) denetim yakalamalı.
    assert audio_gap_s(v, 10.0) > MAX_AUDIO_GAP_S
