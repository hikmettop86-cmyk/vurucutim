import pytest

from short_bot.config import (
    ChannelConfig, GeneratorConfig, load_channel, save_channel,
)


def _make_rss_yaml(tmp_path):
    p = tmp_path / "ch.yaml"
    p.write_text("""\
slug: test-rss
name: Test RSS
language: tr
keywords: [haber, ekonomi]
schedule_cron: "0 8 * * *"
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors: {primary: "#c81e1e", accent: "#ffea3b", bg_gradient: ["#1a3b6b", "#0a1a3b"]}
handle: "@test"
output_dir: output/test
enabled: true
cta:
  enabled: true
  text: BEĞEN
  icons: ["❤️"]
  duration_s: 4
  show_handle: true
""", encoding="utf-8")
    return p


def _make_generator_yaml(tmp_path):
    p = tmp_path / "gen.yaml"
    p.write_text("""\
slug: sevgi
name: Sevgi
language: tr
content_source: generator
generator:
  topic: "Sevgi ve aşk üzerine kısa, vurucu sözler"
  forbidden_lookback: 50
  max_retries: 3
  fuzzy_threshold: 0.85
schedule_cron: "0 9 * * *"
duration_s: 7
min_score: 0.0
max_candidates_per_run: 1
template: kinetic
colors: {primary: "#c81e1e", accent: "#ffea3b", bg_gradient: ["#000", "#111"]}
handle: "@sevgi"
output_dir: output/sevgi
enabled: true
cta:
  enabled: true
  text: BEĞEN
  icons: ["❤️"]
  duration_s: 4
  show_handle: true
""", encoding="utf-8")
    return p


def test_default_content_source_is_rss(tmp_path):
    cfg = load_channel(_make_rss_yaml(tmp_path))
    assert cfg.content_source == "rss"
    assert cfg.generator is None


def test_load_generator_channel(tmp_path):
    cfg = load_channel(_make_generator_yaml(tmp_path))
    assert cfg.content_source == "generator"
    assert cfg.generator is not None
    assert cfg.generator.topic.startswith("Sevgi")
    assert cfg.generator.forbidden_lookback == 50
    assert cfg.generator.max_retries == 3
    assert cfg.generator.fuzzy_threshold == 0.85


def test_generator_block_required_when_source_is_generator(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("""\
slug: bad
name: Bad
language: tr
content_source: generator
schedule_cron: "0 9 * * *"
duration_s: 7
min_score: 0.0
max_candidates_per_run: 1
template: kinetic
colors: {primary: "#000", accent: "#111", bg_gradient: ["#000", "#111"]}
handle: "@x"
output_dir: output/bad
enabled: true
cta: {enabled: false, text: "", icons: [], duration_s: 0, show_handle: false}
""", encoding="utf-8")
    with pytest.raises(ValueError, match="generator"):
        load_channel(p)


def test_generator_topic_min_length(tmp_path):
    """topic too short → reject."""
    p = tmp_path / "short.yaml"
    p.write_text("""\
slug: short-topic
name: X
language: tr
content_source: generator
generator: {topic: "kisa"}
schedule_cron: "0 9 * * *"
duration_s: 7
min_score: 0.0
max_candidates_per_run: 1
template: kinetic
colors: {primary: "#000", accent: "#111", bg_gradient: ["#000", "#111"]}
handle: "@x"
output_dir: output/x
enabled: true
cta: {enabled: false, text: "", icons: [], duration_s: 0, show_handle: false}
""", encoding="utf-8")
    with pytest.raises(ValueError, match="topic"):
        load_channel(p)


def test_save_channel_roundtrip_generator(tmp_path):
    src = _make_generator_yaml(tmp_path)
    cfg = load_channel(src)
    dst = tmp_path / "out.yaml"
    save_channel(dst, cfg)
    cfg2 = load_channel(dst)
    assert cfg2.content_source == "generator"
    assert cfg2.generator.topic == cfg.generator.topic
    assert cfg2.generator.forbidden_lookback == 50
    assert cfg2.generator.fuzzy_threshold == 0.85
