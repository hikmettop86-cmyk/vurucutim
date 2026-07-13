from pathlib import Path
from short_bot.footage_matcher import locate_subject, SubjectPos


class _VC:  # vision_call stub
    claude_path="claude"; model="m"; backend="openrouter"; api_key="k"


def test_locate_no_vision_returns_not_found(tmp_path):
    p = locate_subject(tmp_path/"c.mp4", "kedi", vision_call=None)
    assert isinstance(p, SubjectPos) and p.found is False


def test_locate_parses_vision(tmp_path, monkeypatch):
    import short_bot.footage_matcher as fm
    # kare çıkarmayı ve vision çağrısını sahtele
    monkeypatch.setattr(fm, "_extract_cropped_frame",
                        lambda clip, ff, out, at_s=1.0: out.write_bytes(b"x") or out)
    class _R:  # run_json dönüşü
        found=True; discrete=True; confidence=0.88; x=0.42; y=0.61
    monkeypatch.setattr(fm, "run_json", lambda *a, **k: _R(), raising=False)
    p = locate_subject(tmp_path/"c.mp4", "kedi", vision_call=_VC(), ffmpeg_path="ffmpeg")
    assert p.found and abs(p.x-0.42) < 1e-6 and abs(p.y-0.61) < 1e-6
    assert p.discrete is True and abs(p.confidence-0.88) < 1e-6


def test_locate_reads_the_frame_the_viewer_actually_sees(tmp_path, monkeypatch):
    """Kare, alt-kesimin GERÇEK başlangıç saniyesinden alınmalı.

    Sabit 1. saniyeden ölçmek, klibin ortasından başlayan bir alt-kesimde hareketli
    özneyi (uçan arı) ıskalıyor → marker BOŞLUĞU işaretliyordu.
    """
    import short_bot.footage_matcher as fm
    seen = {}

    def fake_extract(clip, ff, out, at_s=1.0):
        seen["at_s"] = at_s
        out.write_bytes(b"x")
        return out

    monkeypatch.setattr(fm, "_extract_cropped_frame", fake_extract)

    class _R:
        found = True; discrete = True; confidence = 0.9; x = 0.5; y = 0.5
    monkeypatch.setattr(fm, "run_json", lambda *a, **k: _R(), raising=False)

    locate_subject(tmp_path/"c.mp4", "kedi", vision_call=_VC(), at_s=4.9)
    assert abs(seen["at_s"] - 4.9) < 1e-6
