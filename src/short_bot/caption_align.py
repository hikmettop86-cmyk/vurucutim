"""Senaryo kelimelerini konuşulan sese bağlama (karaoke altyazı zamanları).

NEDEN VAR: eskiden ASR zamanları ancak kelime SAYISI senaryoyla birebir tutarsa
kullanılıyordu; tutmazsa hepsi atılıp süre eşit dağıtılıyordu. Ama whisper metni
senaryoyla aynı kelimelere bölmez — "altı"yı "6" yazar, "Amerika'nın"ı ikiye
ayırır — yani sayı sık sık tutmaz ve karaoke aslında sese HİÇ kilitlenmiyordu.
Konuşma temposu düzgün oldukça bu görünmüyordu.

Görünür hâle geldiği yer: TTS metnin bir öbeğini okumadan geçip sonda sessizlik
bırakınca, kalan kelimeler TÜM süreye yayıldı → altyazı sesin 3 saniye gerisine
düştü, video "senaryoda ileri zıplıyor" gibi göründü (gerçek hata: short 757/758).
Ölçüldü: ikinci yarıda altyazı sesin 3.2sn gerisindeydi.

Hem reel hem voiced boru hattı bunu kullanır: aynı kusur ikisinde de vardı.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Protocol

from short_bot.locale import CJK_LANGUAGES
from short_bot.text_normalize import current_language
from short_bot.tts.fidelity import normalize_tokens


class _Timed(Protocol):
    """ASR kelimesi — yalnız bu üç alan okunur (reel/voiced ayrı sınıflar kullanır)."""

    word: str
    start_s: float
    end_s: float


def proportional_times(words: list[str], duration_s: float) -> list[tuple[float, float]]:
    """Ses hizalaması yoksa son çare: süreyi kelime uzunluğuna göre böl."""
    weights = [max(1, len(w)) for w in words]
    total = sum(weights)
    out: list[tuple[float, float]] = []
    cursor = 0.0
    for i, w in enumerate(weights):
        span = duration_s * w / total
        end = duration_s if i == len(weights) - 1 else cursor + span
        out.append((cursor, end))
        cursor = end
    return out


def _key(word: str) -> str:
    t = normalize_tokens(word)
    return t[0] if t else ""


def _cjk_unit_times(script: list[str], asr: list[_Timed]
                    ) -> list[tuple[float, float] | None]:
    """CJK: KARAKTER düzeyinde demir at, zamanları altyazı ÖBEKLERİNE geri topla.

    NEDEN AYRI YOL: Latin dillerinde iki taraf da kelime kelime gelir ve doğrudan
    eşleşir. CJK'de gelmez ve GELEMEZ — senaryoyu biz okunabilir altyazı öbeklerine
    bölüyoruz ('ずぶ濡れの'), whisper ise karakter karakter döküyor ('ず ぶ 濡 れ の').
    Öbek-öbek eşleştirince hiçbir demir tutmuyor, hizalama orantılı dağıtıma düşüyor
    ve altyazı sese HİÇ kilitlenmiyordu. (Bitmiş videoda ölçüldü: final QA "aynı cümle
    4 karede takılı kalmış" dedi.)

    Karakter iki tarafın da üzerinde anlaştığı tek birim. Ekranda yine ÖBEK görünür —
    burada değişen sadece zamanın nereden okunduğu.
    """
    s_chars: list[str] = []
    owner: list[int] = []
    for i, unit in enumerate(script):
        for ch in normalize_tokens(unit):
            s_chars.append(ch)
            owner.append(i)

    a_chars: list[str] = []
    a_spans: list[tuple[float, float]] = []
    for w in asr:
        chars = normalize_tokens(w.word)
        if not chars:
            continue
        # Çok karakterli bir ASR birimi gelirse (whisper bazen birleştirir) süreyi
        # karakterlere eşit böl — kaba ama demir atmaktan iyi.
        span = max(0.0, w.end_s - w.start_s)
        n = len(chars)
        for k, ch in enumerate(chars):
            a_chars.append(ch)
            a_spans.append((w.start_s + span * k / n, w.start_s + span * (k + 1) / n))

    char_times: list[tuple[float, float] | None] = [None] * len(s_chars)
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=s_chars, b=a_chars,
                                               autojunk=False).get_opcodes():
        if tag != "equal":
            continue
        for k in range(i2 - i1):
            char_times[i1 + k] = a_spans[j1 + k]

    out: list[tuple[float, float] | None] = [None] * len(script)
    for idx, t in enumerate(char_times):
        if t is None:
            continue
        u = owner[idx]
        prev = out[u]
        out[u] = (t[0], t[1]) if prev is None else (min(prev[0], t[0]), max(prev[1], t[1]))
    return out


def align_to_asr(script: list[str], asr: list[_Timed],
                 duration_s: float) -> list[tuple[float, float]]:
    """Senaryo kelimelerine ses zamanları verir.

    Eşleşen kelimeler GERÇEK zamanlarını alır. Eşleşmeyenler (whisper farklı yazmış
    ya da TTS okumamış) iki demir atmış komşunun ARASINA orantılı serpiştirilir —
    böylece bir kelimenin kayması sonrasındaki tüm altyazıyı sürüklemez.

    Hiç ASR yoksa ya da hiçbir kelime tutmuyorsa orantılı dağıtıma düşer.
    """
    if not asr:
        return proportional_times(script, duration_s)

    if current_language() in CJK_LANGUAGES:
        times = _cjk_unit_times(script, asr)
    else:
        s_keys = [_key(w) for w in script]
        a_keys = [_key(w.word) for w in asr]

        times = [None] * len(script)
        for tag, i1, i2, j1, j2 in SequenceMatcher(a=s_keys, b=a_keys,
                                                   autojunk=False).get_opcodes():
            if tag != "equal":
                continue
            for k in range(i2 - i1):
                w = asr[j1 + k]
                times[i1 + k] = (w.start_s, w.end_s)

    if not any(t is not None for t in times):
        return proportional_times(script, duration_s)

    out: list[tuple[float, float]] = [(0.0, 0.0)] * len(script)
    i = 0
    while i < len(script):
        if times[i] is not None:
            out[i] = times[i]                                   # type: ignore[assignment]
            i += 1
            continue
        j = i
        while j < len(script) and times[j] is None:
            j += 1
        lo = out[i - 1][1] if i > 0 else 0.0
        hi = times[j][0] if j < len(script) else duration_s     # type: ignore[index]
        hi = max(hi, lo)
        for k, (a, b) in enumerate(proportional_times(script[i:j], hi - lo)):
            out[i + k] = (lo + a, lo + b)
        i = j
    return out
