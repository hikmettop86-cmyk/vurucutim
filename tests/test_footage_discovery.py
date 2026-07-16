"""GERÇEK görüntü-önce keşif: konu STOKTAN doğar (kullanıcı önerisi, 2026-07-16).

Eski akış konuyu önce seçip stok arıyordu → kıt havuz = looplu video (858) ya da
üretim düşüşü. Keşif akışı tersine çevirir: stok taranır, EN AZ 4 ayrık klibi
olan özne seçilir, konu o kliplerden türetilir.
"""
from types import SimpleNamespace

import short_bot.footage_discovery as FD
from short_bot.footage_discovery import (DISCOVERY_QUERIES, MIN_SUBJECT_CLIPS,
                                         DiscoveredSubject, _pick_queries,
                                         discover_subject)
from short_bot.footage_sources import FootageCandidate


def _cand(i, source="pexels"):
    return FootageCandidate(url=f"http://x/{i}.mp4", duration_s=15,
                            image=f"http://x/{i}.jpg", source=source, ident=str(i))


class _Src:
    def __init__(self, name, cands):
        self.name = name
        self._c = cands

    def available(self):
        return True

    def search(self, q, *, max_results, orientation):
        return self._c


def test_pick_queries_seedle_doner_ve_farkli():
    assert len(DISCOVERY_QUERIES) >= 12
    for s in range(8):
        qs = _pick_queries(s)
        assert len(qs) == len(set(qs)) == 3          # üç FARKLI sorgu
        assert all(q in DISCOVERY_QUERIES for q in qs)
    assert _pick_queries(3) == _pick_queries(3)       # deterministik
    assert len({tuple(_pick_queries(s)) for s in range(8)}) >= 4   # rotasyon var


def test_discover_ozne_secer_ve_konu_turetir(monkeypatch):
    cands = [_cand(i) for i in range(8)]
    monkeypatch.setattr(FD, "describe_footage",
                        lambda url, **k: f"an archerfish clip {url}", raising=False)
    # describe_footage modül içinde import ediliyor — footage_matcher'da yamala
    import short_bot.footage_matcher as FM
    monkeypatch.setattr(FM, "describe_footage", lambda url, **k: f"an archerfish {url}")

    yakalanan = {}

    def fake_invoke(prompt, schema):
        yakalanan["p"] = prompt
        return DiscoveredSubject(subject_en="archerfish",
                                 topic_tr="Bizimki su üstündeki böceği tazyikli suyla vuruyor",
                                 clip_indices=[0, 2, 3, 5, 6, 7])

    out = discover_subject(sources=[_Src("pexels", cands)], vision_call=object(),
                           invoke=fake_invoke, seed=1,
                           recent_titles=["Okçu Balığı: Suyun Keskin Nişancısı"])
    assert out is not None
    subj, secilen = out
    assert subj.subject_en == "archerfish"
    assert [c.ident for c in secilen] == ["0", "2", "3", "5", "6", "7"]  # seçilen klipler, sırayla
    p = yakalanan["p"]
    assert "Okçu Balığı" in p                 # son başlıklar tekrar-önleme için promptta
    assert str(MIN_SUBJECT_CLIPS) in p        # min klip kuralı promptta
    assert "uydurma" in p.lower()             # kliplerde olmayan olay yasağı


def test_discover_llm_cokerse_none(monkeypatch):
    import short_bot.footage_matcher as FM
    monkeypatch.setattr(FM, "describe_footage", lambda url, **k: "a fish")

    def patlar(prompt, schema):
        raise RuntimeError("LLM down")

    out = discover_subject(sources=[_Src("pexels", [_cand(i) for i in range(6)])],
                           vision_call=object(), invoke=patlar, seed=0)
    assert out is None                        # fail-open: çağıran eski yola düşer


def test_discover_az_aday_none(monkeypatch):
    out = discover_subject(sources=[_Src("pexels", [_cand(0)])],
                           vision_call=object(), invoke=lambda *a: None, seed=0)
    assert out is None


def test_discover_gecersiz_indeksler_none(monkeypatch):
    import short_bot.footage_matcher as FM
    monkeypatch.setattr(FM, "describe_footage", lambda url, **k: "a fish")

    def fake_invoke(prompt, schema):
        return DiscoveredSubject(subject_en="fish", topic_tr="Bizimki bir şeyler yapıyor",
                                 clip_indices=[50, 51, 52, 53, 54, 55])   # havuz dışı

    out = discover_subject(sources=[_Src("pexels", [_cand(i) for i in range(8)])],
                           vision_call=object(), invoke=fake_invoke, seed=0)
    assert out is None


def test_discover_avoid_subjects_prompta_girer(monkeypatch):
    # İlk öznenin klipleri hareket kapısında eriyince ikinci deneme AYNI özneyi
    # seçmesin diye kaçınma listesi prompt'a girer.
    import short_bot.footage_matcher as FM
    monkeypatch.setattr(FM, "describe_footage", lambda url, **k: "an eagle perched")
    yakalanan = {}

    def fake_invoke(prompt, schema):
        yakalanan["p"] = prompt
        return DiscoveredSubject(subject_en="falcon", topic_tr="Bizimki dalışa geçiyor",
                                 clip_indices=[0, 1, 2, 3, 4, 5])

    out = discover_subject(sources=[_Src("pexels", [_cand(i) for i in range(6)])],
                           vision_call=object(), invoke=fake_invoke, seed=0,
                           avoid_subjects=["eagle", "meerkat"])
    assert out is not None
    assert "eagle" in yakalanan["p"] and "meerkat" in yakalanan["p"]
    assert "SEÇME" in yakalanan["p"]
