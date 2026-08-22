"""Kapanış KISA olmalı; yorum sorusu AYRI alanda.

İKİ HATA BİR KÖKTEN:

1. ÜRETİM ÇÖKTÜ: close max 160 karakter, ama artık hem LOOP CALLBACK'i hem İKİLİ
   YORUM SORUSUNU taşıyordu → "String should have at most 160 characters" →
   ValidationError → üretim iptal.

2. 13 SANİYELİK DEV KAPANIŞ KARTI (kare kare incelemede görüldü): kapanış metni
   uzun olduğu için close segmenti videonun %27'sini yiyordu ve ekranı statik bir
   metin bloğu kaplıyordu. Araştırma: outro ≤5sn, statik son kare LOOP'U ÖLDÜRÜR —
   izleyici videonun bittiğini görür ve başa dönmez.

Çözüm: yorum sorusu AYRI alan (comment). Kapanış yalnız CALLBACK'i taşır ve KISA
kalır. İkisi de KONUŞULUR (TTS full_text'i alır) ama dev kart yalnız callback'i
gösterir.
"""
import pytest
from pydantic import ValidationError

from short_bot.reel_models import ReelBeat, ReelNarration


def _beats(n=3):
    return [ReelBeat(text=f"Beat {i} metni.", visual_query=f"shot {i}",
                     keyword=f"K{i}") for i in range(n)]


def _narr(**over):
    base = dict(hook="Piramitleri köleler yapmadı.", beats=_beats(),
                close="Ve işte bu yüzden, piramitleri köleler yapmadı.",
                mood="neutral")
    base.update(over)
    return ReelNarration(**base)


def test_comment_question_lives_in_its_own_field():
    n = _narr(comment="Sence hangisi: A mı, B mi? Tek harf yaz.")
    assert n.comment.startswith("Sence hangisi")
    # Kapanış SORUYU İÇERMEZ — dev kart yalnız callback'i gösterir
    assert "hangisi" not in n.close


def test_both_are_spoken():
    """TTS ikisini de okumalı — yorum sorusu SESLİ sorulmazsa yanıt gelmez."""
    n = _narr(comment="Tek harf yaz: A mı B mi?")
    assert n.close in n.full_text()
    assert n.comment in n.full_text()


def test_close_stays_short_so_the_outro_does_not_eat_the_video():
    """Kapanış uzun olursa close segmenti videonun dörtte birini yer ve statik bir
    metin bloğu ekranı kaplar → loop ölür. Sınır DAR tutuluyor."""
    from short_bot.reel_models import CLOSE_MAX_CHARS
    assert CLOSE_MAX_CHARS <= 120
    with pytest.raises(ValidationError):
        _narr(close="x" * (CLOSE_MAX_CHARS + 1))


def test_long_comment_is_trimmed_not_fatal():
    """Yorum sorusu taşarsa ÜRETİM DÜŞMESİN — kırpılsın.
    (Bir karakterlik taşma yüzünden LLM+TTS+footage+montaj çöpe gitmemeli.)"""
    from short_bot.reel_models import COMMENT_MAX_CHARS
    n = _narr(comment="y" * (COMMENT_MAX_CHARS + 40))
    assert len(n.comment) <= COMMENT_MAX_CHARS


def test_comment_is_optional():
    n = _narr()
    assert n.comment == ""
    assert n.full_text().endswith(n.close)


def test_close_still_echoes_the_hook_for_the_loop():
    """Yorum sorusu ayrılınca LOOP CALLBACK kontrolü BOZULMAMALI."""
    n = _narr(comment="A mı B mi?")
    assert n.close_echoes_hook() is True
