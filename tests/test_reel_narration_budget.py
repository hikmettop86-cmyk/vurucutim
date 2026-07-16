"""Kelime bütçesi ZORLANMALI — aşan senaryo videoyu hedefin dışına taşırır.

GERÇEK HATA (short_id=747): hedef 25-45sn (bütçe 55-99 kelime). LLM 112 kelime
üretti → video 53.3 SANİYE oldu. Retry mekanizması vardı ama SONUCU KONTROL
EDİLMİYORDU: ikinci deneme de taşınca 112 kelime olduğu gibi gitti.

Neden önemli: 45 saniyeyi aşınca düşüş sertleşiyor, loop'a girmek zorlaşıyor, ve
TEPE geç kalıyor (34.3sn = videonun %64'ü; olması gereken ~%50) — dolayısıyla
beğeni/abone tetikleri de geç kalıyor.
"""
import pytest

from short_bot.config import ReelConfig
from short_bot.reel_models import ReelBeat, ReelNarration
from short_bot.reel_narration import fit_word_budget, reel_word_budget


class _Ch:
    language = "tr"
    reel = ReelConfig(enabled=True, voice_id="v", target_duration_s=(25, 45))


def _narr(n_beats=5, words_per_beat=20, peak=2):
    beats = [ReelBeat(text=" ".join(f"s{j}" for j in range(words_per_beat)),
                      visual_query=f"fish shot {i}", keyword=f"K{i}")
             for i in range(n_beats)]
    return ReelNarration(hook="Hook cumlesi burada", beats=beats,
                         close="Kapanis cumlesi burada", mood="neutral",
                         peak_beat=peak)


def test_budget_matches_the_measured_speech_rate():
    """1.80 kelime/sn — EN YAVAŞ ölçülen hız.

    Gerçek koşular: 86/47.8=1.80 | 96/48.6=1.98 | 92/43.4=2.12 | 112/53.3=2.10.
    2.2 varsayımı iyimserdi: üst sınır 99 kelime → 48-53 SANİYELİK video.
    45 saniyeyi aşmamak, kısa kalmaktan önemli (aşınca düşüş sertleşiyor ve
    loop'a girmek zorlaşıyor).
    """
    lo, hi = reel_word_budget((25, 45))
    assert (lo, hi) == (45, 81)
    assert hi / 1.80 <= 45, "en yavaş ölçülen hızda bile 45 saniyeyi aşmamalı"


def test_over_budget_narration_is_trimmed_to_fit():
    """Bütçeyi aşan senaryo KISALTILIR — 53 saniyelik video gönderilmez."""
    n = _narr(n_beats=6, words_per_beat=25)       # ~154 kelime, sınır 99
    assert n.word_count() > 81
    out = fit_word_budget(n, lo_w=45, hi_w=81)
    assert out.word_count() <= 81


def test_trimming_never_drops_the_peak_beat():
    """TEPE videonun duygusal boşalma anı — kısaltma onu ASLA atmamalı."""
    n = _narr(n_beats=6, words_per_beat=25, peak=1)
    peak_text = n.beats[1].text
    out = fit_word_budget(n, lo_w=45, hi_w=81)
    assert any(b.text == peak_text for b in out.beats), "tepe beat atıldı"
    # peak_beat indeksi yeni listeye göre GÜNCELLENMELİ
    assert out.beats[out.peak_beat].text == peak_text


def test_trimming_keeps_the_minimum_beat_count():
    """3 beat'in altına inme — ark çöker."""
    n = _narr(n_beats=6, words_per_beat=35)       # aşırı uzun
    out = fit_word_budget(n, lo_w=45, hi_w=81)
    assert len(out.beats) >= 3


def test_in_budget_narration_is_returned_untouched():
    n = _narr(n_beats=4, words_per_beat=15)       # ~66 kelime
    assert 45 <= n.word_count() <= 81
    out = fit_word_budget(n, lo_w=45, hi_w=81)
    assert out is n


def test_hook_and_close_are_never_trimmed():
    """Hook videonun en kritik saniyesi; close LOOP callback'i. İkisi de dokunulmaz."""
    n = _narr(n_beats=6, words_per_beat=30)
    out = fit_word_budget(n, lo_w=45, hi_w=81)
    assert out.hook == n.hook and out.close == n.close


# --- GÖRÜNTÜ-ÖNCE EFEKTİF SÜRE OVERRIDE (loop teşhisi, short 874) --------------
def test_fd_prompt_target_override_butceyi_kucultur():
    # Süre klip sayısından türünce senaryo o küçük pencereye yazılır (3 klip → ~16sn,
    # 42sn'ye gerilip loop YOK). Override küçük bütçe → prompt küçük hedef içerir.
    from short_bot.reel_narration import build_footage_driven_prompt

    class _Ch2:
        language = "tr"
        reel = ReelConfig(enabled=True, voice_id="v", target_duration_s=(30, 45),
                          persona="", footage_driven=True)

    ch = _Ch2()
    p_def = build_footage_driven_prompt("konu", ["a cat sitting"], channel=ch)
    p_ovr = build_footage_driven_prompt("konu", ["a cat sitting"], channel=ch,
                                        target_duration_s=(11, 16))
    lo_w_def, hi_w_def = reel_word_budget((30, 45))
    lo_w_ovr, hi_w_ovr = reel_word_budget((11, 16))
    assert str(hi_w_ovr) in p_ovr and str(hi_w_def) not in p_ovr   # küçük bütçe
    assert str(hi_w_def) in p_def                                   # default değişmedi


def test_fd_enforce_budget_target_override_kucuk_sinir_uygular():
    # Override edilen küçük süre → küçük kelime sınırı → uzun senaryo kısaltılır.
    from short_bot.reel_narration import _fd_enforce_budget

    class _Ch3:
        language = "tr"
        reel = ReelConfig(enabled=True, voice_id="v", target_duration_s=(30, 45))

    # ~51 kelime: (30,45) bütçesinde (54-81, tolerans×1.1) GEÇER; (11,16) bütçesinde AŞAR.
    n = _narr(n_beats=3, words_per_beat=15, peak=1)
    kisaltildi = {"cagrildi": False}

    def fake_invoke(prompt, schema):
        kisaltildi["cagrildi"] = True
        return n   # kısaltma çağrıldığını görmek yeter (fail-open orijinali döndürür)

    ch = _Ch3()
    # override YOK → geniş bütçe, kısaltma çağrılmaz
    _fd_enforce_budget(n, ch, "konu", invoke=fake_invoke)
    assert kisaltildi["cagrildi"] is False
    # override küçük süre → dar bütçe, kısaltma turu tetiklenir
    _fd_enforce_budget(n, ch, "konu", invoke=fake_invoke, target_duration_s=(11, 16))
    assert kisaltildi["cagrildi"] is True
