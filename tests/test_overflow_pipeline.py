import logging
from unittest.mock import MagicMock, patch
from pathlib import Path

from short_bot.models import Highlight, NewsItem, Script
from short_bot.overflow import FieldOverflow, OverflowReport
from short_bot.pipeline import write_script_with_overflow_check


def _script(header="Short", body="x" * 30):
    return Script(
        header_top=header, header_bottom="B", photo_overlay="C",
        body_paragraph=body, category="X", mood="neutral", highlights=[],
    )


def _item():
    return NewsItem(
        guid="g", title="t", link="http://x",
        source=None, pub_date=None, thumb_url=None, description=None,
    )


def _fo(overflow=False, cur=10, rec=10):
    return FieldOverflow(
        name="header_top", has_overflow=overflow,
        current_chars=cur, current_lines=1,
        max_lines=2, recommended_max_chars=rec,
    )


def _clean_report():
    return OverflowReport(archetype="newscast",
                          fields={"header_top": _fo(False)})


def _bad_report():
    return OverflowReport(archetype="newscast",
                          fields={"header_top": _fo(True, cur=26, rec=14)})


def _channel():
    c = MagicMock()
    c.template = "newscast"
    c.language = "tr"
    c.colors = {"primary": "#cc0000", "accent": "#ffea3b",
                "bg_gradient": ["#1a1a2a", "#0a0a1a"]}
    c.handle = "@test"
    c.duration_s = 30
    return c


def test_clean_first_attempt_returns_immediately(tmp_path):
    log = logging.getLogger("test")
    s1 = _script("Short")

    with patch("short_bot.pipeline.write_script", return_value=s1) as ws, \
         patch("short_bot.pipeline.build_html", return_value="<html></html>"), \
         patch("short_bot.pipeline.check_overflow",
               return_value=_clean_report()):
        script, retries = write_script_with_overflow_check(
            item=_item(), body_html="b", channel=_channel(),
            template_path=Path("tpl.j2"),
            job_template_args={"music_path": Path("dummy.mp3"),
                               "ui_language": "tr"},
            max_retries=2, log=log,
        )

    assert script is s1
    assert retries == 0
    assert ws.call_count == 1


def test_overflow_then_clean_returns_v2(tmp_path):
    log = logging.getLogger("test")
    s1 = _script("Long Title Overflows")
    s2 = _script("Short")

    reports = [_bad_report(), _clean_report()]
    with patch("short_bot.pipeline.write_script", side_effect=[s1, s2]) as ws, \
         patch("short_bot.pipeline.build_html", return_value="<html></html>"), \
         patch("short_bot.pipeline.check_overflow",
               side_effect=reports):
        script, retries = write_script_with_overflow_check(
            item=_item(), body_html="b", channel=_channel(),
            template_path=Path("tpl.j2"),
            job_template_args={"music_path": Path("dummy.mp3"),
                               "ui_language": "tr"},
            max_retries=2, log=log,
        )

    assert script is s2
    assert retries == 1
    assert ws.call_count == 2


def test_three_overflows_falls_back_to_truncate(tmp_path):
    log = logging.getLogger("test")
    scripts = [_script("V1 long long"), _script("V2 long"), _script("V3 long")]
    reports = [_bad_report(), _bad_report(), _bad_report()]
    truncated = _script("V3")

    with patch("short_bot.pipeline.write_script", side_effect=scripts), \
         patch("short_bot.pipeline.build_html", return_value="<html></html>"), \
         patch("short_bot.pipeline.check_overflow", side_effect=reports), \
         patch("short_bot.pipeline.truncate_to_fit",
               return_value=truncated) as tt:
        script, retries = write_script_with_overflow_check(
            item=_item(), body_html="b", channel=_channel(),
            template_path=Path("tpl.j2"),
            job_template_args={"music_path": Path("dummy.mp3"),
                               "ui_language": "tr"},
            max_retries=2, log=log,
        )

    assert script is truncated
    assert retries == 3
    assert tt.call_count == 1


def test_playwright_exception_soft_falls_back_to_v1(tmp_path):
    log = logging.getLogger("test")
    s1 = _script("Whatever")

    with patch("short_bot.pipeline.write_script", return_value=s1), \
         patch("short_bot.pipeline.build_html", return_value="<html></html>"), \
         patch("short_bot.pipeline.check_overflow",
               side_effect=RuntimeError("playwright crash")):
        script, retries = write_script_with_overflow_check(
            item=_item(), body_html="b", channel=_channel(),
            template_path=Path("tpl.j2"),
            job_template_args={"music_path": Path("dummy.mp3"),
                               "ui_language": "tr"},
            max_retries=2, log=log,
        )

    assert script is s1
    assert retries == 0


def test_truncate_validation_failure_returns_last_script(tmp_path):
    """If truncate raises ValidationError or ValueError, log warning and
    return the last (still-overflowing) script — don't kill the pipeline."""
    log = logging.getLogger("test")
    scripts = [_script("V1"), _script("V2"), _script("V3")]
    reports = [_bad_report(), _bad_report(), _bad_report()]

    with patch("short_bot.pipeline.write_script", side_effect=scripts), \
         patch("short_bot.pipeline.build_html", return_value="<html></html>"), \
         patch("short_bot.pipeline.check_overflow", side_effect=reports), \
         patch("short_bot.pipeline.truncate_to_fit",
               side_effect=ValueError("validation")):
        script, retries = write_script_with_overflow_check(
            item=_item(), body_html="b", channel=_channel(),
            template_path=Path("tpl.j2"),
            job_template_args={"music_path": Path("dummy.mp3"),
                               "ui_language": "tr"},
            max_retries=2, log=log,
        )

    assert script is scripts[-1]   # v3 returned as-is
    assert retries == 3
