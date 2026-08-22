"""Senaryo LİSTE değil ARK olmalı; TEPE ortada; kapanış hook'u geri çağırmalı.

TEŞHİS (araştırma + kullanıcı şikâyeti "kaliteli ama abone/beğeni gelmiyor"):

"Şok edici bilgiler" formatı değeri MONOTON teslim eder — bilgi, bilgi, bilgi.
Üç ölümcül sonucu var:
  1. HER BEAT BİR ÇIKIŞ RAMPASI. İzleyici bilgiyi aldı, merak KAPANDI. 12. saniyenin
     13'e götürmesi için sebep yok → retention doğrusal düşer.
  2. TEPE YOK. Beğeni bir karar değil, DUYGUSAL BOŞALMADIR. Düzgün, eşit tempolu,
     olgusal olarak eksiksiz bir videonun tepesi yoktur; bilgiler düzdür. Boşalacak
     yer olmayınca beğeni gelmez. ("Kalite ≠ duygusal genlik.")
  3. LOOP YOK. Kapanış hook'a bağlanmazsa video BİTER; oysa faceless format loop'ta
     yapısal olarak avantajlıdır (yüz yok = yeniden başladığı belli olmaz) ve her
     tekrar oynatma ayrı bir izlenme sayılır.

Yapısal karşılık:
  hook → döngü aç → ilk ödeme → tırmanan beat'ler (her biri mikro-döngüyle biter)
  → TEPE (ortada) → twist → kapanış hook'un SÖZCÜKLERİNİ geri çağırır.
"""
import pytest
from pydantic import ValidationError

from short_bot.config import ReelConfig
from short_bot.reel_models import ReelBeat, ReelNarration
from short_bot.reel_narration import build_reel_prompt


class _Ch:
    language = "tr"
    reel = ReelConfig(enabled=True, voice_id="v", target_duration_s=(35, 45))


def _beats(n=4):
    return [ReelBeat(text=f"Beat {i} metni burada.", visual_query=f"kangaroo shot {i}",
                     keyword=f"K{i}") for i in range(n)]


def test_narration_carries_the_peak_beat_index():
    """Videonun EN BÜYÜK reveal'i hangi beat? Kod bunu bilmeli — CTA/beğeni tetiği
    ve müzik değişimi ona göre yerleşecek."""
    n = ReelNarration(hook="Hook cumlesi", beats=_beats(4), close="Kapanis cumlesi", mood="neutral",
                      peak_beat=2)
    assert n.peak_beat == 2


def test_peak_defaults_to_the_middle_when_llm_omits_it():
    """LLM alanı vermezse ORTA beat tepe sayılır — 'en iyi bilgi öne' hatasına
    düşmektense ortaya varsay."""
    n = ReelNarration(hook="Hook cumlesi", beats=_beats(4), close="Kapanis cumlesi", mood="neutral")
    assert n.peak_beat == 2          # 4 beat → orta


def test_peak_out_of_range_is_clamped_not_crashing():
    """LLM uydurma indeks verirse ÜRETİM ÇÖKMESİN (fail-open)."""
    n = ReelNarration(hook="Hook cumlesi", beats=_beats(3), close="Kapanis cumlesi", mood="neutral",
                      peak_beat=99)
    assert 0 <= n.peak_beat < 3


def test_peak_cannot_be_the_last_beat():
    """TEPE SON BEAT OLAMAZ — o zaman videonun %80'ine kayar.

    GERÇEK HATA (short_id=750): bütçe 3 beat'e indirdi, LLM peak_beat=2 (SONUNCU)
    dedi. Tepe 32.1sn / 40.3sn = %80'e kaydı → beğeni ve abone tetikleri videonun
    sonunda kaldı. Araştırma tepeyi ~%50'de istiyor.

    Kural: tepe ne İLK ne SON beat olabilir — prompt söylüyor ama LLM uymuyor,
    o yüzden KOD zorluyor.
    """
    n = ReelNarration(hook="Hook cumlesi", beats=_beats(3), close="Kapanis cumlesi",
                      mood="neutral", peak_beat=2)      # sonuncu
    assert n.peak_beat == 1, "tepe son beat'te kaldı → video sonunda CTA"

    n4 = ReelNarration(hook="Hook cumlesi", beats=_beats(4), close="Kapanis cumlesi",
                       mood="neutral", peak_beat=3)     # sonuncu
    assert n4.peak_beat in (1, 2)


def test_peak_cannot_be_the_first_beat():
    """İlk beat tepe olursa video baştan yokuş aşağı — 'front-load' hatası."""
    n = ReelNarration(hook="Hook cumlesi", beats=_beats(4), close="Kapanis cumlesi",
                      mood="neutral", peak_beat=0)
    assert n.peak_beat != 0


def test_three_beats_peak_is_the_middle_one():
    n = ReelNarration(hook="Hook cumlesi", beats=_beats(3), close="Kapanis cumlesi",
                      mood="neutral", peak_beat=1)
    assert n.peak_beat == 1


def test_peak_time_is_derived_from_segment_spans():
    """Tepenin SANİYESİ segment aralıklarından türetilir (overlay bunu kullanacak)."""
    n = ReelNarration(hook="Hook cumlesi", beats=_beats(3), close="Kapanis cumlesi", mood="neutral",
                      peak_beat=1)
    # segmentler: [hook, b0, b1, b2, close] → tepe beat 1 = segment index 2
    assert n.peak_segment() == 2


def test_close_must_echo_the_hook_for_the_loop():
    """LOOP: kapanış hook'un sözcüklerini geri çağırmalı.

    Kapanış hook'la HİÇ ortak içerik sözcüğü paylaşmıyorsa video 'biter' ve
    izleyici döngüye girmez.
    """
    ok = ReelNarration(
        hook="Piramitleri köleler yapmadı.", beats=_beats(3),
        close="Ve işte bu yüzden, piramitleri köleler yapmadı.", mood="neutral")
    assert ok.close_echoes_hook() is True

    weak = ReelNarration(
        hook="Piramitleri köleler yapmadı.", beats=_beats(3),
        close="Doğa her zaman şaşırtır.", mood="neutral")
    assert weak.close_echoes_hook() is False


def test_prompt_demands_arc_peak_and_loop():
    p = build_reel_prompt("kanguru yavrusunun keseye yolculuğu", _Ch())
    assert "peak_beat" in p, "tepe alanı istenmiyor"
    low = p.lower()
    # Mikro-döngü: her beat bir sonrakine borç bırakmalı
    assert "mikro" in low or "micro" in low, "mikro-döngü kuralı yok"
    # Loop: kapanış hook'un sözcüklerini geri çağırmalı
    assert "callback" in low or "geri çağır" in low
    # En iyi bilgiyi öne koyma yasağı
    assert "front-load" in low or "öne koyma" in low or "başa koyma" in low


def test_beats_still_validate_normally():
    with pytest.raises(ValidationError):
        ReelNarration(hook="Hook cumlesi", beats=[], close="Kapanis cumlesi", mood="neutral")
