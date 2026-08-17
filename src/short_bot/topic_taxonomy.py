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


def normalize_subject(raw: str | None) -> str:
    """Saga öznesini (kişi/kulüp) karşılaştırılabilir tek biçime indir.

    `normalize_category` ile aynı katlama, TEK farkla: boş girdi BOŞ döner,
    `"?"` değil. Bilinmeyen kategori "bilinmeyen kovasında topla" demektir;
    bilinmeyen özne ise "bu videoyu hiç sayma" demektir — ikisini aynı yer
    tutucuya bağlamak, öznesiz videoları tek bir dev sagaya toplar ve o
    sahte saga bütün üretimi kilitlerdi.
    """
    if not isinstance(raw, str):
        return ""
    # "İ".lower() → "i" + U+0307 (görünmez birleşik nokta). "I" → "ı" YAPILMAZ:
    # kanallar çok dilli, Türkçe kuralı İspanyolca/Almanca özneleri bozar.
    text = raw.replace("İ", "i").lower()
    return " ".join(text.split())


def subject_matches(a: str, b: str) -> bool:
    """İki özne anahtarı aynı sagaya mı işaret ediyor.

    LLM bir koşuda "batrakov", diğerinde "aleksey batrakov" yazabilir; bunlar
    ayrı kova sayılırsa sayaç hiç dolmaz ve özellik sessizce işlevsiz kalır.
    Bu yüzden KELİME KÜMESİ alt-kümeliğine bakılır.

    Ham alt-dize (`a in b`) yerine kelime kümesi kullanmanın sebebi:
    "sara" ham alt-dize kuralıyla "sarabia"ya uyardı ve iki ayrı futbolcuyu
    birleştirirdi. Kelime kümesi bu yanlış birleşmeyi yapmaz.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = set(a.split()), set(b.split())
    kisa, uzun = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if not kisa or kisa == uzun:
        return False
    if any(len(t) < _SUBJECT_MIN_TOKEN for t in kisa):
        return False
    return kisa < uzun
