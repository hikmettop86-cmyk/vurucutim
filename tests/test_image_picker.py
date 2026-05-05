from pathlib import Path
from unittest.mock import patch, MagicMock

from short_bot.image_picker import (
    build_search_query,
    pick_image_for_script,
    _Verdict,
)
from short_bot.image_search import ImageCandidate
from short_bot.models import Script, Highlight


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
    with patch("short_bot.image_picker.search_images", return_value=[]):
        result = pick_image_for_script(_script(), tmp_path / "img", claude_path="claude")
    assert result is None


def test_pick_skips_candidate_when_download_fails(tmp_path):
    candidates = [_cand("https://example.com/a.jpg"),
                  _cand("https://example.com/b.jpg")]
    with patch("short_bot.image_picker.search_images", return_value=candidates), \
         patch("short_bot.image_picker._download", side_effect=[False, True]), \
         patch("short_bot.image_picker._verify_with_claude",
               return_value=_Verdict(appropriate=True, reason="ok")):
        result = pick_image_for_script(_script(), tmp_path / "img", claude_path="claude")
    assert result is not None
