from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest

from short_bot.youtube.auto_upload import should_auto_upload, AutoUploadDecision


def _channel(auto=True, min_score=8.0):
    c = MagicMock()
    c.youtube = MagicMock(auto_upload=auto, min_score_for_upload=min_score)
    return c


def test_decline_when_youtube_block_missing():
    c = MagicMock(); c.youtube = None
    d = should_auto_upload(channel=c, picked_score=10.0,
                            last_upload_at=None, cooldown_minutes=5)
    assert d.eligible is False


def test_decline_when_auto_upload_off():
    d = should_auto_upload(channel=_channel(auto=False), picked_score=10.0,
                            last_upload_at=None, cooldown_minutes=5)
    assert d.eligible is False


def test_decline_when_score_below_threshold():
    d = should_auto_upload(channel=_channel(min_score=8.0), picked_score=7.5,
                            last_upload_at=None, cooldown_minutes=5)
    assert d.eligible is False
    assert "skor" in d.reason.lower() or "score" in d.reason.lower()


def test_accept_when_score_meets_threshold():
    d = should_auto_upload(channel=_channel(min_score=8.0), picked_score=8.0,
                            last_upload_at=None, cooldown_minutes=5)
    assert d.eligible is True


def test_score_threshold_zero_means_no_filter():
    d = should_auto_upload(channel=_channel(min_score=0.0), picked_score=0.5,
                            last_upload_at=None, cooldown_minutes=5)
    assert d.eligible is True


def test_decline_during_cooldown():
    last = datetime.now(timezone.utc) - timedelta(minutes=2)
    d = should_auto_upload(channel=_channel(min_score=8.0), picked_score=9.0,
                            last_upload_at=last, cooldown_minutes=5)
    assert d.eligible is False
    assert "cooldown" in d.reason.lower() or "soğuma" in d.reason.lower() or "bekle" in d.reason.lower()


def test_accept_after_cooldown():
    last = datetime.now(timezone.utc) - timedelta(minutes=10)
    d = should_auto_upload(channel=_channel(min_score=8.0), picked_score=9.0,
                            last_upload_at=last, cooldown_minutes=5)
    assert d.eligible is True


def test_generator_mode_no_score_always_eligible_when_auto_on():
    d = should_auto_upload(channel=_channel(min_score=8.0), picked_score=None,
                            last_upload_at=None, cooldown_minutes=5)
    assert d.eligible is True
