"""Koordineli kesinti: 3-5 anda dört kanal birlikte, ötekilerde SESSİZLİK.

Bu modülün varlık sebebi KONTRAST. O yüzden testler yalnız "kesinti seçildi mi"
demiyor; kesinti-DIŞI kesimlerin gerçekten KISILDIĞINI de ölçüyor. Kısılma
olmadan kesintinin hiçbir anlamı yok.
"""
import pytest

from short_bot.reel_interrupt import (LOUD_SFX_GAIN, MAX_INTERRUPTS, MIN_AT_S,
                                      MIN_GAP_S, MIN_INTERRUPTS, MIN_TAIL_S,
                                      PEAK_GUARD_S, QUIET_SFX_GAIN,
                                      impact_cut_indices, select_interrupts,
                                      sfx_gains)
from short_bot.reel_sfx import pick_sfx_per_cut

# 5 segment: hook 0-4, beat0 4-12, beat1 12-22, beat2 22-30, close 30-36
_SEG_STARTS = [4.0, 12.0, 22.0, 30.0]
# Alt-kesimler beat sınırlarında VE beat içinde kesim üretir
_CUTS = [2.0, 4.0, 7.5, 12.0, 16.0, 19.0, 22.0, 26.0, 30.0, 33.0]


def test_kesintiler_BEAT_SINIRINA_oturur():
    """Beat içindeki rastgele bir kesim hiçbir şeyi işaretlemez — sınır işaretler."""
    it = select_interrupts(_CUTS, _SEG_STARTS, duration_s=36.0)
    assert it, "beat sınırına oturan kesim var, seçilmeli"
    for t in it:
        assert t in _SEG_STARTS, f"{t}s bir beat sınırı değil"
    assert 7.5 not in it and 16.0 not in it and 26.0 not in it


def test_sayi_3_ile_5_arasinda():
    it = select_interrupts(_CUTS, _SEG_STARTS, duration_s=36.0)
    assert MIN_INTERRUPTS <= len(it) <= MAX_INTERRUPTS


def test_cok_yakin_kesintiler_elenir():
    """Birbirine yapışan iki kesinti tek bir gürültüye dönüşür."""
    sik = [4.0, 5.0, 6.0, 12.0, 22.0]
    it = select_interrupts(sik, sik, duration_s=36.0)
    for a, b in zip(it, it[1:]):
        assert b - a >= MIN_GAP_S


def test_acilis_ve_kapanis_korunur():
    """Hook oturmadan kesmek açılışı böler; kapanışa binmek loop callback'ini bozar."""
    it = select_interrupts([1.0, 4.0, 35.5], [1.0, 4.0, 35.5], duration_s=36.0)
    assert 1.0 not in it, "hook daha oturmadan kesinti konmamalı"
    assert 35.5 not in it, "kapanışın üstüne kesinti binmemeli"
    assert all(MIN_AT_S <= t <= 36.0 - MIN_TAIL_S for t in it)


def test_tepe_kesinti_olarak_secilmez():
    """Tepenin kendi ses grameri var (riser → impact); üstüne vuruş bindirmeyiz."""
    it = select_interrupts(_CUTS, _SEG_STARTS, duration_s=36.0, peak_s=22.0)
    assert 22.0 not in it
    assert all(abs(t - 22.0) > PEAK_GUARD_S for t in it)
    assert it, "tepe elendi diye tüm kesintiler kaybolmamalı"


def test_beat_sinirina_oturan_kesim_yoksa_bos_doner():
    """Uydurulmuş bir kesinti, kesinti olmamasından kötüdür."""
    assert select_interrupts([3.0, 9.0, 17.0], [4.0, 12.0], duration_s=36.0) == []
    assert select_interrupts([], _SEG_STARTS, duration_s=36.0) == []


def test_kesinti_disi_kesimler_KISILIR():
    """KONTRAST TESTİ — modülün varlık sebebi bu.

    Tüm kesimler aynı seviyede çalarsa kesinti de sıradanlaşır. Kısılmış kesimler,
    yüksek olanı 'olay' yapar.
    """
    it = select_interrupts(_CUTS, _SEG_STARTS, duration_s=36.0, peak_s=22.0)
    g = sfx_gains(_CUTS, it)
    assert len(g) == len(_CUTS)
    for c, gain in zip(_CUTS, g):
        assert gain == (LOUD_SFX_GAIN if c in it else QUIET_SFX_GAIN)
    assert LOUD_SFX_GAIN > 1.0 > QUIET_SFX_GAIN, "kontrast yoksa vurgu da yok"
    # Kesinti, komşusundan en az 3 kat yüksek duyulmalı
    assert LOUD_SFX_GAIN / QUIET_SFX_GAIN >= 3.0


def test_kesinti_yoksa_kazanc_listesi_notr():
    assert sfx_gains(_CUTS, []) == [QUIET_SFX_GAIN] * len(_CUTS)


def test_kesinti_kesimleri_impact_sesi_alir(tmp_path):
    """Kesinti bir VURUŞTUR — 'whoosh' geçiş sesi onu taşıyamaz."""
    (tmp_path / "impact").mkdir(); (tmp_path / "whoosh").mkdir()
    for i in range(3):
        (tmp_path / "impact" / f"i{i}.mp3").write_bytes(b"x")
        (tmp_path / "whoosh" / f"w{i}.mp3").write_bytes(b"x")
    from short_bot.reel_sfx import discover_sfx
    pool = discover_sfx(tmp_path)

    it = select_interrupts(_CUTS, _SEG_STARTS, duration_s=36.0, peak_s=22.0)
    idx = impact_cut_indices(_CUTS, it)
    assert idx, "kesinti seçildiyse indeksleri de bulunmalı"

    # Kurgucu HER kesime 'whoosh' demiş olsa bile kesintide 'impact' kazanmalı
    picks = pick_sfx_per_cut(pool, seed=7, n_cuts=len(_CUTS),
                             sfx_plan=["whoosh"] * len(_CUTS), impact_at=idx)
    for k, p in enumerate(picks):
        beklenen = "impact" if k in idx else "whoosh"
        assert p.parent.name == beklenen, f"kesim {k}: {p.parent.name} ≠ {beklenen}"


def test_impact_kategorisi_yoksa_eski_davranis(tmp_path):
    """Havuzda impact yoksa çökmemeli — plan aynen sürmeli (fail-open)."""
    (tmp_path / "whoosh").mkdir()
    for i in range(3):
        (tmp_path / "whoosh" / f"w{i}.mp3").write_bytes(b"x")
    from short_bot.reel_sfx import discover_sfx
    picks = pick_sfx_per_cut(discover_sfx(tmp_path), seed=1, n_cuts=4,
                             sfx_plan=["whoosh"] * 4, impact_at={0, 2})
    assert all(p.parent.name == "whoosh" for p in picks)


def test_punch_kesinti_anlarinda_da_atesleniyor():
    """Dördüncü kanal: görüntü punch'ı ses vuruşuyla AYNI KAREDE."""
    from short_bot.reel_punch import punch_times
    it = [4.0, 12.0, 30.0]
    p = punch_times(numbers=[], peak_s=22.0, extra=it)
    for t in it:
        assert t in p, f"{t}s kesintisinde punch yok"
    assert 22.0 in p, "tepe punch'ı kaybolmamalı"
    # extra verilmezse eski davranış birebir korunur
    assert punch_times(numbers=[], peak_s=22.0) == [22.0]
