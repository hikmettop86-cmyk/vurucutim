"""flas arketipi: kayıt, şablon sözleşmesi, ticker_items akışı."""
from __future__ import annotations

from pathlib import Path

from short_bot.models import NewsItem, RenderJob, ScoredItem, Script


def _script():
    return Script(header_top="ADALAR", header_bottom="YİNE SALLANDI",
                  body_paragraph="Kandilli'ye göre Adalar'da 3.1 büyüklüğünde deprem oldu. "
                                 "Sarsıntı 11 km derinlikte meydana geldi.",
                  highlights=[{"text": "3.1 büyüklüğünde deprem", "color": "yellow"}], category="Deprem",
                  photo_overlay="3.1 büyüklüğünde sarsıntı", mood="breaking")


def test_flas_registered_as_designed_archetype():
    from short_bot.dna import ARCHETYPES, ARCHETYPE_DEFAULTS
    from short_bot.templates_config import ARCHETYPE_OVERFLOW_FIELDS
    assert "flas" in ARCHETYPES
    assert ARCHETYPE_DEFAULTS["flas"]["font_headline"] == "Oswald"
    selectors = {f.selector for f in ARCHETYPE_OVERFLOW_FIELDS["flas"]}
    assert {".header .top", ".header .bot", ".yellow", ".body-text"} <= selectors


def test_render_job_ticker_items_defaults_empty(tmp_path):
    job = RenderJob(script=_script(), bg_image_path=None, music_path=tmp_path / "m.mp3",
                    channel_colors={"primary": "#d0021b", "accent": "#ffe600",
                                    "bg_gradient": ["#141414", "#0e0e0e"]},
                    handle="@gundem", duration_s=6)
    assert job.ticker_items == ()


def test_flas_template_renders_ticker_and_contract_selectors(tmp_path):
    from short_bot.renderer import build_html
    job = RenderJob(script=_script(), bg_image_path=None, music_path=tmp_path / "m.mp3",
                    channel_colors={"primary": "#d0021b", "accent": "#ffe600",
                                    "bg_gradient": ["#141414", "#0e0e0e"]},
                    handle="@gundem", duration_s=6, rss_source="Sözcü",
                    ticker_items=("Asgari ücrete ara zam", "Demirovic için teklif"))
    html = build_html(job, Path("templates/flas.html.j2"))
    for needle in ('class="header"', 'class="top"', 'class="bot"', 'class="yellow"',
                   'class="body-text"', 'class="ticker"', "Asgari ücrete ara zam",
                   "Demirovic için teklif", "Sırada", "SON DAKİKA", "Sözcü"):
        assert needle in html, needle


def test_flas_template_hides_ticker_when_empty(tmp_path):
    from short_bot.renderer import build_html
    job = RenderJob(script=_script(), bg_image_path=None, music_path=tmp_path / "m.mp3",
                    channel_colors={"primary": "#d0021b", "accent": "#ffe600",
                                    "bg_gradient": ["#141414", "#0e0e0e"]},
                    handle="@gundem", duration_s=6)
    html = build_html(job, Path("templates/flas.html.j2"))
    assert 'class="ticker"' not in html


def test_ticker_items_from_scored_excludes_picked_and_orders_by_volume():
    from short_bot.pipeline import _ticker_items_for_trends

    def _s(guid, title, score, volume):
        item = NewsItem(guid=guid, title=title, link=guid, source=None, pub_date=None,
                        thumb_url=None, description=None, trend_volume=volume)
        return ScoredItem(item=item, score=score, reasoning="")
    picked = _s("p", "Seçilen", 9.0, 50000)
    scored = [picked,
              _s("a", "Düşük hacim ama olay", 8.0, 2000),
              _s("b", "Yüksek hacim olay", 7.0, 20000),
              _s("c", "Hava durumu (kapıda elendi)", 2.0, 500000),
              _s("d", "Orta", 6.5, 5000)]
    out = _ticker_items_for_trends(scored, picked, min_score=6.0, limit=3)
    assert out == ("Yüksek hacim olay", "Orta", "Düşük hacim ama olay")
