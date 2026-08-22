import pytest

from short_bot.locale import (
    RSS_LOCALES, LANGUAGE_NAMES, UI_LABELS, SUPPORTED_LANGUAGES,
    rss_locale_for, ui_labels_for, language_name,
)


def test_supported_languages_set():
    assert SUPPORTED_LANGUAGES == ["tr", "en", "de", "es", "fr", "ja"]


def test_every_language_has_an_alphabet_entry():
    """Alfabe tablosu eksikse aksan sökücüsü SESSİZCE Türkçeye düşer."""
    from short_bot.locale import ALPHABET_EXTRA
    for lang in SUPPORTED_LANGUAGES:
        assert lang in ALPHABET_EXTRA


def test_rss_locales_cover_all_languages():
    for lang in SUPPORTED_LANGUAGES:
        assert lang in RSS_LOCALES
        loc = RSS_LOCALES[lang]
        assert "hl=" in loc and "ceid=" in loc


def test_ui_labels_cover_all_languages_with_5_keys():
    # like/subscribe/share KALDIRILDI (2026-07-16, kullanıcı kararı)
    expected_keys = {"breaking", "source"}
    for lang in SUPPORTED_LANGUAGES:
        assert lang in UI_LABELS
        assert set(UI_LABELS[lang].keys()) == expected_keys


def test_language_names_cover_all_languages():
    for lang in SUPPORTED_LANGUAGES:
        assert lang in LANGUAGE_NAMES
        assert len(LANGUAGE_NAMES[lang]) >= 2


def test_rss_locale_for_helper():
    assert rss_locale_for("tr") == RSS_LOCALES["tr"]
    with pytest.raises(KeyError):
        rss_locale_for("xx")


def test_ui_labels_for_helper():
    labels = ui_labels_for("de")
    assert labels["breaking"] == "EILMELDUNG"


def test_language_name_helper():
    assert language_name("fr") == "Français"
