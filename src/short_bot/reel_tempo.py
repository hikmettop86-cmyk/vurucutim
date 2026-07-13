"""Anlatım TEMPO BÖLGELERİ: hook hızlı, gövde sabit, tepe yavaş.

NEDEN VAR: TTS baştan sona TEK hızda okur; insan anlatıcı okumaz. Açılışta
hızlıdır (izleyici ilk saniyede kalma kararını verir — ağır bir giriş onu
kaybeder), gövdede sabitlenir, en büyük açıklamada YAVAŞLAR: yavaşlama, cümleye
ağırlık verir ve "şimdi önemli olan geliyor" der. Tek hız, videoyu düzleştirir ve
"makine okumuş" hissi bırakır — kırmaya çalıştığımız otomasyon parmak izinin ta
kendisi.

NASIL: yeniden seslendirmiyoruz (ai33'e her ek çağrı hem kredi hem YENİ bir arıza
yüzeyi — bkz. tts/fidelity). Üretilmiş mp3'ü bölgelere ayırıp her bölgeye ``atempo``
uyguluyor, sonra birleştiriyoruz.

SENKRON: ses gerilip sıkışınca altyazı zamanları da değişmeli. Ama dönüşüm
PARÇALI-DOĞRUSALDIR ve KESİNDİR: bir bölgedeki her an aynı katsayıyla ölçeklenir.
Yani whisper'ı tekrar koşturmaya gerek yok — ``remap_words`` zamanları birebir
hesaplar.

ŞART — ASR: bölge sınırları KELİME ARASINA düşmeli. Segment sınırları gerçek ASR'den
geldiğinde öyledir. Kelime zamanı yoksa sınırlar ORANSAL TAHMİNDİR ve atempo bir
hecenin ortasında hız değiştirir (duyulur bir "kayma" bırakır) — o yüzden çağıran
ASR yokken bu adımı ATLAR. Tahmine göre ses kesmeyiz.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

# Hook: %7 hızlı. Ölçüldü — 1.12 açıkça "acele" duyuluyor (kelimeler birbirine
# giriyor), 1.03 hiç fark edilmiyor. 1.07, 4 saniyelik bir hook'tan ~0.26sn kazanır:
# izleyicinin ilk sözü daha erken duyması demek.
HOOK_TEMPO = 1.07
BODY_TEMPO = 1.00
# Tepe: %7 yavaş. Yavaşlama yalnız TEPE SEGMENTİNE uygulandığı için toplam süreye
# etkisi küçük kalır (~+0.5sn) — kelime bütçesi ve 45sn tavanı bozulmaz.
PEAK_TEMPO = 0.93
# Bölge bu kadar kısaysa hız değişimi bir "kayma" gibi duyulur ve kazanç riski
# karşılamaz → hiç bölge kurma (eski davranış).
MIN_ZONE_S = 1.0
# atempo'nun tek geçişte kabul ettiği aralık.
_TEMPO_MIN, _TEMPO_MAX = 0.5, 2.0


@dataclass(frozen=True)
class Zone:
    start_s: float
    end_s: float
    tempo: float

    @property
    def out_dur_s(self) -> float:
        """Bölgenin YENİ (yeniden hızlandırılmış) süresi."""
        return (self.end_s - self.start_s) / self.tempo


def plan_zones(seg_spans: list[tuple[float, float]], *, peak_seg: int,
               duration_s: float, hook_tempo: float = HOOK_TEMPO,
               body_tempo: float = BODY_TEMPO,
               peak_tempo: float = PEAK_TEMPO) -> list[Zone]:
    """Dört bölge: hook hızlı → gövde sabit → TEPE yavaş → kalan gövde sabit.

    YAVAŞ BÖLGE YALNIZ TEPE SEGMENTİDİR, "tepeden sonuna kadar" DEĞİL. İlk kurulum
    öyleydi ve ölçüm hatayı gösterdi: 36sn'lik videonun 24 saniyesi yavaşlayınca
    süre 1.5sn uzuyordu (hook'un kazandırdığı 0.26sn'nin yanında devasa) — üstelik
    KAPANIŞ da yavaşlıyordu, oysa kapanış çevik olmalı: loop callback'i sürüklenirse
    izleyici başa dönmeden çıkar. Vurgu, yalnız açıklamanın kendisine ait.

    Bölgelerden biri ``MIN_ZONE_S``den kısaysa BOŞ liste döner → çağıran sesi hiç
    ellemez (fail-open). Kısa bir videoda dört bölge zorlamanın anlamı yok.
    """
    n = len(seg_spans)
    # Tepeden SONRA en az bir segment olmalı (kapanış) — yoksa 4. bölge kurulamaz.
    if n < 3 or duration_s <= 0 or not (0 < peak_seg < n - 1):
        return []
    if not all(_TEMPO_MIN <= t <= _TEMPO_MAX
               for t in (hook_tempo, body_tempo, peak_tempo)):
        return []
    bounds = [0.0, seg_spans[0][1], seg_spans[peak_seg][0],
              seg_spans[peak_seg][1], duration_s]
    for a, b in zip(bounds, bounds[1:]):
        if b - a < MIN_ZONE_S:
            return []
    tempos = (hook_tempo, body_tempo, peak_tempo, body_tempo)
    return [Zone(a, b, t) for (a, b), t in zip(zip(bounds, bounds[1:]), tempos)]


def retimed_duration_s(zones: list[Zone]) -> float:
    return sum(z.out_dur_s for z in zones)


def map_time(t: float, zones: list[Zone]) -> float:
    """Eski zaman → yeni zaman. Parçalı-doğrusal, kesin, artan."""
    if not zones:
        return t
    out = 0.0
    for z in zones:
        if t < z.start_s:
            return out                      # bölgelerin önünde (olmamalı) → başa sabitle
        if t < z.end_s:
            return out + (t - z.start_s) / z.tempo
        out += z.out_dur_s
    return out                              # son bölgenin sonrası → toplam süre


def remap_words(words: list, zones: list[Zone]) -> list:
    """Kelime zamanlarını yeni tempoya taşı (dataclasses.replace — tür korunur)."""
    if not zones:
        return list(words)
    return [replace(w, start_s=map_time(w.start_s, zones),
                    end_s=map_time(w.end_s, zones)) for w in words]


def retime(mp3: Path, out: Path, zones: list[Zone], *,
           ffmpeg_path: str = "ffmpeg") -> Path:
    """Her bölgeye kendi ``atempo``sunu uygula ve birleştir; yeni dosyayı döndür.

    Bölgeler [0, duration_s] aralığını kesintisiz kapladığı için concat ORİJİNALİ
    yeniden kurar — yalnız hızları değişmiş olarak. Aralığın DIŞINDA kalan son
    (ölü hava) da böylece atılır.
    """
    if not zones:
        raise ValueError("retime: bölge yok")
    parts, labels = [], []
    for i, z in enumerate(zones):
        parts.append(f"[0:a]atrim={z.start_s:.3f}:{z.end_s:.3f},asetpts=N/SR/TB,"
                     f"atempo={z.tempo:g}[z{i}]")
        labels.append(f"[z{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(zones)}:v=0:a=1[o]")
    p = subprocess.run(
        [ffmpeg_path, "-y", "-i", str(mp3), "-filter_complex", ";".join(parts),
         "-map", "[o]", "-c:a", "libmp3lame", "-q:a", "2", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"tempo bölgeleri uygulanamadı: {(p.stderr or '')[-400:]}")
    return Path(out)
