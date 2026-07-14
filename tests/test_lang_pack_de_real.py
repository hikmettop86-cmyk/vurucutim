"""ÜRETİLEN Almanca paketin gerçekten kullanılabilir olduğunu kanıtlar.

test_lang_pack_de.py ELLE YAZILMIŞ bir fixture kullanır — yani benim Almancamı sınar.
Bu dosya Sonnet 5'in GERÇEK ÇIKTISINI sınar: de.json.

KALİTE KAPISI. Bu testler düşerse paket yeniden üretilmeli (prompt düzeltilerek).
Testi zayıflatarak geçirme — Almanca kanal sessizce bozuk çalışır.
"""
from short_bot.lang_pack import CTA_MAX_CHARS, load_pack, validate_pack
from short_bot.reel_phrases import find_overused
from short_bot.reel_series import clean_open_loop, episode_badge, trade_cta

DE = load_pack("de")


def test_uretilen_paket_GECERLI():
    assert validate_pack(DE) == []


def test_CTA_ALMANCA_ve_kadraja_sigar():
    for c in DE.cta_texts:
        assert len(c) <= CTA_MAX_CHARS, f"{len(c)}: {c!r}"
    assert len(trade_cta(48, pack=DE)) <= CTA_MAX_CHARS
    birlesik = (" ".join(DE.cta_texts) + DE.trade_cta).upper()
    assert "ABONNIER" in birlesik, "Almanca abone kelimesi yok"


def test_TURKCE_sizintisi_YOK():
    ham = DE.model_dump_json()
    for tr in ["ABONE OL", "BÖLÜM", "bölüm", "yarın", "İzleyici", "biliyor mu"]:
        assert tr not in ham, f"Türkçe sızıntı: {tr!r}"


def test_rozet_NOKTASIZ_I():
    assert episode_badge("Bier Garten", 47, pack=DE) == "BIER GARTEN #47"


def test_GERCEK_almanca_kliseler_yakalanir():
    """Sonnet'in yazdığı kalıplar GERÇEKTEN eşleşiyor mu?

    Kritik: kelime sırası dilden dile değişiyor. Türkçe kalıbın yapısını çeviren bir
    regex SESSİZCE hiçbir şey yakalamaz. (Elle yazdığım Almanca fixture'da bu hatayı
    bizzat yaptım — bkz. test_lang_pack_de.py'deki not.)
    """
    kliseler = [
        "Wusstest du schon, dass Bier älter ist als Brot?",
        "Hallo Leute, willkommen zurück auf dem Kanal!",
        "Heute zeige ich euch etwas Verrücktes.",
        "Seid ihr bereit? Dann los!",
    ]
    for k in kliseler:
        assert find_overused(k, pack=DE), f"klişe KAÇTI: {k!r}"


def test_temiz_ALMANCA_metin_GECER():
    """Yanlış pozitif, kaçırmaktan beter: her anlatımı boşuna yeniden yazdırır."""
    temiz = [
        "Ein Bier braucht neun Monate im kalten Keller.",
        "Das Reinheitsgebot stammt aus dem Jahr 1516.",
    ]
    for t in temiz:
        assert find_overused(t, pack=DE) == [], f"yanlış alarm: {t!r}"


def test_meta_dili_ALMANCA_SOZDIZIMIYLE_sokulur():
    """Almanca'da fiil ÖNCE gelir ('erkläre ich in Folge 48'), Türkçe'de SONRA
    ('48. bölümde açıklıyorum'). Sonnet bunu doğru yapmalı."""
    assert clean_open_loop("Das leuchtende Bakterium erkläre ich in Folge 48.",
                           pack=DE) == "Das leuchtende Bakterium"
    assert clean_open_loop("Das leuchtende Bakterium zeige ich euch morgen.",
                           pack=DE) == "Das leuchtende Bakterium"


def test_temiz_konu_KIRPILMAZ():
    temiz = "Das symbiotische Bakterium im Licht des Anglerfischs"
    assert clean_open_loop(temiz, pack=DE) == temiz


def test_seri_yonergeleri_ALMANCA_ve_PEDAGOJI_korunmus():
    """Ödenmiş tepe + açık kapı pedagojisi her dilde ayakta kalmalı."""
    d = DE.series.chain_loop.format(next_no=48)
    assert "Folge 48" in d
    assert "open_loop" in d, "alan adı yönergeden düşmüş"
    # Yönerge iki AYRI çıktı istemeli (alan + konuşulan cliffhanger).
    assert d.count("48") >= 2
    assert "BÖLÜM" not in d and "ABONE" not in d
