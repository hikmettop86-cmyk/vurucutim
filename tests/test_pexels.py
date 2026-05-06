import os
from pathlib import Path

import pytest

from short_bot.pexels import load_secrets, resolve_pexels_api_key


def test_load_secrets_returns_empty_dict_when_file_missing(tmp_path):
    assert load_secrets(tmp_path / "missing.yaml") == {}


def test_load_secrets_parses_yaml(tmp_path):
    p = tmp_path / "secrets.yaml"
    p.write_text("pexels_api_key: abc123\n", encoding="utf-8")
    assert load_secrets(p) == {"pexels_api_key": "abc123"}


def test_resolve_returns_env_var_when_set(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "from-env")
    assert resolve_pexels_api_key({"pexels_api_key": "from-file"}) == "from-env"


def test_resolve_falls_back_to_secrets_dict(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert resolve_pexels_api_key({"pexels_api_key": "from-file"}) == "from-file"


def test_resolve_returns_empty_string_when_neither_set(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert resolve_pexels_api_key({}) == ""


from short_bot.pexels import ARCHETYPE_BG_QUERIES, pick_query_for_archetype


def test_archetype_pool_covers_all_seven_archetypes():
    expected = {"newscast", "tabloid", "magazine", "kinetic",
                "dark-tech", "stadium", "meme"}
    assert set(ARCHETYPE_BG_QUERIES.keys()) == expected


def test_each_archetype_pool_has_at_least_three_queries():
    for arch, queries in ARCHETYPE_BG_QUERIES.items():
        assert len(queries) >= 3, f"{arch} has fewer than 3 queries"


def test_pick_query_returns_member_of_pool():
    q = pick_query_for_archetype("newscast")
    assert q in ARCHETYPE_BG_QUERIES["newscast"]


def test_pick_query_unknown_archetype_falls_back_to_generic():
    q = pick_query_for_archetype("nonexistent-xyz")
    assert q == "abstract motion background"
