"""Konu etiketlerini tek biçime indirir.

`Script.category` serbest metindir ve LLM her koşuda farklı yazıyor. Gerçek
dağılım (galatasaray, 695 short):

    Transfer 210 | transfer 138 | futbol 113 | spor 51 | Futbol 41 | Spor 32
    Futbol Transfer 14 | Transfer Haberleri 10 | Galatasaray 8 | ...

Aynı konu 4-5 kovaya bölününce learning/aggregator'ın kategori ortalamaları
n=2 eşiğinin altında kalıyor ve scorer'a giden ipucu boşalıyor. Buradaki
normalizasyon yalnız YAZIM farklarını katlar (büyük/küçük harf, boşluk) —
anlam birleştirmesi (ör. "Futbol Transfer" → "transfer-gelen") yapmaz, çünkü
geçmiş etiketler o ayrımı taşıyacak kadar ayrıntılı değil. İleriye dönük
ayrım kanal config'indeki canonical liste ile sağlanır.
"""
from __future__ import annotations

import unicodedata

_PLACEHOLDER = "?"


def normalize_category(raw: str | None) -> str:
    """Kategori etiketini karşılaştırılabilir tek biçime indir.

    Boş/None girdi `"?"` döner (aggregator'ın mevcut bilinmeyen göstergesi).
    """
    if not isinstance(raw, str):
        return _PLACEHOLDER
    # "İ".lower() Python'da "i" + U+0307 (combining dot above) üretir; bu
    # görünmez karakter "İLGİNÇ" ile "ilginç" etiketlerini ayrı kovalara
    # düşürür. Türkçe'ye özgü tek harf olduğu için önce onu eşliyoruz.
    # NOT: "I" → "ı" dönüşümü YAPILMAZ — kanallar çok dilli (es/ja/de) ve
    # Türkçe kuralı İspanyolca "INFORMACIÓN"u "ınformacıón" yapardı.
    text = raw.replace("İ", "i").lower()
    collapsed = " ".join(text.split())
    return collapsed or _PLACEHOLDER


# Özne (saga) anahtarları için en kısa anlamlı kelime uzunluğu. Bunun altındaki
# kelimelerde alt-küme eşleşmesi rastgele birleştirme üretir ("ns" her yere uyar).
_SUBJECT_MIN_TOKEN = 4

# Türkçede özel ada gelen çekim eki KESMEYLE ayrılır: "Batrakov'un",
# "Galatasaray'ın", "Leao'ya". Kesmeden sonrası ek olduğu için atılır —
# atılmazsa aynı özne iki kovaya bölünür ve sayaç sessizce hiç dolmaz.
# Gövde 3 harften kısaysa KESİLMEZ: "O'Brien" gibi adlarda kesme ekin değil
# adın parçasıdır ve kesmek özneyi "o"ya indirirdi.
_APOSTROPHES = "'’ʼ`"
_MIN_STEM_BEFORE_APOSTROPHE = 3


def _fold_ascii(text: str) -> str:
    """Aksanı eşleşme için sök. YALNIZ özne anahtarında.

    Özne hiçbir yerde GÖSTERİLMİYOR — tek işi karşılaştırılmak. Bu yüzden
    burada sert katlama doğru ve simetriktir: iki taraf da `normalize_subject`
    üzerinden geçtiği için "Aktürkoğlu" ile "Akturkoglu" aynı anahtara iner.

    Neden gerekli (ölçüldü): LLM aynı Türkçe soyadını iki koşuda iki farklı
    yazıyor ve anahtar ikiye bölünüyordu —

        'Aktürkoğlu' -> 'aktürkoğlu' | 'Akturkoglu' -> 'akturkoglu' | eşleşme YOK
        'Kılıç'      -> 'kılıç'      | 'Kilic'      -> 'kilic'      | eşleşme YOK
        'Şahin'      -> 'şahin'      | 'Sahin'      -> 'sahin'      | eşleşme YOK

    Bu kanalda anahtar sapmasının EN SIK kaynağı buydu ve hiçbir savunma yoktu;
    sayaç yarı yarıya boş kalıyordu.

    `ı` ve `ß` elle eşlenir: `ı` ayrı bir HARFTİR, birleşik işaret ayrışması
    yoktur ve NFKD onu olduğu gibi bırakır. `ğ ş ü ö ç` ise NFKD altında
    doğru ayrışır (taban harf + birleşik işaret), işareti atmak yeter.

    NOT: Katlama ASCII yönündedir (`ı → i`), Türkçe `I → ı` yönünde DEĞİL —
    o yön İspanyolca "INFORMACIÓN"u bozardı. Bu yön hem "Kılıç"ı hem
    "INFORMACIÓN"u güvenle tek biçime indirir.
    """
    text = text.replace("ı", "i").replace("ß", "ss")
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _stem(token: str) -> str:
    """Bir kelimeyi çekim ekinden ve noktalamadan arındır."""
    for ch in _APOSTROPHES:
        idx = token.find(ch)
        if idx >= _MIN_STEM_BEFORE_APOSTROPHE:
            token = token[:idx]
            break
    return "".join(c for c in token if c.isalnum())


def normalize_subject(raw: str | None) -> str:
    """Saga öznesini (kişi/kulüp) karşılaştırılabilir tek biçime indir.

    `normalize_category`'den İKİ noktada ayrılır:

    1) Boş girdi BOŞ döner, `"?"` değil. Bilinmeyen kategori "bilinmeyen
       kovasında topla" demektir; bilinmeyen özne ise "bu videoyu hiç sayma"
       demektir — ikisini aynı yer tutucuya bağlamak, öznesiz videoları tek
       bir dev sagaya toplar ve o sahte saga bütün üretimi kilitlerdi.
    2) Aksan SÖKÜLÜR (`_fold_ascii`). Kategoride sökülmez, çünkü kategori
       değerleri kanal config'indeki KAPALI listeden birebir kopyalanır ve
       gösterilir; özne ise hiç gösterilmeyen saf karşılaştırma anahtarıdır,
       LLM'in yazım tercihine dayanır.
    """
    if not isinstance(raw, str):
        return ""
    # "İ".lower() → "i" + U+0307 (görünmez birleşik nokta). "I" → "ı" YAPILMAZ:
    # kanallar çok dilli, Türkçe kuralı İspanyolca/Almanca özneleri bozar.
    text = raw.replace("İ", "i").lower()
    # Aksan sökme SIRASI iki sebeple TAM BURADA:
    # 1) KÜÇÜLTMEDEN SONRA — `ı → i` eşlemesi yalnız küçük harfte anlamlı;
    #    büyük "I" zaten ASCII ve `.lower()` onu "i" yapıyor.
    # 2) TİRE BÖLMESİ ve `_stem`'den ÖNCE — NFKD, aşağıdaki adımların ARADIĞI
    #    ayırıcıların uyumluluk biçimlerini ASCII karşılığına indirir:
    #    tam-genişlik kesme (U+FF07) → "'", tam-genişlik tire (U+FF0D) → "-".
    #    Sökme sonraya kalsaydı bu karakterler ayırıcı listelerine uymaz,
    #    `_stem`'in alnum süzgeci de onları sessizce yutup kelimeleri
    #    yapıştırırdı. Ölçüldü:
    #        "Batrakov＇un" → sonra sökülürse 'batrakovun', önce 'batrakov'
    #        "Jean－Claude" → sonra sökülürse 'jeanclaude',  önce 'jean claude'
    text = _fold_ascii(text)
    # Tire ve alt çizgi kelime ayırıcıdır: "jean-claude" ile "jean claude"
    # aynı öznedir, LLM'in hangisini yazdığı rastlantıdır.
    for ayirici in ("-", "–", "_"):
        text = text.replace(ayirici, " ")
    return " ".join(_stem(t) for t in text.split() if _stem(t))


def subject_matches(a: str, b: str) -> bool:
    """İki özne anahtarı aynı sagaya mı işaret ediyor.

    LLM bir koşuda "batrakov", diğerinde "aleksey batrakov" yazabilir; bunlar
    ayrı kova sayılırsa sayaç hiç dolmaz ve özellik sessizce işlevsiz kalır.
    Bu yüzden KELİME KÜMESİ alt-kümeliğine bakılır.

    Ham alt-dize (`a in b`) yerine kelime kümesi kullanmanın sebebi:
    "sara" ham alt-dize kuralıyla "sarabia"ya uyardı ve iki ayrı futbolcuyu
    birleştirirdi. Kelime kümesi bu yanlış birleşmeyi yapmaz.

    ÇAĞIRAN SORUMLULUĞU: her iki argüman da `normalize_subject`'ten geçmiş
    olmalı. Bu fonksiyon katlama YAPMAZ; ham LLM çıktısıyla çağrılırsa hata
    değil sessiz EŞLEŞMEME döner.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return False
    if ta == tb:
        # Aynı kelimeler, farklı sıra: "real madrid" / "madrid real".
        # Erken dönüş `a == b` bunu YAKALAMAZ (dizgeler farklı) ve alt-küme
        # testi de yakalamaz (öz alt-küme değil, eşit) — ayrıca ele alınmalı,
        # yoksa aynı özne iki kovaya bölünür ve sayaç sessizce hiç dolmaz.
        return True
    kisa, uzun = (ta, tb) if len(ta) < len(tb) else (tb, ta)
    if any(len(t) < _SUBJECT_MIN_TOKEN for t in kisa):
        return False
    return kisa < uzun
