"""İngilizce paket — elle yazıldı, LLM üretmedi (bildiğimiz dil).

DİKKAT: find_overused metni normalleştirirken noktalamayı boşluğa çeviriyor
(reel_phrases._norm), yani "what's up" → "what s up". Kalıplar buna göre yazılmalı.
meta_tail_pattern ise HAM metne uygulanıyor (clean_open_loop), noktalama duruyor.
"""
from short_bot.lang_pack import CTA_MAX_CHARS, load_pack, validate_pack

EN = load_pack("en")


def test_gecerli():
    assert validate_pack(EN) == []


def test_CTA_24_karaktere_sigar():
    for c in EN.cta_texts:
        assert len(c) <= CTA_MAX_CHARS, f"{len(c)}: {c!r}"
    render = EN.trade_cta.format(no=48)
    assert len(render) <= CTA_MAX_CHARS, f"{len(render)}: {render!r}"


def test_TURKCE_sizintisi_YOK():
    ham = EN.model_dump_json()
    for tr in ["ABONE OL", "BÖLÜM", "bölüm", "yarın"]:
        assert tr not in ham, f"Türkçe sızıntı: {tr!r}"


def test_trade_cta():
    from short_bot.reel_series import trade_cta
    assert trade_cta(48, pack=EN) == "#48 tomorrow — SUB"


def test_rozet_NOKTASIZ_I():
    """turkish_upper 'Big History' → 'BİG HİSTORY' yapardı."""
    from short_bot.reel_series import episode_badge
    assert episode_badge("Big History", 47, pack=EN) == "BIG HISTORY #47"


def test_ingilizce_KLISE_yakalanir():
    from short_bot.reel_phrases import find_overused
    assert find_overused("Did you know that octopuses have three hearts?", pack=EN)
    assert find_overused("Hey guys, today I'm going to show you something", pack=EN)
    assert find_overused("Wait for it. The ending is wild.", pack=EN)


def test_temiz_metin_GECER():
    from short_bot.reel_phrases import find_overused
    assert find_overused("An octopus has three hearts and blue blood.", pack=EN) == []


def test_meta_dili_SOKULUR():
    """İngilizce'de fiil önce ('I'll explain in episode 48'), Türkçe'de sonra."""
    from short_bot.reel_series import clean_open_loop
    ham = "The symbiotic bacterium I'll explain in episode 48."
    assert clean_open_loop(ham, pack=EN) == "The symbiotic bacterium"


def test_meta_OLMAYAN_metin_BOZULMAZ():
    from short_bot.reel_series import clean_open_loop
    temiz = "The symbiotic bacterium that produces the light"
    assert clean_open_loop(temiz, pack=EN) == temiz
