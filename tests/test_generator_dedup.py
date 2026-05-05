import pytest
from unittest.mock import MagicMock

from short_bot.db import init_db
from short_bot.generated_db import insert_generated
from short_bot.generator import check_duplicate, DupVerdict
from tests.test_generator_call import _fake_result


@pytest.fixture
def eng(tmp_path):
    return init_db(tmp_path / "t.sqlite")


def test_layer1_exact_hash_in_db(eng):
    insert_generated(eng, channel="sevgi",
                     text="Aşk, ilk anlayışta başlar.",
                     topic_tag="tanisma", language="tr",
                     status="used", short_id=None)
    result = _fake_result()    # same text
    verdict = check_duplicate(eng, "sevgi", result, forbidden=[],
                              fuzzy_threshold=0.85)
    assert verdict.is_duplicate
    assert verdict.reason == "exact_hash"


def test_layer2_fuzzy_text_against_forbidden(eng):
    result = _fake_result()
    forbidden = ["Aşk, ilk anlayışla başlar."]   # 1 character diff
    verdict = check_duplicate(eng, "sevgi", result, forbidden=forbidden,
                              fuzzy_threshold=0.85)
    assert verdict.is_duplicate
    assert verdict.reason.startswith("fuzzy_text")


def test_layer3_same_tag_medium_fuzzy(eng):
    insert_generated(eng, channel="sevgi",
                     text="Aşk, ilk bakışta değil ilk anlayışta başlamalı.",
                     topic_tag="tanisma", language="tr",
                     status="used", short_id=None)
    # _fake_result text: "Aşk, ilk anlayışta başlar." — same tag (tanisma),
    # fuzzy ratio ~ 0.7+ but < 0.85 → layer2 misses, layer3 catches
    result = _fake_result()
    verdict = check_duplicate(eng, "sevgi", result, forbidden=[],
                              fuzzy_threshold=0.85)
    assert verdict.is_duplicate
    assert verdict.reason.startswith("tag_overlap")


def test_novel_passes_all_layers(eng):
    insert_generated(eng, channel="sevgi", text="Tamamen farklı bir konu.",
                     topic_tag="ozlem", language="tr",
                     status="used", short_id=None)
    result = _fake_result()    # tanisma tag, different text
    verdict = check_duplicate(eng, "sevgi", result, forbidden=[],
                              fuzzy_threshold=0.85)
    assert not verdict.is_duplicate
    assert verdict.reason == ""


def test_other_channel_does_not_collide(eng):
    insert_generated(eng, channel="other", text=_fake_result().text,
                     topic_tag="tanisma", language="tr",
                     status="used", short_id=None)
    verdict = check_duplicate(eng, "sevgi", _fake_result(),
                              forbidden=[], fuzzy_threshold=0.85)
    assert not verdict.is_duplicate
