"""Voiced (seslendirmeli) video üretim orkestratörü.

Zincir: preflight → anlatım senaryosu → TTS → kelime hizalama →
karaoke render → ses miksi. Tüm dış bağımlılıklar ``VoicedDeps`` üzerinden
enjekte edilir; böylece pipeline entegrasyonu ve testler ayrışır.

Tasarım kararı: TTS başarısızsa SESSİZCE sessiz videoya düşülmez —
kullanıcı yanlış formatta bir videonun yayına gitmesindense hatayı görmeli.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from short_bot.audio_probe import probe_duration_s as _probe_duration_s
from short_bot.composer import compose_video as _compose_video
from short_bot.models import RenderJob
from short_bot.narration_writer import write_narration as _write_narration
from short_bot.renderer import render_frames as _render_frames
from short_bot.tts.ai33_client import health_check as _health_check
from short_bot.tts.ai33_client import synthesize as _synthesize
from short_bot.tts.align import build_timeline
from short_bot.tts.align import transcribe_words as _transcribe_words

log = logging.getLogger(__name__)

_PREFLIGHT_ERRORS = {
    "no-key": "ai33 seslendirme için AI33_API_KEY tanımlı değil "
              "(Ayarlar → API anahtarları).",
    "auth": "ai33 reddetti: AI33_API_KEY geçersiz ya da kredi bitmiş.",
    "no-voice": "Kanal voice.voice_id boş — panelden bir ses seç.",
    "stalled": "ai33 kuyruk takılı görünüyor (preflight zaman aşımı); "
               "üretim iptal edildi, kredi harcanmadı.",
    "error": "ai33 preflight başarısız — servis şu an yanıt vermiyor.",
}


@dataclass(frozen=True)
class VoicedDeps:
    """Enjekte edilebilir dış bağımlılıklar (testte sahteleri geçilir)."""
    write_narration: Callable = _write_narration
    health_check: Callable = _health_check
    synthesize: Callable = _synthesize
    probe_duration_s: Callable = _probe_duration_s
    transcribe_words: Callable = _transcribe_words
    render_frames: Callable = _render_frames
    compose_video: Callable = _compose_video


def produce_voiced_video(
    *,
    item,
    body: str,
    script,
    bg_image_path: Path | None,
    music_path: Path,
    channel,
    templates_dir: Path,
    work_dir: Path,
    out_path: Path,
    api_key: str,
    ffmpeg_path: str = "ffmpeg",
    ffprobe_path: str = "ffprobe",
    fps: int = 30,
    browser: str = "chromium",
    ui_labels: dict | None = None,
    dna_css: str = "",
    animation_style: str = "none",
    sfx_overlays: list | None = None,
    bg_video_path: Path | None = None,
    bg_blur_px: int = 30,
    bg_dim: float = 0.7,
    fg_scale: float = 1.0,
    llm_claude_path: str = "claude",
    llm_model: str = "default",
    llm_backend: str = "claude_cli",
    llm_api_key: str | None = None,
    deps: VoicedDeps | None = None,
) -> Path:
    """Seslendirmeli videoyu üretip ``out_path``'e yazar."""
    voice = getattr(channel, "voice", None)
    if voice is None or not voice.enabled:
        raise ValueError("produce_voiced_video: channel.voice etkin değil")

    d = deps or VoicedDeps()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1) Preflight — LLM/TTS kredisi harcamadan servisin canlı olduğunu doğrula.
    verdict = d.health_check(voice_id=voice.voice_id, api_key=api_key,
                             tmp_dir=work_dir)
    if verdict != "healthy":
        raise RuntimeError(_PREFLIGHT_ERRORS.get(verdict, f"ai33 preflight: {verdict}"))
    log.info("  ai33 preflight: healthy")

    # 2) Anlatım senaryosu
    narration = d.write_narration(item, body, channel=channel,
                                   claude_path=llm_claude_path, model=llm_model,
                                   backend=llm_backend, api_key=llm_api_key)
    log.info(f"  narration: {narration.word_count()} kelime, "
             f"{len(narration.beats)} beat")

    # 3) TTS
    narration_mp3 = work_dir / "narration.mp3"
    d.synthesize(narration.full_text(), voice_id=voice.voice_id, api_key=api_key,
                 out_path=narration_mp3, speed=voice.speed)

    # 4) Süre + kelime hizalama
    duration_s = d.probe_duration_s(narration_mp3, ffprobe_path=ffprobe_path)
    words = d.transcribe_words(narration_mp3, language=channel.language)
    timeline = build_timeline(narration, words, duration_s=duration_s)
    log.info(f"  ses {duration_s:.1f}s, {len(timeline.words)} kelime hizalandı")

    # ffmpeg üst sınırı: sesin bir saniye ötesi (kuyruk karesi payı).
    cap_s = math.ceil(duration_s) + 1

    # 5) Render — voiced her zaman narrator arketipini kullanır.
    job = RenderJob(
        script=script,
        bg_image_path=bg_image_path,
        music_path=music_path,
        channel_colors=channel.colors,
        handle=channel.handle,
        duration_s=cap_s,
        language=channel.language,
        rss_source=getattr(item, "source", None),
        narration=timeline,
    )
    frames_dir = work_dir / "frames"
    d.render_frames(job, Path(templates_dir) / "narrator.html.j2", frames_dir,
                    fps=fps, browser=browser, ui_labels=ui_labels,
                    dna_css=dna_css, animation_style=animation_style)

    # 6) Compose — anlatım ana ses, müzik altında kısık.
    d.compose_video(
        frames_dir, music_path, out_path,
        fps=fps, ffmpeg_path=ffmpeg_path,
        sfx_overlays=sfx_overlays or [],
        music_volume=voice.music_volume,
        bg_video_path=bg_video_path,
        bg_blur_px=bg_blur_px, bg_dim=bg_dim, fg_scale=fg_scale,
        duration_s=cap_s,
        narration_path=narration_mp3,
    )
    return out_path
