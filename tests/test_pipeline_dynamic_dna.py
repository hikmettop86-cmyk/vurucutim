"""Tests for pipeline._resolve_dna_for_video — cache hit/miss + fallback paths."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from short_bot.config import ChannelConfig
from short_bot.db import init_db
from short_bot.dna import DnaSpec
from short_bot.pipeline import _resolve_dna_for_video


def _channel(dynamic: bool = True) -> ChannelConfig:
    return ChannelConfig(
        slug="test", name="Test", keywords=["a"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@test", output_dir="out",
        enabled=True, language="tr",
        max_age_hours=24, dynamic_dna=dynamic,
    )


def _sample_dna() -> DnaSpec:
    return DnaSpec.model_validate({
        "archetype": "newscast",
        "palette": {
            "primary": "#e8141a", "accent": "#fff100",
            "bg_gradient": ["#000000", "#2a0000"],
            "body_bg": ["#0a0000", "#220000"],
            "text_main": "#ffffff", "text_muted": "#ffd1d1",
        },
        "fonts": {"headline": "Inter", "body": "Inter", "google_imports": []},
        "tone": {
            "voice": "x", "style": "x", "forbidden": [],
            "sentence_max_words": 10, "paragraph_sentences": [2, 3],
            "body_max_chars": 200, "headline_style_hint": "",
        },
        "persona_summary": "test", "custom_css": "", "ui_badge": "X",
    })


@pytest.fixture
def eng(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def templates_dir(tmp_path):
    d = tmp_path / "templates" / "css"
    d.mkdir(parents=True)
    return tmp_path / "templates"


@pytest.fixture
def secrets_path(tmp_path):
    p = tmp_path / "secrets.yaml"
    p.write_text("openai_api_key: sk-test\n", encoding="utf-8")
    return p


def test_returns_none_when_dynamic_disabled(eng, templates_dir, secrets_path):
    cfg = _channel(dynamic=False)
    log = MagicMock()
    result = _resolve_dna_for_video(
        channel=cfg, headline="x", body="y",
        log=log, claude_path="claude", secrets_path=secrets_path,
        templates_dir=templates_dir, eng=eng,
    )
    assert result is None


def test_returns_none_when_no_api_key(eng, templates_dir, tmp_path, monkeypatch):
    cfg = _channel(dynamic=True)
    secrets = tmp_path / "empty.yaml"
    secrets.write_text("", encoding="utf-8")
    log = MagicMock()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = _resolve_dna_for_video(
        channel=cfg, headline="x", body="y",
        log=log, claude_path="claude", secrets_path=secrets,
        templates_dir=templates_dir, eng=eng,
    )
    assert result is None


def test_cache_miss_generates_and_saves(eng, templates_dir, secrets_path):
    cfg = _channel(dynamic=True)
    log = MagicMock()
    fake_emb = [0.1] * 1536
    fake_dna = _sample_dna()

    with patch("short_bot.pipeline.embed_text", return_value=fake_emb), \
         patch("short_bot.pipeline.generate_dna_for_video", return_value=fake_dna):
        result = _resolve_dna_for_video(
            channel=cfg, headline="Galatasaray", body="x" * 500,
            log=log, claude_path="claude", secrets_path=secrets_path,
            templates_dir=templates_dir, eng=eng,
        )
    assert result is not None
    dna, css_path = result
    assert dna.archetype == "newscast"
    assert css_path.exists()
    assert css_path.parent == templates_dir / "css"
    assert css_path.name.startswith("dynamic-test-")


def test_cache_hit_skips_llm(eng, templates_dir, secrets_path):
    cfg = _channel(dynamic=True)
    log = MagicMock()
    fake_emb = [0.5] * 1536
    fake_dna = _sample_dna()

    from short_bot.dna_cache import save_cached_dna
    save_cached_dna(eng, "test", "seeded", fake_emb, fake_dna, "preexisting.css")
    (templates_dir / "css" / "preexisting.css").write_text("/* seeded */",
                                                          encoding="utf-8")

    with patch("short_bot.pipeline.embed_text", return_value=fake_emb), \
         patch("short_bot.pipeline.generate_dna_for_video") as mock_gen:
        result = _resolve_dna_for_video(
            channel=cfg, headline="x", body="y",
            log=log, claude_path="claude", secrets_path=secrets_path,
            templates_dir=templates_dir, eng=eng,
        )
    assert result is not None
    dna, css_path = result
    assert css_path.name == "preexisting.css"
    mock_gen.assert_not_called()


def test_embedding_failure_returns_none(eng, templates_dir, secrets_path):
    """If OpenAI embedding fails, return None so caller falls back to static DNA."""
    cfg = _channel(dynamic=True)
    log = MagicMock()
    from short_bot.embeddings import EmbeddingError
    with patch("short_bot.pipeline.embed_text", side_effect=EmbeddingError("boom")):
        result = _resolve_dna_for_video(
            channel=cfg, headline="x", body="y",
            log=log, claude_path="claude", secrets_path=secrets_path,
            templates_dir=templates_dir, eng=eng,
        )
    assert result is None


def test_generation_failure_returns_none(eng, templates_dir, secrets_path):
    """If Opus generation fails, return None for fallback."""
    cfg = _channel(dynamic=True)
    log = MagicMock()
    fake_emb = [0.2] * 1536

    with patch("short_bot.pipeline.embed_text", return_value=fake_emb), \
         patch("short_bot.pipeline.generate_dna_for_video",
               side_effect=RuntimeError("opus down")):
        result = _resolve_dna_for_video(
            channel=cfg, headline="x", body="y",
            log=log, claude_path="claude", secrets_path=secrets_path,
            templates_dir=templates_dir, eng=eng,
        )
    assert result is None


def test_run_rss_with_dynamic_dna_uses_per_video_archetype(
    tmp_path, monkeypatch
):
    """E2E placeholder: a dynamic_dna channel with mocked embeddings + Opus call
    yields a video rendered with the per-video archetype, not channel.template.

    Manual smoke procedure (acceptance for F2):
      1. Set OPENAI_API_KEY env var (or via Settings UI → OpenAI Key)
      2. Pick or create a low-stakes channel; toggle dynamic_dna on (Edit page)
      3. Trigger "Run Now" from dashboard
      4. Inspect run log:
           - cache MISS path: "[dna] cache MISS → generating (Opus)..." then
             "[dna] saved: archetype=<X> css=dynamic-<slug>-<hex>.css"
           - cache HIT path: "[dna] cache HIT id=<N> archetype=<X> (cos=0.9xx)"
      5. Verify templates/css/dynamic-<slug>-*.css file exists
      6. Inspect produced video: visual style reflects archetype chosen by Opus,
         possibly different from channel.template
      7. Re-trigger Run Now: cache HIT increments hit_count, no Opus call

    A full Playwright integration test is a v2 nice-to-have.
    """
    pytest.skip("F2 acceptance is via manual smoke (see docstring)")
