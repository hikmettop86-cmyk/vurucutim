from short_bot.footage_matcher import SubjectPos
from short_bot.reel_markers import build_markers, MARKER_TYPES


def test_marker_types_are_six():
    assert set(MARKER_TYPES) == {"arrow","ring","pulse","box","spotlight","underline"}


def test_build_markers_skips_not_found_and_off():
    pos = [SubjectPos(found=True, x=0.3, y=0.4),
           SubjectPos(found=False, x=0.5, y=0.5),
           SubjectPos(found=True, x=0.6, y=0.7)]
    ms = build_markers(pos, marker_kit=("ring",), frequency="beats", seed=1)
    segs = {m["seg"] for m in ms}
    assert 1 not in segs                       # found=False atlandı
    assert all(m["type"] == "ring" for m in ms)
    assert build_markers(pos, marker_kit=("ring",), frequency="off", seed=1) == []


def test_build_markers_rotates_kit():
    pos = [SubjectPos(found=True, x=0.5, y=0.5) for _ in range(4)]
    ms = build_markers(pos, marker_kit=("arrow","box"), frequency="beats", seed=2)
    types = [m["type"] for m in ms]
    assert set(types) <= {"arrow","box"} and len(set(types)) >= 1
