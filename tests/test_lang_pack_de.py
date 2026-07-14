"""Almanca paketle uçtan uca — elle yazılmış fixture, LLM ÇAĞRILMAZ.

ÖLÇÜLDÜ (düzeltmeden önce): locale_fold Türkçe için I→ı yaptığı için Almanca metin
"ıch zeige euch" oluyordu ve r"\\bich\\b" ASLA eşleşmiyordu. Yani kusursuz bir Almanca
yasaklı-kalıp listesi bile ölü doğardı. Bu dosya o zinciri baştan sona kanıtlıyor:
paket → normalleştirme → denetçi → ekran metni.
"""
from short_bot.lang_pack import CTA_MAX_CHARS, LangPack, validate_pack
from short_bot.reel_phrases import find_overused, pick_styles

DE = LangPack.model_validate({
    "lang": "de",
    "cta_texts": ["Täglich neu — ABONNIEREN", "Morgen mehr — ABO",
                  "Serie läuft — ABO", "Teil 2 morgen — ABO"],
    "trade_cta": "#{no} morgen — ABO",
    "default_series_title": "Kuriose Fakten",
    "comment_styles": [f"Y{i}" for i in range(4)],
    "connective_styles": [f"S{i}" for i in range(8)],
    "series": {
        "header": "Folge {no} von '{title}'. Nächste: {next_no}.",
        "paying_promise": 'Löse dieses Versprechen ein: "{promise}"',
        "announce_arc": "Serie '{arc_title}', {arc_total} Folgen.",
        "finale": "Letzte Folge von '{arc_title}'. Folge {next_no} bringt Neues.",
        "planned_loop": 'Thema von Folge {next_no}: "{next_topic}"',
        "chain_loop": "Öffne eine Tür — die Antwort kommt in Folge {next_no}.",
        "teaser_fallback": "Eine Folge der Serie '{title}'.",
    },
    "overused": ["wusstest du schon", "hallo leute", "heute zeige ich euch",
                 "bleibt dran", "vergesst nicht zu abonnieren"],
    "overused_patterns": [
        {"label": "Wusstest du schon? (beantwortbare Ja/Nein-Frage — kein Hook)",
         "pattern": r"\bwusstest du\b"},
        {"label": "Hallo Leute (Kanal-Intro — verschwendet die erste Sekunde)",
         "pattern": r"\bhallo leute\b"},
        {"label": "Heute zeige ich euch (Ankündigung, kein Versprechen)",
         "pattern": r"\bheute zeige ich\b"},
        {"label": "Seid ihr bereit? (leere Floskel)",
         "pattern": r"\bseid ihr bereit\b"},
    ],
    # DİKKAT — KELİME SIRASI: Almanca'da fiil ÖNCE gelir ("...erkläre ich in Folge 48"),
    # Türkçe'de SONRA ("...48. bölümde açıklıyorum"). Türkçe regex'in yapısını çevirmek
    # işe yaramaz; her dilin kalıbı o dilin sözdizimine göre yazılmalı. (Bu fixture'ı
    # ilk yazışımda tam bu hatayı yaptım ve test yakaladı.)
    "meta_tail_pattern":
        r"\s*[—,;:-]*\s*(erkl[äa]r|zeig|sag|verrat)\w*\s+ich[^.]*?"
        r"(folge\s+\d+|n[äa]chsten\s+folge|morgen)[^.]*?[.!?]?\s*$",
})


def test_fixture_GECERLI():
    assert validate_pack(DE) == []


# --- DENETÇİ: düzeltmeden önce ÇALIŞMIYORDU --------------------------------

def test_almanca_KALIP_yakalanir():
    """'Ich' → 'ıch' oluyordu ve hiçbir Almanca kalıp eşleşmiyordu."""
    assert find_overused("Heute zeige ich euch etwas Verrücktes", pack=DE)


def test_wusstest_du_schon_yakalanir():
    assert find_overused("Wusstest du schon, dass Bier älter ist als Brot?", pack=DE)


def test_hallo_leute_yakalanir():
    assert find_overused("Hallo Leute, willkommen zurück!", pack=DE)


def test_BIREBIR_ifade_de_yakalanir():
    assert find_overused("Also bleibt dran, es wird gleich spannend.", pack=DE)


def test_temiz_almanca_metin_GECER():
    assert find_overused("Ein Bier braucht neun Monate im kalten Keller.",
                         pack=DE) == []


def test_TURKCE_kaliplar_ALMANCA_pakette_ARANMAZ():
    # Almanca kanalda Türkçe denetçi koşmamalı.
    assert find_overused("Bunu biliyor muydunuz", pack=DE) == []


def test_denetci_ETIKETI_dondurur():
    """LLM'e geri bildirimde gösterilen şey etiket — hedef dilde olmalı."""
    bulunan = find_overused("Wusstest du schon, dass...", pack=DE)
    assert any("Ja/Nein" in b for b in bulunan), bulunan


# --- BAĞLAÇ YÖNERGELERİ ----------------------------------------------------

def test_pick_styles_ALMANCA_havuzdan_secer():
    secilen = pick_styles(42, 4, pack=DE)
    assert len(secilen) == 4
    assert all(s in DE.connective_styles for s in secilen)


def test_pick_styles_DETERMINISTIK():
    assert pick_styles(7, 4, pack=DE) == pick_styles(7, 4, pack=DE)


def test_pick_styles_SEED_degisince_degisir():
    assert pick_styles(1, 4, pack=DE) != pick_styles(999, 4, pack=DE)


# --- EKRAN METNİ -----------------------------------------------------------

def test_almanca_rozet_NOKTASIZ_I():
    """GÖRÜNÜR HATA: turkish_upper 'Bier Garten' → 'BİER GARTEN' yapıyordu. Rozet,
    kanalın özenli olduğunu SÖYLEMESİ gereken şeydir."""
    from short_bot.reel_series import episode_badge
    assert episode_badge("Bier Garten", 47, pack=DE) == "BIER GARTEN #47"


def test_almanca_trade_cta():
    from short_bot.reel_series import trade_cta
    assert trade_cta(48, pack=DE) == "#48 morgen — ABO"


def test_almanca_CTA_24_karaktere_sigar():
    for c in DE.cta_texts:
        assert len(c) <= CTA_MAX_CHARS, f"{len(c)}: {c!r}"
    assert len(DE.trade_cta.format(no=48)) <= CTA_MAX_CHARS


# --- SERİ YÖNERGESİ + META TEMİZLİĞİ ---------------------------------------

def test_almanca_seri_yonergesi_ALMANCA():
    from short_bot.reel_series import EpisodePlan, series_directive
    plan = EpisodePlan(episode_no=47, arc_pos=2,
                       continue_from="das Bakterium im Licht")
    d = series_directive(plan, "Kuriose Fakten", pack=DE)
    assert "Folge 47" in d
    assert "das Bakterium im Licht" in d
    assert "BÖLÜM" not in d, "Türkçe yönerge sızdı"
    assert "ABONE" not in d


def test_almanca_meta_dili_SOKULUR():
    """clean_open_loop Almanca meta dilini sökmeli — sökmezse o metin BİR SONRAKİ
    BÖLÜMÜN ÜRETİM KONUSU olarak kullanılır ve senaryo yazıcısını yanıltır."""
    from short_bot.reel_series import clean_open_loop
    ham = "Das leuchtende Bakterium erkläre ich in Folge 48."
    assert clean_open_loop(ham, pack=DE) == "Das leuchtende Bakterium"


def test_meta_OLMAYAN_metin_BOZULMAZ():
    from short_bot.reel_series import clean_open_loop
    temiz = "Das symbiotische Bakterium im Licht des Anglerfischs"
    assert clean_open_loop(temiz, pack=DE) == temiz


# --- ABONE BİTLERİ ---------------------------------------------------------

def test_almanca_abone_bitleri_ALMANCA(monkeypatch):
    from short_bot.reel_subscribe import build_subscribe_bits

    class _Reel:
        series_enabled = False
        comment_question = True
        cta_enabled = True
        cta_text_custom = ""
        series_title = ""

    class _Ch:
        language = "de"
        reel = _Reel()

    monkeypatch.setattr("short_bot.reel_subscribe.load_pack", lambda lang: DE)
    bits = build_subscribe_bits(_Ch(), seed=3)
    assert bits.cta_text in DE.cta_texts
    assert "ABONE OL" not in bits.cta_text, "Türkçe çip Almanca kanalda"
    assert bits.comment_line in DE.comment_styles
