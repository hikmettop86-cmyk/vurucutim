from pathlib import Path

from short_bot.reel import _match_with_fallback


class _D:
    """match_beat_clip çağrılarını kaydeden sahte ReelDeps."""
    def __init__(self, succeed_on=None):
        self.calls = []          # (query, verify, pool) kayıtları
        self.budgets = []        # her çağrıya geçen tarama bütçesi
        self.succeed_on = succeed_on   # bu query'de klip döndür, aksi None

    def match_beat_clip(self, q, *, api_key, cache_dir, verify, vision_call, deps,
                        topic_pool=None, ffmpeg_path="ffmpeg", budget=None,
                        exclude=None, context="", seen=None, bank=None,
                        hook=False):
        self.calls.append((q, verify, topic_pool))
        self.budgets.append(budget)
        return "clip.mp4" if q == self.succeed_on else None


def test_fallback_passes_pool_and_uses_anchor(tmp_path):
    # tam sorgu + kısaltmalar başarısız → anchor sorgusu (verify+pool) başarır
    d = _D(succeed_on="whale ocean")
    clip, _gated = _match_with_fallback(
        d, "humpback whale calf swimming underwater", topic_q="balina",
        api_key="k", cache_dir=tmp_path, verify=True, vision_call=object(),
        footage_deps=None, topic_pool={"whale", "ocean"}, anchor="whale ocean")
    assert clip == "clip.mp4"
    # pool tüm vision'lı aşamalara taşındı
    verified = [c for c in d.calls if c[1] is True]
    assert verified and all(c[2] == {"whale", "ocean"} for c in verified)
    # anchor sorgusu denendi
    assert any(c[0] == "whale ocean" for c in d.calls)


def test_fallback_safe_last_resort_is_anchor_not_garbage(tmp_path):
    # hiçbir vision'lı arama bulmasa da SON çare anchor sorgusu (verify=False),
    # asla ham ilk-2-kelime değil → off-topic (insan bebeği) girmez
    d = _D(succeed_on=None)
    _match_with_fallback(
        d, "baby whale reaching adulthood", topic_q="balina",
        api_key="k", cache_dir=tmp_path, verify=True, vision_call=object(),
        footage_deps=None, topic_pool={"whale", "ocean"}, anchor="whale ocean")
    # en son çağrı: anchor sorgusu, verify=False
    assert d.calls[-1][0] == "whale ocean"
    assert d.calls[-1][1] is False


def test_fallback_shares_scan_budget_across_strict_stages(tmp_path):
    """KATI geçişin tüm aşamaları AYNI bütçe kovasından yer (tek segment sınırsız
    Storyblocks indirmesi yapamaz). Son çare TAZE bütçe alır.

    NOT: bağlam-b-roll yedeği artık AYRI BİR TARAMA DEĞİL — adaylar katı taramada
    kenara notlanır (bank), yeniden arama/yeniden vision yok."""
    d = _D(succeed_on=None)
    _match_with_fallback(
        d, "uzun bir footage sorgusu", topic_q="konu",
        api_key="k", cache_dir=tmp_path, verify=True, vision_call=object(),
        footage_deps=None, topic_pool=None, anchor="anchor q")
    strict = [b for b, (q, v, p) in zip(d.budgets, d.calls) if v is True]
    assert len(strict) >= 2
    assert all(b is strict[0] for b in strict)          # katı aşamalar: AYNI kova
    assert d.budgets[-1] is not strict[0]              # son çare: taze kova


def test_fallback_reuses_ontopic_clip_instead_of_garbage_anchor(tmp_path):
    """Kapıdan geçen aday yoksa: rastgele çıpa footage'ı DEĞİL, bu videonun
    zaten kabul edilmiş klibi tekrar kullanılır (gerçek şikâyet: açılış karesi
    'science history' çıpasından gelen tablo pazarıydı)."""
    d = _D(succeed_on=None)
    out, _gated = _match_with_fallback(
        d, "oto-kanibalizm soyut sorgu", topic_q="konu",
        api_key="k", cache_dir=tmp_path, verify=True, vision_call=object(),
        footage_deps=None, anchor="science history",
        reuse_clips=[Path("/tmp/onceki_iyi_klip.mp4")])
    assert out == Path("/tmp/onceki_iyi_klip.mp4")
    # çıpa vision'sız İNDİRİLMEDİ (verify=False çağrısı hiç yapılmadı)
    assert all(v is True for (_q, v, _p) in d.calls)


def test_ungated_fallback_uses_own_query_not_generic_anchor(tmp_path):
    """Hiç klip yoksa (ilk işlenen segment): vision'sız ama SEGMENTİN KENDİ
    sorgusuyla ara. Kanal çıpası ('science history') ÇÖP getiriyordu — gerçek
    hata: 'autopsy table doctor' beat'i tablo/poster pazarı footage'ı aldı."""
    class _OnlyUngated(_D):
        """Vision kapılı aşamalar HEP başarısız; yalnız vision'sız çağrı tutar."""
        def match_beat_clip(self, q, *, verify, **kw):
            self.calls.append((q, verify, kw.get("topic_pool")))
            self.budgets.append(kw.get("budget"))
            return "clip.mp4" if verify is False else None

    d = _OnlyUngated()
    out, _gated = _match_with_fallback(
        d, "autopsy table doctor", topic_q="konu", api_key="k", cache_dir=tmp_path,
        verify=True, vision_call=object(), footage_deps=None,
        anchor="science history", reuse_clips=[])
    assert out == "clip.mp4"
    ungated = [q for (q, v, _p) in d.calls if v is False]
    assert ungated[0] == "autopsy table doctor"      # ÖNCE kendi sorgusu
    assert "science history" not in ungated          # jenerik çıpaya hiç gerek kalmadı
