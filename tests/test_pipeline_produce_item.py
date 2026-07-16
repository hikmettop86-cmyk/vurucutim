"""_produce_from_item: tek bir NewsItem'dan video üretiminin izole testi."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from short_bot.db import init_db, is_processed
from short_bot.models import NewsItem, Script


def _minimal_settings():
    from short_bot.config import Settings
    return Settings(
        ffmpeg_path="ffmpeg", claude_cli_path="claude",
        playwright_browser="chromium", web_host="127.0.0.1", web_port=5005,
        fuzzy_dedup_threshold=0.85, log_level="INFO",
        claude_models={"default": "haiku", "script": "haiku", "dna": "opus"},
    )


def _minimal_channel(tmp_path):
    from short_bot.config import ChannelConfig
    return ChannelConfig(
        slug="testch", name="Test", keywords=["test"],
        rss_locale="hl=tr&gl=TR&ceid=TR:tr", schedule_cron="0 * * * *",
        duration_s=6, min_score=5.0, max_candidates_per_run=10,
        template="newscast", colors={"primary": "#fff", "accent": "#000",
                                       "bg_gradient": ["#111", "#222"]},
        handle="@test", output_dir=str(tmp_path / "out"),
        enabled=True,    )


def _item():
    return NewsItem(
        guid="g-manual-1", title="Test Haber",
        link="https://ornek.com/haber/1", source="Örnek",
        pub_date=datetime.now(timezone.utc),
        thumb_url=None, description="gövde metni burada yeterince uzun olsun.",
    )


def _script():
    return Script(
        header_top="TEST", header_bottom="MANUEL ÜRETİM",
        photo_overlay="örnek foto altyazısı", category="SPOR",
        body_paragraph="Bu bir test gövdesidir ve yeterince uzundur.",
        highlights=[], mood="neutral",
    )


def test_produce_from_item_success_records_short(tmp_path, monkeypatch):
    """Görsel + script + render mock'lanınca, tek item başarılı short üretir
    ve mark_processed çağrılır."""
    from short_bot import pipeline

    eng = init_db(tmp_path / "x.sqlite")
    ch = _minimal_channel(tmp_path)

    monkeypatch.setattr(pipeline, "extract_article", lambda url: "uzun gövde metni")
    monkeypatch.setattr(pipeline, "write_script", lambda *a, **k: _script())
    # newscast is in ARCHETYPE_OVERFLOW_FIELDS, so write_script_with_overflow_check
    # would be called and trigger Playwright. Mock it directly to avoid that.
    monkeypatch.setattr(pipeline, "write_script_with_overflow_check",
                        lambda **k: (_script(), 0))
    monkeypatch.setattr(pipeline, "extract_og_image_url", lambda url: None)
    fake_img = tmp_path / "bg.jpg"; fake_img.write_bytes(b"x")
    monkeypatch.setattr(pipeline, "download_and_blur_thumb", lambda *a, **k: fake_img)
    # og→thumb dalları atlanınca pick_image_for_script'e düşülür (local import).
    # Gerçek modül konumunu patch'le ki gerçek DuckDuckGo + Claude subprocess'e
    # gitmesin → test offline ve <1s kalsın.
    monkeypatch.setattr("short_bot.image_picker.pick_image_for_script",
                        lambda *a, **k: fake_img)
    monkeypatch.setattr(pipeline, "render_frames", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "compose_video", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "pick_music", lambda *a, **k: tmp_path / "m.mp3")

    log = MagicMock()
    result = pipeline._produce_from_item(
        item=_item(), channel=ch, eng=eng, settings=_minimal_settings(),
        log=log, music_root=tmp_path, templates_dir=Path("templates"),
        cache_dir=tmp_path, run_id=1, score=None,
    )
    assert result.status == "success"
    assert is_processed(eng, "g-manual-1", ch.slug)


def test_run_pipeline_with_preselected_item(tmp_path, monkeypatch):
    """preselected_item verilince fetch/score atlanir, dogrudan uretim yapilir."""
    from short_bot import pipeline

    monkeypatch.setattr(pipeline, "extract_article", lambda url: "uzun govde")
    monkeypatch.setattr(pipeline, "write_script", lambda *a, **k: _script())
    monkeypatch.setattr(pipeline, "write_script_with_overflow_check",
                        lambda **k: (_script(), 0))
    monkeypatch.setattr(pipeline, "extract_og_image_url", lambda url: None)
    fake_img = tmp_path / "bg.jpg"; fake_img.write_bytes(b"x")
    monkeypatch.setattr(pipeline, "download_and_blur_thumb", lambda *a, **k: fake_img)
    monkeypatch.setattr("short_bot.image_picker.pick_image_for_script",
                        lambda *a, **k: fake_img)
    monkeypatch.setattr(pipeline, "render_frames", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "compose_video", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "pick_music", lambda *a, **k: tmp_path / "m.mp3")

    # fetch_rss cagirilmamali -- cagirirsa testi patlat
    monkeypatch.setattr(pipeline, "fetch_rss",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("fetch_rss preselected modda cagrilmamali")))

    ch = _minimal_channel(tmp_path)
    result = pipeline.run_pipeline(
        channel=ch, settings=_minimal_settings(),
        db_path=tmp_path / "x.sqlite", music_root=tmp_path,
        templates_dir=Path("templates"), cache_dir=tmp_path,
        logs_dir=tmp_path / "logs", lock_dir=tmp_path / "locks",
        trigger="manual_feed", preselected_item=_item(),
    )
    assert result.status == "success"
