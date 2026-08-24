"""TTS sadakat denetimi: ses gerçekten senaryoyu okudu mu?

NEDEN VAR: ai33 arada bir metnin bir parçasını SESSİZCE düşürüyor. Hata dönmüyor,
ses dosyası geçerli, süresi bile normal — sadece birkaç kelime hiç okunmamış.
Gerçek vaka (short 757): hook'un sonu + ilk beat'in başı ("sessiz bir katildir.
Güney Amerika'nın zirvesinde") seslendirilmedi; altyazılar o kelimeleri yine de
gösterdiği için video ikinci sahnede ileri zıplamış gibi göründü. Aynı metni üç
kez daha gönderdik, üçünde de eksiksiz okundu — yani arıza ARALIKLI.

Bunu kaynağında düzeltemeyiz, ama BEDAVA yakalayabiliriz: whisper zaten altyazı
hizalaması için sesi çözümlüyor. Duyulanı senaryoyla karşılaştırmak yeter.

Ayırt edici işaret ARD ARDA kayıptır. Normal ASR gürültüsü tek tek kelimeleri
ıskalar ("And Kondoru" → "Ant kondoru"); TTS'in düşürdüğü parça ise bitişik bir
kelime öbeğidir. Bu yüzden eşik toplam kayıpta değil, EN UZUN BİTİŞİK KAYIPTA.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from short_bot.locale import CJK_LANGUAGES
from short_bot.text_normalize import current_language, locale_fold, split_words

# Bitişik kayıp bu uzunluğa ulaşırsa TTS parça düşürmüştür. 3: tek kelimelik ASR
# ıskaları (ve bir-iki kelimelik yanlış duyumlar) altında kalsın, gerçek öbek
# kaybı (ölçülen vaka: 5-6 kelime) üstünde kalsın.
MAX_DROPPED_RUN = 3

# Sayılar iki tarafta farklı yazılıyor: senaryo "altı", whisper "6". Karşılaştırma
# için İKİ TARAFI DA aynı biçime indirger — "bir" belirteci de "1" olur ama iki
# tarafta da olduğu için eşleşme bozulmaz.
_NUMBERS = {
    "sıfır": "0", "bir": "1", "iki": "2", "üç": "3", "dört": "4", "beş": "5",
    "altı": "6", "yedi": "7", "sekiz": "8", "dokuz": "9", "on": "10",
    "yirmi": "20", "otuz": "30", "kırk": "40", "elli": "50", "altmış": "60",
    "yetmiş": "70", "seksen": "80", "doksan": "90", "yüz": "100", "bin": "1000",
}


def _fold(text: str, lang: str | None = None) -> str:
    """Dile duyarlı küçültme (bkz. text_normalize.locale_fold)."""
    return locale_fold(text, lang or current_language())


def normalize_tokens(text: str, lang: str | None = None) -> list[str]:
    """Karşılaştırılabilir kelime dizisi: noktalama, kesme işareti ve sayı yazımı
    farkları elenir.

    DİL ŞART. Türkçe eşlemesi 'I' → 'ı' yapıyor. Almanca senaryoda büyük 'Ich',
    whisper dökümünde küçük 'ich' geldiğinde 'ıch' ≠ 'ich' olur ve sadakat denetimi
    OLMAYAN bir kayıp bildirir. Almanca'da 'Ich/In/Ist/Immer' çok sık.

    ``lang`` verilmezse aktif dil bağlamından okunur (run_pipeline kanalın dilini
    kurar). Bu, altyazı hizalama zincirinin (caption_align → reel_models → tts.align)
    dili elden ele taşımasını gereksiz kılıyor — ve o zincirde biri unutulursa hata
    SESSİZ olurdu.
    """
    lg = lang or current_language()
    cjk = lg in CJK_LANGUAGES
    out: list[str] = []
    # split() DEĞİL: Japoncada senaryo tarafı 1 token, whisper tarafı 20 token olur
    # ve sadakat denetimi OLMAYAN bir kayıp bildirip TTS'i boşuna iki kez yeniler.
    for raw in split_words(_fold(text, lg), lg):
        # Kesme işareti: senaryo "Amerika'nın", whisper "Amerika 'nın" verebilir.
        w = re.sub(r"[^\w]", "", unicodedata.normalize("NFC", raw), flags=re.UNICODE)
        if not w:
            continue
        if cjk:
            # CJK'de ÖLÇÜT KARAKTER. İki taraf farklı tanelikte gelir ve bu KAÇINILMAZ:
            # senaryoyu biz altyazı öbeklerine bölüyoruz ('ずぶ濡れの'), whisper ise
            # karakter karakter döküyor ('ず ぶ 濡 れ の'). Öbek-öbek karşılaştırmak
            # ölçüldü: TTS metnin TAMAMINI okuduğu hâlde '9 kelime okunmadı' dedi ve
            # sesi iki kez boşuna ürettirdi — üstelik GERÇEK kaybı da kaçırıyordu.
            # Karakter, iki tarafın da üzerinde anlaştığı tek birim.
            out.extend(w)
            continue
        out.append(_NUMBERS.get(w, w))
    return out


@dataclass(frozen=True)
class Drop:
    """Senaryodan düşen en uzun bitişik öbek."""

    count: int
    phrase: str

    @property
    def ok(self) -> bool:
        return self.count < MAX_DROPPED_RUN


def worst_drop(script: str, heard: str, lang: str | None = None) -> Drop:
    """Seslendirilmeyen en uzun bitişik kelime öbeği.

    Kayıp, ``delete`` kadar ``replace`` olarak da görünür: TTS öbeği atlayınca
    whisper sınırdaki kelimeleri birleştirip tek bir dolgu kelimesi duyabiliyor
    (ölçülen vaka: 6 kelime yerine "ve"). Bu yüzden ölçüt NET kayıp — senaryo
    tarafındaki kelime sayısı eksi duyulan taraftaki.
    """
    s, h = normalize_tokens(script, lang), normalize_tokens(heard, lang)
    worst = Drop(0, "")
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=s, b=h, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        lost = (i2 - i1) - (j2 - j1)
        if lost > worst.count:
            worst = Drop(lost, " ".join(s[i1:i2]))
    return worst
