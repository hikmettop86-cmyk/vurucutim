"""Pipeline orchestrator: runs all 8 stages, persists to DB, writes per-run log."""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock, Timeout

from short_bot.config import ChannelConfig, Settings
from short_bot.db import (
    init_db, mark_processed, record_short, record_rss_item,
    start_run, finish_run,
)
from short_bot.models import RenderJob
from short_bot.fetcher import fetch_rss
from short_bot.dedup import filter_new
from short_bot.scorer import score_items, select_top
from short_bot.extractor import extract_article
from short_bot.script_writer import write_script
from short_bot.assets import download_and_blur_thumb, pick_music
from short_bot.renderer import render_frames
from short_bot.composer import compose_video
from short_bot.locale import ui_labels_for
from short_bot.generator import (
    GeneratorRetryExhausted, check_duplicate, generate_quote,
)
from short_bot.generated_db import (
    insert_generated, recent_generated_texts, topic_distribution,
    update_generated_short_id,
)
from short_bot.image_picker import pick_image_for_generator

_GENERATOR_TOPIC_DIST_DAYS = 7   # window for topic_distribution Sonnet hint


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
    return logger


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
        # Close log handlers to release the file
        for h in list(log.handlers):
            try:
                h.close()
            except Exception:
                pass
            log.removeHandler(h)
        # Dispose engine to release the SQLite connection pool (CLI use case)
        eng.dispose()


def _run_rss(*, channel, run_id, log, eng, settings,
             music_root, templates_dir, cache_dir) -> RunResult:
    """Existing 8-stage RSS pipeline body, extracted verbatim. Returns RunResult."""
    log.info("[1/8] fetch_rss")
    items = fetch_rss(channel.keywords, channel.rss_locale)
    log.info(f"  → {len(items)} items")

    log.info("[2/8] dedup")
    new_items = filter_new(eng, items, channel.slug,
                            fuzzy_threshold=settings.fuzzy_dedup_threshold)
    log.info(f"  → {len(new_items)} new")
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
    scored = score_items(candidates, claude_path=settings.claude_cli_path)
    top = select_top(scored, min_score=channel.min_score, n=1)
    picked_guid = top[0].item.guid if top else None
    for s in scored:
        status = "selected" if s.item.guid == picked_guid else "below_threshold"
        record_rss_item(eng, guid=s.item.guid, channel=channel.slug,
                        title=s.item.title, link=s.item.link, source=s.item.source,
                        pub_date=s.item.pub_date, thumb_url=s.item.thumb_url,
                        score=s.score, status=status)
    if not top:
        log.info(f"no item ≥ {channel.min_score} → finish")
        # Show top 3 for calibration / debug
        top_seen = sorted(scored, key=lambda s: s.score, reverse=True)[:3]
        for i, s in enumerate(top_seen, 1):
            log.info(f"  top#{i} score={s.score:.1f} | {s.item.title[:80]}")
        finish_run(eng, run_id, status="no_candidates", short_id=None, error=None)
        return RunResult(run_id=run_id, status="no_candidates", short_path=None, error=None)
    picked = top[0]
    log.info(f"  → picked {picked.item.guid} (score={picked.score})")

    log.info("[4/8] extract_article")
    body = extract_article(picked.item.link)
    if body is None:
        body = picked.item.description or picked.item.title
        log.warning("  trafilatura empty → fallback description")
    log.info(f"  → body {len(body)} chars")

    log.info("[5/8] write_script")
    script_model = channel.script_model or settings.claude_models.get("default", "default")
    script = write_script(picked.item, body, claude_path=settings.claude_cli_path,
                          channel=channel, model=script_model)
    log.info(f"  → {script.header_top} | {script.header_bottom}")

    log.info("[6/8] assets")
    bg = None
    if picked.item.thumb_url:
        bg = download_and_blur_thumb(picked.item.thumb_url, cache_dir)
    if bg is None:
        # Fallback: search DDG + verify with Claude vision
        from short_bot.image_picker import pick_image_for_script
        images_cache = cache_dir / "images"
        bg = pick_image_for_script(script, images_cache,
                                    claude_path=settings.claude_cli_path,
                                    channel=channel)
        if bg:
            log.info(f"  ddg image accepted: {bg.name}")
    music = pick_music(music_root, mood=script.mood)
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
    )

    with tempfile.TemporaryDirectory() as tmpd:
        frames_dir = Path(tmpd) / "frames"
        t0 = time.perf_counter()
        template_path = templates_dir / f"{channel.template}.html.j2"
        ui_labels = ui_labels_for(channel.language)
        dna_css_path = Path("templates") / "css" / f"{channel.slug}.css"
        dna_css = dna_css_path.read_text(encoding="utf-8") if dna_css_path.exists() else ""
        render_frames(job, template_path, frames_dir,
                      fps=30, browser=settings.playwright_browser,
                      ui_labels=ui_labels, dna_css=dna_css)

        log.info("[8/8] compose_video")
        out_dir = Path(channel.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(picked.item.title)
        out_path = out_dir / f"{datetime.now(timezone.utc):%Y-%m-%d}_{slug}.mp4"

        # Build SFX schedule for CTA window
        sfx_overlays = _build_cta_sfx(channel)

        compose_video(frames_dir, music, out_path,
                      fps=30, ffmpeg_path=settings.ffmpeg_path,
                      sfx_overlays=sfx_overlays)
        render_ms = int((time.perf_counter() - t0) * 1000)
        log.info(f"  → {out_path.name} ({render_ms}ms)")

    mark_processed(eng, picked.item.guid, picked.item.title, channel.slug)
    short_id = record_short(eng,
        channel=channel.slug, rss_item_guid=picked.item.guid,
        title=script.header_top + " " + script.header_bottom,
        file_path=str(out_path), duration_s=channel.duration_s,
        script_json=script.model_dump_json(), render_ms=render_ms,
    )
    finish_run(eng, run_id, status="success", short_id=short_id, error=None)
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
                       or settings.fuzzy_dedup_threshold)

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
    music = pick_music(music_root, mood=chosen_result.script.mood)
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
    )

    with tempfile.TemporaryDirectory() as tmpd:
        frames_dir = Path(tmpd) / "frames"
        t0 = time.perf_counter()
        template_path = templates_dir / f"{channel.template}.html.j2"
        ui_labels = ui_labels_for(channel.language)
        dna_css_path = Path("templates") / "css" / f"{channel.slug}.css"
        dna_css = dna_css_path.read_text(encoding="utf-8") if dna_css_path.exists() else ""
        render_frames(job, template_path, frames_dir,
                      fps=30, browser=settings.playwright_browser,
                      ui_labels=ui_labels, dna_css=dna_css)

        log.info("[6/6] compose_video")
        out_dir = Path(channel.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(chosen_result.text)
        out_path = out_dir / f"{datetime.now(timezone.utc):%Y-%m-%d}_{slug}.mp4"
        sfx_overlays = _build_cta_sfx(channel)
        compose_video(frames_dir, music, out_path,
                      fps=30, ffmpeg_path=settings.ffmpeg_path,
                      sfx_overlays=sfx_overlays)
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
    log.info(f"=== success short_id={short_id} ===")
    return RunResult(run_id=run_id, status="success",
                     short_path=out_path, error=None)
