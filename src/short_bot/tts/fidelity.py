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


def _fold(text: str) -> str:
    """Türkçe-güvenli küçültme. ``"İ".lower()`` birleşik nokta üretir (i̇), bu da
    kelimeleri eşleşmez kılar; harfleri önce elle eşliyoruz."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def normalize_tokens(text: str) -> list[str]:
    """Karşılaştırılabilir kelime dizisi: noktalama, kesme işareti ve sayı yazımı
    farkları elenir."""
    out: list[str] = []
    for raw in _fold(text).split():
        # Kesme işareti: senaryo "Amerika'nın", whisper "Amerika 'nın" verebilir.
        w = re.sub(r"[^\w]", "", unicodedata.normalize("NFC", raw), flags=re.UNICODE)
        if not w:
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


def worst_drop(script: str, heard: str) -> Drop:
    """Seslendirilmeyen en uzun bitişik kelime öbeği.

    Kayıp, ``delete`` kadar ``replace`` olarak da görünür: TTS öbeği atlayınca
    whisper sınırdaki kelimeleri birleştirip tek bir dolgu kelimesi duyabiliyor
    (ölçülen vaka: 6 kelime yerine "ve"). Bu yüzden ölçüt NET kayıp — senaryo
    tarafındaki kelime sayısı eksi duyulan taraftaki.
    """
    s, h = normalize_tokens(script), normalize_tokens(heard)
    worst = Drop(0, "")
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=s, b=h, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        lost = (i2 - i1) - (j2 - j1)
        if lost > worst.count:
            worst = Drop(lost, " ".join(s[i1:i2]))
    return worst
