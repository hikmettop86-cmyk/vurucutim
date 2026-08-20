"""Olgu kapısı: anlatımda geçip haberde GEÇMEYEN özel isim/sayıları bulur.

NEDEN VAR (canlı vaka, short 1389 — Latido Blanco): anlatım prompt'unda
"Every claim must come from the article body. Invent nothing." kuralı ZATEN
vardı. Buna rağmen Sonnet "El Chelsea de Xavi Alonso ya lo quiso" diye bir cümle
yazdı; haberde ne Chelsea ne Alonso geçiyordu ve Xabi Alonso zaten Chelsea'de
değil. Yorum/hüküm serbestliği verilen bir personada model, hafızasındaki
parçaları habere aitmiş gibi cümleye katıyor.

Bir kural yetmediğine göre kapı MEKANİK olmalı: görüş serbest kalır ama her
İSİM ve her SAYI haberden gelmek zorundadır — ikisi de doğrulanabilir şeylerdir.

FAIL-OPEN: kaynak metin yoksa (paywall, çekim hatası) kapı çalışmaz. Aksi hâlde
makalesi çekilemeyen her haber sessizce üretimden düşerdi.
"""
from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

# Aday sayılmayan, cümle başında büyük harfle başlayan yapı kelimeleri.
# Bunlar aday sayılsaydı kapı her videoyu boşuna reddederdi.
_STOP: frozenset[str] = frozenset("""
el la los las un una unos unas y o pero si no ni que se de del al en con por
para su sus este esta esto ese esa eso ya cuando porque mientras aunque sin
todo toda todos todas mas muy como donde quien cual hay ha han habia sera son
es era fue solo tambien ahora asi hasta desde entre sobre tras cada otro otra
bu su o ve ama fakat ancak cunku eger ya da ise ki bir birkac her hepsi
daha sonra simdi artik yine hem ise iste sadece bile kadar gibi icin ile
yav yahu abi abicim kardesim hadi valla vallahi helal mesela bence bak
tamam yani aslinda gercekten kesinlikle bakin gordun soyluyorum bizim
the a an and or but if not that this these those there here when because
while although without all more very how where who which has have had was
were is are be been only also now still just even than then from into over
""".split())

_KELIME = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)
# Sayıları da yakalayan bölme (yalnız ad-dilleri için, bkz. _proper_nouns).
_TOKEN = re.compile(r"\d+|[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)
_SAYI = re.compile(r"\d+")
# Cümle sonu: . ! ? ve İspanyolca ters işaretler cümle BAŞLATIR.
_CUMLE_SONU = re.compile(r"[.!?…]+\s*")

# Fuzzy eşik: 'Osimhen'i' ↔ 'Osimhen' gibi ek/aksan farkları geçmeli,
# 'Chelsea' ↔ 'Arsenal' geçmemeli.
_ESIK = 88


def _fold(s: str) -> str:
    """Aksanları söküp küçültür — 'preguntó' ile 'pregunto' aynı sayılsın."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold().replace("’", "'")


# ADLARI BÜYÜK HARFLE YAZAN DİLLER. Almancada HER ad büyük harfle başlar
# ("der Streit", "ein Wechsel", "die Konkurrenz") — "cümle içinde büyük harf =
# özel ad" sezgiseli bu dilde çöker ve kapı her anlatımı uydurma ilan eder.
#
# CANLI VAKA (2026-08-20, Deutschland Klartext ilk koşusu): kapı
# ['Überläufer', 'Reihe', 'Konkurrenz', 'Streit', 'Wechsel', 'Kontoauszug']
# listesini "kaynakta geçmeyen isim" sayıp boşuna bir yeniden yazım turu
# harcadı. İkinci tur da takılsaydı video düşecekti.
#
# AYIRT EDİCİ: Almancada sıradan adın önünde neredeyse her zaman bir belirteç
# vardır (der/die/das, ein/eine, im/am/zum, dieser, kein…). Özel ad çoğunlukla
# belirteçsiz gelir ("in Stendal", "Bernd Prange spendet"). Kısaltmalar (CDU,
# AfD) ve arka arkaya iki büyük harfli sözcük (kişi/yer adı) HER ZAMAN adaydır.
_NOUN_CAPITALIZING: frozenset[str] = frozenset({"de"})

_DE_BELIRTEC: frozenset[str] = frozenset("""
der die das den dem des ein eine einen einem einer eines
kein keine keinen keinem keiner keines
mein meine meinen meinem meiner dein deine sein seine seinen seinem seiner
ihr ihre ihren ihrem ihrer unser unsere unseren unserem unserer euer eure
dieser diese dieses diesen diesem jeder jede jedes jeden jedem
im am zum zur beim vom ins ans aufs
viele mehrere einige manche alle solche beide welche
""".split())


def _cok_buyuk_harf(k: str) -> bool:
    """CDU, AfD, ARD gibi kısaltma mı (içinde ikinci bir büyük harf var mı)."""
    return sum(1 for c in k if c.isupper()) >= 2


# 'als'/'wie' sonrası ROL gelir, ad değil ("als Überläufer", "wie Nachbarn").
# Sayıdan sonra BİRİM gelir ("zehntausend Euro", "60 Häuser") — sayının kendisi
# zaten ayrıca denetleniyor.
_DE_ROL_ONCESI: frozenset[str] = frozenset({"als", "wie"})
_DE_SAYI_SONU = ("tausend", "hundert", "zig", "millionen", "milliarden",
                 "million", "milliarde")
_DE_SAYI_KELIME: frozenset[str] = frozenset("""
ein eine zwei drei vier funf sechs sieben acht neun zehn elf zwolf
dutzend etliche rund etwa knapp uber mehr weniger
""".split())


def _sayi_gibi(k: str) -> bool:
    f = _fold(k)
    return (any(c.isdigit() for c in k) or f in _DE_SAYI_KELIME
            or f.endswith(_DE_SAYI_SONU))


def _proper_nouns(text: str, language: str = "tr") -> list[str]:
    """Özel isim adayları.

    Cümle İÇİNDE büyük harfle başlayan her kelime adaydır. Cümle BAŞINDAKİ
    kelime ancak metinde başka bir yerde de (cümle içinde) büyük harfle geçiyorsa
    adaydır.

    NEDEN (canlı vaka, Aslan Gündem+ Burhan koşusu): halk dili personası
    "Yav bak şimdi...", "Fırsatlar böyle..." diye cümleye başlıyor. Cümle başı
    büyük harfli her kelimeyi aday saymak bunları uydurma ilan etti, iki tur da
    reddedildi ve video hiç üretilemedi. Sözlükle kovalamak sürdürülemez —
    ölçüt konumsal olmalı. Gerçek uydurmalar kaçmaz: bir kulüp/kişi adı
    anlatımda neredeyse her zaman cümle içinde de geçer.
    """
    ad_dili = (language or "tr").split("-")[0].lower() in _NOUN_CAPITALIZING
    ic_konumda: set[str] = set()
    adaylar: list[tuple[str, bool]] = []

    for cumle in _CUMLE_SONU.split(text):
        # Ad dillerinde SAYILAR da belirteç sayılır ("60 Häuser" → birim, ad
        # değil); bu yüzden orada rakamları da içeren bir bölme kullanılır.
        # Diğer dillerde bölme AYNEN korunur — sayı eklemek cümle-başı kuralını
        # kaydırıp Türkçede yeni yanlış pozitifler doğururdu.
        kelimeler = (_TOKEN.findall(cumle) if ad_dili else _KELIME.findall(cumle))
        buyukler = [bool(k[:1].isupper()) for k in kelimeler]
        for i, k in enumerate(kelimeler):
            if len(k) < 3 or not k[:1].isupper():
                continue
            if _fold(k) in _STOP:
                continue
            if ad_dili:
                # Kısaltma ya da arka arkaya büyük harfli sözcük dizisi (kişi/yer
                # adı) her hâlükârda aday; tek başına duran bir ad ancak önünde
                # belirteç YOKSA aday olur.
                komsu_buyuk = ((i > 0 and buyukler[i - 1] and i - 1 != 0)
                               or (i + 1 < len(kelimeler) and buyukler[i + 1]))
                onceki_ham = kelimeler[i - 1] if i > 0 else ""
                onceki = _fold(onceki_ham)
                if not _cok_buyuk_harf(k) and not komsu_buyuk and i > 0 and (
                        onceki in _DE_ROL_ONCESI or _sayi_gibi(onceki_ham)):
                    continue
                if not (_cok_buyuk_harf(k) or komsu_buyuk
                        or (i > 0 and onceki not in _DE_BELIRTEC)):
                    continue
                if i > 0 and onceki in _DE_BELIRTEC and not (
                        _cok_buyuk_harf(k) or komsu_buyuk):
                    continue
            cumle_basi = i == 0
            adaylar.append((k, cumle_basi))
            if not cumle_basi:
                ic_konumda.add(_fold(k))

    return [k for k, cumle_basi in adaylar
            if not cumle_basi or _fold(k) in ic_konumda]


def _gecer_mi(aday: str, kaynak_fold: str, kaynak_kelimeler: list[str]) -> bool:
    a = _fold(aday)
    if a in kaynak_fold:            # düz geçiş: en sık durum
        return True
    # Ek almış / harfi düşmüş biçimler: 'Osimhen'i' ↔ 'Osimhen'
    a_cek = a.split("'")[0]
    if len(a_cek) >= 3 and a_cek in kaynak_fold:
        return True
    return any(fuzz.ratio(a_cek, k) >= _ESIK for k in kaynak_kelimeler)


def unverified_claims(narration_text: str, source_text: str, *,
                      language: str = "tr") -> list[str]:
    """Anlatımda geçip kaynakta bulunmayan özel isim ve sayılar (tekilleştirilmiş).

    Boş liste = anlatımdaki her isim/sayı haberden geliyor.
    Kaynak boşsa boş liste döner (fail-open — bkz. modül açıklaması).
    """
    if not (source_text or "").strip() or not (narration_text or "").strip():
        return []

    kaynak_fold = _fold(source_text)
    kaynak_kelimeler = [_fold(k) for k in _KELIME.findall(source_text)]

    eksik: list[str] = []
    gorulen: set[str] = set()

    for aday in _proper_nouns(narration_text, language):
        anahtar = _fold(aday)
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        if not _gecer_mi(aday, kaynak_fold, kaynak_kelimeler):
            eksik.append(aday)

    for sayi in _SAYI.findall(narration_text):
        if sayi in gorulen:
            continue
        gorulen.add(sayi)
        if sayi not in kaynak_fold:
            eksik.append(sayi)

    return eksik
