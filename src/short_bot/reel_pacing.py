"""Segment-içi hızlı kesim planı (retention).

Kesim SADECE segment sınırlarındayken 45sn video ≈ 6.4sn/kesim oluyordu; tutan
shorts'larda insan editör 1.5-3sn'de bir keser. Bu modül her segmenti hedef
aralığa böler ve kesimleri KELİME BAŞLANGICINA hizalar (cümle ortasında kesme yok).

``ReelConfig.cut_pacing`` ve ``VariationProfile.cut_pacing`` zaten vardı ama
hiçbir yere bağlı değildi (ölü kod) — bu modül onu canlandırır.
"""
from __future__ import annotations

# pacing → (min, max) hedef alt-kesim süresi (saniye)
TARGET_S = {"fast": (1.5, 2.2), "medium": (2.2, 3.2), "slow": (3.2, 4.5)}
MIN_SUBCUT_S = 1.2   # bundan kısa alt-kesim göz yorucu → segment bölünmez


def _target(pacing: str) -> tuple[float, float]:
    return TARGET_S.get(pacing, TARGET_S["medium"])


def _word_starts_in(words, a: float, b: float) -> list[float]:
    """(a,b) aralığındaki kelime başlangıçları (artan)."""
    return sorted(w.start_s for w in (words or []) if a < w.start_s < b)


def plan_subcuts(seg_spans, words, pacing: str = "medium") -> list[tuple[int, float, float]]:
    """Her segmenti hedef aralığa böl → [(seg_index, start_s, end_s), ...].

    Kesim sınırları kelime başlangıcına hizalanır. Segment 2*MIN_SUBCUT_S'ten
    kısaysa bölünmez. Her segment en az bir parça döndürür (sıra korunur).
    """
    lo, hi = _target(pacing)
    out: list[tuple[int, float, float]] = []
    for si, (a, b) in enumerate(seg_spans or []):
        span = max(0.0, b - a)
        if span < 2 * MIN_SUBCUT_S:
            out.append((si, a, b))
            continue
        starts = _word_starts_in(words, a, b)
        cut_at: list[float] = []
        cursor = a
        target = (lo + hi) / 2.0
        while True:
            want = cursor + target
            if b - want < MIN_SUBCUT_S:       # kalan çok kısa → son parça uzasın
                break
            # hedefe en yakın kelime başlangıcı (min parça süresi korunarak)
            cands = [s for s in starts
                     if s - cursor >= MIN_SUBCUT_S and b - s >= MIN_SUBCUT_S]
            if not cands:
                break
            pick = min(cands, key=lambda s: abs(s - want))
            if pick - cursor > hi + 1.0:      # hizalama çok uzattıysa vazgeç
                break
            cut_at.append(pick)
            cursor = pick
        bounds = [a, *cut_at, b]
        for i in range(len(bounds) - 1):
            out.append((si, bounds[i], bounds[i + 1]))
    return out


def subcut_clip_index(subcuts, clips_per_seg: dict[int, int]) -> list[int]:
    """Her alt-kesim, segmentinin klipleri arasında round-robin döner.

    Böylece ardışık alt-kesimler FARKLI klip gösterir (gerçek çeşitlilik).
    Dönüş: alt-kesimle aynı boyda, segment-içi klip indeksleri.
    """
    seen: dict[int, int] = {}
    out: list[int] = []
    for si, _a, _b in subcuts:
        n = max(1, int(clips_per_seg.get(si, 1)))
        k = seen.get(si, 0)
        out.append(k % n)
        seen[si] = k + 1
    return out


def clip_offsets(clip_paths, subcuts, durations) -> list[float]:
    """Her alt-kesim için klip-İÇİ başlangıç saniyesi.

    Aynı klip birden çok alt-kesimde kullanılınca hepsi klibin AYNI yerinden
    başlarsa izleyici donmuş bir kare görür. Bu yüzden bir klibin N kullanımı
    klibin kullanılabilir süresine EŞİT ARALIKLA yayılır.

    GERÇEK HATA (short 802, gartengeheimnisse): eski formül ``min(6.0, 1.5*k)``
    idi ve k>=4'te DOYUYORDU. ``visual_loop`` kapanış klibini hook klibine
    bağladığı için hook klibi 5+ kez kullanılıyor → kapanışın BÜTÜN alt-kesimleri
    klibin aynı 6.0 saniyesinden başlıyordu. Ölçüldü: videonun son 11.4 saniyesi
    (%33'ü) donmuş tek kare — 8 fps'te 90/90 ardışık kare farkı <= 2.

    durations: {str(path): süre_s}. Süresi bilinmeyen klip 0.0 ofset alır
    (kırpmaktansa klibin başından oynat — fail-open).
    """
    toplam: dict[str, int] = {}
    for c in clip_paths:
        toplam[str(c)] = toplam.get(str(c), 0) + 1
    sayac: dict[str, int] = {}
    out: list[float] = []
    for i, c in enumerate(clip_paths):
        anahtar = str(c)
        k = sayac.get(anahtar, 0)
        sayac[anahtar] = k + 1
        n = toplam[anahtar]
        dur = float(durations.get(anahtar) or 0.0)
        # bu alt-kesim klipten kaç saniye TÜKETECEK
        need = 0.0
        if i < len(subcuts):
            _si, a, b = subcuts[i]
            need = max(0.0, float(b) - float(a))
        # PAY: klibin sonuna dayanıp kare donmasın diye küçük bir emniyet
        usable = dur - need - 0.2
        if n <= 1 or usable <= 0.0:
            out.append(0.0)
            continue
        out.append(round(usable * k / n, 2))
    return out
