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
