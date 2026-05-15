"""Format channel insights as a scorer-prompt hint.

The hint is INJECTED INTO the existing scoring prompt as a "kanal geçmişi"
block. We keep it short (sentences, not paragraphs) and only include data
points that have enough samples to be trustworthy (n>=2 for categories,
n>=3 for moods). When sample_size is too small the hint returns empty
string — better to use Claude's generic judgement than to anchor on noise.
"""
from __future__ import annotations

from typing import Any

_MIN_TOTAL_SAMPLES = 5         # below this, no hint at all (data too sparse)
_MIN_MOOD_SAMPLES = 3
_MIN_CATEGORY_SAMPLES_FOR_HINT = 2


def format_scorer_hint(insights: dict[str, Any] | None) -> str:
    """Build a Turkish hint block to inject into the scorer prompt.

    Returns an empty string when insights are missing or too sparse.
    Caller appends the returned string to its prompt (no leading/trailing
    newlines built in — caller decides whitespace).
    """
    if not insights:
        return ""
    if insights.get("sample_size", 0) < _MIN_TOTAL_SAMPLES:
        return ""

    lines: list[str] = []
    lines.append("KANAL GEÇMİŞ PERFORMANSI (son 30 gün, gerçek YouTube verisi):")

    # Top categories (only the 3 strongest, with n>=2)
    cats = [
        c for c in insights.get("top_categories", [])
        if c.get("n", 0) >= _MIN_CATEGORY_SAMPLES_FOR_HINT
    ][:3]
    if cats:
        cat_strs = []
        for c in cats:
            cat_strs.append(
                f"{c['category']} (n={c['n']}, avg {int(c['avg_views'])} view"
                + (f", %{int(c['avg_watch_pct'])} watch" if c['avg_watch_pct'] > 0 else "")
                + ")"
            )
        lines.append("- En çok izlenen kategoriler: " + ", ".join(cat_strs))

    # Mood guidance — only mention moods with enough samples
    strong_moods = [
        m for m in insights.get("top_moods", [])
        if m.get("n", 0) >= _MIN_MOOD_SAMPLES
    ]
    if strong_moods:
        best = strong_moods[0]
        worst = strong_moods[-1] if len(strong_moods) > 1 else None
        parts = [
            f"En iyi mood: {best['mood']} (avg {int(best['avg_views'])} view)"
        ]
        if worst and worst["mood"] != best["mood"] and worst["avg_views"] < best["avg_views"] / 2:
            parts.append(f"kaçın: {worst['mood']} (avg {int(worst['avg_views'])})")
        lines.append("- " + ", ".join(parts))

    # Watch-pct leaders — concrete examples of what worked
    leaders = insights.get("watch_pct_leaders", [])[:3]
    if leaders:
        lines.append("- İzleyici tekrar oynatan başlık örnekleri (watch%>100):")
        for l in leaders:
            lines.append(f"  · \"{l['title'][:70]}\" ({int(l['watch_pct'])}% watch)")

    lines.append(
        "Yukarıdaki kalıplara uyan haberleri 1-2 puan yukarı çekebilirsin; "
        "ama gerçekten alakasız haberi sırf 'pattern uyar' diye yükseltme."
    )
    return "\n".join(lines)
