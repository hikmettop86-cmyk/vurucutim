"""Pipeline'ın kategori kotasını seçim öncesi uygulaması."""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime

from short_bot.config import ChannelConfig
from short_bot.db import init_db, record_short
from short_bot.models import NewsItem, ScoredItem
from short_bot.pipeline import _apply_category_quota


def _channel(**kw) -> ChannelConfig:
    base = ChannelConfig(
        slug="gs", name="GS", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, template="stadium",
        colors={"primary": "#fff"}, handle="@x", output_dir="out",
        enabled=True, language="tr",
    )
    return replace(base, **kw)


def _scored(guid, score, category):
    item = NewsItem(guid=guid, title=guid, link="l", source="s",
                    pub_date=datetime(2026, 8, 10), thumb_url=None, description=None)
    return ScoredItem(item=item, score=score, reasoning="", category=category)


def _produce(eng, category, n):
    for i in range(n):
        record_short(eng, channel="gs", rss_item_guid=f"{category}-{i}",
                     title=f"{category}-{i}", file_path="x.mp4", duration_s=6,
                     script_json=json.dumps({"category": category}), render_ms=1)


def test_quota_demotes_saturated_topic_so_other_topic_wins(tmp_path):
    """Asıl amaç: aynı konunun art arda seçilmesini kırmak.

    Analizde üretimin %50'si gelen-transferdi ve o en zayıf kategoriydi;
    puanlayıcı havuzun dağılımını olduğu gibi yayına geçiriyordu.
    """
    eng = init_db(tmp_path / "x.sqlite")
    _produce(eng, "transfer-gelen", 3)
    ch = _channel(categories=["transfer-gelen", "avrupa-kura"],
                  category_quota_per_day={"transfer-gelen": 3})

    scored = [_scored("g1", 9.0, "transfer-gelen"), _scored("g2", 7.0, "avrupa-kura")]
    out = _apply_category_quota(scored, channel=ch, eng=eng,
                                log=logging.getLogger("t"))

    best = max(out, key=lambda s: s.score)
    assert best.item.guid == "g2"          # doymuş konu geri düştü
    assert best.category == "avrupa-kura"


def test_no_quota_configured_is_passthrough(tmp_path):
    """Kotası olmayan kanallar (mevcut hepsi) hiç etkilenmez."""
    eng = init_db(tmp_path / "x.sqlite")
    ch = _channel()
    scored = [_scored("g1", 9.0, "transfer-gelen")]
    out = _apply_category_quota(scored, channel=ch, eng=eng,
                                log=logging.getLogger("t"))
    assert out == scored


def test_quota_not_reached_leaves_ranking_intact(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _produce(eng, "transfer-gelen", 1)
    ch = _channel(categories=["transfer-gelen", "avrupa-kura"],
                  category_quota_per_day={"transfer-gelen": 3})

    scored = [_scored("g1", 9.0, "transfer-gelen"), _scored("g2", 7.0, "avrupa-kura")]
    out = _apply_category_quota(scored, channel=ch, eng=eng,
                                log=logging.getLogger("t"))
    assert max(out, key=lambda s: s.score).item.guid == "g1"
