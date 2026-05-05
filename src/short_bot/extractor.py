"""Article body extractor — trafilatura with HTTP error / empty-body handling."""
from __future__ import annotations

import requests
import trafilatura


def extract_article(
    url: str,
    *,
    max_chars: int = 2000,
    timeout: int = 15,
) -> str | None:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "short-bot/0.1"})
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None

    text = trafilatura.extract(
        r.text,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text:
        return None

    text = text.strip()
    if len(text) < 30:                    # likely paywall/login wall
        return None
    if len(text) > max_chars:
        # truncate at last full sentence
        truncated = text[:max_chars]
        last = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
        if last > max_chars // 2:
            text = truncated[:last + 1]
        else:
            text = truncated
    return text
