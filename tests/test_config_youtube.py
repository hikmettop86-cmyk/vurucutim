from pathlib import Path

import pytest

from short_bot.config import load_channel, save_channel, ChannelConfig, YoutubeChannelConfig


def _base_yaml(extra: str = "") -> str:
    return (
        "slug: t\nname: T\nkeywords: [a]\nlanguage: tr\n"
        "schedule_cron: '* * * * *'\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}\n"
        "handle: '@t'\noutput_dir: out\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n"
        + extra
    )


def test_youtube_field_defaults_to_none(tmp_path):
    (tmp_path / "ch.yaml").write_text(_base_yaml(), encoding="utf-8")
    c = load_channel(tmp_path / "ch.yaml")
    assert c.youtube is None


def test_youtube_block_parses(tmp_path):
    (tmp_path / "ch.yaml").write_text(_base_yaml(
        "youtube:\n  auto_upload: true\n  ai_content: false\n"
        "  category_id: '24'\n  privacy_status: public\n"
    ), encoding="utf-8")
    c = load_channel(tmp_path / "ch.yaml")
    assert c.youtube is not None
    assert c.youtube.auto_upload is True
    assert c.youtube.ai_content is False
    assert c.youtube.category_id == "24"
    assert c.youtube.privacy_status == "public"


def test_youtube_defaults_when_partial(tmp_path):
    (tmp_path / "ch.yaml").write_text(_base_yaml(
        "youtube:\n  auto_upload: false\n"
    ), encoding="utf-8")
    c = load_channel(tmp_path / "ch.yaml")
    assert c.youtube.auto_upload is False
    assert c.youtube.ai_content is True
    assert c.youtube.category_id == "24"
    assert c.youtube.privacy_status == "public"


def test_youtube_round_trips(tmp_path):
    src = tmp_path / "ch.yaml"
    src.write_text(_base_yaml(
        "youtube:\n  auto_upload: true\n  ai_content: true\n"
        "  category_id: '28'\n  privacy_status: private\n"
    ), encoding="utf-8")
    cfg = load_channel(src)
    out = tmp_path / "saved.yaml"
    save_channel(out, cfg)
    reloaded = load_channel(out)
    assert reloaded.youtube.auto_upload is True
    assert reloaded.youtube.category_id == "28"
    assert reloaded.youtube.privacy_status == "private"


def test_youtube_invalid_privacy_rejected(tmp_path):
    (tmp_path / "ch.yaml").write_text(_base_yaml(
        "youtube:\n  privacy_status: weird\n"
    ), encoding="utf-8")
    with pytest.raises(ValueError):
        load_channel(tmp_path / "ch.yaml")


def test_youtube_min_score_default_is_8(tmp_path):
    (tmp_path / "ch.yaml").write_text(_base_yaml(
        "youtube:\n  auto_upload: true\n"
    ), encoding="utf-8")
    c = load_channel(tmp_path / "ch.yaml")
    assert c.youtube.min_score_for_upload == 8.0
    assert c.youtube.cron_preset is None


def test_youtube_min_score_zero_means_no_filter(tmp_path):
    (tmp_path / "ch.yaml").write_text(_base_yaml(
        "youtube:\n  auto_upload: true\n  min_score_for_upload: 0.0\n"
    ), encoding="utf-8")
    c = load_channel(tmp_path / "ch.yaml")
    assert c.youtube.min_score_for_upload == 0.0


def test_youtube_cron_preset_persists(tmp_path):
    src = tmp_path / "ch.yaml"
    src.write_text(_base_yaml(
        "youtube:\n  auto_upload: true\n  cron_preset: daily_09\n"
    ), encoding="utf-8")
    cfg = load_channel(src)
    assert cfg.youtube.cron_preset == "daily_09"
    out = tmp_path / "saved.yaml"
    save_channel(out, cfg)
    reloaded = load_channel(out)
    assert reloaded.youtube.cron_preset == "daily_09"
