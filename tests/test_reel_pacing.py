from short_bot.reel_models import TimedWord
from short_bot.reel_pacing import (MIN_SUBCUT_S, TARGET_S, plan_subcuts,
                                    subcut_clip_index)


def test_plan_splits_long_segment_into_target_range():
    spans = [(0.0, 2.0), (2.0, 22.0), (22.0, 24.0)]   # orta segment 20sn
    words = ([TimedWord(word="h", start_s=0.0, end_s=2.0, seg=0)]
             + [TimedWord(word=f"w{i}", start_s=2.0 + i * 0.5, end_s=2.5 + i * 0.5,
                          seg=1) for i in range(40)]
             + [TimedWord(word="c", start_s=22.0, end_s=24.0, seg=2)])
    cuts = plan_subcuts(spans, words, "fast")
    mid = [c for c in cuts if c[0] == 1]
    assert len(mid) >= 8                      # 20sn / ~2sn → çok parça
    lo, hi = TARGET_S["fast"]
    for _seg, a, b in mid[:-1]:               # sonuncusu artık olabilir
        assert lo - 0.6 <= (b - a) <= hi + 0.8
    # segment sırası ve süreklilik korunur
    assert mid[0][1] == 2.0 and mid[-1][2] == 22.0


def test_plan_aligns_cuts_to_word_starts():
    spans = [(0.0, 10.0)]
    words = [TimedWord(word=f"w{i}", start_s=i * 1.0, end_s=i * 1.0 + 0.9, seg=0)
             for i in range(10)]
    cuts = plan_subcuts(spans, words, "fast")
    starts = {round(w.start_s, 3) for w in words} | {0.0, 10.0}
    for _seg, a, b in cuts:
        assert round(a, 3) in starts and round(b, 3) in starts   # cümle ortası yok


def test_short_segment_not_split():
    spans = [(0.0, 1.8)]                      # 2*MIN_SUBCUT_S altı
    words = [TimedWord(word="a", start_s=0.0, end_s=1.8, seg=0)]
    cuts = plan_subcuts(spans, words, "fast")
    assert cuts == [(0, 0.0, 1.8)]
    assert 1.8 < 2 * MIN_SUBCUT_S


def test_every_segment_has_at_least_one_subcut():
    spans = [(0.0, 1.0), (1.0, 9.0), (9.0, 10.0)]
    words = [TimedWord(word=f"w{i}", start_s=i * 0.5, end_s=i * 0.5 + 0.4,
                       seg=min(2, i // 8)) for i in range(20)]
    cuts = plan_subcuts(spans, words, "medium")
    assert {c[0] for c in cuts} == {0, 1, 2}


def test_subcut_clip_index_round_robin():
    subcuts = [(0, 0.0, 2.0), (1, 2.0, 4.0), (1, 4.0, 6.0), (1, 6.0, 8.0),
               (2, 8.0, 10.0)]
    clips_per_seg = {0: 1, 1: 3, 2: 2}
    idx = subcut_clip_index(subcuts, clips_per_seg)
    assert idx == [0, 0, 1, 2, 0]        # seg1'in 3 alt-kesimi 3 farklı klip


def test_reelconfig_retention_flags_default_on():
    from short_bot.config import ReelConfig
    c = ReelConfig(enabled=False)
    assert c.fast_cuts is True and c.number_pop is True and c.visual_loop is True
    c2 = ReelConfig(enabled=False, fast_cuts=False)
    assert c2.fast_cuts is False


# --- KLİP-İÇİ OFSET: aynı klip TEKRAR kullanılınca donmuş kare olmasın ---------
# GERÇEK HATA (short 802, gartengeheimnisse): eski formül ``min(6.0, 1.5*k)`` k>=4'te
# DOYUYORDU. ``visual_loop`` kapanış klibini hook klibine bağladığı için hook klibi
# 5+ alt-kesimde kullanılıyor → kapanışın TÜM alt-kesimleri klibin aynı 6.0 saniyesinden
# başlıyordu. Ölçüldü: videonun son 11.4 saniyesi (%33'ü) DONMUŞ tek kare
# (8 fps'te 90/90 ardışık kare farkı <= 2).

def _802_durum():
    """short 802'nin gerçek şekli.

    seg0 (hook) 2 klip aldı (A, B) → alt-kesimleri round-robin: A, B, A.
    Kapanış ``visual_loop`` yüzünden TEK klip aldı ve o klip hook'un klibi (A);
    kapanış 11.5sn sürdüğü için ~6 alt-kesime bölündü → hepsi A.
    Yani A TOPLAM 8 kez kullanıldı → eski formülde k=4..7 hepsi 6.0'da DOYDU.
    """
    clip_paths = ["A", "B", "A", "C",
                  "A", "A", "A", "A", "A", "A"]
    subcuts = [(0, 0.0, 1.8), (0, 1.8, 3.6), (0, 3.6, 5.4), (1, 5.4, 7.2),
               (4, 7.2, 9.0), (4, 9.0, 10.8), (4, 10.8, 12.6),
               (4, 12.6, 14.4), (4, 14.4, 16.2), (4, 16.2, 18.0)]
    return clip_paths, subcuts


def test_ayni_klibin_tekrarlari_ayni_saniyeden_baslamaz():
    from short_bot.reel_pacing import clip_offsets
    cp, sc = _802_durum()
    off = clip_offsets(cp, sc, {"A": 40.0, "B": 12.0, "C": 12.0})
    a_off = [o for c, o in zip(cp, off) if c == "A"]
    assert len(set(a_off)) == len(a_off), f"aynı ofset tekrarlanıyor: {a_off}"


def test_eski_formulun_doyma_hatasi_geri_gelmesin():
    """Eski formülü YENİDEN KUR ve DONDUĞUNU göster; yeni formül donmamalı."""
    from short_bot.reel_pacing import clip_offsets
    cp, sc = _802_durum()
    # eski: ofset = min(6.0, 1.5 * (bu klibin kaçıncı kullanımı))
    sayac, eski = {}, []
    for c in cp:
        k = sayac.get(c, 0)
        eski.append(min(6.0, 1.5 * k))
        sayac[c] = k + 1
    kapanis_eski = [o for (c, o, (si, _a, _b)) in zip(cp, eski, sc) if si == 4]
    assert len(set(kapanis_eski)) < len(kapanis_eski), (
        "hata gerçekten böyleydi: kapanış alt-kesimleri aynı ofsette DONUYORDU")
    assert kapanis_eski.count(6.0) >= 4, kapanis_eski

    yeni = clip_offsets(cp, sc, {"A": 40.0, "B": 12.0, "C": 12.0})
    kapanis_yeni = [o for (o, (si, _a, _b)) in zip(yeni, sc) if si == 4]
    assert len(set(kapanis_yeni)) == len(kapanis_yeni), (
        f"doyma hatası geri geldi: {kapanis_yeni}")


def test_ofsetler_klibin_suresine_yayilir():
    from short_bot.reel_pacing import clip_offsets
    cp, sc = _802_durum()
    off = clip_offsets(cp, sc, {"A": 40.0, "B": 12.0, "C": 12.0})
    a_off = sorted(o for c, o in zip(cp, off) if c == "A")
    assert a_off[0] == 0.0                    # ilk kullanım klibin başından
    assert a_off[-1] > 25.0, f"40sn klipte en son ofset {a_off[-1]} — yayılmamış"


def test_klip_sonunu_asmaz():
    """Kısa klipte ofset + alt-kesim süresi klibi AŞMAMALI (yoksa son kare donar)."""
    from short_bot.reel_pacing import clip_offsets
    cp, sc = _802_durum()
    off = clip_offsets(cp, sc, {"A": 4.0, "B": 12.0, "C": 12.0})
    for (c, o, (_si, a, b)) in zip(cp, off, sc):
        if c == "A":
            assert o + (b - a) <= 4.0, f"ofset {o} + {b-a}sn > klip süresi 4.0"


def test_tek_kullanimda_klibin_basindan():
    from short_bot.reel_pacing import clip_offsets
    off = clip_offsets(["A", "B"], [(0, 0.0, 2.0), (1, 2.0, 4.0)],
                       {"A": 30.0, "B": 30.0})
    assert off == [0.0, 0.0]


def test_sure_bilinmiyorsa_klibin_basindan_fail_open():
    """ffprobe okunamadı → üretimi düşürme, klibin başından oynat."""
    from short_bot.reel_pacing import clip_offsets
    cp, sc = _802_durum()
    assert clip_offsets(cp, sc, {}) == [0.0] * len(cp)
