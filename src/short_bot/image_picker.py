"""Pick a topical image for the photo band when RSS doesn't supply one.

Strategy:
1. Build a search query from the script (header + category)
2. DuckDuckGo image search
3. For each candidate (top N): download to cache, ask Claude to verify
4. Return first OK image, or None if all rejected/failed
"""
from __future__ import annotations

import hashlib
import io
import logging
import subprocess
from pathlib import Path

import requests
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from short_bot.claude_cli import ClaudeCliError, run_json
from short_bot.config import ChannelConfig
from short_bot.image_search import ImageCandidate, search_images
from short_bot.models import Script

logger = logging.getLogger(__name__)


class _Verdict(BaseModel):
    appropriate: bool
    reason: str


def build_search_query(script: Script) -> str:
    """Build image search query from script header + category."""
    parts = [script.header_top, script.header_bottom, script.category]
    return " ".join(p for p in parts if p).strip()


def _download(url: str, dest: Path, *, timeout: int = 15) -> bool:
    """Download URL to dest. Returns True on success."""
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "short-bot/0.1"})
    except requests.RequestException as e:
        logger.warning(f"download failed {url}: {e}")
        return False
    if r.status_code != 200 or not r.content:
        return False
    try:
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        logger.warning(f"decode failed {url}: {e}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=88)
    return True


def _verify_with_claude(image_path: Path, script: Script, claude_path: str) -> _Verdict | None:
    """Ask Claude (vision) whether the image is appropriate. Returns None on CLI failure."""
    summary = script.body_paragraph[:200]
    prompt = (
        f"@{image_path.absolute().as_posix()}\n\n"
        f"Bu görselin bir Türkçe haber kanalının YouTube Shorts'unda kapak görseli olarak kullanılmasının "
        f"uygun olup olmadığını değerlendir.\n\n"
        f"HABER BAŞLIĞI: {script.header_top} {script.header_bottom}\n"
        f"KATEGORİ: {script.category}\n"
        f"ÖZET: {summary}\n\n"
        f"Değerlendirme kriterleri:\n"
        f"- Görsel haberin konusuyla doğrudan ya da yakından ilgili olmalı\n"
        f"- Yanlış kişi/yer/marka göstermemeli (ör. başka bir ülkenin bayrağı vs.)\n"
        f"- Reklam/banner/watermark bariz biçimde dolu olmamalı\n"
        f"- Şiddet, çıplaklık vs. uygunsuz içerik olmamalı\n\n"
        f"SADECE JSON formatında yanıt ver:\n"
        f'{{"appropriate": true|false, "reason": "<kısa Türkçe açıklama, 1 cümle>"}}'
    )
    try:
        return run_json(prompt, _Verdict, claude_path=claude_path, retries=1, timeout_s=60)
    except ClaudeCliError as e:
        logger.warning(f"claude verification failed: {e}")
        return None


def build_search_query_for_channel(script: Script, channel: ChannelConfig) -> str:
    """Build DDG image search query using channel.dna.search_query_template if set."""
    template = (
        channel.dna.search_query_template if channel.dna is not None
        else "{header_top} {header_bottom} {category}"
    )
    return template.format(
        header_top=script.header_top,
        header_bottom=script.header_bottom,
        category=script.category,
        photo_overlay=script.photo_overlay,
    ).strip()


def pick_image_for_script(
    script: Script,
    cache_dir: Path,
    *,
    claude_path: str = "claude",
    max_candidates: int = 3,
    channel: ChannelConfig | None = None,
) -> Path | None:
    """Search -> download candidates -> verify with Claude -> return first OK image path.

    Tries DuckDuckGo first; if that returns nothing (rate limit, network), falls back
    to Wikimedia Commons API.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    query = (build_search_query_for_channel(script, channel)
             if channel is not None else build_search_query(script))
    logger.info(f"image search (DDG): {query!r}")
    candidates = search_images(query, max_results=max_candidates)
    if not candidates:
        logger.warning("DDG returned 0 candidates; trying Wikimedia Commons")
        from short_bot.wikimedia_search import search_images_commons
        candidates = search_images_commons(query, max_results=max_candidates)
        if candidates:
            logger.warning(f"Wikimedia returned {len(candidates)} candidates")
    if not candidates:
        logger.warning("no image candidates from any source")
        return None

    for i, cand in enumerate(candidates):
        key = hashlib.sha1(cand.url.encode("utf-8")).hexdigest()[:16]
        path = cache_dir / f"{key}.jpg"
        if not path.exists():
            if not _download(cand.url, path):
                continue
        verdict = _verify_with_claude(path, script, claude_path)
        if verdict is None:
            logger.warning(f"  cand {i}: verification CLI failed -> skip")
            continue
        if verdict.appropriate:
            logger.warning(f"  cand {i} ACCEPTED: {verdict.reason}")
            return path
        logger.warning(f"  cand {i} rejected: {verdict.reason}")
    logger.info("no candidate passed verification")
    return None
