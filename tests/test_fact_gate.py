"""Anlatim, kaynak haberde OLMAYAN ozel isim/sayi uydurmamali.

CANLI VAKA (short 1389, Latido Blanco): Sonnet "El Chelsea de Xavi Alonso ya lo
quiso y sigue ahi" diye bir cumle yazdi. Ne Chelsea ne Alonso haberde geciyordu;
Xabi Alonso zaten Chelsea'de degil. Prompt'ta "Invent nothing" kurali VARDI ve
yetmedi -- bu yuzden kapi mekanik.
"""
import pytest

from short_bot.fact_gate import unverified_claims

MAKALE = (
    "La IA lo tiene claro. El diario As pregunto a la inteligencia artificial "
    "quien es el ideal para el puesto de Rodri y respondio Zubimendi. "
    "El Arsenal pide 90 millones por el centrocampista vasco. "
    "El Real Madrid sigue atento al mercado y Xabi Alonso no ha dicho nada."
)


def test_gercek_uydurma_yakalanir():
    anlatim = ("Zubimendi vuelve a sonar. El Chelsea ya lo quiso y sigue ahi. "
               "El Arsenal pide 90 millones.")
    eksik = unverified_claims(anlatim, MAKALE, language="es")
    assert any("Chelsea" in e for e in eksik), f"Chelsea yakalanmadi: {eksik}"


def test_haberden_gelen_isimler_gecer():
    anlatim = ("Zubimendi es el ideal para el Real Madrid. "
               "El Arsenal pide 90 millones.")
    assert unverified_claims(anlatim, MAKALE, language="es") == []


def test_cumle_basi_baglaclari_ozel_isim_sayilmaz():
    """'El', 'Si', 'Pero', 'Y' cumle basinda buyuk harfle baslar ama isim degil.
    Bunlari uydurma saymak her videoyu bosuna reddederdi."""
    anlatim = "Pero el Madrid no lo necesita. Si reaparece, algo pasa. Y ya esta."
    assert unverified_claims(anlatim, MAKALE, language="es") == []


def test_aksan_farki_uydurma_sayilmaz():
    """Model/TTS aksani dusurebiliyor; 'pregunto' ile 'pregunto' ayni seydir."""
    anlatim = "Zubimendi y el Real Madrid. As pregunto a la IA."
    assert unverified_claims(anlatim, MAKALE, language="es") == []


def test_uydurma_sayi_yakalanir():
    anlatim = "El Arsenal pide 150 millones."
    assert "150" in unverified_claims(anlatim, MAKALE, language="es")


def test_haberdeki_sayi_gecer():
    assert unverified_claims("Pide 90 millones.", MAKALE, language="es") == []


def test_turkce_ek_almis_isim_gecer():
    """Turkcede ozel isim ek alir ('Osimhen'i'); bu uydurma degildir."""
    makale = "Galatasaray, Osimhen ile anlasti. Transfer bedeli 75 milyon euro."
    anlatim = "Galatasaray Osimhen'i aldi. Bedel 75 milyon."
    assert unverified_claims(anlatim, makale, language="tr") == []


def test_turkce_uydurma_kulup_yakalanir():
    makale = "Galatasaray, Osimhen ile anlasti. Transfer bedeli 75 milyon euro."
    anlatim = "Galatasaray Osimhen'i aldi. Bizim Osimhen'i Fenerbahce de istiyordu."
    eksik = unverified_claims(anlatim, makale, language="tr")
    assert any("Fenerbah" in e for e in eksik), f"yakalanmadi: {eksik}"


def test_bilincli_taviz_cumle_basinda_tek_gecen_isim_kacar():
    """BILINCLI TAVIZ, belgelensin diye test edilmistir.

    Cumle basinda SADECE BIR KEZ gecen uydurma isim yakalanmaz. Alternatifi --
    cumle basi buyuk harfli her kelimeyi aday saymak -- halk dili anlatiminda
    'Yav' ve 'Firsatlar' yuzunden videoyu HIC urettirmedi (Aslan Gundem+ Burhan
    kosusu). Yanlis pozitif kanali tamamen durdurur; yanlis negatif nadiren bir
    uydurma gecirir. Pahali olan birincisidir.
    """
    makale = "Galatasaray, Osimhen ile anlasti."
    assert unverified_claims("Fenerbahce de istiyordu.", makale, language="tr") == []


def test_halk_dili_cumle_basi_kelimeleri_uydurma_sayilmaz():
    """CANLI VAKA (Aslan Gundem+, Burhan kosusu): fanatik/halk dili personasi
    'Yav bak simdi...', 'Firsatlar boyle...' diye cumleye basliyor. Kapi bunlari
    ozel isim sanip iki turda da reddetti ve VIDEO URETILEMEDI.

    Cumle basindaki bir kelime, ancak metinde BASKA bir yerde de buyuk harfle
    geciyorsa ozel isimdir."""
    makale = "Galatasaray, Porto ile Rodrigo Mora icin anlasmak uzere."
    anlatim = ("Yav bak simdi. Galatasaray Mora'yi aliyor. "
               "Firsatlar boyle degerlendirilir. Kardesim bu is tamam.")
    assert unverified_claims(anlatim, makale, language="tr") == []


def test_cumle_basindaki_uydurma_isim_yine_yakalanir():
    """Cumle basi tamamen korumasiz birakilamaz: ayni isim metinde bir kez daha
    (cumle icinde) geciyorsa ozel isimdir ve denetlenir."""
    makale = "Galatasaray, Porto ile anlasmak uzere."
    anlatim = "Chelsea de istiyordu. Ama Chelsea vazgecmedi."
    eksik = unverified_claims(anlatim, makale, language="tr")
    assert any("Chelsea" in e for e in eksik), f"yakalanmadi: {eksik}"


def test_bos_kaynak_kapiyi_actirmaz():
    """Makale cekilemediyse (paywall) her sey 'dogrulanamaz' olurdu ve kapi
    her videoyu reddederdi. Kaynak yoksa kapi CALISMAZ (fail-open)."""
    assert unverified_claims("Chelsea ve Alonso.", "", language="es") == []
