"""Topic-level dedup via OpenAI embeddings.

The existing dedup (GUID exact + title fuzzy 0.85) misses the common case
of multiple publishers covering the same story with different headlines —
e.g. 'Galatasaray'da Icardi'den duygusal veda' vs 'Mauro Icardi'den
Galatasaray'a mesaj'. Both videos get produced because GUIDs differ and
the headlines aren't string-similar enough. This module adds a third
dedup check: cosine similarity between OpenAI text embeddings."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from short_bot.db import (
    init_db,
    mark_processed,
    fetch_recent_embeddings,
    processed_items,
)
from short_bot.dedup import filter_new
from short_bot.models import NewsItem


def _item(guid: str, title: str) -> NewsItem:
    return NewsItem(
        guid=guid, title=title, link=f"https://x/{guid}",
        source="S", pub_date=None, thumb_url=None, description=None,
    )


def _utcnow():
    return datetime.now(timezone.utc)


# ---- DB layer ----

def test_init_db_adds_embedding_json_column_if_missing(tmp_path):
    """Existing production DBs predate this column; init_db must migrate."""
    db_path = tmp_path / "state.db"
    eng = init_db(db_path)
    with eng.connect() as conn:
        cols = conn.exec_driver_sql(
            "PRAGMA table_info(processed_items)"
        ).fetchall()
    col_names = {c[1] for c in cols}
    assert "embedding_json" in col_names


def test_mark_processed_stores_embedding_when_provided(tmp_path):
    eng = init_db(tmp_path / "state.db")
    emb = [0.1, 0.2, 0.3]
    mark_processed(eng, "g1", "Icardi veda etti", "galatasaray", embedding=emb)
    with eng.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT embedding_json FROM processed_items WHERE guid='g1'"
        ).fetchone()
    assert row is not None
    assert json.loads(row[0]) == emb


def test_mark_processed_without_embedding_leaves_column_null(tmp_path):
    """Backward-compat: callers that don't pass embedding still work."""
    eng = init_db(tmp_path / "state.db")
    mark_processed(eng, "g1", "X", "galatasaray")
    with eng.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT embedding_json FROM processed_items WHERE guid='g1'"
        ).fetchone()
    assert row[0] is None


def test_fetch_recent_embeddings_returns_only_in_window(tmp_path):
    eng = init_db(tmp_path / "state.db")
    # Recent (within window)
    mark_processed(eng, "recent", "X", "galatasaray", embedding=[0.1, 0.2])
    # Manually backdate one as old
    mark_processed(eng, "old", "Y", "galatasaray", embedding=[0.9, 0.8])
    old_ts = _utcnow() - timedelta(days=10)
    with eng.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE processed_items SET processed_at=? WHERE guid='old'",
            (old_ts.replace(tzinfo=None),)
        )
    out = fetch_recent_embeddings(eng, "galatasaray", lookback_days=7)
    assert [0.1, 0.2] in out
    assert [0.9, 0.8] not in out


def test_fetch_recent_embeddings_filters_by_channel(tmp_path):
    eng = init_db(tmp_path / "state.db")
    mark_processed(eng, "g1", "X", "galatasaray", embedding=[1.0, 0.0])
    mark_processed(eng, "f1", "Y", "fenerbahce", embedding=[0.0, 1.0])
    out = fetch_recent_embeddings(eng, "galatasaray", lookback_days=7)
    assert out == [[1.0, 0.0]]


def test_fetch_recent_embeddings_skips_null_rows(tmp_path):
    """processed_items rows from before this feature have NULL embedding —
    skip them silently."""
    eng = init_db(tmp_path / "state.db")
    mark_processed(eng, "old_null", "X", "galatasaray")  # no embedding
    mark_processed(eng, "new", "Y", "galatasaray", embedding=[0.5, 0.5])
    out = fetch_recent_embeddings(eng, "galatasaray", lookback_days=7)
    assert out == [[0.5, 0.5]]


# ---- filter_new integration ----

def _fake_embed(text: str, *, api_key: str) -> list[float]:
    """Deterministic 'embedding' for tests: stable per-keyword vectors."""
    # Simple bag-of-words → vector. Two strings sharing keywords get high cosine.
    keywords = {
        "icardi": [1.0, 0.0, 0.0],
        "veda": [0.9, 0.1, 0.0],
        "galatasaray": [0.5, 0.5, 0.0],
        "osimhen": [0.0, 1.0, 0.0],
        "transfer": [0.0, 0.9, 0.1],
        "putin": [0.0, 0.0, 1.0],
    }
    vec = [0.0, 0.0, 0.0]
    low = text.lower()
    for kw, kv in keywords.items():
        if kw in low:
            vec = [vec[i] + kv[i] for i in range(3)]
    n = (vec[0]**2 + vec[1]**2 + vec[2]**2) ** 0.5
    if n == 0:
        return [0.0, 0.0, 0.0]
    return [v / n for v in vec]


def _acili_vektor(cosine: float) -> list[float]:
    """[1,0] ile cosine'i TAM verilen deger olan birim vektor."""
    import math
    t = math.acos(cosine)
    return [math.cos(t), math.sin(t)]


def test_varsayilan_esik_olculmus_ayni_haber_bandini_eler(tmp_path):
    """VARSAYILAN esik, ayni haberin farkli gazetelerdeki basliklarini elemeli.

    OLCULDU (galatasaray gecmisi: 220 baslik, 24.090 cift). Ayni haber
    0.68-0.72 bandinda kumeleniyor:
      0.698  "Alen Smailagic Galatasaray MCT Technic'te!"
          vs "...Ve Alen Smailagic Galatasaray'da"
      0.691  "Okan Buruk ustunu cizdi, sozlesmesi feshedildi"
          vs "Okan Buruk ustunu cizdi! Nelsson'a veda vakti"
      0.699  "Leao icin ikinci teklifini goren Milan"
          vs "Milan'dan flas Leao cevabi"
    Eski varsayilan 0.72 idi: bu ciftlerin HEPSI dedup'tan geciyor ve ayni haber
    tekrar tekrar video oluyordu.
    """
    eng = init_db(tmp_path / "state.db")
    mark_processed(eng, "g1", "Alen Smailagic Galatasaray MCT Technic'te",
                   "galatasaray", embedding=[1.0, 0.0])
    aday = _item("g2", "Ve Alen Smailagic Galatasaray'da")

    with patch("short_bot.dedup.embed_text",
               side_effect=lambda t, *, api_key: _acili_vektor(0.70)):
        sonuc = filter_new(eng, [aday], "galatasaray", fuzzy_threshold=0.85,
                           openai_api_key="k", embeddings_out={})
    assert sonuc == [], "0.70 cosine ayni haberdir; varsayilan esik elemeli"


def test_varsayilan_esik_farkli_haberi_elemez(tmp_path):
    """0.64-0.66 bandi OLCULDU ve cogunlukla FARKLI haber:
      0.651  "Galatasaray'dan Arsenal cikarmasi"
          vs "Galatasaray Manchester City'nin kalbini istiyor"
    Esigi buraya kadar indirmek gercek haberleri elerdi -> kanal aday bulamaz.
    """
    eng = init_db(tmp_path / "state.db")
    mark_processed(eng, "g1", "Galatasaray'dan Arsenal cikarmasi", "galatasaray",
                   embedding=[1.0, 0.0])
    aday = _item("g2", "Galatasaray Manchester City'nin kalbini istiyor")

    with patch("short_bot.dedup.embed_text",
               side_effect=lambda t, *, api_key: _acili_vektor(0.65)):
        sonuc = filter_new(eng, [aday], "galatasaray", fuzzy_threshold=0.85,
                           openai_api_key="k", embeddings_out={})
    assert len(sonuc) == 1, "0.65 cosine farkli haberdir; elenmemeli"


def test_filter_new_skips_topic_similar_via_embedding(tmp_path):
    """Same story, different headline — must be deduped via embedding."""
    eng = init_db(tmp_path / "state.db")
    # Existing entry: Icardi vedası
    existing_emb = _fake_embed("Icardi veda etti Galatasaray", api_key="k")
    mark_processed(eng, "g1", "Icardi veda etti", "galatasaray",
                   embedding=existing_emb)

    # New candidate: same story, different headline
    new_item = _item("g2", "Galatasaray'da Mauro Icardi'den duygusal veda")
    out_map: dict = {}
    with patch("short_bot.dedup.embed_text", side_effect=_fake_embed):
        result = filter_new(
            eng, [new_item], "galatasaray",
            fuzzy_threshold=0.85,
            openai_api_key="test-key",
            embeddings_out=out_map,
            topic_threshold=0.80,
        )
    assert result == [], "Topic-similar item should be filtered"


def test_filter_new_passes_when_topic_dissimilar(tmp_path):
    eng = init_db(tmp_path / "state.db")
    existing_emb = _fake_embed("Icardi veda etti", api_key="k")
    mark_processed(eng, "g1", "Icardi veda etti", "galatasaray",
                   embedding=existing_emb)

    # New candidate: completely different topic
    new_item = _item("g2", "Putin savaş açıklaması")
    out_map: dict = {}
    with patch("short_bot.dedup.embed_text", side_effect=_fake_embed):
        result = filter_new(
            eng, [new_item], "galatasaray",
            fuzzy_threshold=0.85,
            openai_api_key="test-key",
            embeddings_out=out_map,
            topic_threshold=0.80,
        )
    assert len(result) == 1
    assert result[0].guid == "g2"
    assert "g2" in out_map  # embedding cached for later mark_processed


def test_filter_new_works_without_api_key(tmp_path):
    """Graceful degradation: no key → fall back to existing fuzzy behavior."""
    eng = init_db(tmp_path / "state.db")
    mark_processed(eng, "g1", "Icardi veda etti", "galatasaray")
    new_item = _item("g2", "Galatasaray'da Mauro Icardi'den duygusal veda")
    out_map: dict = {}
    # No openai_api_key → embed_text must NOT be called
    with patch("short_bot.dedup.embed_text") as mock_embed:
        result = filter_new(
            eng, [new_item], "galatasaray",
            fuzzy_threshold=0.85,
            openai_api_key=None,
            embeddings_out=out_map,
        )
        assert mock_embed.call_count == 0
    # Without embedding dedup, fuzzy can't catch this — new item passes
    assert len(result) == 1
    assert out_map == {}


def test_filter_new_graceful_when_embedding_fails(tmp_path):
    """Network error on embed → continue with fuzzy-only check."""
    from short_bot.embeddings import EmbeddingError

    eng = init_db(tmp_path / "state.db")
    mark_processed(eng, "g1", "Icardi veda etti", "galatasaray",
                   embedding=_fake_embed("Icardi veda", api_key="k"))
    new_item = _item("g2", "Mauro Icardi'den duygusal veda")
    out_map: dict = {}
    with patch("short_bot.dedup.embed_text",
               side_effect=EmbeddingError("network")):
        result = filter_new(
            eng, [new_item], "galatasaray",
            fuzzy_threshold=0.85,
            openai_api_key="test-key",
            embeddings_out=out_map,
        )
    # Embedding failed → fuzzy-only fallback → new item passes
    assert len(result) == 1
