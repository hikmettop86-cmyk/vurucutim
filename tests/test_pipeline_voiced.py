from pathlib import Path

from short_bot.config import VoiceConfig
from short_bot.pipeline import _render_and_compose


class _Settings:
    ffmpeg_path = "ffmpeg"
    playwright_browser = "chromium"


class _Channel:
    slug = "c"
    language = "tr"
    handle = "@c"
    colors = {"primary": "#111", "accent": "#222", "bg_gradient": ["#0f172a", "#020617"]}
    cta_enabled = False
    cta_text = ""
    cta_icons: list[str] = []
    cta_duration_s = 0
    cta_show_handle = True
    duration_s = 6
    bg_video = None
    voice = None


def _kwargs(tmp_path, **over):
    base = dict(
        job=object(), archetype="newscast", templates_dir=Path("templates"),
        frames_dir=tmp_path / "frames", music=tmp_path / "m.mp3",
        out_path=tmp_path / "o.mp4", channel=_Channel(), settings=_Settings(),
        secrets={}, ui_labels={}, dna_css="", animation_style="none",
        sfx_overlays=[], bg_video_path=None, item=object(), body="b",
        script=object(), bg_image_path=None, log=_Log(),
        llm_call=_AICall(),
    )
    base.update(over)
    return base


class _Log:
    def info(self, *a): pass
    def warning(self, *a): pass


class _AICall:
    claude_path = "claude"
    model = "haiku"
    backend = "claude_cli"
    api_key = None


def test_silent_channel_uses_render_and_compose(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("short_bot.pipeline.render_frames",
                        lambda *a, **kw: seen.append("render"))
    monkeypatch.setattr("short_bot.pipeline.compose_video",
                        lambda *a, **kw: seen.append("compose"))
    monkeypatch.setattr("short_bot.voiced.produce_voiced_video",
                        lambda **kw: seen.append("voiced"))

    _render_and_compose(**_kwargs(tmp_path))
    assert seen == ["render", "compose"]


def test_voiced_channel_delegates_to_produce_voiced_video(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("short_bot.pipeline.render_frames",
                        lambda *a, **kw: seen.append("render"))
    monkeypatch.setattr("short_bot.pipeline.compose_video",
                        lambda *a, **kw: seen.append("compose"))
    monkeypatch.setattr("short_bot.voiced.produce_voiced_video",
                        lambda **kw: (seen.append(("voiced", kw)), kw["out_path"])[1])

    class Voiced(_Channel):
        voice = VoiceConfig(enabled=True, voice_id="elevenlabs_v1")

    _render_and_compose(**_kwargs(tmp_path, channel=Voiced()))
    assert [s if isinstance(s, str) else s[0] for s in seen] == ["voiced"]


def test_voiced_passes_ai33_key_from_secrets(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr("short_bot.voiced.produce_voiced_video",
                        lambda **kw: (captured.update(kw), kw["out_path"])[1])
    monkeypatch.delenv("AI33_API_KEY", raising=False)

    class Voiced(_Channel):
        voice = VoiceConfig(enabled=True, voice_id="elevenlabs_v1")

    _render_and_compose(**_kwargs(tmp_path, channel=Voiced(),
                                  secrets={"ai33_api_key": "sk_from_secrets"}))
    assert captured["api_key"] == "sk_from_secrets"
    assert captured["ffmpeg_path"] == "ffmpeg"


def test_voiced_disabled_block_still_silent(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("short_bot.pipeline.render_frames",
                        lambda *a, **kw: seen.append("render"))
    monkeypatch.setattr("short_bot.pipeline.compose_video",
                        lambda *a, **kw: seen.append("compose"))

    class Off(_Channel):
        voice = VoiceConfig(enabled=False)

    _render_and_compose(**_kwargs(tmp_path, channel=Off()))
    assert seen == ["render", "compose"]
