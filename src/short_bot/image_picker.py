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
    # Dual-axis verdict: appropriate is the strict "real fit?" check; is_safe
    # is the lenient "not unsafe and at least minimally usable?" check. When
    # every source rejects on appropriate, the first is_safe candidate is
    # used as a last-resort fallback — better than producing no video.
    # Default False so older prompt outputs (which omit the field) don't
    # accidentally make every reject eligible for fallback.
    is_safe: bool = False
    # Hard-reject signal: image contains burned-in headline/news graphic
    # (e.g. another outlet's "ATEŞKES 15 GÜN UZATILDI" card with contradictory
    # numbers when our script says "45 GÜN"). These graphics overlay onto
    # the video frame and surface conflicting facts to the viewer. Treat as
    # rejection — even disqualifies the last-resort fallback path. Default
    # False so older verdicts (pre-feature) are not retroactively rejected.
    has_text_overlay: bool = False


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
    """Ask Claude (vision) whether the image is appropriate. Returns None on CLI failure.

    Three signals returned:
      - appropriate: STRICT fit (image directly represents the news topic)
      - is_safe: LOOSE/thematic fit (no inappropriate content, at least
        plausible for the news category — used as last-resort fallback
        when every source rejects on appropriate=true)
      - has_text_overlay: HARD REJECT — another outlet's burned-in headline
        graphic, embedded text will appear in our frame and may contradict
        the script (e.g. our script says '45 gün', image says '15 gün').
    Loose phrasing in the prompt prevents over-rejection on stories like
    'Putin announces ceasefire' where the search returns thematic images
    (Kremlin, Russian flag, soldiers) rather than a direct headshot.
    """
    summary = script.body_paragraph[:200]
    prompt = (
        f"@{image_path.absolute().as_posix()}\n\n"
        f"Bu görseli haber kanalı YouTube Shorts kapağı olarak değerlendir. "
        f"GEVŞEK ol — haberin TEMASIYLA ilişkili olması yeterli, "
        f"kişinin yüzü/birebir yer şart değil.\n\n"
        f"HABER: {script.header_top} {script.header_bottom}\n"
        f"KATEGORİ: {script.category}\n"
        f"ÖZET: {summary}\n\n"
        f"ÜÇ AYRI KARAR VER:\n\n"
        f"1) appropriate (sıkı kriter): görsel haberin konusunu/temasını "
        f"yansıtıyor mu?\n"
        f"   - TRUE örnekler: Putin haberi → Putin/Kremlin/Rus bayrağı; "
        f"GS haberi → futbolcu/stadyum/GS logosu; ekonomi → para/grafik\n"
        f"   - FALSE örnekler: tamamen ilgisiz (savaş haberinde tatil, "
        f"futbol haberinde kedi resmi)\n\n"
        f"2) is_safe (gevşek minimum eşik): görsel uygunsuz içerik "
        f"İÇERMİYOR ve haber kategorisi için en azından kullanılabilir mi?\n"
        f"   - TRUE: şiddet/çıplaklık/müstehcen YOK, watermark/reklam ön "
        f"planda değil, kategoriyle uyumlu stok/jenerik görsel\n"
        f"   - FALSE: müstehcen/şiddet, kalın watermark, çocuk kitabı "
        f"kapağı, kategoriyle hiç uyuşmayan absürt görsel\n\n"
        f"3) has_text_overlay (OTOMATIK RED kriteri): görsel BURNED-IN büyük "
        f"metin/başlık içeriyor mu — başka bir haber sitesinin grafik kartı "
        f"gibi? Bu metin video frame'imize gömülür ve haberle çelişebilir "
        f"(örn. bizim script '45 gün' der ama görseldeki yazıda '15 gün' "
        f"geçer). Tam ekran kaplayan başlık metni varsa REDDEDİLİR.\n"
        f"   - TRUE: ekrana yapışık iri başlık/banner (Habertürk/CNN/Sözcü "
        f"tarzı haber kartı), tam ekran 'SON DAKİKA ATEŞKES UZATILDI' yazısı, "
        f"alt yazı + kanal logosu + başlık birleşimi\n"
        f"   - FALSE: doğal fotoğraf (politikacı, stadyum, mekan, ürün), "
        f"küçük köşe watermark/logo, TV anchor görüntüsü (sadece kişi, alt "
        f"chyron şerit yoksa veya çok küçükse), grafik (chart) ama büyük "
        f"başlık metni yoksa\n\n"
        f"appropriate her zaman is_safe'in alt kümesi olmalı "
        f"(appropriate=true ise is_safe=true).\n"
        f"has_text_overlay=true ise appropriate ve is_safe ne olursa olsun "
        f"GÖRSEL KULLANILMAZ.\n\n"
        f"SADECE JSON:\n"
        f'{{"appropriate": true|false, "is_safe": true|false, '
        f'"has_text_overlay": true|false, '
        f'"reason": "<kısa Türkçe açıklama, 1 cümle>"}}'
    )
    try:
        return run_json(prompt, _Verdict, claude_path=claude_path, retries=1, timeout_s=60)
    except ClaudeCliError as e:
        logger.warning(f"claude verification failed: {e}")
        return None


def build_search_query_for_channel(script: Script, channel: ChannelConfig) -> str:
    """Build DDG image search query using channel.dna.search_query_template if set.

    Post-processing:
      1. Dedupe consecutive/repeated words (case-insensitive). Opus often bakes
         redundant terms like 'NFL {category} NFL football' which expand to
         'NFL NFL NFL football' — DDG treats this as one weak signal.
      2. Append up to 3 channel keywords whose words aren't already in the
         query. Keeps queries channel-specific even when the template is
         generic (e.g. 'football' → adds 'american football' for NFL channel).
    """
    template = (
        channel.dna.search_query_template if channel.dna is not None
        else "{header_top} {header_bottom} {category}"
    )
    base_query = template.format(
        header_top=script.header_top,
        header_bottom=script.header_bottom,
        category=script.category,
        photo_overlay=script.photo_overlay,
    ).strip()

    # Dedupe (preserve first occurrence order)
    seen: set[str] = set()
    deduped_words: list[str] = []
    for w in base_query.split():
        wl = w.lower()
        if wl and wl not in seen:
            deduped_words.append(w)
            seen.add(wl)

    # Append channel keywords whose component words aren't already in seen
    for kw in (channel.keywords or [])[:3]:
        kw_words = [w.lower() for w in kw.split() if w]
        if not kw_words:
            continue
        if all(w in seen for w in kw_words):
            continue
        deduped_words.append(kw)
        seen.update(kw_words)

    return " ".join(deduped_words)


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
    """Source-by-source iteration: each source gets its own batch of candidates,
    Claude-verified until one is accepted. If all candidates from a source are
    rejected, the next source is tried (instead of giving up).

    Source order: DDG (orig) → DDG (ASCII normalize) → DDG (header_bottom only)
                  → Wikimedia (orig) → Wikimedia (normalize) → Pexels.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    normalized = _normalize_query(query)
    short_q = _normalize_query(script.header_bottom) if script.header_bottom else ""
    logger.info(
        f"image_picker queries: orig={query!r} ascii={normalized!r} "
        f"header={short_q!r}"
    )

    def _from_pexels() -> list[ImageCandidate]:
        try:
            from short_bot.pexels import (
                search_photos as _pexels_photos,
                resolve_pexels_api_key as _pexels_key,
                load_secrets as _pexels_secrets,
            )
            try:
                from flask import current_app
                secrets_path = current_app.config.get("SHORTBOT_SECRETS_PATH")
            except (ImportError, RuntimeError):
                secrets_path = None
            if secrets_path is None:
                secrets_path = Path("data") / "secrets.yaml"
            api_key = _pexels_key(_pexels_secrets(secrets_path))
            if not api_key:
                return []
            pexels_q = normalized or query
            results = _pexels_photos(pexels_q, api_key, max_results=max_candidates)
            return [
                ImageCandidate(url=p.url, thumbnail=p.url,
                               title=f"Pexels #{p.id}",
                               source_domain="pexels.com",
                               width=p.width, height=p.height)
                for p in results
            ]
        except Exception as e:
            logger.warning(f"Pexels source failed: {e}")
            return []

    def _from_wikimedia(q: str) -> list[ImageCandidate]:
        try:
            from short_bot.wikimedia_search import search_images_commons
            return search_images_commons(q, max_results=max_candidates)
        except Exception as e:
            logger.warning(f"Wikimedia source failed: {e}")
            return []

    sources: list[tuple[str, callable]] = [
        ("DDG (orig)",         lambda: search_images(query, max_results=max_candidates)),
    ]
    if normalized and normalized != query:
        sources.append(
            ("DDG (ASCII)",    lambda: search_images(normalized, max_results=max_candidates))
        )
    if short_q and short_q != query and short_q != normalized:
        sources.append(
            ("DDG (header)",   lambda: search_images(short_q, max_results=max_candidates))
        )
    sources.append(("Wikimedia (orig)", lambda: _from_wikimedia(query)))
    if normalized and normalized != query:
        sources.append(("Wikimedia (ASCII)", lambda: _from_wikimedia(normalized)))
    sources.append(("Pexels", _from_pexels))

    # Track the first is_safe-but-not-appropriate candidate as a last-resort
    # fallback. Used only when every source rejects on `appropriate`. This
    # prevents the "5 sources searched, 10 candidates all rejected, no video"
    # outcome on stories where the search returns thematic but not exact
    # matches (e.g. Russian flag for a Putin announcement story).
    last_resort_safe: Path | None = None
    last_resort_reason: str = ""

    for source_name, fetch in sources:
        try:
            candidates = fetch()
        except Exception as e:
            logger.warning(f"{source_name}: search failed: {e}")
            continue
        if not candidates:
            logger.info(f"{source_name}: 0 sonuc, sonraki kaynak deneniyor")
            continue
        logger.info(f"{source_name}: {len(candidates)} aday, Claude verify ediliyor")

        for i, cand in enumerate(candidates):
            key = hashlib.sha1(cand.url.encode("utf-8")).hexdigest()[:16]
            path = cache_dir / f"{key}.jpg"
            if not path.exists():
                if not _download(cand.url, path):
                    continue
            verdict = _verify_with_claude(path, script, claude_path)
            if verdict is None:
                logger.warning(f"  {source_name} cand {i}: verification CLI failed -> skip")
                continue
            # Hard reject: burned-in news graphic with embedded headline. These
            # contradict our own script (e.g. '45 gün' vs image's '15 gün').
            # Skip entirely — do not promote to last-resort fallback either.
            if verdict.has_text_overlay:
                logger.warning(
                    f"  {source_name} cand {i} REJECTED (text overlay): {verdict.reason}"
                )
                continue
            if verdict.appropriate:
                logger.warning(f"  {source_name} cand {i} ACCEPTED: {verdict.reason}")
                return path
            if last_resort_safe is None and verdict.is_safe:
                last_resort_safe = path
                last_resort_reason = verdict.reason
                logger.info(
                    f"  {source_name} cand {i} safe (not appropriate): "
                    f"saved as last-resort fallback — {verdict.reason}"
                )
            logger.warning(f"  {source_name} cand {i} rejected: {verdict.reason}")

        logger.info(f"{source_name}: tum adaylar reddedildi, sonraki kaynak")

    if last_resort_safe is not None:
        logger.warning(
            f"no source returned an appropriate image — using last-resort "
            f"safe candidate {last_resort_safe.name} ({last_resort_reason})"
        )
        return last_resort_safe
    logger.warning("no image accepted from any source after all fallbacks")
    return None
