from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from short_bot.db import init_db, add_feed
from short_bot.models import NewsItem, ScoredItem, Script


def _channel(tmp_path, feed_ids):
    from short_bot.config import ChannelConfig
    return ChannelConfig(
        slug="feedch", name="Feed", keywords=[],
        rss_locale="hl=tr&gl=TR&ceid=TR:tr", schedule_cron="0 * * * *",
        duration_s=6, min_score=6.0, max_candidates_per_run=10,
        template="newscast", colors={"primary": "#fff", "accent": "#000",
                                       "bg_gradient": ["#111", "#222"]},
        handle="@f", output_dir=str(tmp_path / "out"), enabled=True,
        cta_enabled=False, cta_text="", cta_icons=[], cta_duration_s=0,
        cta_show_handle=False, content_source="feed", auto_feed_ids=feed_ids,
    )


def _settings():
    from short_bot.config import Settings
    return Settings(
        ffmpeg_path="ffmpeg", claude_cli_path="claude",
        playwright_browser="chromium", web_host="127.0.0.1", web_port=5005,
        fuzzy_dedup_threshold=0.85, log_level="INFO",
        claude_models={"default": "haiku", "script": "haiku", "dna": "opus"})


def test_run_feed_fetches_scores_produces(tmp_path, monkeypatch):
    from short_bot import pipeline
    eng = init_db(tmp_path / "x.sqlite")
    fid = add_feed(eng, url="https://ornek.com/rss", title="Örnek")
    ch = _channel(tmp_path, [fid])

    news = [NewsItem(guid="g1", title="Yeni haber", link="https://o.com/1",
                     source="Örnek", pub_date=datetime.now(timezone.utc),
                     thumb_url=None, description="özet uzun gövde metni")]
    monkeypatch.setattr(pipeline, "fetch_feed_url", lambda url, **k: news)
    monkeypatch.setattr(pipeline, "filter_new", lambda eng, items, slug, **k: items)
    monkeypatch.setattr(pipeline, "score_items",
                        lambda items, **k: [ScoredItem(item=items[0], score=8.0,
                                                        reasoning="")])
    captured = {}
    def _fake_produce(*, item, score, **kwargs):
        captured["item"] = item; captured["score"] = score
        from short_bot.pipeline import RunResult
        return RunResult(run_id=kwargs["run_id"], status="success",
                         short_path=Path("x.mp4"), error=None)
    monkeypatch.setattr(pipeline, "_produce_from_item", _fake_produce)

    log = MagicMock()
    result = pipeline._run_feed(
        channel=ch, run_id=1, log=log, eng=eng, settings=_settings(),
        music_root=tmp_path, templates_dir=Path("templates"), cache_dir=tmp_path)
    assert result.status == "success"
    assert captured["item"].guid == "g1"
    assert captured["score"] == 8.0
