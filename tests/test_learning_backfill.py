"""Geçmiş script_json kayıtlarını canonical kategoriye çevirme."""
from __future__ import annotations

import json

from short_bot.db import init_db, record_short
from short_bot.learning.backfill import apply_category_backfill


def _short(eng, channel, guid, category, **extra):
    payload = {"header_top": "H", "body_paragraph": "b", "mood": "breaking",
               "category": category}
    payload.update(extra)
    return record_short(eng, channel=channel, rss_item_guid=guid, title=guid,
                        file_path="x.mp4", duration_s=6,
                        script_json=json.dumps(payload), render_ms=1)


def _payload(eng, sid):
    from short_bot.db import shorts
    with eng.connect() as conn:
        row = conn.execute(
            shorts.select().where(shorts.c.id == sid)).mappings().first()
    return json.loads(row["script_json"])


def test_backfill_rewrites_category_and_keeps_original(tmp_path):
    """Hint penceresi 30 gün; eski kayıtlar 'transfer'/'futbol' gibi serbest
    etiketli olduğu için scorer'a giden kategori ipucu ayırt edici değil.
    Yeniden etiketleme orijinali SAKLAMALI — yanlış eşleme geri alınabilsin."""
    eng = init_db(tmp_path / "x.sqlite")
    sid = _short(eng, "gs", "g1", "transfer")

    n = apply_category_backfill(eng, {sid: "transfer-gelen"})

    assert n == 1
    p = _payload(eng, sid)
    assert p["category"] == "transfer-gelen"
    assert p["category_original"] == "transfer"


def test_backfill_leaves_other_fields_untouched(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    sid = _short(eng, "gs", "g1", "futbol", header_top="ORİJİNAL")

    apply_category_backfill(eng, {sid: "avrupa-kura"})

    p = _payload(eng, sid)
    assert p["header_top"] == "ORİJİNAL"
    assert p["body_paragraph"] == "b"
    assert p["mood"] == "breaking"


def test_backfill_is_idempotent_on_original(tmp_path):
    """İkinci kez çalıştırılırsa category_original ilk değeri korumalı."""
    eng = init_db(tmp_path / "x.sqlite")
    sid = _short(eng, "gs", "g1", "transfer")

    apply_category_backfill(eng, {sid: "transfer-gelen"})
    apply_category_backfill(eng, {sid: "transfer-giden"})

    p = _payload(eng, sid)
    assert p["category"] == "transfer-giden"
    assert p["category_original"] == "transfer"   # ilk hali, ezilmedi


def test_backfill_skips_unknown_ids(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    assert apply_category_backfill(eng, {999: "transfer-gelen"}) == 0
