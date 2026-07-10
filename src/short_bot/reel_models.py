"""Reel (footage-sürüklü) domain modelleri.

Segment indeksleme (TimedWord.seg): 0=hook, 1..N=beats, N+1=close.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from short_bot.text_normalize import strip_non_turkish_diacritics


class ReelBeat(BaseModel):
    text: str = Field(min_length=8, max_length=300)
    visual_query: str = Field(min_length=2, max_length=120)
    keyword: str = Field(default="", max_length=40)

    @field_validator("text", "keyword", mode="before")
    @classmethod
    def _norm(cls, v):
        return strip_non_turkish_diacritics(v) if isinstance(v, str) else v

    @field_validator("visual_query")
    @classmethod
    def _query_nonblank(cls, v):
        if not (v or "").strip():
            raise ValueError("visual_query boş olamaz")
        return v.strip()


class ReelNarration(BaseModel):
    hook: str = Field(min_length=5, max_length=140)
    beats: list[ReelBeat] = Field(min_length=3, max_length=6)
    close: str = Field(min_length=5, max_length=160)
    mood: Literal["upbeat", "neutral", "calm"]

    @field_validator("hook", "close", mode="before")
    @classmethod
    def _norm(cls, v):
        return strip_non_turkish_diacritics(v) if isinstance(v, str) else v

    def segments(self) -> list[str]:
        return [self.hook, *[b.text for b in self.beats], self.close]

    def segment_queries(self) -> list[str | None]:
        return [None, *[b.visual_query for b in self.beats], None]

    def segment_keywords(self) -> list[str]:
        return ["", *[b.keyword for b in self.beats], ""]

    def full_text(self) -> str:
        return " ".join(self.segments())

    def word_count(self) -> int:
        return len(self.full_text().split())


@dataclass(frozen=True)
class TimedWord:
    word: str
    start_s: float
    end_s: float
    seg: int


@dataclass(frozen=True)
class ReelTimeline:
    words: list[TimedWord]
    seg_spans: list[tuple[float, float]]   # her segmentin [start, end]'i
    seg_queries: list[str | None]          # footage sorgusu (hook/close None)
    seg_keywords: list[str]                # ekran kartı metni
    duration_s: float
    hook: str
    close: str
