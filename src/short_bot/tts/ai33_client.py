"""ai33.pro TTS istemcisi (ElevenLabs altyapılı aggregator).

Protokol (faceless-2'deki doğrulanmış akıştan):
  POST {base}/v3/text-to-speech   multipart: text, voice_id, speed  -> {task_id}
  GET  {base}/v1/task/{task_id}                                     -> {status, metadata:{audio_url}}
  GET  audio_url                                                    -> mp3 bytes
Auth: HTTP header  ``xi-api-key: <key>``  (Bearer değil).

Not: v3 endpoint ``model_id`` ve ``voice_settings`` KABUL ETMEZ; modeli
voice_id'nin prefix'i belirler. Timestamp de döndürmez — kelime senkronu
için ``short_bot.tts.align`` kullanılır.
"""
from __future__ import annotations

import os

BASE_URL = "https://api.ai33.pro"

_VOICE_PREFIXES = ("elevenlabs_", "minimax_", "edge_", "kokoro_", "clone_")


def resolve_ai33_api_key(secrets: dict) -> str:
    """ai33 API anahtarını çöz. Env var AI33_API_KEY, secrets dict'i ezer."""
    return os.environ.get("AI33_API_KEY") or secrets.get("ai33_api_key") or ""


def normalize_voice_id(voice_id: str) -> str:
    """v3 provider-prefix'i zorunlu; ham id'ye 'elevenlabs_' eklenir."""
    v = (voice_id or "").strip()
    if not v:
        raise ValueError("voice_id boş olamaz")
    return v if v.startswith(_VOICE_PREFIXES) else f"elevenlabs_{v}"
