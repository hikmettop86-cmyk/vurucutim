"""content_source=trends kanalı _run_rss içinden: fetch_rss yerine
fetch_trending_items, select_top yerine hacimli seçim."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from short_bot.db import init_db
from short_bot.models import NewsItem, ScoredItem


def _channel(tmp_path, *, region=None, language="tr"):
    from short_bot.config import ChannelConfig
    return ChannelConfig(
        slug="gundem", name="Gündem", keywords=[],
        rss_locale="hl=tr&gl=TR&ceid=TR:tr", schedule_cron="0 */2 * * *",
        duration_s=6, min_score=6.0, max_candidates_per_run=25,
        template="broadcast", colors={"primary": "#fff", "accent": "#000",
                                        "bg_gradient": ["#111", "#222"]},
        handle="@g", output_dir=str(tmp_path / "out"), enabled=True,
        language=language, content_source="trends", trends_region=region,
    )


def _settings():
    from short_bot.config import Settings
    return Settings(
        ffmpeg_path="ffmpeg", claude_cli_path="claude",
        playwright_browser="chromium", web_host="127.0.0.1", web_port=5005,
        fuzzy_dedup_threshold=0.85, log_level="INFO",
        claude_models={"default": "haiku", "script": "haiku", "dna": "opus"})


def _item(guid, title, volume):
    return NewsItem(guid=guid, title=title, link=guid, source="S",
                    pub_date=datetime.now(timezone.utc), thumb_url=None,
                    description="Google Trends · …", trend_volume=volume)


def _wire(monkeypatch, pipeline, items, scores: dict[str, float]):
    """Ağ ve üretimi kes; seçilen adayı yakala."""
    seen = {}

    def _fake_fetch_trending(region, **kw):
        seen["region"] = region; seen["language"] = kw.get("language")
        seen["cache_dir"] = kw.get("cache_dir")
        return items

    def _no_rss(*a, **k):
        raise AssertionError("trend kanalında fetch_rss çağrılmamalı")

    monkeypatch.setattr(pipeline, "fetch_trending_items", _fake_fetch_trending)
    monkeypatch.setattr(pipeline, "fetch_rss", _no_rss)
    monkeypatch.setattr(pipeline, "filter_new", lambda eng, items, slug, **k: items)
    monkeypatch.setattr(pipeline, "score_items",
                        lambda items, **k: [ScoredItem(item=i, score=scores[i.guid],
                                                        reasoning="") for i in items])
    monkeypatch.setattr(pipeline, "_apply_trend_boost",
                        lambda scored, **k: scored)
    # Aday döngüsünün ilk adımı: google-news çözümleme + extract. İlk adayda
    # dururuz — seçim sırası bu noktada bellidir.
    monkeypatch.setattr(pipeline, "_is_google_news_url", lambda url: False)

    def _stop(url):
        seen["picked_url"] = url
        raise RuntimeError("dur")
    monkeypatch.setattr(pipeline, "extract_article", _stop)
    return seen


def test_trends_channel_fetches_trends_and_picks_highest_volume(tmp_path, monkeypatch):
    from short_bot import pipeline
    eng = init_db(tmp_path / "x.sqlite")
    ch = _channel(tmp_path)
    items = [_item("https://x/yuksek-puan", "İlginç ama küçük", 2000),
             _item("https://x/deprem", "Marmara sallandı", 100000),
             _item("https://x/hava", "Trabzon hava durumu", 500000)]
    seen = _wire(monkeypatch, pipeline, items,
                 {"https://x/yuksek-puan": 9.5, "https://x/deprem": 7.5, "https://x/hava": 2.0})

    try:
        pipeline._run_rss(channel=ch, run_id=1, log=MagicMock(), eng=eng,
                          settings=_settings(), music_root=tmp_path,
                          templates_dir=Path("templates"), cache_dir=tmp_path)
    except RuntimeError:
        pass
    assert seen["region"] == "TR"                  # dilden türetildi
    assert seen["language"] == "tr"
    assert Path(seen["cache_dir"]) == tmp_path / "trends"
    assert seen["picked_url"] == "https://x/deprem"   # eşiği geçenlerden en yüksek hacim


def test_trends_region_override_wins_over_language(tmp_path, monkeypatch):
    from short_bot import pipeline
    eng = init_db(tmp_path / "x.sqlite")
    ch = _channel(tmp_path, region="AT", language="de")
    items = [_item("https://x/a", "Tornado", 50000)]
    seen = _wire(monkeypatch, pipeline, items, {"https://x/a": 8.0})
    try:
        pipeline._run_rss(channel=ch, run_id=1, log=MagicMock(), eng=eng,
                          settings=_settings(), music_root=tmp_path,
                          templates_dir=Path("templates"), cache_dir=tmp_path)
    except RuntimeError:
        pass
    assert seen["region"] == "AT"


def test_trends_channel_no_candidates_when_all_gated(tmp_path, monkeypatch):
    from short_bot import pipeline
    eng = init_db(tmp_path / "x.sqlite")
    ch = _channel(tmp_path)
    items = [_item("https://x/hava", "Hava durumu", 500000)]
    _wire(monkeypatch, pipeline, items, {"https://x/hava": 2.0})
    res = pipeline._run_rss(channel=ch, run_id=1, log=MagicMock(), eng=eng,
                            settings=_settings(), music_root=tmp_path,
                            templates_dir=Path("templates"), cache_dir=tmp_path)
    assert res.status == "no_candidates"


def test_trends_channel_empty_source_is_no_candidates(tmp_path, monkeypatch):
    from short_bot import pipeline
    eng = init_db(tmp_path / "x.sqlite")
    ch = _channel(tmp_path)
    _wire(monkeypatch, pipeline, [], {})
    res = pipeline._run_rss(channel=ch, run_id=1, log=MagicMock(), eng=eng,
                            settings=_settings(), music_root=tmp_path,
                            templates_dir=Path("templates"), cache_dir=tmp_path)
    assert res.status == "no_candidates"


def test_trends_min_volume_passed_to_fetch(tmp_path, monkeypatch):
    from dataclasses import replace
    from short_bot import pipeline
    eng = init_db(tmp_path / "x.sqlite")
    ch = replace(_channel(tmp_path), trends_min_volume=5000)
    seen = {}

    def _fake(region, **kw):
        seen.update(kw)
        return []
    monkeypatch.setattr(pipeline, "fetch_trending_items", _fake)
    monkeypatch.setattr(pipeline, "filter_new", lambda eng, items, slug, **k: items)
    pipeline._run_rss(channel=ch, run_id=1, log=MagicMock(), eng=eng,
                      settings=_settings(), music_root=tmp_path,
                      templates_dir=Path("templates"), cache_dir=tmp_path)
    assert seen["min_volume"] == 5000
