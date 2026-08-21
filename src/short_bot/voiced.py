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
from short_bot.narration_writer import write_yorum_narration as _write_yorum_narration
from short_bot.formats import channel_format
from short_bot.renderer import render_frames as _render_frames
from short_bot.tts.ai33_client import health_check as _health_check
from short_bot.tts.ai33_client import synthesize as _synthesize
from short_bot.tts.align import build_timeline
from short_bot.tts.providers import resolve_tts
from short_bot.tts.align import transcribe_words as _transcribe_words

log = logging.getLogger(__name__)

_PREFLIGHT_ERRORS = {
    "no-key": "{label} seslendirme için {key_hint} tanımlı değil.",
    "auth": "{label} reddetti: {key_hint} geçersiz ya da kredi bitmiş.",
    "no-voice": "Kanal voice.voice_id boş — panelden bir ses seç.",
    "voice-missing": "{label}: bu voice_id bulunamadı — panelden geçerli bir ses seç.",
    "model": "{label}: model kimliği geçersiz — panelden ölçülmüş bir model seç.",
    "stalled": "{label} kuyruk takılı görünüyor (preflight zaman aşımı); "
               "üretim iptal edildi, kredi harcanmadı.",
    "error": "{label} preflight başarısız — servis şu an yanıt vermiyor.",
}


@dataclass(frozen=True)
class VoicedDeps:
    """Enjekte edilebilir dış bağımlılıklar (testte sahteleri geçilir).

    ``health_check``/``synthesize`` varsayılanı ai33; ``for_provider`` kanalın
    sağlayıcısına göre doğru çifti kurar."""
    write_narration: Callable = _write_narration
    write_yorum_narration: Callable = _write_yorum_narration
    health_check: Callable = _health_check
    synthesize: Callable = _synthesize
    probe_duration_s: Callable = _probe_duration_s
    transcribe_words: Callable = _transcribe_words
    render_frames: Callable = _render_frames
    compose_video: Callable = _compose_video

    @classmethod
    def for_provider(cls, provider: str) -> "VoicedDeps":
        p = resolve_tts(provider)
        return cls(health_check=p.health_check, synthesize=p.synthesize)


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
    ticker_items: tuple[str, ...] = (),
    usage_dir: Path | None = None,
    extra_sources: list[tuple[str, str]] | None = None,
    recent_variations: tuple[str, ...] = (),
) -> Path:
    """Seslendirmeli videoyu üretip ``out_path``'e yazar."""
    voice = getattr(channel, "voice", None)
    if voice is None or not voice.enabled:
        raise ValueError("produce_voiced_video: channel.voice etkin değil")

    provider = resolve_tts(getattr(voice, "provider", "ai33"))
    d = deps or VoicedDeps.for_provider(provider.name)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1) Preflight — LLM/TTS kredisi harcamadan servisin canlı olduğunu doğrula.
    verdict = d.health_check(voice_id=voice.voice_id, api_key=api_key,
                             tmp_dir=work_dir)
    # 'yavas' BAŞARIDIR: preflight penceresi doldu ama görev ilerliyordu, yani
    # servis canlı. Bunu 'ölü' saymak üretimi durduruyordu (panel koşusu #1585);
    # asıl sentezin kendi 600sn bütçesi gerçek arızayı zaten yakalar.
    if verdict not in ("healthy", "yavas"):
        msg = _PREFLIGHT_ERRORS.get(verdict, "{label} preflight: " + str(verdict))
        raise RuntimeError(msg.format(label=provider.label, key_hint=provider.key_hint))
    log.info(f"  {provider.label} preflight: {verdict}")

    # 2) Anlatım senaryosu — format 'yorum' ise yorumcu yazarı (çok-kaynak +
    # Trends bağlamı), değilse mevcut anlatım yazarı.
    if channel_format(channel) == "yorum":
        # Her video kendi biçiminde: açılış/yaklaşım/kapanış üç bankadan seçilir ve
        # SON videolarda kullanılanlar dışlanır. Sabit iskelet "hepsi aynı" hissi
        # veriyordu (kullanıcı bildirimi 2026-08-20).
        from short_bot.yorum_variation import pick_variation
        variation = pick_variation(seed_text=f"{channel.slug}:{getattr(item, 'guid', '')}",
                                   recent=recent_variations)
        log.info(f"  yorum biçimi: {variation.key}")
        narration = d.write_yorum_narration(
            item, body, channel=channel, extra_sources=list(extra_sources or []),
            variation=variation,
            claude_path=llm_claude_path, model=llm_model,
            backend=llm_backend, api_key=llm_api_key)
        try:
            script.narration_variation = variation.key
        except Exception:  # noqa: BLE001 — kayıt alanı yoksa üretim durmaz
            pass
    else:
        narration = d.write_narration(item, body, channel=channel,
                                       claude_path=llm_claude_path, model=llm_model,
                                       backend=llm_backend, api_key=llm_api_key)
    # BİRİM DİLE GÖRE: CJK'de .split() 1 döner ve log "5 kelime" diye
    # YANILTICI bir sayı yazardı (Japonca ilk koşuda ölçüldü).
    from short_bot.narration_writer import narration_length as _nl
    from short_bot.reel_narration import budget_unit as _bu
    _birim = "karakter" if _bu(channel.language) == "characters" else "kelime"
    log.info(f"  narration: {_nl(narration.full_text(), channel.language)} {_birim}, "
             f"{len(narration.beats)} beat")

    # Anlatımın kendisi + Türkçesi script'e yazılır; pipeline script'i JSON olarak
    # kaydeder ve panel /shorts/<id>'de gösterir. PENCERE, kapı değil: back_translate
    # zaten fail-open, burada da hiçbir hata üretimi durdurmaz.
    try:
        script.narration_text = narration.full_text()
        if channel.language != "tr":
            from short_bot.lang_review import back_translate
            script.body_paragraph_tr = back_translate(
                narration.full_text(), language=channel.language,
                backend=llm_backend, model=llm_model,
                api_key=llm_api_key, claude_path=llm_claude_path)
            if script.body_paragraph_tr:
                log.info(f"  anlatım TR: {script.body_paragraph_tr[:160]}")
    except Exception as e:  # noqa: BLE001 — çeviri yokluğu videoyu engellemez
        log.info(f"  anlatım TR alınamadı ({e})")

    # 3) TTS — sağlayıcının kabul ettiği ek anahtarlar yalnız ona iletilir
    # (ai33'e volume/model geçmek TypeError verirdi).
    narration_mp3 = work_dir / "narration.mp3"
    extra = {}
    if "volume" in provider.extra_kwargs:
        extra["volume"] = getattr(voice, "volume", 1.0)
    if "model" in provider.extra_kwargs and getattr(voice, "model", ""):
        extra["model"] = voice.model
    if "emotion" in provider.extra_kwargs and getattr(voice, "emotion", ""):
        extra["emotion"] = voice.emotion
    if "language" in provider.extra_kwargs:
        extra["language"] = channel.language
    if "usage_dir" in provider.extra_kwargs and usage_dir is not None:
        extra["usage_dir"] = usage_dir
    result = d.synthesize(narration.full_text(), voice_id=voice.voice_id, api_key=api_key,
                          out_path=narration_mp3, speed=voice.speed, **extra)
    # ai33 düz yol döndürür; Cartesia SynthesisResult (yol + kelimeler). Dönen yolu
    # kullan: Cartesia .wav yazar, dosya adı uzantıya göre değişir.
    synth_words = list(getattr(result, "words", []) or [])
    narration_audio = Path(getattr(result, "path", result) or narration_mp3)

    # 4) Süre + kelime hizalama — sentez kelime zamanı verdiyse whisper ATLANIR
    # (cron çakışmasında whisper ölüyordu; Cartesia zamanları zaten kesin).
    duration_s = d.probe_duration_s(narration_audio, ffprobe_path=ffprobe_path)
    if synth_words:
        words = synth_words
        log.info(f"  kelime zamanları sentezden geldi ({len(words)} kelime), whisper atlandı")
    else:
        words = d.transcribe_words(narration_audio, language=channel.language)
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
        ticker_items=tuple(ticker_items or ()),
    )
    frames_dir = work_dir / "frames"
    # Seslendirme şablonu üç kademede aranır:
    #   <slug>-narrator → <arketip>-narrator → narrator
    # NEDEN: ortak narrator tam ekran foto + karaoke çizer; haber-kartı kimliği
    # (manşet bandı, çerçeveli foto) olan bir kanal seslendirmeye geçince o
    # kimliği kaybediyordu. RenderJob hem `script` hem `narration` taşıdığı için
    # ikisini birlikte çizen bir şablon mümkün. Arketip kademesi sayesinde aynı
    # arketipteki kanallar tek şablonu paylaşır (kopya dosya tutmaya gerek yok);
    # slug kademesi tek bir kanalı ayrıştırmak isteyene açık kapı bırakır.
    # Hiçbiri yoksa ortak narrator'a düşer — mevcut kanalların davranışı aynı kalır.
    tpl = None
    for aday in (f"{getattr(channel, 'slug', '')}-narrator.html.j2",
                 f"{getattr(channel, 'template', '')}-narrator.html.j2",
                 "narrator.html.j2"):
        p = Path(templates_dir) / aday
        if p.exists():
            tpl = p
            break
    if tpl is None:      # narrator.html.j2 kodla gelir; yoksa kurulum bozuk
        raise RuntimeError(f"seslendirme şablonu bulunamadı: {templates_dir}")
    log.info(f"  şablon: {tpl.name}")
    d.render_frames(job, tpl, frames_dir,
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
        narration_path=narration_audio,
    )
    return out_path
