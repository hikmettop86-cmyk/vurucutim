"""Yorum yemi İKİLİ olmalı — açık uçlu soru cevapsız kalır.

ARAŞTIRMA BULGULARI:

YORUM: açık uçlu sorular ("Ne düşünüyorsun?", "Hangisi seni en çok şaşırttı?")
yüksek eforlu → cevapsız kalır. Yanıt ALAN türler: İKİLİ/hangisi (tek harf yeter),
kişisel hatırlama ("kaç yaşında öğrendin?"), doğrulama ("bir ben miyim?"),
eksiği-bul. Soru VİDEODAKİ SPESİFİK BİR ANA bağlı olmalı — jenerik olamaz, o yüzden
kalıp cümle değil YÖNERGE veriyoruz ve cümleyi LLM içerikten yazıyor.

NOT (2026-07-16, kullanıcı kararı): beğeni/abone çipleri ve CTA havuzu tamamen
KALDIRILDI — "kullanıcı gerçekten içinden gelirse abone veya beğenme yapar".
Bu dosyada yalnız YORUM yemi testleri kaldı.
"""
from short_bot.lang_pack import load_pack
from short_bot.reel_subscribe import build_subscribe_bits

TR = load_pack("tr")
COMMENT_STYLES = TR.comment_styles


class _Reel:
    series_enabled = False
    series_title = ""
    comment_question = True


class _Ch:
    language = "tr"
    reel = _Reel()


def test_comment_directive_demands_a_binary_or_low_effort_question():
    """Yönerge, LLM'e AÇIK UÇLU değil DÜŞÜK EFORLU soru yazdırmalı."""
    bits = build_subscribe_bits(_Ch(), seed=1)
    assert bits.comment_line, "yorum yönergesi üretilmedi"
    low = bits.comment_line.lower()
    assert "ikili" in low or "tek harf" in low or "tek kelime" in low or \
        "kaç yaş" in low or "bir ben mi" in low or "eksi" in low, \
        f"yönerge düşük eforlu soru istemiyor: {bits.comment_line}"


def test_no_open_ended_comment_question_survives():
    """'Ne düşünüyorsun' / 'Hangisi seni en çok şaşırttı' YASAK — cevapsız kalır."""
    for style in COMMENT_STYLES:
        low = style.lower()
        assert "ne düşünüyorsun" not in low
        assert "en çok şaşırttı" not in low
        assert "yorumlara yaz" not in low or "tek" in low   # çıplak "yorumlara yaz" yok


def test_comment_styles_rotate():
    """Aynı yönerge her videoda çıkmamalı (şablon parmak izi + 'inauthentic' riski)."""
    seen = {build_subscribe_bits(_Ch(), seed=s).comment_line for s in range(12)}
    assert len(seen) > 1
