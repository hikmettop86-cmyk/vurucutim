from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.youtube.uploader import upload_video, build_snippet, build_status


def test_build_snippet_combines_header_and_body():
    snippet = build_snippet(
        header_top="İPLER KOPTU!",
        header_bottom="CANLI YAYINDA",
        body_paragraph="Detaylar şokta.",
        handle="@galatasaray",
        keywords=["spor", "futbol"],
        category_id="24",
    )
    assert snippet["title"] == "İPLER KOPTU! | CANLI YAYINDA"
    assert "Detaylar şokta." in snippet["description"]
    assert "#shorts" in snippet["description"]
    assert "@galatasaray" in snippet["description"]
    assert snippet["tags"] == ["spor", "futbol"]
    assert snippet["categoryId"] == "24"


def test_build_snippet_truncates_long_title():
    snippet = build_snippet(
        header_top="Çok uzun başlık" * 10,
        header_bottom="alt",
        body_paragraph="x" * 50, handle="@x", keywords=[], category_id="24",
    )
    assert len(snippet["title"]) <= 100


def test_build_status_with_ai_flag():
    s = build_status(privacy_status="public", ai_content=True)
    assert s["privacyStatus"] == "public"
    assert s["containsSyntheticMedia"] is True
    assert s["selfDeclaredMadeForKids"] is False


def test_build_status_without_ai_flag():
    s = build_status(privacy_status="unlisted", ai_content=False)
    assert s["privacyStatus"] == "unlisted"
    assert "containsSyntheticMedia" not in s


def test_upload_video_returns_video_id(tmp_path):
    fake_mp4 = tmp_path / "v.mp4"
    fake_mp4.write_bytes(b"\x00" * 1024)
    fake_creds = MagicMock()

    with patch("short_bot.youtube.uploader.build") as mbuild, \
         patch("short_bot.youtube.uploader.MediaFileUpload") as mmf:
        api = MagicMock()
        mbuild.return_value = api
        request = MagicMock()
        request.next_chunk.side_effect = [(None, {"id": "VID123"})]
        api.videos.return_value.insert.return_value = request

        video_id = upload_video(
            credentials=fake_creds, file_path=fake_mp4,
            snippet={"title": "T", "description": "D", "tags": [], "categoryId": "24"},
            status={"privacyStatus": "public"},
        )
    assert video_id == "VID123"


def test_upload_video_retries_on_resumable_error(tmp_path):
    from googleapiclient.errors import ResumableUploadError
    fake_mp4 = tmp_path / "v.mp4"
    fake_mp4.write_bytes(b"\x00" * 1024)
    fake_creds = MagicMock()

    with patch("short_bot.youtube.uploader.build") as mbuild, \
         patch("short_bot.youtube.uploader.MediaFileUpload"):
        api = MagicMock()
        mbuild.return_value = api
        bad_resp = MagicMock(); bad_resp.status = 500; bad_resp.reason = "x"
        request_first = MagicMock()
        request_first.next_chunk.side_effect = ResumableUploadError(bad_resp, b"err")
        request_ok = MagicMock()
        request_ok.next_chunk.return_value = (None, {"id": "VID999"})
        api.videos.return_value.insert.side_effect = [request_first, request_ok]

        with patch("short_bot.youtube.uploader.time.sleep"):
            vid = upload_video(
                credentials=fake_creds, file_path=fake_mp4,
                snippet={"title": "T", "description": "D",
                          "tags": [], "categoryId": "24"},
                status={"privacyStatus": "public"},
            )
    assert vid == "VID999"


def test_upload_video_gives_up_after_max_retries(tmp_path):
    from googleapiclient.errors import ResumableUploadError
    fake_mp4 = tmp_path / "v.mp4"
    fake_mp4.write_bytes(b"\x00")
    fake_creds = MagicMock()

    bad_resp = MagicMock(); bad_resp.status = 500; bad_resp.reason = "x"
    err = ResumableUploadError(bad_resp, b"err")

    with patch("short_bot.youtube.uploader.build") as mbuild, \
         patch("short_bot.youtube.uploader.MediaFileUpload"), \
         patch("short_bot.youtube.uploader.time.sleep"):
        api = MagicMock(); mbuild.return_value = api
        request = MagicMock(); request.next_chunk.side_effect = err
        api.videos.return_value.insert.return_value = request
        with pytest.raises(ResumableUploadError):
            upload_video(
                credentials=fake_creds, file_path=fake_mp4,
                snippet={"title": "T", "description": "D",
                          "tags": [], "categoryId": "24"},
                status={"privacyStatus": "public"},
                max_retries=3,
            )


def test_build_snippet_language_default_is_tr():
    snippet = build_snippet(
        header_top="A", header_bottom="B", body_paragraph="x" * 30,
        handle="@x", keywords=[], category_id="24",
    )
    assert snippet["defaultLanguage"] == "tr"


def test_build_snippet_respects_explicit_language():
    snippet = build_snippet(
        header_top="A", header_bottom="B", body_paragraph="x" * 30,
        handle="@x", keywords=[], category_id="24",
        language="de",
    )
    assert snippet["defaultLanguage"] == "de"
