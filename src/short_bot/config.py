"""YAML config loader for global settings and per-channel configs."""
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


def _default_trends_settings() -> "TrendsSettings":
    return TrendsSettings(
        enabled=False, refresh_minutes=60,
        default_sources=("google_daily", "youtube"),
        cache_max_age_minutes=90.0,
    )

from short_bot.dna import DnaSpec
from short_bot.locale import RSS_LOCALES, SUPPORTED_LANGUAGES

SLUG_RE = re.compile(r"^[a-z0-9\-]+$")


@dataclass(frozen=True)
class TrendsSettings:
    enabled: bool
    refresh_minutes: int
    default_sources: tuple[str, ...]
    cache_max_age_minutes: float


@dataclass(frozen=True)
class Settings:
    ffmpeg_path: str
    claude_cli_path: str
    playwright_browser: str
    web_host: str
    web_port: int
    fuzzy_dedup_threshold: float
    log_level: str
    claude_models: dict
    ai_backend: str = "claude_cli"
    openrouter_models: dict = field(default_factory=dict)
    trends: TrendsSettings = field(default_factory=_default_trends_settings)
    whisper_quality: str = "auto"
    whisper_device: str = "auto"
    footage_priority: list = field(default_factory=lambda: ["pexels"])
    storyblocks_session: str = "data/storyblocks_session.json"
    storyblocks_max_concurrent: int = 3


@dataclass(frozen=True)
class GeneratorConfig:
    topic: str
    forbidden_lookback: int = 50
    max_retries: int = 3
    fuzzy_threshold: float | None = None


class YoutubeChannelConfig(BaseModel):
    auto_upload: bool = False
    ai_content: bool = True
    category_id: str = "24"
    privacy_status: Literal["public", "unlisted", "private"] = "public"
    min_score_for_upload: float = Field(default=8.0, ge=0.0, le=10.0)
    cron_preset: str | None = None


class BgVideoConfig(BaseModel):
    enabled: bool = False
    scale: Literal[0.88, 0.80] = 0.88
    blur_px: int = Field(ge=0, le=80, default=30)
    # dim=1.0 → orijinal parlaklik, dim=0.0 → tam siyah.
    # Default 0.7 = subtle dim, BG video gorunur kalir ama on plana
    # yer acar. (0.4 default'u "hep siyah video" sikayetine yol aciyordu.)
    dim: float = Field(ge=0.0, le=1.0, default=0.7)


class TrendBoostConfig(BaseModel):
    """Per-channel trend-boost knobs. Score augmentation when a candidate
    headline matches an active trending term in the channel's region."""
    enabled: bool = False
    max_boost: float = Field(default=2.0, ge=0.0, le=5.0)
    # When None, inherits Settings.trends.default_sources.
    sources: list[str] | None = None
    min_term_length: int = Field(default=4, ge=2, le=20)
    fuzzy_threshold: int = Field(default=85, ge=50, le=100)
    exclude_terms: list[str] = Field(default_factory=list)
    # Override the channel-language -> region default (e.g. 'GB' for an
    # English-language channel targeting UK YouTube trending).
    region_override: str | None = None


class VoiceConfig(BaseModel):
    """Voiced (seslendirmeli) üretim ayarları. Blok yoksa kanal sessiz üretir."""
    enabled: bool = False
    voice_id: str = ""          # ai33 voice id (prefix'li ya da ham)
    speed: float = Field(default=1.0, ge=0.5, le=1.5)
    persona: str = "enerjik, meraklı anlatıcı"
    target_duration_s: tuple[int, int] = (45, 60)
    # Anlatım altındaki müzik seviyesi (~-18 dB).
    music_volume: float = Field(default=0.12, ge=0.0, le=1.0)

    @field_validator("target_duration_s", mode="before")
    @classmethod
    def _coerce_tuple(cls, v):
        return tuple(v) if isinstance(v, list) else v

    @model_validator(mode="after")
    def _check(self) -> "VoiceConfig":
        lo, hi = self.target_duration_s
        if not (10 <= lo < hi <= 180):
            raise ValueError(
                f"target_duration_s must satisfy 10 <= lo < hi <= 180, got ({lo}, {hi})"
            )
        if self.enabled and not self.voice_id.strip():
            raise ValueError("voice.enabled=true ise voice_id zorunlu")
        return self


class ReelConfig(BaseModel):
    """Footage-sürüklü reel formatı ayarları. Blok yoksa kanal reel üretmez."""
    enabled: bool = False
    voice_id: str = ""
    speed: float = Field(default=1.0, ge=0.5, le=1.5)
    target_duration_s: tuple[int, int] = (25, 45)
    cut_pacing: Literal["auto", "slow", "medium", "fast"] = "auto"
    highlight_color: str = "#ffd400"
    arrows_enabled: bool = True
    arrow_color: str = "#ff2d2d"
    arrow_frequency: Literal["off", "reveal", "beats"] = "beats"
    transitions_flash: bool = True
    transitions_whoosh: bool = True
    transitions_zoom: bool = True
    music_mood: Literal["upbeat", "neutral", "calm"] = "upbeat"
    music_volume: float = Field(default=0.10, ge=0.0, le=1.0)
    font: Literal["Montserrat", "Anton", "Bebas Neue", "Oswald",
                  "Poppins", "Inter", "Archivo Black"] = "Montserrat"
    verify_footage: bool = True
    footage_anchor: str = ""   # EN konu çıpası (boşsa dna.search_query_template'ten türetilir)
    # Retention kurgu katmanı (2026-07-12): insan-editör hamleleri
    fast_cuts: bool = True      # segment-içi hızlı kesim (1.5-3sn'de b-roll değişir)
    number_pop: bool = True     # anlatımdaki sayıları ekranda büyük vurgula
    visual_loop: bool = True    # kapanış klibi = hook klibi (loop hissi)
    # AI kurgucu (2026-07-13): anlatımı okuyup tempo/efekt/SFX/müzik seçer.
    # Kapalıysa kararlar eski seed-hash havuzlarından gelir (içerikten habersiz).
    ai_director: bool = True
    # Faz 2 varyasyon knob'ları (per-video deterministik profil)
    layout: Literal["auto", "classic", "lower_left", "top_heavy"] = "auto"
    hook_angle_vary: bool = True
    accent_vary: bool = True
    transition_vary: bool = True
    # Faz 3 abone mekanikleri (reel_subscribe üzerinden aktif)
    series_enabled: bool = False
    series_title: str = ""
    cta_enabled: bool = True
    comment_question: bool = True
    cta_text_custom: str = ""

    @field_validator("target_duration_s", mode="before")
    @classmethod
    def _coerce_tuple(cls, v):
        return tuple(v) if isinstance(v, list) else v

    @model_validator(mode="after")
    def _check(self) -> "ReelConfig":
        lo, hi = self.target_duration_s
        if not (10 <= lo < hi <= 120):
            raise ValueError(
                f"target_duration_s must satisfy 10 <= lo < hi <= 120, got ({lo}, {hi})"
            )
        if self.enabled and not self.voice_id.strip():
            raise ValueError("reel.enabled=true ise voice_id zorunlu")
        return self


@dataclass(frozen=True)
class ChannelConfig:
    slug: str
    name: str
    keywords: list[str]
    rss_locale: str
    schedule_cron: str
    duration_s: int
    min_score: float
    max_candidates_per_run: int
    template: str
    colors: dict
    handle: str
    output_dir: str
    enabled: bool
    cta_enabled: bool
    cta_text: str
    cta_icons: list[str]
    cta_duration_s: int
    cta_show_handle: bool
    language: str = "tr"
    # max_age_hours: pipeline drops RSS items older than this many hours
    # (0 = no limit). Default 24h prevents stale articles from being turned
    # into shorts.
    max_age_hours: int = 24
    dynamic_dna: bool = False
    negative_keywords: list[str] = field(default_factory=list)
    dna: DnaSpec | None = None
    script_model: str | None = None
    content_source: Literal["rss", "generator", "feed"] = "rss"
    generator: GeneratorConfig | None = None
    auto_feed_ids: list[int] = field(default_factory=list)
    youtube: YoutubeChannelConfig | None = None
    bg_video: BgVideoConfig | None = None
    trend_boost: TrendBoostConfig | None = None
    # Per-channel og:image blur radius (0 = crisp original). Up to v0.6.2 a
    # baked-in 8px GaussianBlur was applied to every publisher photo. v0.6.3
    # made this a UI knob: 0 = original, 8 = old behavior, 20 = heavy frosted.
    bg_image_blur: int = 0
    voice: VoiceConfig | None = None
    reel: "ReelConfig | None" = None
    # Referans/rakip kanallar (URL/@handle/UC-id) — konu-bankası madencisi bu
    # kanalların KENDİ medyanına göre patlayan shorts'larını kanıtlanmış konu
    # olarak çeker (format+kitle garantili). Boşsa yalnız arama madenciliği.
    reference_channels: list[str] = field(default_factory=list)


def load_settings(path: Path) -> Settings:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    web = data.get("web", {})
    wh_data = data.get("whisper", {}) or {}
    tr_data = data.get("trends", {}) or {}
    ft_data = data.get("footage", {}) or {}
    trends = TrendsSettings(
        enabled=bool(tr_data.get("enabled", False)),
        refresh_minutes=int(tr_data.get("refresh_minutes", 60)),
        default_sources=tuple(tr_data.get("default_sources",
                                          ["google_daily", "youtube"])),
        cache_max_age_minutes=float(tr_data.get("cache_max_age_minutes", 90)),
    )
    return Settings(
        ffmpeg_path=data["ffmpeg_path"],
        claude_cli_path=data["claude_cli_path"],
        playwright_browser=data.get("playwright_browser", "chromium"),
        web_host=web.get("host", "127.0.0.1"),
        web_port=int(web.get("port", 5005)),
        fuzzy_dedup_threshold=float(data.get("fuzzy_dedup_threshold", 0.85)),
        log_level=data.get("log_level", "INFO"),
        claude_models=dict(data.get("claude_models", {"dna": "opus", "default": "haiku"})),
        ai_backend=data.get("ai_backend", "claude_cli"),
        openrouter_models=dict(data.get("openrouter_models", {})),
        trends=trends,
        whisper_quality=wh_data.get("quality", "auto"),
        whisper_device=wh_data.get("device", "auto"),
        footage_priority=list(ft_data.get("priority", ["pexels"])),
        storyblocks_session=str(ft_data.get("storyblocks_session",
                                            "data/storyblocks_session.json")),
        storyblocks_max_concurrent=int(ft_data.get("storyblocks_max_concurrent", 3)),
    )


def load_channel(path: Path) -> ChannelConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    slug = data["slug"]
    if not SLUG_RE.match(slug):
        raise ValueError(f"Geçersiz slug '{slug}': sadece [a-z0-9-] izinli")

    # Resolve language (with backward-compat for legacy rss_locale-only YAMLs)
    language = data.get("language", "tr")
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language '{language}': must be one of {SUPPORTED_LANGUAGES}"
        )
    rss_locale = data.get("rss_locale") or RSS_LOCALES[language]

    # Backward-compat: 'template: default' → 'newscast'
    template = data.get("template", "newscast")
    if template == "default":
        template = "newscast"

    # Optional DNA block
    dna_data = data.get("dna")
    dna = DnaSpec.model_validate(dna_data) if dna_data else None
    if dna is not None and dna.archetype != template:
        raise ValueError(
            f"channel.template ({template!r}) must match dna.archetype ({dna.archetype!r})"
        )

    content_source = data.get("content_source", "rss")
    if content_source not in ("rss", "generator", "feed"):
        raise ValueError(
            f"content_source must be 'rss', 'generator' or 'feed', "
            f"got {content_source!r}"
        )

    auto_feed_ids = [int(x) for x in (data.get("auto_feed_ids") or [])]
    if content_source == "feed" and not auto_feed_ids:
        raise ValueError(
            f"channel {slug!r} has content_source='feed' but no auto_feed_ids. "
            f"Add at least one feed id from the pool."
        )

    keywords = list(data.get("keywords", []))
    if content_source == "rss" and not keywords:
        raise ValueError(
            f"channel {slug!r} has content_source='rss' but no keywords. "
            f"Either add keywords or set content_source: generator (with a generator block)."
        )

    generator = None
    if content_source == "generator":
        gen_data = data.get("generator")
        if not gen_data:
            raise ValueError(
                "content_source='generator' requires a 'generator' block in YAML"
            )
        topic = (gen_data.get("topic") or "").strip()
        if len(topic) < 10:
            raise ValueError(
                f"generator.topic must be at least 10 chars, got {len(topic)}"
            )
        generator = GeneratorConfig(
            topic=topic,
            forbidden_lookback=int(gen_data.get("forbidden_lookback", 50)),
            max_retries=int(gen_data.get("max_retries", 3)),
            fuzzy_threshold=(float(gen_data["fuzzy_threshold"])
                              if "fuzzy_threshold" in gen_data else None),
        )

    yt_data = data.get("youtube")
    youtube = YoutubeChannelConfig.model_validate(yt_data) if yt_data else None

    bg_video_data = data.get("bg_video")
    bg_video = BgVideoConfig.model_validate(bg_video_data) if bg_video_data else None

    trend_boost_data = data.get("trend_boost")
    trend_boost = (TrendBoostConfig.model_validate(trend_boost_data)
                   if trend_boost_data else None)

    voice_data = data.get("voice")
    voice = VoiceConfig.model_validate(voice_data) if voice_data else None

    reel_data = data.get("reel")
    reel = ReelConfig.model_validate(reel_data) if reel_data else None

    cta = data.get("cta", {})
    return ChannelConfig(
        slug=slug,
        name=data["name"],
        keywords=keywords,
        rss_locale=rss_locale,
        schedule_cron=data["schedule_cron"],
        duration_s=int(data["duration_s"]),
        min_score=float(data["min_score"]),
        max_candidates_per_run=int(data["max_candidates_per_run"]),
        max_age_hours=int(data.get("max_age_hours", 24)),
        dynamic_dna=bool(data.get("dynamic_dna", False)),
        negative_keywords=list(data.get("negative_keywords") or []),
        reference_channels=list(data.get("reference_channels") or []),
        template=template,
        colors=dict(data["colors"]),
        handle=data["handle"],
        output_dir=data["output_dir"],
        enabled=bool(data.get("enabled", True)),
        cta_enabled=bool(cta.get("enabled", True)),
        cta_text=cta.get("text", "BEĞEN · ABONE OL · PAYLAŞ"),
        cta_icons=list(cta.get("icons", ["❤️", "🔔", "↗️"])),
        cta_duration_s=int(cta.get("duration_s", 4)),
        cta_show_handle=bool(cta.get("show_handle", True)),
        language=language,
        dna=dna,
        script_model=data.get("script_model"),
        content_source=content_source,
        generator=generator,
        auto_feed_ids=auto_feed_ids,
        youtube=youtube,
        bg_video=bg_video,
        trend_boost=trend_boost,
        bg_image_blur=int(data.get("bg_image_blur", 0)),
        voice=voice,
        reel=reel,
    )


def save_channel(path: Path, cfg: ChannelConfig) -> None:
    """Write a ChannelConfig back to YAML (inverse of load_channel)."""
    data = {
        "slug": cfg.slug,
        "name": cfg.name,
        "keywords": list(cfg.keywords),
        "language": cfg.language,
        "schedule_cron": cfg.schedule_cron,
        "duration_s": cfg.duration_s,
        "min_score": cfg.min_score,
        "max_candidates_per_run": cfg.max_candidates_per_run,
        "max_age_hours": cfg.max_age_hours,
        "template": cfg.template,
        "colors": dict(cfg.colors),
        "handle": cfg.handle,
        "output_dir": cfg.output_dir,
        "enabled": cfg.enabled,
        "cta": {
            "enabled": cfg.cta_enabled,
            "text": cfg.cta_text,
            "icons": list(cfg.cta_icons),
            "duration_s": cfg.cta_duration_s,
            "show_handle": cfg.cta_show_handle,
        },
    }
    if cfg.dynamic_dna:
        data["dynamic_dna"] = True
    if cfg.negative_keywords:
        data["negative_keywords"] = list(cfg.negative_keywords)
    if cfg.reference_channels:
        data["reference_channels"] = list(cfg.reference_channels)
    if cfg.script_model:
        data["script_model"] = cfg.script_model
    if cfg.content_source != "rss":
        data["content_source"] = cfg.content_source
    if cfg.auto_feed_ids:
        data["auto_feed_ids"] = list(cfg.auto_feed_ids)
    if cfg.generator is not None:
        gen_data = {
            "topic": cfg.generator.topic,
            "forbidden_lookback": cfg.generator.forbidden_lookback,
            "max_retries": cfg.generator.max_retries,
        }
        if cfg.generator.fuzzy_threshold is not None:
            gen_data["fuzzy_threshold"] = cfg.generator.fuzzy_threshold
        data["generator"] = gen_data
    if cfg.youtube is not None:
        data["youtube"] = {
            "auto_upload": cfg.youtube.auto_upload,
            "ai_content": cfg.youtube.ai_content,
            "category_id": cfg.youtube.category_id,
            "privacy_status": cfg.youtube.privacy_status,
            "min_score_for_upload": cfg.youtube.min_score_for_upload,
        }
        if cfg.youtube.cron_preset:
            data["youtube"]["cron_preset"] = cfg.youtube.cron_preset
    if cfg.bg_video is not None and cfg.bg_video.enabled:
        data["bg_video"] = {
            "enabled": cfg.bg_video.enabled,
            "scale": cfg.bg_video.scale,
            "blur_px": cfg.bg_video.blur_px,
            "dim": cfg.bg_video.dim,
        }
    if cfg.trend_boost is not None:
        tb = {
            "enabled": cfg.trend_boost.enabled,
            "max_boost": cfg.trend_boost.max_boost,
            "min_term_length": cfg.trend_boost.min_term_length,
            "fuzzy_threshold": cfg.trend_boost.fuzzy_threshold,
        }
        if cfg.trend_boost.sources is not None:
            tb["sources"] = list(cfg.trend_boost.sources)
        if cfg.trend_boost.exclude_terms:
            tb["exclude_terms"] = list(cfg.trend_boost.exclude_terms)
        if cfg.trend_boost.region_override:
            tb["region_override"] = cfg.trend_boost.region_override
        data["trend_boost"] = tb
    if cfg.bg_image_blur:
        data["bg_image_blur"] = cfg.bg_image_blur
    if cfg.voice is not None:
        data["voice"] = {
            "enabled": cfg.voice.enabled,
            "voice_id": cfg.voice.voice_id,
            "speed": cfg.voice.speed,
            "persona": cfg.voice.persona,
            "target_duration_s": list(cfg.voice.target_duration_s),
            "music_volume": cfg.voice.music_volume,
        }
    if cfg.reel is not None:
        data["reel"] = {
            "enabled": cfg.reel.enabled,
            "voice_id": cfg.reel.voice_id,
            "speed": cfg.reel.speed,
            "target_duration_s": list(cfg.reel.target_duration_s),
            "cut_pacing": cfg.reel.cut_pacing,
            "highlight_color": cfg.reel.highlight_color,
            "arrows_enabled": cfg.reel.arrows_enabled,
            "arrow_color": cfg.reel.arrow_color,
            "arrow_frequency": cfg.reel.arrow_frequency,
            "transitions_flash": cfg.reel.transitions_flash,
            "transitions_whoosh": cfg.reel.transitions_whoosh,
            "transitions_zoom": cfg.reel.transitions_zoom,
            "music_mood": cfg.reel.music_mood,
            "music_volume": cfg.reel.music_volume,
            "font": cfg.reel.font,
            "verify_footage": cfg.reel.verify_footage,
            "fast_cuts": cfg.reel.fast_cuts,
            "number_pop": cfg.reel.number_pop,
            "visual_loop": cfg.reel.visual_loop,
            "layout": cfg.reel.layout,
            "hook_angle_vary": cfg.reel.hook_angle_vary,
            "accent_vary": cfg.reel.accent_vary,
            "transition_vary": cfg.reel.transition_vary,
            "series_enabled": cfg.reel.series_enabled,
            "series_title": cfg.reel.series_title,
            "cta_enabled": cfg.reel.cta_enabled,
            "comment_question": cfg.reel.comment_question,
            "cta_text_custom": cfg.reel.cta_text_custom,
        }
    if cfg.dna is not None:
        # mode='json' → tuple becomes list, ready for YAML round-trip
        data["dna"] = cfg.dna.model_dump(mode="json")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def list_channels(channels_dir: Path, enabled_only: bool = False) -> list[ChannelConfig]:
    """List all channels in directory. Invalid channel YAMLs are SKIPPED with a
    warning instead of crashing the whole scheduler — this protects the panel
    boot path when a single channel references a stale archetype/setting.
    """
    import logging
    log = logging.getLogger(__name__)
    out = []
    for p in sorted(Path(channels_dir).glob("*.yaml")):
        try:
            c = load_channel(p)
        except Exception as e:
            log.warning(f"skipping invalid channel {p.name}: {e}")
            continue
        if enabled_only and not c.enabled:
            continue
        out.append(c)
    return out


@dataclass(frozen=True)
class AICall:
    backend: str            # "claude_cli" | "openrouter"
    model: str
    api_key: str | None     # openrouter'da dolu, claude_cli'da None
    claude_path: str


def resolve_ai_call(settings: Settings, secrets: dict, role: str) -> AICall:
    """role: 'dna' | 'default' | 'script' | 'vision'. Aktif backend'e göre model+key çözer."""
    if settings.ai_backend == "openrouter":
        model = (settings.openrouter_models.get(role)
                 or settings.openrouter_models.get("default", ""))
        return AICall(
            backend="openrouter",
            model=model,
            api_key=(secrets.get("openrouter_api_key", "") or None),
            claude_path=settings.claude_cli_path,
        )
    cli_fallback = "default" if role == "vision" else "haiku"
    return AICall(
        backend="claude_cli",
        model=settings.claude_models.get(role, cli_fallback),
        api_key=None,
        claude_path=settings.claude_cli_path,
    )
