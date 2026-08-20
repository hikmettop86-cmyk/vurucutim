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


# ADLARI BÜYÜK HARFLE YAZAN DİLLER (Almanca). Bu dilde "büyük harf = özel ad"
# sezgiseli KANIT DEĞİLDİR: her ad büyük harfle başlar.
#
# İKİ CANLI VAKA:
#   1) İlk koşu: ['Überläufer','Reihe','Konkurrenz','Streit','Wechsel',
#      'Kontoauszug'] uydurma sayıldı → boşuna bir yeniden yazım turu.
#   2) İkinci koşu (kullanıcı bildirimi): 'Todesfall' iki turda da düzelmedi,
#      VİDEO ÜRETİLMEDİ. Belirteç kuralı yetmiyor çünkü Almancada sıfat araya
#      giriyor ("ein plötzlicher Todesfall") ve deyimler belirteçsiz kuruluyor
#      ("unter Schock", "vor Ort", "nach Angaben").
#
# KARAR: kanıt olmayan şeye dayanarak video düşürülmez. Almancada aday yalnız
# GERÇEKTEN ad işareti taşıyanlardır:
#   * kısaltma (CDU, AfD, ZDF) — ikinci bir büyük harf taşır,
#   * arka arkaya iki "ad-gibi" sözcük (kişi/yer/kurum: "Bernd Prange",
#     "Sachsen Anhalt") — işlev sözcükleri ve belirteçler bu diziye girmez.
# Tek başına duran büyük harfli sözcük ADAY DEĞİLDİR.
#
# KAPI KÖRLEŞMEZ: uydurma bir kişi/kurum anlatımda neredeyse her zaman iki
# sözcüklü ("Olaf Scholz") ya da kısaltmadır; uydurma SAYILAR ise dilden
# bağımsız olarak ayrıca denetleniyor — sahtekârlığın en sık biçimi zaten odur.
#
# KABUL EDİLEN BOŞLUK: tek sözcüklü bir yer/kişi adı ("in Karlsruhe") kaçar,
# çünkü Almancada "in Karlsruhe" ile "unter Schock" yapı olarak AYNIDIR ve
# ikisini ayıracak bir sinyal yok. Takas bilinçli: iki günde iki video
# kaybetmektense nadir bir tek sözcüklü ad kaçsın. Testle yazılı:
# tests/test_german_channel.py::test_olgu_kapisi_almanca_BILINEN_BOSLUK_tek_sozcuklu_ad
_NOUN_CAPITALIZING: frozenset[str] = frozenset({"de"})

# Almanca işlev sözcükleri: belirteçler, edatlar, bağlaçlar, yardımcı fiiller.
# KAPALI bir sınıf olduğu için liste sürdürülebilir — modül başındaki "sözlükle
# kovalamak sürdürülemez" uyarısı İÇERİK adları içindi, işlev sözcükleri için
# değil. Cümle başında büyük harfle yazıldıklarında ad dizisini bozmasınlar diye
# gerekli ("Auch Olaf Scholz" → 'Auch' diziye girmemeli).
_DE_ISLEV: frozenset[str] = frozenset("""
der die das den dem des ein eine einen einem einer eines
kein keine keinen keinem keiner keines
mein meine meinen meinem meiner dein deine sein seine seinen seinem seiner
ihr ihre ihren ihrem ihrer unser unsere unseren unserem unserer euer eure
dieser diese dieses diesen diesem jeder jede jedes jeden jedem
im am zum zur beim vom ins ans aufs
viele mehrere einige manche alle solche beide welche
in an auf aus bei mit nach von vor seit zu über unter gegen um für durch ohne
laut trotz während wegen ab bis neben hinter zwischen innerhalb statt
und oder aber denn dass weil wenn als wie also doch schon noch nur auch sogar
ist sind war waren hat haben hatte hatten wird werden wurde wurden kann können
soll sollen muss müssen darf dürfen will wollen sich man wer was wann wo warum
nicht kein sehr mehr weniger hier dort dann jetzt heute gestern morgen
es er sie ihm ihn ihr wir uns ihr euch dann dabei damit dafür dagegen
""".split())


def _cok_buyuk_harf(k: str) -> bool:
    """CDU, AfD, ARD gibi kısaltma mı (içinde ikinci bir büyük harf var mı)."""
    return sum(1 for c in k if c.isupper()) >= 2


def _ad_gibi(k: str) -> bool:
    """Ad dizisine girebilecek sözcük: büyük harfle başlar ve işlev sözcüğü
    değildir. 'Auch Olaf Scholz' → 'Auch' diziye girmez, 'Olaf Scholz' girer."""
    return bool(k) and k[:1].isupper() and _fold(k) not in _DE_ISLEV


def ad_gibi_dizi(kelimeler: list[str], i: int) -> bool:
    """i'deki sözcük, arka arkaya en az İKİ ad-gibi sözcükten oluşan bir dizinin
    parçası mı ("Bernd Prange", "Sachsen Anhalt", "Olaf Scholz")."""
    if not _ad_gibi(kelimeler[i]):
        return False
    onceki = i > 0 and _ad_gibi(kelimeler[i - 1])
    sonraki = i + 1 < len(kelimeler) and _ad_gibi(kelimeler[i + 1])
    return bool(onceki or sonraki)


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
                # Aday YALNIZ gerçek ad işareti taşıyanlar: kısaltma ya da
                # arka arkaya iki "ad-gibi" sözcük. Tek başına duran büyük
                # harfli sözcük Almancada kanıt DEĞİLDİR (bkz. modül üstü not).
                if not (_cok_buyuk_harf(k) or ad_gibi_dizi(kelimeler, i)):
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
