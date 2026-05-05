import pytest

from short_bot.db import init_db
from short_bot.generated_db import (
    insert_generated, recent_generated_texts, exists_hash,
    recent_by_tag, topic_distribution, text_hash,
)


@pytest.fixture
def eng(tmp_path):
    return init_db(tmp_path / "t.sqlite")


def test_insert_and_exists_hash(eng):
    insert_generated(eng, channel="sevgi", text="Aşk her şeydir.",
                     topic_tag="ask", language="tr", status="used",
                     short_id=None)
    h = text_hash("Aşk her şeydir.")
    assert exists_hash(eng, "sevgi", h)
    assert not exists_hash(eng, "sevgi", "0" * 64)
    assert not exists_hash(eng, "other-channel", h)


def test_recent_generated_texts_only_used(eng):
    insert_generated(eng, channel="sevgi", text="A", topic_tag="x",
                     language="tr", status="used", short_id=None)
    insert_generated(eng, channel="sevgi", text="B", topic_tag="x",
                     language="tr", status="discarded", short_id=None)
    insert_generated(eng, channel="sevgi", text="C", topic_tag="x",
                     language="tr", status="used", short_id=None)
    texts = recent_generated_texts(eng, "sevgi", limit=10)
    assert set(texts) == {"A", "C"}    # B excluded


def test_recent_generated_texts_respects_limit_and_order(eng):
    for i in range(5):
        insert_generated(eng, channel="sevgi", text=f"text-{i}",
                         topic_tag="x", language="tr", status="used",
                         short_id=None)
    texts = recent_generated_texts(eng, "sevgi", limit=3)
    assert len(texts) == 3
    assert texts[0] == "text-4"   # most recent first


def test_recent_by_tag_filters_tag_and_window(eng):
    insert_generated(eng, channel="sevgi", text="patient",
                     topic_tag="sabir", language="tr", status="used",
                     short_id=None)
    insert_generated(eng, channel="sevgi", text="hopeful",
                     topic_tag="umut", language="tr", status="used",
                     short_id=None)
    insert_generated(eng, channel="sevgi", text="another patient",
                     topic_tag="sabir", language="tr", status="used",
                     short_id=None)
    found = recent_by_tag(eng, "sevgi", tag="sabir", days=7, limit=10)
    assert set(found) == {"patient", "another patient"}


def test_topic_distribution(eng):
    for _ in range(3):
        insert_generated(eng, channel="sevgi", text=f"a-{_}", topic_tag="ask",
                         language="tr", status="used", short_id=None)
    insert_generated(eng, channel="sevgi", text="b1", topic_tag="umut",
                     language="tr", status="used", short_id=None)
    dist = topic_distribution(eng, "sevgi", days=7)
    assert dist == {"ask": 3, "umut": 1}


def test_unique_constraint_raises_on_duplicate_hash(eng):
    from sqlalchemy.exc import IntegrityError
    insert_generated(eng, channel="sevgi", text="same",
                     topic_tag="x", language="tr", status="used",
                     short_id=None)
    with pytest.raises(IntegrityError):
        insert_generated(eng, channel="sevgi", text="same",
                         topic_tag="x", language="tr", status="used",
                         short_id=None)
