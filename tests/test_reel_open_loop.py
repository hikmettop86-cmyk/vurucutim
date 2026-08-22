"""AÇIK KAPI: vaat, abone çipi ekrana gelmeden ÖNCE konuşulmuş olmalı.

Abone çipi tepeden ~1.3sn sonra beliriyor. Vaat o ana kadar söylenmemişse izleyici
neyin karşılığında abone olacağını BİLMEZ ve çip "daha fazlası için abone ol"
beyaz gürültüsüne düşer — yani serinin bütün mekanizması ölür.

Prompt bunu istiyor. Ama LLM'e güvenmiyoruz: ÖLÇÜYORUZ (close_echoes_hook ile
aynı gerekçe, aynı desen).
"""
import pytest

from short_bot.reel_models import (OPEN_LOOP_MAX_CHARS, ReelBeat, ReelNarration)
from short_bot.reel_narration import fit_word_budget


def _narr(open_loop="", post_peak="Ama o isik baligin kendi degil, onu ureten sey bambaska."):
    return ReelNarration(
        hook="Disi fener baligi erkegi eritir.",
        beats=[
            ReelBeat(text="Erkek fener baligi disiden yuz kat kucuktur.",
                     visual_query="anglerfish", keyword="YUZ KAT"),
            ReelBeat(text="Erkek disiye yapisir ve dokulari birlesir.",
                     visual_query="anglerfish pair", keyword="BIRLESME"),
            ReelBeat(text=post_peak, visual_query="deep sea light", keyword="ISIK"),
        ],
        close="Iste bu yuzden disi fener baligi erkegi eritir.",
        mood="neutral", peak_beat=1, open_loop=open_loop)


def test_vaat_tepe_sonrasi_beatte_geciyorsa_GECER():
    n = _narr(open_loop="O isigi ureten sey balik degil, baska bir canli.")
    assert n.open_loop_spoken()


def test_vaat_hicbir_yerde_gecmiyorsa_KALIR():
    """LLM open_loop alanını doldurmuş ama metne DOKUMAMIŞ — en sinsi hâl.

    Alan dolu olduğu için her şey yolunda görünür; oysa izleyici vaadi hiç duymaz.
    """
    n = _narr(open_loop="Denizin dibindeki basinc insani aninda oldurur.",
              post_peak="Bu birlesme kalici olur ve erkek asla ayrilamaz.")
    assert not n.open_loop_spoken()


def test_vaat_TEPEDEN_ONCE_geciyorsa_SAYILMAZ():
    """Yer önemli: vaat tepeden ÖNCE söylenirse abone çipi ateşlendiğinde çoktan
    unutulmuştur — üstelik tepe henüz gelmediği için ödenmiş bir şey de yoktur."""
    n = ReelNarration(
        hook="Disi fener baligi erkegi eritir.",
        beats=[
            # vaat BURADA (tepeden ÖNCE) — sayılmamalı
            ReelBeat(text="O isigi ureten sey bambaska bir canli, ama once sunu bil.",
                     visual_query="anglerfish", keyword="ISIK"),
            ReelBeat(text="Erkek disiye yapisir ve dokulari birlesir.",
                     visual_query="anglerfish pair", keyword="BIRLESME"),
            ReelBeat(text="Bu birlesme kalicidir.",
                     visual_query="deep sea", keyword="KALICI"),
        ],
        close="Iste bu yuzden disi fener baligi erkegi eritir.",
        mood="neutral", peak_beat=1,
        open_loop="O isigi ureten sey bambaska bir canli.")
    assert not n.open_loop_spoken()


def test_kapi_yoksa_konusulmus_da_sayilmaz():
    assert not _narr(open_loop="").open_loop_spoken()


def test_tek_ortak_kelime_YETMEZ():
    """Tesadüfi bir kelime örtüşmesi 'vaat dokundu' anlamına gelmez."""
    n = _narr(open_loop="Balina sarkilari kilometrelerce duyulur.",
              post_peak="Bu birlesme kalicidir ve erkek asla ayrilamaz.")
    assert not n.open_loop_spoken()


def test_uzun_kapi_kirpilir_uretim_dusmez():
    uzun = "x" * (OPEN_LOOP_MAX_CHARS + 60)
    n = _narr(open_loop=uzun)
    assert len(n.open_loop) <= OPEN_LOOP_MAX_CHARS


# --- BÜTÇE KISALTMASI VAADİ SİLMEMELİ --------------------------------------

def test_butce_kisaltmasi_TEPE_SONRASI_beati_ATMAZ():
    """Vaat cümlesi tepe-sonrası beat'te yaşıyor. Kısaltma onu atarsa takas çöker.

    fit_word_budget SONDAN beat atıyor — ve tepe-sonrası beat çoğu zaman SON beat.
    """
    n = ReelNarration(
        hook="Disi fener baligi erkegi eritir cunku derinlerde esini bulmak zordur.",
        beats=[
            ReelBeat(text="Erkek fener baligi disiden tam yuz kat daha kucuktur ve "
                          "kendi basina avlanamaz, sindirim sistemi bile korelmistir.",
                     visual_query="anglerfish", keyword="YUZ KAT"),
            ReelBeat(text="Erkek disiye disleriyle yapisir, sonra dokulari birlesir ve "
                          "kan dolasimlari ortak hale gelir, artik tek bir canlidirlar.",
                     visual_query="anglerfish pair", keyword="BIRLESME"),
            ReelBeat(text="Ama o isigi ureten sey baligin kendi degil, tamamen baska "
                          "bir canli ve onu bir sonraki bolumde anlatiyorum.",
                     visual_query="deep sea light", keyword="ISIK"),
            ReelBeat(text="Bu arada disi omru boyunca alti erkegi birden tasiyabilir.",
                     visual_query="anglerfish many", keyword="ALTI ERKEK"),
        ],
        close="Iste bu yuzden disi fener baligi erkegi eritir.",
        mood="neutral", peak_beat=1,
        open_loop="O isigi ureten sey baligin kendi degil, baska bir canli.")
    assert n.open_loop_spoken()
    kisa = fit_word_budget(n, lo_w=10, hi_w=40)   # sert bütçe → beat atmak ZORUNDA
    assert len(kisa.beats) < len(n.beats), "bütçe testi beat attırmadı, senaryo boşa çıktı"
    assert kisa.open_loop_spoken(), (
        "kısaltma vaadi taşıyan beat'i attı → abone çipi söylenmemiş bir sözün "
        "üstüne düşecek")


def test_kapi_yokken_kisaltma_eski_davranisini_surdurur():
    n = _narr(open_loop="")
    kisa = fit_word_budget(n, lo_w=5, hi_w=8)
    # MIN_BEATS=3 altına inilmez → değişmeden döner
    assert len(kisa.beats) == 3

