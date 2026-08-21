"""channel_format kararları, flas-narrator şablonu, voiced'da yorum yazarı seçimi."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from short_bot.models import NewsItem, RenderJob, Script
from short_bot.narration import NarrationTimeline, TimedBeat, TimedWord


def _cfg(**kw):
    from short_bot.config import ChannelConfig
    base = dict(slug="x", name="X", keywords=["k"], rss_locale="hl=tr&gl=TR&ceid=TR:tr",
                schedule_cron="0 * * * *", duration_s=6, min_score=6.0, max_candidates_per_run=5,
                template="flas", colors={"primary": "#d0021b", "accent": "#ffe600",
                                         "bg_gradient": ["#3a3a3a", "#141414"]},
                handle="@x", output_dir="out", enabled=True, language="tr")
    base.update(kw)
    return ChannelConfig(**base)


def test_channel_format_table():
    from short_bot.config import ReelConfig, VoiceConfig
    from short_bot.formats import channel_format
    assert channel_format(_cfg()) == "card"
    assert channel_format(_cfg(content_source="trends")) == "card"
    v = VoiceConfig(enabled=True, voice_id="v")
    assert channel_format(_cfg(voice=v)) == "voiced"
    assert channel_format(_cfg(content_source="trends", voice=v)) == "yorum"
    assert channel_format(_cfg(content_source="curated")) == "curated"
    # `reel.enabled` FORMAT BELİRLEMEZ: reel kanal formatı olmaktan çıktı
    # (canlıda 0 kanal). O blok artık yalnız kürate montaj ayarı taşır.
    assert channel_format(_cfg(reel=ReelConfig(enabled=True, voice_id="v"))) == "card"
    assert channel_format(_cfg(reel=ReelConfig(enabled=True, voice_id="v"),
                               content_source="curated")) == "curated"
    # Düzenleme yolu artık formata bakmıyor: dört format da /channels/<slug>/edit
    # rotasından çiziliyor, `edit_path`/`FORMAT_EDIT_SUFFIX` kalktı.


def test_format_spec_her_format_icin_var():
    """Dört canlı format kayıtlı; reel formatı yok (canlıda 0 kanal, kaldırıldı)."""
    from short_bot.formats import FORMATS, FormatSpec
    assert set(FORMATS) == {"card", "voiced", "yorum", "curated"}
    for spec in FORMATS.values():
        assert isinstance(spec, FormatSpec)


def test_format_spec_alanlari():
    from short_bot.formats import FORMATS
    yorum = FORMATS["yorum"]
    assert yorum.key == "yorum"
    assert yorum.label == "Gündem Yorum"
    assert yorum.glyph == "❝"
    assert yorum.body_template == "channels/_body_yorum.html.j2"


def test_ortak_cekirdek_her_formatta_ayni():
    """Ayrımın bütün noktası bu: kimlik/zamanlama/youtube/otomasyon TEK kümedir.

    Bugün böyle değildi ve ölçüldü: kürate kanalda gizlilik ve yükleme eşiği,
    kart kanalında credentials_from UI'de HİÇ yoktu."""
    from short_bot.formats import CORE_PARTIALS, FORMATS
    for spec in FORMATS.values():
        assert spec.core == CORE_PARTIALS
    assert "core/youtube" in CORE_PARTIALS


def test_format_labels_spec_ten_turetilir():
    """İki liste elle senkron tutulursa biri unutulur; FORMAT_LABELS türetilmiş olmalı."""
    from short_bot.formats import FORMAT_LABELS, FORMATS
    assert FORMAT_LABELS == {k: v.label for k, v in FORMATS.items()}


def _timeline():
    words = [TimedWord("a", 0.0, 0.4, 0), TimedWord("b", 0.5, 0.9, 0)]
    beats = [TimedBeat("36 SARSINTI", 2.0, 12.0), TimedBeat("BENCE HAZIRLIK", 12.0, 30.0)]
    return NarrationTimeline(words=words, beats=beats, duration_s=31.0, hook="h", loop_close="l")


def test_flas_narrator_template_renders_beats_ticker_and_seek(tmp_path):
    from short_bot.renderer import build_html
    script = Script(header_top="ADALAR", header_bottom="YİNE SALLANDI", photo_overlay="KANDİLLİ: 3.1",
                    body_paragraph="Adalar'da 3.1 büyüklüğünde deprem oldu. Gece boyu sürdü.",
                    highlights=[], category="Deprem", mood="breaking")
    job = RenderJob(script=script, bg_image_path=None, music_path=tmp_path / "m.mp3",
                    channel_colors={"primary": "#d0021b", "accent": "#ffe600",
                                    "bg_gradient": ["#3a3a3a", "#141414"]},
                    handle="@gundem", duration_s=31, rss_source="Milliyet",
                    narration=_timeline(), ticker_items=("Sırada bir",))
    html = build_html(job, Path("templates/flas-narrator.html.j2"))
    assert 'class="yellow card on" data-s="0" data-e="2.0"' in html and "KANDİLLİ: 3.1" in html
    assert 'data-s="2.0" data-e="12.0"' in html and "36 SARSINTI" in html and "BENCE HAZIRLIK" in html
    assert "window.__seek" in html and "const DURATION_S = 31.0" in html
    assert 'class="ticker"' in html and "Sırada bir" in html
    assert 'class="header"' in html and 'class="body-text"' in html and 'id="__progress"' in html


def test_voiced_yorum_uses_yorum_writer_with_extra_sources(tmp_path):
    from short_bot.config import VoiceConfig
    from short_bot.narration import Beat, Narration
    from short_bot.tts.cartesia_client import SynthesisResult
    from short_bot.voiced import VoicedDeps, produce_voiced_video
    ch = _cfg(content_source="trends",
              voice=VoiceConfig(enabled=True, provider="cartesia", voice_id="v", target_duration_s=(10, 60)))
    item = NewsItem(guid="g", title="t", link="https://a", source="A", pub_date=None, thumb_url=None,
                    description="Google Trends · 50.000 arama", trend_volume=50000,
                    extra_links=("https://b",))
    script = Script(header_top="A", header_bottom="B", photo_overlay="C",
                    body_paragraph="Gövde metni burada yeterince uzun olsun diye.", highlights=[],
                    category="D", mood="neutral")
    calls = {}
    narr = Narration(hook="Soru mu?", beats=[Beat(text="Bir cümle burada.", on_screen="BİR"),
                                            Beat(text="İki cümle burada.", on_screen="İKİ"),
                                            Beat(text="Üç cümle burada.", on_screen="ÜÇ")],
                     loop_close="Siz ne dersiniz?", mood="neutral")

    def _yorum(item_, body, **kw):
        calls["yorum"] = kw
        return narr

    def _plain(*a, **k):
        raise AssertionError("yorum kanalında düz anlatım yazarı çağrılmamalı")

    def _synth(text, **kw):
        p = tmp_path / "n.wav"
        p.write_bytes(b"\0" * 4096)
        return SynthesisResult(path=p, words=[], duration_s=5.0, chars_spent=len(text))

    def _render(job, tpl, frames_dir, **kw):
        calls["tpl"] = Path(tpl).name
        Path(frames_dir).mkdir(parents=True, exist_ok=True)

    deps = VoicedDeps(write_narration=_plain, write_yorum_narration=_yorum,
                      health_check=lambda **k: "healthy", synthesize=_synth,
                      probe_duration_s=lambda p, **k: 5.0, transcribe_words=lambda *a, **k: [],
                      render_frames=_render,
                      compose_video=lambda f, m, o, **k: Path(o).write_bytes(b"x"))
    produce_voiced_video(item=item, body="gövde", script=script, bg_image_path=None,
                         music_path=tmp_path / "m.mp3", channel=ch, templates_dir=Path("templates"),
                         work_dir=tmp_path / "w", out_path=tmp_path / "o.mp4", api_key="k",
                         deps=deps, extra_sources=[("https://b", "ek gövde")])
    assert calls["yorum"]["extra_sources"] == [("https://b", "ek gövde")]
    assert calls["tpl"] == "flas-narrator.html.j2"
    assert script.narration_text.startswith("Soru mu?")
