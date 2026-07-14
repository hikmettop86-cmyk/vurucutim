"""ALTIN TEST — regresyon kalkanı.

tr.json bugünkü Türkçe sabitlerin BİREBİR kopyası olmalı. Bu test onu kanıtlar:
paketten okunan her değer, koddaki sabitle karakter karakter aynı.

SERİ YÖNERGELERİ özel: tests/golden/tr_series_directives.json dosyası, ESKİ
series_directive() fonksiyonu hâlâ ayaktayken üretildi (7 dalın hepsi taranarak).
Altın dosya sonradan üretilseydi test totolojiye dönerdi ("yeni kod yeni kodla aynı")
ve hiçbir şey kanıtlamazdı.

BU TEST KIRILIRSA tr.json yanlış çıkarılmıştır ve Türkçe kanalların çıktısı DEĞİŞİR.
Testi zayıflatarak geçirme — tr.json'u düzelt.
"""
import json
import re
from pathlib import Path

from short_bot.lang_pack import load_pack, validate_pack
from short_bot.text_normalize import locale_fold

PACK = load_pack("tr")
ALTIN = json.loads(
    (Path(__file__).parent / "golden" / "tr_series_directives.json")
    .read_text(encoding="utf-8"))


def test_tr_paketi_GECERLI():
    assert validate_pack(PACK) == []


# --- EKRANA BASILAN --------------------------------------------------------

def test_cta_metinleri_BIREBIR():
    assert PACK.cta_texts == [
        "Her gün yeni — ABONE OL",
        "Yarın devamı — ABONE OL",
        "Seri sürüyor — ABONE OL",
        "Devamı yarın — ABONE OL",
    ]


def test_trade_cta_BIREBIR():
    assert PACK.trade_cta.format(no=48) == "#48 yarın — ABONE OL"


def test_varsayilan_seri_basligi():
    assert PACK.default_series_title == "İlginç Bilgiler"


# --- LLM YÖNERGELERİ -------------------------------------------------------

def test_baglac_yonergeleri_KAYNAKLA_ayni():
    from short_bot.reel_phrases import CONNECTIVE_STYLES
    assert PACK.connective_styles == list(CONNECTIVE_STYLES)
    assert len(PACK.connective_styles) == 8


def test_yorum_yonergeleri_KAYNAKLA_ayni():
    from short_bot.reel_subscribe import COMMENT_STYLES
    assert PACK.comment_styles == list(COMMENT_STYLES)
    assert len(PACK.comment_styles) == 4


# --- DENETÇİ ---------------------------------------------------------------

def test_asinmis_kaliplar_KAYNAKLA_ayni():
    from short_bot.reel_phrases import OVERUSED
    assert PACK.overused == list(OVERUSED)


def test_kalip_orintuleri_KAYNAKLA_ayni():
    from short_bot.reel_phrases import OVERUSED_PATTERNS
    paket = [(op.label, op.pattern) for op in PACK.overused_patterns]
    assert paket == list(OVERUSED_PATTERNS)


def test_kalip_orintuleri_GERCEK_KACAGI_hala_yakalar():
    """Bölüm #2'de yaşanan GERÇEK kaçak: 'bunu biliyor muydunuz' dizgesi yasaklıydı
    ama LLM '...sahip olduğunu biliyor muydunuz?' yazıp DENETİMDEN GEÇTİ. Örüntü
    katmanı bunun için var."""
    metin = locale_fold("Kalbin kendi elektriğini ürettiğini biliyor muydunuz", "tr")
    assert any(re.search(op.pattern, metin, re.IGNORECASE)
               for op in PACK.overused_patterns)


def test_meta_tail_TURKCE_meta_dilini_soker():
    metin = "Ev kedilerinden iyi olmalarının bilimsel sırrını 2. bölümde açıklıyoruz."
    assert re.search(PACK.meta_tail_pattern, metin, re.IGNORECASE)


def test_meta_tail_KAYNAK_regexle_ayni_davranir():
    """reel_series._META ile aynı metinleri yakalamalı."""
    from short_bot.reel_series import _META
    ornekler = [
        "Ev kedilerinden iyi olmalarının sırrını 2. bölümde açıklıyoruz.",
        "Fener balığının ışığını bir sonraki bölümde anlatacağım.",
        "Bunu yarın göstereceğim.",
        "Fener balığının ışığını üreten simbiyotik bakteri",   # meta YOK
        "Kalbin kendi elektriğini üretmesi",                    # meta YOK
    ]
    paket = re.compile(PACK.meta_tail_pattern, re.IGNORECASE)
    for m in ornekler:
        assert bool(paket.search(m)) == bool(_META.search(m)), m


# --- SERİ YÖNERGELERİ: DONDURULMUŞ ÇIKTIYLA BİREBİR ------------------------

def test_altin_dosya_TUM_dallari_kapsar():
    assert set(ALTIN) == {
        "zincir_yeni_ark", "zincir_soz_odeyen", "planli_ilk_bolum",
        "planli_orta_bolum", "planli_ark_finali", "baslik_bos_fallback",
        "devre_disi",
    }


def test_seri_yonergeleri_DONDURULMUS_CIKTIYLA_ayni():
    """Canlı series_directive(), dondurulmuş çıktıyla BİREBİR aynı mı?

    Task 6'dan ÖNCE bu totolojik (eski fonksiyon, kendi çıktısı). Task 6'dan SONRA
    fonksiyon paketten beslendiği için gerçek regresyon kalkanı olur.
    """
    from short_bot.reel_series import EpisodePlan, series_directive
    for ad, v in ALTIN.items():
        plan = EpisodePlan(**v["plan"])
        uretilen = series_directive(plan, v["series_title"])
        assert uretilen == v["directive"], f"{ad}: seri yönergesi DEĞİŞTİ"


def _paketten_render(plan, series_title: str, pack) -> str:
    """Task 6'daki yeni series_directive() ile AYNI mantık, paket şablonlarından.

    Buradaki amaç: tr.json'a elle transkribe ettiğim şablonların, ESKİ fonksiyonun
    ürettiğiyle birebir aynı metni verdiğini Task 6'yı beklemeden kanıtlamak.
    Transkripsiyon hatası varsa şimdi görülmeli.
    """
    if not plan.enabled:
        return ""
    t = (series_title or pack.default_series_title).strip()
    s = pack.series
    satirlar = [s.header.format(title=t, no=plan.episode_no, next_no=plan.next_no)]
    if plan.continue_from:
        satirlar.append(s.paying_promise.format(promise=plan.continue_from,
                                                no=plan.episode_no))
    if plan.is_planned and plan.is_new_arc:
        satirlar.append(s.announce_arc.format(arc_title=plan.arc_title,
                                              arc_total=plan.arc_total,
                                              no=plan.episode_no))
    if plan.is_arc_finale:
        satirlar.append(s.finale.format(arc_title=plan.arc_title,
                                        next_no=plan.next_no, no=plan.episode_no))
        return "\n".join(satirlar)
    if plan.next_topic:
        satirlar.append(s.planned_loop.format(next_no=plan.next_no,
                                              next_topic=plan.next_topic))
        return "\n".join(satirlar)
    satirlar.append(s.chain_loop.format(next_no=plan.next_no))
    return "\n".join(satirlar)


def test_PAKET_SABLONLARI_dondurulmus_ciktiyi_URETIR():
    """TRANSKRİPSİYON KANITI — bu planın en kritik testi.

    tr.json'daki seri şablonlarını elle çıkardım (f-string dalları → .format
    şablonları). Bir karakter kaydıysa Türkçe kanalların seri yönergesi değişir ve
    bunu hiçbir şey söylemez. Yedi dalın hepsini dondurulmuş çıktıyla karşılaştırıyoruz.
    """
    from short_bot.reel_series import EpisodePlan
    for ad, v in ALTIN.items():
        plan = EpisodePlan(**v["plan"])
        uretilen = _paketten_render(plan, v["series_title"], PACK)
        assert uretilen == v["directive"], (
            f"{ad}: tr.json şablonu ESKİ ÇIKTIYLA UYUŞMUYOR\n"
            f"--- beklenen ---\n{v['directive']!r}\n"
            f"--- paket üretti ---\n{uretilen!r}")


def test_seri_sablonlari_RENDER_EDILEBILIR():
    s = PACK.series
    assert s.header.format(title="Bilinmeyen Tarih", no=47, next_no=48)
    assert s.paying_promise.format(promise="fener balığının ışığı", no=47)
    assert s.announce_arc.format(arc_title="Derin Deniz", arc_total=3, no=10)
    assert s.finale.format(arc_title="Derin Deniz", next_no=48, no=47)
    assert s.planned_loop.format(next_no=48, next_topic="simbiyotik bakteri")
    assert s.chain_loop.format(next_no=48)
    assert s.teaser_fallback.format(title="Bilinmeyen Tarih")
