"""Pipeline orchestrator: runs all 8 stages, persists to DB, writes per-run log."""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock, Timeout

from short_bot.config import ChannelConfig, Settings
from short_bot.db import (
    init_db, mark_processed, record_short, record_rss_item,
    start_run, finish_run, get_last_youtube_upload_at,
)
from short_bot.youtube import auth as _yt_auth
from short_bot.youtube.auto_upload import (
    should_auto_upload, run_auto_upload,
)
from short_bot.models import RenderJob
from short_bot.fetcher import fetch_rss
from short_bot.dedup import filter_new
from short_bot.scorer import score_items, select_top
from short_bot.extractor import (
    extract_article,
    extract_og_image_url,
    _is_google_news_url,
)
from short_bot.script_writer import write_script
from short_bot.assets import download_and_blur_thumb, pick_music
from short_bot.renderer import render_frames, build_html
from short_bot.overflow import (
    OverflowReport,
    check_overflow,
    format_feedback,
    truncate_to_fit,
)
from short_bot.templates_config import ARCHETYPE_OVERFLOW_FIELDS
from short_bot.composer import compose_video, compose_video_from_silent_video
from short_bot.locale import ui_labels_for
from short_bot.generator import (
    GeneratorRetryExhausted, check_duplicate, generate_quote,
)
from short_bot.generated_db import (
    insert_generated, recent_generated_texts, topic_distribution,
    update_generated_short_id,
)
from short_bot.image_picker import pick_image_for_generator
import os
import secrets as _secrets_mod  # avoid shadowing the local `secrets_path` var
import short_bot.pexels as _pexels_mod
from short_bot.pexels import (
    load_secrets as _load_secrets,
    pick_query_for_archetype,
    resolve_pexels_api_key,
    resolve_openai_api_key,
)
from short_bot.dna import DnaSpec, build_css_override, generate_dna_for_video
from short_bot.dna_cache import (
    increment_hit_count, lookup_cached_dna, save_cached_dna,
)
from short_bot.embeddings import EmbeddingError, embed_text
from short_bot.locale import trend_region_for
from short_bot.models import ScoredItem

_GENERATOR_TOPIC_DIST_DAYS = 7   # window for topic_distribution Sonnet hint
_IMAGE_RETRY_MAX = 3   # try this many top candidates before giving up on image


def _is_recent(pub_date: datetime | None, cutoff: datetime) -> bool:
    """True if pub_date is at or after cutoff. Items without pub_date are rejected
    (Google News normally provides one — missing date most often means a re-syndicated
    aggregator entry with no fresh signal)."""
    if pub_date is None:
        return False
    aware = pub_date if pub_date.tzinfo else pub_date.replace(tzinfo=timezone.utc)
    return aware >= cutoff


def _filter_negative_keywords(items: list, negative_keywords: list[str]) -> list:
    """Drop items whose title contains any negative keyword (case-insensitive substring)."""
    if not negative_keywords:
        return items
    needles = [k.strip().lower() for k in negative_keywords if k.strip()]
    if not needles:
        return items
    return [
        i for i in items
        if not any(n in i.title.lower() for n in needles)
    ]


def _apply_trend_boost(
    scored: list[ScoredItem],
    *,
    channel: ChannelConfig,
    settings: Settings,
    cache_dir: Path,
    secrets_path: Path,
    log: logging.Logger,
) -> list[ScoredItem]:
    """Augment each ScoredItem.score by +trend_boost when its headline
    matches a currently trending term in the channel's region.

    Graceful: any failure (no cache, no api key, network error) returns
    the input list unchanged. Boost amount + matched term shown in log.
    """
    if channel.trend_boost is None or not channel.trend_boost.enabled:
        return scored
    if not settings.trends.enabled:
        log.info("  [trends] settings.trends.enabled=false -- skipping boost")
        return scored
    if not scored:
        return scored

    from short_bot.trends.aggregator import get_or_refresh
    from short_bot.trends.matcher import compute_trend_boost

    tb = channel.trend_boost
    region = tb.region_override or trend_region_for(channel.language)
    sources = list(tb.sources) if tb.sources else list(settings.trends.default_sources)
    secrets = _load_secrets(secrets_path)
    yt_key = secrets.get("youtube_api_key", "") or ""

    try:
        cache = get_or_refresh(
            region, sources=sources, youtube_api_key=yt_key,
            cache_dir=cache_dir / "trends",
            max_age_minutes=settings.trends.cache_max_age_minutes,
        )
    except Exception as e:  # noqa: BLE001 -- never let trend fetch break pipeline
        log.warning(f"  [trends] fetch failed: {e} -- skipping boost")
        return scored

    if cache is None or not cache.items:
        log.info(f"  [trends] no trends loaded for region={region} -- skipping boost")
        return scored

    log.info(f"  [trends] {len(cache.items)} terms (region={region}, "
             f"age={cache.age_minutes():.0f}m, sources={','.join(cache.sources)})")

    boosted: list[ScoredItem] = []
    boost_count = 0
    for s in scored:
        boost, matches = compute_trend_boost(
            s.item.title, cache.items,
            max_boost=tb.max_boost,
            min_term_length=tb.min_term_length,
            exclude_terms=tb.exclude_terms,
            fuzzy_threshold=tb.fuzzy_threshold,
        )
        if boost <= 0:
            boosted.append(s)
            continue
        new_score = min(10.0, s.score + boost)
        boost_count += 1
        top = matches[0]
        log.info(
            f"  trend boost +{boost:.2f} "
            f"[{top.match_type} rank#{top.item.rank} '{top.item.term[:60]}'] "
            f"{s.score:.1f}->{new_score:.1f} | {s.item.title[:70]}"
        )
        boosted.append(ScoredItem(
            item=s.item,
            score=new_score,
            reasoning=f"{s.reasoning} [trend+{boost:.2f}]",
        ))

    if boost_count == 0:
        log.info("  [trends] no candidate headlines matched any trending term")
    else:
        log.info(f"  [trends] {boost_count}/{len(scored)} item(s) boosted")
    return boosted


def _resolve_dna_for_video(
    *,
    channel: ChannelConfig,
    headline: str,
    body: str,
    log: logging.Logger,
    claude_path: str,
    secrets_path: Path,
    templates_dir: Path,
    eng,
) -> tuple[DnaSpec, Path] | None:
    """For dynamic_dna channels: lookup cache or generate per-video DNA.

    Returns (dna, css_path) on success or None on any failure
    (caller falls back to channel.dna or channel.template).
    """
    if not channel.dynamic_dna:
        return None

    topic_text = f"{headline}\n{body[:200]}"

    # 1. Resolve key + embed
    api_key = resolve_openai_api_key(_load_secrets(secrets_path))
    if not api_key:
        log.warning("  [dna] no openai_api_key configured → fallback to static")
        return None
    try:
        emb = embed_text(topic_text, api_key=api_key)
    except EmbeddingError as e:
        log.warning(f"  [dna] embedding failed: {e} → fallback to static")
        return None

    css_dir = templates_dir / "css"

    # 2. Cache lookup
    hit = lookup_cached_dna(eng, channel.slug, emb, threshold=0.85)
    if hit is not None:
        css_path = css_dir / hit.css_filename
        if css_path.exists():
            log.info(
                f"  [dna] cache HIT id={hit.id} archetype={hit.archetype} "
                f"(cos={hit.score:.3f})"
            )
            increment_hit_count(eng, hit.id)
            return hit.dna, css_path
        # CSS missing on disk (manual cleanup, etc.) — treat as miss, fall through
        log.warning(
            f"  [dna] cache HIT id={hit.id} but {css_path.name} missing → regenerating"
        )

    # 3. Cache miss → generate
    log.info("  [dna] cache MISS → generating (Opus)…")
    try:
        dna = generate_dna_for_video(
            channel=channel, headline=headline, body=body,
            claude_path=claude_path,
        )
    except Exception as e:  # broad: timeout, JSON parse, validation, etc.
        log.warning(f"  [dna] generation failed: {e} → fallback to static")
        return None

    # 4. Save (DNA + CSS file + cache row)
    try:
        css_text = build_css_override(dna)
        css_filename = f"dynamic-{channel.slug}-{_secrets_mod.token_hex(3)}.css"
        css_path = css_dir / css_filename
        css_dir.mkdir(parents=True, exist_ok=True)
        css_path.write_text(css_text, encoding="utf-8")
        save_cached_dna(eng, channel.slug, topic_text, emb, dna, css_filename)
        log.info(f"  [dna] saved: archetype={dna.archetype} css={css_filename}")
        return dna, css_path
    except OSError as e:
        log.warning(f"  [dna] save failed: {e} → fallback to static")
        return None


def _resolve_ui_labels(channel: ChannelConfig) -> dict[str, str]:
    labels = dict(ui_labels_for(channel.language))
    if channel.dna and channel.dna.ui_badge.strip():
        labels["breaking"] = channel.dna.ui_badge.strip()
    return labels


def _maybe_auto_upload(*, eng, short_id: int, channel, picked_score: float | None,
                       log, yt_creds_root: Path, claude_path: str,
                       model: str, cooldown_minutes: int = 5,
                       secrets_path: Path | None = None) -> None:
    """Post-render hook: if channel opts in, evaluate gates + run upload."""
    if channel.youtube is None or not channel.youtube.auto_upload:
        return
    # Token refresh için proxy session hazır olsun (varsa)
    proxy_session = None
    if secrets_path:
        from short_bot.youtube.proxy import (
            load_channel_proxy_url, build_proxied_requests_session,
        )
        proxy_url = load_channel_proxy_url(channel.slug, secrets_path)
        if proxy_url:
            proxy_session = build_proxied_requests_session(proxy_url)
    creds = _yt_auth.load_credentials(
        yt_creds_root, channel.slug, proxy_session=proxy_session,
    )
    if creds is None:
        log.info("[YT] auto-upload atlandı — kanal bağlanmamış (token.json yok)")
        return
    last_at = get_last_youtube_upload_at(eng)
    decision = should_auto_upload(
        channel=channel, picked_score=picked_score,
        last_upload_at=last_at, cooldown_minutes=cooldown_minutes,
    )
    if not decision.eligible:
        log.info(f"[YT] auto-upload atlandı — {decision.reason}")
        return
    log.info(f"[YT] auto-upload başlıyor (short {short_id})")
    try:
        result = run_auto_upload(
            eng=eng, short_id=short_id, channel=channel,
            credentials=creds, claude_path=claude_path, model=model,
            secrets_path=secrets_path,
        )
        log.info(f"[YT] auto-upload başarılı: {result.video_url}")
    except Exception as e:
        log.warning(f"[YT] auto-upload hatası: {e}")


@dataclass
class RunResult:
    run_id: int
    status: str           # 'success' | 'failed' | 'no_candidates'
    short_path: Path | None
    error: str | None


def _slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len] or "haber"


def _build_cta_sfx(channel) -> list:
    """Build SFX overlay schedule for the CTA window. Returns empty if SFX missing."""
    from short_bot.composer import SfxOverlay
    sfx_dir = Path("assets/sfx")
    whoosh = sfx_dir / "whoosh.mp3"
    pop = sfx_dir / "pop.mp3"
    ding = sfx_dir / "ding.mp3"
    if not (whoosh.exists() and pop.exists() and ding.exists()):
        return []  # SFX optional — silent if files missing
    if not channel.cta_enabled:
        return []

    cta_start_ms = (channel.duration_s - channel.cta_duration_s) * 1000
    # Timings match the CSS animations in the template:
    #   handle-drop:  +0.05s
    #   sub-pop:      +0.15s   ← whoosh here (entrance)
    #   icon-pop #1:  +0.25s   ← pop1
    #   icon-pop #2:  +0.40s   ← pop2
    #   icon-pop #3:  +0.55s   ← pop3
    #   sub-press:    +0.55s   ← ding (subscribe tap)
    return [
        SfxOverlay(path=whoosh, delay_ms=cta_start_ms + 100, volume=0.6),
        SfxOverlay(path=pop, delay_ms=cta_start_ms + 250, volume=0.5),
        SfxOverlay(path=pop, delay_ms=cta_start_ms + 400, volume=0.5),
        SfxOverlay(path=pop, delay_ms=cta_start_ms + 550, volume=0.5),
        SfxOverlay(path=ding, delay_ms=cta_start_ms + 550, volume=0.55),
    ]


_RUN_SUB_LOGGERS = (
    "short_bot.assets",
    "short_bot.claude_cli",
    "short_bot.composer",
    "short_bot.dedup",
    "short_bot.dna",
    "short_bot.dna_smoke",
    "short_bot.extractor",
    "short_bot.fetcher",
    "short_bot.generator",
    "short_bot.image_picker",
    "short_bot.image_search",
    "short_bot.pexels",
    "short_bot.renderer",
    "short_bot.scorer",
    "short_bot.script_writer",
    "short_bot.wikimedia_search",
    "short_bot.youtube.auth",
    "short_bot.youtube.uploader",
)


# Thread-local active run path so concurrent pipeline runs (different
# channels firing in parallel) keep their sub-logger output (image_picker,
# scorer, etc.) inside their own log files. Without this, every run's
# FileHandler is attached to the same shared sub-logger and they all
# receive every log record — galatasaray's run log was getting NFL/Putin
# query lines from other channels' concurrent runs.
_active_run = threading.local()


def _set_active_run_log_path(log_path: str) -> None:
    _active_run.log_path = log_path


def _clear_active_run_log_path() -> None:
    if hasattr(_active_run, "log_path"):
        del _active_run.log_path


class _RunFileFilter(logging.Filter):
    """Only let a record through if the calling thread's active run log
    path matches the handler's log path."""

    def __init__(self, log_path: str) -> None:
        super().__init__()
        self._log_path = log_path

    def filter(self, record: logging.LogRecord) -> bool:
        active = getattr(_active_run, "log_path", None)
        return active == self._log_path


def _setup_logger(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"shortbot.run.{log_path.stem}")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(sh)
    # Forward asset-fase module logs to this run's file so failure reasons
    # (DDG empty, Claude vision reject, etc.) show up in the run log.
    sub_fmt = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
    log_path_str = str(log_path)
    for name in _RUN_SUB_LOGGERS:
        sub = logging.getLogger(name)
        sub.setLevel(logging.INFO)
        sub_fh = logging.FileHandler(log_path, encoding="utf-8")
        sub_fh.setFormatter(sub_fmt)
        sub_fh.addFilter(_RunFileFilter(log_path_str))
        sub_fh._shortbot_run = True
        sub.addHandler(sub_fh)
    return logger


def _teardown_logger(log: logging.Logger) -> None:
    for h in list(log.handlers):
        try:
            h.close()
        except Exception:
            pass
        log.removeHandler(h)
    for name in _RUN_SUB_LOGGERS:
        sub = logging.getLogger(name)
        for h in list(sub.handlers):
            if getattr(h, "_shortbot_run", False):
                try:
                    h.close()
                except Exception:
                    pass
                sub.removeHandler(h)


def _resolve_pexels_bg(*, channel, cache_dir, secrets_path, log) -> Path | None:
    """Search/download a Pexels bg video for `channel`. None on opt-out / failure."""
    if channel.bg_video is None or not channel.bg_video.enabled:
        return None
    api_key = resolve_pexels_api_key(_load_secrets(secrets_path))
    if not api_key:
        log.warning("  bg_video enabled but PEXELS_API_KEY not set → fallback")
        return None
    archetype = (channel.dna.archetype if channel.dna is not None
                 else channel.template)
    query = pick_query_for_archetype(archetype)
    log.info(f"  pexels search: query={query!r}")
    candidates = _pexels_mod.search_videos(query, api_key, max_results=8)
    if not candidates:
        log.warning("  pexels: no candidates returned → fallback")
        return None
    # Shuffle candidates so successive runs don't always pick the FIRST
    # (most popular) result. Combined with random page in search_videos this
    # gives reasonable variety across renders for the same channel.
    import random as _rand
    _rand.shuffle(candidates)
    bg_cache = Path(cache_dir) / "pexels_videos"
    for cand in candidates:
        path = _pexels_mod.download_video(cand.url, bg_cache)
        if path is not None:
            log.info(f"  pexels accepted: {path.name} (id={cand.id})")
            return path
    log.warning("  pexels: all candidate downloads failed → fallback")
    return None


def current_app_secrets_path() -> Path:
    """Resolve the secrets path (data/secrets.yaml relative to cwd).

    Pipeline runs both inside Flask (web 'Run now') and standalone (CLI/cron).
    Keep simple: data/secrets.yaml next to the cwd's data directory. If a project-level
    DATA_DIR helper exists in the future, swap to that — but don't refactor for it now."""
    return Path("data") / "secrets.yaml"


def run_pipeline(
    *,
    channel: ChannelConfig,
    settings: Settings,
    db_path: Path,
    music_root: Path,
    templates_dir: Path,
    cache_dir: Path,
    logs_dir: Path,
    lock_dir: Path | None = None,
    trigger: str = "cli",
) -> RunResult:
    eng = init_db(db_path)
    log_path = logs_dir / f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{channel.slug}.log"
    log_rel = str(log_path)
    log = _setup_logger(log_path)
    _set_active_run_log_path(str(log_path))
    run_id = start_run(eng, channel.slug, trigger=trigger, log_path=log_rel)

    lock_dir = Path(lock_dir) if lock_dir else Path("data/locks")
    lock_path = lock_dir / f"{channel.slug}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_path), timeout=0)

    try:
        try:
            with lock:
                log.info(f"=== run {run_id} channel={channel.slug} "
                         f"trigger={trigger} source={channel.content_source} ===")
                if channel.content_source == "generator":
                    return _run_generator(
                        channel=channel, run_id=run_id, log=log, eng=eng,
                        settings=settings, music_root=music_root,
                        templates_dir=templates_dir, cache_dir=cache_dir,
                    )
                return _run_rss(
                    channel=channel, run_id=run_id, log=log, eng=eng,
                    settings=settings, music_root=music_root,
                    templates_dir=templates_dir, cache_dir=cache_dir,
                )
        except Timeout:
            finish_run(eng, run_id, status="failed", short_id=None,
                       error="lock busy: pipeline already running for this channel")
            return RunResult(run_id=run_id, status="failed", short_path=None,
                             error="lock busy")
        except Exception as e:
            log.exception("pipeline failed")
            finish_run(eng, run_id, status="failed", short_id=None, error=str(e))
            return RunResult(run_id=run_id, status="failed", short_path=None, error=str(e))
    finally:
        _teardown_logger(log)
        _clear_active_run_log_path()
        # Dispose engine to release the SQLite connection pool (CLI use case)
        eng.dispose()


def _run_rss(*, channel, run_id, log, eng, settings,
             music_root, templates_dir, cache_dir) -> RunResult:
    """Existing 8-stage RSS pipeline body, extracted verbatim. Returns RunResult."""
    log.info("[1/8] fetch_rss")
    items = fetch_rss(channel.keywords, channel.rss_locale)
    log.info(f"  → {len(items)} items")

    if channel.max_age_hours > 0:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=channel.max_age_hours)
        before = len(items)
        items = [i for i in items if _is_recent(i.pub_date, cutoff)]
        if before != len(items):
            log.info(f"  → {len(items)} after age filter "
                      f"(<= {channel.max_age_hours}h, dropped {before - len(items)})")
    # NEW: negative keyword filter
    if channel.negative_keywords:
        before = len(items)
        items = _filter_negative_keywords(items, channel.negative_keywords)
        if before != len(items):
            log.info(f"  → {len(items)} after negative keyword filter (dropped {before - len(items)})")

    log.info("[2/8] dedup")
    # Topic-level dedup via OpenAI embeddings (in addition to GUID + fuzzy
    # title) — catches the multi-publisher-same-story case where two
    # videos for the same Icardi/Osimhen news pass through because GUIDs
    # and headlines differ. Graceful degradation if no API key configured.
    secrets_path_for_dedup = (
        (Path(eng.url.database).parent / "secrets.yaml").resolve()
        if eng.url.database else Path("data/secrets.yaml").resolve()
    )
    try:
        dedup_openai_key = resolve_openai_api_key(_load_secrets(secrets_path_for_dedup))
    except Exception:
        dedup_openai_key = ""
    dedup_embeddings: dict[str, list[float]] = {}
    new_items = filter_new(
        eng, items, channel.slug,
        fuzzy_threshold=settings.fuzzy_dedup_threshold,
        openai_api_key=dedup_openai_key or None,
        embeddings_out=dedup_embeddings,
    )
    log.info(f"  → {len(new_items)} new"
             f"{' (embedding-dedup active)' if dedup_openai_key else ''}")
    # Record only fuzzy-similar dropped items (not GUID-exact duplicates,
    # which would bloat rss_items on every poll for the same headline)
    from short_bot.db import is_processed
    new_guids = {n.guid for n in new_items}
    for old in items:
        if old.guid in new_guids:
            continue
        if is_processed(eng, old.guid, channel.slug):
            continue  # GUID-exact, already in processed_items, skip
        # Fuzzy-similar: log it for the panel
        record_rss_item(eng, guid=old.guid, channel=channel.slug,
                        title=old.title, link=old.link, source=old.source,
                        pub_date=old.pub_date, thumb_url=old.thumb_url,
                        score=None, status="duplicate")

    if not new_items:
        log.info("no candidates → finish")
        finish_run(eng, run_id, status="no_candidates", short_id=None, error=None)
        return RunResult(run_id=run_id, status="no_candidates", short_path=None, error=None)

    log.info("[3/8] score_items")
    candidates = new_items[:channel.max_candidates_per_run]
    # Load cached insights (computed nightly + on-demand from /insights page).
    # When sparse or absent the formatter returns "" so the scorer prompt
    # stays unchanged — strictly additive feature.
    perf_insights = None
    try:
        from short_bot.db import load_channel_insights
        perf_insights = load_channel_insights(eng, channel.slug)
        if perf_insights:
            log.info(
                f"  [insights] loaded (sample_size="
                f"{perf_insights.get('sample_size', 0)})"
            )
    except Exception as e:  # noqa: BLE001 -- never let insights crash pipeline
        log.warning(f"  [insights] load failed: {e} -- skipping injection")
    scored = score_items(
        candidates,
        claude_path=settings.claude_cli_path,
        model=settings.claude_models.get("default", "haiku"),
        channel=channel,
        performance_insights=perf_insights,
    )
    # Trend boost: augment scores when a candidate headline matches a
    # currently trending term in the channel's region. Best-effort -- any
    # failure leaves scores untouched.
    secrets_path_for_trends = (
        (Path(eng.url.database).parent / "secrets.yaml").resolve()
        if eng.url.database else Path("data/secrets.yaml").resolve()
    )
    scored = _apply_trend_boost(
        scored, channel=channel, settings=settings,
        cache_dir=Path(cache_dir),
        secrets_path=secrets_path_for_trends, log=log,
    )
    top_n_candidates = select_top(scored, min_score=channel.min_score,
                                  n=_IMAGE_RETRY_MAX)
    if not top_n_candidates:
        log.info(f"no item ≥ {channel.min_score} → finish")
        for s in scored:
            record_rss_item(eng, guid=s.item.guid, channel=channel.slug,
                            title=s.item.title, link=s.item.link, source=s.item.source,
                            pub_date=s.item.pub_date, thumb_url=s.item.thumb_url,
                            score=s.score, status="below_threshold")
        # Show top 3 for calibration / debug
        top_seen = sorted(scored, key=lambda s: s.score, reverse=True)[:3]
        for i, s in enumerate(top_seen, 1):
            log.info(f"  top#{i} score={s.score:.1f} | {s.item.title[:80]}")
        finish_run(eng, run_id, status="no_candidates", short_id=None, error=None)
        return RunResult(run_id=run_id, status="no_candidates", short_path=None, error=None)

    log.info(f"  → {len(top_n_candidates)} candidate(s) ≥ {channel.min_score} "
             f"(retry-on-no-image up to {_IMAGE_RETRY_MAX})")
    top_guids = {c.item.guid for c in top_n_candidates}

    script_model = (channel.script_model
                    or settings.claude_models.get("script")
                    or settings.claude_models.get("default", "haiku"))

    picked = None
    body = None
    script = None
    bg = None
    for attempt, candidate in enumerate(top_n_candidates, 1):
        log.info(f"[4-6/8] candidate {attempt}/{len(top_n_candidates)} "
                 f"score={candidate.score:.1f} | {candidate.item.title[:80]}")

        # Resolve google-news redirect URLs to the publisher URL so BOTH the
        # body extractor AND the og:image fetch see the real article page
        # (mynet.com.tr / sozcu.com.tr etc.) instead of Google's JS-redirect
        # interstitial. Costs ~3-5s per resolve via Playwright; this is
        # cheaper than falling through to DDG search + Claude vision verify
        # AND it eliminates the "burned-in news graphic" failure mode (the
        # publisher's own og:image is by construction the right photo).
        article_url = candidate.item.link
        if _is_google_news_url(article_url):
            from short_bot.google_news_resolver import resolve as _resolve_gnews
            resolved = _resolve_gnews(article_url)
            if resolved:
                log.info(f"  resolved gnews → {resolved[:90]}")
                article_url = resolved
            else:
                log.info("  gnews resolve failed — using raw URL (body/og may be empty)")

        log.info("  extract_article")
        body_try = extract_article(article_url)
        if body_try is None:
            body_try = candidate.item.description or candidate.item.title
            log.warning("  trafilatura empty → fallback description")
        log.info(f"  → body {len(body_try)} chars")

        log.info(f"  write_script (model={script_model})")
        if channel.template in ARCHETYPE_OVERFLOW_FIELDS:
            template_path = templates_dir / f"{channel.template}.html.j2"
            script_try, _overflow_retries = write_script_with_overflow_check(
                item=candidate.item,
                body_html=body_try,
                channel=channel,
                template_path=template_path,
                job_template_args={
                    "music_path": Path("dummy.mp3"),
                    "ui_language": channel.language,
                },
                max_retries=2,
                log=log,
                claude_path=settings.claude_cli_path,
                model=script_model,
            )
        else:
            log.info(f"  template '{channel.template}' not in overflow config "
                     f"— skipping overflow check")
            script_try = write_script(
                candidate.item, body_try,
                claude_path=settings.claude_cli_path,
                channel=channel, model=script_model,
            )
        log.info(f"  → {script_try.header_top} | {script_try.header_bottom}")

        log.info("  assets/image")
        bg_try = None
        original_was_gnews = _is_google_news_url(candidate.item.link)
        # 1. og:image — publisher's actual hero photo. When the original RSS
        # URL was a google-news redirect, `article_url` was resolved above
        # to the publisher's real page, so og:image now reads the real hero
        # photo (mynet/sozcu/etc.) instead of Google's generic CDN preview.
        og_url = extract_og_image_url(article_url)
        if og_url:
            log.info(f"  og:image: {og_url[:100]}")
            bg_try = download_and_blur_thumb(og_url, cache_dir)
            if bg_try:
                log.info(f"  og:image accepted: {bg_try.name}")
        # 2. RSS thumb fallback (publisher media:thumbnail). Still skipped
        # when the original was google-news -- the thumb on those feeds is
        # always Google's generic publisher logo, identical across articles.
        if bg_try is None and not original_was_gnews and candidate.item.thumb_url:
            bg_try = download_and_blur_thumb(candidate.item.thumb_url, cache_dir)
        # 3. DDG/Wikimedia/Pexels search fallback.
        if bg_try is None:
            from short_bot.image_picker import pick_image_for_script
            images_cache = cache_dir / "images"
            bg_try = pick_image_for_script(script_try, images_cache,
                                           claude_path=settings.claude_cli_path,
                                           channel=channel)
            if bg_try:
                log.info(f"  ddg image accepted: {bg_try.name}")

        if bg_try is None:
            log.warning(f"  candidate {attempt} no image → image_rejected, trying next")
            record_rss_item(eng, guid=candidate.item.guid, channel=channel.slug,
                            title=candidate.item.title, link=candidate.item.link,
                            source=candidate.item.source, pub_date=candidate.item.pub_date,
                            thumb_url=candidate.item.thumb_url, score=candidate.score,
                            status="image_rejected")
            continue

        picked = candidate
        body = body_try
        script = script_try
        bg = bg_try
        log.info(f"  → picked {picked.item.guid} (attempt {attempt})")
        break

    # Record below_threshold items (those not in top_n)
    for s in scored:
        if s.item.guid not in top_guids:
            record_rss_item(eng, guid=s.item.guid, channel=channel.slug,
                            title=s.item.title, link=s.item.link, source=s.item.source,
                            pub_date=s.item.pub_date, thumb_url=s.item.thumb_url,
                            score=s.score, status="below_threshold")

    if picked is None:
        msg = f"no usable image after {len(top_n_candidates)} candidates"
        log.warning(f"{msg} → finish")
        finish_run(eng, run_id, status="no_candidates", short_id=None, error=msg)
        return RunResult(run_id=run_id, status="no_candidates",
                         short_path=None, error=msg)

    record_rss_item(eng, guid=picked.item.guid, channel=channel.slug,
                    title=picked.item.title, link=picked.item.link,
                    source=picked.item.source, pub_date=picked.item.pub_date,
                    thumb_url=picked.item.thumb_url, score=picked.score,
                    status="selected")

    music = pick_music(music_root, mood=script.mood, channel_slug=channel.slug)
    log.info(f"  → bg={'cached' if bg else 'none'} music={music.name}")

    log.info("[7/8] render_frames")
    job = RenderJob(
        script=script,
        bg_image_path=bg,
        music_path=music,
        channel_colors=channel.colors,
        handle=channel.handle,
        duration_s=channel.duration_s,
        language=channel.language,
        cta_enabled=channel.cta_enabled,
        cta_text=channel.cta_text,
        cta_icons=channel.cta_icons,
        cta_duration_s=channel.cta_duration_s,
        cta_show_handle=channel.cta_show_handle,
        rss_source=picked.item.source if picked else None,
    )

    with tempfile.TemporaryDirectory() as tmpd:
        frames_dir = Path(tmpd) / "frames"
        t0 = time.perf_counter()
        ui_labels = _resolve_ui_labels(channel)
        # Resolve effective DNA (per-video for dynamic_dna channels; else channel-level).
        # Note: overflow check ran earlier against channel.template; if the dynamic DNA
        # picks a different archetype the rendered video uses it but overflow was not
        # re-checked. Acceptable risk — fallback is always channel.dna or template.
        from short_bot.dna import build_css_override
        effective_dna = channel.dna
        secrets_path = current_app_secrets_path()
        resolved = _resolve_dna_for_video(
            channel=channel,
            headline=f"{script.header_top} {script.header_bottom}",
            body=script.body_paragraph,
            log=log, claude_path=settings.claude_cli_path,
            secrets_path=secrets_path, templates_dir=templates_dir, eng=eng,
        )
        if resolved is not None:
            effective_dna, css_path = resolved
            dna_css = css_path.read_text(encoding="utf-8")
        else:
            dna_css = build_css_override(channel.dna) if channel.dna else ""
        archetype = effective_dna.archetype if effective_dna is not None else channel.template

        log.info("[8/8] compose_video")
        out_dir = Path(channel.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(picked.item.title)
        out_path = out_dir / f"{datetime.now(timezone.utc):%Y-%m-%d}_{slug}.mp4"

        sfx_overlays = _build_cta_sfx(channel)
        bg_video_path = _resolve_pexels_bg(
            channel=channel, cache_dir=cache_dir,
            secrets_path=secrets_path, log=log,
        )
        bv = channel.bg_video

        if channel.renderer == "remotion":
            from short_bot.remotion_renderer import (
                render as remotion_render,
                render_job_from_pipeline,
                ensure_remotion_installed,
                RemotionRenderError,
            )
            # ensure_remotion_installed is idempotent: no-op when node_modules
            # already present, otherwise runs `npm install` (~2 min once).
            # render() also does this internally, but calling it here surfaces
            # any install error to the run log with the right context.
            try:
                ensure_remotion_installed(log=log)
            except RemotionRenderError as e:
                raise RuntimeError(
                    f"channel.renderer='remotion' but install failed: {e}"
                ) from e
            silent_path = Path(tmpd) / "remotion-silent.mp4"
            remotion_job = render_job_from_pipeline(
                script=script,
                channel_colors=channel.colors,
                handle=channel.handle,
                duration_s=channel.duration_s,
                template=channel.resolved_remotion_template,
                bg_image_path=bg,
                dimensions=channel.remotion_dimensions,
            )
            log.info(f"  → remotion render {remotion_job.template}")
            try:
                remotion_render(remotion_job, silent_path)
            except RemotionRenderError as e:
                raise RuntimeError(f"Remotion render failed: {e}") from e
            compose_video_from_silent_video(
                silent_path, music, out_path,
                ffmpeg_path=settings.ffmpeg_path,
                sfx_overlays=sfx_overlays,
                bg_video_path=bg_video_path,
                bg_blur_px=bv.blur_px if bv else 30,
                bg_dim=bv.dim if bv else 0.4,
                fg_scale=bv.scale if (bv and bg_video_path) else 1.0,
                duration_s=channel.duration_s,
            )
        else:
            template_path = templates_dir / f"{archetype}.html.j2"
            render_frames(job, template_path, frames_dir,
                          fps=30, browser=settings.playwright_browser,
                          ui_labels=ui_labels, dna_css=dna_css,
                          animation_style=(effective_dna.animation_style
                                            if effective_dna is not None else "none"))
            compose_video(
                frames_dir, music, out_path,
                fps=30, ffmpeg_path=settings.ffmpeg_path,
                sfx_overlays=sfx_overlays,
                bg_video_path=bg_video_path,
                bg_blur_px=bv.blur_px if bv else 30,
                bg_dim=bv.dim if bv else 0.4,
                fg_scale=bv.scale if (bv and bg_video_path) else 1.0,
                duration_s=channel.duration_s,
            )
        render_ms = int((time.perf_counter() - t0) * 1000)
        log.info(f"  → {out_path.name} ({render_ms}ms) renderer={channel.renderer}")

    # Compute embedding of the Claude-PRODUCED headline too — drives the new
    # "produced-headline dedup" layer in dedup.filter_new on future runs.
    # Best-effort: any failure leaves it NULL and we still benefit from the
    # RSS-side dedup. Reuses the same OpenAI key as RSS-side embedding.
    produced_embedding = None
    try:
        if dedup_openai_key:
            produced_text = (
                f"{script.header_top} {script.header_bottom}".strip()
            )
            if produced_text:
                from short_bot.embeddings import embed_text as _embed
                produced_embedding = _embed(produced_text, api_key=dedup_openai_key)
    except Exception as e:  # noqa: BLE001 — never block render success
        log.warning(f"  produced-title embedding failed: {e}")

    mark_processed(
        eng, picked.item.guid, picked.item.title, channel.slug,
        embedding=dedup_embeddings.get(picked.item.guid),
        produced_title_embedding=produced_embedding,
    )
    short_id = record_short(eng,
        channel=channel.slug, rss_item_guid=picked.item.guid,
        title=script.header_top + " " + script.header_bottom,
        file_path=str(out_path), duration_s=channel.duration_s,
        script_json=script.model_dump_json(), render_ms=render_ms,
    )
    finish_run(eng, run_id, status="success", short_id=short_id, error=None)
    yt_creds_root = (Path(eng.url.database).parent / "youtube_credentials").resolve() \
        if eng.url.database else Path("data/youtube_credentials").resolve()
    secrets_path = (Path(eng.url.database).parent / "secrets.yaml").resolve() \
        if eng.url.database else Path("data/secrets.yaml").resolve()
    _maybe_auto_upload(
        eng=eng, short_id=short_id, channel=channel,
        picked_score=picked.score, log=log,
        yt_creds_root=yt_creds_root,
        claude_path=settings.claude_cli_path,
        model=settings.claude_models.get("default", "haiku"),
        secrets_path=secrets_path,
    )
    log.info(f"=== success short_id={short_id} ===")
    return RunResult(run_id=run_id, status="success", short_path=out_path, error=None)


def _run_generator(*, channel, run_id, log, eng, settings,
                   music_root, templates_dir, cache_dir) -> RunResult:
    """6-phase generator pipeline."""
    log.info("[1/6] prepare (forbidden + topic distribution)")
    forbidden = recent_generated_texts(
        eng, channel.slug, limit=channel.generator.forbidden_lookback,
    )
    topic_dist = topic_distribution(eng, channel.slug, days=_GENERATOR_TOPIC_DIST_DAYS)
    log.info(f"  → forbidden={len(forbidden)} topic_dist={topic_dist}")

    fuzzy_threshold = (channel.generator.fuzzy_threshold
                       if channel.generator.fuzzy_threshold is not None
                       else settings.fuzzy_dedup_threshold)

    last_text = ""
    chosen_result = None
    for attempt in range(1, channel.generator.max_retries + 1):
        log.info(f"[2/6] generate attempt {attempt}/{channel.generator.max_retries}")
        result = generate_quote(
            channel=channel, dna=channel.dna,
            forbidden_texts=forbidden, topic_distribution=topic_dist,
            claude_path=settings.claude_cli_path,
            model=channel.script_model
                  or settings.claude_models.get("default", "sonnet"),
        )

        log.info(f"[3/6] dedup-check (text={result.text[:60]!r})")
        verdict = check_duplicate(eng, channel.slug, result, forbidden,
                                  fuzzy_threshold)
        if verdict.is_duplicate:
            log.warning(f"  duplicate ({verdict.reason}) → discard")
            try:
                insert_generated(
                    eng, channel=channel.slug, text=result.text,
                    topic_tag=result.topic_tag, language=channel.language,
                    status="discarded", short_id=None,
                )
            except Exception as e:
                log.warning(f"  discarded insert failed (probably hash race): {e}")
            last_text = result.text
            continue

        chosen_result = result
        break

    if chosen_result is None:
        msg = (f"{channel.slug}: {channel.generator.max_retries} attempts all "
               f"duplicate. Last attempt: {last_text[:80]!r}")
        finish_run(eng, run_id, status="failed",
                   short_id=None, error=msg)
        raise GeneratorRetryExhausted(msg)

    # Record as 'used' WITHOUT short_id yet (filled after render)
    generated_id = insert_generated(
        eng, channel=channel.slug, text=chosen_result.text,
        topic_tag=chosen_result.topic_tag, language=channel.language,
        status="used", short_id=None,
    )

    # Phase 4: image
    log.info("[4/6] image search (Sonnet keywords)")
    images_cache = Path(cache_dir) / "images"
    bg = pick_image_for_generator(
        keywords=chosen_result.image_keywords,
        script=chosen_result.script,
        cache_dir=images_cache,
        claude_path=settings.claude_cli_path,
    )
    music = pick_music(music_root, mood=chosen_result.script.mood, channel_slug=channel.slug)
    log.info(f"  → bg={'cached' if bg else 'none'} music={music.name}")

    # Phase 5+6: render + compose (same RenderJob shape as RSS path)
    log.info("[5/6] render_frames")
    job = RenderJob(
        script=chosen_result.script, bg_image_path=bg, music_path=music,
        channel_colors=channel.colors, handle=channel.handle,
        duration_s=channel.duration_s, language=channel.language,
        cta_enabled=channel.cta_enabled, cta_text=channel.cta_text,
        cta_icons=channel.cta_icons, cta_duration_s=channel.cta_duration_s,
        cta_show_handle=channel.cta_show_handle,
        rss_source=None,  # generator path — no RSS source
    )

    with tempfile.TemporaryDirectory() as tmpd:
        frames_dir = Path(tmpd) / "frames"
        t0 = time.perf_counter()
        ui_labels = _resolve_ui_labels(channel)
        # Resolve effective DNA (per-video for dynamic_dna channels; else channel-level).
        # Note: overflow check ran earlier against channel.template; if the dynamic DNA
        # picks a different archetype the rendered video uses it but overflow was not
        # re-checked. Acceptable risk — fallback is always channel.dna or template.
        from short_bot.dna import build_css_override
        effective_dna = channel.dna
        secrets_path = current_app_secrets_path()
        resolved = _resolve_dna_for_video(
            channel=channel,
            headline=f"{chosen_result.script.header_top} {chosen_result.script.header_bottom}",
            body=chosen_result.script.body_paragraph,
            log=log, claude_path=settings.claude_cli_path,
            secrets_path=secrets_path, templates_dir=templates_dir, eng=eng,
        )
        if resolved is not None:
            effective_dna, css_path = resolved
            dna_css = css_path.read_text(encoding="utf-8")
        else:
            dna_css = build_css_override(channel.dna) if channel.dna else ""
        archetype = effective_dna.archetype if effective_dna is not None else channel.template
        template_path = templates_dir / f"{archetype}.html.j2"
        render_frames(job, template_path, frames_dir,
                      fps=30, browser=settings.playwright_browser,
                      ui_labels=ui_labels, dna_css=dna_css,
                      animation_style=(effective_dna.animation_style
                                        if effective_dna is not None else "none"))

        log.info("[6/6] compose_video")
        out_dir = Path(channel.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(chosen_result.text)
        out_path = out_dir / f"{datetime.now(timezone.utc):%Y-%m-%d}_{slug}.mp4"
        sfx_overlays = _build_cta_sfx(channel)

        bg_video_path = _resolve_pexels_bg(
            channel=channel, cache_dir=cache_dir,
            secrets_path=secrets_path, log=log,
        )

        bv = channel.bg_video
        compose_video(
            frames_dir, music, out_path,
            fps=30, ffmpeg_path=settings.ffmpeg_path,
            sfx_overlays=sfx_overlays,
            bg_video_path=bg_video_path,
            bg_blur_px=bv.blur_px if bv else 30,
            bg_dim=bv.dim if bv else 0.4,
            fg_scale=bv.scale if (bv and bg_video_path) else 1.0,
            duration_s=channel.duration_s,
        )
        render_ms = int((time.perf_counter() - t0) * 1000)
        log.info(f"  → {out_path.name} ({render_ms}ms)")

    short_id = record_short(
        eng, channel=channel.slug, rss_item_guid=None,
        title=chosen_result.script.header_top + " " + chosen_result.script.header_bottom,
        file_path=str(out_path), duration_s=channel.duration_s,
        script_json=chosen_result.script.model_dump_json(),
        render_ms=render_ms,
    )
    update_generated_short_id(eng, generated_id, short_id)
    finish_run(eng, run_id, status="success", short_id=short_id, error=None)
    yt_creds_root = (Path(eng.url.database).parent / "youtube_credentials").resolve() \
        if eng.url.database else Path("data/youtube_credentials").resolve()
    secrets_path = (Path(eng.url.database).parent / "secrets.yaml").resolve() \
        if eng.url.database else Path("data/secrets.yaml").resolve()
    _maybe_auto_upload(
        eng=eng, short_id=short_id, channel=channel,
        picked_score=None, log=log,
        yt_creds_root=yt_creds_root,
        claude_path=settings.claude_cli_path,
        model=settings.claude_models.get("default", "haiku"),
        secrets_path=secrets_path,
    )
    log.info(f"=== success short_id={short_id} ===")
    return RunResult(run_id=run_id, status="success",
                     short_path=out_path, error=None)


def _build_check_job(script, channel, *, music_path, ui_language):
    """Lightweight RenderJob for in-memory overflow check.

    No bg image (Pexels download may not have happened yet at this point —
    template falls back to gradient when bg_image_path is None).
    Music path is required by RenderJob dataclass but unused by build_html.
    """
    from short_bot.models import RenderJob   # local import to avoid cycles
    return RenderJob(
        script=script,
        bg_image_path=None,
        music_path=music_path,
        channel_colors=channel.colors,
        handle=channel.handle,
        duration_s=channel.duration_s,
        language=ui_language,
        cta_enabled=False,   # CTA layer would only confuse measurements
    )


def write_script_with_overflow_check(
    *,
    item,
    body_html: str,
    channel,
    template_path,
    job_template_args: dict,
    max_retries: int = 2,
    log,
    claude_path: str = "claude",
    model: str = "default",
) -> tuple:
    """Returns (final_script, retry_count).

    retry_count: 0 = clean on first attempt
                 1-2 = clean after N retries
                 max_retries+1 (=3) = truncate fallback used (or attempted)
    """
    feedback = ""
    last_script = None
    last_report: OverflowReport | None = None

    for attempt in range(max_retries + 1):  # 0, 1, 2 → 3 attempts
        script = write_script(item, body_html, channel=channel,
                              overflow_feedback=feedback,
                              claude_path=claude_path, model=model)
        last_script = script

        check_job = _build_check_job(script, channel, **job_template_args)
        html = build_html(check_job, template_path)

        try:
            report = check_overflow(html, archetype=channel.template)
        except Exception as e:  # noqa: BLE001 — Playwright/timeout are runtime
            log.warning(f"[overflow] check failed (attempt {attempt + 1}): "
                        f"{e} — using script as-is")
            return script, attempt

        if not report.has_any_overflow():
            log.info(f"[overflow] check #{attempt + 1}: clean")
            return script, attempt

        last_report = report
        log.info(f"[overflow] check #{attempt + 1}: {report.summary()}")

        if attempt < max_retries:
            feedback = format_feedback(report)
            log.info("[overflow] retry write_script with feedback")

    # All attempts overflowed — truncate fallback.
    log.warning("[overflow] all retries failed -> truncate_to_fit fallback")
    try:
        return truncate_to_fit(last_script, last_report), max_retries + 1
    except Exception as e:  # noqa: BLE001 — Pydantic ValidationError or ValueError
        log.warning(f"[overflow] truncate failed ({e}) "
                    f"- using last script as-is")
        return last_script, max_retries + 1
