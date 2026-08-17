"""Boru hattının saga cezasını seçim öncesi uygulaması."""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime

from short_bot.config import ChannelConfig
from short_bot.db import init_db, record_short
from short_bot.models import NewsItem, ScoredItem
from short_bot.pipeline import _apply_category_quota, _apply_saga_penalty


def _channel(**kw) -> ChannelConfig:
    base = ChannelConfig(
        slug="gs", name="GS", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, template="stadium",
        colors={"primary": "#fff"}, handle="@x", output_dir="out",
        enabled=True, language="tr",
    )
    return replace(base, **kw)


def _scored(guid, score, subject):
    item = NewsItem(guid=guid, title=guid, link="l", source="s",
                    pub_date=datetime(2026, 8, 18), thumb_url=None, description=None)
    return ScoredItem(item=item, score=score, reasoning="", subject=subject)


def _produce(eng, subject, n):
    for i in range(n):
        record_short(eng, channel="gs", rss_item_guid=f"{subject}-{i}",
                     title=f"{subject}-{i}", file_path="x.mp4", duration_s=6,
                     script_json=json.dumps({"subject": subject}), render_ms=1)


def test_saturated_saga_loses_to_a_fresh_one(tmp_path):
    """Asıl amaç: Batrakov'un 4. videosu yerine başka hikâye seçilsin."""
    eng = init_db(tmp_path / "x.sqlite")
    _produce(eng, "batrakov", 3)
    ch = _channel(saga_penalty_per_repeat=1.0)

    scored = [_scored("g1", 9.0, "batrakov"), _scored("g2", 7.0, "osimhen")]
    out = _apply_saga_penalty(scored, channel=ch, eng=eng,
                              log=logging.getLogger("t"))

    best = max(out, key=lambda s: s.score)
    assert best.item.guid == "g2"
    assert best.subject == "osimhen"


def test_penalty_can_push_below_min_score(tmp_path):
    """Kotadan ayrılan davranış: aday tamamen elenebilir."""
    eng = init_db(tmp_path / "x.sqlite")
    _produce(eng, "batrakov", 5)
    ch = _channel(saga_penalty_per_repeat=1.0)

    out = _apply_saga_penalty([_scored("g1", 9.0, "batrakov")],
                              channel=ch, eng=eng, log=logging.getLogger("t"))
    assert out[0].score == 4.0
    assert out[0].score < ch.min_score


def test_disabled_channel_is_passthrough(tmp_path):
    """Varsayılan 0.0 — diğer tüm kanallar bit bit aynı davranır."""
    eng = init_db(tmp_path / "x.sqlite")
    _produce(eng, "batrakov", 5)
    scored = [_scored("g1", 9.0, "batrakov")]

    out = _apply_saga_penalty(scored, channel=_channel(), eng=eng,
                              log=logging.getLogger("t"))
    assert out == scored


def test_disabled_channel_never_touches_the_db():
    """Kapalı kanalda erken dönüş GERÇEKTEN erken olmalı.

    Üstteki passthrough testi bu muhafazayı kanıtlamıyor: `saga_penalty_per_repeat`
    0.0 iken muhafazayı silsek bile `scorer.apply_saga_penalty` kendi `if not step`
    kontrolüyle listeyi aynen döndürür ve test yeşil kalır. Oysa aradaki fark
    gerçek: muhafaza silinirse 29 kanalın HEPSİ her koşuda gereksiz bir
    `count_recent_subjects` sorgusu öder. `eng=None` bunu ölçülebilir kılar —
    veritabanına dokunulursa test patlar.
    """
    out = _apply_saga_penalty([_scored("g1", 9.0, "batrakov")],
                              channel=_channel(), eng=None,
                              log=logging.getLogger("t"))
    assert out[0].score == 9.0


def test_window_excludes_nothing_when_recent(tmp_path):
    eng = init_db(tmp_path / "x.sqlite")
    _produce(eng, "batrakov", 2)
    ch = _channel(saga_penalty_per_repeat=0.5, saga_window_days=14)

    out = _apply_saga_penalty([_scored("g1", 9.0, "batrakov")],
                              channel=ch, eng=eng, log=logging.getLogger("t"))
    assert out[0].score == 8.0


def test_logs_the_reason(tmp_path, caplog):
    """Günlükte 'neden cezalandı' okunabilir olmalı."""
    eng = init_db(tmp_path / "x.sqlite")
    _produce(eng, "batrakov", 3)
    ch = _channel(saga_penalty_per_repeat=1.0)
    log = logging.getLogger("saga-test")

    with caplog.at_level(logging.INFO, logger="saga-test"):
        _apply_saga_penalty([_scored("g1", 9.0, "batrakov")],
                            channel=ch, eng=eng, log=log)
    assert "batrakov" in caplog.text
    assert "saga" in caplog.text


def test_saga_veto_beats_the_quota_floor(tmp_path):
    """İKİSİ BİRLİKTE: saga cezası kotanın tabanının ALTINA inebilmeli.

    Sıra bilinçlidir — kota puanı min_score'a sabitler (SIRALAMA aracı),
    saga cezası sonra o tabanı deler (VETO aracı). Bu testin varlık sebebi:
    sıra ters çevrilirse (saga önce, kota sonra) kota adayı 6.0'a geri
    yükseltir ve altıncı Batrakov videosu yine üretilir.
    """
    eng = init_db(tmp_path / "x.sqlite")
    for i in range(3):
        record_short(eng, channel="gs", rss_item_guid=f"b-{i}", title=f"b-{i}",
                     file_path="x.mp4", duration_s=6, render_ms=1,
                     script_json=json.dumps({"category": "transfer-gelen",
                                             "subject": "batrakov"}))
    ch = _channel(min_score=6.0, saga_penalty_per_repeat=1.0,
                  categories=["transfer-gelen"],
                  category_quota_per_day={"transfer-gelen": 3})

    scored = [_scored("g1", 9.0, "batrakov")]
    scored[0] = replace(scored[0], category="transfer-gelen")
    log = logging.getLogger("t")

    after_quota = _apply_category_quota(scored, channel=ch, eng=eng, log=log)
    assert after_quota[0].score == 6.0          # kota tabana sabitledi

    after_saga = _apply_saga_penalty(after_quota, channel=ch, eng=eng, log=log)
    assert after_saga[0].score == 3.0           # 6.0 - 3×1.0, taban delindi
    assert after_saga[0].score < ch.min_score   # seçime hiç girmez
