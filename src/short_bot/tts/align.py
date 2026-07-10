"""Anlatım sesinin kelime-seviyesi hizalaması.

ai33/ElevenLabs v3 timestamp döndürmediği için mp3 yeniden transkript edilip
WhisperX forced-alignment ile kelime zamanları çıkarılır. WhisperX ağır bir
bağımlılıktır (torch): ``pip install short-bot[voice]``.
"""
from __future__ import annotations

import logging
from pathlib import Path

from short_bot.narration import Narration, NarrationTimeline, TimedBeat, TimedWord

log = logging.getLogger(__name__)


def transcribe_words(
    audio_path: Path,
    *,
    language: str,
    model_size: str = "small",
    device: str = "cpu",
    compute_type: str = "int8",
    _whisperx=None,
) -> list[TimedWord]:
    """mp3'ten kelime-seviyesi zaman damgaları çıkarır.

    Align modeli o dil için yoksa boş liste döner — çağıran orantılı dağıtıma
    düşer (video yine üretilir, senkron kabalaşır).
    ``_whisperx`` testler için enjekte edilir.
    """
    wx = _whisperx
    if wx is None:
        try:
            import whisperx as wx  # type: ignore[no-redef]
        except ImportError:
            log.warning(
                "whisperx kurulu değil — kelime senkronu orantılı dağıtıma düşecek. "
                "Kurulum: pip install short-bot[voice]"
            )
            return []

    audio = wx.load_audio(str(audio_path))
    model = wx.load_model(model_size, device, compute_type=compute_type,
                          language=language)
    result = model.transcribe(audio, language=language)

    try:
        align_model, metadata = wx.load_align_model(language_code=language,
                                                    device=device)
    except Exception as e:
        log.warning(f"whisperx align modeli yok ({language}): {e}")
        return []

    aligned = wx.align(result["segments"], align_model, metadata, audio, device,
                       return_char_alignments=False)

    out: list[TimedWord] = []
    for w in aligned.get("word_segments", []):
        if w.get("start") is None or w.get("end") is None:
            continue    # WhisperX bazı kelimelere zaman veremez
        out.append(TimedWord(word=str(w["word"]), start_s=float(w["start"]),
                             end_s=float(w["end"]), seg=-1))
    return out


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
