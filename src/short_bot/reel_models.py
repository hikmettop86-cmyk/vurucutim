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
    # Hook/close KENDİ görsel sorgusu (İngilizce stok araması). Boşsa ilk/son
    # beat'in sorgusu ödünç alınır (eski davranış). Hook videonun en kritik
    # karesi — kendi vurucu görselini hak eder (gerçek şikâyet: "ilk girişteki
    # görüntü alakasız" — hook, soyut bir beat sorgusunun çöp fallback'ini almıştı).
    hook_visual: str = Field(default="", max_length=120)
    close_visual: str = Field(default="", max_length=120)

    @field_validator("hook", "close", mode="before")
    @classmethod
    def _norm(cls, v):
        return strip_non_turkish_diacritics(v) if isinstance(v, str) else v

    def segments(self) -> list[str]:
        return [self.hook, *[b.text for b in self.beats], self.close]

    def segment_queries(self) -> list[str | None]:
        """Segment başına footage sorgusu. hook/close kendi sorgusunu kullanır;
        boşsa None → çağıran ilk/son beat'in sorgusuna düşer."""
        hook_q = (self.hook_visual or "").strip() or None
        close_q = (self.close_visual or "").strip() or None
        return [hook_q, *[b.visual_query for b in self.beats], close_q]

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


def _proportional(words: list[str], duration_s: float) -> list[tuple[float, float]]:
    weights = [max(1, len(w)) for w in words]
    total = sum(weights)
    out, cursor = [], 0.0
    for i, w in enumerate(weights):
        span = duration_s * w / total
        end = duration_s if i == len(weights) - 1 else cursor + span
        out.append((cursor, end))
        cursor = end
    return out


def build_reel_timeline(narration: "ReelNarration", asr_words: list[TimedWord],
                        *, duration_s: float) -> "ReelTimeline":
    if duration_s <= 0:
        raise ValueError(f"duration_s pozitif olmalı, got {duration_s}")

    words_flat: list[str] = []
    segs_flat: list[int] = []
    for seg_idx, seg_text in enumerate(narration.segments()):
        for w in seg_text.split():
            words_flat.append(w)
            segs_flat.append(seg_idx)

    if len(asr_words) == len(words_flat) and asr_words:
        times = [(w.start_s, w.end_s) for w in asr_words]
    else:
        times = _proportional(words_flat, duration_s)

    timed = [TimedWord(word=w, start_s=t[0], end_s=t[1], seg=s)
             for w, s, t in zip(words_flat, segs_flat, times)]

    n_segs = len(narration.segments())
    seg_spans: list[tuple[float, float]] = []
    for si in range(n_segs):
        chunk = [tw for tw in timed if tw.seg == si]
        if chunk:
            seg_spans.append((chunk[0].start_s, chunk[-1].end_s))
        else:
            prev = seg_spans[-1][1] if seg_spans else 0.0
            seg_spans.append((prev, prev))

    return ReelTimeline(
        words=timed, seg_spans=seg_spans,
        seg_queries=narration.segment_queries(),
        seg_keywords=narration.segment_keywords(),
        duration_s=duration_s, hook=narration.hook, close=narration.close,
    )
