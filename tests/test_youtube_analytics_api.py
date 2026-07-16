from datetime import date
from unittest.mock import MagicMock, patch

from short_bot.youtube.analytics_api import fetch_video_analytics


def test_fetch_video_analytics_returns_metrics():
    fake_creds = MagicMock()
    with patch("short_bot.youtube.analytics_api.build") as mbuild:
        api = MagicMock(); mbuild.return_value = api
        api.reports.return_value.query.return_value.execute.return_value = {
            "columnHeaders": [
                {"name": "video"}, {"name": "views"}, {"name": "estimatedMinutesWatched"},
                {"name": "averageViewDuration"},
            ],
            "rows": [
                ["V1", 200, 30.0, 9.0],
                ["V2", 50, 5.0, 6.0],
            ],
        }
        start = date(2026, 5, 1); end = date(2026, 5, 4)
        result = fetch_video_analytics(fake_creds, start_date=start, end_date=end,
                                         video_ids=["V1", "V2"])
    assert result["V1"]["watch_time_min"] == 30.0
    assert result["V1"]["avg_view_duration_s"] == 9.0
    assert result["V2"]["watch_time_min"] == 5.0


def test_fetch_video_analytics_donusum_metrikleri():
    # Beğeni/abone teşhisi (2026-07-16): dönüşüm görünürlüğü için subscribersGained +
    # averageViewPercentage da çekilir. Gerçek API bu kombinasyonu video boyutuyla
    # destekliyor (canlı doğrulandı).
    fake_creds = MagicMock()
    with patch("short_bot.youtube.analytics_api.build") as mbuild:
        api = MagicMock(); mbuild.return_value = api
        api.reports.return_value.query.return_value.execute.return_value = {
            "columnHeaders": [
                {"name": "video"}, {"name": "views"},
                {"name": "estimatedMinutesWatched"}, {"name": "averageViewDuration"},
                {"name": "subscribersGained"}, {"name": "averageViewPercentage"},
            ],
            "rows": [["V1", 200, 30.0, 9.0, 3, 187.5]],
        }
        result = fetch_video_analytics(fake_creds,
                                         start_date=date(2026, 5, 1),
                                         end_date=date(2026, 5, 4),
                                         video_ids=["V1"])
        metrics_arg = api.reports.return_value.query.call_args.kwargs["metrics"]
    assert "subscribersGained" in metrics_arg
    assert "averageViewPercentage" in metrics_arg
    assert result["V1"]["subscribers_gained"] == 3
    assert result["V1"]["avg_view_percentage"] == 187.5


def test_fetch_video_analytics_eski_yanit_yeni_alanlari_sifirlar():
    # Sütun yoksa (eski mock/eski API yanıtı) yeni alanlar 0 — KeyError değil.
    fake_creds = MagicMock()
    with patch("short_bot.youtube.analytics_api.build") as mbuild:
        api = MagicMock(); mbuild.return_value = api
        api.reports.return_value.query.return_value.execute.return_value = {
            "columnHeaders": [{"name": "video"}, {"name": "views"}],
            "rows": [["V1", 200]],
        }
        result = fetch_video_analytics(fake_creds,
                                         start_date=date(2026, 5, 1),
                                         end_date=date(2026, 5, 4),
                                         video_ids=["V1"])
    assert result["V1"]["subscribers_gained"] == 0
    assert result["V1"]["avg_view_percentage"] == 0.0


def test_fetch_video_analytics_handles_no_rows():
    fake_creds = MagicMock()
    with patch("short_bot.youtube.analytics_api.build") as mbuild:
        api = MagicMock(); mbuild.return_value = api
        api.reports.return_value.query.return_value.execute.return_value = {
            "columnHeaders": [{"name": "video"}, {"name": "views"}],
        }
        result = fetch_video_analytics(fake_creds,
                                         start_date=date(2026, 5, 1),
                                         end_date=date(2026, 5, 4),
                                         video_ids=["V1"])
    assert result == {}


def test_fetch_video_analytics_handles_empty_video_list():
    fake_creds = MagicMock()
    result = fetch_video_analytics(fake_creds,
                                     start_date=date(2026, 5, 1),
                                     end_date=date(2026, 5, 4),
                                     video_ids=[])
    assert result == {}
