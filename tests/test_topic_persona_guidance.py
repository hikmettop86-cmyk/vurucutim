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


def test_director_guidance_vahsi_mizah():
    from short_bot.persona import load_persona, director_guidance
    p = load_persona("vahsi_mizah", language="tr")
    g = director_guidance(p)
    assert "upbeat" in g and ("dark" in g or "gerilim" in g)   # eğlenceli, gerilim yasak


def test_director_guidance_personasiz_bos():
    from short_bot.persona import director_guidance
    assert director_guidance(None) == ""


def test_director_persona_hint_prompta_girer():
    from short_bot.reel_director import _prompt

    class _B:
        text = "beat"

    class _N:
        hook = "hook"; beats = [_B()]; close = "close"

    p = _prompt(_N(), "konu", 4, ["impact"], ["upbeat"], persona_hint="MİZAH KURGU REHBERİ")
    assert "MİZAH KURGU REHBERİ" in p
