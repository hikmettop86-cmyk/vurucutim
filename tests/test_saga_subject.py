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
