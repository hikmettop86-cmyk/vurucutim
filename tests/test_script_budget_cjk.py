"""Senaryo uzunluk bütçesi DİLE DUYARLI olmalı.

ÖLÇÜLDÜ (Japonca deneme videosu, 2026-07-24, ai33 'Yoshiki' sesi):
    158 karakter (boşluksuz) → 28.775sn ses  ⇒  5.49 karakter/sn
    33 öbek                                  ⇒  1.15 öbek/sn

Türkçe sabiti WORDS_PER_SECOND = 1.80 kelime/sn. Yani aynı formülü Japoncaya uygulamak
(30sn için "45-81 kelime yaz") modele Japoncada yaklaşık İKİ KATI metin yazdırır ve video
hedefin çok üstüne çıkar — tepe kayar, klip loop'a girer, düşüş sertleşir.

Japoncada "kelime" ölçülebilir bir birim de değildir (boşluk yok). Bu yüzden CJK'de bütçe
KARAKTER cinsindendir ve prompt da öyle söyler.
"""
from short_bot.reel_narration import budget_unit, reel_word_budget
from short_bot.text_normalize import language


def test_turkish_budget_unchanged():
    assert reel_word_budget((25, 45), "tr") == (int(25 * 1.80), int(45 * 1.80))


def test_turkish_unit_is_words():
    assert budget_unit("tr") == "words"


def test_japanese_unit_is_characters():
    assert budget_unit("ja") == "characters"


def test_japanese_budget_is_character_based_and_much_larger_number():
    lo, hi = reel_word_budget((25, 45), "ja")
    # 5.49 kar/sn → 30sn ≈ 165 karakter; kelime formülü 54 verirdi
    assert 120 <= lo <= 160, (lo, hi)
    assert 220 <= hi <= 280, (lo, hi)


def test_japanese_budget_matches_measured_rate():
    """Bir 30sn video için bütçe, ölçülen 5.49 kar/sn ile uyumlu olmalı."""
    lo, hi = reel_word_budget((30, 30), "ja")
    assert abs(lo - 30 * 5.49) < 30, lo


def test_budget_reads_language_from_context_when_not_given():
    with language("ja"):
        assert reel_word_budget((25, 45)) == reel_word_budget((25, 45), "ja")
    with language("tr"):
        assert reel_word_budget((25, 45)) == reel_word_budget((25, 45), "tr")


# --------------------------------------------------- bütçe ÖLÇÜMÜ de dile duyarlı

def _narration(text_lang):
    from short_bot.reel_models import ReelBeat, ReelNarration
    if text_lang == "ja":
        return ReelNarration(
            hook="病院の廊下、たった一人の男の子",
            beats=[ReelBeat(text="椅子で静かに待っていました。", visual_query="clip"),
                   ReelBeat(text="窓辺のスパイダーマンに両手を広げました。", visual_query="clip"),
                   ReelBeat(text="そのまま胸に抱き上げられました。", visual_query="clip")],
            close="胸に響いたら、コメントに残してください。", mood="calm")
    return ReelNarration(
        hook="Bal nasıl olur?",
        beats=[ReelBeat(text="Arılar nektar toplar burada.", visual_query="clip"),
               ReelBeat(text="Enzimlerle işler bunu.", visual_query="clip"),
               ReelBeat(text="Peteğe biriktirir hemen.", visual_query="clip")],
        close="İşte arının emeği.", mood="upbeat")


def test_word_count_counts_characters_for_japanese():
    """Bütçe karakterse ÖLÇÜM de karakter olmalı — yoksa kısaltma emniyeti hiç çalışmaz
    (Japonca metin split() ile ~5 'kelime' sayılıp her sınırın altında kalırdı)."""
    with language("ja"):
        n = _narration("ja")
        assert n.word_count() > 60, n.word_count()


def test_word_count_unchanged_for_turkish():
    with language("tr"):
        n = _narration("tr")
        assert n.word_count() == len(n.full_text().split())
