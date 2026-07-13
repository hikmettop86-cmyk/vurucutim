"""KOORDİNELİ KESİNTİ ANLARI: dört kanal AYNI KAREDE ateşlenir.

SORUN — UYARAN ENFLASYONU. Bugün her kesimde SFX çalıyor, her kesimde geçiş efekti
patlıyor, punch her sayıda tetikleniyor. Hepsi ayrı ayrı ve HER ZAMAN. Sonuç: hiçbiri
VURGU değil. Uyaranın her yerde olması, hiçbir yerde olmaması demektir — izleyici beş
saniyede bağışıklık kazanır ve ritim düzleşir. Otomasyon parmak izinin sesli hâli budur:
insan kurgucu her kesimde bağırmaz, SEÇTİĞİ ÜÇ ANDA bağırır.

ÇÖZÜM — KONTRAST. Videoda 3-5 KESİNTİ anı seçilir; o karelerde dört kanal birlikte
ateşlenir (vuruş sesi + tam güçlü ve UZUN geçiş efekti + altyazı darbesi + görüntü
punch'ı). Diğer kesimlerde SFX KISILIR. Vurgu ancak etrafı sessizse vurgudur.

NEREYE: kesinti anları BEAT SINIRLARIDIR — anlatının döndüğü yerler. Alt-kesimlerin
ortasına serpiştirilmiş rastgele bir vuruş, hiçbir şeyi işaretlemez; beat sınırı ise
"yeni bir şey başlıyor" demektir ve ses onu ONAYLAR.

TEPE HARİÇ: en büyük açıklamanın kendi ses grameri zaten var (riser → impact,
bkz. reel.py). Oraya bir de kesinti vuruşu koymak iki impact'i üst üste bindirir.
Görsel koordinasyon tepede de sürer; yalnız SFX vuruşu oraya konmaz.
"""
from __future__ import annotations

# 3-5: araştırmanın verdiği aralık. Altı düşünce kesinti "yok" sayılır, üstünde
# yine enflasyona dönüşür.
MIN_INTERRUPTS = 3
MAX_INTERRUPTS = 5
# Birbirine bu kadar yakın iki kesinti tek bir gürültüye dönüşür.
MIN_GAP_S = 3.0
# Hook daha oturmadan kesmek açılışı böler.
MIN_AT_S = 2.0
# Kapanışın üstüne kesinti binmemeli — loop callback'i temiz duyulmalı.
MIN_TAIL_S = 2.0
# Tepenin kendi riser/impact grameri var; SFX vuruşu bu yarıçapta oraya konmaz.
PEAK_GUARD_S = 0.8
# Kesinti-DIŞI kesimlerde SFX seviyesi çarpanı. Kısmak şart: kontrast olmadan
# kesintinin bir anlamı kalmaz.
QUIET_SFX_GAIN = 0.45
# Kesinti anında SFX seviyesi çarpanı.
LOUD_SFX_GAIN = 1.7
# Kesim zamanı ile segment başlangıcının aynı sayılacağı tolerans (kayan nokta).
_EPS = 0.05


def select_interrupts(cut_times: list[float], seg_starts: list[float], *,
                      duration_s: float, peak_s: float | None = None) -> list[float]:
    """Kesinti anlarını seç: BEAT SINIRINA denk düşen, iyi yayılmış 3-5 kesim.

    ``seg_starts``: beat/kapanış segmentlerinin başlangıç saniyeleri (hook hariç).
    ``peak_s``: tepe anı — kendi ses grameri olduğu için kesinti olarak SEÇİLMEZ.

    Beat sınırına oturan yeterli kesim yoksa liste kısa döner (3'ün altına inebilir);
    zorlama yapmayız — uydurulmuş bir kesinti, kesinti olmamasından kötüdür.
    """
    if not cut_times or duration_s <= 0:
        return []
    sinir = [s for s in seg_starts if MIN_AT_S <= s <= duration_s - MIN_TAIL_S]
    aday = sorted({round(c, 3) for c in cut_times
                   if any(abs(c - s) <= _EPS for s in sinir)})
    if peak_s is not None:
        aday = [c for c in aday if abs(c - peak_s) > PEAK_GUARD_S]
    secili: list[float] = []
    for c in aday:
        if secili and c - secili[-1] < MIN_GAP_S:
            continue
        secili.append(c)
        if len(secili) == MAX_INTERRUPTS:
            break
    return secili


def sfx_gains(cut_times: list[float], interrupts: list[float]) -> list[float]:
    """Kesim başına SFX seviye çarpanı: kesintide yüksek, ötekilerde kısık.

    KONTRAST BURADA DOĞUYOR. Tüm kesimler aynı seviyede çalarsa kesinti anı da
    sıradanlaşır; kısılmış kesimler, yüksek olanı "olay" yapar.
    """
    kesinti = {round(t, 3) for t in interrupts}
    return [LOUD_SFX_GAIN if round(c, 3) in kesinti else QUIET_SFX_GAIN
            for c in cut_times]


def impact_cut_indices(cut_times: list[float], interrupts: list[float]) -> set[int]:
    """Kesinti anlarına denk gelen kesimlerin indeksleri (SFX kategorisi 'impact')."""
    kesinti = {round(t, 3) for t in interrupts}
    return {i for i, c in enumerate(cut_times) if round(c, 3) in kesinti}
