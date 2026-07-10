from pathlib import Path

from short_bot.config import ReelConfig
from short_bot.pipeline import _reel_produce_or_none


class _Settings:
    ffmpeg_path = "ffmpeg"; playwright_browser = "chromium"


class _Channel:
    slug = "c"; language = "tr"; handle = "@c"
    colors = {"primary": "#111", "accent": "#222", "bg_gradient": ["#0f172a", "#020617"]}
    output_dir = "output/c"; reel = None


class _AICall:
    claude_path = "claude"; model = "haiku"; backend = "claude_cli"; api_key = None


class _Log:
    def info(self, *a): pass
    def warning(self, *a): pass


def _kwargs(tmp_path, **over):
    base = dict(
        channel=_Channel(), topic="bal ilginç bilgi", out_path=tmp_path / "o.mp4",
        settings=_Settings(), secrets={}, music_root=tmp_path, templates_dir=Path("templates"),
        cache_dir=tmp_path / "cache", work_dir=tmp_path / "w", log=_Log(),
        llm_call=_AICall(), vision_call=_AICall(),
    )
    base.update(over); return base


def test_non_reel_channel_returns_none(tmp_path):
    assert _reel_produce_or_none(**_kwargs(tmp_path)) is None


def test_reel_channel_delegates(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr("short_bot.reel.produce_reel_video",
                        lambda **kw: (seen.update(kw), kw["out_path"])[1])
    monkeypatch.delenv("AI33_API_KEY", raising=False)

    class Reel(_Channel):
        reel = ReelConfig(enabled=True, voice_id="elevenlabs_v1")

    out = _reel_produce_or_none(**_kwargs(tmp_path, channel=Reel(),
                                          secrets={"ai33_api_key": "sk_x", "pexels_api_key": "pk"}))
    assert out == tmp_path / "o.mp4"
    assert seen["ai33_api_key"] == "sk_x"
    assert seen["pexels_api_key"] == "pk"
    assert seen["topic"] == "bal ilginç bilgi"


def test_reel_disabled_returns_none(tmp_path):
    class Off(_Channel):
        reel = ReelConfig(enabled=False)
    assert _reel_produce_or_none(**_kwargs(tmp_path, channel=Off())) is None
