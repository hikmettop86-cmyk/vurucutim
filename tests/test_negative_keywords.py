"""negative_keywords elemesi Turkce I/i tuzagina dusmemeli.

CANLI VAKA: Aslan Gundem+ kanalina 'canlı' anahtar kelimesi eklendi ama
"CANLI | Galatasaray aliyor" baslikli canli blog ELENMEDI. Sebep Python'un
dile duyarsiz .lower()'i: "CANLI".lower() -> "canli" (noktali i), anahtar
kelime ise "canlı" (noktasiz i). Ikisi esitlenmez, filtre sessizce hicbir sey
yapmaz -- calisiyor gorunup sifir sey eler.
"""
from types import SimpleNamespace as NS

from short_bot.pipeline import _filter_negative_keywords


def _basliklar(*t):
    return [NS(title=x) for x in t]


def test_turkce_buyuk_harfli_baslik_elenir():
    items = _basliklar("CANLI | Galatasaray alıyor: anlaşmak üzere",
                       "Galatasaray-Villarreal maçında olay")
    kalan = _filter_negative_keywords(items, ["canlı"], language="tr")
    assert [i.title for i in kalan] == ["Galatasaray-Villarreal maçında olay"]


def test_turkce_kucuk_harfli_baslik_da_elenir():
    items = _basliklar("canlı anlatım: Galatasaray sahada", "Transfer tamam")
    kalan = _filter_negative_keywords(items, ["canlı"], language="tr")
    assert [i.title for i in kalan] == ["Transfer tamam"]


def test_ispanyolca_buyuk_harfli_baslik_elenir():
    items = _basliklar("Mercado de fichajes EN DIRECTO: altas y bajas",
                       "El Real Madrid rinde homenaje a Puskás")
    kalan = _filter_negative_keywords(items, ["en directo"], language="es")
    assert [i.title for i in kalan] == ["El Real Madrid rinde homenaje a Puskás"]


def test_almanca_I_harfi_turkcelestirilmez():
    """locale_fold dile ozgu: Almancada 'I'nin kucugu 'i'dir, 'ı' degil.
    Dile duyarsiz Turkce eslemesi 'Ich'i 'ıch' yapip filtreyi bozardi."""
    items = _basliklar("ICH BIN EIN BERLINER", "Bayern gewinnt")
    kalan = _filter_negative_keywords(items, ["ich bin"], language="de")
    assert [i.title for i in kalan] == ["Bayern gewinnt"]


def test_bos_liste_hicbir_seyi_elemez():
    items = _basliklar("CANLI yayin", "normal haber")
    assert _filter_negative_keywords(items, [], language="tr") == items
    assert _filter_negative_keywords(items, ["   "], language="tr") == items


def test_dil_parametresi_zorunlu():
    """Dilin VARSAYILANI YOK ve olmamali.

    Turkce eslemesini Ispanyolca baslikta kullanmak "EN DIRECTO"yu
    "en dırecto" yapar; 'en directo' anahtar kelimesi HIC eslesmez ve filtre
    calisiyor gorunup sifir sey eler. Yanlis varsayilan, filtresizlikten daha
    tehlikelidir cunku fark edilmez.
    """
    import pytest

    with pytest.raises(TypeError):
        _filter_negative_keywords(_basliklar("EN DIRECTO: partido"),
                                  ["en directo"])


def test_ayni_anahtar_kelime_dile_gore_farkli_davranir():
    """Ayni girdi, farkli dil -> farkli sonuc. Dilin gercekten islendiginin
    kaniti (fold dile duyarli olmasa iki sonuc ayni cikardi)."""
    items = _basliklar("EN DIRECTO: partido")
    assert _filter_negative_keywords(items, ["en directo"], "es") == []
    assert _filter_negative_keywords(items, ["en directo"], "tr") == items
