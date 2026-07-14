"""Yorum yemi İKİLİ olmalı, abone isteği DEĞER/SERİ çerçeveli.

ARAŞTIRMA BULGULARI:

YORUM: açık uçlu sorular ("Ne düşünüyorsun?", "Hangisi seni en çok şaşırttı?")
yüksek eforlu → cevapsız kalır. Yanıt ALAN türler: İKİLİ/hangisi (tek harf yeter),
kişisel hatırlama ("kaç yaşında öğrendin?"), doğrulama ("bir ben miyim?"),
eksiği-bul. Soru VİDEODAKİ SPESİFİK BİR ANA bağlı olmalı — jenerik olamaz, o yüzden
kalıp cümle değil YÖNERGE veriyoruz ve cümleyi LLM içerikten yazıyor.

ABONE: "Daha fazlası için abone ol" ARAŞTIRMANIN ADIYLA ANDIĞI başarısız ifade —
izleyici bunu on bin kez duydu, beyni filtreliyor ("YouTube beyaz gürültüsü").
İşe yarayan çerçeveler: DEĞER-SPESİFİK (ne alacağını söyle), SERİ (dönüşü alışkanlık
yapar), CLIFFHANGER (aboneliği bir İSTEK değil TAKAS'a çevirir).
"""
from short_bot.lang_pack import CTA_MAX_CHARS, load_pack
from short_bot.reel_subscribe import build_subscribe_bits

TR = load_pack("tr")
CTA_TEXTS = TR.cta_texts
COMMENT_STYLES = TR.comment_styles


class _Reel:
    series_enabled = False
    series_title = ""
    cta_enabled = True
    cta_text_custom = ""
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


def test_cta_never_uses_the_dead_generic_phrase():
    """'Daha fazlası için abone ol' araştırmanın adıyla andığı başarısız ifade."""
    for t in CTA_TEXTS:
        low = t.lower()
        assert "daha fazlası için" not in low, f"ölü ifade havuzda: {t}"


def test_cta_names_the_value_or_the_series():
    """Her CTA ya NE ALACAĞINI söylemeli ya SERİ/süreklilik çerçevesi kurmalı."""
    for t in CTA_TEXTS:
        low = t.lower()
        assert ("her gün" in low or "yarın" in low or "her" in low
                or "seri" in low or "bölüm" in low or "sıradaki" in low), \
            f"CTA ne vaat ettiğini söylemiyor: {t}"


def test_cta_text_fits_the_frame():
    """Çip TEK SATIR ve kadraja SIĞMALI.

    GERÇEK HATA (short_id=751): "Bu seri devam ediyor — ABONE OL" 1080px'e sığmadı,
    sağdan kesildi ("...ABONE O"). Sarmaya izin vermek çözüm DEĞİL — iki satırlık
    çip altyazının üstüne biner ve payoff'u kapatır (araştırma: CTA payoff'u
    KAPATMAMALI). Doğru çözüm: metni KISA tut.
    """
    for t in CTA_TEXTS:
        assert len(t) <= CTA_MAX_CHARS, (
            f"çip kadraja sığmaz ({len(t)} > {CTA_MAX_CHARS} karakter): {t}")


def test_custom_cta_is_also_length_checked():
    """Kullanıcı kendi metnini yazarsa da kesilmemeli — uyar, kırp."""
    class _R(_Reel):
        cta_text_custom = "Bu çok çok çok uzun bir abone çağrısı metni ABONE OL"

    class _C:
        language = "tr"
        reel = _R()
    out = build_subscribe_bits(_C(), seed=1).cta_text
    assert len(out) <= CTA_MAX_CHARS


def test_cta_disabled_yields_nothing():
    class _R(_Reel):
        cta_enabled = False

    class _C:
        language = "tr"
        reel = _R()
    assert build_subscribe_bits(_C(), seed=1).cta_text == ""
