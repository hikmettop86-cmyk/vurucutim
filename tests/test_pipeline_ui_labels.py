"""_resolve_ui_labels: DNA.ui_badge overrides locale 'breaking' label."""
from short_bot.pipeline import _resolve_ui_labels
from short_bot.config import ChannelConfig
from short_bot.dna import DnaSpec, DnaPalette, DnaFonts, DnaTone


def _channel_with_dna(language: str, ui_badge: str) -> ChannelConfig:
    dna = DnaSpec(
        archetype="newscast",
        palette=DnaPalette(primary="#8b1a3b", accent="#d4a574",
                           bg_gradient=["#fff1e6", "#f5d5c0"],
                           body_bg=["#fffaf5", "#fce4d6"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
        ui_badge=ui_badge,
    )
    return ChannelConfig(
        slug="t", name="T", keywords=[], rss_locale="hl=tr",
        schedule_cron="*", duration_s=6, min_score=6.0,
        max_candidates_per_run=1, template="newscast",
        colors={"primary": "#000", "accent": "#111", "bg_gradient": ["#000", "#111"]},
        handle="@t", output_dir="out",
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language=language, dna=dna, script_model=None,
        content_source="rss", generator=None,
    )


def test_ui_badge_overrides_breaking_when_set():
    cfg = _channel_with_dna(language="tr", ui_badge="❀ AŞK SÖZLERİ ❀")
    labels = _resolve_ui_labels(cfg)
    assert labels["breaking"] == "❀ AŞK SÖZLERİ ❀"
    # Other labels untouched
    assert labels["like"] == "BEĞEN"
    assert labels["subscribe"] == "ABONE OL"


def test_empty_ui_badge_keeps_locale_default():
    cfg = _channel_with_dna(language="tr", ui_badge="")
    labels = _resolve_ui_labels(cfg)
    assert labels["breaking"] == "SON DAKİKA"


def test_whitespace_only_ui_badge_keeps_locale_default():
    cfg = _channel_with_dna(language="en", ui_badge="   ")
    labels = _resolve_ui_labels(cfg)
    assert labels["breaking"] == "BREAKING"


def test_no_dna_keeps_locale_default():
    cfg = ChannelConfig(
        slug="t", name="T", keywords=["x"], rss_locale="hl=de",
        schedule_cron="*", duration_s=6, min_score=6.0,
        max_candidates_per_run=1, template="newscast",
        colors={"primary": "#000", "accent": "#111", "bg_gradient": ["#000", "#111"]},
        handle="@t", output_dir="out",
        enabled=True, cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language="de", dna=None, script_model=None,
        content_source="rss", generator=None,
    )
    labels = _resolve_ui_labels(cfg)
    assert labels["breaking"] == "EILMELDUNG"
