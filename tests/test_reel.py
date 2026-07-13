from pathlib import Path

import pytest

from short_bot.config import ReelConfig
from short_bot.reel import ReelDeps, produce_reel_video
from short_bot.reel_models import ReelBeat, ReelNarration


def _narr():
    return ReelNarration(
        hook="Bal nasıl olur?",
        beats=[
            ReelBeat(text="Arılar nektar toplar.", visual_query="bee flower", keyword="NEKTAR"),
            ReelBeat(text="Enzimlerle işler bunu.", visual_query="bee macro", keyword="ENZİM"),
            ReelBeat(text="Peteğe biriktirir.", visual_query="honeycomb", keyword="PETEK"),
        ],
        close="İşte arının emeği.", mood="upbeat",
    )


class _Channel:
    slug = "test-reel"; language = "tr"; handle = "@test"
    colors = {"primary": "#0ea5e9", "accent": "#facc15", "bg_gradient": ["#0f172a", "#020617"]}
    reel = ReelConfig(enabled=True, voice_id="elevenlabs_v1", target_duration_s=(25, 45))


def _deps(calls, health="healthy"):
    return ReelDeps(
        write_reel_narration=lambda *a, **kw: (calls.append("narr"), _narr())[1],
        health_check=lambda **kw: (calls.append("health"), health)[1],
        synthesize=lambda text, **kw: (calls.append(("tts", text)),
                                       Path(kw["out_path"]).write_bytes(b"mp3"),
                                       Path(kw["out_path"]))[2],
        probe_duration_s=lambda p, **kw: (calls.append("probe"), 30.0)[1],
        transcribe_words=lambda p, **kw: (calls.append("asr"), [])[1],
        match_beat_clip=lambda q, **kw: (calls.append(("match", q)),
                                         Path(kw["cache_dir"]).joinpath(f"{q[:3]}.mp4"))[1]
                        if _mk(kw["cache_dir"], q) else None,
        render_reel_overlay_frames=lambda tl, out, **kw: (calls.append("render"), 900)[1],
        assemble_reel=lambda **kw: (calls.append(("assemble", kw)), kw["out_path"])[1],
    )


def _mk(cache_dir, q):
    p = Path(cache_dir); p.mkdir(parents=True, exist_ok=True)
    (p / f"{q[:3]}.mp4").write_bytes(b"mp4"); return True


def _call(deps, tmp_path, **over):
    kwargs = dict(
        topic="bal ilginç bilgi", channel=_Channel(),
        templates_dir=Path("templates"), work_dir=tmp_path,
        out_path=tmp_path / "out.mp4", music_path=tmp_path / "m.mp3",
        ai33_api_key="k", pexels_api_key="pk", ffmpeg_path="ffmpeg",
        deps=deps,
    )
    kwargs.update(over)
    return produce_reel_video(**kwargs)


def test_happy_path_chain_order(tmp_path):
    calls = []
    out = _call(_deps(calls), tmp_path)
    assert out == tmp_path / "out.mp4"
    names = [c if isinstance(c, str) else c[0] for c in calls]
    # preflight ÖNCE, sonra narration, tts, probe, asr, match'ler, render, assemble
    # (5 segment = hook + 3 beat + close; fast_cuts açıkken beat başına 2-3 klip
    # çekilir → match sayısı segment sayısından FAZLA)
    assert names[0] == "health" and names[1] == "narr"
    assert names.count("match") >= 5
    assert names[-2:] == ["render", "assemble"]


def test_tts_gets_full_text(tmp_path):
    calls = []
    _call(_deps(calls), tmp_path)
    tts = next(c[1] for c in calls if isinstance(c, tuple) and c[0] == "tts")
    assert tts == _narr().full_text()


def test_assemble_gets_subcut_clips(tmp_path):
    """fast_cuts (varsayılan açık): 5 segment → segment-içi alt-kesimlerle DAHA
    ÇOK parça. clip_paths ve seg_spans daima aynı boyda."""
    calls = []
    _call(_deps(calls), tmp_path)
    _, kw = next(c for c in calls if isinstance(c, tuple) and c[0] == "assemble")
    assert len(kw["clip_paths"]) == len(kw["seg_spans"])
    assert len(kw["clip_paths"]) > 5       # alt-kesim → 5 segment'ten fazla
    assert kw["duration_s"] == 30.0


@pytest.mark.parametrize("verdict,match,n_health", [
    # GEÇİCİ ("stalled"): yeniden denenir — ai33 üç kez anlık kesinti verip koşuyu
    # düşürdü, hemen ardından SAĞLIKLI çıktı. KALICI (auth/no-key): anında dur,
    # beklemenin faydası yok.
    ("stalled", "kuyruk", 3),
    ("auth", "AI33_API_KEY", 1),
    ("no-key", "AI33_API_KEY", 1)])
def test_preflight_failure_stops_before_llm(tmp_path, verdict, match, n_health,
                                            monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a: None)   # geri çekilmeyi hızlandır
    calls = []
    with pytest.raises(RuntimeError, match=match):
        _call(_deps(calls, health=verdict), tmp_path)
    assert calls == ["health"] * n_health
    assert "narr" not in calls, "preflight geçmeden LLM kredisi harcandı"


def test_requires_reel_enabled(tmp_path):
    class NoReel(_Channel):
        reel = None
    with pytest.raises(ValueError, match="reel"):
        _call(_deps([]), tmp_path, channel=NoReel())


def test_match_with_fallback_simplifies_query(tmp_path):
    from short_bot.reel import _match_with_fallback
    tries = []

    class D:
        def match_beat_clip(self, q, **kw):
            tries.append((q, kw.get("verify")))
            return Path("clip.mp4") if q == "storm cloud" else None

    clip, gated = _match_with_fallback(
        D(), "storm cloud interior ice crystals turbulence", topic_q="lightning",
        api_key="k", cache_dir=tmp_path, verify=True, vision_call=object())
    assert clip == Path("clip.mp4") and gated is True
    assert tries[0][0] == "storm cloud interior ice crystals turbulence"  # önce tam
    assert tries[1][0] == "storm cloud"                                   # sonra ilk 2 kelime


def test_match_with_fallback_last_resort_drops_vision(tmp_path):
    from short_bot.reel import _match_with_fallback
    tries = []

    class D:
        def match_beat_clip(self, q, **kw):
            tries.append(kw.get("verify"))
            return Path("c.mp4") if kw.get("verify") is False else None  # yalnız son çare

    clip, gated = _match_with_fallback(
        D(), "very rare specific subject phrase", topic_q="nature",
        api_key="k", cache_dir=tmp_path, verify=True, vision_call=object())
    assert clip == Path("c.mp4")
    assert tries[-1] is False        # son çağrı vision'sız (boş dönmesin)
    assert gated is False            # DOĞRULANMADI → tekrar havuzuna girmemeli
