from short_bot.reel_relevance import (extract_topic_words, overlap_ratio,
                                       build_topic_pool, analyze_scene,
                                       derive_footage_anchor, MIN_POOL)


def test_extract_drops_stopwords_and_short():
    words = extract_topic_words("A large red whale swimming in the ocean")
    assert "whale" in words and "ocean" in words and "swimming" in words
    assert "the" not in words and "red" not in words        # stopword + renk
    assert "in" not in words and "a" not in words           # <3 harf / stopword


def test_overlap_ratio_direction_and_empty():
    assert overlap_ratio(set(), {"whale"}) == 1.0           # boş a → 1.0
    desc = {"baby", "swimming", "pool", "inflatable", "child"}
    pool = {"whale", "ocean", "migrate", "marine"}
    assert overlap_ratio(desc, pool) == 0.0                 # kesişim yok
    assert overlap_ratio({"whale", "ocean"}, pool) == 1.0   # ikisi de havuzda


def test_build_topic_pool_anchor_dominated():
    # çıpa her zaman girer; tek-seferlik yumuşak kelime ('baby','swimming') GİRMEZ
    pool = build_topic_pool(["humpback whale swimming", "baby whale calf"],
                            anchor="whale ocean marine")
    assert pool is not None
    assert "whale" in pool and "ocean" in pool and "marine" in pool   # çıpa
    assert "whales" in pool and "oceans" in pool                      # çoğul normalize
    assert "baby" not in pool and "swimming" not in pool             # tek-seferlik → düştü
    # ≥2 beat'te tekrar eden kelime havuza girer (çıpa havuzu aktif tutar)
    pool2 = build_topic_pool(["storm clouds", "storm lightning"], anchor="weather sky")
    assert pool2 is not None and "storm" in pool2                     # freq=2
    assert "clouds" not in pool2 and "lightning" not in pool2         # tek-seferlik düştü
    # zayıf, çıpasız havuz → None (gate pasif)
    assert build_topic_pool(["cat"], anchor="") is None
    assert build_topic_pool(["storm clouds", "storm lightning"], anchor="") is None  # anchor yok + <MIN_POOL


def test_analyze_scene_offtopic_and_ok():
    # 'baby whale' beat sorgusuna rağmen havuz anchor-baskın → insan bebeği off-topic
    pool = build_topic_pool(["baby whale calf swimming", "warm tropical ocean water"],
                            anchor="whale ocean marine")
    baby = analyze_scene("A human baby in a swimming pool with an inflatable ring", pool)
    assert baby["off_topic"] is True                        # regresyon: en kötü kusur
    beach = analyze_scene("A tropical beach with palm trees and white sand", pool)
    assert beach["off_topic"] is True                       # regresyon: tatil plajı
    whale = analyze_scene("A large whale swimming in the deep ocean", pool)
    assert whale["off_topic"] is False
    # on-topic KALIR: tek domain kelimesi ('ocean') yeter (uzunluğa duyarsız)
    iceberg = analyze_scene("icebergs floating in cold polar ocean water", pool)
    assert iceberg["off_topic"] is False                    # kutup sahnesi konuda
    # kaçış dalları
    assert analyze_scene("", pool)["reason"] == "no-vision"
    assert analyze_scene("whale", None)["reason"] == "no-topic"


def test_derive_footage_anchor_strips_placeholders():
    assert derive_footage_anchor("{header_top} {header_bottom} whale ocean") == "whale ocean"
    assert derive_footage_anchor("{a} {b} {category}") == ""      # sadece placeholder
    assert derive_footage_anchor("") == ""


def test_reelconfig_has_footage_anchor():
    from short_bot.config import ReelConfig
    c = ReelConfig(enabled=False)
    assert c.footage_anchor == ""
    c2 = ReelConfig(enabled=False, footage_anchor="whale ocean")
    assert c2.footage_anchor == "whale ocean"
