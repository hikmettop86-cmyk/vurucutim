from short_bot.config import ReelConfig
from short_bot.reel_subscribe import (CTA_TEXTS, COMMENT_STYLES,
                                      SubscribeBits, build_subscribe_bits)


class _Ch:
    def __init__(self, **reel_kw):
        self.reel = ReelConfig(enabled=True, voice_id="v", **reel_kw)


def test_same_seed_same_bits():
    ch = _Ch(cta_enabled=True, comment_question=True, series_enabled=True, series_title="Tuhaf Gerçekler")
    assert build_subscribe_bits(ch, 5) == build_subscribe_bits(ch, 5)


def test_all_off_empty():
    ch = _Ch(cta_enabled=False, comment_question=False, series_enabled=False)
    b = build_subscribe_bits(ch, 3)
    assert b == SubscribeBits("", "", "")


def test_comment_from_pool_when_on():
    ch = _Ch(comment_question=True, cta_enabled=False, series_enabled=False)
    lines = {build_subscribe_bits(ch, s).comment_line for s in range(len(COMMENT_STYLES) * 2)}
    assert len(lines) >= 2
    assert build_subscribe_bits(ch, 0).comment_line in COMMENT_STYLES


def test_cta_from_pool_when_on():
    ch = _Ch(cta_enabled=True, comment_question=False, series_enabled=False)
    assert build_subscribe_bits(ch, 0).cta_text in CTA_TEXTS


def test_cta_custom_overrides_pool():
    ch = _Ch(cta_enabled=True, cta_text_custom="TAKİP ET →", comment_question=False, series_enabled=False)
    assert all(build_subscribe_bits(ch, s).cta_text == "TAKİP ET →" for s in range(4))


def test_series_directive_uses_title():
    ch = _Ch(series_enabled=True, series_title="Doğanın Sırları", cta_enabled=False, comment_question=False)
    d = build_subscribe_bits(ch, 1).series_directive
    assert "Doğanın Sırları" in d


def test_series_off_empty_directive():
    ch = _Ch(series_enabled=False, cta_enabled=False, comment_question=False)
    assert build_subscribe_bits(ch, 1).series_directive == ""


# --- SERİ MODU (EpisodePlan verilince) --------------------------------------

def _ep(no=47, arc=1, gelen=""):
    from short_bot.reel_series import EpisodePlan
    return EpisodePlan(episode_no=no, arc_pos=arc, continue_from=gelen)


def test_seride_cta_bir_TAKASA_donusur():
    """'Her gün yeni — ABONE OL' bir RİCA; '#48 yarın — ABONE OL' bir TAKAS.

    İkincisi somut bir şey vaat eder ve ne zaman geleceğini söyler.
    """
    ch = _Ch(cta_enabled=True, series_enabled=True, series_title="Bilinmeyen Tarih")
    b = build_subscribe_bits(ch, 3, episode=_ep(47))
    assert b.cta_text == "#48 yarın — ABONE OL"
    assert b.cta_text not in CTA_TEXTS, "seride jenerik havuza düşmemeli"


def test_seride_rozet_uretilir():
    ch = _Ch(cta_enabled=True, series_enabled=True, series_title="Bilinmeyen Tarih")
    assert build_subscribe_bits(ch, 3, episode=_ep(47)).badge == "BİLİNMEYEN TARİH #47"


def test_seride_YORUM_SORUSU_kapanir():
    """Belge §3.1: 'son 5 saniyede CTA yığılması — üç istek = sıfır istek.'

    Seride izleyiciden istediğimiz TEK şey net: sonraki bölüm için abone olmak.
    Yorum sorusu onunla dikkat için yarışır ve ikisi de kaybeder.
    """
    ch = _Ch(cta_enabled=True, comment_question=True, series_enabled=True,
             series_title="X")
    assert build_subscribe_bits(ch, 3, episode=_ep()).comment_line == ""
    # Seri YOKKEN yorum sorusu yerinde durmalı
    assert build_subscribe_bits(ch, 3).comment_line != ""


def test_seride_yonerge_odenecek_sozu_tasir():
    ch = _Ch(series_enabled=True, series_title="Bilinmeyen Tarih", cta_enabled=False)
    d = build_subscribe_bits(ch, 1, episode=_ep(48, 2, "O ışığı üreten şey ne?")).series_directive
    assert "O ışığı üreten şey ne?" in d
    assert "48" in d and "49" in d


def test_ozel_cta_takasi_da_ezer():
    """Kullanıcı sözü son sözdür."""
    ch = _Ch(cta_enabled=True, cta_text_custom="TAKİP ET →", series_enabled=True,
             series_title="X")
    assert build_subscribe_bits(ch, 1, episode=_ep(47)).cta_text == "TAKİP ET →"


def test_bolum_plani_yoksa_ESKI_davranis():
    """Geriye uyum: episode verilmezse seri açık olsa bile eski teaser yönergesi."""
    ch = _Ch(cta_enabled=True, comment_question=True, series_enabled=True,
             series_title="Doğanın Sırları")
    b = build_subscribe_bits(ch, 1)
    assert b.badge == ""
    assert b.cta_text in CTA_TEXTS
    assert b.comment_line != ""
    assert "Doğanın Sırları" in b.series_directive
