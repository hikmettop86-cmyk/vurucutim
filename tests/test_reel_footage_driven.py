"""Görüntü-öncelikli mod entegrasyonu (produce_reel_video iki dallanma)."""
from short_bot.reel import ReelDeps


def test_reeldeps_footage_driven_alanlari_var():
    d = ReelDeps()
    assert callable(d.write_footage_driven_narration)
    assert callable(d.footage_search_queries)
