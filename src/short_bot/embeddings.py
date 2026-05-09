"""OpenAI text-embedding-3-small HTTP client wrapper.

Used by dna_cache for per-channel similarity lookup. Pure-requests
(no openai SDK dep) to keep the dep tree minimal.
"""
from __future__ import annotations

import logging
import time

import requests

_LOG = logging.getLogger(__name__)

_OPENAI_URL = "https://api.openai.com/v1/embeddings"
_MODEL = "text-embedding-3-small"
_EXPECTED_DIM = 1536
# Truncate input to 8000 chars before sending. OpenAI's tokenizer ~4 chars/token,
# 8000 chars ≈ 2000 tokens — well under the 8192 token model limit.
_MAX_INPUT_CHARS = 8000
_MAX_RETRIES = 3
_RETRY_BACKOFF_S = 1.0


class EmbeddingError(RuntimeError):
    """Raised when embedding cannot be produced (key missing, API error, etc.)."""


def embed_text(text: str, *, api_key: str, timeout_s: float = 10.0) -> list[float]:
    """Return a 1536-dim embedding vector for `text`.

    Raises EmbeddingError on any failure (caller falls back to static DNA).
    """
    if not api_key:
        raise EmbeddingError("api_key required (no OPENAI_API_KEY env or secrets value)")

    payload = {
        "model": _MODEL,
        "input": text[:_MAX_INPUT_CHARS],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    last_err: str = ""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = requests.post(_OPENAI_URL, json=payload, headers=headers,
                                  timeout=timeout_s)
        except requests.RequestException as e:
            last_err = f"network error: {e}"
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_S * attempt)
                continue
            raise EmbeddingError(last_err) from e

        if resp.status_code == 200:
            data = resp.json().get("data") or []
            if not data:
                raise EmbeddingError("empty data in OpenAI response")
            vec = data[0].get("embedding") or []
            if len(vec) != _EXPECTED_DIM:
                raise EmbeddingError(
                    f"unexpected dimension {len(vec)} (want {_EXPECTED_DIM})"
                )
            return [float(x) for x in vec]

        # Retry on 5xx; bail on 4xx
        if 500 <= resp.status_code < 600 and attempt < _MAX_RETRIES:
            last_err = f"HTTP {resp.status_code} {resp.text[:200]}"
            time.sleep(_RETRY_BACKOFF_S * attempt)
            continue
        raise EmbeddingError(f"HTTP {resp.status_code} {resp.text[:200]}")

    raise EmbeddingError(last_err or "exhausted retries")
