"""Tests for proxy injection into youtube.auth.load_credentials."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock


def _make_token_dict():
    return {
        "token": "old",
        "refresh_token": "r",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid",
        "client_secret": "cs",
        "scopes": [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
        "expiry": "2000-01-01T00:00:00Z",   # expired → refresh tetiklenir
    }


def test_load_credentials_passes_session_to_request(tmp_path):
    from short_bot.youtube import auth as yt_auth
    slug = "ch1"
    d = tmp_path / slug
    d.mkdir()
    (d / "token.json").write_text(json.dumps(_make_token_dict()), encoding="utf-8")
    sess = MagicMock(name="proxy_session")

    with patch("short_bot.youtube.auth.Request") as mock_request, \
         patch.object(yt_auth, "save_credentials"):
        mock_request.return_value = MagicMock()
        with patch("short_bot.youtube.auth.Credentials") as mock_creds_cls:
            mock_creds = MagicMock()
            mock_creds.expired = True
            mock_creds.refresh_token = "r"
            mock_creds_cls.from_authorized_user_info.return_value = mock_creds
            yt_auth.load_credentials(tmp_path, slug, proxy_session=sess)

    mock_request.assert_called_once_with(session=sess)


def test_load_credentials_no_session_arg_uses_default_request(tmp_path):
    """Backward-compat: proxy_session argümanı verilmezse Request() default."""
    from short_bot.youtube import auth as yt_auth
    slug = "ch1"
    d = tmp_path / slug
    d.mkdir()
    (d / "token.json").write_text(json.dumps(_make_token_dict()), encoding="utf-8")

    with patch("short_bot.youtube.auth.Request") as mock_request, \
         patch.object(yt_auth, "save_credentials"), \
         patch("short_bot.youtube.auth.Credentials") as mock_creds_cls:
        mock_request.return_value = MagicMock()
        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "r"
        mock_creds_cls.from_authorized_user_info.return_value = mock_creds
        yt_auth.load_credentials(tmp_path, slug)

    mock_request.assert_called_once_with()   # session= argümanı YOK


def test_fetch_and_save_channel_info_uses_authorized_http_when_http_given(tmp_path):
    """When http= is given, build() must receive AuthorizedHttp(creds, http=http),
    NOT credentials= directly. (proxy path)"""
    from short_bot.youtube import auth as yt_auth
    fake_http = MagicMock(name="proxied_http")
    fake_creds = MagicMock(name="creds")
    slug = "ch1"
    (tmp_path / slug).mkdir()

    with patch("short_bot.youtube.auth.build") as mock_build, \
         patch("short_bot.youtube.auth.AuthorizedHttp") as mock_authed:
        mock_authed.return_value = "AUTHED"
        mock_yt = MagicMock()
        mock_yt.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "c1", "snippet": {}, "statistics": {}}],
        }
        mock_build.return_value = mock_yt
        with patch("short_bot.youtube.avatar.fetch_and_cache_avatar"):
            yt_auth.fetch_and_save_channel_info(tmp_path, slug, fake_creds, http=fake_http)

    mock_authed.assert_called_once_with(fake_creds, http=fake_http)
    mock_build.assert_called_once_with("youtube", "v3", http="AUTHED")


def test_fetch_and_save_channel_info_no_http_uses_credentials_directly(tmp_path):
    """Backward-compat: http= yoksa eski davranış (credentials= geçer)."""
    from short_bot.youtube import auth as yt_auth
    fake_creds = MagicMock(name="creds")
    slug = "ch1"
    (tmp_path / slug).mkdir()

    with patch("short_bot.youtube.auth.build") as mock_build, \
         patch("short_bot.youtube.auth.AuthorizedHttp") as mock_authed:
        mock_yt = MagicMock()
        mock_yt.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "c1", "snippet": {}, "statistics": {}}],
        }
        mock_build.return_value = mock_yt
        with patch("short_bot.youtube.avatar.fetch_and_cache_avatar"):
            yt_auth.fetch_and_save_channel_info(tmp_path, slug, fake_creds)

    mock_authed.assert_not_called()
    mock_build.assert_called_once_with("youtube", "v3", credentials=fake_creds)
