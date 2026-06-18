"""OpenRouter /models'tan canlı model kataloğu (cache + filtre + fallback)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

_MODELS_URL = "https://openrouter.ai/api/v1/models"
_TTL_SECONDS = 12 * 3600
# Popüler sağlayıcı prefix → grup etiketi (sıra = UI sırası)
_PROVIDERS = [
    ("anthropic/", "Anthropic Claude"),
    ("google/", "Google Gemini / Gemma"),
    ("openai/", "OpenAI"),
    ("x-ai/", "xAI Grok"),
    ("meta-llama/", "Meta Llama"),
    ("mistralai/", "Mistral"),
    ("deepseek/", "DeepSeek"),
]


def _build_from_models(raw: list) -> dict:
    """OpenRouter /models data[] → {groups:[{label, models:[{id,label,vision}]}]}.
    Yalnızca _PROVIDERS prefix'li modeller, sağlayıcıya gruplu, vision bayraklı."""
    groups = []
    for prefix, label in _PROVIDERS:
        models = []
        for m in raw:
            mid = m.get("id", "")
            if not mid.startswith(prefix):
                continue
            arch = m.get("architecture") or {}
            modalities = arch.get("input_modalities") or []
            models.append({
                "id": mid,
                "label": m.get("name") or mid,
                "vision": "image" in modalities,
            })
        if models:
            models.sort(key=lambda x: x["id"])
            groups.append({"label": label, "models": models})
    return {"groups": groups}


def _cache_path(cache_dir) -> Path:
    return Path(cache_dir) / "openrouter_models_cache.json"


def _fetch_live(timeout_s: int = 10) -> dict:
    r = requests.get(_MODELS_URL, timeout=timeout_s)
    r.raise_for_status()
    data = r.json().get("data") or []
    return _build_from_models(data)


def _static_fallback() -> dict:
    p = Path("config/openrouter_models.json")
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {"groups": []}


def get_catalog(cache_dir) -> dict:
    """Cache taze ise onu; bayat/yok ise /models çek+cache; fail ise cache→statik.
    Asla exception fırlatmaz (UI'yı kırmaz)."""
    cpath = _cache_path(cache_dir)
    cached = None
    try:
        if cpath.exists():
            cached = json.loads(cpath.read_text(encoding="utf-8"))
            if time.time() - cached.get("fetched_at", 0) < _TTL_SECONDS:
                return cached["catalog"]
    except (OSError, json.JSONDecodeError):
        cached = None
    try:
        catalog = _fetch_live()
        if catalog["groups"]:
            cpath.parent.mkdir(parents=True, exist_ok=True)
            cpath.write_text(
                json.dumps({"fetched_at": time.time(), "catalog": catalog}),
                encoding="utf-8")
            return catalog
    except (requests.RequestException, ValueError, KeyError):
        pass
    if cached and cached.get("catalog", {}).get("groups"):
        return cached["catalog"]
    return _static_fallback()
