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
