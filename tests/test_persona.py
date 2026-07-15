"""Reel anlatım personası: yükleme + prompt bloğu."""
import pytest


def test_bos_slug_none():
    from short_bot.persona import load_persona
    assert load_persona("", language="tr") is None


def test_vahsi_mizah_yuklenir():
    from short_bot.persona import load_persona
    p = load_persona("vahsi_mizah", language="tr")
    assert p is not None
    assert p.slug == "vahsi_mizah"
    assert "Porsuk Dumrul" in p.few_shot
    assert len(p.rules) >= 5
    assert p.humor_check is True


def test_bilinmeyen_slug_raise():
    from short_bot.persona import load_persona
    with pytest.raises(RuntimeError, match="persona"):
        load_persona("boyle_bir_persona_yok", language="tr")


def test_yanlis_dilde_raise():
    # Türk dizisi referansları yalnız tr'de. Almanca'da vahsi_mizah RuntimeError.
    from short_bot.persona import load_persona
    with pytest.raises(RuntimeError, match="persona"):
        load_persona("vahsi_mizah", language="de")


def test_persona_block_few_shot_ve_kurallari_icerir():
    from short_bot.persona import load_persona, persona_block
    p = load_persona("vahsi_mizah", language="tr")
    blok = persona_block(p)
    assert "Porsuk Dumrul" in blok
    assert "KARAKTERE BÜRÜNDÜR" in blok
    assert "GERÇEK" in blok
