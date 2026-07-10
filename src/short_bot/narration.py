"""Anlatım (voiced) domain modelleri.

Segment indeksleme (``TimedWord.seg``):
  0        → hook
  1..N     → beats[0..N-1]
  N+1      → loop_close
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from short_bot.text_normalize import strip_non_turkish_diacritics


class Beat(BaseModel):
    """Bir anlatı vuruşu: söylenen cümle(ler) + o sırada ekranda duran kart."""
    text: str = Field(min_length=10, max_length=400)
    on_screen: str = Field(min_length=1, max_length=60)

    @field_validator("text", "on_screen", mode="before")
    @classmethod
    def _normalize_text(cls, v):
        return strip_non_turkish_diacritics(v) if isinstance(v, str) else v


class Narration(BaseModel):
    """LLM'in ürettiği anlatım senaryosu."""
    hook: str = Field(min_length=5, max_length=140)
    beats: list[Beat] = Field(min_length=3, max_length=5)
    loop_close: str = Field(min_length=5, max_length=160)
    mood: Literal["breaking", "neutral", "upbeat"]

    @field_validator("hook", "loop_close", mode="before")
    @classmethod
    def _normalize_text(cls, v):
        return strip_non_turkish_diacritics(v) if isinstance(v, str) else v

    def segments(self) -> list[str]:
        """Seslendirilecek metin parçaları, sırayla."""
        return [self.hook, *[b.text for b in self.beats], self.loop_close]

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
class TimedBeat:
    on_screen: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class NarrationTimeline:
    """Render'a giren zaman çizelgesi: karaoke kelimeleri + sahne beat'leri."""
    words: list[TimedWord]
    beats: list[TimedBeat]
    duration_s: float
    hook: str
    loop_close: str
