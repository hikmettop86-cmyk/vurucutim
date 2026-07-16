from short_bot.config import ReelConfig
from short_bot.lang_pack import load_pack
from short_bot.reel_subscribe import SubscribeBits, build_subscribe_bits

# Metinler artık DİL PAKETİNDE (tr.json = eski sabitlerin birebir kopyası;
# bkz. test_lang_pack_tr_golden.py). Beklentiler DEĞİŞMEDİ.
# NOT: Beğeni/abone çipleri 2026-07-16'da KALDIRILDI (kullanıcı kararı) —
# SubscribeBits artık cta_text taşımaz; yorum sorusu + seri yönergesi + rozet kaldı.
TR = load_pack("tr")
COMMENT_STYLES = TR.comment_styles


class _Ch:
    language = "tr"

    def __init__(self, **reel_kw):
        self.reel = ReelConfig(enabled=True, voice_id="v", **reel_kw)


def test_same_seed_same_bits():
    ch = _Ch(comment_question=True, series_enabled=True, series_title="Tuhaf Gerçekler")
    assert build_subscribe_bits(ch, 5) == build_subscribe_bits(ch, 5)


def test_all_off_empty():
    ch = _Ch(comment_question=False, series_enabled=False)
    b = build_subscribe_bits(ch, 3)
    assert b == SubscribeBits("", "", "")


def test_comment_from_pool_when_on():
    ch = _Ch(comment_question=True, series_enabled=False)
    lines = {build_subscribe_bits(ch, s).comment_line for s in range(len(COMMENT_STYLES) * 2)}
    assert len(lines) >= 2
    assert build_subscribe_bits(ch, 0).comment_line in COMMENT_STYLES


def test_cta_alani_tamamen_kalkti():
    # Kaldırma kalıcı: SubscribeBits'e cta_text geri eklenirse bu test kırılsın.
    assert not hasattr(build_subscribe_bits(_Ch(), 1), "cta_text")


def test_series_directive_uses_title():
    ch = _Ch(series_enabled=True, series_title="Doğanın Sırları", comment_question=False)
    d = build_subscribe_bits(ch, 1).series_directive
    assert "Doğanın Sırları" in d


def test_series_off_empty_directive():
    ch = _Ch(series_enabled=False, comment_question=False)
    assert build_subscribe_bits(ch, 1).series_directive == ""


# --- SERİ MODU (EpisodePlan verilince) --------------------------------------

def _ep(no=47, arc=1, gelen=""):
    from short_bot.reel_series import EpisodePlan
    return EpisodePlan(episode_no=no, arc_pos=arc, continue_from=gelen)


def test_seride_rozet_uretilir():
    ch = _Ch(series_enabled=True, series_title="Bilinmeyen Tarih")
    assert build_subscribe_bits(ch, 3, episode=_ep(47)).badge == "BİLİNMEYEN TARİH #47"


def test_seride_YORUM_SORUSU_kapanir():
    """Belge §3.1: 'son 5 saniyede istek yığılması — üç istek = sıfır istek.'

    Seride izleyicinin dikkati TEK şeyde kalmalı: sonraki bölümün merakı.
    Yorum sorusu onunla dikkat için yarışır ve ikisi de kaybeder.
    """
    ch = _Ch(comment_question=True, series_enabled=True, series_title="X")
    assert build_subscribe_bits(ch, 3, episode=_ep()).comment_line == ""
    # Seri YOKKEN yorum sorusu yerinde durmalı
    assert build_subscribe_bits(ch, 3).comment_line != ""


def test_seride_yonerge_odenecek_sozu_tasir():
    ch = _Ch(series_enabled=True, series_title="Bilinmeyen Tarih")
    d = build_subscribe_bits(ch, 1, episode=_ep(48, 2, "O ışığı üreten şey ne?")).series_directive
    assert "O ışığı üreten şey ne?" in d
    assert "48" in d and "49" in d


def test_bolum_plani_yoksa_ESKI_davranis():
    """Geriye uyum: episode verilmezse seri açık olsa bile eski teaser yönergesi."""
    ch = _Ch(comment_question=True, series_enabled=True,
             series_title="Doğanın Sırları")
    b = build_subscribe_bits(ch, 1)
    assert b.badge == ""
    assert b.comment_line != ""
    assert "Doğanın Sırları" in b.series_directive
