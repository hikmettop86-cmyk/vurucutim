"""Strip foreign Latin diacritics while keeping Turkish letters intact.

Sonnet occasionally leaks Spanish/Portuguese/French accents into Turkish
output ('CANLÍ' instead of 'CANLI', 'Niño' would survive, etc.). We strip
those at the model boundary so renders never display non-Turkish glyphs.
"""
import unicodedata

# Letters that ARE part of the Turkish alphabet — never decompose these.
_TURKISH_KEEP = set("ÇĞİıÖŞÜçğöşü")


def strip_non_turkish_diacritics(s: str) -> str:
    """Decompose any non-ASCII, non-Turkish letter and drop combining marks.

    Examples:
        'CANLÍ'    → 'CANLI'        (Í has acute → drop accent)
        'İPLER'    → 'İPLER'        (İ is Turkish → kept)
        'Çocuklar' → 'Çocuklar'     (Ç is Turkish → kept)
        'Niño'     → 'Nino'         (ñ has tilde → drop)
        'café'     → 'cafe'         (é has acute → drop)
    """
    out = []
    for ch in s:
        if ord(ch) < 128 or ch in _TURKISH_KEEP:
            out.append(ch)
            continue
        decomposed = unicodedata.normalize("NFKD", ch)
        base = "".join(c for c in decomposed if not unicodedata.combining(c))
        out.append(base if base else "")
    return "".join(out)


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
