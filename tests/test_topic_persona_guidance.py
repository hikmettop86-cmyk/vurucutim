"""Mizah personası için konu üretimi rehberi (extra_guidance)."""


def test_topic_guidance_vahsi_mizah():
    from short_bot.persona import load_persona, topic_guidance
    p = load_persona("vahsi_mizah", language="tr")
    g = topic_guidance(p)
    assert "KARAKTERLİ" in g or "KABADAYI" in g
    assert "KAÇIN" in g            # hüzünlü/nötr konulardan kaçınma yönergesi


def test_topic_guidance_personasiz_bos():
    from short_bot.persona import topic_guidance
    assert topic_guidance(None) == ""


def test_extra_guidance_prompta_girer():
    from short_bot.topic_propose import propose_topics
    yakalanan = {}

    class _P:
        topics = []

    def sahte_llm(prompt, schema):
        yakalanan["prompt"] = prompt
        return _P()

    propose_topics("hayvan nişi", language="tr", evidence=[], existing=[],
                   count=5, llm=sahte_llm, extra_guidance="MİZAH REHBERİ BURADA")
    assert "MİZAH REHBERİ BURADA" in yakalanan["prompt"]


def test_extra_guidance_bos_promptu_kirletmez():
    from short_bot.topic_propose import propose_topics
    yakalanan = {}

    class _P:
        topics = []

    def sahte_llm(prompt, schema):
        yakalanan["prompt"] = prompt
        return _P()

    propose_topics("hayvan nişi", language="tr", evidence=[], existing=[],
                   count=5, llm=sahte_llm)   # extra_guidance yok
    assert "MİZAH" not in yakalanan["prompt"]
