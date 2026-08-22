import json as _json
import time as _time
from unittest.mock import patch, MagicMock

import requests

from short_bot.openrouter_catalog import _build_from_models


def _model(mid, modalities):
    return {"id": mid, "name": mid.split("/")[-1],
            "architecture": {"input_modalities": modalities}}


def test_build_filters_to_popular_providers_and_groups():
    raw = [
        _model("anthropic/claude-x", ["text", "image"]),
        _model("google/gemini-x", ["text", "image"]),
        _model("openai/gpt-x", ["text"]),
        _model("randomlab/obscure-model", ["text"]),
    ]
    cat = _build_from_models(raw)
    labels = [g["label"] for g in cat["groups"]]
    assert any("Anthropic" in l for l in labels)
    assert any("Google" in l for l in labels)
    assert any("OpenAI" in l for l in labels)
    all_ids = [m["id"] for g in cat["groups"] for m in g["models"]]
    assert "randomlab/obscure-model" not in all_ids
    assert "anthropic/claude-x" in all_ids


def test_build_sets_vision_flag_from_image_modality():
    raw = [
        _model("anthropic/with-vision", ["text", "image"]),
        _model("anthropic/no-vision", ["text"]),
    ]
    cat = _build_from_models(raw)
    by_id = {m["id"]: m for g in cat["groups"] for m in g["models"]}
    assert by_id["anthropic/with-vision"]["vision"] is True
    assert by_id["anthropic/no-vision"]["vision"] is False


def test_build_empty_when_no_popular():
    cat = _build_from_models([_model("foo/bar", ["text"])])
    assert cat["groups"] == []


from short_bot.openrouter_catalog import get_catalog


def _models_resp(ids_modalities):
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = {"data": [
        {"id": mid, "name": mid, "architecture": {"input_modalities": mod}}
        for mid, mod in ids_modalities
    ]}
    return r


def test_get_catalog_fresh_cache_skips_fetch(tmp_path):
    cache = tmp_path / "openrouter_models_cache.json"
    cache.write_text(_json.dumps({
        "fetched_at": _time.time(),
        "catalog": {"groups": [{"label": "X", "models": []}]},
    }), encoding="utf-8")
    with patch("short_bot.openrouter_catalog.requests.get") as g:
        cat = get_catalog(tmp_path)
    g.assert_not_called()
    assert cat["groups"][0]["label"] == "X"


def test_get_catalog_stale_fetches_and_writes_cache(tmp_path):
    cache = tmp_path / "openrouter_models_cache.json"
    cache.write_text(_json.dumps({"fetched_at": 0, "catalog": {"groups": []}}),
                     encoding="utf-8")
    with patch("short_bot.openrouter_catalog.requests.get",
               return_value=_models_resp([("anthropic/c", ["text", "image"])])):
        cat = get_catalog(tmp_path)
    assert "anthropic/c" in [m["id"] for grp in cat["groups"] for m in grp["models"]]
    written = _json.loads(cache.read_text(encoding="utf-8"))
    assert written["fetched_at"] > 0


def test_get_catalog_fetch_fail_falls_back_to_stale_cache(tmp_path):
    cache = tmp_path / "openrouter_models_cache.json"
    cache.write_text(_json.dumps({
        "fetched_at": 0,
        "catalog": {"groups": [{"label": "OLD", "models": []}]},
    }), encoding="utf-8")
    with patch("short_bot.openrouter_catalog.requests.get",
               side_effect=requests.ConnectionError("down")):
        cat = get_catalog(tmp_path)
    assert cat["groups"][0]["label"] == "OLD"


def test_get_catalog_no_cache_fetch_fail_uses_static(tmp_path):
    with patch("short_bot.openrouter_catalog.requests.get",
               side_effect=requests.ConnectionError("down")):
        cat = get_catalog(tmp_path)
    assert "groups" in cat
