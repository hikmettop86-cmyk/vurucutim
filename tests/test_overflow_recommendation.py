"""Unit tests for _compute_recommended_chars — the overflow recommendation
algorithm. Lives in Python (not JS) so we can test without Playwright."""
from short_bot.overflow import _compute_recommended_chars


def test_no_overflow_returns_current():
    assert _compute_recommended_chars(
        current_chars=20, current_lines=2, max_lines=4, has_overflow=False
    ) == 20


def test_zero_lines_returns_current():
    """Defensive: division-by-zero guard."""
    assert _compute_recommended_chars(
        current_chars=20, current_lines=0, max_lines=4, has_overflow=True
    ) == 20


def test_vertical_overflow_recommends_proportionally_less():
    """Classic case: current 4 lines, max 2 → recommend ~half."""
    rec = _compute_recommended_chars(
        current_chars=40, current_lines=4, max_lines=2, has_overflow=True
    )
    # target = floor(40 * 2 * 0.9 / 4) = 18
    assert rec == 18
    assert rec < 40


def test_horizontal_overflow_caps_below_current():
    """Horizontal overflow regression: stadium header_top reported
    current=20 chars, current_lines=2, max_lines=4 — old JS computed
    target=36 (>current), LLM had no incentive to shorten. Fix: cap
    at current-1 so recommendation is always strictly less when overflow."""
    rec = _compute_recommended_chars(
        current_chars=20, current_lines=2, max_lines=4, has_overflow=True
    )
    assert rec < 20, f"recommended={rec} must be < current=20 when overflow"
    assert rec >= 1


def test_overflow_floor_at_one():
    """Pathological: tiny current, can't go below 1."""
    rec = _compute_recommended_chars(
        current_chars=2, current_lines=10, max_lines=1, has_overflow=True
    )
    assert rec == 1


def test_recommendation_strictly_less_when_overflow():
    """Invariant: when overflow=True, recommendation < current_chars."""
    for cur_chars in [5, 20, 50, 100]:
        for cur_lines in [1, 2, 5, 10]:
            for max_lines in [1, 2, 4, 10]:
                rec = _compute_recommended_chars(
                    current_chars=cur_chars, current_lines=cur_lines,
                    max_lines=max_lines, has_overflow=True
                )
                if cur_chars > 1:
                    assert rec < cur_chars, (
                        f"rec={rec} not < cur={cur_chars} "
                        f"(lines={cur_lines}, max={max_lines})"
                    )
                assert rec >= 1


def test_horizontal_overflow_shrinks_meaningfully_not_by_one_char():
    """current-1 adımı 3 retry'lık bütçeyi tüketiyor, sonra truncate ediliyor.

    Gerçek koşu (run 1611, stadium header_top): 16->15 -> LLM 14 yazdı ->
    14->13 -> 13->12 -> "all retries failed -> truncate_to_fit". Yatay
    taşmada oransal formül current'in ÜSTÜNE çıkıyor, cap=current-1 devreye
    giriyor ve her tur yalnız 1 karakter kırpılıyor. Kanalın manşetlerinin
    %59'u bu yüzden kesik ("SOYUNMA…", "GERİ…").
    """
    rec = _compute_recommended_chars(
        current_chars=16, current_lines=3, max_lines=4, has_overflow=True
    )
    assert rec <= 14, f"recommended={rec}: 16 karakterden en az 2 kırpılmalı"
    assert rec >= 1


def test_horizontal_shrink_is_proportional_for_long_headlines():
    """Uzun manşette 1 karakterlik adım daha da yetersiz."""
    rec = _compute_recommended_chars(
        current_chars=40, current_lines=1, max_lines=4, has_overflow=True
    )
    assert rec <= 34, f"recommended={rec}: 40 karakterde ~%15 kırpma beklenir"
