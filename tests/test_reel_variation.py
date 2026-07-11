from short_bot.config import ReelConfig
from short_bot.reel_variation import (HOOK_ANGLES, LAYOUTS, VariationProfile,
                                      build_variation_profile)


class _Ch:
    colors = {"primary": "#0ea5e9", "accent": "#facc15", "bg_gradient": ["#0f172a", "#020617"]}

    def __init__(self, **reel_kw):
        self.reel = ReelConfig(enabled=True, voice_id="v", **reel_kw)


def test_same_seed_same_profile():
    ch = _Ch()
    assert build_variation_profile(ch, 7) == build_variation_profile(ch, 7)


def test_different_seed_rotates_layout():
    ch = _Ch()
    layouts = {build_variation_profile(ch, s).layout for s in range(len(LAYOUTS) * 2)}
    assert len(layouts) >= 2                       # rotasyon var


def test_auto_layout_from_pool():
    ch = _Ch(layout="auto")
    assert build_variation_profile(ch, 0).layout in LAYOUTS


def test_pinned_layout_overrides_rotation():
    ch = _Ch(layout="classic")
    assert all(build_variation_profile(ch, s).layout == "classic" for s in range(5))


def test_hook_angle_pool_when_vary(monkeypatch):
    ch = _Ch(hook_angle_vary=True)
    angles = {build_variation_profile(ch, s).hook_angle for s in range(len(HOOK_ANGLES) * 2)}
    assert len(angles) >= 2
    assert build_variation_profile(ch, 0).hook_angle in HOOK_ANGLES


def test_hook_angle_empty_when_not_vary():
    ch = _Ch(hook_angle_vary=False)
    assert build_variation_profile(ch, 3).hook_angle == ""


def test_accent_varies_or_fixed():
    varied = {build_variation_profile(_Ch(accent_vary=True), s).accent for s in range(6)}
    assert len(varied) >= 2
    fixed = _Ch(accent_vary=False, highlight_color="#ff0000")
    assert build_variation_profile(fixed, 4).accent == "#ff0000"


def test_transitions_subset():
    p = build_variation_profile(_Ch(transition_vary=True), 2)
    assert set(p.transitions) <= {"flash", "whoosh", "zoom"}
    fixed = _Ch(transition_vary=False, transitions_flash=True,
                transitions_whoosh=False, transitions_zoom=True)
    assert set(build_variation_profile(fixed, 1).transitions) == {"flash", "zoom"}


def test_accent_variants_excludes_dark_primary():
    from short_bot.reel_variation import _accent_variants

    class _R:
        highlight_color = "#38bdf8"

    class _C:
        reel = _R()
        colors = {"accent": "#2de2e6", "primary": "#0a2540"}

    variants = _accent_variants(_C())
    assert "#0a2540" not in variants           # koyu primary elendi
    assert "#38bdf8" in variants


def test_variation_has_marker_kit():
    from short_bot.reel_variation import build_variation_profile, MARKER_TYPES
    ch = _Ch()
    kit = build_variation_profile(ch, 7).marker_kit
    assert kit                                 # kit boş değil
    assert set(kit) <= set(MARKER_TYPES)       # MARKER_TYPES alt kümesi


def test_variation_has_cut_effect():
    from short_bot.reel_variation import build_variation_profile, CUT_EFFECTS
    ch = _Ch()
    assert build_variation_profile(ch, 7).cut_effect in CUT_EFFECTS
