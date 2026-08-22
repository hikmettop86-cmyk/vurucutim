from short_bot.db import (init_db, insert_bank_topics, active_bank_topics,
                          all_bank_topics, mark_bank_topic_used,
                          reject_bank_topic, bank_last_refresh,
                          bank_hook_patterns)


def _eng(tmp_path):
    return init_db(tmp_path / "t.sqlite")


def _rows(n=3):
    return [{"topic": f"konu {i}", "source_title": f"Title {i}",
             "views": 1000 * (i + 1), "subs": 500,
             "hook_pattern": "sayı + iddia" if i % 2 == 0 else "merak sorusu"}
            for i in range(n)]


def test_insert_and_active_roundtrip(tmp_path):
    eng = _eng(tmp_path)
    assert insert_bank_topics(eng, "balinalar", _rows()) == 3
    active = active_bank_topics(eng, "balinalar", limit=10)
    assert len(active) == 3
    assert {"id", "topic", "source_title", "views", "subs",
            "hook_pattern"} <= set(active[0].keys())
    # başka kanala sızmaz
    assert active_bank_topics(eng, "muhendis") == []


def test_mark_used_and_reject_filtered_out(tmp_path):
    eng = _eng(tmp_path)
    insert_bank_topics(eng, "balinalar", _rows())
    ids = [r["id"] for r in active_bank_topics(eng, "balinalar")]
    mark_bank_topic_used(eng, ids[0])
    reject_bank_topic(eng, ids[1])
    remaining = [r["id"] for r in active_bank_topics(eng, "balinalar")]
    assert remaining == [ids[2]]
    statuses = {r["id"]: r["status"] for r in all_bank_topics(eng, "balinalar")}
    assert statuses[ids[0]] == "used" and statuses[ids[1]] == "rejected"
    mark_bank_topic_used(eng, 99999)   # bilinmeyen id → no-op, hata yok


def test_last_refresh_and_hook_patterns(tmp_path):
    eng = _eng(tmp_path)
    assert bank_last_refresh(eng, "balinalar") is None
    insert_bank_topics(eng, "balinalar", _rows())
    assert bank_last_refresh(eng, "balinalar") is not None
    pats = bank_hook_patterns(eng, "balinalar", limit=5)
    assert set(pats) == {"sayı + iddia", "merak sorusu"}   # distinct
