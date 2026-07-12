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
    monkeypatch.setattr(fm, "_extract_cropped_frame", lambda clip, ff, out: out.write_bytes(b"x") or out)
    class _R:  # run_json dönüşü
        found=True; discrete=True; confidence=0.88; x=0.42; y=0.61
    monkeypatch.setattr(fm, "run_json", lambda *a, **k: _R(), raising=False)
    p = locate_subject(tmp_path/"c.mp4", "kedi", vision_call=_VC(), ffmpeg_path="ffmpeg")
    assert p.found and abs(p.x-0.42) < 1e-6 and abs(p.y-0.61) < 1e-6
    assert p.discrete is True and abs(p.confidence-0.88) < 1e-6
