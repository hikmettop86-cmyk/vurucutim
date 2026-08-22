from short_bot.text_normalize import strip_non_turkish_diacritics


def test_strips_spanish_acute_on_capital_i():
    assert strip_non_turkish_diacritics("CANLÍ") == "CANLI"


def test_keeps_turkish_capital_dotted_i():
    assert strip_non_turkish_diacritics("İPLER KOPTU") == "İPLER KOPTU"


def test_keeps_turkish_lowercase_dotless_i():
    assert strip_non_turkish_diacritics("ışık") == "ışık"


def test_keeps_turkish_c_g_o_s_u_letters():
    s = "Çocuklar Ğemi Öğretmen Şahan Üzüm çay ğ ö ş ü"
    assert strip_non_turkish_diacritics(s) == s


def test_strips_spanish_tilde_n():
    assert strip_non_turkish_diacritics("Niño") == "Nino"


def test_strips_french_circumflex():
    assert strip_non_turkish_diacritics("Hôtel café") == "Hotel cafe"


def test_strips_acute_on_vowels():
    assert strip_non_turkish_diacritics("ÁÉÍÓÚ áéíóú") == "AEIOU aeiou"


def test_passes_pure_ascii_unchanged():
    assert strip_non_turkish_diacritics("Hello, World!") == "Hello, World!"


def test_handles_empty_string():
    assert strip_non_turkish_diacritics("") == ""


def test_full_headline_mixed():
    # Real bug case: Turkish text with one Spanish accent leak
    assert strip_non_turkish_diacritics("İPLER KOPTU CANLÍ YAYINDA") == \
           "İPLER KOPTU CANLI YAYINDA"


# ---------------------------------------------------------------- CJK (2026-07-24)
#
# ÖLÇÜLDÜ: NFKD Japonca dakuten'i AYRI bir birleşen işarete ayırıyor (が = か +
# U+3099) ve unicodedata.combining() onu 1 sayıyor → söküyoruz. Sonuç kelimeyi
# yok ediyor: 犬が (köpek-ÖZNE) → 犬か (köpek-mi?), ヤバい → ヤハい (kelime değil).
# Bu fonksiyon bir pydantic field_validator, yani anlatımın HER cümlesinde koşuyor.
#
# Bu bir "yabancı aksan" DEĞİL: dakuten Japon alfabesinin parçası, tıpkı Almanca
# 'ä' gibi. Ama 'ä'yi ALPHABET_EXTRA'ya yazabiliyoruz, 50.000 kanji'yi yazamayız —
# bu yüzden kural blok tabanlı: CJK'ye hiç dokunma.

def test_keeps_japanese_dakuten():
    """が→か bir anlam kaymasıdır; sessizce olursa Japonca kanal çöp üretir."""
    assert strip_non_turkish_diacritics("この犬が飼い主を助けた") == "この犬が飼い主を助けた"


def test_keeps_japanese_handakuten_and_katakana():
    assert strip_non_turkish_diacritics("ぱんだ ガチでヤバい") == "ぱんだ ガチでヤバい"


def test_keeps_japanese_punctuation_and_fullwidth():
    assert strip_non_turkish_diacritics("すごい！　１２３。") == "すごい！　１２３。"


def test_cjk_passthrough_does_not_leak_into_latin():
    """CJK muafiyeti Latin aksanını kurtarmasın — karışık cümlede ikisi de doğru."""
    assert strip_non_turkish_diacritics("東京の CANLÍ 映像") == "東京の CANLI 映像"
