"""Tepe öncesi dramatik duraklama.

NEDEN VAR: anlatım baştan sona AYNI tempoda akıyor. İnsan anlatıcı en büyük
açıklamadan hemen önce SUSAR — o sessizlik izleyiciye "şimdi bir şey gelecek" der
ve beyni cevaba hazırlar. Kesintisiz akan ses ise vurguyu düzleştirir: tepe, diğer
cümlelerin arasında kaybolur.

NASIL: yeniden seslendirmiyoruz (ai33'e her ek çağrı hem kredi hem de yeni bir
arıza yüzeyi). Üretilmiş mp3'e, tepe beat'inin İLK KELİMESİNDEN hemen önce sessizlik
enjekte ediyoruz. Kesim bir KELİME SINIRINDA olduğu için hiçbir hece bölünmez.

SENKRON: ses değişince altyazı zamanları da değişmeli. Ama saf sessizlik eklemek
konuşmanın hiçbir yerini bozmaz — duraklamadan ÖNCEKİ kelimeler yerinde kalır,
SONRAKİLER tam olarak duraklama kadar kayar. Yani zamanları yeniden ölçmeye
(whisper'ı tekrar koşturmaya) gerek yok: kaydırma KESİN.
"""
from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

# 0.45sn: nefes alacak kadar uzun, "ses kesildi mi?" dedirtecek kadar değil.
REVEAL_PAUSE_S = 0.45
# Duraklama hook'un içine düşmemeli — açılışta sessizlik izleyiciyi kaçırır.
MIN_PAUSE_AT_S = 2.0


def shift_words(words: list, at_s: float, dur_s: float) -> list:
    """``at_s``den itibaren tüm kelimeleri ``dur_s`` kadar ileri kaydır.

    Saf sessizlik enjekte edildiği için bu dönüşüm KESİNDİR: öncesi değişmez,
    sonrası tam olarak duraklama kadar ötelenir.
    """
    out = []
    for w in words:
        if w.start_s >= at_s:
            out.append(replace(w, start_s=w.start_s + dur_s, end_s=w.end_s + dur_s))
        else:
            out.append(w)
    return out


def _audio_format(path: Path, ffprobe: str = "ffprobe") -> tuple[int, str]:
    """(örnekleme hızı, kanal düzeni) — enjekte edilen sessizlik BİREBİR aynı
    biçimde olmalı, yoksa concat filtresi girdileri birleştiremez."""
    p = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=sample_rate,channel_layout", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    parts = (p.stdout or "").strip().split(",")
    sr = int(parts[0]) if parts and parts[0].isdigit() else 44100
    cl = parts[1] if len(parts) > 1 and parts[1] else "mono"
    return sr, cl


def insert_pause(mp3: Path, out: Path, *, at_s: float, dur_s: float = REVEAL_PAUSE_S,
                 ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe") -> Path:
    """``at_s`` anına ``dur_s`` saniyelik sessizlik ekler; yeni dosyayı döndürür."""
    sr, cl = _audio_format(Path(mp3), ffprobe_path)
    graph = (
        f"[0:a]atrim=0:{at_s:.3f},asetpts=N/SR/TB[a];"
        f"[0:a]atrim={at_s:.3f},asetpts=N/SR/TB[b];"
        f"anullsrc=r={sr}:cl={cl},atrim=0:{dur_s:.3f},asetpts=N/SR/TB[s];"
        f"[a][s][b]concat=n=3:v=0:a=1[o]"
    )
    p = subprocess.run(
        [ffmpeg_path, "-y", "-i", str(mp3), "-filter_complex", graph,
         "-map", "[o]", "-c:a", "libmp3lame", "-q:a", "2", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"duraklama eklenemedi: {(p.stderr or '')[-400:]}")
    return Path(out)
