"""Uyaran yoğunluğu: görsel değişim her 1.5-3 saniyede bir olmalı.

GERÇEK ÖLÇÜM (short_id=756): 34.4 saniyelik videoda YALNIZ 9 alt-kesim =
3.8 saniyede bir değişim. Seed "slow" temposunu seçmişti (3.2-4.5sn).

Araştırma: görsel değişim her 1.5-2.0sn (10 saniyede 5-7 değişim). 4/10s'nin altı
"ağır" okunuyor. Bizim "slow" havuzda olduğu sürece videolarının dörtte biri bu
eşiğin ALTINA düşüyor.

ÖNEMLİ: "görsel değişim" yalnız KESİM değil — zoom/push/pan da sayılır. Ken Burns
ve vurgu punch-in'leri (Faz 2) gelince yoğunluğu onlar da taşıyacak ve daha yavaş
tempo tekrar anlamlı olabilir. Şimdilik TEK değişim aracımız kesim, o yüzden
tempo havuzu yoğunluk hedefini tutmalı.

MALİYET YOK: daha çok alt-kesim, segmentin ZATEN indirilmiş kliplerini dönüşümlü
kullanır — ekstra footage indirmesi/vision çağrısı gerekmez.
"""
from short_bot.reel_pacing import TARGET_S, plan_subcuts
from short_bot.reel_variation import CUT_PACINGS


def test_no_pacing_option_is_slower_than_the_density_target():
    """Havuzdaki HİÇBİR tempo 3 saniyeden yavaş olmamalı."""
    for name in set(CUT_PACINGS):
        lo, hi = TARGET_S[name]
        assert hi <= 3.2, (
            f"'{name}' temposu {hi}sn'ye kadar çıkıyor → 10 saniyede 3 değişim; "
            f"araştırma 5-7 istiyor")


def test_slow_is_not_in_the_rotation():
    """'slow' (3.2-4.5sn) uyaran yoğunluğunun ALTINDA — havuzdan çıkarıldı."""
    assert "slow" not in CUT_PACINGS


def test_a_35s_video_gets_enough_cuts():
    """34 saniyelik videoda 9 kesim AZDI. Hedef: en az ~12."""
    spans = [(0.0, 4.0), (4.0, 14.0), (14.0, 24.0), (24.0, 30.0), (30.0, 34.0)]
    words = [{"word": f"w{i}", "start_s": i * 0.5, "end_s": i * 0.5 + 0.4}
             for i in range(68)]

    class _W:
        def __init__(self, d):
            self.word = d["word"]; self.start_s = d["start_s"]; self.end_s = d["end_s"]

    tw = [_W(w) for w in words]
    for pacing in set(CUT_PACINGS):
        cuts = plan_subcuts(spans, tw, pacing)
        per_10s = len(cuts) / 3.4
        assert per_10s >= 3.5, (
            f"'{pacing}': 10 saniyede {per_10s:.1f} değişim — çok az")


def test_peak_s_verilince_tempo_tepeye_dogru_sikisir():
    # Merak mimarisi: alt-kesim süresi hook→tepe kademeli kısalır (~1.25x→0.75x),
    # tepe sonrası rahatlar. MIN_SUBCUT_S tabanı korunur.
    from short_bot.reel_models import TimedWord
    from short_bot.reel_pacing import plan_subcuts
    words = [TimedWord(word=f"w{i}", start_s=i * 0.3, end_s=i * 0.3 + 0.25, seg=0)
             for i in range(200)]
    spans = [(0.0, 20.0), (20.0, 40.0), (40.0, 60.0)]
    ramp = plan_subcuts(spans, words, "medium", peak_s=40.0)
    d_ramp = [(b - a) for (_s, a, b) in ramp]

    def ort(cuts, lo, hi):
        v = [(b - a) for (_s, a, b) in cuts if lo <= a < hi]
        return sum(v) / max(1, len(v))

    # tepe öncesi son çeyrek (30-40s) ortalaması açılış çeyreğinden KISA
    assert ort(ramp, 30, 40) < ort(ramp, 0, 10)
    assert all(d >= 1.2 - 1e-9 for d in d_ramp)     # MIN_SUBCUT_S tabanı
    # peak_s verilmeyince davranış birebir eski (regresyon)
    duz1 = plan_subcuts(spans, words, "medium")
    duz2 = plan_subcuts(spans, words, "medium", peak_s=None)
    assert duz1 == duz2
