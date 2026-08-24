"""Dile duyarlı metin normalleştirme: aksan koruması, büyütme, küçültme.

Üç iş var ve ÜÇÜ DE DİLE ÖZGÜ. Dile duyarsız hâlleri Türkçe dışındaki her kanalı
SESSİZCE bozuyordu:

  • strip_foreign_diacritics — hedef dilin alfabesinde olmayan aksanları söker.
    Dile duyarsız hâli Almanca 'Täglich'i 'Taglich' yapıyordu. Bu bir pydantic
    field_validator, yani LLM'in yazdığı HER anlatım cümlesinde koşuyor: TTS yanlış
    okuyor, altyazıda yanlış görünüyor. Hiçbir hata, hiçbir log.

  • locale_upper — Türkçede 'i'nin büyüğü 'İ'dir, Almancada 'I'dır. Dile duyarsız hâli
    Almanca kanalın ekran rozetine 'BİER GARTEN' yazıyordu.

  • locale_fold — eşleştirme için küçültme. Türkçe eşlemesi 'I' → 'ı' yapıyor; Almanca
    metinde bu 'Ich'i 'ıch' yapar ve r'\\bich\\b' ASLA eşleşmez. Yani kusursuz bir
    Almanca yasaklı-kalıp listesi yazsak bile denetçi sıfır şey bulurdu.
"""
import re
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar

from short_bot.locale import ALPHABET_EXTRA

# Aktif hedef dil.
#
# NEDEN CONTEXTVAR, NEDEN PARAMETRE DEĞİL: aksan temizleyicisi bir pydantic
# field_validator'dan çağrılıyor ve validator'ın çağıranın dilini görmesinin yolu yok.
# Dili her model kurulum noktasından (LLM parse + fit_word_budget gibi yeniden-kurma
# yolları + testler) elle geçirmek onlarca dokunuş demek ve BİRİ UNUTULURSA SESSİZCE
# TÜRKÇEYE DÜŞER — düzeltmeye çalıştığımız hatanın aynısı. Contextvar iş parçacığı
# başına yalıtık (her pipeline koşusu kendi thread'inde) ve `with language(...)`
# kapsamı açıkça sınırlar.
_LANG: ContextVar[str] = ContextVar("shortbot_lang", default="tr")


@contextmanager
def language(lang: str):
    """Bu blok boyunca hedef dil ``lang``. İç içe kullanılabilir."""
    tok = _LANG.set(lang)
    try:
        yield
    finally:
        _LANG.reset(tok)


def current_language() -> str:
    """Şu anki hedef dil (kurulmadıysa 'tr')."""
    return _LANG.get()


# CJK ve akrabalarının başladığı kod noktası (CJK Radicals Supplement). Buradan
# yukarısı: kana, CJK noktalama (、。「」), kanji, hangul, tam-genişlik formlar.
#
# NEDEN BLOK KURALI, NEDEN ALPHABET_EXTRA'YA YAZMIYORUZ: 'ä'yi tabloya yazabiliriz,
# 50.000 kanji'yi yazamayız. Ve tehlike gerçek — NFKD, dakuten'i AYRI bir birleşen
# işarete ayırıyor (が = か + U+3099), sökücü de onu bir aksan sanıp atıyordu:
# 犬が (köpek-ÖZNE) → 犬か (köpek-mi?), ヤバい → ヤハい (kelime bile değil). Bu
# fonksiyon bir pydantic field_validator; anlatımın HER cümlesinde, sessizce koşar.
_CJK_START = 0x2E80


def strip_foreign_diacritics(s: str) -> str:
    """Hedef dilin alfabesinde OLMAYAN harflerin aksanını sök.

    Var oluş sebebi: model ara sıra hedef dile yabancı aksan sızdırıyor (Türkçe
    çıktıda 'CANLÍ'). Ama sökme HEDEF DİLE GÖRE yapılmalı — Almancada 'ä' yabancı
    değil, alfabenin harfidir.

        with language("tr"): strip_foreign_diacritics("CANLÍ")    → "CANLI"
        with language("de"): strip_foreign_diacritics("Täglich")  → "Täglich"
        with language("tr"): strip_foreign_diacritics("Täglich")  → "Taglich"
    """
    keep = ALPHABET_EXTRA.get(_LANG.get(), ALPHABET_EXTRA["tr"])
    out = []
    for ch in s:
        if ord(ch) < 128 or ch in keep or ord(ch) >= _CJK_START:
            out.append(ch)
            continue
        decomposed = unicodedata.normalize("NFKD", ch)
        base = "".join(c for c in decomposed if not unicodedata.combining(c))
        # Tabanı ASCII DEĞİLSE bu bir Latin aksanı değil, BAŞKA BİR YAZI SİSTEMİ.
        # Kiril 'й' → 'и', Yunanca 'ά' → 'α': ikisi de ayrı harf, aksanlı varyant
        # değil. Sökmek kelimeyi bozar; bu fonksiyonun işi o değil.
        if base and not base.isascii():
            out.append(ch)
            continue
        out.append(base if base else "")
    return "".join(out)


# Eski ad — 15 import noktası var (models.py, narration.py, generator.py,
# reel_models.py, reel_arc.py). Kırmıyoruz; varsayılan dil "tr" olduğu için davranış
# birebir aynı kalır.
strip_non_turkish_diacritics = strip_foreign_diacritics


# Python'un str.upper()'ı Unicode'un DİLDEN BAĞIMSIZ eşlemesini kullanır: 'i' → 'I'.
# Türkçede 'i'nin büyüğü 'İ'dir (noktalı), 'ı'nın büyüğü 'I'dır (noktasız). Bu iki
# harf Türkçede AYRI harflerdir; karıştırmak kelimeyi bozar.
_TR_UPPER = str.maketrans({"i": "İ", "ı": "I"})


def turkish_upper(s: str) -> str:
    """Türkçe-farkında büyük harf.

    'Bilinmeyen Tarih'.upper() → 'BILINMEYEN TARIH' (YANLIŞ)
    turkish_upper('Bilinmeyen Tarih') → 'BİLİNMEYEN TARİH' (doğru)

    Bunun en çok acıttığı yer MARKA ROZETİDİR: rozet, kanalın özenli olduğunu
    söylemesi gereken şeydir; 'BILINMEYEN TARIH' yazan bir rozet tam tersini ilan
    eder.
    """
    return s.translate(_TR_UPPER).upper()


# ------------------------------------------------------------------ kelime bölme
#
# Boşlukla yazmayan diller. Bunlarda ``text.split()`` TÜM CÜMLEYİ tek "kelime"
# yapar ve üç şey birden bozulur: karaoke altyazı (cümle tek blok yanar), sadakat
# denetimi (senaryo 1 token, whisper 20 token → olmayan kayıp bildirir, TTS boşuna
# yenilenir) ve kelime bütçesi.
_NO_SPACE_LANGS = frozenset({"ja", "zh"})

# Öbek boyu. MIN: iyi bir kırılma noktası bulunsa bile bu kadar birikmeden kesme
# (tek karakterlik altyazı okunmaz). MAX: hiç kırılma noktası çıkmazsa zorla kes.
_JA_MIN_CHUNK = 3
_JA_MAX_CHUNK = 7

# ÖKSÜZ KUYRUK BİRLEŞTİRME. Uzun hiragana dizilerinde (見捨てませんでした) kırılacak yer
# yoktur, MAX zorla keser ve geriye "した。" gibi bir parça kalır — ekranda görülüyor.
# Bu kadarlık kuyruğu önceki öbeğe geri yapıştırıyoruz.
#
# ÜST SINIR ALTYAZI SATIRINDAN GELİYOR: altyazı 82px, kutu 960px geniş, CJK glifleri
# tam genişlik (1em) → satıra 960/82 ≈ 11 karakter. 11'e kadar birleştirmek bir satırı
# taşırmaz; ortadan bölünmüş bir kelimeden de her hâlükârda iyidir.
_JA_TAIL_MAX = 4
_JA_LINE_MAX = 11

# Kendinden ÖNCEKİ öbeğe yapışıp onu bitiren işaretler.
_JA_BREAK_AFTER = frozenset("。、！？…・：；」』）〉》!?,.")


def _ja_class(ch: str) -> str:
    """Karakterin yazı sınıfı. Sınıf DEĞİŞİMİ muhtemel bir kelime sınırıdır."""
    o = ord(ch)
    if 0x3041 <= o <= 0x309F:
        return "hira"
    if 0x30A0 <= o <= 0x30FF or 0xFF66 <= o <= 0xFF9F:
        return "kata"
    if 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF:
        return "kanji"
    return "other"          # latin, rakam, sembol — bitişik akar, ortadan bölünmez


def _split_ja(token: str) -> list[str]:
    """Boşluksuz Japonca metni altyazı boyunda öbeklere böler.

    DİLBİLİMSEL DEĞİL, SEZGİSEL. Gerçek çözümleyici (MeCab/fugashi) harici bağımlılık
    ister; buradaki kural yazı-sınıfı değişimini kullanır: hiragana genelde ek/edattır,
    kanji/katakana genelde içerik kelimesi — hiragana'dan kanji'ye geçiş çoğunlukla
    yeni bir öbeğin başıdır ("この犬が | 飼い主を | 助けた。").

    En kötü hâli zararsız: öbekler whisper'ın birimlerine benzemezse ``align_to_asr``
    demir bulamaz ve orantılı dağıtıma düşer — yani bugünkü davranışa.
    """
    chunks: list[str] = []
    cur = ""
    prev = ""
    for ch in token:
        if ch in _JA_BREAK_AFTER:
            if cur:
                chunks.append(cur + ch)
            elif chunks:
                chunks[-1] += ch        # noktalama yeni öbek BAŞLATMAZ
            else:
                chunks.append(ch)
            cur, prev = "", ""
            continue
        cls = _ja_class(ch)
        if cur:
            boundary = cls != prev and not (cls == "hira" or prev == "")
            if len(cur) >= _JA_MAX_CHUNK or (boundary and len(cur) >= _JA_MIN_CHUNK):
                chunks.append(cur)
                cur = ""
        cur += ch
        prev = cls
    if cur:
        chunks.append(cur)

    # ÖKSÜZ KUYRUK YOK. MAX sınırı zorla kırınca geriye 1-2 karakterlik bir parça
    # kalabiliyor ve o parça EKRANDA görünüyor: "近づいてきまし | た。" (final QA bunu
    # bitmiş videoda yakaladı). Kısa parçayı önceki öbeğe geri yapıştır — bir-iki
    # karakterlik taşma, ortadan bölünmüş bir kelimeden iyidir.
    merged: list[str] = []
    for c in chunks:
        if (merged and len(c) <= _JA_TAIL_MAX
                and merged[-1][-1] not in _JA_BREAK_AFTER   # cümle sonu SERT sınır
                and len(merged[-1]) + len(c) <= _JA_LINE_MAX):
            merged[-1] += c
        else:
            merged.append(c)
    return merged


def split_words(text: str, lang: str | None = None) -> list[str]:
    """Metni hizalanabilir birimlere böler. Boşluklu dillerde ``text.split()``.

    ``lang`` verilmezse aktif dil bağlamından okunur (pipeline kanalın dilini kurar).
    """
    lg = lang if lang is not None else _LANG.get()
    if lg not in _NO_SPACE_LANGS:
        return text.split()
    out: list[str] = []
    for token in text.split():
        out.extend(_split_ja(token))
    return out


def locale_upper(s: str, lang: str = "tr") -> str:
    """Dile duyarlı büyük harf.

    Türkçe eşlemesini Almancaya uygulamak da en az onun kadar yanlıştır:
    'Bier Garten' → 'BİER GARTEN'. Büyütme dile özgüdür.
    """
    return turkish_upper(s) if lang == "tr" else s.upper()


def locale_fold(text: str, lang: str = "tr") -> str:
    """Eşleştirme için küçültme (kalıp denetimi, kelime karşılaştırması).

    Türkçe: ``"İ".lower()`` birleşik nokta üretir (i̇) ve kelimeyi eşleşmez kılar;
    harfleri elle eşliyoruz. Ama bu eşleme DİLE ÖZGÜ: Almancada 'I' harfinin küçüğü
    'ı' değil 'i'dir. Dile duyarsız hâli 'Ich'i 'ıch' yapıyordu ve r'\\bich\\b' asla
    eşleşmiyordu — denetçi çalışıyor görünüp sıfır şey buluyordu.
    """
    if lang == "tr":
        return text.replace("İ", "i").replace("I", "ı").lower()
    return text.casefold()


# TR'ye ÖZGÜ harfler: es/en/de/fr'de hiçbiri yok (ö/ü/ç Almanca ve Fransızcada
# da var, onlar sinyal değil).
_TR_IZ_HARF = "ığş"
# Fonksiyon kelimeleri — konu ne olursa olsun Türkçe metinde bulunurlar.
# BAŞKA DİLDE DE YAYGIN olanlar bilerek DIŞARIDA: de/da/o/en/son (es, pt, it),
# ne (fr), her (en). Onlarla kurulan bir liste İspanyolca haber başlıklarını
# "Türkçe" sayıyordu ("El Real Madrid… se aleja DE un fichaje").
_TR_IZ_KELIME = frozenset({
    "ve", "bir", "için", "ile", "bu", "şu", "ki", "ama", "çok", "daha",
    "sonra", "kadar", "gibi", "olarak", "oldu", "olan", "var", "yok",
    "dedi", "etti", "göre", "ise", "değil", "üzerinde", "arasında",
})


def turkce_gorunuyor_mu(metin: str) -> bool:
    """Metin Türkçe İZİ taşıyor mu — POZİTİF kanıt arar, boşta False döner.

    İki yerde kullanılıyor ve ikisinde de "şüphede sessiz kal" isteniyor:
      • RSS Havuzu (`feed_translate`) — yabancı kaynağı çeviriye yollamadan önce.
      • YouTube metadata (`youtube.metadata_writer`) — üretilen metne Türkçe
        SIZDI mı diye. Metadata istemi baştan sona Türkçe yazılmış olduğundan
        model ara sıra dili karıştırıyor: ölçüldü, İspanyolca bir kanalın
        başlığı "Real Madrid transfer planları ve Bernabéu'da yaşanan son
        gelişmeler" çıktı ve istemdeki DİL KİLİDİ talimatı tek başına yetmedi.

    Kanıt yoksa (boş metin, salt rakam, Latin dışı yazı) False: burada "bilmiyorum"
    ile "Türkçe değil" aynı kefeye konur, çünkü çağıranların ikisi de yalnız
    POZİTİF sinyalde harekete geçer.
    """
    kucuk = (metin or "").lower()
    if not kucuk.strip():
        return False
    if sum(kucuk.count(c) for c in _TR_IZ_HARF) >= 3:
        return True
    kelimeler = re.findall(r"[a-zçğıöşü]+", kucuk)
    if not kelimeler:
        return False
    isaret = sum(1 for k in kelimeler if k in _TR_IZ_KELIME)
    return (isaret / len(kelimeler)) >= 0.05
