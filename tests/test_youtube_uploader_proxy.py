"""upload_video respects proxied http when given."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock


def test_upload_video_with_http_uses_authorized_http(tmp_path):
    from short_bot.youtube import uploader
    fake_http = MagicMock(name="proxied_http")
    fake_creds = MagicMock(name="creds")
    file = tmp_path / "video.mp4"
    file.write_bytes(b"\x00" * 16)

    with patch("short_bot.youtube.uploader.build") as mock_build, \
         patch("short_bot.youtube.uploader.AuthorizedHttp") as mock_authed, \
         patch("short_bot.youtube.uploader.MediaFileUpload"):
        mock_authed.return_value = "AUTHED"
        mock_req = MagicMock()
        mock_req.next_chunk.return_value = (None, {"id": "VID123"})
        mock_build.return_value.videos.return_value.insert.return_value = mock_req

        out = uploader.upload_video(
            credentials=fake_creds, file_path=file,
            snippet={"title": "t"}, status={"privacyStatus": "public"},
            http=fake_http,
        )

    assert out == "VID123"
    mock_authed.assert_called_once_with(fake_creds, http=fake_http)
    mock_build.assert_called_once_with("youtube", "v3", http="AUTHED")


def test_upload_video_without_http_uses_credentials_directly(tmp_path):
    """Backward-compat."""
    from short_bot.youtube import uploader
    fake_creds = MagicMock(name="creds")
    file = tmp_path / "video.mp4"
    file.write_bytes(b"\x00" * 16)

    with patch("short_bot.youtube.uploader.build") as mock_build, \
         patch("short_bot.youtube.uploader.AuthorizedHttp") as mock_authed, \
         patch("short_bot.youtube.uploader.MediaFileUpload"):
        mock_req = MagicMock()
        mock_req.next_chunk.return_value = (None, {"id": "VID999"})
        mock_build.return_value.videos.return_value.insert.return_value = mock_req
        out = uploader.upload_video(
            credentials=fake_creds, file_path=file,
            snippet={"title": "t"}, status={"privacyStatus": "public"},
        )
    assert out == "VID999"
    mock_authed.assert_not_called()
    mock_build.assert_called_once_with("youtube", "v3", credentials=fake_creds)
