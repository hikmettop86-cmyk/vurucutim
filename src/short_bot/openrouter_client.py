"""OpenRouter /chat/completions çağrısı (OpenAI-uyumlu). Ham metin döndürür."""
from __future__ import annotations

import requests

from short_bot.claude_cli import OpenRouterError

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def complete(prompt: str, *, model: str, api_key: str | None,
             timeout_s: int = 180, json_mode: bool = True) -> str:
    """OpenRouter'a tek-atış istek; mesaj içeriğini (ham metin) döndürür.

    Raises OpenRouterError: key yok / ağ hatası / non-200.
    """
    if not api_key:
        raise OpenRouterError(
            "OpenRouter seçili ama openrouter_api_key girilmemiş — Ayarlar'dan ekleyin."
        )
    body: dict = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {api_key}", "X-Title": "short-bot"}
    try:
        r = requests.post(_ENDPOINT, json=body, headers=headers, timeout=timeout_s)
    except requests.RequestException as e:
        raise OpenRouterError(f"OpenRouter ağ hatası: {e}") from e
    if r.status_code == 400 and json_mode:
        # Model response_format'ı desteklemiyor olabilir → json_mode'suz bir kez dene
        return complete(prompt, model=model, api_key=api_key,
                        timeout_s=timeout_s, json_mode=False)
    if r.status_code != 200:
        raise OpenRouterError(f"OpenRouter HTTP {r.status_code}: {r.text[:500]}")
    return r.json()["choices"][0]["message"]["content"]
