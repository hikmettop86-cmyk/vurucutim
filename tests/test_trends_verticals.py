"""Trend dikeyleri — Google kategori kimliklerinin okunabilir kümeleri."""
from __future__ import annotations

import pytest


def test_para_dikeyi_yalniz_is_finans():
    """Alışveriş(16) BİLEREK dışarıda: canlı TR kuyruğunda kattığı tek haber
    'erkek el çantaları' modasıydı; gerçek para haberleri hep kategori 3."""
    from short_bot.trends.verticals import categories_for
    assert categories_for("para") == frozenset({3})


def test_alisveris_hicbir_dikeyde_yok():
    from short_bot.trends.verticals import VERTICALS
    assert not any(16 in cats for cats in VERTICALS.values())


def test_siyaset_hicbir_dikeyde_yok():
    from short_bot.trends.verticals import VERTICALS
    assert not any(14 in cats for cats in VERTICALS.values())


def test_spor_dikeyi_tek_kategori():
    from short_bot.trends.verticals import categories_for
    assert categories_for("spor") == frozenset({17})


def test_dikeysiz_kanal_sinirsiz():
    from short_bot.trends.verticals import categories_for, matches
    assert categories_for(None) is None
    assert matches((17,), None) is True
    assert matches((), None) is True


def test_coklu_kategoride_herhangi_biri_yeter():
    # 'sucuk' gerçek veride [3, 5] etiketli (İş&Finans + Yeme-İçme).
    # Tek-kategori kuralı olsaydı para dikeyinden düşerdi.
    from short_bot.trends.verticals import matches
    assert matches((3, 5), "para") is True


def test_eslesmeyen_trend_elenir():
    from short_bot.trends.verticals import matches
    assert matches((17,), "para") is False


def test_kategorisiz_trend_dikeyde_kalamaz():
    # RSS yedeğinden gelen haberde kategori YOK; dikey kanalda kullanılamaz.
    from short_bot.trends.verticals import matches
    assert matches((), "para") is False


def test_bilinmeyen_dikey_hata_verir():
    from short_bot.trends.verticals import categories_for
    with pytest.raises(KeyError):
        categories_for("futbol")


def test_buyuk_harf_ve_bosluk_tolere_edilir():
    from short_bot.trends.verticals import categories_for
    assert categories_for("  Para  ") == frozenset({3})


def test_her_dikeyin_etiketi_var():
    from short_bot.trends.verticals import VERTICAL_LABELS, VERTICALS
    assert set(VERTICALS) == set(VERTICAL_LABELS)


def test_her_kategori_kimliginin_adi_var():
    from short_bot.trends.verticals import CATEGORY_NAMES, VERTICALS
    for cats in VERTICALS.values():
        for c in cats:
            assert c in CATEGORY_NAMES


# --- çift etiketli trendler ---------------------------------------------------

def test_birincil_kategorisi_baska_dikeye_ait_olan_girmez():
    """CANLI VAKA (2026-08-22): MLB beyzbol haberi (17=Spor, 4=Eğlence) magazin
    kuyruğuna girdi ve video üretildi. Japonca havuzda 47 magazin adayının 9'u
    böyle çift etiketliydi.

    Kural: herhangi bir kategori tutuyorsa gir — AMA birincil kategori BAŞKA
    bir adlandırılmış dikeye aitse girme. Google birincil kategoriyi başa
    koyuyor."""
    from short_bot.trends.verticals import matches
    assert matches((17, 4), "magazin") is False   # birincil=Spor
    assert matches((17, 4), "spor") is True


def test_sucuk_vakasi_hala_korunur():
    """(3, 5) = İş&Finans + Yeme-İçme. Birincil kategori PARA dikeyinin kendisi,
    ikincil kategori hiçbir dikeye ait değil -> para dikeyinde KALIR."""
    from short_bot.trends.verticals import matches
    assert matches((3, 5), "para") is True


def test_birincil_kategorisi_dikeysiz_olan_ikincilden_girer():
    """(16, 2) = Alışveriş + Güzellik&Moda. 16 hiçbir dikeyde yok, 2 magazinde
    -> magazine girer."""
    from short_bot.trends.verticals import matches
    assert matches((16, 2), "magazin") is True


def test_tek_kategorili_davranis_degismedi():
    from short_bot.trends.verticals import matches
    assert matches((4,), "magazin") is True
    assert matches((17,), "magazin") is False
