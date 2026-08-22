"""Panelin ses acilirinda KANAL DILINDEKI sesler gorunmeli.

CANLI VAKA (2026-08-09): /api/ai33/voices tek sayfa cekiyordu. Ekranda
"121 ses yuklendi" yaziyordu ama icinde yalnizca 3 Turkce, 11 Ispanyolca ses
vardi -- kutuphanede 23 ve 77 var. Yani kullanici kanalina ses secmek
istediginde aradigi ses listede HIC yoktu ve hicbir uyari bunu soylemiyordu.
voice_picker bu tuzagi docstring'inde zaten yaziyordu ("SAYFALAMA SART:
varsayilan sayfa cogunlukla Ingilizce"), panel endpoint'i uygulamamisti.
"""
from short_bot.voice_picker import fetch_all_voices, voices_for


def _sayfa(dil: str, n: int, ofs: int = 0):
    return [{"voice_id": f"{dil}{i + ofs}", "name": f"{dil} ses {i + ofs}",
             "language": dil} for i in range(n)]


class _FakeList:
    """list_voices yerine: sayfa numarasina gore farkli diller dondurur.

    Gercek kutuphanenin davranisi: ilk sayfa agirlikli Ingilizce, hedef dil
    ILERIKI sayfalarda.
    """

    def __init__(self):
        self.pages_seen = []

    def __call__(self, *, api_key, provider="elevenlabs", search="", page=1,
                 page_size=100, base_url=None, session=None):
        self.pages_seen.append(page)
        if page == 1:
            return _sayfa("en", 100)
        if page == 2:
            return _sayfa("tr", 20) + _sayfa("es", 30)
        return []


def test_tek_sayfada_durmaz_ileriki_sayfalari_da_tarar(monkeypatch):
    sahte = _FakeList()
    monkeypatch.setattr("short_bot.voice_picker.list_voices", sahte)
    hepsi = fetch_all_voices(api_key="k")
    assert len(hepsi) == 150, "sayfalama yapilmadi -> hedef dil sesleri kaybolur"
    assert sahte.pages_seen[:2] == [1, 2]


def test_hedef_dildeki_sesler_ilk_sayfada_olmasa_da_bulunur(monkeypatch):
    monkeypatch.setattr("short_bot.voice_picker.list_voices", _FakeList())
    tr = voices_for("tr", api_key="k")
    assert len(tr) == 20
    assert {v["language"] for v in tr} == {"tr"}


def test_anahtar_yoksa_bos_liste(monkeypatch):
    monkeypatch.setattr("short_bot.voice_picker.list_voices", _FakeList())
    assert fetch_all_voices(api_key="") == []


def test_bos_sayfa_taramayi_bitirir(monkeypatch):
    """Kutuphane bitince durmali; _MAX_PAGES'e kadar bos istek atmamali."""
    sahte = _FakeList()
    monkeypatch.setattr("short_bot.voice_picker.list_voices", sahte)
    fetch_all_voices(api_key="k")
    assert sahte.pages_seen == [1, 2, 3], f"gereksiz istek: {sahte.pages_seen}"
