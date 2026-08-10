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

from playwright.sync_api import sync_playwright

from short_bot.models import Highlight, Script
from short_bot.templates_config import ARCHETYPE_OVERFLOW_FIELDS


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
# recommended_max_chars is computed in Python (_compute_recommended_chars)
# so it can be unit-tested without spinning up Playwright.
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
    let overflowedByClamp = false;

    // Feature-detect line-clamp instead of gating on field name — meme's
    // .body renders header_bottom (not body_paragraph) and other archetypes
    // could remap fields to clamped elements too.
    const isClamped = cs.webkitLineClamp && cs.webkitLineClamp !== "none" &&
                      cs.display === "-webkit-box";
    if (isClamped) {
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

    result[f.name] = {
      has_overflow,
      current_chars,
      current_lines,
      max_lines: f.max_lines,
    };
  }
  return result;
}
"""


def _compute_recommended_chars(
    *, current_chars: int, current_lines: int,
    max_lines: int, has_overflow: bool,
) -> int:
    """Target char count for the LLM's next attempt.

    INVARIANT: when has_overflow is True, the recommendation is strictly
    less than current_chars. Old JS computed
    `current * max_lines * 0.9 / current_lines` which can exceed current
    when overflow is purely horizontal (current_lines < max_lines but
    width exceeded). LLM saw "max 36" with current=20 and didn't shorten
    → infinite retry → truncate fallback. We now floor the target by
    current_chars - 1 so each retry monotonically narrows the window.
    """
    if not has_overflow or current_lines == 0:
        return current_chars
    # Same proportional formula as before, integer division for stability.
    target = (current_chars * max_lines * 9) // (current_lines * 10)
    # YATAY taşmada (satır sayısı bütçe içinde ama genişlik aşılmış) oransal
    # formül current'in ÜSTÜNE çıkar ve eski cap=current-1 her turda yalnız 1
    # karakter kırpardı. 3 retry'lık bütçe 3 karakter ilerletiyordu; gerçek
    # koşuda 16->15->14->13 diye gidip truncate'e düşüyordu ve kanal
    # manşetlerinin %59'u kesik çıkıyordu. Yatay durumda sabit oranlı (%15)
    # kırpma uygula — dikey taşmada oransal formül zaten doğru daralıyor.
    cap = max(1, (current_chars * 85) // 100)
    if cap >= current_chars:            # çok kısa metinlerde oran yuvarlanır
        cap = current_chars - 1
    return max(1, min(target, cap))


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
        has_overflow = bool(m["has_overflow"])
        current_chars = int(m["current_chars"])
        current_lines = int(m["current_lines"])
        max_lines = int(m["max_lines"])
        out[f.name] = FieldOverflow(
            name=f.name,
            has_overflow=has_overflow,
            current_chars=current_chars,
            current_lines=current_lines,
            max_lines=max_lines,
            recommended_max_chars=_compute_recommended_chars(
                current_chars=current_chars,
                current_lines=current_lines,
                max_lines=max_lines,
                has_overflow=has_overflow,
            ),
        )
    return OverflowReport(archetype=archetype, fields=out)


def format_feedback(report: OverflowReport) -> str:
    """English block appended to the LLM script-generation prompt on retry.

    Why English: existing prompts in script_writer.build_script_prompt are
    English (`TASK: Convert this news ...`). Output language is controlled
    separately via `Output language: <name>`, so DE/FR/EN channels still get
    correct field values.
    """
    bad = [f for f in report.fields.values() if f.has_overflow]
    if not bad:
        return ""

    lines = ["PREVIOUS ATTEMPT OVERFLOWED THESE FIELDS — REWRITE SHORTER:"]
    for f in bad:
        lines.append(
            f"- {f.name}: currently {f.current_chars} chars, "
            f"must be <= {f.recommended_max_chars} chars "
            f"({f.max_lines}-line limit)"
        )

    ok = sorted(
        n for n, f in report.fields.items() if not f.has_overflow
    )
    if ok:
        lines.append(
            "Other fields (" + ", ".join(ok) + ") are OK, "
            "keep them at the same length."
        )
    return "\n".join(lines)


# Pydantic min_length floors from models.py:40-46 — truncate must respect them.
_FIELD_MIN_CHARS: dict[str, int] = {
    "header_top": 1,
    "header_bottom": 1,
    "photo_overlay": 1,
    "body_paragraph": 20,
}


def _smart_cut(text: str, target_chars: int) -> str:
    """Truncate at word boundary, append U+2026 ellipsis. Preserves whole words.

    If text is already <= target_chars, returns text unchanged.
    If target_chars is <1, returns "" (caller should floor by min_length first).
    """
    if target_chars < 1:
        return ""
    if len(text) <= target_chars:
        return text

    # Hard cut at target, then back up to the previous space.
    cut = text[:target_chars]
    # Prefer last space; if no space (single word), keep hard cut as-is.
    last_space = cut.rfind(" ")
    if last_space >= max(1, target_chars // 2):
        cut = cut[:last_space]
    cut = cut.rstrip()
    if not cut:
        cut = text[:target_chars].rstrip()
    return cut + "…"


def truncate_to_fit(script: Script, report: OverflowReport) -> Script:
    """Hard-cut overflowing fields and rebuild the Script.

    Floors recommended_max_chars by the Pydantic field's min_length
    (slight overflow may remain on the smallest fields, but the script
    will validate).

    For body_paragraph: any highlight whose text is no longer contained
    in the truncated body is dropped — otherwise the
    `highlights_must_be_substrings` model_validator (models.py:55-62)
    raises ValidationError.

    Raises ValidationError if the resulting Script still cannot be built
    (very rare edge case — caller in pipeline catches and falls back).
    """
    updates: dict[str, object] = {}

    for name, fo in report.fields.items():
        if not fo.has_overflow:
            continue
        if name not in _FIELD_MIN_CHARS:
            continue
        original = getattr(script, name)
        target = max(_FIELD_MIN_CHARS[name], fo.recommended_max_chars)
        truncated = _smart_cut(original, target)
        # Floor: if smart_cut removed too much (single long word), keep at
        # least min_length chars by hard-cutting the original text.
        if len(truncated) < _FIELD_MIN_CHARS[name]:
            truncated = original[:_FIELD_MIN_CHARS[name]]
        updates[name] = truncated

    if not updates:
        return script

    # If body changed, drop highlights whose text no longer appears.
    if "body_paragraph" in updates:
        new_body = updates["body_paragraph"]
        kept = [h for h in script.highlights if h.text in new_body]
        updates["highlights"] = kept

    return script.model_copy(update=updates)
