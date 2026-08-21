"""Trend dikeyleri — Google kategori kimliklerinin okunabilir kümeleri."""
from __future__ import annotations

import pytest


def test_para_dikeyi_is_finans_ve_alisverisi_kapsar():
    from short_bot.trends.verticals import categories_for
    assert categories_for("para") == frozenset({3, 16})


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
    assert categories_for("  Para  ") == frozenset({3, 16})


def test_her_dikeyin_etiketi_var():
    from short_bot.trends.verticals import VERTICAL_LABELS, VERTICALS
    assert set(VERTICALS) == set(VERTICAL_LABELS)


def test_her_kategori_kimliginin_adi_var():
    from short_bot.trends.verticals import CATEGORY_NAMES, VERTICALS
    for cats in VERTICALS.values():
        for c in cats:
            assert c in CATEGORY_NAMES
