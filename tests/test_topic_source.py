"""Konunun KAYNAĞI görünür olmalı.

Bir konu ya kanıtlıdır (referans kanal / arama outlier'ı) ya da modelin üretimidir.
İkisi aynı şey değil ve kullanıcı hangisine baktığını bilmeli — bu projenin "sessiz
bozulma olmasın" ilkesinin gereği.
"""
from short_bot.db import all_bank_topics, init_db, insert_bank_topics


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def test_kaynak_YAZILIR_ve_OKUNUR(tmp_path):
    eng = _eng(tmp_path)
    insert_bank_topics(eng, "k", [
        {"topic": "Referanstan gelen konu", "source_title": "V1",
         "views": 100, "subs": 10, "source": "reference"},
        {"topic": "Aramadan gelen konu", "source_title": "V2",
         "views": 50, "subs": 5, "source": "search"},
        {"topic": "Modelin urettigi konu", "source_title": "",
         "views": 0, "subs": 0, "source": "llm"},
    ])
    rows = {r["topic"]: r["source"] for r in all_bank_topics(eng, "k")}
    assert rows["Referanstan gelen konu"] == "reference"
    assert rows["Aramadan gelen konu"] == "search"
    assert rows["Modelin urettigi konu"] == "llm"


def test_kaynak_verilmezse_SEARCH(tmp_path):
    """Eski kayıtlar ve eski çağıranlar 'search' sayılır (migration varsayılanı)."""
    eng = _eng(tmp_path)
    insert_bank_topics(eng, "k", [
        {"topic": "Kaynaksiz konu", "source_title": "V", "views": 1, "subs": 1}])
    assert all_bank_topics(eng, "k")[0]["source"] == "search"
