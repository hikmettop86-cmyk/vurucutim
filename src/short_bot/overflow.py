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
