"""data_api fonksiyonlari proxied http kwarg destekler."""
from __future__ import annotations

from unittest.mock import patch, MagicMock


def test_fetch_video_stats_batch_with_http_uses_authorized_http():
    from short_bot.youtube import data_api
    fake_http = MagicMock(name="proxied_http")
    fake_creds = MagicMock(name="creds")

    with patch("short_bot.youtube.data_api.build") as mock_build, \
         patch("short_bot.youtube.data_api.AuthorizedHttp") as mock_authed:
        mock_authed.return_value = "AUTHED"
        mock_yt = MagicMock()
        mock_yt.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "v1", "statistics": {"viewCount": "10"}}],
        }
        mock_build.return_value = mock_yt
        out = data_api.fetch_video_stats_batch(
            fake_creds, ["v1"], http=fake_http,
        )
    assert out == {"v1": {"views": 10, "likes": 0, "comments": 0}}
    mock_authed.assert_called_once_with(fake_creds, http=fake_http)
    mock_build.assert_called_once_with("youtube", "v3", http="AUTHED")


def test_fetch_video_stats_batch_no_http_uses_credentials_directly():
    from short_bot.youtube import data_api
    fake_creds = MagicMock(name="creds")
    with patch("short_bot.youtube.data_api.build") as mock_build, \
         patch("short_bot.youtube.data_api.AuthorizedHttp") as mock_authed:
        mock_yt = MagicMock()
        mock_yt.videos.return_value.list.return_value.execute.return_value = {"items": []}
        mock_build.return_value = mock_yt
        data_api.fetch_video_stats_batch(fake_creds, ["v1"])
    mock_authed.assert_not_called()
    mock_build.assert_called_once_with("youtube", "v3", credentials=fake_creds)


def test_fetch_channel_stats_with_http_uses_authorized_http():
    from short_bot.youtube import data_api
    fake_http = MagicMock(name="proxied_http")
    fake_creds = MagicMock(name="creds")

    with patch("short_bot.youtube.data_api.build") as mock_build, \
         patch("short_bot.youtube.data_api.AuthorizedHttp") as mock_authed:
        mock_authed.return_value = "AUTHED"
        mock_yt = MagicMock()
        mock_yt.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "c1", "statistics": {
                "subscriberCount": "100", "viewCount": "5000",
            }}],
        }
        mock_build.return_value = mock_yt
        out = data_api.fetch_channel_stats(fake_creds, http=fake_http)
    assert out == {"channel_id": "c1", "subscribers": 100, "total_views": 5000}
    mock_authed.assert_called_once_with(fake_creds, http=fake_http)
    mock_build.assert_called_once_with("youtube", "v3", http="AUTHED")


def test_fetch_channel_stats_no_http_uses_credentials_directly():
    from short_bot.youtube import data_api
    fake_creds = MagicMock(name="creds")
    with patch("short_bot.youtube.data_api.build") as mock_build, \
         patch("short_bot.youtube.data_api.AuthorizedHttp") as mock_authed:
        mock_yt = MagicMock()
        mock_yt.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "c1", "statistics": {}}],
        }
        mock_build.return_value = mock_yt
        data_api.fetch_channel_stats(fake_creds)
    mock_authed.assert_not_called()
    mock_build.assert_called_once_with("youtube", "v3", credentials=fake_creds)
