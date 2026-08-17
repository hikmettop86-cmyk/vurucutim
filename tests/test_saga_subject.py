"""Saga sınırı: özne anahtarının biçimi ve eşleşme kuralı."""
from __future__ import annotations

from short_bot.topic_taxonomy import normalize_subject, subject_matches


def test_normalize_folds_turkish_dotted_i():
    """"İ".lower() görünmez birleşik nokta üretir; iki ayrı kovaya bölerdi."""
    assert normalize_subject("İCARDİ") == "icardi"


def test_normalize_does_not_apply_turkish_i_rule():
    """Kanallar çok dilli: "I"→"ı" İspanyolca özneleri bozardı."""
    assert normalize_subject("INTER") == "inter"


def test_normalize_collapses_whitespace():
    assert normalize_subject("  aleksey   batrakov ") == "aleksey batrakov"


def test_normalize_empty_returns_empty_not_placeholder():
    """Bilinmeyen özne 'sayma' demek; kategorideki '?' kovası burada YANLIŞ."""
    assert normalize_subject("") == ""
    assert normalize_subject(None) == ""


def test_matches_identical():
    assert subject_matches("batrakov", "batrakov") is True


def test_matches_short_key_inside_longer_one():
    """LLM bir gün soyadı, ertesi gün tam ad yazarsa sayaç bölünmemeli."""
    assert subject_matches("batrakov", "aleksey batrakov") is True
    assert subject_matches("aleksey batrakov", "batrakov") is True


def test_does_not_match_mere_substring_of_a_word():
    """'sara' ile 'sarabia' AYRI kişi — harf içermesi yetmez, kelime olmalı."""
    assert subject_matches("sara", "sarabia") is False


def test_does_not_match_on_short_tokens():
    """2-3 harflik anahtar rastgele eşleşme üretir."""
    assert subject_matches("ns", "ns transfer") is False


def test_empty_never_matches():
    assert subject_matches("", "batrakov") is False
    assert subject_matches("batrakov", "") is False


def test_disjoint_subjects_do_not_match():
    assert subject_matches("leao", "osimhen") is False


def test_matches_same_words_in_different_order():
    """Aynı özne iki kovaya bölünmemeli; sıra farkı anlam farkı değil."""
    assert subject_matches("real madrid", "madrid real") is True


def test_normalize_strips_turkish_possessive_suffix():
    """Kesmeden sonrası ektir; "batrakov'un" ile "batrakov" aynı öznedir."""
    assert normalize_subject("Batrakov'un") == "batrakov"
    assert normalize_subject("Galatasaray'ın") == "galatasaray"


def test_normalize_strips_typographic_apostrophe_too():
    """LLM düz kesme yerine tipografik kesme yazabilir."""
    assert normalize_subject("Leao’ya") == "leao"


def test_normalize_keeps_apostrophe_that_belongs_to_the_name():
    """"O'Brien"de kesme ek ayırıcı değil; gövde 3 harften kısaysa kesme."""
    assert normalize_subject("O'Brien") == "obrien"


def test_normalize_treats_hyphen_as_word_separator():
    assert normalize_subject("Jean-Claude") == "jean claude"


def test_suffixed_and_bare_forms_match():
    """Asıl kazanım: iki biçim aynı sagaya sayılmalı."""
    assert subject_matches(normalize_subject("Batrakov'un"),
                           normalize_subject("Batrakov")) is True


def test_min_token_boundary_rejects_three_chars():
    """_SUBJECT_MIN_TOKEN sınırı: 3 harf reddedilir, 4 harf kabul edilir."""
    assert subject_matches("leo", "leo messi") is False
    assert subject_matches("leao", "sporting leao") is True
