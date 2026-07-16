"""run_auto_upload proxy yolunu doğru çağırıyor + fail durumlarını
proxy_failed olarak işaretliyor."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def channel_with_yt():
    from short_bot.config import ChannelConfig, YoutubeChannelConfig
    yt = YoutubeChannelConfig(
        auto_upload=True, ai_content=True, category_id="24",
        privacy_status="public", min_score_for_upload=0.0, cron_preset=None,
    )
    return ChannelConfig(
        slug="t", name="t", keywords=[], rss_locale="tr-TR",
        schedule_cron="* * * * *", duration_s=30, min_score=0.0,
        max_candidates_per_run=5, template="newscast", colors={},
        handle="@x", output_dir="output/t", enabled=True,
        language="tr",
        youtube=yt,
    )


def test_run_auto_upload_uses_proxy_when_set(tmp_path, channel_with_yt):
    """Proxy URL secrets'ta varsa upload_video http= ile çağrılır."""
    from short_bot.youtube import auto_upload
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("channel_proxies:\n  t: http://h:1\n", encoding="utf-8")

    with patch.object(auto_upload, "upload_video") as mock_upload, \
         patch.object(auto_upload, "build_proxied_http") as mock_bph, \
         patch.object(auto_upload, "build_proxied_requests_session") as mock_bps, \
         patch.object(auto_upload, "record_youtube_upload"), \
         patch.object(auto_upload, "_load_short_for_upload") as mock_load, \
         patch.object(auto_upload, "generate_youtube_metadata", side_effect=Exception()):
        mock_load.return_value = (
            MagicMock(file_path=str(tmp_path / "v.mp4"), script_json="{}"),
            None, None,
        )
        (tmp_path / "v.mp4").write_bytes(b"\x00")
        mock_bph.return_value = "PROXIED_HTTP"
        mock_bps.return_value = MagicMock()
        mock_upload.return_value = "VID"
        # creds.expired = False so no refresh attempted
        creds = MagicMock()
        creds.expired = False
        auto_upload.run_auto_upload(
            eng=MagicMock(), short_id=1, channel=channel_with_yt,
            credentials=creds, secrets_path=secrets,
        )

    mock_bph.assert_called_once_with("http://h:1")
    # upload_video http=PROXIED_HTTP ile çağrılmalı
    _, kwargs = mock_upload.call_args
    assert kwargs.get("http") == "PROXIED_HTTP"


def test_run_auto_upload_no_proxy_passes_none(tmp_path, channel_with_yt):
    """Secrets'ta proxy yoksa http=None geçilir (existing direct behavior)."""
    from short_bot.youtube import auto_upload
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("pexels_api_key: x\n", encoding="utf-8")

    with patch.object(auto_upload, "upload_video") as mock_upload, \
         patch.object(auto_upload, "record_youtube_upload"), \
         patch.object(auto_upload, "_load_short_for_upload") as mock_load, \
         patch.object(auto_upload, "generate_youtube_metadata", side_effect=Exception()):
        mock_load.return_value = (
            MagicMock(file_path=str(tmp_path / "v.mp4"), script_json="{}"),
            None, None,
        )
        (tmp_path / "v.mp4").write_bytes(b"\x00")
        mock_upload.return_value = "VID"
        creds = MagicMock()
        creds.expired = False
        auto_upload.run_auto_upload(
            eng=MagicMock(), short_id=1, channel=channel_with_yt,
            credentials=creds, secrets_path=secrets,
        )
    _, kwargs = mock_upload.call_args
    assert kwargs.get("http") is None


def test_run_auto_upload_proxy_fail_raises_abort_and_records_proxy_failed(
    tmp_path, channel_with_yt
):
    """Proxy fail edince UploadAbortError + record_youtube_upload(status='proxy_failed')."""
    import requests
    from short_bot.youtube import auto_upload
    from short_bot.youtube.auto_upload import UploadAbortError
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("channel_proxies:\n  t: http://h:1\n", encoding="utf-8")

    fake_creds = MagicMock()
    fake_creds.expired = True
    fake_creds.refresh_token = "r"
    fake_creds.refresh.side_effect = requests.exceptions.ProxyError("proxy down")

    with patch.object(auto_upload, "upload_video"), \
         patch.object(auto_upload, "record_youtube_upload") as mock_record, \
         patch.object(auto_upload, "_load_short_for_upload") as mock_load, \
         patch.object(auto_upload, "generate_youtube_metadata", side_effect=Exception()):
        mock_load.return_value = (
            MagicMock(file_path=str(tmp_path / "v.mp4"), script_json="{}"), None, None,
        )
        (tmp_path / "v.mp4").write_bytes(b"\x00")
        with pytest.raises(UploadAbortError):
            auto_upload.run_auto_upload(
                eng=MagicMock(), short_id=1, channel=channel_with_yt,
                credentials=fake_creds, secrets_path=secrets,
            )
    # Hata kaydı status='proxy_failed' ile yapılmış olmalı
    mock_record.assert_called_once()
    _, kw = mock_record.call_args
    assert kw["status"] == "proxy_failed"
    assert "proxy" in (kw["error"] or "").lower()
