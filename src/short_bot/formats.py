"""Kanal formatı — TEK yerde karar.

Panel (liste rozeti, düzenle bağlantısı), voiced.py (anlatım yazarı seçimi) ve
pipeline aynı soruyu soruyor: "bu kanal hangi formatta üretiyor?" Her biri kendi
if-zincirini kursaydı, bir alan eklenince (örn. content_source=trends + voice)
biri güncellenir diğeri unutulurdu.

Formatlar:
- card    : 6 sn haber kartı (rss/feed/trends, sessiz)
- voiced  : kart + seslendirme (Aslan Gündem+, Latido Blanco)
- yorum   : Google Trends + seslendirme = Gündem Yorum (ayrı UI kurulumu)
- reel    : footage-sürüklü reel
- curated : Reddit kürate klip
"""
from __future__ import annotations

FORMAT_LABELS: dict[str, str] = {
    "card": "Kart",
    "voiced": "Sesli",
    "yorum": "Gündem Yorum",
    "reel": "Reel",
    "curated": "Kürate",
}

# Kanal listesindeki "Düzenle" bağlantısının yolu (slug'dan sonraki parça).
FORMAT_EDIT_SUFFIX: dict[str, str] = {
    "card": "edit",
    "voiced": "edit",
    "yorum": "edit-yorum",
    "reel": "edit-reel",
    "curated": "edit-curated",
}


def channel_format(cfg) -> str:
    if getattr(cfg, "content_source", "rss") == "curated":
        return "curated"
    reel = getattr(cfg, "reel", None)
    if reel is not None and getattr(reel, "enabled", False):
        return "reel"
    voice = getattr(cfg, "voice", None)
    if voice is not None and getattr(voice, "enabled", False):
        if getattr(cfg, "content_source", "rss") == "trends":
            return "yorum"
        return "voiced"
    return "card"


def edit_path(cfg) -> str:
    return f"/channels/{cfg.slug}/{FORMAT_EDIT_SUFFIX[channel_format(cfg)]}"
