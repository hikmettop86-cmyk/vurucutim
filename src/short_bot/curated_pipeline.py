"""Kürate-klip üretim orkestratörü (SP3): seçilen Reddit cevherini uçtan uca videoya
çevirir ve panelde görünsün/yüklenebilsin diye Short olarak kaydeder.

Zincir: indir (v.redd.it) → vision ile GERÇEK aksiyonu oku → persona ile yeniden-senaryo
(uydurma yok) → produce_reel_video (tek klip; kısa klip loop yerine YAVAŞLATILIR) →
record_short. Metin/vision backend'i hibrit (resolve_ai_call); footage ARANMAZ.
"""
from __future__ import annotations

import json
import logging
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def produce_curated(gem: dict, channel, *, settings, secrets, db_path,
                    output_root, music_root, templates_dir, cache_dir=None,
                    seed: int = 0, log=log) -> tuple[int, Path]:
    """Bir cevherden video üretip Short kaydeder. Döner (short_id, out_path).

    gem: find_gems/fetch_post çıktısı (video_url + title şart).
    Reel etkin, persona'lı bir kanal gerekir. Hata olursa net Türkçe RuntimeError.
    """
    from short_bot.assets import pick_music
    from short_bot.db import init_db, record_short
    from short_bot.pipeline import resolve_ai_call, unique_output_path, _slugify
    from short_bot.reddit_gems import download_clip
    from short_bot.reel import (_clip_duration_s, _describe_clip,
                                produce_reel_video)
    from short_bot.reel_narration import curated_target, write_curated_narration
    from short_bot.tts.ai33_client import resolve_ai33_api_key

    reel = getattr(channel, "reel", None)
    if reel is None or not reel.enabled:
        raise ValueError("produce_curated: kanal reel etkin değil")
    video_url = gem.get("video_url")
    if not video_url:
        raise ValueError("produce_curated: cevherde video_url yok")
    title_seed = (gem.get("title") or "kürate klip").strip()

    vision = resolve_ai_call(settings, secrets, "vision")
    llm = resolve_ai_call(settings, secrets, "script")
    ai33_key = resolve_ai33_api_key(secrets)

    out_dir = Path(output_root) / channel.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now(timezone.utc):%Y-%m-%d}_{_slugify(title_seed)}"
    out_path = unique_output_path(out_dir, stem)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        log.info(f"  kürate: klip indiriliyor ({video_url})")
        clip = download_clip(video_url, td / "src.mp4")
        clip_dur = _clip_duration_s(clip, settings.ffmpeg_path)

        log.info("  kürate: vision ile GERÇEK aksiyon okunuyor…")
        desc = _describe_clip(clip, vision_call=vision, ffmpeg_path=settings.ffmpeg_path)
        if not desc.strip():
            raise RuntimeError("kürate: vision klibi tarif edemedi (backend kapalı?)")
        log.info(f"  kürate: vision → {desc}")

        target = curated_target(clip_dur, reel.target_duration_s)
        log.info(f"  kürate: klip {clip_dur:.1f}s → video hedefi {target} (loop önleme)")
        narration = write_curated_narration(
            title_seed, desc, channel=channel, subject="clip",
            claude_path=llm.claude_path, model=llm.model, backend=llm.backend,
            api_key=llm.api_key, seed=seed, target_duration_s=target)
        log.info(f"  kürate: senaryo {narration.word_count()} kelime | "
                 f"başlık='{narration.title}' kapak='{narration.cover_title}'")

        try:
            music = pick_music(Path(music_root), mood=reel.music_mood,
                               channel_slug=channel.slug)
        except Exception as e:  # noqa: BLE001 — müziksiz de üretilir
            log.info(f"  kürate: müzik yok ({e})")
            music = None

        t0 = time.perf_counter()
        produce_reel_video(
            topic=title_seed, channel=channel, templates_dir=Path(templates_dir),
            work_dir=td / "work", out_path=out_path, music_path=music,
            ai33_api_key=ai33_key, pexels_api_key="", pixabay_api_key="",
            ffmpeg_path=settings.ffmpeg_path, browser=settings.playwright_browser,
            llm_claude_path=llm.claude_path, llm_model=llm.model,
            llm_backend=llm.backend, llm_api_key=llm.api_key,
            vision_call=vision, seed=seed, assets_root=Path(music_root).parent,
            curated_clip=clip, curated_narration=narration)
        render_ms = int((time.perf_counter() - t0) * 1000)

    # Short kaydı: /shorts'ta görünür + mevcut yükleme yolu kullanılabilir.
    # script_json yükleme anında YT başlık/açıklamasını besler (bkz. youtube route).
    seo = (narration.title or title_seed)[:100]
    script_json = json.dumps({
        "header_top": narration.cover_title or narration.hook,
        "header_bottom": "",
        "body_paragraph": narration.full_text(),
        "title": seo,
        "source_permalink": gem.get("permalink", ""),
    }, ensure_ascii=False)
    eng = init_db(db_path)
    short_id = record_short(
        eng, channel=channel.slug, rss_item_guid=None, title=seo,
        file_path=str(out_path), duration_s=int(round(clip_dur)) or None,
        script_json=script_json, render_ms=render_ms)
    log.info(f"  kürate: Short kaydedildi id={short_id} → {out_path.name}")
    return short_id, out_path
