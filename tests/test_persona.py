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
    assert "Aşık Kargayi" in p.few_shot   # ozan imzası — marka öğesi
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
    assert "Aşık Kargayi" in blok            # few-shot örneği
    assert "BÜRÜNDÜR" in blok                # kurallar
    assert "GERÇEK" in blok


def test_signature_style_seed_ile_doner():
    # İmza kalır ama STİL DÖNER (her video aynı ozan kalıbı = formül). seed%3.
    from short_bot.persona import signature_style, SIGNATURE_STYLES
    assert len(SIGNATURE_STYLES) == 3
    etiketler = {signature_style(s)[0] for s in range(3)}
    assert len(etiketler) == 3                        # 3 FARKLI stil
    assert signature_style(3) == signature_style(0)   # döngüsel (deterministik)
    assert signature_style(4) == signature_style(1)
    assert signature_style(0)[0] == "OZAN İMZASI"     # varsayılan = eski davranış


def test_persona_block_imza_stili_seed_ile_degisir():
    from short_bot.persona import load_persona, persona_block, signature_style
    p = load_persona("vahsi_mizah", language="tr")
    # Seçilen stilin etiketi bloğa GERÇEKTEN enjekte edilmeli (stil dönüyor)
    for seed in range(3):
        etiket, _ = signature_style(seed)
        assert etiket in persona_block(p, seed=seed)
    # Ozan-DIŞI stillerde 'Aşık ... der ki' kalıbını KULLANMA talimatı olmalı
    for seed in [s for s in range(3) if signature_style(s)[0] != "OZAN İMZASI"]:
        assert "KULLANMA" in persona_block(p, seed=seed)
    # seed=0 (varsayılan) ozan → 'Aşık' geçer (geriye uyum)
    assert "Aşık" in persona_block(p, seed=0)
