"""Boru hattının saga cezasını seçim öncesi uygulaması."""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from short_bot.config import ChannelConfig
from short_bot.db import init_db, record_short
from short_bot.models import NewsItem, ScoredItem, Script
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


def _script(**kw) -> Script:
    base = dict(header_top="UST", header_bottom="ALT", photo_overlay="foto",
                body_paragraph="Bu bir gövde metnidir, yeterince uzun.",
                category="transfer-gelen", mood="neutral")
    base.update(kw)
    return Script(**base)


def test_subject_survives_into_the_counter(tmp_path):
    """Uçtan uca: seçilen adayın öznesi script_json'a yazılıp sayaca dönmeli."""
    from short_bot.db import count_recent_subjects

    eng = init_db(tmp_path / "x.sqlite")
    script = _script().model_copy(update={"subject": "batrakov"})
    record_short(eng, channel="gs", rss_item_guid="a", title="t",
                 file_path="x.mp4", duration_s=6,
                 script_json=script.model_dump_json(), render_ms=1)

    assert count_recent_subjects(eng, "gs", days=14) == {"batrakov": 1}


def test_produce_from_item_accepts_subject_kwarg():
    """_run_feed öznesini bu parametreyle taşıyor; imza kaybolursa sessizce
    kör satır yazılır."""
    import inspect

    from short_bot.pipeline import _produce_from_item
    assert "subject" in inspect.signature(_produce_from_item).parameters


# ---------------------------------------------------------------------------
# DEĞER kanıtı. Üstteki imza testi parametre kabul edilip SESSİZCE yok sayılsa
# bile yeşil kalır — asıl hata sınıfı tam olarak budur ("kör satır"). Aşağıdaki
# üç test değerin gerçekten script_json'a düştüğünü ve sayaca döndüğünü ölçer.
# ---------------------------------------------------------------------------

def _pipeline_channel(tmp_path, **kw) -> ChannelConfig:
    base = ChannelConfig(
        slug="rssch", name="R", keywords=["x"], rss_locale="hl=tr",
        schedule_cron="0 * * * *", duration_s=2, min_score=5.0,
        max_candidates_per_run=10, template="newscast",
        colors={"primary": "#c81e1e", "accent": "#ffea3b",
                "bg_gradient": ["#1a3b6b", "#0a1a3b"]},
        handle="@x", output_dir=str(tmp_path / "out"), enabled=True,
        language="tr", max_age_hours=0,
    )
    return replace(base, **kw)


def _pipeline_settings():
    from short_bot.config import Settings
    return Settings(
        ffmpeg_path="ffmpeg", claude_cli_path="claude",
        playwright_browser="chromium", web_host="127.0.0.1", web_port=5005,
        fuzzy_dedup_threshold=0.85, log_level="INFO",
        claude_models={"default": "haiku", "script": "haiku", "dna": "opus"})


def _stub_render(monkeypatch, tmp_path):
    """Görsel/senaryo/render/müzik ağır yollarını kapat — DB yazımı gerçek kalsın."""
    from short_bot import pipeline

    fake_img = tmp_path / "bg.jpg"
    fake_img.write_bytes(b"x")
    monkeypatch.setattr(pipeline, "extract_article", lambda url: "uzun gövde metni")
    monkeypatch.setattr(pipeline, "write_script", lambda *a, **k: _script())
    monkeypatch.setattr(pipeline, "write_script_with_overflow_check",
                        lambda **k: (_script(), 0))
    monkeypatch.setattr(pipeline, "extract_og_image_url", lambda url: None)
    monkeypatch.setattr(pipeline, "download_and_blur_thumb", lambda *a, **k: fake_img)
    monkeypatch.setattr("short_bot.image_picker.pick_image_for_script",
                        lambda *a, **k: fake_img)
    monkeypatch.setattr(pipeline, "render_frames", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "pick_music", lambda *a, **k: tmp_path / "m.mp3")

    def _compose(frames_dir, music_path, out_path, **kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"mp4")
        return Path(out_path)
    monkeypatch.setattr(pipeline, "compose_video", _compose)


def test_produce_from_item_actually_writes_the_subject(tmp_path, monkeypatch):
    """`subject=` parametresi gerçek `record_short`'a kadar gitmeli.

    İmza testinin göremediği şey: değer yolda düşerse sayaç boş döner.
    """
    from short_bot import pipeline
    from short_bot.db import count_recent_subjects

    eng = init_db(tmp_path / "x.sqlite")
    _stub_render(monkeypatch, tmp_path)
    item = NewsItem(guid="g-1", title="Batrakov", link="https://o.com/1",
                    source="S", pub_date=datetime(2026, 8, 18), thumb_url=None,
                    description="gövde metni yeterince uzun olsun.")

    res = pipeline._produce_from_item(
        item=item, channel=_pipeline_channel(tmp_path, slug="prodch"), eng=eng,
        settings=_pipeline_settings(), log=logging.getLogger("t"),
        music_root=tmp_path, templates_dir=Path("templates"),
        cache_dir=tmp_path, run_id=1, score=9.0, subject="batrakov")

    assert res.status == "success"
    assert count_recent_subjects(eng, "prodch", days=14) == {"batrakov": 1}


def test_run_rss_writes_the_picked_candidates_subject(tmp_path, monkeypatch):
    """RSS yolu kendi `record_short`'unu çağırır — ayrıca kanıtlanmalı."""
    from short_bot import pipeline
    from short_bot.db import count_recent_subjects

    _stub_render(monkeypatch, tmp_path)
    item = NewsItem(guid="g1", title="Batrakov transferi", link="http://x",
                    source="S", pub_date=datetime(2026, 8, 18), thumb_url=None,
                    description="d")
    monkeypatch.setattr(pipeline, "fetch_rss", lambda *a, **k: [item])
    monkeypatch.setattr(
        pipeline, "score_items",
        lambda items, **k: [ScoredItem(item=item, score=9.0, reasoning="ok",
                                       subject="batrakov")])

    db_path = tmp_path / "db.sqlite"
    res = pipeline.run_pipeline(
        channel=_pipeline_channel(tmp_path), settings=_pipeline_settings(),
        db_path=db_path, music_root=tmp_path, templates_dir=Path("templates"),
        cache_dir=tmp_path / "cache", logs_dir=tmp_path / "logs",
        lock_dir=tmp_path / "locks", trigger="cli")

    assert res.status == "success"
    assert count_recent_subjects(init_db(db_path), "rssch", days=14) \
        == {"batrakov": 1}


def test_run_feed_hands_the_subject_to_the_producer(tmp_path, monkeypatch):
    """Feed yolu `chosen.subject`'i taşımalı; taşımazsa üretim kör satır yazar."""
    from short_bot import pipeline
    from short_bot.db import add_feed

    eng = init_db(tmp_path / "x.sqlite")
    fid = add_feed(eng, url="https://ornek.com/rss", title="Örnek")
    ch = _pipeline_channel(tmp_path, slug="feedch", min_score=6.0,
                           content_source="feed", auto_feed_ids=[fid])

    item = NewsItem(guid="g1", title="Batrakov", link="https://o.com/1",
                    source="Örnek", pub_date=datetime.now(timezone.utc),
                    thumb_url=None, description="özet")
    monkeypatch.setattr(pipeline, "fetch_feed_url", lambda url, **k: [item])
    monkeypatch.setattr(pipeline, "filter_new", lambda eng, items, slug, **k: items)
    monkeypatch.setattr(
        pipeline, "score_items",
        lambda items, **k: [ScoredItem(item=items[0], score=8.0, reasoning="",
                                       subject="batrakov")])
    captured: dict = {}

    def _fake_produce(*, item, subject, **kw):
        captured["subject"] = subject
        return pipeline.RunResult(run_id=kw["run_id"], status="success",
                                  short_path=Path("x.mp4"), error=None)
    monkeypatch.setattr(pipeline, "_produce_from_item", _fake_produce)

    res = pipeline._run_feed(
        channel=ch, run_id=1, log=logging.getLogger("t"), eng=eng,
        settings=_pipeline_settings(), music_root=tmp_path,
        templates_dir=Path("templates"), cache_dir=tmp_path)

    assert res.status == "success"
    assert captured["subject"] == "batrakov"
