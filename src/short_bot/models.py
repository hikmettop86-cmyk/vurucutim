"""Domain models. Frozen dataclasses for in-pipeline data, Pydantic for LLM output."""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


@dataclass(frozen=True)
class NewsItem:
    guid: str
    title: str
    link: str
    source: str | None
    pub_date: datetime | None
    thumb_url: str | None
    description: str | None


@dataclass(frozen=True)
class ScoredItem:
    item: NewsItem
    score: float            # 0-10
    reasoning: str          # LLM's short rationale (debug/UI)


class Highlight(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    color: Literal["red", "yellow"]


class Script(BaseModel):
    header_top: str = Field(min_length=1, max_length=40)
    header_bottom: str = Field(min_length=1, max_length=40)
    photo_overlay: str = Field(min_length=1, max_length=60)
    body_paragraph: str = Field(min_length=20, max_length=800)
    highlights: list[Highlight] = Field(default_factory=list, max_length=8)
    category: str = Field(min_length=1, max_length=30)
    mood: Literal["breaking", "neutral", "upbeat"]

    @model_validator(mode="after")
    def highlights_must_be_substrings(self) -> "Script":
        for h in self.highlights:
            if h.text not in self.body_paragraph:
                raise ValueError(
                    f"Highlight '{h.text}' paragrafta birebir geçmiyor"
                )
        return self


@dataclass
class RenderJob:
    script: Script
    bg_image_path: Path | None
    music_path: Path
    channel_colors: dict
    handle: str
    duration_s: int
    language: str = "tr"
    cta_enabled: bool = True
    cta_text: str = "BEĞEN · ABONE OL · PAYLAŞ"
    cta_icons: list[str] = field(default_factory=lambda: ["❤️", "🔔", "↗️"])
    cta_duration_s: int = 4
    cta_show_handle: bool = True
