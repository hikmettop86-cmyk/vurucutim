"""Per-archetype overflow check configuration.

Each archetype maps to a list of OverflowField — which CSS selectors to
measure and how many lines of text are visually allowed before content
overflows the layout. Used by overflow.check_overflow().
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OverflowField:
    name: str           # Script field name ("header_top", "body_paragraph", ...)
    selector: str       # CSS selector — Playwright querySelector target
    max_lines: int      # Max visually allowed lines before overflow


ARCHETYPE_OVERFLOW_FIELDS: dict[str, list[OverflowField]] = {
    # newscast: 100px Inter font header (padding 78px/44px, 1080px wide) — .top at 100px
    # gives ~9-10 chars/line in non-bold display; 23-char German compound words need 3 lines.
    # .bot also 100px → 2-3 lines; 64px photo .yellow → 2-5 lines; 48px body clamped at
    # 9 lines CSS (-webkit-line-clamp: 9). Budget = clamp so any cut triggers retry.
    "newscast": [
        OverflowField("header_top",     ".header .top",      3),
        OverflowField("header_bottom",  ".header .bot",      3),
        OverflowField("photo_overlay",  ".photo .yellow",    5),
        OverflowField("body_paragraph", ".body",              99),
    ],
    # stadium: 200px Oswald header → ~5 chars/line → 4 lines max for 25-char inputs;
    # 64px .yellow overlay → 3-4 lines; body 36px font (~30 chars/line).
    # Body budget yüksek (99) — channel custom_css elements (::first-letter, gradients,
    # padding override) Playwright scrollHeight ölçümünü şişirip yanlış overflow
    # raporluyordu, truncate "..." sonu sürekli aktif oluyordu. CSS line-clamp 11
    # zaten görsel kesim yapar, mask gradient ile son satır graceful fade out.
    "stadium": [
        OverflowField("header_top",     ".header .top",      4),
        OverflowField("header_bottom",  ".header .bot",      2),
        OverflowField("photo_overlay",  ".photo .yellow",    4),
        OverflowField("body_paragraph", ".body",             99),
    ],
    # stat-hero: 80px header .top + 56px .bot, NOWRAP with width-fit JS shrink.
    # Body is split — .stat-number renders a JS-extracted figure (e.g. "%54,3"),
    # .stat-caption holds the rest. Both use auto-fit (number 120-280px,
    # caption 24-42px). Generous clamp budgets so the script writer's natural
    # 180-char-cap body doesn't trigger spurious overflow retries.
    "stat-hero": [
        OverflowField("header_top",     ".header .top",   3),
        OverflowField("header_bottom",  ".header .bot",   3),
        OverflowField("photo_overlay",  ".photo .yellow", 3),
        OverflowField("body_paragraph", ".stat-caption",  99),
    ],
    # bigquote: body_paragraph = THE QUOTE (dominates the frame).
    "bigquote": [
        OverflowField("header_top",     ".attribution .who",  2),
        OverflowField("header_bottom",  ".attribution .when", 1),
        OverflowField("photo_overlay",  ".caption",           3),
        OverflowField("body_paragraph", ".quote-text",        6),
    ],
    # ─── Designed archetypes (from share zip, 2026-05-20) — all spec-compliant
    # Standard selectors: .header .top, .header .bot, .yellow (photo_overlay),
    # .body-text (body, auto-fit handles size; max_lines=99 = clamp-only).
    **{
        slug: [
            OverflowField("header_top",     ".header .top",   3),
            OverflowField("header_bottom",  ".header .bot",   3),
            OverflowField("photo_overlay",  ".yellow",        2),
            OverflowField("body_paragraph", ".body-text",    99),
        ]
        for slug in (
            "editorial", "neon", "tabloid", "brutalist",
            "noir", "popblock", "broadsheet", "holo",
            "extra", "manifesto", "polaroid", "story",
        )
    },
}
