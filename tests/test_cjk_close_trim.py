"""CJK kapanışı ekran bütçesine KODLA sığdırılır (kullanıcı kararı, 2026-07-24).

EKRANDA ÖLÇÜLDÜ (Short 1090): kapanış 42 karakterdi ve 23 saniyelik videonun son
~8 saniyesini (%35) 3 satırlık statik metin duvarı olarak kapladı. Prompt kuralı
(≤25 karakter) YETMEDİ — model 42 yazdı.

Kırpma SÖZLEŞMESİ:
  • yalnız CJK dillerinde; Türkçe/Almanca kapanışa DOKUNULMAZ,
  • kesme YALNIZ cümle sınırından — ortadan kesmek okunmaz bir kuyruk bırakır,
  • SON cümle her zaman korunur (CTA orada),
  • tek cümle bile bütçeyi aşıyorsa OLDUĞU GİBİ bırakılır (yarım cümle daha kötü),
  • kırpma SESSİZ değildir: çağıran loglar.

NOT: kapanış KONUŞULAN metindir; kırpmak anlatımı da kısaltır. Kullanıcı bunu bilerek
seçti (alternatif: sesi tam bırakıp yalnız kartı kısaltmaktı).
"""
from short_bot.reel_narration import CJK_CLOSE_MAX, trim_cjk_close


def test_long_close_drops_leading_sentence():
    src = "猫は満足げに去っていきました。この様子、どう思いましたか。コメントで教えてください。"
    got = trim_cjk_close(src, "ja")
    assert got == "この様子、どう思いましたか。コメントで教えてください。", got
    assert len(got) <= CJK_CLOSE_MAX


def test_cta_sentence_is_always_kept():
    src = "猫は満足げに去っていきました。この様子、どう思いましたか。コメントで教えてください。"
    assert trim_cjk_close(src, "ja").endswith("コメントで教えてください。")


def test_short_close_is_untouched():
    src = "この優しさ、どう感じましたか。"
    assert trim_cjk_close(src, "ja") == src


def test_single_oversized_sentence_is_left_alone():
    """Yarım cümle basmaktansa uzun bassın — ortadan kesmek okunmaz."""
    src = "この信じられないほど心温まる光景についてぜひコメントで教えてくださいね。"
    assert trim_cjk_close(src, "ja") == src


def test_turkish_close_is_never_trimmed():
    src = ("Bu kucaklaşma içini burkuyorsa yorumlara bir kalp bırak. "
           "Sen olsan ne yapardın? Yorumlarda söyle.")
    assert trim_cjk_close(src, "tr") == src


def test_question_and_exclamation_count_as_sentence_ends():
    src = "本当に驚きました！この光景、どう思いましたか。コメントで教えてください。"
    got = trim_cjk_close(src, "ja")
    assert not got.startswith("本当に"), got
    assert len(got) <= CJK_CLOSE_MAX


def test_trim_keeps_text_a_suffix_of_the_original():
    """Kırpma yalnız BAŞTAN atar — kelime değiştirmez, yeniden yazmaz."""
    src = "猫は満足げに去っていきました。この様子、どう思いましたか。コメントで教えてください。"
    assert src.endswith(trim_cjk_close(src, "ja"))


def test_empty_and_blank_are_safe():
    assert trim_cjk_close("", "ja") == ""
    assert trim_cjk_close("   ", "ja") == "   "
