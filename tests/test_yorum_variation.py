"""Yorum çeşitleme: her video farklı biçim, son videolar tekrarlanmaz."""
from __future__ import annotations

from short_bot.yorum_variation import ANGLES, CLOSINGS, OPENINGS, pick_variation


def test_variation_is_deterministic_for_same_story():
    a = pick_variation(seed_text="gundem-yorum:https://x/1")
    b = pick_variation(seed_text="gundem-yorum:https://x/1")
    assert a == b and a.key.count("/") == 2


def test_different_stories_get_different_shapes():
    keys = {pick_variation(seed_text=f"ch:{i}").key for i in range(30)}
    assert len(keys) >= 15          # 8x8x7 bankadan geniş dağılım


def test_recent_openings_and_angles_are_avoided():
    first = pick_variation(seed_text="ch:1")
    second = pick_variation(seed_text="ch:2", recent=[first.key])
    third = pick_variation(seed_text="ch:3", recent=[second.key, first.key])
    assert second.opening_key != first.opening_key
    assert second.angle_key != first.angle_key
    assert third.opening_key not in {first.opening_key, second.opening_key}
    assert third.angle_key not in {first.angle_key, second.angle_key}


def test_exhausted_bank_still_returns_a_shape():
    recent = [f"{o[0]}/{a[0]}/{c[0]}" for o, a, c in zip(OPENINGS, ANGLES, CLOSINGS)]
    v = pick_variation(seed_text="ch:x", recent=recent)   # her şey "kullanılmış"
    assert v.opening and v.angle and v.closing


def test_malformed_history_is_ignored():
    v = pick_variation(seed_text="ch:1", recent=["", "bozuk", None, "a/b"])
    assert v.key.count("/") == 2


def test_banks_have_no_duplicate_keys():
    for bank in (OPENINGS, ANGLES, CLOSINGS):
        keys = [k for k, _ in bank]
        assert len(keys) == len(set(keys))


def test_db_reads_recent_variations_newest_first(tmp_path):
    import json
    from short_bot.db import init_db, record_short, recent_narration_variations
    eng = init_db(tmp_path / "x.sqlite")
    for i, key in enumerate(["soru/neden/hukum", "sahne/kiyas/izle", ""]):
        record_short(eng, channel="ch", rss_item_guid=f"g{i}", title="t", file_path="f",
                     duration_s=6, script_json=json.dumps({"narration_variation": key}), render_ms=0)
    record_short(eng, channel="ch", rss_item_guid="bozuk", title="t", file_path="f",
                 duration_s=6, script_json="{bozuk", render_ms=0)
    record_short(eng, channel="baska", rss_item_guid="x", title="t", file_path="f",
                 duration_s=6, script_json=json.dumps({"narration_variation": "x/y/z"}), render_ms=0)
    out = recent_narration_variations(eng, "ch")
    assert out == ["sahne/kiyas/izle", "soru/neden/hukum"]      # yeniden eskiye, boş/bozuk atlanır
