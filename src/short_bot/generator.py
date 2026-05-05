"""Content generator: Sonnet-driven short content with 3-layer dedup."""
from __future__ import annotations

from pydantic import BaseModel, Field

from short_bot.models import Script


class GeneratorRetryExhausted(RuntimeError):
    """Raised when all dedup retries return duplicates — topic likely exhausted."""


class GeneratorResult(BaseModel):
    text: str = Field(min_length=10, max_length=200)
    topic_tag: str = Field(
        min_length=2,
        max_length=20,
        pattern=r"^[a-zçğıöşü]+$",   # Turkish lowercase, single word
    )
    script: Script
    image_keywords: list[str] = Field(min_length=2, max_length=8)
