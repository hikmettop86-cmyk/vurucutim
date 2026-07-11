"""Anlatım sesinin kelime-seviyesi hizalaması.

ai33/ElevenLabs v3 timestamp döndürmediği için mp3 yeniden transkript edilip
faster-whisper ile kelime zamanları çıkarılır. faster-whisper opsiyonel bir
bağımlılıktır: ``pip install short-bot[whisper]``. Kurulu değilse çağıran
orantılı dağıtıma düşer (video yine üretilir, senkron kabalaşır).

Cihaz otomatik seçilir (CUDA varsa GPU, yoksa CPU) ve kalite kademesi
buna göre ayarlanır; ``quality``/``device`` ile elle geçilebilir.
"""
from __future__ import annotations

import logging
from pathlib import Path

from short_bot.narration import Narration, NarrationTimeline, TimedBeat, TimedWord

log = logging.getLogger(__name__)


def _detect_device(device: str) -> str:
    """``auto`` ise CUDA cihazı var mı diye bakar; yoksa CPU'ya düşer."""
    if device != "auto":
        return device
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _resolve_whisper(quality: str, device: str) -> tuple[str, str, str]:
    """(model_size, device, compute_type) üçlüsünü kalite + cihaza göre türetir."""
    dev = _detect_device(device)
    ct = "float16" if dev == "cuda" else "int8"
    if quality == "high":
        ms = "large-v3"
    elif quality == "medium":
        ms = "medium"
    elif quality == "low":
        ms = "base"
    else:  # auto — GPU varsa büyük model, yoksa hızlı olsun
        ms = "large-v3" if dev == "cuda" else "base"
    return ms, dev, ct


def _import_model():
    """faster-whisper ``WhisperModel``'i döndürür; kurulu değilse ``None``."""
    try:
        from faster_whisper import WhisperModel
        return WhisperModel
    except ImportError:
        return None


def transcribe_words(
    audio_path: Path,
    *,
    language: str,
    quality: str = "auto",
    device: str = "auto",
    _model=None,
) -> list[TimedWord]:
    """mp3'ten kelime-seviyesi zaman damgaları çıkarır.

    faster-whisper kurulu değilse, model yüklenemezse ya da ``quality="off"``
    ise boş liste döner — çağıran orantılı dağıtıma düşer (video yine üretilir,
    senkron kabalaşır). ``_model`` testler için enjekte edilir.
    """
    if quality == "off":
        return []
    model = _model
    if model is None:
        WhisperModel = _import_model()
        if WhisperModel is None:
            log.warning(
                "faster-whisper kurulu değil — kelime senkronu orantılı "
                "dağıtıma düşecek. Kurulum: pip install short-bot[whisper]"
            )
            return []
        ms, dev, ct = _resolve_whisper(quality, device)
        try:
            model = WhisperModel(ms, device=dev, compute_type=ct)
        except Exception as e:
            log.warning(f"faster-whisper model yüklenemedi ({e}) — orantılı dağıtım.")
            return []
    try:
        segments, _info = model.transcribe(str(audio_path), language=language,
                                           word_timestamps=True)
        out: list[TimedWord] = []
        for seg in segments:
            for w in (getattr(seg, "words", None) or []):
                if w.start is None or w.end is None:
                    continue    # bazı kelimelere zaman verilemeyebilir
                out.append(TimedWord(word=str(w.word).strip(), start_s=float(w.start),
                                     end_s=float(w.end), seg=-1))
        return out
    except Exception as e:
        log.warning(f"faster-whisper transcribe hatası ({e}) — orantılı dağıtım.")
        return []


def _segment_word_counts(narration: Narration) -> list[int]:
    return [len(s.split()) for s in narration.segments()]


def _proportional_times(words: list[str], duration_s: float) -> list[tuple[float, float]]:
    """Kelimelere karakter uzunluğuna orantılı, boşluksuz zaman dilimleri ver."""
    weights = [max(1, len(w)) for w in words]
    total = sum(weights)
    times: list[tuple[float, float]] = []
    cursor = 0.0
    for i, wgt in enumerate(weights):
        span = duration_s * wgt / total
        start = cursor
        end = duration_s if i == len(weights) - 1 else cursor + span
        times.append((start, end))
        cursor = end
    return times


def build_timeline(
    narration: Narration,
    asr_words: list[TimedWord],
    *,
    duration_s: float,
) -> NarrationTimeline:
    """Anlatım metnini ses zamanlarıyla eşleyip render zaman çizelgesi kurar.

    Gösterilen kelimeler HER ZAMAN anlatım metninden gelir (ASR yanlış
    duymuş olabilir); ASR yalnızca zamanları sağlar. Kelime sayıları
    tutmuyorsa süre orantılı dağıtılır.
    """
    if duration_s <= 0:
        raise ValueError(f"duration_s pozitif olmalı, got {duration_s}")

    counts = _segment_word_counts(narration)
    words_flat: list[str] = []
    segs_flat: list[int] = []
    for seg_idx, seg_text in enumerate(narration.segments()):
        for w in seg_text.split():
            words_flat.append(w)
            segs_flat.append(seg_idx)

    if len(asr_words) == len(words_flat) and asr_words:
        times = [(w.start_s, w.end_s) for w in asr_words]
    else:
        if asr_words:
            log.warning(
                f"ASR kelime sayısı ({len(asr_words)}) anlatımla "
                f"({len(words_flat)}) tutmadı — orantılı dağıtım kullanılıyor"
            )
        times = _proportional_times(words_flat, duration_s)

    timed = [TimedWord(word=w, start_s=t[0], end_s=t[1], seg=s)
             for w, s, t in zip(words_flat, segs_flat, times)]

    beats: list[TimedBeat] = []
    offset = counts[0]                      # hook kelimeleri atlanır
    for i, beat in enumerate(narration.beats):
        n = counts[i + 1]
        chunk = timed[offset:offset + n]
        if chunk:
            beats.append(TimedBeat(on_screen=beat.on_screen,
                                   start_s=chunk[0].start_s,
                                   end_s=chunk[-1].end_s))
        offset += n

    return NarrationTimeline(words=timed, beats=beats, duration_s=duration_s,
                             hook=narration.hook, loop_close=narration.loop_close)
