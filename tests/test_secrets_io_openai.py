"""Tests for OpenAI key resolution + secrets writer."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from short_bot.pexels import resolve_openai_api_key
from short_bot.secrets_io import update_openai_api_key


def test_resolve_openai_api_key_from_secrets():
    secrets = {"openai_api_key": "sk-test-123"}
    assert resolve_openai_api_key(secrets) == "sk-test-123"


def test_resolve_openai_api_key_env_beats_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    secrets = {"openai_api_key": "sk-from-secrets"}
    assert resolve_openai_api_key(secrets) == "sk-from-env"


def test_resolve_openai_api_key_empty_when_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert resolve_openai_api_key({}) == ""


def test_update_openai_api_key_writes_to_file(tmp_path: Path):
    p = tmp_path / "secrets.yaml"
    update_openai_api_key(p, "sk-abc")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data == {"openai_api_key": "sk-abc"}


def test_update_openai_api_key_preserves_other_keys(tmp_path: Path):
    p = tmp_path / "secrets.yaml"
    p.write_text(yaml.safe_dump({"pexels_api_key": "px-1"}), encoding="utf-8")
    update_openai_api_key(p, "sk-abc")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data == {"pexels_api_key": "px-1", "openai_api_key": "sk-abc"}


def test_update_openai_api_key_clear_with_none(tmp_path: Path):
    p = tmp_path / "secrets.yaml"
    p.write_text(
        yaml.safe_dump({"openai_api_key": "sk-old", "pexels_api_key": "px-1"}),
        encoding="utf-8",
    )
    update_openai_api_key(p, None)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data == {"pexels_api_key": "px-1"}
