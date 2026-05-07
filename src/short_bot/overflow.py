"""Render-time overflow detection + LLM retry feedback + truncate fallback.

Pipeline integration: pipeline.write_script_with_overflow_check wraps the
existing write_script call. After each LLM script attempt we render to
in-memory HTML, measure target fields with Playwright, and either:
  - return clean script
  - re-prompt LLM with surgical per-field feedback (up to 2 retries)
  - truncate the final attempt at word boundaries (Pydantic-aware) as fallback
"""
from __future__ import annotations

from dataclasses import dataclass

from playwright.sync_api import (
    sync_playwright,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
)

from short_bot.templates_config import ARCHETYPE_OVERFLOW_FIELDS, OverflowField


@dataclass
class FieldOverflow:
    name: str                    # Script attr name ("header_top", "body_paragraph", ...)
    has_overflow: bool
    current_chars: int
    current_lines: int           # Lines actually rendered (measured via JS)
    max_lines: int               # Budget from templates_config
    recommended_max_chars: int   # Target char count for the LLM's next attempt


@dataclass
class OverflowReport:
    archetype: str
    fields: dict[str, FieldOverflow]

    def has_any_overflow(self) -> bool:
        return any(f.has_overflow for f in self.fields.values())

    def summary(self) -> str:
        bad = [f for f in self.fields.values() if f.has_overflow]
        if not bad:
            return f"{self.archetype}: clean"
        parts = [
            f"{f.name} ({f.current_chars}->{f.recommended_max_chars} chars)"
            for f in bad
        ]
        return f"{self.archetype}: " + ", ".join(parts)


# Same viewport as renderer.render_frames (renderer.py uses WIDTH/HEIGHT 1080x1920)
_VIEWPORT = {"width": 1080, "height": 1920}


# JS measurement function. For each field we:
#   - Find element via querySelector(selector). If null → return null entry.
#   - Read computed line-height; lines = round(scrollHeight / lineHeight).
#   - For body: temporarily strip `-webkit-line-clamp` and `display:-webkit-box`
#     so we get the real (unclamped) scrollHeight, compare to clamped
#     clientHeight; if greater → overflow.
#   - For others: scrollHeight > clientHeight (vertical) OR
#     scrollWidth > clientWidth (horizontal) → overflow.
#   - current_chars = innerText.length (whitespace counted; LLM produces
#     similar tokens so this is a fair proxy).
_MEASURE_JS = r"""
(fields) => {
  const result = {};
  for (const f of fields) {
    const el = document.querySelector(f.selector);
    if (!el) { result[f.name] = null; continue; }

    const cs = window.getComputedStyle(el);
    const lineHeightPx = parseFloat(cs.lineHeight) ||
      (parseFloat(cs.fontSize) * 1.2);

    let unclampedScrollH = el.scrollHeight;
    let clampedClientH = el.clientHeight;
    let overflowedByClamp = false;

    // Body uses -webkit-line-clamp; remove it to measure the natural height.
    if (f.name === "body_paragraph") {
      const origClamp = el.style.webkitLineClamp;
      const origDisplay = el.style.display;
      const origMask = el.style.webkitMaskImage;
      const origMaskStd = el.style.maskImage;
      // Toggle off
      el.style.webkitLineClamp = "unset";
      el.style.display = "block";
      el.style.webkitMaskImage = "none";
      el.style.maskImage = "none";
      // Force layout
      void el.offsetHeight;
      const realH = el.scrollHeight;
      // Restore
      el.style.webkitLineClamp = origClamp;
      el.style.display = origDisplay;
      el.style.webkitMaskImage = origMask;
      el.style.maskImage = origMaskStd;
      void el.offsetHeight;

      const allowedH = f.max_lines * lineHeightPx;
      overflowedByClamp = realH > allowedH + 1;
      unclampedScrollH = realH;
      clampedClientH = allowedH;
    }

    // Line-count comparison avoids false positives from font ink overflow
    // (scrollHeight includes descenders which inflate it vs clientHeight).
    const current_lines = Math.max(1,
      Math.round(unclampedScrollH / lineHeightPx));
    const overflowsV = current_lines > f.max_lines;
    const overflowsH = el.scrollWidth > el.clientWidth + 1;
    const has_overflow = overflowsV || overflowsH || overflowedByClamp;
    const text = (el.innerText || el.textContent || "").trim();
    const current_chars = text.length;

    let recommended_max_chars = current_chars;
    if (has_overflow && current_lines > 0) {
      const target = Math.floor(
        current_chars * (f.max_lines * 0.9) / current_lines
      );
      recommended_max_chars = Math.max(1, target);
    }

    result[f.name] = {
      has_overflow,
      current_chars,
      current_lines,
      max_lines: f.max_lines,
      recommended_max_chars,
    };
  }
  return result;
}
"""


def check_overflow(
    html: str,
    archetype: str,
    *,
    timeout_s: float = 10.0,
) -> OverflowReport:
    """Render HTML in headless Chromium and measure each configured field.

    Raises KeyError if archetype is not registered in
    ARCHETYPE_OVERFLOW_FIELDS — silent skip would mask config bugs.
    Raises PlaywrightError / PlaywrightTimeout to caller; pipeline wrapper
    catches these and falls back to the unchecked script.
    """
    fields = ARCHETYPE_OVERFLOW_FIELDS[archetype]
    payload = [
        {"name": f.name, "selector": f.selector, "max_lines": f.max_lines}
        for f in fields
    ]

    timeout_ms = int(timeout_s * 1000)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport=_VIEWPORT, device_scale_factor=1)
            page.set_default_timeout(timeout_ms)
            page.set_content(html, wait_until="domcontentloaded")
            measurements = page.evaluate(_MEASURE_JS, payload)
        finally:
            browser.close()

    out: dict[str, FieldOverflow] = {}
    for f in fields:
        m = measurements.get(f.name)
        if m is None:
            # Selector not in DOM — skip. (e.g. kinetic has no photo_overlay.)
            continue
        out[f.name] = FieldOverflow(
            name=f.name,
            has_overflow=bool(m["has_overflow"]),
            current_chars=int(m["current_chars"]),
            current_lines=int(m["current_lines"]),
            max_lines=int(m["max_lines"]),
            recommended_max_chars=int(m["recommended_max_chars"]),
        )
    return OverflowReport(archetype=archetype, fields=out)
