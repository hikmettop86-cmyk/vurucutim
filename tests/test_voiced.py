from pathlib import Path

import pytest

from short_bot.config import VoiceConfig
from short_bot.models import Script
from short_bot.narration import Beat, Narration
from short_bot.voiced import VoicedDeps, produce_voiced_video


class _Item:
    title = "Faiz karari"
    link = "https://example.com/x"
    source = "Ornek"


def _script():
    return Script(
        header_top="FAIZ KARARI", header_bottom="MERKEZ BANKASI",
        photo_overlay="BES PUAN INDI",
        body_paragraph="Merkez bankasi faizi bes puan indirdi ve piyasalar sasirdi.",
        highlights=[], category="Ekonomi", mood="breaking",
    )


def _narration():
    return Narration(
        hook="Neden herkes sasirdi?",
        beats=[
            Beat(text="Faiz bes puan indi.", on_screen="FAIZ"),
            Beat(text="Piyasalar beklemiyordu.", on_screen="SURPRIZ"),
            Beat(text="Kur hemen yukseldi.", on_screen="KUR"),
        ],
        loop_close="Iste tam bu yuzden.",
        mood="breaking",
    )


class _Channel:
    slug = "test-anlatici"
    language = "tr"
    handle = "@test"
    colors = {"primary": "#0ea5e9", "accent": "#facc15",
              "bg_gradient": ["#0f172a", "#020617"]}
    duration_s = 6
    voice = VoiceConfig(enabled=True, voice_id="elevenlabs_v1", speed=1.0,
                        target_duration_s=(45, 60))


def _deps(calls, health="healthy"):
    return VoicedDeps(
        write_narration=lambda *a, **kw: (calls.append("narration"), _narration())[1],
        health_check=lambda **kw: (calls.append("health"), health)[1],
        synthesize=lambda text, **kw: (calls.append(("tts", text)),
                                        Path(kw["out_path"]).write_bytes(b"mp3"),
                                        Path(kw["out_path"]))[2],
        probe_duration_s=lambda p, **kw: (calls.append("probe"), 48.0)[1],
        transcribe_words=lambda p, **kw: (calls.append("asr"), [])[1],
        render_frames=lambda job, tpl, out, **kw: (calls.append(("render", job, tpl)), 1440)[1],
        compose_video=lambda *a, **kw: (calls.append(("compose", kw)), a[2])[1],
    )


def _call(deps, tmp_path, **over):
    kwargs = dict(
        item=_Item(), body="haber govdesi", script=_script(),
        bg_image_path=None, music_path=tmp_path / "m.mp3",
        channel=_Channel(), templates_dir=Path("templates"),
        work_dir=tmp_path, out_path=tmp_path / "out.mp4",
        api_key="sk_test", ffmpeg_path="ffmpeg", ffprobe_path="ffprobe",
        deps=deps,
    )
    kwargs.update(over)
    return produce_voiced_video(**kwargs)


def test_happy_path_runs_full_chain(tmp_path):
    calls = []
    out = _call(_deps(calls), tmp_path)
    assert out == tmp_path / "out.mp4"
    names = [c if isinstance(c, str) else c[0] for c in calls]
    # preflight ONCE narration yazilir (bosuna LLM harcanmaz), sonra tts
    assert names == ["health", "narration", "tts", "probe", "asr", "render", "compose"]


def test_tts_receives_full_narration_text(tmp_path):
    calls = []
    _call(_deps(calls), tmp_path)
    tts_text = next(c[1] for c in calls if isinstance(c, tuple) and c[0] == "tts")
    assert tts_text == _narration().full_text()


def test_render_job_carries_timeline_and_narrator_template(tmp_path):
    calls = []
    _call(_deps(calls), tmp_path)
    _, job, tpl = next(c for c in calls if isinstance(c, tuple) and c[0] == "render")
    assert job.narration is not None
    assert job.narration.duration_s == 48.0
    assert len(job.narration.beats) == 3
    assert tpl.name == "narrator.html.j2"
    assert job.duration_s == 49          # ceil(48.0) + 1


def test_compose_gets_narration_and_quiet_music(tmp_path):
    calls = []
    _call(_deps(calls), tmp_path)
    _, kw = next(c for c in calls if isinstance(c, tuple) and c[0] == "compose")
    assert kw["narration_path"].name == "narration.mp3"
    assert kw["music_volume"] == 0.12
    assert kw["duration_s"] == 49


@pytest.mark.parametrize("verdict,match", [
    ("stalled", "kuyruk"),
    ("auth", "AI33_API_KEY"),
    ("no-key", "AI33_API_KEY"),
    ("error", "ai33"),
])
def test_preflight_failure_stops_before_llm(tmp_path, verdict, match):
    calls = []
    with pytest.raises(RuntimeError, match=match):
        _call(_deps(calls, health=verdict), tmp_path)
    assert calls == ["health"]            # LLM ve TTS hic cagrilmadi


def test_requires_voice_enabled(tmp_path):
    class NoVoice(_Channel):
        voice = None
    with pytest.raises(ValueError, match="voice"):
        _call(_deps([]), tmp_path, channel=NoVoice())
