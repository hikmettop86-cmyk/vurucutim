"""Dayanaksız kısa cümle kapısı — kullanıcının yakaladığı 'Asıl mesele hız.' vakası."""
from __future__ import annotations

import pytest

from short_bot.narration_lint import dangling_fragments, fragment_feedback

REAL = ("Bir başkanlık ataması yüzünden bıçak çekildiyse, mesele bıçağı tutan elden büyüktür. "
        "Gaziantep'te milletvekili Melih Meriç bıçaklandı, bağırsakları zarar gördü. "
        "Hayati tehlikeyi atlattı, yoğun bakımda. Asıl mesele hız. "
        "Saldırgan bir ay önce CHP'nin ilçe başkanlığından istifa edip aynı partiye geçmişti.")


def test_catches_the_reported_fragment():
    assert dangling_fragments(REAL) == ["Asıl mesele hız."]


@pytest.mark.parametrize("s", [
    "Asıl mesele hız.",
    "Sorun burada.",
    "Kritik nokta zamanlama.",
    "Asıl soru güven.",
])
def test_flags_short_abstract_headlines(s):
    assert dangling_fragments(s) == [s]


@pytest.mark.parametrize("s", [
    "Hayati tehlikeyi atlattı, yoğun bakımda.",            # kısa ama somut fiil + durum
    "Asıl mesele hız: saldırgan bir ay önce geçmişti.",     # soyut + AYNI cümlede olgu
    "Kandilli üç nokta bir dedi.",                          # özel ad + sayı
    "Yirmi yedi suç kaydı var.",                            # sayı sözcüğü
    "Mesele Galatasaray'ın planı.",                         # özel ad dayanağı
    "Bu sıradan değil.",                                    # başlık kelimesi yok
    "Parti yönetimi bunu siyasi saldırı diye okudu; il başkanına soruşturma açıldı.",
])
def test_does_not_flag_grounded_or_plain_sentences(s):
    assert dangling_fragments(s) == []


def test_long_abstract_sentence_is_allowed():
    s = "Asıl mesele burada kimin ne zaman hangi sözü verdiği ve kimin tuttuğu."
    assert dangling_fragments(s) == []      # 5 kelimeden uzun → başlık cümlesi değil


def test_feedback_names_the_offenders_and_shows_the_fix():
    fb = fragment_feedback(["Asıl mesele hız."])
    assert "Asıl mesele hız." in fb
    assert "merge" in fb.lower() and "Asıl mesele hız: saldırgan" in fb
    assert "ONLY the JSON" in fb


def test_empty_and_none_safe():
    assert dangling_fragments("") == [] and dangling_fragments(None) == []
