import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.youtube.auth import (
    credentials_dir, save_credentials, load_credentials, has_credentials,
    delete_credentials,
)


def test_credentials_dir_returns_per_channel_path(tmp_path):
    p = credentials_dir(tmp_path / "creds", "galatasaray")
    assert p == tmp_path / "creds" / "galatasaray"


def test_save_and_load_round_trip(tmp_path):
    fake_creds = MagicMock()
    fake_creds.to_json.return_value = json.dumps({
        "token": "abc", "refresh_token": "def",
        "client_id": "x", "client_secret": "y",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
    })
    save_credentials(tmp_path / "creds", "ch", fake_creds)
    assert (tmp_path / "creds" / "ch" / "token.json").exists()

    with patch("short_bot.youtube.auth.Credentials") as MockCreds:
        mock_obj = MagicMock()
        mock_obj.expired = False
        MockCreds.from_authorized_user_info.return_value = mock_obj
        loaded = load_credentials(tmp_path / "creds", "ch")
    assert loaded is mock_obj


def test_load_returns_none_when_missing(tmp_path):
    assert load_credentials(tmp_path / "creds", "missing") is None


def test_has_credentials(tmp_path):
    assert not has_credentials(tmp_path / "creds", "ch")
    (tmp_path / "creds" / "ch").mkdir(parents=True)
    (tmp_path / "creds" / "ch" / "token.json").write_text("{}")
    assert has_credentials(tmp_path / "creds", "ch")


def test_delete_credentials_removes_token_file(tmp_path):
    (tmp_path / "creds" / "ch").mkdir(parents=True)
    (tmp_path / "creds" / "ch" / "token.json").write_text("{}")
    (tmp_path / "creds" / "ch" / "channel_info.json").write_text("{}")
    delete_credentials(tmp_path / "creds", "ch")
    assert not (tmp_path / "creds" / "ch" / "token.json").exists()
    assert (tmp_path / "creds" / "ch" / "channel_info.json").exists()


def test_load_credentials_refreshes_when_expired(tmp_path):
    """When token is expired AND has refresh_token, load_credentials() must
    call .refresh() and persist the renewed token back to disk."""
    import json as _json
    d = tmp_path / "creds" / "ch"; d.mkdir(parents=True)
    (d / "token.json").write_text(_json.dumps({
        "token": "old", "refresh_token": "rt",
        "client_id": "x", "client_secret": "y",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
    }))

    refreshed = MagicMock()
    refreshed.expired = True
    refreshed.refresh_token = "rt"
    refreshed.to_json.return_value = _json.dumps({"token": "new", "scopes": []})

    with patch("short_bot.youtube.auth.Credentials") as MockCreds, \
         patch("short_bot.youtube.auth.Request") as MockReq:
        MockCreds.from_authorized_user_info.return_value = refreshed
        load_credentials(tmp_path / "creds", "ch")

    refreshed.refresh.assert_called_once_with(MockReq.return_value)
    # Renewed token must be persisted
    persisted = (d / "token.json").read_text(encoding="utf-8")
    assert '"token": "new"' in persisted


def test_build_flow_loads_client_secrets(tmp_path):
    secrets_path = tmp_path / "creds" / "ch" / "client_secrets.json"
    secrets_path.parent.mkdir(parents=True)
    secrets_path.write_text(json.dumps({
        "web": {
            "client_id": "x.apps.googleusercontent.com",
            "client_secret": "secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://127.0.0.1:5005/oauth/callback"],
        }
    }))
    from short_bot.youtube.auth import build_flow
    flow = build_flow(tmp_path / "creds", "ch",
                       redirect_uri="http://127.0.0.1:5005/oauth/callback")
    assert flow is not None
    auth_url, state = flow.authorization_url(state="ch", access_type="offline",
                                              prompt="consent")
    assert "accounts.google.com" in auth_url
    assert "state=ch" in auth_url


def test_build_flow_raises_when_secrets_missing(tmp_path):
    from short_bot.youtube.auth import build_flow
    with pytest.raises(FileNotFoundError, match="client_secrets.json"):
        build_flow(tmp_path / "creds", "ch", redirect_uri="http://x/cb")


def test_fetch_and_save_channel_info_writes_json(tmp_path):
    fake_creds = MagicMock()
    with patch("short_bot.youtube.auth.build") as mbuild:
        api = MagicMock()
        mbuild.return_value = api
        api.channels.return_value.list.return_value.execute.return_value = {
            "items": [{
                "id": "UC123",
                "snippet": {"title": "Test Kanal"},
                "statistics": {"subscriberCount": "42", "videoCount": "7"},
            }]
        }
        from short_bot.youtube.auth import fetch_and_save_channel_info
        info = fetch_and_save_channel_info(tmp_path / "creds", "ch", fake_creds)

    assert info["id"] == "UC123"
    assert info["snippet"]["title"] == "Test Kanal"
    saved = json.loads(
        (tmp_path / "creds" / "ch" / "channel_info.json").read_text(encoding="utf-8")
    )
    assert saved["id"] == "UC123"


def test_load_channel_info_returns_dict(tmp_path):
    d = tmp_path / "creds" / "ch"
    d.mkdir(parents=True)
    (d / "channel_info.json").write_text(json.dumps({"id": "UC9", "snippet": {"title": "X"}}))
    from short_bot.youtube.auth import load_channel_info
    info = load_channel_info(tmp_path / "creds", "ch")
    assert info["id"] == "UC9"


def test_load_channel_info_returns_none_when_missing(tmp_path):
    from short_bot.youtube.auth import load_channel_info
    assert load_channel_info(tmp_path / "creds", "missing") is None


def test_purge_credentials_removes_entire_dir(tmp_path):
    d = tmp_path / "creds" / "ch"
    d.mkdir(parents=True)
    (d / "token.json").write_text("{}")
    (d / "channel_info.json").write_text("{}")
    (d / "client_secrets.json").write_text("{}")
    from short_bot.youtube.auth import purge_credentials
    purge_credentials(tmp_path / "creds", "ch")
    assert not d.exists()


def test_purge_credentials_idempotent_when_dir_missing(tmp_path):
    from short_bot.youtube.auth import purge_credentials
    purge_credentials(tmp_path / "creds", "missing")  # should not raise


def test_scopes_include_analytics():
    from short_bot.youtube.auth import SCOPES
    assert "https://www.googleapis.com/auth/yt-analytics.readonly" in SCOPES
