from pathlib import Path

import pytest

from short_bot.models import RenderJob, Script
from short_bot.narration import NarrationTimeline, TimedBeat, TimedWord
from short_bot.renderer import _total_frames, build_html


def _script():
    return Script(
        header_top="FAIZ KARARI", header_bottom="MERKEZ BANKASI",
        photo_overlay="BES PUAN INDI",
        body_paragraph="Merkez bankasi faizi bes puan indirdi ve piyasalar sasirdi.",
        highlights=[], category="Ekonomi", mood="breaking",
    )


def _timeline():
    return NarrationTimeline(
        words=[
            TimedWord(word="Neden", start_s=0.0, end_s=0.4, seg=0),
            TimedWord(word="sasirdi", start_s=0.4, end_s=1.0, seg=0),
            TimedWord(word="Faiz", start_s=1.0, end_s=1.5, seg=1),
        ],
        beats=[TimedBeat(on_screen="FAIZ INDIRIMI", start_s=1.0, end_s=1.5)],
        duration_s=2.0, hook="Neden sasirdi?", loop_close="Iste bu yuzden.",
    )


def _job(narration=None, duration_s=6):
    return RenderJob(
        script=_script(), bg_image_path=None, music_path=Path("m.mp3"),
        channel_colors={"primary": "#b91c1c", "accent": "#ffea3b",
                        "bg_gradient": ["#2a3a5e", "#11182f"]},
        handle="@test", duration_s=duration_s, narration=narration,
    )


def test_render_job_narration_defaults_to_none():
    assert _job().narration is None


def test_total_frames_uses_duration_s_without_narration():
    assert _total_frames(_job(duration_s=6), fps=30) == 180


def test_total_frames_uses_narration_duration_when_present():
    assert _total_frames(_job(narration=_timeline()), fps=30) == 60   # 2.0s * 30


def test_narrator_template_embeds_words_and_seek():
    tpl = Path("templates/narrator.html.j2")
    html = build_html(_job(narration=_timeline()), tpl)

    assert "__seek" in html                    # renderer'in cagirdigi fonksiyon
    assert 'data-s="0.0"' in html              # kelime baslangic zamani
    assert "Neden" in html and "sasirdi" in html
    assert "FAIZ INDIRIMI" in html             # beat karti
    assert "Iste bu yuzden." in html           # loop kapanisi


def test_legacy_template_ignores_narration():
    """Sessiz sablonlar narration degiskenini gormezden gelir (regresyon yok)."""
    html = build_html(_job(), Path("templates/newscast.html.j2"))
    assert "FAIZ KARARI" in html


@pytest.mark.slow
def test_render_frames_voiced_counts_frames(tmp_path):
    from short_bot.renderer import render_frames
    n = render_frames(_job(narration=_timeline()),
                      Path("templates/narrator.html.j2"), tmp_path, fps=10)
    assert n == 20                              # 2.0s * 10fps
    assert len(list(tmp_path.glob("frame_*.png"))) == 20
