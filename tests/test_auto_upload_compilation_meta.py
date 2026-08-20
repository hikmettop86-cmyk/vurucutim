"""Derleme satırı kendi metadata'sını taşır: yükleyici LLM'i atlar, #shorts eklemez."""
from __future__ import annotations

import ast
from pathlib import Path


def test_auto_upload_prefers_compilation_meta_without_llm():
    src = (Path(__file__).resolve().parents[1] / "src/short_bot/youtube/auto_upload.py").read_text(encoding="utf-8")
    assert 'script.get("compilation_meta")' in src
    i_meta = src.index('script.get("compilation_meta")')
    i_llm = src.index("meta = generate_youtube_metadata(")
    assert i_meta < i_llm
    # LLM çağrısı yalnız generated boşken
    assert "if generated is None:" in src[i_meta:i_llm]
    ast.parse(src)


def test_scheduler_registers_nightly_compilation_for_yorum_channels():
    src = (Path(__file__).resolve().parents[1] / "src/short_bot/web/scheduler.py").read_text(encoding="utf-8")
    assert "_daily_compilation_for" in src and "__derleme" in src
    assert "CronTrigger(hour=23, minute=30)" in src
    # _reload_jobs içinde kayıt (5 dk'lık yeniden yükleme tüm işleri siliyor)
    i_reload = src.index("def _reload_jobs")
    assert src.index("__derleme") > i_reload
