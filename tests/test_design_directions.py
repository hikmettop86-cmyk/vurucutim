"""Tasarım dili kütüphanesi — VoltAgent/awesome-design-md uyarlayıcısı.

KULLANICI İSTEĞİ (2026-08-21): "yaratıcı bir modül lazım, düz html css ile
olmuyorsa githubtan bak" + "şablonlar birbirine benzemesin".

Eskiden prompt iki ESKİ ŞABLONU örnek veriyordu ("yapıyı bunlardan al") —
model onlara demir atıyor ve çıktı hep aynı kalıba benziyordu. Artık her adaya
FARKLI bir tasarım dili veriliyor.

ÖLÇÜLDÜ: dosyaların ~%26'sı buton/input/responsive (bizim tuvalimiz sabit
1080×1920 dikey kart, web sayfası değil) ve tipografi ölçüleri web boyutunda
(Wired hero manşeti 64px, bizimki 96-132px).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from short_bot.design_directions import (ANKARALAR, Yon, prompt_blogu, sec,
                                         yonler, yukle)

DIZIN = Path("templates/design")


@pytest.fixture(autouse=True)
def _dizin_var():
    if not DIZIN.exists():
        pytest.skip("templates/design takipsiz olabilir")


def test_diller_bulunur():
    ad = yonler(DIZIN)
    assert len(ad) >= 8, ad
    assert "wired" in ad and "nike" in ad
    assert "LICENSE-VoltAgent" not in ad, "lisans notu dil sanılıyor"


def test_yukle_ozet_ve_metin_verir():
    y = yukle(DIZIN, "wired")
    assert isinstance(y, Yon)
    assert y.ad == "wired" and y.etiket
    assert "editorial" in y.ozet.lower() or "magazine" in y.ozet.lower()
    assert len(y.metin) > 2000


def test_BIZE_UYMAYAN_bolumler_AYIKLANIR():
    """Buton/input/form ve responsive breakpoint prompt'u şişirip yanlış
    yönlendirir: bizim çıktımızda buton yok, tek bir sabit tuval var."""
    y = yukle(DIZIN, "wired")
    ham = (DIZIN / "wired.md").read_text(encoding="utf-8")
    assert "## Components" in ham, "kaynak dosya değişmiş"
    assert "## Components" not in y.metin
    assert "Responsive" not in y.metin
    assert len(y.metin) < len(ham), "hiçbir şey ayıklanmamış"


def test_ISE_YARAYAN_bolumler_KALIR():
    y = yukle(DIZIN, "wired")
    for bolum in ("Colors", "Typography", "Layout"):
        assert bolum in y.metin, bolum


def test_TUVAL_CAPALARI_prompta_girer():
    """Web ölçekli merdiveni bizim tuvalimize oturtacak mutlak çapalar."""
    y = yukle(DIZIN, "wired")
    assert "1080" in y.metin and "1920" in y.metin
    for anahtar in ANKARALAR:
        assert anahtar in y.metin, anahtar


def test_sec_FARKLI_diller_dondurur():
    a = sec(DIZIN, 3, tohum="besiktas")
    assert len(a) == 3 and len(set(a)) == 3


def test_sec_TOHUM_ayni_ise_ayni_sonuc():
    assert sec(DIZIN, 3, tohum="x") == sec(DIZIN, 3, tohum="x")


def test_sec_TOHUM_farkli_ise_genelde_farkli():
    """Her kanal aynı üç dili almamalı."""
    kumeler = {tuple(sec(DIZIN, 3, tohum=f"kanal{i}")) for i in range(12)}
    assert len(kumeler) >= 5, kumeler


def test_sec_ISTENEN_SAYIDAN_az_dil_varsa_patlamaz(tmp_path):
    (tmp_path / "a.md").write_text("---\ndescription: x\n---\n## Colors\nx\n",
                                   encoding="utf-8")
    assert sec(tmp_path, 3, tohum="t") == ["a"]


def test_prompt_blogu_DILI_ve_NIYETI_birlestirir():
    b = prompt_blogu(DIZIN, "wired", "Beşiktaş, siyah-beyaz")
    assert "Beşiktaş" in b and "Wired" in b or "wired" in b
    assert "1080" in b


def test_BILINMEYEN_dil_hata_vermez(tmp_path):
    assert yukle(tmp_path, "yok") is None
    assert prompt_blogu(tmp_path, "yok", "niyet").strip().startswith("İSTENEN")
