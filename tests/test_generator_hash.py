from short_bot.generated_db import text_hash, normalize_for_hash


def test_normalize_strips_punctuation_and_lowercases():
    assert normalize_for_hash("Aşk, sabırla başlar.") == "aşk sabırla başlar"
    assert normalize_for_hash("AŞK SABIRLA BAŞLAR") == "aşk sabırla başlar"
    assert normalize_for_hash("aşk   sabırla\tbaşlar") == "aşk sabırla başlar"


def test_text_hash_paraphrase_collision():
    """Verbatim text and lowercase-with-different-punct should match."""
    h1 = text_hash("Aşk, sabırla başlar.")
    h2 = text_hash("aşk sabırla başlar")
    h3 = text_hash("AŞK; SABIRLA BAŞLAR!")
    assert h1 == h2 == h3
    assert len(h1) == 64  # sha256 hex


def test_text_hash_distinguishes_different_meanings():
    h1 = text_hash("Aşk sabırla başlar.")
    h2 = text_hash("Aşk hızla biter.")
    assert h1 != h2
