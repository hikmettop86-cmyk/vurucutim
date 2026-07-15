"""Görüntü-öncelikli mod entegrasyonu (produce_reel_video iki dallanma)."""
from short_bot.reel import ReelDeps


def test_reeldeps_footage_driven_alanlari_var():
    d = ReelDeps()
    assert callable(d.write_footage_driven_narration)
    assert callable(d.footage_search_queries)


from pathlib import Path

from short_bot.reel import _footage_driven_clip_count, _footage_driven_seg_clip


def test_klip_sayisi_sureden_turer():
    assert _footage_driven_clip_count((45, 60)) == 5   # ort 52.5 / 11 ≈ 5
    assert _footage_driven_clip_count((25, 45)) == 3   # ort 35 / 11 ≈ 3
    assert _footage_driven_clip_count((10, 12)) == 3   # taban 3
    assert _footage_driven_clip_count((160, 180)) == 6 # tavan 6


def test_beat_klip_eslemesi():
    # 3 klip → 5 segment (hook + 3 beat + close). hook=clips[0], close=clips[-1].
    clips = [Path("c0.mp4"), Path("c1.mp4"), Path("c2.mp4")]
    n_segs = 5
    got = [_footage_driven_seg_clip(clips, si, n_segs) for si in range(n_segs)]
    assert got == [Path("c0.mp4"),   # seg 0 hook  → clips[0]
                   Path("c0.mp4"),   # seg 1 beat0 → clips[0]
                   Path("c1.mp4"),   # seg 2 beat1 → clips[1]
                   Path("c2.mp4"),   # seg 3 beat2 → clips[2]
                   Path("c2.mp4")]   # seg 4 close → clips[-1]


def test_beat_klip_kelepce_beat_fazlaysa():
    # LLM 4 beat yazdı ama 2 klip var (n_segs=6) → fazla beat son klibe kelepçelenir.
    clips = [Path("c0.mp4"), Path("c1.mp4")]
    n_segs = 6
    got = [_footage_driven_seg_clip(clips, si, n_segs) for si in range(n_segs)]
    assert got == [Path("c0.mp4"), Path("c0.mp4"), Path("c1.mp4"),
                   Path("c1.mp4"), Path("c1.mp4"), Path("c1.mp4")]
