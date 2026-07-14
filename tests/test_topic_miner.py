"""Kanıt madencisi.

Madenci artık YALNIZ KANIT toplar (outlier başlıkları) — konuyu YAZAN yer
``topic_propose``. Damıtma prompt'unun testleri oraya taşındı
(tests/test_topic_propose.py), akış testleri tests/test_topic_bank_flow.py'de.

Burada kalan: kanıt toplama davranışı (referans-önce, bilinen eleme, kademeli filtre,
sorgu rotasyonu) — hepsi ölçümle kazanıldı ve korunmalı.
"""
import pytest

from short_bot.db import active_bank_topics, init_db, insert_bank_topics
from short_bot.topic_miner import (_search_queries, _short_query, mine_evidence,
                                   refresh_topic_bank)


def _outlier(i, title=None):
    """Hepsi EN SIKI tier'ı geçer (ratio ≥ 3, views ≥ 20K, subs ≤ 500K).

    Oranlar sadece SIRALAMA için farklı — tier filtresi bu testlerin konusu değil,
    ELEMENİN YERİ konusu.
    """
    return {"source_title": title or f"Video {i}", "views": 100_000 + i,
            "subs": 5_000, "ratio": 20.0 - i * 0.1, "video_id": f"v{i}",
            "channel_id": "c", "ref_channel": ""}


class _LC:
    claude_path = "claude"; model = "m"; backend = "openrouter"; api_key = "k"


def _llm(topics, verdicts=None):
    """Sahte Sonnet: öneri + yargı."""
    def _f(prompt, schema, **kw):
        if "verdicts" in schema.model_json_schema().get("properties", {}):
            v = verdicts if verdicts is not None else [
                {"index": i, "solid": True} for i in range(len(topics))]
            return schema.model_validate({"verdicts": v})
        return schema.model_validate({"topics": topics})
    return _f


# --- ELEMENİN YERİ ---------------------------------------------------------
# ÖLÇÜLDÜ (vucudun-gizli-onarim-gucu): yenileme 10 konu üretti, 8'i bankada ZATEN
# OLAN videolardan geliyordu → yalnız 2 yeni. Eleme SONRA yapılıyordu.

def test_BILINEN_videolar_KANIT_HAVUZUNDAN_elenir(monkeypatch):
    """Bankada olan video, kanıt olarak bir daha sunulmamalı."""
    import short_bot.yt_outliers as yo
    havuz = [_outlier(i) for i in range(1, 21)]
    monkeypatch.setattr(yo, "search_outlier_shorts", lambda *a, **kw: havuz)
    monkeypatch.setattr(yo, "channel_outlier_shorts", lambda *a, **kw: [])

    bilinen = {f"video {i}" for i in range(1, 9)}      # Video 1-8 bankada
    out = mine_evidence("nis", api_keys=["K"], llm_call=None, count=12,
                        exclude_sources=bilinen)
    basliklar = {r["source_title"] for r in out}
    assert not (basliklar & {f"Video {i}" for i in range(1, 9)}), \
        "bankada olan video yine kanıt olarak sunuldu"
    assert "Video 9" in basliklar and "Video 20" in basliklar


def test_bilinen_yoksa_havuz_AYNEN_gecer(monkeypatch):
    import short_bot.yt_outliers as yo
    monkeypatch.setattr(yo, "search_outlier_shorts",
                        lambda *a, **kw: [_outlier(i) for i in range(1, 6)])
    monkeypatch.setattr(yo, "channel_outlier_shorts", lambda *a, **kw: [])
    assert len(mine_evidence("nis", api_keys=["K"], llm_call=None, count=12)) == 5


def test_REFERANS_kanallarda_da_bilinen_elenir(monkeypatch):
    """Referans yolu aramayı atlıyor — eleme orada da olmalı."""
    import short_bot.yt_outliers as yo
    monkeypatch.setattr(
        yo, "channel_outlier_shorts",
        lambda ref, **kw: [_outlier(i) for i in range(1, 16)])
    monkeypatch.setattr(yo, "search_outlier_shorts",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("arama yapılmamalıydı")))
    bilinen = {f"video {i}" for i in range(1, 4)}
    out = mine_evidence("nis", api_keys=["K"], llm_call=None, count=12,
                        reference_channels=["@A"], exclude_sources=bilinen)
    basliklar = {r["source_title"] for r in out}
    assert not (basliklar & {"Video 1", "Video 2", "Video 3"})


def test_havuzun_TAMAMI_bilinense_BOS_LISTE(monkeypatch):
    """DAVRANIŞ DEĞİŞTİ: eskiden ValueError('TAZE outlier bulunamadı') fırlıyordu ve
    madencilik TAMAMEN duruyordu. Artık boş liste → üretim KANITSIZ koşar."""
    import short_bot.yt_outliers as yo
    monkeypatch.setattr(yo, "search_outlier_shorts",
                        lambda *a, **kw: [_outlier(i) for i in range(1, 6)])
    monkeypatch.setattr(yo, "channel_outlier_shorts", lambda *a, **kw: [])
    bilinen = {f"video {i}" for i in range(1, 6)}
    assert mine_evidence("nis", api_keys=["K"], llm_call=None, count=12,
                         exclude_sources=bilinen) == []


def test_KANIT_ref_bayragi_TASIR(monkeypatch):
    """topic_propose 'reference' ve 'search' kanıtını ayırt edebilmeli."""
    import short_bot.yt_outliers as yo
    monkeypatch.setattr(yo, "channel_outlier_shorts",
                        lambda ref, **kw: [_outlier(1, "Ref video")])
    monkeypatch.setattr(yo, "search_outlier_shorts",
                        lambda *a, **kw: [_outlier(2, "Arama videosu")])
    out = mine_evidence("nis", api_keys=["K"], llm_call=None, count=12,
                        reference_channels=["@A"])
    bayrak = {r["source_title"]: r["ref"] for r in out}
    assert bayrak["Ref video"] is True
    assert bayrak["Arama videosu"] is False


# --- SORGU ROTASYONU -------------------------------------------------------

def test_sorgular_yenilemeden_yenilemeye_DEGISIR(monkeypatch):
    from short_bot.topic_miner import _QUERY_USE, _SearchQueries

    havuz = ["q1", "q2", "q3", "q4", "q5", "q6"]
    monkeypatch.setattr("short_bot.topic_miner.run_json",
                        lambda p, s, **kw: _SearchQueries(queries=havuz))

    a = _search_queries("nis", "tr", _LC(), rotate=0)
    b = _search_queries("nis", "tr", _LC(), rotate=3)
    assert len(a) == _QUERY_USE and len(b) == _QUERY_USE
    assert a != b, "her yenileme aynı sorguları arıyor → aynı videolar → yeni kanıt yok"
    assert set(a).issubset(havuz) and set(b).issubset(havuz)


def test_rotasyon_ayni_kaydirmada_AYNI(monkeypatch):
    from short_bot.topic_miner import _SearchQueries
    monkeypatch.setattr("short_bot.topic_miner.run_json",
                        lambda p, s, **kw: _SearchQueries(
                            queries=["q1", "q2", "q3", "q4", "q5", "q6"]))
    assert _search_queries("nis", "tr", _LC(), rotate=2) == \
        _search_queries("nis", "tr", _LC(), rotate=2)


def test_short_query_cuts_long_directive():
    assert _short_query("Bilim ve keşif tarihindeki şok edici olayları — ölümcül "
                        "deneyler, kazayla buluşlar anlat.") == \
        "Bilim ve keşif tarihindeki şok edici olayları"
    assert _short_query("") == ""


def test_keywords_KISA_DEVRE_YAPMAZ(monkeypatch):
    """DAVRANIŞ DEĞİŞTİ. Eskiden keywords doluysa TEK sorgu döndürülüp LLM'e HİÇ
    gidilmiyordu — arama havuzu tek sorguya iniyor, niş hızla tükeniyordu.
    Artık keywords LLM'e İPUCU olur; sorguları yine LLM üretir."""
    from short_bot.topic_miner import _QUERY_USE, _SearchQueries
    gorulen = {}

    def _fake(prompt, schema, **kw):
        gorulen["p"] = prompt
        return _SearchQueries(queries=["q1", "q2", "q3", "q4", "q5", "q6"])

    monkeypatch.setattr("short_bot.topic_miner.run_json", _fake)
    out = _search_queries("uzun niş", "tr", _LC(), keywords=["balina", "deniz"])
    assert len(out) == _QUERY_USE, "keywords yine kısa devre yaptı"
    assert "balina, deniz" in gorulen["p"], "keywords ipucu olarak verilmedi"


def test_LLM_yoksa_keywords_fallback():
    """LLM yoksa keywords hâlâ en iyi tahmindir."""
    assert _search_queries("uzun niş", "tr", None, keywords=["balina", "deniz"]) == \
        ["balina deniz"]
    assert _search_queries("bilim tarihi ilginç olaylar", "tr", None) == \
        ["bilim tarihi ilginç"]


def test_sorgu_prompt_u_SOZDE_BILIM_MIKNATISLARINI_yasaklar(monkeypatch):
    """GERÇEK HATA: 'doğal şifa yolları' sorgusu bir BİLİM kanalına mistik şifa
    konusu soktu. Sorgu, çöpü havuza girmeden önce engellemeli."""
    from short_bot.topic_miner import _SearchQueries
    gorulen = {}

    def _fake(prompt, schema, **kw):
        gorulen["p"] = prompt
        return _SearchQueries(queries=["q1", "q2", "q3"])

    monkeypatch.setattr("short_bot.topic_miner.run_json", _fake)
    _search_queries("insan vücudu onarım", "tr", _LC())
    p = gorulen["p"]
    assert "SÖZDE-BİLİM MIKNATISLARI YASAK" in p
    assert "doğal şifa" in p and "detoks" in p


# --- REFERANS KANAL ÖNCELİĞİ -----------------------------------------------

def test_REFERANS_yeterse_ARAMA_yapilmaz(monkeypatch):
    """Kota tasarrufu: referans kanallar ~3 birim, arama ~102 birim."""
    import short_bot.yt_outliers as yo
    arandi = {"n": 0}
    monkeypatch.setattr(
        yo, "channel_outlier_shorts",
        lambda ref, **kw: [{"source_title": f"Ref {ref}{i}", "views": 100_000 * i,
                            "subs": 5_000, "ratio": 10.0 - i, "video_id": f"r{ref}{i}",
                            "channel_id": "", "ref_channel": ref}
                           for i in range(1, 8)])

    def _no_search(*a, **kw):
        arandi["n"] += 1
        return []

    monkeypatch.setattr(yo, "search_outlier_shorts", _no_search)
    out = mine_evidence("bilim", api_keys=["K"], llm_call=None, count=12,
                        reference_channels=["@A", "@B"])
    assert arandi["n"] == 0, "referanslar yeterken arama yapıldı (kota israfı)"
    assert all(r["ref"] for r in out)


def test_REFERANS_azsa_arama_TAMAMLAR(monkeypatch):
    """Referanslar az kanıt verirse arama havuzu tamamlar; ref'ler ÖNDE."""
    import short_bot.yt_outliers as yo
    monkeypatch.setattr(
        yo, "channel_outlier_shorts",
        lambda ref, **kw: [{"source_title": "Ref tek", "views": 900_000,
                            "subs": 5_000, "ratio": 12.0, "video_id": "r1",
                            "channel_id": "", "ref_channel": ref}])
    monkeypatch.setattr(
        yo, "search_outlier_shorts",
        lambda q, **kw: [{"source_title": "Aramadan", "views": 500_000,
                          "subs": 4_000, "ratio": 125.0, "video_id": "s1",
                          "channel_id": "c"}])
    out = mine_evidence("bilim", api_keys=["K"], llm_call=None, count=12,
                        reference_channels=["@A"])
    assert out[0]["source_title"] == "Ref tek", "format-kanıtlı referans önde olmalı"
    assert any(r["source_title"] == "Aramadan" for r in out)


# --- refresh_topic_bank: DEDUP ---------------------------------------------

def test_refresh_inserts_and_dedups(tmp_path, monkeypatch):
    eng = init_db(tmp_path / "t.sqlite")
    insert_bank_topics(eng, "balinalar",
                       [{"topic": "Balinalar neden şarkı söyler", "source_title": "",
                         "views": 1, "subs": 1, "hook_pattern": ""}])
    import short_bot.topic_miner as tm
    monkeypatch.setattr(tm, "mine_evidence", lambda *a, **kw: [])
    res = refresh_topic_bank(
        eng, "balinalar", "q", api_keys=["K"],
        llm=_llm([{"topic": "Balinalar neden şarkı söyler", "source_title": "t1",
                   "views": 5, "subs": 5, "hook_pattern": ""},          # fuzzy-dup
                  {"topic": "Orkalar köpekbalığı avlıyor", "source_title": "t2",
                   "views": 9, "subs": 9, "hook_pattern": ""}]))
    assert res["added"] == 1 and res["skipped_dup"] == 1
    assert len(active_bank_topics(eng, "balinalar")) == 2


def test_refresh_swallows_legacy_kwargs(tmp_path, monkeypatch):
    """Eski çağıranların claude_path/model/run/backend argümanları hata vermez."""
    eng = init_db(tmp_path / "t.sqlite")
    import short_bot.topic_miner as tm
    monkeypatch.setattr(tm, "mine_evidence", lambda *a, **kw: [])
    res = refresh_topic_bank(
        eng, "x", "q", api_keys=["K"],
        llm=_llm([{"topic": "x konusu", "source_title": "t", "views": 1, "subs": 1,
                   "hook_pattern": ""}]),
        claude_path="claude", model=None, run=None, backend="auto")
    assert res["added"] == 1


def test_ayni_kaynak_videodan_ikinci_konu_elenir(monkeypatch, tmp_path):
    """Metin benzerliği YETMİYOR.

    Aynı videodan çıkarılan iki konu FARKLI cümlelerle yazılıyor ("Sigara içtiğinizde
    her organ toksik hasar görür" / "Sigara içtiğinizde yıkıcı bir reaksiyon başlar")
    ve fuzzy oran eşiğin altında kalıyor. Bankada aynı olgunun iki kaydı birikiyordu —
    gerçek durumda 45 aktif konudan 10'u mükerrerdi. Aynı video = aynı olgu.
    """
    from short_bot import topic_miner
    from short_bot.db import all_bank_topics

    eng = init_db(tmp_path / "b.sqlite")
    insert_bank_topics(eng, "ch", [{"topic": "Sigara her organa toksik hasar verir.",
                                    "source_title": "When you Smoking!",
                                    "views": 33_000_000, "subs": 80_000}])
    monkeypatch.setattr(topic_miner, "mine_evidence", lambda *a, **kw: [])
    res = topic_miner.refresh_topic_bank(
        eng, "ch", "nis", api_keys=["k"],
        llm=_llm([{"topic": "Sigara içince yıkıcı bir reaksiyon başlar.",
                   "source_title": "When you Smoking!",      # AYNI kaynak
                   "views": 33_000_000, "subs": 80_000, "hook_pattern": ""},
                  {"topic": "Kalp günde 100 bin kez atar.",
                   "source_title": "Heart Facts",            # FARKLI kaynak
                   "views": 5_000_000, "subs": 20_000, "hook_pattern": ""}]))
    assert res["added"] == 1 and res["skipped_dup"] == 1
    konular = [r["topic"] for r in all_bank_topics(eng, "ch")]
    assert "Kalp günde 100 bin kez atar." in konular
    assert "Sigara içince yıkıcı bir reaksiyon başlar." not in konular


def test_ayni_partide_de_kaynak_tekrari_elenir(monkeypatch, tmp_path):
    from short_bot import topic_miner

    eng = init_db(tmp_path / "b.sqlite")
    monkeypatch.setattr(topic_miner, "mine_evidence", lambda *a, **kw: [])
    res = topic_miner.refresh_topic_bank(
        eng, "ch", "nis", api_keys=["k"],
        llm=_llm([{"topic": "Birinci olgu burada.", "source_title": "Aynı Video",
                   "views": 1_000_000, "subs": 10_000, "hook_pattern": ""},
                  {"topic": "Bambaşka cümleyle ikinci olgu.",
                   "source_title": "Aynı Video",
                   "views": 1_000_000, "subs": 10_000, "hook_pattern": ""}]))
    assert res["added"] == 1 and res["skipped_dup"] == 1
