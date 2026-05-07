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
    "newscast": [
        OverflowField("header_top",     ".header .top",      2),
        OverflowField("header_bottom",  ".header .bot",      1),
        OverflowField("photo_overlay",  ".photo .yellow",    2),
        OverflowField("body_paragraph", ".body",             9),
    ],
    "tabloid": [
        OverflowField("header_top",     ".header .top",      1),
        OverflowField("header_bottom",  ".header .bot",      1),
        OverflowField("photo_overlay",  ".photo .yellow",    2),
        OverflowField("body_paragraph", ".body",             8),
    ],
    "magazine": [
        OverflowField("header_top",     ".header .top",      2),
        OverflowField("header_bottom",  ".header .bot",      2),
        OverflowField("photo_overlay",  ".photo .caption",   2),
        OverflowField("body_paragraph", ".body",             8),
    ],
    "kinetic": [
        OverflowField("header_top",     ".header .top",      1),
        OverflowField("header_bottom",  ".header .bot",      2),
        # No photo_overlay — kinetic template has no overlay element
        OverflowField("body_paragraph", ".body",             3),
    ],
    "dark-tech": [
        OverflowField("header_top",     ".header .top",      2),
        OverflowField("header_bottom",  ".header .bot",      2),
        OverflowField("photo_overlay",  ".photo .label",     2),
        OverflowField("body_paragraph", ".body",             8),
    ],
    "stadium": [
        OverflowField("header_top",     ".header .top",      1),
        OverflowField("header_bottom",  ".header .bot",      2),
        OverflowField("photo_overlay",  ".photo .yellow",    2),
        OverflowField("body_paragraph", ".body",             7),
    ],
    "meme": [
        OverflowField("header_top",     ".header .top",      2),
        OverflowField("header_bottom",  ".header .bot",      2),
        OverflowField("photo_overlay",  ".photo .overlay-text", 2),
        OverflowField("body_paragraph", ".body",             2),
    ],
}
