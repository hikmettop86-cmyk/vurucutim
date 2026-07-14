"""Locale dictionaries: RSS URL hints + UI labels + prompt language names.

Multi-language support for short-bot. Each language maps to:
- An RSS URL fragment (hl/gl/ceid params for Google News)
- A human-readable language name (used in LLM prompts)
- A small UI vocabulary (BEĞEN/SUBSCRIBE/SHARE/BREAKING)
"""
from __future__ import annotations

SUPPORTED_LANGUAGES = ["tr", "en", "de", "es", "fr"]


RSS_LOCALES: dict[str, str] = {
    "tr": "hl=tr&gl=TR&ceid=TR:tr",
    "en": "hl=en-US&gl=US&ceid=US:en",
    "de": "hl=de&gl=DE&ceid=DE:de",
    "es": "hl=es&gl=ES&ceid=ES:es",
    "fr": "hl=fr&gl=FR&ceid=FR:fr",
}


LANGUAGE_NAMES: dict[str, str] = {
    "tr": "Türkçe",
    "en": "English",
    "de": "Deutsch",
    "es": "Español",
    "fr": "Français",
}


# ISO 3166-1 alpha-2 region codes for Google Trends / YouTube Trending.
# YouTube uses `regionCode`; Google Trends uses `geo` — both accept the same codes.
TREND_REGIONS: dict[str, str] = {
    "tr": "TR",
    "en": "US",
    "de": "DE",
    "es": "ES",
    "fr": "FR",
}


def trend_region_for(language: str) -> str:
    """Return the ISO region code used by Google Trends/YouTube Trending APIs."""
    return TREND_REGIONS[language]


UI_LABELS: dict[str, dict[str, str]] = {
    "tr": {"like": "BEĞEN",       "subscribe": "ABONE OL",   "share": "PAYLAŞ",   "breaking": "SON DAKİKA",     "source": "Kaynak"},
    "en": {"like": "LIKE",        "subscribe": "SUBSCRIBE",  "share": "SHARE",    "breaking": "BREAKING",        "source": "Source"},
    "de": {"like": "GEFÄLLT MIR", "subscribe": "ABONNIEREN", "share": "TEILEN",   "breaking": "EILMELDUNG",      "source": "Quelle"},
    "es": {"like": "ME GUSTA",    "subscribe": "SUSCRIBIRSE","share": "COMPARTIR","breaking": "ÚLTIMA HORA",     "source": "Fuente"},
    "fr": {"like": "J'AIME",      "subscribe": "S'ABONNER",  "share": "PARTAGER", "breaking": "DERNIÈRE MINUTE", "source": "Source"},
}


def rss_locale_for(language: str) -> str:
    """Return the Google News RSS URL fragment for `language`. Raises KeyError if unknown."""
    return RSS_LOCALES[language]


def ui_labels_for(language: str) -> dict[str, str]:
    """Return the UI label dict for `language`. Raises KeyError if unknown."""
    return UI_LABELS[language]


def language_name(language: str) -> str:
    """Return the human-readable language name (e.g. 'Türkçe' for 'tr'). Raises KeyError."""
    return LANGUAGE_NAMES[language]


# Dilin alfabesindeki ASCII-DIŞI harfler. Aksan temizleyicisi
# (text_normalize.strip_foreign_diacritics) bu tabloda OLMAYAN her aksanı söker.
#
# NEDEN OLGU TABLOSU, NEDEN DİL PAKETİNDE DEĞİL: alfabe bir olgudur, üslup değil.
# Dil paketini Sonnet üretiyor; 'ß'i unutursa Almanca anlatım metni SESSİZCE bozulur
# ("Weiß" → "Wei") ve bunu hiçbir hata bildirmez. Bu riski almanın karşılığı yok.
ALPHABET_EXTRA: dict[str, str] = {
    "tr": "ÇĞİıÖŞÜçğöşü",
    "en": "",
    "de": "ÄÖÜäöüß",
    "es": "ÑñÁÉÍÓÚÜáéíóúü¿¡",
    "fr": "ÀÂÆÇÉÈÊËÎÏÔŒÙÛÜŸàâæçéèêëîïôœùûüÿ",
}
