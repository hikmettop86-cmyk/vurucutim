"""Channel DNA: Pydantic models for visual + content identity (archetype + palette + tone)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


ARCHETYPES = ["newscast", "tabloid", "magazine", "kinetic", "dark-tech", "stadium", "meme"]


class DnaPalette(BaseModel):
    primary: str
    accent: str
    bg_gradient: list[str] = Field(min_length=2, max_length=2)
    body_bg: list[str] = Field(min_length=2, max_length=2)
    text_main: str = "#ffffff"
    text_muted: str = "#cccccc"

    @field_validator("primary", "accent", "text_main", "text_muted")
    @classmethod
    def _validate_hex(cls, v: str) -> str:
        if not (v.startswith("#") and len(v) == 7):
            raise ValueError(f"Invalid hex color: {v!r} (expected #RRGGBB)")
        try:
            int(v[1:], 16)
        except ValueError as e:
            raise ValueError(f"Invalid hex color: {v!r}") from e
        return v.lower()


class DnaFonts(BaseModel):
    headline: str = "Inter"
    body: str = "Inter"
    google_imports: list[str] = Field(default_factory=list)


class DnaTone(BaseModel):
    voice: str = Field(min_length=1, max_length=200)
    style: str = Field(min_length=1, max_length=200)
    forbidden: list[str] = Field(default_factory=list, max_length=10)
    sentence_max_words: int = Field(ge=4, le=40, default=18)
    paragraph_sentences: tuple[int, int] = (3, 5)
    body_max_chars: int = Field(ge=50, le=800, default=350)
    headline_style_hint: str = Field(default="", max_length=200)


class DnaSpec(BaseModel):
    archetype: Literal["newscast", "tabloid", "magazine", "kinetic", "dark-tech", "stadium", "meme"]
    palette: DnaPalette
    fonts: DnaFonts
    tone: DnaTone
    banner_shape: Literal["flat", "ribbon", "slanted", "sharp"] = "flat"
    highlight_style: Literal["bg-flat", "underline", "marker", "neon"] = "bg-flat"
    chip_style: Literal["rounded", "sharp", "pill"] = "rounded"
    category_icon: str = ""
    search_query_template: str = "{header_top} {header_bottom} {category}"
    persona_summary: str = Field(max_length=400)
