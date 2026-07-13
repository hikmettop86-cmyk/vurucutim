from short_bot.footage_matcher import SubjectPos
from short_bot.reel_markers import MARKER_CONF_MIN, MARKER_TYPES, build_markers

# (segment, t0, t1) — 0=hook, 1..3=beat (marker alabilir), 4=kapanış
SUBCUTS = [(0, 0.0, 2.0), (1, 2.0, 4.0), (2, 4.0, 6.0), (3, 6.0, 8.0),
           (4, 8.0, 10.0)]


def _pos(**kw):
    base = dict(found=True, discrete=True, confidence=0.9, x=0.5, y=0.5)
    base.update(kw)
    return SubjectPos(**base)


def test_marker_types_are_six():
    assert set(MARKER_TYPES) == {"arrow", "ring", "pulse", "box", "spotlight",
                                 "underline"}


def test_build_markers_rotates_kit():
    ms = build_markers(SUBCUTS, [_pos()] * len(SUBCUTS),
                       marker_kit=("arrow", "box"), frequency="beats", seed=2)
    types = [m["type"] for m in ms]
    assert types and set(types) <= {"arrow", "box"}


def test_build_markers_skips_not_found():
    pos = [_pos(), _pos(found=False), _pos(x=0.6, y=0.7), _pos(), _pos()]
    ms = build_markers(SUBCUTS, pos, marker_kit=("ring",), frequency="beats",
                       seed=1)
    assert 1 not in {m["seg"] for m in ms}      # found=False olan segment atlandı
    assert all(m["type"] == "ring" for m in ms)


def test_build_markers_gates_on_discrete_and_confidence():
    pos = [_pos(x=0.1, y=0.1),                 # hook — marker almaz
           _pos(discrete=False),               # manzara → elenir
           _pos(confidence=0.3),               # düşük güven → elenir
           _pos(x=0.6, y=0.7),                 # geçer
           _pos(x=0.8, y=0.8)]                 # kapanış — marker almaz
    ms = build_markers(SUBCUTS, pos, marker_kit=("ring",), frequency="beats",
                       seed=1)
    assert {m["seg"] for m in ms} == {3}       # yalnız güvenli + tekil beat
    assert MARKER_CONF_MIN == 0.55


def test_build_markers_off_disables_everything():
    assert build_markers(SUBCUTS, [_pos()] * len(SUBCUTS), marker_kit=("ring",),
                         frequency="off", seed=1) == []
