"""Kurgucu planı ile seed-hash varyasyonunun evliliği."""
from short_bot.reel_director import EditPlan
from short_bot.reel_variation import build_variation_profile


class _Reel:
    layout = "auto"; cut_pacing = "auto"
    highlight_color = "#ff3355"; arrow_color = "#fff"
    hook_angle_vary = True; accent_vary = True; transition_vary = True
    transitions_flash = True; transitions_whoosh = True; transitions_zoom = True


class _Ch:
    slug = "bilim"; colors = {}
    reel = _Reel()


def test_plan_fields_override_seed_hash():
    """Kurgucunun ayrım yaptığı İÇERİK alanları seed-hash'i ezer."""
    plan = EditPlan(cut_effect="lightleak", music_mood="dark",
                    sfx_plan=["impact", "whoosh"])
    p = build_variation_profile(_Ch(), seed=42, edit_plan=plan)
    assert p.cut_effect == "lightleak"
    assert p.music_mood == "dark" and p.sfx_plan == ("impact", "whoosh")


def test_empty_plan_fields_fall_back_to_seed_hash():
    """Kurgucu bir alanı boş bıraktıysa (ya da uydurması elendiyse) eski davranış.

    validate_plan cut_pacing/layout/marker_kit'i HER ZAMAN boşaltır (mod çöküşü),
    yani gerçekte bu alanlar hep bu daldan gelir — çeşitlilik seed'den GARANTİ.
    """
    seedy = build_variation_profile(_Ch(), seed=42)
    p = build_variation_profile(_Ch(), seed=42, edit_plan=EditPlan())
    assert p.cut_pacing == seedy.cut_pacing and p.cut_effect == seedy.cut_effect
    assert p.layout == seedy.layout and p.marker_kit == seedy.marker_kit
    assert p.music_mood == "" and p.sfx_plan == ()


def test_no_plan_is_backwards_compatible():
    a = build_variation_profile(_Ch(), seed=9)
    b = build_variation_profile(_Ch(), seed=9, edit_plan=None)
    assert a == b


def test_explicit_channel_setting_wins():
    """Kullanıcı layout/tempoyu elle seçtiyse seed de kurgucu da onu EZEMEZ."""
    class _R(_Reel):
        layout = "classic"; cut_pacing = "fast"

    class _C(_Ch):
        reel = _R()

    p = build_variation_profile(_C(), seed=1, edit_plan=EditPlan(cut_effect="glitch"))
    assert p.cut_pacing == "fast" and p.layout == "classic"
    assert p.cut_effect == "glitch"      # kurgucunun alanı yine de geçerli
