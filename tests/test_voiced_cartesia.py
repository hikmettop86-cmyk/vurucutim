"""voiced.py sağlayıcı seçimi: cartesia kelimeleriyle hizalama, whisper atlanır; ai33 yolu aynı."""
from __future__ import annotations

from pathlib import Path

import pytest

from short_bot.models import NewsItem, Script
from short_bot.narration import Beat, Narration, TimedWord
from short_bot.tts.cartesia_client import SynthesisResult

SPOKEN = ("Adalar yine mi sallandı? Kandilli üç nokta bir dedi. Gece boyu elli bir sarsıntı oldu. "
          "Uzmanlar fayı izliyor dedi. Bu sıradan değil.")


def _channel(tmp_path, provider):
    from short_bot.config import ChannelConfig, VoiceConfig
    return ChannelConfig(
        slug="sesli", name="Sesli", keywords=["x"], rss_locale="hl=tr&gl=TR&ceid=TR:tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0, max_candidates_per_run=5,
        template="flas", colors={"primary": "#d0021b", "accent": "#ffe600",
                                 "bg_gradient": ["#3a3a3a", "#141414"]},
        handle="@s", output_dir=str(tmp_path / "out"), enabled=True, language="tr",
        voice=VoiceConfig(enabled=True, provider=provider, voice_id="v1", speed=1.05,
                          volume=1.3, model="sonic-preview", emotion="[sakin]",
                          target_duration_s=(10, 60), music_volume=0.05),
    )


def _narration():
    return Narration(hook="Adalar yine mi sallandı?",
                     beats=[Beat(text="Kandilli üç nokta bir dedi.", on_screen="3.1 BÜYÜKLÜK"),
                            Beat(text="Gece boyu elli bir sarsıntı oldu.", on_screen="51 SARSINTI"),
                            Beat(text="Uzmanlar fayı izliyor dedi.", on_screen="FAY İZLENİYOR")],
                     loop_close="Bu sıradan değil.", mood="neutral")


def _script():
    return Script(header_top="ADALAR", header_bottom="YİNE SALLANDI", photo_overlay="KANDİLLİ: 3.1",
                  body_paragraph="Adalar'da 3.1 büyüklüğünde deprem oldu. Gece boyu sürdü.",
                  highlights=[], category="Deprem", mood="breaking")


def _item():
    return NewsItem(guid="g", title="Adalar sallandı", link="https://x", source="Milliyet",
                    pub_date=None, thumb_url=None, description=None)


def _deps(tmp_path, provider, calls):
    from short_bot.voiced import VoicedDeps

    def _synth(text, **kw):
        calls["synth_kw"] = kw
        p = tmp_path / ("n.wav" if provider == "cartesia" else "n.mp3")
        p.write_bytes(b"\0" * 4096)
        if provider == "cartesia":
            words = [TimedWord(w, i * 0.5, i * 0.5 + 0.4, 0) for i, w in enumerate(SPOKEN.split())]
            return SynthesisResult(path=p, words=words, duration_s=6.0, chars_spent=len(text))
        return p

    def _transcribe(path, **kw):
        calls["transcribed"] = True
        return []

    def _health(**k):
        calls["health_kw"] = k
        return "healthy"

    def _render(job, tpl, frames_dir, **kw):
        calls["job"] = job
        calls["tpl"] = Path(tpl).name
        Path(frames_dir).mkdir(parents=True, exist_ok=True)

    def _compose(frames_dir, music, out_path, **kw):
        calls["compose_kw"] = kw
        Path(out_path).write_bytes(b"mp4")

    return VoicedDeps(write_narration=lambda *a, **k: _narration(), health_check=_health,
                      synthesize=_synth, probe_duration_s=lambda p, **k: 6.0,
                      transcribe_words=_transcribe, render_frames=_render, compose_video=_compose)


@pytest.mark.parametrize("provider", ["cartesia", "ai33"])
def test_voiced_provider_paths(tmp_path, provider):
    from short_bot.voiced import produce_voiced_video
    calls = {}
    ch = _channel(tmp_path, provider)
    out = produce_voiced_video(
        item=_item(), body="gövde", script=_script(), bg_image_path=None,
        music_path=tmp_path / "m.mp3", channel=ch, templates_dir=Path("templates"),
        work_dir=tmp_path / "w", out_path=tmp_path / "o.mp4", api_key="k",
        deps=_deps(tmp_path, provider, calls), ticker_items=("Sırada bir", "Sırada iki"))
    assert out.exists()
    kw = calls["synth_kw"]
    assert kw["voice_id"] == "v1" and kw["api_key"] == "k" and kw["speed"] == 1.05
    if provider == "cartesia":
        assert kw["volume"] == 1.3 and kw["model"] == "sonic-preview" and kw["emotion"] == "[sakin]"
        assert kw["language"] == "tr"
        assert "transcribed" not in calls                    # whisper atlandı
        assert calls["compose_kw"]["narration_path"] == tmp_path / "n.wav"
        assert calls["job"].narration.words[0].word == "Adalar"
        assert calls["job"].narration.words[0].start_s == pytest.approx(0.0)
    else:
        assert "volume" not in kw and "model" not in kw     # ai33 imzası değişmedi
        assert calls["transcribed"] is True
        assert calls["compose_kw"]["narration_path"] == tmp_path / "n.mp3"
    assert calls["job"].ticker_items == ("Sırada bir", "Sırada iki")
    assert calls["tpl"] in ("flas-narrator.html.j2", "narrator.html.j2")


def test_resolve_tts_provider_table():
    from short_bot.tts import ai33_client, cartesia_client, providers
    a = providers.resolve_tts("ai33")
    c = providers.resolve_tts("cartesia")
    assert a.synthesize is ai33_client.synthesize and a.health_check is ai33_client.health_check
    assert c.synthesize is cartesia_client.synthesize and c.health_check is cartesia_client.health_check
    assert a.resolve_api_key({"ai33_api_key": "x"}) == "x"
    assert c.resolve_api_key({"cartesia_api_key": "y"}) == "y"
    assert c.label == "Cartesia" and a.label == "ai33"
    with pytest.raises(ValueError):
        providers.resolve_tts("nope")


def test_recent_variations_are_passed_and_recorded(tmp_path):
    """Rotasyon zinciri: geçmiş → seçim → script.narration_variation."""
    from short_bot.config import VoiceConfig
    from short_bot.voiced import VoicedDeps, produce_voiced_video
    from short_bot.yorum_variation import pick_variation
    from dataclasses import replace as _replace

    ch = _channel(tmp_path, "cartesia")
    ch = _replace(ch, content_source="trends")
    script = _script()
    seen = {}

    def _yorum(item_, body, **kw):
        seen["variation"] = kw.get("variation")
        return _narration()

    def _synth(text, **kw):
        p = tmp_path / "n.wav"
        p.write_bytes(b"\0" * 4096)
        return SynthesisResult(path=p, words=[], duration_s=5.0, chars_spent=len(text))

    first = pick_variation(seed_text=f"{ch.slug}:g")
    deps = VoicedDeps(write_narration=lambda *a, **k: _narration(), write_yorum_narration=_yorum,
                      health_check=lambda **k: "healthy", synthesize=_synth,
                      probe_duration_s=lambda p, **k: 5.0, transcribe_words=lambda *a, **k: [],
                      render_frames=lambda job, tpl, fd, **k: Path(fd).mkdir(parents=True, exist_ok=True),
                      compose_video=lambda f, m, o, **k: Path(o).write_bytes(b"x"))
    produce_voiced_video(item=_item(), body="gövde", script=script, bg_image_path=None,
                         music_path=tmp_path / "m.mp3", channel=ch, templates_dir=Path("templates"),
                         work_dir=tmp_path / "w", out_path=tmp_path / "o.mp4", api_key="k",
                         deps=deps, recent_variations=(first.key,))
    v = seen["variation"]
    assert v is not None and v.opening_key != first.opening_key
    assert script.narration_variation == v.key
