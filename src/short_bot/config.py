"""YAML config loader for global settings and per-channel configs."""
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Literal

import yaml
from pydantic import BaseModel, Field


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


def load_settings(path: Path) -> Settings:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    web = data.get("web", {})
    tr_data = data.get("trends", {}) or {}
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
