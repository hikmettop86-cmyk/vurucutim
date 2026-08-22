"""CJK'de senaryo ÖBEKLERİ ile whisper KARAKTERLERİ aynı tanelikte karşılaştırılmalı.

GERÇEK HATA (Japonca üretim, 2026-07-24, kedi kurtarma klibi): TTS metnin TAMAMINI
okumuştu — whisper dökümü bunu açıkça gösteriyor — ama sadakat denetimi "9 kelime
okunmadı" dedi ve ses İKİ KEZ boşuna yeniden üretildi.

Kök neden tek: iki taraf farklı tanelikte tokenleşiyordu.
    senaryo  → split_words → ['ずぶ濡れの', '子猫が', '狭い水路の', ...]   (2-7 karakter)
    whisper  → zaten karakter karakter → ['ず', 'ぶ', '濡', 'れ', 'の', ...]
SequenceMatcher hiçbir eşleşme bulamıyor.

İkinci ve daha ağır sonucu: ``align_to_asr`` da demir atacak eşleşme bulamayıp ORANTILI
dağıtıma düşüyordu → altyazı sese hiç kilitlenmiyordu. Final QA bunu bitmiş videoda
gördü: "aynı cümle 4 karede takılı kalmış".

Çözüm: CJK'de ölçüt KARAKTER. Sadakat karakter dizisi karşılaştırır; hizalama karakter
düzeyinde demir atıp zamanları öbeklere geri toplar (ekranda yine öbek görünür).
"""
from short_bot.caption_align import align_to_asr
from short_bot.text_normalize import language
from short_bot.tts.fidelity import normalize_tokens, worst_drop


class _W:
    def __init__(self, word, start_s, end_s):
        self.word, self.start_s, self.end_s = word, start_s, end_s


_SCRIPT = "ずぶ濡れの子猫が狭い水路の縁で震えていました。"
# whisper Japoncayı böyle döker: karakter karakter, araya boşluk koyarak
_HEARD = "ず ぶ 濡 れ の 子 猫 が 狭 い 水 路 の 縁 で 震 え て いました。"


# ------------------------------------------------------------------ sadakat denetimi

def test_no_false_drop_when_tts_read_everything():
    """EN KRİTİK: aynı metin farklı tanelikte gelince 'okunmadı' DEMEMELİ."""
    with language("ja"):
        d = worst_drop(_SCRIPT, _HEARD, "ja")
    assert d.count == 0, f"sahte kayıp: {d.count} → {d.phrase!r}"
    assert d.ok


def test_real_drop_is_still_caught():
    """Gerçekten okunmayan öbek YAKALANMALI — denetim körleşmesin."""
    heard = "ず ぶ 濡 れ の 子 猫 が いました。"      # ortadaki uzun öbek hiç okunmamış
    with language("ja"):
        d = worst_drop(_SCRIPT, heard, "ja")
    assert d.count >= 3, d
    assert not d.ok


def test_tokens_are_characters_for_japanese():
    with language("ja"):
        t = normalize_tokens("子猫が", "ja")
    assert t == ["子", "猫", "が"], t


def test_tokens_unchanged_for_turkish():
    assert normalize_tokens("bu çocuk yalnızdı", "tr") == ["bu", "çocuk", "yalnızdı"]


# ------------------------------------------------------------------ altyazı hizalama

def _char_asr(text, *, per_char=0.2):
    """whisper benzeri: her karakter ayrı bir 'kelime', sıralı zamanlarla."""
    out, t = [], 0.0
    for ch in text.replace(" ", ""):
        out.append(_W(ch, t, t + per_char))
        t += per_char
    return out


def test_chunks_get_real_asr_times_not_proportional():
    """Öbekler ASR'a demir atmalı: ilk öbeğin bitişi, karakterlerinin gerçek zamanı."""
    script = ["ずぶ濡れの", "子猫が", "震えていました"]
    asr = _char_asr("ずぶ濡れの子猫が震えていました", per_char=0.2)
    with language("ja"):
        times = align_to_asr(script, asr, duration_s=20.0)
    # 'ずぶ濡れの' 5 karakter × 0.2 = 1.0sn'de bitmeli (orantılı dağıtım 20sn'ye yayardı)
    assert abs(times[0][1] - 1.0) < 0.25, times
    assert abs(times[1][0] - 1.0) < 0.25, times


def test_alignment_times_are_monotonic():
    script = ["ずぶ濡れの", "子猫が", "震えていました"]
    asr = _char_asr("ずぶ濡れの子猫が震えていました")
    with language("ja"):
        times = align_to_asr(script, asr, duration_s=20.0)
    for (s1, e1), (s2, e2) in zip(times, times[1:]):
        assert s1 <= e1 <= s2 + 1e-6, (times,)


def test_alignment_returns_one_span_per_chunk():
    script = ["ずぶ濡れの", "子猫が", "震えていました"]
    asr = _char_asr("ずぶ濡れの子猫が震えていました")
    with language("ja"):
        assert len(align_to_asr(script, asr, duration_s=20.0)) == 3


def test_turkish_alignment_unchanged():
    script = ["bu", "çocuk", "yalnızdı"]
    asr = [_W("bu", 0.0, 0.5), _W("çocuk", 0.5, 1.2), _W("yalnızdı", 1.2, 2.0)]
    times = align_to_asr(script, asr, duration_s=2.0)
    assert times == [(0.0, 0.5), (0.5, 1.2), (1.2, 2.0)]


def test_falls_back_to_proportional_when_asr_empty():
    script = ["ずぶ濡れの", "子猫が"]
    with language("ja"):
        times = align_to_asr(script, [], duration_s=10.0)
    assert len(times) == 2 and times[-1][1] == 10.0
