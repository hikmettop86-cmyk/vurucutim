"""Aşama 1'in taşıyıcı halkası: Trends sorguları script_json'a GERÇEKTEN yazılıyor mu.

Saga dersi (2026-08-19): alan modele eklendi ama TAŞIYAN yer güncellenmediği için
değer yolda düşüyordu ve özellik sessizce çalışmıyordu. Sorgular yükleme anında
(metadata yazarı) okunacak; üretim anında yazılmazlarsa hiç var olmamış olurlar.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from short_bot.db import init_db, shorts
from short_bot.models import NewsItem, ScoredItem
from tests.test_pipeline_saga_penalty import (
    _pipeline_channel, _pipeline_settings, _stub_render,
)

RELATED = ("galatasaray transfer son dakika", "batrakov kimdir", "gs transfer")


def _queries(eng, channel):
    with eng.connect() as conn:
        row = conn.execute(select(shorts.c.script_json)
                           .where(shorts.c.channel == channel)
                           .order_by(shorts.c.id.desc())).fetchone()
    return (json.loads(row[0]) or {}).get("search_queries")


def test_manuel_yol_sorgulari_yazar(tmp_path, monkeypatch):
    from short_bot import pipeline
    eng = init_db(tmp_path / "x.sqlite")
    _stub_render(monkeypatch, tmp_path)
    item = NewsItem(guid="g-1", title="Batrakov", link="https://o.com/1", source="S",
                    pub_date=datetime(2026, 8, 18), thumb_url=None,
                    description="gövde metni yeterince uzun olsun.",
                    trend_volume=50000, trend_related=RELATED)
    res = pipeline._produce_from_item(
        item=item, channel=_pipeline_channel(tmp_path, slug="prodch"), eng=eng,
        settings=_pipeline_settings(), log=logging.getLogger("t"),
        music_root=tmp_path, templates_dir=Path("templates"),
        cache_dir=tmp_path, run_id=1, score=9.0, subject="batrakov")
    assert res.status == "success"
    assert _queries(eng, "prodch") == list(RELATED)


def test_rss_yolu_sorgulari_yazar(tmp_path, monkeypatch):
    from short_bot import pipeline
    _stub_render(monkeypatch, tmp_path)
    item = NewsItem(guid="g1", title="Batrakov transferi", link="http://x", source="S",
                    pub_date=datetime(2026, 8, 18), thumb_url=None, description="d",
                    trend_volume=50000, trend_related=RELATED)
    monkeypatch.setattr(pipeline, "fetch_rss", lambda *a, **k: [item])
    monkeypatch.setattr(pipeline, "score_items",
                        lambda items, **k: [ScoredItem(item=item, score=9.0,
                                                       reasoning="ok", subject="batrakov")])
    db_path = tmp_path / "db.sqlite"
    res = pipeline.run_pipeline(
        channel=_pipeline_channel(tmp_path), settings=_pipeline_settings(),
        db_path=db_path, music_root=tmp_path, templates_dir=Path("templates"),
        cache_dir=tmp_path / "cache", logs_dir=tmp_path / "logs",
        lock_dir=tmp_path / "locks", trigger="cli")
    assert res.status == "success"
    assert _queries(init_db(db_path), "rssch") == list(RELATED)


def test_trends_disi_kanalda_alan_bos_kalir(tmp_path, monkeypatch):
    """RSS/mizah kanallarında sorgu yok — metadata bloğu da yazılmaz."""
    from short_bot import pipeline
    eng = init_db(tmp_path / "x.sqlite")
    _stub_render(monkeypatch, tmp_path)
    item = NewsItem(guid="g-2", title="Haber", link="https://o.com/2", source="S",
                    pub_date=datetime(2026, 8, 18), thumb_url=None,
                    description="gövde metni yeterince uzun olsun.")
    pipeline._produce_from_item(
        item=item, channel=_pipeline_channel(tmp_path, slug="rsskanal"), eng=eng,
        settings=_pipeline_settings(), log=logging.getLogger("t"),
        music_root=tmp_path, templates_dir=Path("templates"),
        cache_dir=tmp_path, run_id=1, score=9.0, subject="")
    assert _queries(eng, "rsskanal") == []
