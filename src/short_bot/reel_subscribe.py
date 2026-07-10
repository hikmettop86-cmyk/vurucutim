"""Reel abone mekanikleri: seri çerçevesi + yorum-sorusu + CTA son kartı.

Deterministik (seed → sabit), havuzdan rotasyon (şablon parmak izi vermez).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

COMMENT_QUESTIONS = (
    "Sen biliyor muydun? Yorumlara yaz.",
    "Hangisi seni en çok şaşırttı?",
    "Bunu bilen var mıydı aranızda?",
    "Sence en ilginci hangisiydi?",
)
CTA_TEXTS = (
    "Her gün yeni bilgi — ABONE OL",
    "Kaçırma, ABONE OL",
    "Daha fazlası için ABONE OL",
    "Bunu sevdiysen ABONE OL",
)


@dataclass(frozen=True)
class SubscribeBits:
    series_directive: str
    comment_line: str
    cta_text: str


def _idx(seed: int, salt: str, n: int) -> int:
    h = hashlib.sha1(f"{seed}:{salt}".encode("utf-8")).hexdigest()
    return int(h, 16) % n


def build_subscribe_bits(channel, seed: int) -> SubscribeBits:
    reel = channel.reel

    series_directive = ""
    if getattr(reel, "series_enabled", False):
        title = (getattr(reel, "series_title", "") or "İlginç Bilgiler").strip()
        series_directive = (
            f"Bu bir '{title}' serisinin bir bölümü. Kapanışı, izleyiciyi bir "
            f"sonraki bölüm için meraklandıracak bir AÇIK DÖNGÜ / teaser ile bitir "
            f"('bir sonrakinde daha da tuhafı var' tarzı)."
        )

    comment_line = ""
    if getattr(reel, "comment_question", False):
        comment_line = COMMENT_QUESTIONS[_idx(seed, "comment", len(COMMENT_QUESTIONS))]

    cta_text = ""
    if getattr(reel, "cta_enabled", False):
        custom = (getattr(reel, "cta_text_custom", "") or "").strip()
        cta_text = custom or CTA_TEXTS[_idx(seed, "cta", len(CTA_TEXTS))]

    return SubscribeBits(series_directive=series_directive,
                         comment_line=comment_line, cta_text=cta_text)
