import short_bot.reel_assembler as ra


class _P:
    returncode = 0
    stderr = ""


def test_normalize_segment_seeks_and_punches(monkeypatch, tmp_path):
    """Alt-kesim: aynı klibin FARKLI anından başla (-ss) + açılışta zoom-punch."""
    cmds = []
    monkeypatch.setattr(ra, "_run", lambda c: (cmds.append(c), _P())[1])
    clip = tmp_path / "c.mp4"; clip.write_bytes(b"x")
    ra._normalize_segment(clip, 2.0, tmp_path / "o.mp4", fps=30, ffmpeg="ffmpeg",
                          zoom=True, start_s=4.5, punch=True)
    cmd = cmds[0]
    assert "-ss" in cmd and "4.500" in cmd          # klip içinde seek
    vf = cmd[cmd.index("-vf") + 1]
    assert "zoompan" in vf and "1.25" in vf         # agresif punch filtresi


def test_normalize_segment_no_seek_by_default(monkeypatch, tmp_path):
    cmds = []
    monkeypatch.setattr(ra, "_run", lambda c: (cmds.append(c), _P())[1])
    clip = tmp_path / "c.mp4"; clip.write_bytes(b"x")
    ra._normalize_segment(clip, 2.0, tmp_path / "o.mp4", fps=30, ffmpeg="ffmpeg",
                          zoom=False)
    assert "-ss" not in cmds[0]


def test_punch_only_on_first_segment(monkeypatch, tmp_path):
    """hook_punch → yalnız İLK alt-kesime uygulanır."""
    seen = []

    def fake_norm(clip, span, out, *, fps, ffmpeg, zoom, start_s=0.0, punch=False,
                  **_kw):
        seen.append(punch)
        out.write_bytes(b"seg")
    monkeypatch.setattr(ra, "_normalize_segment", fake_norm)
    monkeypatch.setattr(ra, "_run", lambda c: _P())

    clips = []
    for i in range(3):
        c = tmp_path / f"c{i}.mp4"; c.write_bytes(b"x"); clips.append(c)
    nar = tmp_path / "n.mp3"; nar.write_bytes(b"a")
    frames = tmp_path / "fr"; frames.mkdir()
    try:
        ra.assemble_reel(
            clip_paths=clips, seg_spans=[(0, 2), (2, 4), (4, 6)],
            frames_dir=frames, narration_path=nar, music_path=None,
            out_path=tmp_path / "o.mp4", cut_times=[2.0, 4.0], duration_s=6.0,
            clip_starts=[0.0, 1.5, 3.0], hook_punch=True)
    except Exception:
        pass    # concat/ffmpeg sahte — normalize çağrıları yeterli
    assert seen[:3] == [True, False, False]
