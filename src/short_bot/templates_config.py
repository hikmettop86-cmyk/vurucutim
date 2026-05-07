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
        OverflowField("body_paragraph", ".body",             9),
    ],
    # tabloid: 180px Bebas Neue header (~6 chars/line) → 2 lines at 15 chars is normal;
    # 96px .yellow overlay → wide font, 3-4 lines for ~50 chars; 44px italic body clamped
    # at 8 lines CSS (-webkit-line-clamp: 8). Budget = clamp so any cut triggers retry.
    "tabloid": [
        OverflowField("header_top",     ".header .top",      4),
        OverflowField("header_bottom",  ".header .bot",      4),
        OverflowField("photo_overlay",  ".photo .yellow",    5),
        OverflowField("body_paragraph", ".body",             8),
    ],
    # magazine: 110px Playfair italic header → ~8 chars/line (serif wider than sans);
    # 26 DE chars need 3 lines. 28px caption (small, 2 lines); 38px Playfair body clamped
    # at 8 lines CSS (-webkit-line-clamp: 8). Budget = clamp so any cut triggers retry.
    "magazine": [
        OverflowField("header_top",     ".header .top",      2),
        OverflowField("header_bottom",  ".header .bot",      3),
        OverflowField("photo_overlay",  ".photo .caption",   2),
        OverflowField("body_paragraph", ".body",             8),
    ],
    # kinetic: 320px Anton header (.top) — giant display font, ~3 chars/line; at 25 char
    # Pydantic max that is ~8 lines, but 4 is the realistic visual capacity for short labels.
    # body clamped at 3 lines CSS (-webkit-line-clamp: 3). Budget = clamp so any cut triggers
    # retry. Synthetic medium/long body tiers exceed this — those are xfailed in the matrix.
    "kinetic": [
        OverflowField("header_top",     ".header .top",      4),
        OverflowField("header_bottom",  ".header .bot",      2),
        # No photo_overlay — kinetic template has no overlay element
        OverflowField("body_paragraph", ".body",             3),
    ],
    # dark-tech: flex:1 body area, JetBrains Mono, body clamped at 8 lines CSS
    # (-webkit-line-clamp: 8). Budget = clamp so any cut triggers retry.
    # .bot is 90px font → ~10 chars/line, 3 lines for 26-char inputs.
    "dark-tech": [
        OverflowField("header_top",     ".header .top",      2),
        OverflowField("header_bottom",  ".header .bot",      3),
        OverflowField("photo_overlay",  ".photo .label",     2),
        OverflowField("body_paragraph", ".body",             8),
    ],
    # stadium: 200px Oswald header → ~5 chars/line → 4 lines max for 25-char inputs;
    # 64px .yellow overlay → 3-4 lines; body clamped at 7 lines CSS (-webkit-line-clamp: 7).
    # Budget = clamp so any cut triggers retry.
    "stadium": [
        OverflowField("header_top",     ".header .top",      4),
        OverflowField("header_bottom",  ".header .bot",      2),
        OverflowField("photo_overlay",  ".photo .yellow",    4),
        OverflowField("body_paragraph", ".body",             7),
    ],
    # meme: 160px Impact header → ~7 chars/line → 4 lines for 25-char inputs; 26px
    # overlay-text (small, 2 lines OK); 110px Impact .body (renders header_bottom,
    # 35 char max) → 2-3 lines.
    "meme": [
        OverflowField("header_top",     ".header .top",         4),
        OverflowField("photo_overlay",  ".photo .overlay-text", 2),
        # Meme template (templates/meme.html.j2:140-149) has no .header .bot
        # element — header is only `<span class="top">`. The `.body` element
        # renders `script.header_bottom`, NOT body_paragraph. body_paragraph
        # is unused by meme.
        OverflowField("header_bottom",  ".body",                2),
    ],
    # politika: 64px Source Serif 4 .top (gold, uppercase) → 2 lines for 25-char inputs;
    # 92px serif .bot → 2 lines; 28px italic .source overlay → 2 lines; 44px body clamped
    # at 9 lines CSS (-webkit-line-clamp: 9). Budget = clamp so any cut triggers retry.
    "politika": [
        OverflowField("header_top",     ".header .top",      2),
        OverflowField("header_bottom",  ".header .bot",      2),
        OverflowField("photo_overlay",  ".photo .source",    2),
        OverflowField("body_paragraph", ".body",             9),
    ],
    # ekonomi: 60px JetBrains Mono .top (green, uppercase) → 2 lines for 25-char inputs;
    # 90px Inter .bot → 2 lines; 88px JetBrains Mono .ticker-num (gold callout) → 2 lines;
    # 42px Inter body clamped at 9 lines CSS (-webkit-line-clamp: 9). Budget = clamp so
    # any cut triggers retry.
    "ekonomi": [
        OverflowField("header_top",     ".header .top",       2),
        OverflowField("header_bottom",  ".header .bot",       2),
        OverflowField("photo_overlay",  ".photo .ticker-num", 2),
        OverflowField("body_paragraph", ".body",              9),
    ],
}
