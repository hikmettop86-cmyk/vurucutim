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


import short_bot.reel as REEL
from short_bot.reel import ReelDeps, _prepare_footage_driven


def _fd_channel():
    from types import SimpleNamespace
    reel = SimpleNamespace(target_duration_s=(45, 60), persona="vahsi_mizah",
                           verify_footage=True, footage_anchor="chimpanzee jungle")
    return SimpleNamespace(reel=reel, language="tr", dna=None)


def test_prepare_indirir_ve_tarif_eder(tmp_path, monkeypatch):
    # match_beat_clip her çağrıda FARKLI klip döndürür (exclude ile ayrık).
    sayac = {"n": 0}

    def fake_match(q, **kw):
        excl = kw.get("exclude") or set()
        for i in range(10):
            p = tmp_path / f"clip{i}.mp4"
            if str(p) not in excl:
                p.write_bytes(b"mp4")
                sayac["n"] += 1
                return p
        return None

    d = ReelDeps(
        footage_search_queries=lambda topic, **k: ["chimpanzee", "chimpanzee fighting"],
        match_beat_clip=fake_match)
    # vision tarifini deterministik yap
    monkeypatch.setattr(REEL, "_describe_clip",
                        lambda c, **k: f"a chimpanzee ({c.name})")

    clips, descs, queries = _prepare_footage_driven(
        topic="şempanze", channel=_fd_channel(), reel=_fd_channel().reel, d=d,
        work_dir=tmp_path, pexels_api_key="k", pixabay_api_key="",
        footage_priority=["pexels"], storyblocks_session=None,
        vision_call=object(), ffmpeg_path="ffmpeg",
        llm_claude_path="claude", llm_model="default",
        llm_backend="claude_cli", llm_api_key=None)

    assert len(clips) == 5                       # (45,60) → 5 klip
    assert len(descs) == 5 and len(queries) == 5 # üçü index-hizalı
    assert len(set(map(str, clips))) == 5        # hepsi AYRIK (exclude çalıştı)
    assert all("chimpanzee" in dsc for dsc in descs)


def test_prepare_hic_footage_yoksa_hata(tmp_path, monkeypatch):
    d = ReelDeps(
        footage_search_queries=lambda topic, **k: ["nonexistent"],
        match_beat_clip=lambda q, **kw: None)
    monkeypatch.setattr(REEL, "_describe_clip", lambda c, **k: "")
    import pytest
    with pytest.raises(RuntimeError, match="footage bulunamadı"):
        _prepare_footage_driven(
            topic="x", channel=_fd_channel(), reel=_fd_channel().reel, d=d,
            work_dir=tmp_path, pexels_api_key="k", pixabay_api_key="",
            footage_priority=["pexels"], storyblocks_session=None,
            vision_call=object(), ffmpeg_path="ffmpeg", llm_claude_path="claude",
            llm_model="default", llm_backend="claude_cli", llm_api_key=None)
