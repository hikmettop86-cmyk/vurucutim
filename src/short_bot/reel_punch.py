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


def punch_times(numbers: list[dict] | None, peak_s: float | None,
                extra: list[float] | None = None) -> list[float]:
    """Darbe anları: söylenen SAYILAR + TEPE + ``extra`` (koordineli kesintiler).

    Sayı ("tam 70 kanserojen") ve reveal, videonun tek gerçek vurgu noktalarıdır.
    Her kesimde darbe atmak ritmi öldürür — darbe SEYREK olduğu için işe yarar.

    ``extra``: kesinti anları (bkz. reel_interrupt). Orada ses vuruşu ve efekt zaten
    ateşleniyor; punch onlarla AYNI KAREDE olunca üçü tek bir "olay" olarak algılanır.
    MIN_GAP_S ve MAX_PUNCHES yine geçerli — seyreklik korunur.
    """
    ts = [float(n["start_s"]) for n in (numbers or []) if n.get("start_s") is not None]
    if peak_s:
        ts.append(float(peak_s))
    ts.extend(float(t) for t in (extra or []))
    return select_punches(ts)


def punch_vf(times: list[float], *, w: int = 1080, h: int = 1920,
             fps: int = 30) -> str:
    """Zoom darbelerini ffmpeg filtre zincirine çevirir. Darbe yoksa boş string.

    ``zoompan`` kullanılır — kadrajı MERKEZDEN yakınlaştırmanın çalışan tek yolu bu.

    ÇALIŞMAYAN yollar (ikisi de denendi ve ÖLÇÜLDÜ):
      • ``crop`` ile daraltmak: crop'un ``eval`` seçeneği YOK, w/h bir kez hesaplanır.
      • ``scale(eval=frame)`` + ``crop``: kare büyüyor ama crop'un ``iw``'si BAĞLANTININ
        sabit genişliğini görüyor, gerçek kare genişliğini değil → x hep 0 çıkıyor ve
        zoom merkeze değil SOL-ÜST KÖŞEYE çakılıyor (karelerde doğrulandı: darbe
        anında sol-üstteki içerik yerinde kalıyordu, oysa merkez zoomda kadraj dışına
        çıkmalıydı).

    zoompan'de zaman ``on`` (çıkış kare no) üzerinden kurulur; d=1 olduğu için
    ``t = on/fps``.
    """
    pts = select_punches(times)
    if not pts:
        return ""
    d = PUNCH_DECAY_S
    tv = f"(on/{fps})"   # zoompan'de 't' yok — kare numarasından zaman üret
    # term(p): darbe anında 1, d saniye sonra 0 — aradaki her yerde doğrusal iner.
    terms = [f"between({tv},{p:.3f},{p + d:.3f})*(1-({tv}-{p:.3f})/{d:g})" for p in pts]
    peak = terms[0]
    for t in terms[1:]:
        peak = f"max({peak},{t})"
    z = f"1+{PUNCH_AMOUNT:g}*({peak})"
    return (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={w}x{h}:fps={fps}")
