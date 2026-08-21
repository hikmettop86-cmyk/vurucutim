"""Japonca yorumcu personası ve yasak kalıpları."""
from __future__ import annotations


def test_japonca_persona_var_ve_japonca():
    from short_bot.narration_writer import default_yorum_persona
    p = default_yorum_persona("ja")
    assert p, "ja personası boş"
    # Japonca yazılmış olmalı — Türkçenin çevirisi değil, hiragana/katakana taşımalı
    assert any("぀" <= c <= "ヿ" for c in p), "persona Japonca değil"
    assert "Sen " not in p and "Du " not in p


def test_japonca_persona_iftira_riskini_kapatir():
    """芸能ニュースde 名誉毀損 riski: doğrulanmamış özel hayat iddiası üzerine
    görüş bildirmek Japonya'da hukuki risk. Türkçe'deki yatırım tavsiyesi,
    Almanca'daki masumiyet karinesi ile aynı sınıf kural."""
    from short_bot.narration_writer import default_yorum_persona
    p = default_yorum_persona("ja")
    assert "憶測" in p, "özel hayat spekülasyonu yasağı yok"
    assert "報じられ" in p or "とみられ" in p, "kaynak/kesinlik ayrımı yok"


def test_japonca_yasak_kaliplar():
    from short_bot.narration_writer import banned_phrases
    b = banned_phrases("ja")
    assert b, "ja yasak listesi boş"
    # Arama verisi konuyu SEÇER, konuşulmaz
    assert any("検索" in x for x in b)
    assert any("トレンド" in x for x in b)
    # Japon web haberinin en yıpranmış kapanışı
    assert any("話題" in x for x in b)


def test_bilinmeyen_dil_hala_bos_doner():
    """Japonca eklemek, bilinmeyen dilde Türkçeye düşme tuzağını AÇMAMALI."""
    from short_bot.narration_writer import banned_phrases, default_yorum_persona
    assert default_yorum_persona("ko") == ""
    assert banned_phrases("ko") == ()
