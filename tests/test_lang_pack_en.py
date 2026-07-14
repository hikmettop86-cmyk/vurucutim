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
    assert EN.trade_cta.format(no=48) == "#48 tomorrow — SUB"
