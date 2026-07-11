"""Reel overlay için okunur renk türetme (saf, bağımsız)."""
from __future__ import annotations


def _parse(hex_str: str) -> tuple[int, int, int] | None:
    s = (hex_str or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return None


def _to_hex(r: int, g: int, b: int) -> str:
    return "#%02x%02x%02x" % (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def luminance(hex_str: str) -> float:
    """WCAG bağıl parlaklık (0=siyah, 1=beyaz). Geçersiz → 0.0."""
    rgb = _parse(hex_str)
    if rgb is None:
        return 0.0

    def _lin(c: int) -> float:
        x = c / 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = (_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_text(bg_hex: str) -> str:
    """Zemine göre en okunur yazı rengi (beyaz vs koyu) — WCAG kontrast oranıyla.

    Sabit luminans eşiği yerine, beyaz ve koyu (#111) yazının gerçek kontrast
    oranını karşılaştırıp yükseğini seçer. Kesişim ~0.19 luminans; böylece
    orta-ton accent'lerde (ör. teal #14b8a6) koyu yazı doğru seçilir.
    """
    lum = luminance(bg_hex)
    dark_lum = luminance("#111111")
    white_ratio = (1.0 + 0.05) / (lum + 0.05)
    dark_ratio = (lum + 0.05) / (dark_lum + 0.05)
    return "#ffffff" if white_ratio >= dark_ratio else "#111111"


def ensure_bright(hex_str: str, keep_lum: float = 0.4, target_lum: float = 0.55) -> str:
    """Renk yeterince parlaksa (keep_lum) aynen döndür; koyuysa target_lum'a
    kadar beyaza doğru aydınlat. Parlak marka renkleri korunur, koyu renkler
    okunur hale gelir."""
    rgb = _parse(hex_str)
    if rgb is None:
        return "#ffd400"
    if luminance(hex_str) >= keep_lum:
        return _to_hex(*rgb)
    r, g, b = rgb
    for _ in range(12):
        r = int(r + (255 - r) * 0.25)
        g = int(g + (255 - g) * 0.25)
        b = int(b + (255 - b) * 0.25)
        if luminance(_to_hex(r, g, b)) >= target_lum:
            break
    return _to_hex(r, g, b)
