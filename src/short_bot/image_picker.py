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
    """Search -> download candidates -> verify with Claude -> return first OK image path."""
    query = (build_search_query_for_channel(script, channel)
             if channel is not None else build_search_query(script))
    return _run_image_search(
        query, script, cache_dir,
        claude_path=claude_path, max_candidates=max_candidates,
    )


def pick_image_for_generator(
    *,
    keywords: list[str],
    script: Script,
    cache_dir: Path,
    claude_path: str = "claude",
    max_candidates: int = 3,
) -> Path | None:
    """Image picker for generator mode: query is space-joined keywords from Sonnet."""
    query = " ".join(k for k in keywords if k).strip()
    return _run_image_search(
        query, script, cache_dir,
        claude_path=claude_path, max_candidates=max_candidates,
    )


def _normalize_query(q: str) -> str:
    """ASCII-fold + punctuation strip for DDG image search.
    Türkçe diakritik karakterler ve apostrof DDG sorgularında 0 sonuç riskini
    artırıyor. Bu fonksiyon agresif bir simplified fallback üretir."""
    import unicodedata, re
    # NFKD decompose + drop combining chars → ASCII
    nfkd = unicodedata.normalize('NFKD', q)
    ascii_q = ''.join(c for c in nfkd if not unicodedata.combining(c))
    # Türkçe-spesifik karakterler için manuel map (NFKD bazılarını kaçırır)
    tr_map = str.maketrans({
        'ı': 'i', 'İ': 'I', 'ğ': 'g', 'Ğ': 'G',
        'ş': 's', 'Ş': 'S', 'ç': 'c', 'Ç': 'C',
        'ö': 'o', 'Ö': 'O', 'ü': 'u', 'Ü': 'U',
    })
    ascii_q = ascii_q.translate(tr_map)
    # Strip apostrof + tek tırnak + redundant whitespace
    ascii_q = re.sub(r"['’‘\"`]", '', ascii_q)
    ascii_q = re.sub(r'\s+', ' ', ascii_q).strip()
    return ascii_q


def _run_image_search(
    query: str,
    script: Script,
    cache_dir: Path,
    *,
    claude_path: str,
    max_candidates: int,
) -> Path | None:
    """Internal: shared DDG -> Wikimedia fallback -> download -> Claude verify loop."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"image search (DDG): {query!r}")
    candidates = search_images(query, max_results=max_candidates)

    # If original query (Türkçe diakritik + apostrof) returns 0 results,
    # retry with ASCII-folded version — DDG often handles plain ASCII better.
    if not candidates:
        normalized = _normalize_query(query)
        if normalized and normalized != query:
            logger.info(f"DDG 0 sonuc; ASCII normalize ile retry: {normalized!r}")
            candidates = search_images(normalized, max_results=max_candidates)

    # Still nothing? Try just the most-distinctive part (header_bottom only)
    if not candidates and script.header_bottom:
        short_q = _normalize_query(script.header_bottom)
        if short_q and short_q != query:
            logger.info(f"DDG hala 0; sadece header_bottom ile retry: {short_q!r}")
            candidates = search_images(short_q, max_results=max_candidates)

    if not candidates:
        logger.warning("DDG returned 0 candidates; trying Wikimedia Commons")
        from short_bot.wikimedia_search import search_images_commons
        candidates = search_images_commons(query, max_results=max_candidates)
        if not candidates:
            normalized = _normalize_query(query)
            if normalized and normalized != query:
                candidates = search_images_commons(normalized, max_results=max_candidates)
        if candidates:
            logger.warning(f"Wikimedia returned {len(candidates)} candidates")

    # Final fallback: Pexels photo API (if pexels_api_key configured).
    # Pexels Türkçe sorgular için zayıf — normalize edilmiş İngilizce-vari
    # query daha iyi sonuç verir.
    if not candidates:
        try:
            from short_bot.pexels import (
                search_photos as _pexels_photos,
                resolve_pexels_api_key as _pexels_key,
                load_secrets as _pexels_secrets,
            )
            from flask import current_app
            try:
                secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
            except RuntimeError:
                # Outside Flask context (e.g. CLI run) — fall back to default
                secrets_path = None
            if secrets_path is None:
                from pathlib import Path as _P
                secrets_path = _P("data") / "secrets.yaml"
            api_key = _pexels_key(_pexels_secrets(secrets_path))
            if api_key:
                pexels_q = _normalize_query(query)
                logger.warning(f"Pexels photo fallback: {pexels_q!r}")
                pexels_results = _pexels_photos(pexels_q, api_key, max_results=max_candidates)
                if pexels_results:
                    logger.warning(f"Pexels returned {len(pexels_results)} photo candidates")
                    candidates = [
                        ImageCandidate(url=p.url, thumbnail=p.url,
                                       title=f"Pexels #{p.id}",
                                       source_domain="pexels.com",
                                       width=p.width, height=p.height)
                        for p in pexels_results
                    ]
            else:
                logger.info("Pexels fallback skipped: pexels_api_key not configured")
        except Exception as e:
            logger.warning(f"Pexels fallback failed: {e}")

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
