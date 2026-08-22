from short_bot.prompt_phrases import GENERATOR_PHRASES, get_phrases


def test_all_5_languages_present():
    assert set(GENERATOR_PHRASES) == {"tr", "en", "de", "es", "fr"}


def test_each_language_has_required_keys():
    required = {"channel_id", "topic", "language_label", "language_name", "task",
                "forbidden_intro", "forbidden_end", "topic_rotation",
                "output_intro", "critical", "marker_unused", "marker_low"}
    for lang, phrases in GENERATOR_PHRASES.items():
        missing = required - set(phrases)
        assert not missing, f"{lang} missing: {missing}"


def test_get_phrases_falls_back_to_tr_for_unknown():
    p = get_phrases("zz")
    assert p == GENERATOR_PHRASES["tr"]


def test_language_name_is_correct():
    assert GENERATOR_PHRASES["tr"]["language_name"] == "Türkçe"
    assert GENERATOR_PHRASES["en"]["language_name"] == "English"
    assert GENERATOR_PHRASES["de"]["language_name"] == "Deutsch"
