"""LangPack doğrulaması.

SERT KISITLAR KODDAN gelir, paketten değil — paket onlara UYMAK zorunda:
  CTA_MAX_CHARS = 24    Almanca'da "ABONNIEREN" tek başına 10 karakter. Çalışma anında
                        kırpılırsa ekranda "ABONNIE" yazar — her şeyden kötü.
  BADGE_MAX_CHARS = 28

Bu yüzden paket ÜRETİLDİĞİ AN doğrulanır, çalışma anında değil. Çalışma anında
"düzeltmek" (kırpmak, atlamak) sessiz bozulmanın tanımıdır.
"""
import pytest

from short_bot.lang_pack import LangPack, SeriesDirectives, validate_pack


def _seri(**kw):
    d = dict(
        header="Dies ist Folge {no} von '{title}'. Die nächste ist {next_no}.",
        paying_promise='Diese Folge löst ein Versprechen ein: "{promise}"',
        announce_arc="Kündige die Serie an: '{arc_title}', {arc_total} Folgen.",
        finale="Letzte Folge von '{arc_title}'. Folge {next_no} bringt ein neues Thema.",
        planned_loop='Das Thema von Folge {next_no} steht fest: "{next_topic}"',
        chain_loop="Öffne eine Tür; die Antwort kommt in Folge {next_no}.",
        teaser_fallback="Dies ist eine Folge der Serie '{title}'.",
    )
    d.update(kw)
    return SeriesDirectives(**d)


def _pack(**kw):
    d = dict(
        lang="de",
        cta_texts=["Täglich neu — ABONNIEREN", "Morgen mehr — ABO",
                   "Serie läuft — ABO", "Teil 2 morgen — ABO"],
        trade_cta="#{no} morgen — ABONNIEREN",
        default_series_title="Kuriose Fakten",
        comment_styles=["A", "B", "C", "D"],
        connective_styles=[f"S{i}" for i in range(8)],
        series=_seri(),
        overused=["wusstest du schon", "hallo leute", "heute zeige ich euch",
                  "bleibt dran", "vergesst nicht"],
        overused_patterns=[
            {"label": "Wusstest du schon? (beantwortbare Ja/Nein-Frage)",
             "pattern": r"\bwusstest du\b"},
            {"label": "Hallo Leute (Kanal-Intro)", "pattern": r"\bhallo leute\b"},
            {"label": "Heute zeige ich euch", "pattern": r"\bheute zeige ich\b"},
            {"label": "Seid ihr bereit?", "pattern": r"\bseid ihr bereit\b"},
        ],
        meta_tail_pattern=r"\bin\s+folge\s+\d+\b.*$",
    )
    d.update(kw)
    return LangPack(**d)


def test_gecerli_paket_KABUL_edilir():
    assert validate_pack(_pack()) == []


# --- EKRAN KISITLARI -------------------------------------------------------

def test_24_karakterlik_CTA_KABUL():
    cta = "Täglich neu — ABONNIEREN"
    assert len(cta) == 24
    assert validate_pack(_pack(cta_texts=[cta, "a", "b", "c"])) == []


def test_25_karakterlik_CTA_RED():
    """SINIR TESTİ. Kırpılan çip ekranda 'ABONNIE' yazar."""
    uzun = "Täglich neue — ABONNIEREN"
    assert len(uzun) == 25, len(uzun)
    hatalar = validate_pack(_pack(cta_texts=[uzun, "a", "b", "c"]))
    assert any("24" in h for h in hatalar), hatalar


def test_trade_cta_RENDER_EDILINCE_olculur():
    """'#{no} ...' şablonu HAM hâlde kısa görünüp, no=48 ile taşabilir."""
    hatalar = validate_pack(_pack(trade_cta="#{no} morgen — JETZT ABONNIEREN"))
    assert hatalar, "render edilmiş uzunluk ölçülmedi"


def test_trade_cta_no_yer_tutucusu_ZORUNLU():
    hatalar = validate_pack(_pack(trade_cta="morgen — ABONNIEREN"))
    assert any("{no}" in h for h in hatalar), hatalar


def test_seri_basligi_ROZETE_sigmali():
    # Rozet "BASLIK #47" ≤ 28 karakter → başlık ≤ 24
    assert validate_pack(_pack(default_series_title="A" * 25))
    assert validate_pack(_pack(default_series_title="A" * 24)) == []


def test_BOS_CTA_RED():
    assert validate_pack(_pack(cta_texts=["", "b", "c", "d"]))


def test_TEKRARLI_CTA_RED():
    assert validate_pack(_pack(cta_texts=["a", "a", "c", "d"]))


# --- SAYILAR (seed rotasyonu bunlara dayanıyor) ----------------------------

def test_comment_styles_TAM_4():
    assert validate_pack(_pack(comment_styles=["A", "B", "C"]))
    assert validate_pack(_pack(comment_styles=["A", "B", "C", "D", "E"]))


def test_connective_styles_TAM_8():
    assert validate_pack(_pack(connective_styles=[f"S{i}" for i in range(7)]))


def test_denetci_BOS_olamaz():
    # Boş liste = denetçi yok = sessiz bozulma.
    assert validate_pack(_pack(overused=[]))
    assert validate_pack(_pack(overused_patterns=[]))


# --- REGEX -----------------------------------------------------------------

def test_DERLENMEYEN_regex_RED():
    bozuk = [{"label": f"bozuk kalıp {i}", "pattern": r"\b(unclosed"} for i in range(4)]
    hatalar = validate_pack(_pack(overused_patterns=bozuk))
    assert any("regex" in h.lower() for h in hatalar), hatalar


def test_bozuk_meta_tail_RED():
    assert validate_pack(_pack(meta_tail_pattern=r"[unclosed"))


# --- SERİ ŞABLONLARI: YER TUTUCULAR ----------------------------------------

def test_EKSIK_yer_tutucusu_RED():
    """planned_loop'ta {next_no} yoksa LLM'e bölüm numarası HİÇ söylenmez."""
    hatalar = validate_pack(_pack(series=_seri(planned_loop='Thema: "{next_topic}"')))
    assert any("next_no" in h for h in hatalar), hatalar


def test_BILINMEYEN_yer_tutucusu_RED():
    """{bilinmeyen} çalışma anında KeyError fırlatır — üretimin TAM ORTASINDA."""
    hatalar = validate_pack(_pack(series=_seri(chain_loop="Folge {bilinmeyen}")))
    assert any("bilinmeyen" in h for h in hatalar), hatalar


def test_desteklenmeyen_dil_RED():
    assert validate_pack(_pack(lang="zz"))


# --- SESSİZ DÜŞME YASAĞI ---------------------------------------------------

def test_paket_YOKSA_TURKCEYE_DUSMEZ():
    """SESSİZ BOZULMANIN TA KENDİSİ: Almanca kanal Türkçe çip basıyordu.
    Paket yoksa NET HATA verilir — sessizce Türkçe döndürülmez."""
    from short_bot.lang_pack import load_pack, set_user_dir
    # TEST YALITIMI: `_user_dir` modül-global ve `load_pack` lru_cache'li. Bir web
    # testi daha önce set_user_dir çağırdıysa bu test onun dizinini görür ve sonuç
    # test SIRASINA bağlı olurdu.
    set_user_dir(None)
    with pytest.raises(RuntimeError, match="dil paketi yok"):
        load_pack("fr")     # kodla gelmiyor, üretilmedi
