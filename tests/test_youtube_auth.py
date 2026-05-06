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
