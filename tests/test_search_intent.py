"""Arama niyeti + metadata arama sözlüğü (Aşama 1).

Ölçüm dayanağı (2026-08-20, YouTube Analytics, Aslan Gündem 28 gün):
  SHORTS %96,4 · YT_SEARCH %2,4 · 60+ günlük videolarda arama payı %17,3
  Bizi bulan ilk 25 sorgunun hiçbiri SORU değil; hepsi varlık+niyet kalıbı.
Bu testler o gerçeklerin koda yansımasını kilitler.
"""
from __future__ import annotations

import pytest

from short_bot.search_intent import (
    has_question_intent, intent_label, is_question_query, question_queries,
    ranked_queries,
)


class _Item:
    def __init__(self, related=()):
        self.trend_related = tuple(related)


@pytest.mark.parametrize("q", [
    "asgari ücrete zam gelecek mi", "adalar fayı nerede", "kaç şiddetinde",
    "icardi kimdir", "deprem ne zaman oldu", "maç saat kaçta", "zam ne kadar",
    "neden istifa etti",
])
def test_soru_sorgulari_taninir(q):
    assert is_question_query(q)


@pytest.mark.parametrize("q", [
    "istanbul deprem", "galatasaray transfer son dakika", "gs transfer",
    "çorum fk galatasaray", "aleksey batrakov",
])
def test_varlik_sorgulari_soru_sayilmaz(q):
    assert not is_question_query(q)


def test_aksanli_harfler_kaybolmaz():
    """locale_fold aksan SÖKMEZ — işaret listesi Türkçe harfle yazılmalı.
    'kaç' ASCII'ye düşürülmüş bir listede asla eşleşmiyordu."""
    assert is_question_query("kaç kişi öldü")
    assert is_question_query("nasıl oldu")
    assert is_question_query("niçin ayrıldı")


def test_ranked_queries_varsayilan_trends_sirasini_korur():
    """ÖLÇÜM: kazanan sorgular soru değil varlık+niyet. Soruyu öne çekmek
    ölçülen kazananı aşağı iter — varsayılan sırayı BOZMAZ."""
    q = ["galatasaray transfer son dakika", "batrakov kimdir", "gs transfer"]
    assert ranked_queries(q)[0] == "galatasaray transfer son dakika"
    assert ranked_queries(q, questions_first=True)[0] == "batrakov kimdir"


def test_ranked_queries_tekrar_ve_sinir():
    q = ["gs transfer", "GS Transfer", "galatasaray", "a", "b", "c", "d", "e", "f"]
    out = ranked_queries(q, limit=4)
    assert out[:2] == ["gs transfer", "galatasaray"]   # büyük/küçük harf tekrarı düşer
    assert len(out) == 4


def test_item_niyeti_ve_rozet():
    assert has_question_intent(_Item(["deprem", "kaç şiddetinde"]))
    assert not has_question_intent(_Item(["deprem", "istanbul deprem"]))
    assert intent_label(_Item(["kaç şiddetinde"])) == "soru"
    assert intent_label(_Item(["istanbul deprem"])) == "son dakika"
    assert intent_label(_Item([])) == ""          # Trends dışı kaynak → rozet yok


def test_question_queries_sirasi_korunur():
    assert question_queries(["a", "kim geldi", "b", "ne zaman"]) == ["kim geldi", "ne zaman"]


# --- metadata prompt'u -------------------------------------------------------

class _Ch:
    name = "Aslan Gündem"; handle = "@aslan"; language = "tr"
    keywords = ["galatasaray"]; reel = None; slug = "galatasaray"


def _prompt(**kw):
    from short_bot.youtube.metadata_writer import build_metadata_prompt
    base = dict(channel=_Ch(), script={"header_top": "A", "header_bottom": "B",
                                       "body_paragraph": "gövde"},
                rss_source="NTV", rss_link="https://ntv/1")
    base.update(kw)
    return build_metadata_prompt(**base)


def test_metadata_prompta_trends_sorgulari_girer():
    p = _prompt(script={"body_paragraph": "gövde",
                        "search_queries": ["galatasaray transfer son dakika",
                                           "batrakov kimdir"]})
    assert "ARAMA SÖZLÜĞÜ" in p
    assert "galatasaray transfer son dakika" in p
    # sıra korunur: canlı sorgu başta
    assert p.index("galatasaray transfer son dakika") < p.index("batrakov kimdir")


def test_metadata_prompta_kanalin_kanitli_sozlugu_girer():
    p = _prompt(search_terms=["galatasaray", "gs transfer", "gs son dakika"])
    assert "kanıtlı sorguları" in p and "gs transfer" in p


def test_metadata_kisaltma_ve_bosluk_kurallari():
    """Ölçüm: 'gs transfer' ayda 25K+ izlenme getiriyordu ve hiçbir başlıkta
    geçmiyordu; etiketler 'sondakika' yazarken arama 'son dakika' idi."""
    p = _prompt(search_terms=["gs transfer"])
    assert "KISALTMAYI da yaz" in p
    assert "'sondakika' diye birleştirme" in p
    assert "Konuyla ilgisiz sorguyu EKLEME" in p     # anahtar kelime doldurma YASAK


def test_metadata_sorgu_yoksa_blok_hic_yazilmaz():
    """Trends dışı kanallarda (mizah, kürate) prompt eskisi gibi kalır."""
    assert "ARAMA SÖZLÜĞÜ" not in _prompt()


def test_search_terms_for_odunc_kimlikte_odunc_soszlugu_okur(tmp_path):
    from short_bot.db import init_db, upsert_search_terms
    from short_bot.youtube.metadata_writer import search_terms_for
    eng = init_db(tmp_path / "t.sqlite")
    upsert_search_terms(eng, channel="gundem", terms=[("gündem son dakika", 10)],
                        window_end="2026-08-17")

    class _Yt:
        credentials_from = "gundem"

    class _C:
        slug = "gundem-yorum"; youtube = _Yt()

    assert search_terms_for(eng, _C()) == ["gündem son dakika"]

    class _C2:
        slug = "bos-kanal"; youtube = None
    assert search_terms_for(eng, _C2()) == []


# --- ölçü: aramanın payı -------------------------------------------------------

def test_masa_arama_payini_gosterir_olcum_varsa(tmp_path):
    """Aşama 1'in etkisi ancak bu oran izlenirse görülür. Ölçüm yoksa panel
    UYDURMA sayı göstermez — satır hiç çıkmaz."""
    import json
    from short_bot.db import init_db, kv_touch
    from short_bot.web.routes.gundem import _search_pct

    eng = init_db(tmp_path / "t.sqlite")

    class _C:
        slug = "galatasaray"; youtube = None

    assert _search_pct(eng, _C()) is None
    kv_touch(eng, "traffic:galatasaray", json.dumps({"search_pct": 2.4, "total": 10190995}))
    assert _search_pct(eng, _C()) == 2.4


def test_bozuk_olcum_kaydi_paneli_dusurmez(tmp_path):
    from short_bot.db import init_db, kv_touch
    from short_bot.web.routes.gundem import _search_pct
    eng = init_db(tmp_path / "t.sqlite")

    class _C:
        slug = "x"; youtube = None
    kv_touch(eng, "traffic:x", "{bozuk")
    assert _search_pct(eng, _C()) is None
