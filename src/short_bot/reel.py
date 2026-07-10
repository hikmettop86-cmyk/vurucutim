"""Reel (footage-sürüklü) üretim orkestratörü.

Zincir: preflight → reel senaryosu → TTS → hizalama → footage eşleştirme →
montaj. Tüm dış bağımlılıklar ReelDeps üzerinden enjekte edilir.
TTS/footage/montaj başarısızsa net Türkçe hatayla durur (sessiz fallback yok).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from short_bot.audio_probe import probe_duration_s as _probe
from short_bot.footage_matcher import match_beat_clip as _match
from short_bot.reel_assembler import assemble_reel as _assemble
from short_bot.reel_models import build_reel_timeline
from short_bot.reel_narration import write_reel_narration as _write_narr
from short_bot.reel_render import render_reel_overlay_frames as _render
from short_bot.tts.ai33_client import health_check as _health
from short_bot.tts.ai33_client import synthesize as _synth
from short_bot.tts.align import transcribe_words as _transcribe

log = logging.getLogger(__name__)

_PREFLIGHT = {
    "no-key": "ai33 için AI33_API_KEY tanımlı değil (Ayarlar → API anahtarları).",
    "auth": "ai33 reddetti: AI33_API_KEY geçersiz ya da kredi bitmiş.",
    "no-voice": "reel.voice_id boş — panelden bir ses seç.",
    "stalled": "ai33 kuyruk takılı (preflight zaman aşımı); üretim iptal, kredi harcanmadı.",
    "error": "ai33 preflight başarısız — servis yanıt vermiyor.",
}


@dataclass(frozen=True)
class ReelDeps:
    write_reel_narration: Callable = _write_narr
    health_check: Callable = _health
    synthesize: Callable = _synth
    probe_duration_s: Callable = _probe
    transcribe_words: Callable = _transcribe
    match_beat_clip: Callable = _match
    render_reel_overlay_frames: Callable = _render
    assemble_reel: Callable = _assemble


def _match_with_fallback(d, query, *, topic_q, api_key, cache_dir, verify, vision_call):
    """Footage eşleştirmeyi kademeli yedeklerle dener (footage = #1 risk).

    Sıra: (1) tam sorgu, (2) ilk 2 kelime, (3) konu tohumu — hepsi vision'lı;
    (4) son çare: ilk 2 kelime vision'sız (her zaman bir klip getirir).
    """
    words = query.split()
    stages = [query]
    if len(words) > 2:
        stages.append(" ".join(words[:2]))
    if topic_q and topic_q.lower() not in (s.lower() for s in stages):
        stages.append(topic_q)
    for q in stages:
        clip = d.match_beat_clip(q, api_key=api_key, cache_dir=cache_dir,
                                 verify=verify, vision_call=vision_call)
        if clip is not None:
            return clip
    # son çare — vision'sız, en sade sorgu (boş dönmesin)
    fallback = " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else topic_q)
    return d.match_beat_clip(fallback, api_key=api_key, cache_dir=cache_dir,
                             verify=False, vision_call=None)


def produce_reel_video(
    *, topic: str, channel, templates_dir: Path, work_dir: Path,
    out_path: Path, music_path: Path | None, ai33_api_key: str,
    pexels_api_key: str, ffmpeg_path: str = "ffmpeg", fps: int = 30,
    browser: str = "chromium",
    llm_claude_path: str = "claude", llm_model: str = "default",
    llm_backend: str = "claude_cli", llm_api_key: str | None = None,
    vision_call=None, deps: ReelDeps | None = None,
) -> Path:
    reel = getattr(channel, "reel", None)
    if reel is None or not reel.enabled:
        raise ValueError("produce_reel_video: channel.reel etkin değil")
    d = deps or ReelDeps()
    work_dir = Path(work_dir); work_dir.mkdir(parents=True, exist_ok=True)

    # 1) Preflight (LLM/TTS kredisi harcamadan)
    verdict = d.health_check(voice_id=reel.voice_id, api_key=ai33_api_key, tmp_dir=work_dir)
    if verdict != "healthy":
        raise RuntimeError(_PREFLIGHT.get(verdict, f"ai33 preflight: {verdict}"))
    log.info("  reel: ai33 preflight healthy")

    # 2) Senaryo
    narration = d.write_reel_narration(topic, channel=channel,
                                       claude_path=llm_claude_path, model=llm_model,
                                       backend=llm_backend, api_key=llm_api_key)
    log.info(f"  reel: {narration.word_count()} kelime, {len(narration.beats)} beat")

    # 3) TTS
    mp3 = work_dir / "narration.mp3"
    d.synthesize(narration.full_text(), voice_id=reel.voice_id, api_key=ai33_api_key,
                 out_path=mp3, speed=reel.speed)

    # 4) Süre + hizalama + zaman çizelgesi
    duration_s = d.probe_duration_s(mp3, ffprobe_path="ffprobe")
    words = d.transcribe_words(mp3, language=channel.language)
    timeline = build_reel_timeline(narration, words, duration_s=duration_s)
    log.info(f"  reel: ses {duration_s:.1f}s, {len(timeline.words)} kelime")

    # 5) Beat başına footage
    clips_cache = work_dir / "clips"
    clip_paths: list[Path] = []
    _first_q = next((q for q in timeline.seg_queries if q), "abstract background")
    _last_q = next((q for q in reversed(timeline.seg_queries) if q), _first_q)
    _topic_q = (topic.split(",")[0].strip()[:40] or "nature")
    for si, query in enumerate(timeline.seg_queries):
        if query is None:
            # hook → ilk beat'in görüntüsü, close → son beat'in görüntüsü
            query = _first_q if si == 0 else _last_q
        clip = _match_with_fallback(
            d, query, topic_q=_topic_q, api_key=pexels_api_key,
            cache_dir=clips_cache, verify=reel.verify_footage, vision_call=vision_call)
        if clip is None:
            raise RuntimeError(f"reel: '{query}' için footage bulunamadı (segment {si}).")
        clip_paths.append(clip)

    # 6) Overlay render
    frames_dir = work_dir / "frames"
    d.render_reel_overlay_frames(
        timeline, frames_dir, fps=fps, browser=browser, templates_dir=templates_dir,
        highlight_color=reel.highlight_color, arrow_color=reel.arrow_color,
        arrow_frequency=reel.arrow_frequency if reel.arrows_enabled else "off",
        flash=reel.transitions_flash, handle=channel.handle,
    )

    # 7) Montaj
    cut_times = [timeline.seg_spans[i][0] for i in range(1, len(timeline.seg_spans))]
    whoosh = Path("assets/sfx/whoosh.mp3") if reel.transitions_whoosh else None
    d.assemble_reel(
        clip_paths=clip_paths, seg_spans=timeline.seg_spans, frames_dir=frames_dir,
        narration_path=mp3, music_path=music_path, out_path=out_path,
        cut_times=cut_times, duration_s=duration_s, fps=fps, ffmpeg_path=ffmpeg_path,
        music_volume=reel.music_volume,
        whoosh_path=whoosh if (whoosh and whoosh.exists()) else None,
        zoom=reel.transitions_zoom,
    )
    return out_path
