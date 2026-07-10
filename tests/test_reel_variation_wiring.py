from pathlib import Path

from short_bot.config import ReelConfig
from short_bot.reel import ReelDeps, produce_reel_video
from short_bot.reel_models import ReelBeat, ReelNarration


def _narr():
    return ReelNarration(
        hook="Bal nasıl olur?",
        beats=[ReelBeat(text="Arılar nektar toplar.", visual_query="bee flower", keyword="NEKTAR"),
               ReelBeat(text="Enzimlerle işler bunu.", visual_query="bee macro", keyword="ENZİM"),
               ReelBeat(text="Peteğe biriktirir.", visual_query="honeycomb", keyword="PETEK")],
        close="İşte arının emeği.", mood="upbeat")


class _Ch:
    slug = "c"; language = "tr"; handle = "@t"
    colors = {"primary": "#0ea5e9", "accent": "#facc15", "bg_gradient": ["#0f172a", "#020617"]}
    reel = ReelConfig(enabled=True, voice_id="v", target_duration_s=(25, 45))


def _deps(rec):
    def match(q, **kw):
        p = Path(kw["cache_dir"]); p.mkdir(parents=True, exist_ok=True)
        f = p / f"{abs(hash(q)) % 1000}.mp4"; f.write_bytes(b"m"); return f
    return ReelDeps(
        write_reel_narration=lambda *a, **kw: (rec.__setitem__("hook_angle", kw.get("hook_angle")), _narr())[1],
        health_check=lambda **kw: "healthy",
        synthesize=lambda t, **kw: (Path(kw["out_path"]).write_bytes(b"m"), Path(kw["out_path"]))[1],
        probe_duration_s=lambda p, **kw: 30.0,
        transcribe_words=lambda p, **kw: [],
        match_beat_clip=match,
        render_reel_overlay_frames=lambda tl, out, **kw: (rec.__setitem__("layout", kw.get("layout")),
                                                          rec.__setitem__("hl", kw.get("highlight_color")), 900)[2],
        assemble_reel=lambda **kw: (rec.__setitem__("zoom", kw.get("zoom")), kw["out_path"])[1],
    )


def _call(deps, tmp_path, seed):
    return produce_reel_video(
        topic="bal", channel=_Ch(), templates_dir=Path("templates"),
        work_dir=tmp_path, out_path=tmp_path / "o.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", seed=seed, deps=deps)


def test_seed_drives_layout_and_angle(tmp_path):
    rec = {}
    _call(_deps(rec), tmp_path, seed=0)
    assert rec["layout"] in ("classic", "lower_left", "top_heavy")
    assert rec["hook_angle"]  # varyasyon açık -> dolu


def test_different_seeds_can_differ(tmp_path):
    seen = set()
    for s in range(6):
        rec = {}
        _call(_deps(rec), tmp_path / f"s{s}", s)
        seen.add((rec["layout"], rec["hl"]))
    assert len(seen) >= 2       # ardışık seed'ler farklı profil


def test_default_seed_zero(tmp_path):
    rec = {}
    produce_reel_video(
        topic="bal", channel=_Ch(), templates_dir=Path("templates"),
        work_dir=tmp_path, out_path=tmp_path / "o.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", deps=_deps(rec))
    assert "layout" in rec       # seed default 0 ile çalışır
