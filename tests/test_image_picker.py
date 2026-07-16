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
         patch("short_bot.wikimedia_search.search_images_commons", return_value=[]), \
         patch("short_bot.pexels.search_photos", return_value=[]):
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


# ---- Verdict.is_safe + last-resort fallback ----

def test_verdict_defaults_is_safe_to_false():
    """When Claude's response omits is_safe (older prompt format), default
    to False so last-resort fallback only accepts images Claude explicitly
    declared safe."""
    v = _Verdict(appropriate=False, reason="x")
    assert v.is_safe is False


def test_verdict_parses_is_safe_from_claude_response():
    v = _Verdict(appropriate=False, reason="x", is_safe=True)
    assert v.is_safe is True


def test_pick_returns_last_resort_safe_when_all_appropriate_rejected(tmp_path):
    """When NO source returns an appropriate image but at least one returns
    is_safe=true, pipeline gets that image (better than no video). This
    fixes the Putin/savaş case: DDG returned thematic but not exact-match
    images (Russian flag, Kremlin) — old behavior rejected all → no video.
    New behavior keeps the first safe one as last-resort fallback."""
    cand_a = _cand("https://example.com/a.jpg")
    cand_b = _cand("https://example.com/b.jpg")
    # Pad verdicts because the source-by-source loop may re-verify cached
    # candidates from later sources (DDG ASCII / header / Wikimedia /
    # Pexels in production differ, but in this test search_images returns
    # the same pair for every source).
    pad = _Verdict(appropriate=False, is_safe=False, reason="repeat reject")
    verdicts = [
        _Verdict(appropriate=False, is_safe=False, reason="absurd cat"),
        _Verdict(appropriate=False, is_safe=True, reason="thematic russian flag"),
    ] + [pad] * 50
    with patch("short_bot.image_picker.search_images", return_value=[cand_a, cand_b]), \
         patch("short_bot.wikimedia_search.search_images_commons", return_value=[]), \
         patch("short_bot.pexels.search_photos", return_value=[]), \
         patch("short_bot.image_picker._download", return_value=True), \
         patch("short_bot.image_picker._verify_with_claude", side_effect=verdicts):
        result = pick_image_for_script(_script(), tmp_path / "img", claude_path="claude")
    assert result is not None, "last-resort safe candidate should be returned"


def test_pick_prefers_appropriate_over_last_resort_safe(tmp_path):
    """When both appropriate and safe-only candidates exist, the appropriate
    one wins regardless of order."""
    cand_a = _cand("https://example.com/a.jpg")
    cand_b = _cand("https://example.com/b.jpg")
    verdicts = [
        _Verdict(appropriate=False, is_safe=True, reason="thematic only"),
        _Verdict(appropriate=True, is_safe=True, reason="exact match"),
    ]
    with patch("short_bot.image_picker.search_images", return_value=[cand_a, cand_b]), \
         patch("short_bot.wikimedia_search.search_images_commons", return_value=[]), \
         patch("short_bot.pexels.search_photos", return_value=[]), \
         patch("short_bot.image_picker._download", return_value=True), \
         patch("short_bot.image_picker._verify_with_claude", side_effect=verdicts):
        result = pick_image_for_script(_script(), tmp_path / "img", claude_path="claude")
    assert result is not None
    # second candidate (the appropriate one) wins
    assert result.name.startswith(
        __import__("hashlib").sha1(cand_b.url.encode()).hexdigest()[:16]
    )


def test_pick_returns_none_when_all_unsafe(tmp_path):
    """All rejected AND no is_safe=true → still None (no video over bad video)."""
    cand_a = _cand("https://example.com/a.jpg")
    with patch("short_bot.image_picker.search_images", return_value=[cand_a]), \
         patch("short_bot.wikimedia_search.search_images_commons", return_value=[]), \
         patch("short_bot.pexels.search_photos", return_value=[]), \
         patch("short_bot.image_picker._download", return_value=True), \
         patch("short_bot.image_picker._verify_with_claude",
               return_value=_Verdict(appropriate=False, is_safe=False, reason="bad")):
        result = pick_image_for_script(_script(), tmp_path / "img", claude_path="claude")
    assert result is None


def test_verify_with_claude_prompt_signals_loose_matching_and_dual_axis():
    """Probe the prompt sent to Claude (without invoking the real CLI).
    It must encourage loose/thematic matching AND ask for is_safe field."""
    from short_bot.image_picker import _verify_with_claude
    captured = {}

    def fake_run_json(prompt, schema, **kw):
        captured["prompt"] = prompt
        return _Verdict(appropriate=True, is_safe=True, reason="ok")

    with patch("short_bot.image_picker.run_json", side_effect=fake_run_json):
        _verify_with_claude(Path("/tmp/x.jpg"), _script(), "claude")

    p = captured["prompt"]
    assert "is_safe" in p, "prompt must request is_safe field"
    assert "appropriate" in p, "prompt must request appropriate field"
    # loose/thematic signal — at least one of these phrases
    pl = p.lower()
    assert any(s in pl for s in ("tema", "thematic", "gevşek", "loose")), \
        "prompt must signal loose thematic matching"


# ---- Verdict.has_text_overlay (burned-in news-graphic hard reject) ---------

def test_verdict_defaults_has_text_overlay_to_false():
    """Older verdicts (pre-feature) must not be retroactively rejected."""
    v = _Verdict(appropriate=True, reason="x")
    assert v.has_text_overlay is False


def test_verdict_parses_has_text_overlay_from_claude_response():
    v = _Verdict(appropriate=False, reason="x", has_text_overlay=True)
    assert v.has_text_overlay is True


def test_pick_rejects_text_overlay_even_if_appropriate(tmp_path):
    """A burned-in 'ATEŞKES 15 GÜN' news card that matches the theme of a
    '45 GÜN' story must be REJECTED — text overlay contradicts our script.
    Hard reject overrides appropriate=True."""
    cand_a = _cand("https://example.com/a.jpg")
    cand_b = _cand("https://example.com/b.jpg")
    # First candidate: appropriate=True BUT has burned-in text → skip
    # Second candidate: clean photo, appropriate=True → accept
    verdicts = [
        _Verdict(appropriate=True, is_safe=True,
                 has_text_overlay=True, reason="haber kartı, 15 gün yazıyor"),
        _Verdict(appropriate=True, is_safe=True,
                 has_text_overlay=False, reason="temiz fotoğraf"),
    ]
    with patch("short_bot.image_picker.search_images",
               return_value=[cand_a, cand_b]), \
         patch("short_bot.image_picker._download", return_value=True), \
         patch("short_bot.image_picker._verify_with_claude", side_effect=verdicts):
        result = pick_image_for_script(_script(), tmp_path / "img", claude_path="claude")
    assert result is not None
    assert result.name.endswith(".jpg")
    # We expect the SECOND candidate's hash (b.jpg url) to be the result, not
    # the first. Verify by checking that the file path differs.
    import hashlib
    expected_key = hashlib.sha1(cand_b.url.encode("utf-8")).hexdigest()[:16]
    assert result.name == f"{expected_key}.jpg"


def test_pick_text_overlay_does_not_become_last_resort_safe(tmp_path):
    """Even when appropriate fails everywhere, a text-overlay image must NOT
    be promoted to the last-resort fallback path. has_text_overlay > is_safe."""
    cand = _cand("https://example.com/a.jpg")
    # is_safe=True but has_text_overlay=True → should be hard-rejected,
    # NOT saved as last-resort, returns None overall.
    verdict = _Verdict(appropriate=False, is_safe=True,
                       has_text_overlay=True, reason="news graphic card")
    with patch("short_bot.image_picker.search_images", return_value=[cand]), \
         patch("short_bot.wikimedia_search.search_images_commons", return_value=[]), \
         patch("short_bot.pexels.search_photos", return_value=[]), \
         patch("short_bot.image_picker._download", return_value=True), \
         patch("short_bot.image_picker._verify_with_claude", return_value=verdict):
        result = pick_image_for_script(_script(), tmp_path / "img", claude_path="claude")
    assert result is None


def test_verify_prompt_requests_has_text_overlay_field():
    """Prompt must instruct Claude to evaluate burned-in headline graphics."""
    from short_bot.image_picker import _verify_with_claude
    captured = {}
    def fake_run_json(prompt, schema, **kw):
        captured["prompt"] = prompt
        return _Verdict(appropriate=True, is_safe=True,
                        has_text_overlay=False, reason="ok")
    with patch("short_bot.image_picker.run_json", side_effect=fake_run_json):
        _verify_with_claude(Path("/tmp/x.jpg"), _script(), "claude")
    p = captured["prompt"]
    assert "has_text_overlay" in p
    # examples of news-graphic cues
    pl = p.lower()
    assert any(s in pl for s in ("burned", "banner", "başlık", "kart"))


def test_verify_forwards_backend_and_image_path(tmp_path):
    from short_bot.image_picker import _verify_with_claude
    img = tmp_path / "x.jpg"
    img.write_bytes(b"jpeg")
    captured = {}
    def fake_run_json(prompt, schema, **kw):
        captured["prompt"] = prompt
        captured.update(kw)
        return _Verdict(appropriate=True, is_safe=True, reason="ok")
    with patch("short_bot.image_picker.run_json", side_effect=fake_run_json):
        _verify_with_claude(img, _script(), "claude",
                            backend="openrouter", api_key="k", model="g")
    assert captured["backend"] == "openrouter"
    assert captured["api_key"] == "k"
    assert captured["model"] == "g"
    assert captured["image_path"] == img
    assert not captured["prompt"].lstrip().startswith("@")


def test_pick_image_forwards_vision_params(tmp_path):
    cand = _cand("https://example.com/a.jpg")
    captured = {}
    def fake_verify(path, script, claude_path, **kw):
        captured.update(kw)
        return _Verdict(appropriate=True, is_safe=True, reason="ok")
    with patch("short_bot.image_picker.search_images", return_value=[cand]), \
         patch("short_bot.image_picker._download", return_value=True), \
         patch("short_bot.image_picker._verify_with_claude", side_effect=fake_verify):
        pick_image_for_script(_script(), tmp_path / "img", claude_path="claude",
                              backend="openrouter", api_key="k", model="g")
    assert captured["backend"] == "openrouter"
    assert captured["api_key"] == "k"
    assert captured["model"] == "g"
