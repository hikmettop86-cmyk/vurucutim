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
    reel = ReelConfig(enabled=True, voice_id="v", target_duration_s=(25, 45),
                      comment_question=True,
                      series_enabled=True, series_title="Tuhaf Gerçekler")


def _deps(rec):
    def match(q, **kw):
        p = Path(kw["cache_dir"]); p.mkdir(parents=True, exist_ok=True)
        f = p / f"{abs(hash(q)) % 1000}.mp4"; f.write_bytes(b"m"); return f
    return ReelDeps(
        write_reel_narration=lambda *a, **kw: (rec.update(series=kw.get("series_directive"),
                                                          comment=kw.get("comment_line")), _narr())[1],
        health_check=lambda **kw: "healthy",
        synthesize=lambda t, **kw: (Path(kw["out_path"]).write_bytes(b"m"), Path(kw["out_path"]))[1],
        probe_duration_s=lambda p, **kw: 30.0,
        transcribe_words=lambda p, **kw: [],
        match_beat_clip=match,
        render_reel_overlay_frames=lambda tl, out, **kw: (rec.update(badge=kw.get("badge", "")), 900)[1],
        assemble_reel=lambda **kw: kw["out_path"],
    )


def test_subscribe_bits_wired(tmp_path):
    rec = {}
    produce_reel_video(
        topic="bal", channel=_Ch(), templates_dir=Path("templates"),
        work_dir=tmp_path, out_path=tmp_path / "o.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", seed=1, deps=_deps(rec))
    assert "Tuhaf Gerçekler" in (rec["series"] or "")
    assert rec["comment"]         # yorum sorusu dolu
    assert "cta_text" not in rec  # beğeni/abone çipi kablosu KALKTI (2026-07-16)
