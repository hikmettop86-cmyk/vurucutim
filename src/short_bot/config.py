"""YAML config loader for global settings and per-channel configs."""
from dataclasses import dataclass
from pathlib import Path
import re

import yaml

from short_bot.locale import RSS_LOCALES, SUPPORTED_LANGUAGES

SLUG_RE = re.compile(r"^[a-z0-9\-]+$")


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


def load_settings(path: Path) -> Settings:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    web = data.get("web", {})
    return Settings(
        ffmpeg_path=data["ffmpeg_path"],
        claude_cli_path=data["claude_cli_path"],
        playwright_browser=data.get("playwright_browser", "chromium"),
        web_host=web.get("host", "127.0.0.1"),
        web_port=int(web.get("port", 5000)),
        fuzzy_dedup_threshold=float(data.get("fuzzy_dedup_threshold", 0.85)),
        log_level=data.get("log_level", "INFO"),
        claude_models=dict(data.get("claude_models", {"dna": "opus", "default": "haiku"})),
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

    cta = data.get("cta", {})
    return ChannelConfig(
        slug=slug,
        name=data["name"],
        keywords=list(data.get("keywords", [])),
        rss_locale=rss_locale,
        schedule_cron=data["schedule_cron"],
        duration_s=int(data["duration_s"]),
        min_score=float(data["min_score"]),
        max_candidates_per_run=int(data["max_candidates_per_run"]),
        template=data["template"],
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
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def list_channels(channels_dir: Path, enabled_only: bool = False) -> list[ChannelConfig]:
    out = []
    for p in sorted(Path(channels_dir).glob("*.yaml")):
        c = load_channel(p)
        if enabled_only and not c.enabled:
            continue
        out.append(c)
    return out
