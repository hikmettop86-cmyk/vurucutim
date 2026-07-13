"""Vurgu punch-in: anlamlı anda görüntüye kısa bir zoom darbesi.

NEDEN VAR: kesme efektleri ve Ken Burns hareketi videoya RİTİM veriyor ama hiçbiri
İÇERİĞE bağlı değil — hepsi zamanlayıcıyla dönüyor. İnsan kurgucu ise kamerayı tam
vurucu kelimede ittirir: "tam YETMİŞ kanserojen" derken görüntü bir tık yaklaşır.
Bu, sesle görüntüyü kilitleyen tek hamledir ve otomasyonun yapmadığı şeydir.

Darbe SERT girer, YUMUŞAK çıkar (%6, 0.35sn): sert giriş vurguyu taşır, yumuşak
çıkış onu fark ettirmeden bırakır. Sabit bir zoom olsaydı KENDİSİ bir örüntü olurdu.
"""
from __future__ import annotations

# %6: fark edilir ama "zıplama" gibi durmaz. Daha fazlası pikselleştirir (kaynak
# zaten 1080x1920'ye ölçeklenmiş) ve ucuz görünür.
PUNCH_AMOUNT = 0.06
# Sönümlenme süresi. Kısası tik gibi, uzunu yavaş zoom gibi durur.
PUNCH_DECAY_S = 0.35
# İfade uzunluğunu sınırla: her darbe filtre grafiğine bir terim ekler.
MAX_PUNCHES = 8
# İki darbe bu kadar yakınsa ikincisi ATILIR — üst üste binen darbeler titreme yapar.
MIN_GAP_S = 0.8


def select_punches(times: list[float]) -> list[float]:
    """Darbe zamanlarını sırala, birbirine çok yakın olanları ve fazlasını at."""
    out: list[float] = []
    for t in sorted(float(t) for t in times if t is not None and t >= 0):
        if out and t - out[-1] < MIN_GAP_S:
            continue
        out.append(t)
        if len(out) >= MAX_PUNCHES:
            break
    return out


def punch_times(numbers: list[dict] | None, peak_s: float | None) -> list[float]:
    """Darbe anları: söylenen SAYILAR + TEPE.

    Sayı ("tam 70 kanserojen") ve reveal, videonun tek gerçek vurgu noktalarıdır.
    Her kesimde darbe atmak ritmi öldürür — darbe SEYREK olduğu için işe yarar.
    """
    ts = [float(n["start_s"]) for n in (numbers or []) if n.get("start_s") is not None]
    if peak_s:
        ts.append(float(peak_s))
    return select_punches(ts)


def punch_vf(times: list[float], *, w: int = 1080, h: int = 1920) -> str:
    """Zoom darbelerini ffmpeg filtre zincirine çevirir. Darbe yoksa boş string.

    ``scale`` kareyi t'ye bağlı olarak BÜYÜTÜR (``eval=frame`` şart: varsayılanda
    ifade yalnız BİR kez hesaplanır ve zoom sabit kalır), merkez ``crop`` fazlasını
    keser → merkeze doğru yaklaşma.

    Neden crop ile daraltıp scale ile büyütmüyoruz: ``crop`` filtresinin ``eval``
    seçeneği YOKTUR — w/h bir kez hesaplanır, zaman ifadesi işlemez (denendi).
    """
    pts = select_punches(times)
    if not pts:
        return ""
    d = PUNCH_DECAY_S
    # term(p): darbe anında 1, d saniye sonra 0 — aradaki her yerde doğrusal iner.
    terms = [f"between(t,{p:.3f},{p + d:.3f})*(1-(t-{p:.3f})/{d:g})" for p in pts]
    peak = terms[0]
    for t in terms[1:]:
        peak = f"max({peak},{t})"
    z = f"1+{PUNCH_AMOUNT:g}*({peak})"
    # Boyutlar ÇİFT olmalı (yuv420p) — tek sayı libx264'ü düşürür.
    # İfadeler TIRNAK içinde: içlerindeki virgüller (between(t,a,b)) aksi hâlde
    # filtre seçeneği ayracı sanılır ve grafik ayrıştırılamaz.
    return (f"scale=w='ceil({w}*({z})/2)*2':h='ceil({h}*({z})/2)*2':eval=frame,"
            f"crop={w}:{h}")
