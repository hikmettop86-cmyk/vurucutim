"""OpenAI-uyumlu tek istemci — DeepSeek, Qwen, ModelScope, Groq, NVIDIA, OpenAI.

Hepsi aynı `/chat/completions` sözleşmesini konuşuyor. Altı ayrı istemci yazmak
altı ayrı hata yolu, altı ayrı zaman aşımı davranışı ve altı ayrı sessiz
başarısızlık demekti; sağlayıcı farkı yalnızca `base_url` + anahtar.

`openrouter_client` ayrı duruyor: OpenRouter'ın kendi başlıkları (X-Title) ve
`response_format` desteklemeyen modeller için json_mode geri-düşmesi var.
"""
from __future__ import annotations

import base64
from pathlib import Path

import requests


class OpenAIUyumluError(RuntimeError):
    """Anahtar yok / ağ hatası / non-200 / boş yanıt."""


def complete(prompt: str, *, base_url: str, model: str, api_key: str | None,
             timeout_s: int = 180, max_tokens: int = 8000,
             json_mode: bool = False, image_path: "Path | None" = None) -> str:
    """Tek atış tamamlama; mesaj içeriğini (ham metin) döndürür.

    `json_mode` VARSAYILAN KAPALI: bu istemcinin ilk kullanıcısı arketip
    şablonu yazıyor ve çıktı HTML. Açık bırakmak modeli JSON'a zorlar.
    """
    if not api_key:
        raise OpenAIUyumluError(
            "API anahtarı girilmemiş — Ayarlar → AI Sağlayıcıları'ndan ekleyin.")

    if image_path is not None:
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        icerik: object = [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]
    else:
        icerik = prompt

    govde: dict = {"model": model,
                   "messages": [{"role": "user", "content": icerik}],
                   "max_tokens": max_tokens}
    if json_mode:
        govde["response_format"] = {"type": "json_object"}

    try:
        r = requests.post(base_url, json=govde, timeout=timeout_s,
                          headers={"Authorization": f"Bearer {api_key}",
                                   "Content-Type": "application/json"})
    except requests.RequestException as e:
        raise OpenAIUyumluError(f"ağ hatası: {e}") from e

    if r.status_code != 200:
        raise OpenAIUyumluError(f"HTTP {r.status_code}: {r.text[:400]}")

    try:
        metin = r.json()["choices"][0]["message"]["content"]
    except Exception as e:   # noqa: BLE001 — beklenmeyen gövde
        raise OpenAIUyumluError(f"beklenmeyen yanıt gövdesi: {e}") from e

    if not (metin or "").strip():
        # Boş içerik sessizce "" dönerse çağıran onu geçerli sanar ve hata
        # şema doğrulamasında ortaya çıkar — sebebi kaybolmuş olarak.
        raise OpenAIUyumluError("model boş yanıt döndürdü")
    return metin
