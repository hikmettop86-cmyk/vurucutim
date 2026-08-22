"""Kapanış cümlesi CJK noktalamasını TANIMALI ve ekranda duvar olmamalı.

EKRANDA GÖRÜLDÜ (Short 1089, fil klibi): kapanış "…聞かせてください。." diye bitti —
Japonca cümle sonu 。 basıldıktan SONRA bir de ASCII nokta. Sebebi ``_strip_bard``:
cümle ".!?" ile bitmiyorsa nokta ekliyor, ama 。！？ o kümede yok. Her Japonca videoda
çıkar.

İkinci kusur aynı karede: kapanış 80 karakterdi ve 4 satırlık küçük puntolu bir metin
bloğu olarak duygusal doruk karesini (filin dişini kepçeye dayadığı an) kapattı.
``CLOSE_MAX_CHARS=120`` LATİN harfe göre ayarlı; Japoncada bir karakter çok daha fazla
şey taşır, 120 karakter paragraf demektir.
"""
from short_bot.locale import narration_style_rule
from short_bot.reel_narration import _strip_bard
from short_bot.text_normalize import language


def test_japanese_full_stop_is_not_double_punctuated():
    with language("ja"):
        s = _strip_bard("コメントで感想を聞かせてください。")
    assert not s.endswith("。."), s
    assert s.endswith("。"), s


def test_japanese_question_and_exclamation_are_respected():
    with language("ja"):
        assert _strip_bard("本当にそう思いますか？").endswith("？")
        assert _strip_bard("すごい！").endswith("！")


def test_japanese_sentence_without_punctuation_still_gets_one():
    """Noktalama yoksa eklenmeli — ama JAPON noktası."""
    with language("ja"):
        s = _strip_bard("コメントで感想を聞かせてください")
    assert s.endswith("。"), s


def test_turkish_behaviour_unchanged():
    assert _strip_bard("İşte arının emeği") == "İşte arının emeği."
    assert _strip_bard("İşte arının emeği.") == "İşte arının emeği."
    assert _strip_bard("Ne dersin?") == "Ne dersin?"


def test_bard_stripping_still_works():
    assert "Aşık" not in _strip_bard("Aşık Karga der ki: iş bitti")


def test_japanese_style_rule_caps_onscreen_length():
    """Kapanış/kapak uzunluk sınırı yazarın önünde olmalı — kırpma çirkin kesiyor."""
    rule = narration_style_rule("ja")
    assert "close" in rule.lower()
    assert any(ch.isdigit() for ch in rule), rule
