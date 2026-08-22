"""Reel senaryo prompt'unun HEDEF DİLİ — sessiz Türkçeye düşüş yasak.

GERÇEK TEHLİKE (2026-07-24, Japonca kanal kurulurken yakalandı): tablo eksik olduğunda
``_language_name`` sessizce "Turkish" döndürüyordu. Yani Japonca kanal kurulsa, ses
Japonca, font Japonca, altyazı Japonca hazır olsa bile ANLATICI TÜRKÇE YAZARDI — ve
bunu hiçbir hata bildirmezdi. Kanal çalışıyor görünür, çıktı çöp olur.
"""
import pytest

from short_bot.locale import SUPPORTED_LANGUAGES
from short_bot.reel_narration import _language_name


def test_japanese_is_named_japanese():
    assert _language_name("ja") == "Japanese"


def test_every_supported_language_has_a_prompt_name():
    """Yeni dil eklenip burası unutulursa o kanal Türkçe yazar — testle bağla."""
    for lang in SUPPORTED_LANGUAGES:
        assert _language_name(lang) not in ("", None)


def test_supported_languages_do_not_collapse_to_turkish():
    names = {lang: _language_name(lang) for lang in SUPPORTED_LANGUAGES}
    turkish = [lang for lang, n in names.items() if n == "Turkish"]
    assert turkish == ["tr"], f"Türkçeye düşen diller: {turkish} ({names})"


def test_unknown_language_raises_instead_of_falling_back():
    with pytest.raises(ValueError):
        _language_name("xx")
