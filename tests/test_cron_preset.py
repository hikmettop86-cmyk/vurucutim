import pytest
from short_bot.web.cron_preset import preset_to_cron, cron_to_preset


def test_hourly():
    assert preset_to_cron("hourly") == "0 * * * *"


def test_every_2h():
    assert preset_to_cron("every_2h") == "0 */2 * * *"


def test_daily_with_hour():
    assert preset_to_cron("daily_09") == "0 9 * * *"
    assert preset_to_cron("daily_14") == "0 14 * * *"
    assert preset_to_cron("daily_00") == "0 0 * * *"


def test_weekly_with_day_and_hour():
    assert preset_to_cron("weekly_1_09") == "0 9 * * 1"
    assert preset_to_cron("weekly_5_18") == "0 18 * * 5"


def test_custom_returns_none():
    assert preset_to_cron("custom") is None


def test_invalid_preset_returns_none():
    assert preset_to_cron("garbage") is None
    assert preset_to_cron("daily_25") is None
    assert preset_to_cron("weekly_8_09") is None


def test_round_trip_known_strings():
    assert cron_to_preset("0 * * * *") == "hourly"
    assert cron_to_preset("0 */2 * * *") == "every_2h"
    assert cron_to_preset("0 9 * * *") == "daily_09"
    assert cron_to_preset("0 18 * * 5") == "weekly_5_18"


def test_unknown_cron_string_is_custom():
    assert cron_to_preset("0 8,14,20 * * *") == "custom"
    assert cron_to_preset("*/15 * * * *") == "custom"


def test_every_10min():
    assert preset_to_cron("every_10min") == "*/10 * * * *"


def test_every_30min():
    assert preset_to_cron("every_30min") == "*/30 * * * *"


def test_every_10min_round_trip():
    assert cron_to_preset("*/10 * * * *") == "every_10min"


def test_every_30min_round_trip():
    assert cron_to_preset("*/30 * * * *") == "every_30min"


def test_every_4h():
    assert preset_to_cron("every_4h") == "0 */4 * * *"


def test_every_4h_round_trip():
    assert cron_to_preset("0 */4 * * *") == "every_4h"
