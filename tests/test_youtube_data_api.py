from unittest.mock import MagicMock, patch
from short_bot.youtube.data_api import (
    fetch_video_stats_batch, fetch_channel_stats,
)


def test_fetch_video_stats_batch_returns_dict_keyed_by_video_id():
    fake_creds = MagicMock()
    with patch("short_bot.youtube.data_api.build") as mbuild:
        api = MagicMock(); mbuild.return_value = api
        api.videos.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "V1", "statistics": {"viewCount": "100", "likeCount": "5", "commentCount": "1"}},
                {"id": "V2", "statistics": {"viewCount": "200", "likeCount": "10", "commentCount": "3"}},
            ]
        }
        result = fetch_video_stats_batch(fake_creds, video_ids=["V1", "V2"])
    assert result["V1"]["views"] == 100
    assert result["V1"]["likes"] == 5
    assert result["V2"]["comments"] == 3


def test_fetch_video_stats_batch_chunks_over_50():
    fake_creds = MagicMock()
    with patch("short_bot.youtube.data_api.build") as mbuild:
        api = MagicMock(); mbuild.return_value = api
        api.videos.return_value.list.return_value.execute.side_effect = [
            {"items": [{"id": f"V{i}", "statistics": {"viewCount": "1", "likeCount": "0", "commentCount": "0"}}
                        for i in range(50)]},
            {"items": [{"id": f"V{i}", "statistics": {"viewCount": "1", "likeCount": "0", "commentCount": "0"}}
                        for i in range(50, 75)]},
        ]
        ids = [f"V{i}" for i in range(75)]
        result = fetch_video_stats_batch(fake_creds, video_ids=ids)
    assert len(result) == 75
    assert api.videos.return_value.list.call_count == 2


def test_fetch_video_stats_batch_handles_empty_list():
    fake_creds = MagicMock()
    result = fetch_video_stats_batch(fake_creds, video_ids=[])
    assert result == {}


def test_fetch_channel_stats_returns_subs_and_views():
    fake_creds = MagicMock()
    with patch("short_bot.youtube.data_api.build") as mbuild:
        api = MagicMock(); mbuild.return_value = api
        api.channels.return_value.list.return_value.execute.return_value = {
            "items": [{
                "id": "UC1",
                "statistics": {"subscriberCount": "1500", "viewCount": "500000"},
            }]
        }
        result = fetch_channel_stats(fake_creds)
    assert result["subscribers"] == 1500
    assert result["total_views"] == 500000
    assert result["channel_id"] == "UC1"


def test_fetch_channel_stats_returns_none_when_no_items():
    fake_creds = MagicMock()
    with patch("short_bot.youtube.data_api.build") as mbuild:
        api = MagicMock(); mbuild.return_value = api
        api.channels.return_value.list.return_value.execute.return_value = {"items": []}
        assert fetch_channel_stats(fake_creds) is None
