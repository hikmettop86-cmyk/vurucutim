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

# CJK'DE ÖZEL İSİM BÜYÜK HARFTEN TANINAMAZ — büyük harf yok. Ölçüldü
# (2026-08-22, Japonca kanalın ilk koşusu): _proper_nouns ve _SAYI japonca
# metinde HİÇBİR ŞEY bulmuyor, dolayısıyla kapı her uydurmaya "temiz" diyordu
# ("ソニーが五百億円で買収しました" bile geçti) — sessiz değil, YANILTICI bir güvence.
#
# KAPSAM BİLEREK DAR:
#   * kanji rakam dizileri (五百億, 十二) — uydurma istatistiğin ana taşıyıcısı
#   * Latin diziler (NHK, TBS, GTA)
# Katakana DIŞARIDA: Japoncada katakana yalnız özel isim değil HER ödünç
# sözcüktür (プラットフォーム, メディア); aday saymak kapıyı yanlış pozitife boğar
# ve kodun kendi dersi bunun üretimi durdurduğunu söylüyor (Burhan vakası).
# Kanji-only Japon isimleri (布施博) morfolojik çözümleyici olmadan güvenilir
# çıkarılamaz; bu kapı onları GÖRMEZ ve görüyormuş gibi yapmaz.
_CJK_DILLER: frozenset[str] = frozenset({"ja", "zh", "ko"})
_KANJI_SAYI = re.compile(r"[〇一二三四五六七八九十百千万億兆]{2,}")

# REKOR/ÜSTÜNLÜK İDDİALARI KAYNAKTA OLMALI.
#
# CANLI VAKA (2026-08-22, Japonca kanalın ilk videosu): anlatım
# 「倒産は過去最多を記録しています」 ("iflaslar REKOR seviyede") dedi; kaynakta
# yalnız 「経営破綻が相次ぐ中」 ("art arda iflaslar") vardı. Sayı da Latin de
# olmadığı için desen kapısı göremiyordu.
#
# Bu sınıf yakalanabilir: rekor/ilk/en-çok iddiaları KAPALI bir kelime kümesi
# ve her zaman olgusaldır. Kaynakta yoksa uydurmadır. Dar tutuldu — yanlış
# pozitif üretimi durdurur (Burhan vakası).
_USTUNLUK: dict[str, tuple[str, ...]] = {
    "ja": ("過去最多", "過去最高", "過去最大", "史上初", "初めて", "記録的", "最多", "最大規模"),
    "tr": ("rekor", "ilk kez", "en yüksek", "en büyük", "tarihi zirve", "zirve yaptı"),
    "de": ("rekord", "erstmals", "zum ersten mal", "höchststand", "so viele wie nie"),
    "en": ("record high", "record number", "for the first time", "all-time high"),
    "es": ("récord", "record", "por primera vez", "máximo histórico"),
}
_LATIN_DIZI = re.compile(r"[A-Za-z][A-Za-z0-9]+")

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


# EKLEMELİ (bitişken) DİLLER: ek KESME İŞARETİ OLMADAN köke yapışır.
#
# CANLI VAKA (2026-08-23, gundem-yorum koşu #2110 — bu listedeki en YENİ olgu
# kapısı kaybı): anlatım "Merkez Bankasının faiz kararı" dedi, kaynak "Merkez
# Bankası" yazıyordu. Kapı 'Bankasının'ı UYDURMA ilan etti ve iki turda da
# düzelmeyince VİDEO ÜRETİLMEDİ.
#
# Neden mevcut kollar yakalamıyor:
#   * `a in kaynak_fold` — 'bankasinin' kaynakta yok (kaynak 'bankasi' yazmış),
#   * kesme kolu — Türkçede ek çoğu zaman kesmesizdir ('Bankasının', 'Fener-
#     bahçenin'), `split("'")` hiçbir şey kırpmaz,
#   * fuzzy — ratio('bankasinin','bankasi') = %82, eşik %88. Ek uzadıkça oran
#     DÜŞER, yani eşiği indirmek çözüm değil: %82'ye inmek 'Chelsea'/'Charles'
#     sınıfını da içeri alırdı.
#
# Doğru değişmez: EK SONA GELİR, yani aday kaynak sözcüğüyle BAŞLAR. Ters yön
# (anlatım kök, kaynak ekli) zaten `a in kaynak_fold` ile geçiyor.
#
# DAR TUTULDU: yalnız ölçülmüş dil (tr). Almancada aynı kural körlük yaratırdı
# — bileşik sözcükler ('Bankgeschäft' 'Bank' ile başlar) uydurma adı kaynakta
# varmış gibi gösterirdi.
_EKLEMELI_DILLER: frozenset[str] = frozenset({"tr"})
# Kök en az bu kadar uzun olmalı.
#
# 4'te KALDI, 5 DEĞİL: gerçek kulüp adlarının bir kısmı dört harflidir (Roma,
# Ajax, Lyon, Nice) ve 5'e çıkarmak "Romanın ← Roma"yı yeniden yanlış pozitif
# yapardı — yani düzeltilen sınıfın ta kendisini geri getirirdi.
#
# KABUL EDİLEN BOŞLUK: kaynakta dört harfli bir sözcük varsa, onunla BAŞLAYAN
# uydurma bir ad kaçar ('Bank' kaynakta → 'Bankrupt' geçer). Takas bilinçli:
# uydurmanın kaynaktaki bir sözcüğün tam olarak baş harflerinden başlaması
# gerekir, bu da pratikte nadirdir; buna karşılık Türkçede ek almış ad HER
# cümlede geçer. Testle yazılı: tests/test_fact_gate_ekler.py
_EK_MIN_KOK = 4


def _gecer_mi(aday: str, kaynak_fold: str, kaynak_kelimeler: list[str],
              *, ek_alan_dil: bool = False) -> bool:
    a = _fold(aday)
    if a in kaynak_fold:            # düz geçiş: en sık durum
        return True
    # Ek almış / harfi düşmüş biçimler: 'Osimhen'i' ↔ 'Osimhen'
    a_cek = a.split("'")[0]
    if len(a_cek) >= 3 and a_cek in kaynak_fold:
        return True
    # Kesmesiz ek: aday kaynaktaki bir sözcükle BAŞLIYOR mu ('Bankasının' ←
    # 'Bankası'). Bkz. _EKLEMELI_DILLER notu.
    if ek_alan_dil and any(len(k) >= _EK_MIN_KOK and a_cek.startswith(k)
                           for k in kaynak_kelimeler):
        return True
    return any(fuzz.ratio(a_cek, k) >= _ESIK for k in kaynak_kelimeler)


_KANJI_RAKAM = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_KUCUK = {"十": 10, "百": 100, "千": 1000}
_KANJI_BUYUK = {"万": 10**4, "億": 10**8, "兆": 10**12}


def kanji_sayi_degeri(s: str) -> int | None:
    """'二十一' -> 21, '五百億' -> 50000000000. Sayı değilse None.

    NEDEN VAR (canlı vaka 2026-08-22): anlatım TTS için sayıyı OKUNDUĞU GİBİ
    yazar ('二十一日'), haber metni rakam kullanır ('21日'). Kapı ikisini ayrı
    şey sanıp uydurma ilan etti ve iki denemede de düzelmeyince ÜRETİM DURDU —
    kodun kendi uyardığı yanlış-pozitif sınıfı (Burhan vakası).
    """
    if not s:
        return None
    toplam = bolum = rakam = 0
    for ch in s:
        if ch in _KANJI_RAKAM:
            rakam = _KANJI_RAKAM[ch]
        elif ch in _KANJI_KUCUK:
            bolum += (rakam or 1) * _KANJI_KUCUK[ch]
            rakam = 0
        elif ch in _KANJI_BUYUK:
            toplam += (bolum + rakam) * _KANJI_BUYUK[ch]
            bolum = rakam = 0
        else:
            return None
    return toplam + bolum + rakam


def _sayi_kaynakta_var(aday: str, kaynak_fold: str, kaynak: str) -> bool:
    """Sayı adayı kaynakta geçiyor mu — YAZIMDAN BAĞIMSIZ.

    Kanji yazım ile rakam yazımı aynı olguyu gösterir; ikisi de denenir.
    """
    if _fold(aday) in kaynak_fold:
        return True
    deger = kanji_sayi_degeri(aday) if not aday.isdigit() else int(aday)
    if deger is None:
        return False
    if str(deger) in kaynak:
        return True
    # Kaynak kanji yazmış, anlatım rakam kullanmış olabilir.
    for k in _KANJI_SAYI.findall(kaynak):
        if kanji_sayi_degeri(k) == deger:
            return True
    return False


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
    cjk = (language or "").split("-")[0].lower() in _CJK_DILLER
    ek_alan_dil = (language or "").split("-")[0].lower() in _EKLEMELI_DILLER

    # BÜYÜK-HARF SEZGİSİ CJK'DE GEÇERSİZ VE ZARARLI.
    #
    # `_proper_nouns` cümleyi `\w+` ile böler ve büyük harfle başlayan
    # parçaları özel isim sayar. Japoncada BOŞLUK YOKTUR: tüm cümle tek bir
    # `\w+` parçasıdır. O parça Latin bir büyük harfle başlarsa — kaynak
    # atfında sık olur — CÜMLENİN TAMAMI özel isim adayı oluyor ve kaynakta
    # birebir bulunamadığı için "uydurma" ilan ediliyor:
    #
    #   「Webの報道によると、監督は起用を見送りました。」
    #     → aday: 'Webの報道によると'  (ek ve edatlar dahil)
    #
    # Bu İKİ ÜRETİMİ öldürdü (2026-08-22): 'Webの報道によると' ve
    # 'NHKの報道によると'. Olgu kapısı iki turda düzelmeyince videoyu iptal
    # ediyor — yani yanlış pozitif doğrudan üretim kaybı.
    #
    # CJK'de KAYIP YOK: Latin adlar zaten `_LATIN_DIZI` ile, sayılar
    # `_KANJI_SAYI` ile aşağıda taranıyor. Kanji/katakana özel isimler bu
    # sezgiye zaten görünmüyordu (büyük harfleri yok).
    if not cjk:
        for aday in _proper_nouns(narration_text, language):
            anahtar = _fold(aday)
            if anahtar in gorulen:
                continue
            gorulen.add(anahtar)
            if not _gecer_mi(aday, kaynak_fold, kaynak_kelimeler,
                             ek_alan_dil=ek_alan_dil):
                eksik.append(aday)

    if cjk:
        for aday in _KANJI_SAYI.findall(narration_text):
            anahtar = _fold(aday)
            if anahtar in gorulen:
                continue
            gorulen.add(anahtar)
            if not _sayi_kaynakta_var(aday, kaynak_fold, source_text):
                eksik.append(aday)
        for aday in _LATIN_DIZI.findall(narration_text):
            anahtar = _fold(aday)
            if anahtar in gorulen:
                continue
            gorulen.add(anahtar)
            if anahtar not in kaynak_fold:
                eksik.append(aday)

    for kalip in _USTUNLUK.get((language or "").split("-")[0].lower(), ()):
        if kalip in gorulen:
            continue
        if _fold(kalip) in _fold(narration_text) and _fold(kalip) not in kaynak_fold:
            gorulen.add(kalip)
            eksik.append(kalip)

    cjk = (language or "").split("-")[0].lower() in _CJK_DILLER
    for sayi in _SAYI.findall(narration_text):
        if sayi in gorulen:
            continue
        gorulen.add(sayi)
        varmi = (_sayi_kaynakta_var(sayi, kaynak_fold, source_text) if cjk
                 else sayi in kaynak_fold)
        if not varmi:
            eksik.append(sayi)

    return eksik
