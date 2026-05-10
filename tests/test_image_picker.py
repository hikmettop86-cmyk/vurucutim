from pathlib import Path
from unittest.mock import patch, MagicMock

from short_bot.image_picker import (
    build_search_query,
    pick_image_for_script,
    build_search_query_for_channel,
    _Verdict,
)
from short_bot.image_search import ImageCandidate
from short_bot.models import Script, Highlight
from short_bot.config import ChannelConfig


def _script():
    return Script(
        header_top="ARA ZAM",
        header_bottom="AÇIKLAMASI",
        photo_overlay="İKTİDARDAN NET YANIT",
        body_paragraph="Sendikalar ara zam çağrısı yaptı, hükümetten açıklama bekleniyor.",
        highlights=[Highlight(text="ara zam çağrısı", color="yellow")],
        category="SİYASET",
        mood="breaking",
    )


def test_build_search_query_combines_header_and_category():
    q = build_search_query(_script())
    assert "ARA ZAM" in q
    assert "AÇIKLAMASI" in q
    assert "SİYASET" in q


def _cand(url, domain="example.com"):
    return ImageCandidate(url=url, title="t", source_domain=domain,
                          width=1200, height=800, thumbnail=None)


def test_pick_returns_first_accepted(tmp_path, monkeypatch):
    candidates = [_cand("https://example.com/a.jpg"),
                  _cand("https://example.com/b.jpg")]
    verdicts = [
        _Verdict(appropriate=False, reason="not relevant"),
        _Verdict(appropriate=True, reason="good match"),
    ]

    with patch("short_bot.image_picker.search_images", return_value=candidates), \
         patch("short_bot.image_picker._download", return_value=True), \
         patch("short_bot.image_picker._verify_with_claude", side_effect=verdicts):
        # Make the cache files exist so the path lookup returns them
        cache = tmp_path / "img"
        result = pick_image_for_script(_script(), cache, claude_path="claude")
    assert result is not None
    assert result.suffix == ".jpg"


def test_pick_returns_none_when_all_rejected(tmp_path):
    candidates = [_cand("https://example.com/a.jpg")]
    with patch("short_bot.image_picker.search_images", return_value=candidates), \
         patch("short_bot.image_picker._download", return_value=True), \
         patch("short_bot.image_picker._verify_with_claude",
               return_value=_Verdict(appropriate=False, reason="not relevant")):
        result = pick_image_for_script(_script(), tmp_path / "img", claude_path="claude")
    assert result is None


def test_pick_returns_none_on_no_candidates(tmp_path):
    with patch("short_bot.image_picker.search_images", return_value=[]), \
         patch("short_bot.wikimedia_search.search_images_commons", return_value=[]):
        result = pick_image_for_script(_script(), tmp_path / "img", claude_path="claude")
    assert result is None


def test_pick_uses_wikimedia_when_ddg_empty(tmp_path):
    wiki_cand = ImageCandidate(
        url="https://upload.wikimedia.org/test.jpg",
        title="t", source_domain="upload.wikimedia.org",
        width=1280, height=720, thumbnail=None,
    )
    with patch("short_bot.image_picker.search_images", return_value=[]), \
         patch("short_bot.wikimedia_search.search_images_commons", return_value=[wiki_cand]), \
         patch("short_bot.image_picker._download", return_value=True), \
         patch("short_bot.image_picker._verify_with_claude",
               return_value=_Verdict(appropriate=True, reason="good fit")):
        result = pick_image_for_script(_script(), tmp_path / "img", claude_path="claude")
    assert result is not None


def test_pick_skips_candidate_when_download_fails(tmp_path):
    candidates = [_cand("https://example.com/a.jpg"),
                  _cand("https://example.com/b.jpg")]
    with patch("short_bot.image_picker.search_images", return_value=candidates), \
         patch("short_bot.image_picker._download", side_effect=[False, True]), \
         patch("short_bot.image_picker._verify_with_claude",
               return_value=_Verdict(appropriate=True, reason="ok")):
        result = pick_image_for_script(_script(), tmp_path / "img", claude_path="claude")
    assert result is not None


def _channel_with_template(template_str=None):
    dna = None
    if template_str is not None:
        from short_bot.dna import DnaSpec, DnaPalette, DnaFonts, DnaTone
        dna = DnaSpec(
            archetype="stadium",
            palette=DnaPalette(primary="#000000", accent="#ffffff",
                               bg_gradient=["#000","#111"], body_bg=["#000","#111"]),
            fonts=DnaFonts(),
            tone=DnaTone(voice="x", style="y"),
            search_query_template=template_str,
            persona_summary="x",
        )
    return ChannelConfig(
        slug="t", name="T", keywords=[], rss_locale="hl=tr",
        schedule_cron="", duration_s=30, min_score=0,
        max_candidates_per_run=1, template="stadium" if dna else "newscast",
        colors={"primary":"#000","accent":"#fff","bg_gradient":["#000","#111"]},
        handle="@x", output_dir="x", enabled=True,
        cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language="tr", dna=dna,
    )


def test_build_search_query_uses_dna_template_when_present():
    ch = _channel_with_template("{header_top} {category} sports")
    q = build_search_query_for_channel(_script(), ch)
    assert "ARA ZAM" in q
    assert "SİYASET" in q
    assert "sports" in q


def test_build_search_query_default_when_no_dna():
    ch = _channel_with_template(None)
    q = build_search_query_for_channel(_script(), ch)
    assert "ARA ZAM" in q
    assert "AÇIKLAMASI" in q
    assert "SİYASET" in q


def test_pick_image_uses_channel_aware_query_when_channel_provided(tmp_path):
    ch = _channel_with_template("{header_top} ONLY")
    candidates = [_cand("https://example.com/a.jpg")]

    captured = {}
    def fake_search(query, **kwargs):
        captured["query"] = query
        return candidates

    with patch("short_bot.image_picker.search_images", side_effect=fake_search), \
         patch("short_bot.image_picker._download", return_value=True), \
         patch("short_bot.image_picker._verify_with_claude",
               return_value=_Verdict(appropriate=True, reason="ok")):
        pick_image_for_script(_script(), tmp_path / "img",
                              claude_path="claude", channel=ch)
    assert "ONLY" in captured["query"]
    assert "ARA ZAM" in captured["query"]   # header_top from _script()


def _channel_with_template_and_keywords(template_str: str, keywords: list[str]):
    """Helper that builds a channel with both DNA template and keywords."""
    from short_bot.dna import DnaSpec, DnaPalette, DnaFonts, DnaTone
    dna = DnaSpec(
        archetype="stadium",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000","#111"], body_bg=["#000","#111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        search_query_template=template_str,
        persona_summary="x",
    )
    return ChannelConfig(
        slug="t", name="T", keywords=keywords, rss_locale="hl=tr",
        schedule_cron="", duration_s=30, min_score=0,
        max_candidates_per_run=1, template="stadium",
        colors={"primary":"#000","accent":"#fff","bg_gradient":["#000","#111"]},
        handle="@x", output_dir="x", enabled=True,
        cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language="en", dna=dna,
    )


def test_build_search_query_dedupes_repeated_words():
    """Repeated words like 'NFL NFL NFL' are collapsed to a single 'NFL'."""
    # Template that, when expanded, repeats the category multiple times
    ch = _channel_with_template_and_keywords(
        "{header_top} {category} {category} football", keywords=[]
    )
    s = Script(
        header_top="NFL SCHEDULE DROPS", header_bottom="x",
        photo_overlay="x", body_paragraph="x"*30, highlights=[],
        category="NFL", mood="breaking",
    )
    q = build_search_query_for_channel(s, ch)
    # 'NFL' should appear exactly once after dedupe
    assert q.lower().count("nfl") == 1
    assert "schedule" in q.lower()
    assert "football" in q.lower()


def test_build_search_query_appends_channel_keywords_when_missing():
    """Channel keywords whose component words aren't in the query get appended."""
    ch = _channel_with_template_and_keywords(
        "{header_top} football", keywords=["nfl", "american football", "draft"]
    )
    s = Script(
        header_top="SCHEDULE", header_bottom="x", photo_overlay="x",
        body_paragraph="x"*30, highlights=[], category="x", mood="breaking",
    )
    q = build_search_query_for_channel(s, ch)
    # 'nfl' (single word, not in template) → appended
    assert "nfl" in q.lower()
    # 'american football' → 'football' is in template but 'american' is missing,
    # so 'american football' as a multi-word keyword is appended (not all
    # component words present)
    assert "american" in q.lower()
    # 'draft' → not in query → appended
    assert "draft" in q.lower()


def test_build_search_query_skips_keywords_whose_words_already_present():
    """Keyword skipped if ALL its component words are already in the query."""
    ch = _channel_with_template_and_keywords(
        "{header_top} {category} football", keywords=["football", "nfl"]
    )
    s = Script(
        header_top="SCHEDULE", header_bottom="x", photo_overlay="x",
        body_paragraph="x"*30, highlights=[], category="NFL", mood="breaking",
    )
    q = build_search_query_for_channel(s, ch)
    # 'football' keyword skipped (already in template); 'nfl' keyword skipped (in category)
    # Each only appears once
    assert q.lower().count("football") == 1
    assert q.lower().count("nfl") == 1


def test_build_search_query_max_3_keywords_appended():
    """Even if 5 keywords are configured, only first 3 are appended."""
    ch = _channel_with_template_and_keywords(
        "{header_top}", keywords=["one", "two", "three", "four", "five"]
    )
    s = Script(
        header_top="HEADER", header_bottom="x", photo_overlay="x",
        body_paragraph="x"*30, highlights=[], category="x", mood="breaking",
    )
    q = build_search_query_for_channel(s, ch)
    assert "one" in q.lower()
    assert "two" in q.lower()
    assert "three" in q.lower()
    assert "four" not in q.lower()
    assert "five" not in q.lower()
