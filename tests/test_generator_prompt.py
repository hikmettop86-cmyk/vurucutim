# tests/test_generator_prompt.py
from short_bot.config import ChannelConfig, GeneratorConfig
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec
from short_bot.generator import build_generator_prompt


def _channel(language="tr"):
    return ChannelConfig(
        slug="sevgi", name="Sevgi", keywords=[], rss_locale="",
        schedule_cron="0 9 * * *", duration_s=7, min_score=0.0,
        max_candidates_per_run=1, template="stat-hero",
        colors={"primary": "#000", "accent": "#fff", "bg_gradient": ["#000", "#111"]},
        handle="@sevgi", output_dir="output/sevgi", enabled=True,
        language=language, dna=None, script_model="sonnet",
        content_source="generator",
        generator=GeneratorConfig(
            topic="Sevgi ve aşk üzerine kısa, vurucu sözler",
        ),
    )


def _dna():
    return DnaSpec(
        archetype="stat-hero",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(headline="Anton", body="Inter"),
        tone=DnaTone(voice="duygusal, samimi", style="kısa, vurucu",
                     forbidden=["klişe", "siyaset"], sentence_max_words=14,
                     body_max_chars=300, headline_style_hint="iki satır, büyük harf"),
        category_icon="❤️",
        persona_summary="Sevgi sözleri kanalı.",
    )


def test_includes_channel_topic():
    p = build_generator_prompt(channel=_channel(), dna=_dna(),
                                forbidden_texts=[], topic_distribution={})
    assert "Sevgi ve aşk üzerine kısa, vurucu sözler" in p


def test_includes_forbidden_list():
    p = build_generator_prompt(channel=_channel(), dna=_dna(),
                                forbidden_texts=["Aşk sabırla başlar.",
                                                  "Sevgi her şeydir."],
                                topic_distribution={})
    assert "Aşk sabırla başlar." in p
    assert "Sevgi her şeydir." in p
    assert "ASLA" in p  # forbidden_intro Turkish


def test_includes_topic_distribution_with_marks():
    p = build_generator_prompt(channel=_channel(), dna=_dna(),
                                forbidden_texts=[],
                                topic_distribution={"tanisma": 12, "ozlem": 0,
                                                     "sabir": 8})
    assert "tanisma: 12" in p
    assert "ozlem: 0" in p
    assert "sabir: 8" in p


def test_includes_dna_tone():
    p = build_generator_prompt(channel=_channel(), dna=_dna(),
                                forbidden_texts=[], topic_distribution={})
    assert "duygusal, samimi" in p     # voice
    assert "kısa, vurucu" in p          # style
    assert "klişe" in p                  # forbidden tone
    assert "300" in p                    # body_max_chars


def test_uses_english_phrases_for_en_channel():
    p = build_generator_prompt(channel=_channel(language="en"), dna=_dna(),
                                forbidden_texts=[], topic_distribution={})
    assert "DO NOT" in p              # forbidden_intro English
    assert "TASK" in p                 # task English
    assert "ASLA" not in p


def test_german_phrases_for_de():
    p = build_generator_prompt(channel=_channel(language="de"), dna=_dna(),
                                forbidden_texts=[], topic_distribution={})
    assert "AUFGABE" in p
    assert "Deutsch" in p
