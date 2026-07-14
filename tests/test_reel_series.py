"""Seri / cliffhanger mimarisi: abonelik bir RİCA değil TAKAS olmalı.

Kritik davranış: video kendi tepesini ÖDER (yoksa beğeni gelmez — beğeni bir karar
değil duygusal boşalmadır) ama kapanmaz: tepenin açığa çıkardığı yeni ve SPESİFİK
bir kapı bırakır ve o kapı bir sonraki BÖLÜMÜN KONU TOHUMUDUR.
"""
import pytest

from short_bot.reel_series import (BADGE_MAX_CHARS, DEFAULT_ARC_MAX, EpisodePlan,
                                   episode_badge, plan_episode, series_directive,
                                   trade_cta)

# Metinler artık DİL PAKETİNDE (tr.json = eski sabitlerin birebir kopyası;
# bkz. test_lang_pack_tr_golden.py). Beklentiler DEĞİŞMEDİ.
from short_bot.lang_pack import load_pack
TR = load_pack("tr")



def test_ilk_bolum_bir_numaradan_baslar():
    p = plan_episode(None)
    assert p.episode_no == 1 and p.arc_pos == 1
    assert p.continue_from == ""
    assert p.is_new_arc


def test_acik_kapi_varsa_ark_surer_ve_kapi_TASINIR():
    """ARKIN TA KENDİSİ: önceki bölümün açtığı kapı, bu bölümün konusu olur."""
    son = {"episode_no": 46, "arc_pos": 1,
           "open_loop": "O ışık balığın kendi değil — onu üreten şey ne?"}
    p = plan_episode(son, arc_max=3)
    assert p.episode_no == 47
    assert p.arc_pos == 2
    assert p.continue_from == son["open_loop"]
    assert not p.is_new_arc


def test_ark_uzunlugu_dolunca_zincir_KESILIR():
    """Zincir sonsuza kadar sürerse konu kanalın nişinden sürüklenir.

    Her bölüm bir öncekinin kapısından doğuyor; sapma birikimlidir. Ark dolunca
    taze konu bankadan gelmeli (continue_from boş → çağıran normal konu seçer).
    """
    son = {"episode_no": 49, "arc_pos": 3, "open_loop": "Peki ya derinlik?"}
    p = plan_episode(son, arc_max=3)
    assert p.episode_no == 50, "numara YİNE de artmalı (kanal kimliği sürüyor)"
    assert p.arc_pos == 1, "yeni ark"
    assert p.continue_from == "", "zincir kesildi → bankadan taze konu"


def test_kapi_acilmadiysa_ark_surmez():
    """LLM open_loop yazmadıysa zincirleyecek bir şey yok."""
    son = {"episode_no": 12, "arc_pos": 1, "open_loop": ""}
    p = plan_episode(son, arc_max=3)
    assert p.episode_no == 13 and p.arc_pos == 1 and p.continue_from == ""


def test_bolum_numarasi_ark_kesilse_de_artmaya_devam_eder():
    """Numara KANAL ömrüne aittir, arka değil — feed kimliği odur."""
    no = 0
    son = None
    for _ in range(7):
        p = plan_episode(son, arc_max=2)
        assert p.episode_no == no + 1
        no = p.episode_no
        son = {"episode_no": p.episode_no, "arc_pos": p.arc_pos,
               "open_loop": "bir kapı"}
    assert no == 7


# --- ROZET ----------------------------------------------------------------

def test_rozet_baslik_ve_numara_tasir():
    assert episode_badge("Bilinmeyen Tarih", 47, pack=TR) == "BİLİNMEYEN TARİH #47"


def test_uzun_baslikta_NUMARA_asla_atilmaz():
    """Rozetin İŞLEVİ numaradır: seri gerçekten var mı sorusunu o yanıtlar."""
    r = episode_badge("Bilim Tarihinin Şok Anları ve Daha Fazlası", 128, pack=TR)
    assert len(r) <= BADGE_MAX_CHARS
    assert r.endswith("#128"), f"numara kırpılmış: {r!r}"


def test_baslik_yoksa_yalniz_numara():
    assert episode_badge("", 9, pack=TR) == "#9"
    assert episode_badge("   ", 9, pack=TR) == "#9"


# --- TAKAS CTA ------------------------------------------------------------

def test_cta_bir_sonraki_bolumu_ADIYLA_vaat_eder():
    """'Daha fazlası için abone ol' beyaz gürültüdür — numara veren istek somuttur."""
    from short_bot.reel_subscribe import CTA_MAX_CHARS
    c = trade_cta(48, pack=TR)
    assert "48" in c and "ABONE" in c
    assert len(c) <= CTA_MAX_CHARS, f"çip kadraja sığmaz ({len(c)} karakter): {c!r}"
    assert "daha fazla" not in c.lower()


# --- YÖNERGE --------------------------------------------------------------

def test_yonerge_odenmis_tepe_ve_yeni_kapi_ister():
    d = series_directive(EpisodePlan(episode_no=47, arc_pos=1), "Bilinmeyen Tarih", pack=TR)
    assert "47" in d and "48" in d
    assert "open_loop" in d
    assert "TEPEDEN SONRAKİ BEAT" in d, "cliffhanger'ın YERİ söylenmeli"


def test_yonerge_ALANI_ve_KONUSULANI_ayirir():
    """Gerçek koşuda LLM ikisini karıştırdı: open_loop alanına '2. bölümde
    açıklıyoruz' yazdı — oysa o alan bir sonraki bölümün ÜRETİM KONUSU."""
    d = series_directive(EpisodePlan(episode_no=47, arc_pos=1), "Bilinmeyen Tarih", pack=TR)
    assert "konuşulmaz" in d.lower()
    assert "üretim konusu" in d.lower()


def test_yonerge_ark_surerken_ONCEKI_SOZU_odetir():
    """İzleyici o cevap için abone oldu. Başka şey anlatmak takası bozar."""
    p = EpisodePlan(episode_no=48, arc_pos=2,
                    continue_from="O ışığı üreten şey ne?")
    d = series_directive(p, "Bilinmeyen Tarih", pack=TR)
    assert "O ışığı üreten şey ne?" in d
    assert "TEPESİ" in d, "sözü ÖDEYECEK yer tepe olmalı"


def test_yonerge_yeni_arkta_odenecek_soz_ANMAZ():
    d = series_directive(EpisodePlan(episode_no=1, arc_pos=1), "Bilinmeyen Tarih", pack=TR)
    assert "ÖDÜYOR" not in d
    assert "open_loop" in d, "yeni arkta bile kapı açılmalı"


def test_seri_kapaliysa_yonerge_bos():
    d = series_directive(EpisodePlan(episode_no=5, arc_pos=1, enabled=False), "X", pack=TR)
    assert d == ""


def test_varsayilan_ark_makul():
    # Çok kısa: ark hissi oluşmaz. Çok uzun: konu nişten sürüklenir.
    assert 2 <= DEFAULT_ARC_MAX <= 5
