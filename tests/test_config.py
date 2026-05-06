from pathlib import Path
import pytest

from short_bot.config import load_settings, load_channel, list_channels, ChannelConfig, Settings


def test_load_settings(tmp_path):
    (tmp_path / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web:\n  host: 127.0.0.1\n  port: 5000\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n",
        encoding="utf-8",
    )
    s = load_settings(tmp_path / "settings.yaml")
    assert isinstance(s, Settings)
    assert s.ffmpeg_path == "ffmpeg"
    assert s.fuzzy_dedup_threshold == 0.85
    assert s.web_port == 5000


def test_load_channel(tmp_path):
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nkeywords: [a, b]\nlanguage: tr\n"
        "schedule_cron: '0 * * * *'\nduration_s: 30\nmin_score: 8.0\n"
        "max_candidates_per_run: 30\ntemplate: default\n"
        "colors:\n  primary: '#c81e1e'\n  accent: '#ffea3b'\n  bg_gradient: ['#1a3b6b', '#0a1a3b']\n"
        "handle: '@x'\noutput_dir: output/test\nenabled: true\n"
        "cta:\n  enabled: true\n  text: 'A · B · C'\n  icons: ['❤️', '🔔', '↗️']\n  duration_s: 4\n  show_handle: true\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.slug == "test"
    assert c.keywords == ["a", "b"]
    assert c.colors["primary"] == "#c81e1e"
    assert c.cta_enabled is True
    assert c.cta_duration_s == 4
    assert c.cta_text == "A · B · C"
    assert c.cta_icons == ["❤️", "🔔", "↗️"]


def test_load_channel_invalid_slug(tmp_path):
    (tmp_path / "bad.yaml").write_text(
        "slug: 'BAD SLUG!'\nname: x\nkeywords: []\nlanguage: tr\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: default\n"
        "colors: {primary: '#000', accent: '#fff', bg_gradient: ['#0', '#1']}\n"
        "handle: '@x'\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="slug"):
        load_channel(tmp_path / "bad.yaml")


def test_list_channels(tmp_path):
    (tmp_path / "a.yaml").write_text("slug: a\nname: A\nkeywords: [a]\nlanguage: tr\nschedule_cron: ''\nduration_s: 30\nmin_score: 0\nmax_candidates_per_run: 1\ntemplate: default\ncolors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\nhandle: x\noutput_dir: x\nenabled: true\ncta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("slug: b\nname: B\nkeywords: [b]\nlanguage: tr\nschedule_cron: ''\nduration_s: 30\nmin_score: 0\nmax_candidates_per_run: 1\ntemplate: default\ncolors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\nhandle: x\noutput_dir: x\nenabled: false\ncta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n", encoding="utf-8")
    chans = list_channels(tmp_path, enabled_only=True)
    assert len(chans) == 1 and chans[0].slug == "a"


def test_load_settings_missing_required_raises(tmp_path):
    # Missing ffmpeg_path
    (tmp_path / "settings.yaml").write_text(
        "claude_cli_path: claude\nweb: {host: 127.0.0.1, port: 5000}\n",
        encoding="utf-8",
    )
    with pytest.raises(KeyError):
        load_settings(tmp_path / "settings.yaml")


def test_load_channel_missing_required_raises(tmp_path):
    # Missing 'colors' key
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nkeywords: [a]\nlanguage: tr\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: default\n"
        "handle: '@x'\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    with pytest.raises(KeyError):
        load_channel(tmp_path / "ch.yaml")


def test_list_channels_includes_disabled_when_not_filtered(tmp_path):
    (tmp_path / "a.yaml").write_text("slug: a\nname: A\nkeywords: [a]\nlanguage: tr\nschedule_cron: ''\nduration_s: 30\nmin_score: 0\nmax_candidates_per_run: 1\ntemplate: default\ncolors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\nhandle: x\noutput_dir: x\nenabled: true\ncta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("slug: b\nname: B\nkeywords: [b]\nlanguage: tr\nschedule_cron: ''\nduration_s: 30\nmin_score: 0\nmax_candidates_per_run: 1\ntemplate: default\ncolors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\nhandle: x\noutput_dir: x\nenabled: false\ncta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n", encoding="utf-8")
    chans = list_channels(tmp_path, enabled_only=False)
    slugs = {c.slug for c in chans}
    assert slugs == {"a", "b"}


def test_save_channel_round_trips(tmp_path):
    """ChannelConfig → save → load should preserve all fields including Turkish chars and emojis."""
    from short_bot.config import save_channel
    src_path = tmp_path / "orig.yaml"
    src_path.write_text(
        "slug: test-rt\nname: 'Türkçe Ad'\nkeywords: ['son dakika', 'asgari ücret']\n"
        "language: tr\nschedule_cron: '0 * * * *'\n"
        "duration_s: 30\nmin_score: 8.0\nmax_candidates_per_run: 10\ntemplate: default\n"
        "colors:\n  primary: '#c81e1e'\n  accent: '#ffea3b'\n  bg_gradient: ['#1a3b6b', '#0a1a3b']\n"
        "handle: '@RoundTrip'\noutput_dir: output/test-rt\nenabled: true\n"
        "cta:\n  enabled: true\n  text: 'BEĞEN · ABONE OL · PAYLAŞ'\n  icons: ['❤️', '🔔', '↗️']\n  duration_s: 4\n  show_handle: true\n",
        encoding="utf-8",
    )
    original = load_channel(src_path)

    out_path = tmp_path / "saved.yaml"
    save_channel(out_path, original)
    loaded = load_channel(out_path)

    assert loaded.slug == original.slug
    assert loaded.name == "Türkçe Ad"
    assert loaded.keywords == ["son dakika", "asgari ücret"]
    assert loaded.colors == original.colors
    assert loaded.cta_text == "BEĞEN · ABONE OL · PAYLAŞ"
    assert loaded.cta_icons == ["❤️", "🔔", "↗️"]
    assert loaded.cta_duration_s == 4
    assert loaded.handle == "@RoundTrip"


def test_load_settings_default_claude_models(tmp_path):
    (tmp_path / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5000}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n",
        encoding="utf-8",
    )
    s = load_settings(tmp_path / "settings.yaml")
    assert s.claude_models == {"dna": "opus", "default": "haiku"}


def test_load_settings_custom_claude_models(tmp_path):
    (tmp_path / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5000}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: sonnet\n",
        encoding="utf-8",
    )
    s = load_settings(tmp_path / "settings.yaml")
    assert s.claude_models["default"] == "sonnet"


def test_load_channel_with_language_field(tmp_path):
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nkeywords: [a]\nlanguage: de\n"
        "schedule_cron: '0 * * * *'\nduration_s: 30\nmin_score: 8.0\n"
        "max_candidates_per_run: 30\ntemplate: newscast\n"
        "colors:\n  primary: '#c81e1e'\n  accent: '#ffea3b'\n  bg_gradient: ['#1a3b6b', '#0a1a3b']\n"
        "handle: '@x'\noutput_dir: output/test\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.language == "de"
    # rss_locale field auto-derived from language
    assert c.rss_locale == "hl=de&gl=DE&ceid=DE:de"


def test_load_channel_backward_compat_rss_locale_only(tmp_path):
    """Legacy YAML with rss_locale but no language field should still work."""
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nkeywords: [a]\nrss_locale: hl=tr&gl=TR&ceid=TR:tr\n"
        "schedule_cron: '0 * * * *'\nduration_s: 30\nmin_score: 8.0\n"
        "max_candidates_per_run: 30\ntemplate: default\n"
        "colors:\n  primary: '#c81e1e'\n  accent: '#ffea3b'\n  bg_gradient: ['#1a3b6b', '#0a1a3b']\n"
        "handle: '@x'\noutput_dir: output/test\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.language == "tr"  # default when not set
    assert c.rss_locale == "hl=tr&gl=TR&ceid=TR:tr"


def test_load_channel_invalid_language_raises(tmp_path):
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nkeywords: []\nlanguage: xx\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: newscast\n"
        "colors: {primary: '#000', accent: '#fff', bg_gradient: ['#0','#1']}\n"
        "handle: '@x'\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="language"):
        load_channel(tmp_path / "ch.yaml")


def test_load_channel_with_dna_block(tmp_path):
    yaml_text = """slug: test
name: Test
language: de
keywords: [a]
schedule_cron: '0 * * * *'
duration_s: 30
min_score: 8.0
max_candidates_per_run: 30
template: stadium
colors:
  primary: '#0a4d2a'
  accent: '#ffd700'
  bg_gradient: ['#1a8b3a','#0a4d1a']
handle: '@x'
output_dir: output/test
enabled: true
cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}
dna:
  archetype: stadium
  palette:
    primary: '#0a4d2a'
    accent: '#ffd700'
    bg_gradient: ['#1a8b3a','#0a4d1a']
    body_bg: ['#0a1a0a','#000000']
  fonts:
    headline: 'Bebas Neue'
    body: 'Inter'
    google_imports: ['Bebas+Neue']
  tone:
    voice: 'leidenschaftlich'
    style: 'dynamisch'
    forbidden: []
    sentence_max_words: 14
    paragraph_sentences: [3, 4]
    body_max_chars: 280
    headline_style_hint: ''
  banner_shape: slanted
  highlight_style: marker
  chip_style: pill
  category_icon: '⚽'
  search_query_template: '{header_top} football'
  persona_summary: 'Spor kanalı'
"""
    (tmp_path / "ch.yaml").write_text(yaml_text, encoding="utf-8")
    c = load_channel(tmp_path / "ch.yaml")
    assert c.template == "stadium"
    assert c.dna is not None
    assert c.dna.archetype == "stadium"
    assert c.dna.palette.primary == "#0a4d2a"
    assert c.dna.tone.body_max_chars == 280


def test_load_channel_no_dna_block_returns_none(tmp_path):
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nlanguage: tr\nkeywords: [a]\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: newscast\n"
        "colors: {primary: '#000000', accent: '#ffffff', bg_gradient: ['#000000','#111111']}\n"
        "handle: '@x'\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.dna is None
    assert c.template == "newscast"


def test_load_channel_template_dna_archetype_mismatch_raises(tmp_path):
    yaml_text = """slug: test
name: Test
language: tr
keywords: []
schedule_cron: ''
duration_s: 30
min_score: 0
max_candidates_per_run: 1
template: newscast
colors: {primary: '#000000', accent: '#ffffff', bg_gradient: ['#000000','#111111']}
handle: '@x'
output_dir: x
enabled: true
cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}
dna:
  archetype: tabloid
  palette:
    primary: '#ffea3b'
    accent: '#c81e1e'
    bg_gradient: ['#ffea3b','#ff9999']
    body_bg: ['#ffffff','#eeeeee']
  fonts: {headline: Inter, body: Inter, google_imports: []}
  tone: {voice: x, style: y, forbidden: [], sentence_max_words: 14, paragraph_sentences: [2,3], body_max_chars: 200, headline_style_hint: ''}
  banner_shape: flat
  highlight_style: bg-flat
  chip_style: rounded
  category_icon: ''
  search_query_template: '{header_top}'
  persona_summary: ''
"""
    (tmp_path / "ch.yaml").write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ValueError, match="template.*archetype"):
        load_channel(tmp_path / "ch.yaml")


def test_load_channel_legacy_template_default_maps_to_newscast(tmp_path):
    """Backward-compat: 'template: default' should be loaded as 'newscast'."""
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nlanguage: tr\nkeywords: [a]\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: default\n"
        "colors: {primary: '#000000', accent: '#ffffff', bg_gradient: ['#000000','#111111']}\n"
        "handle: '@x'\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.template == "newscast"


def test_load_channel_with_script_model_override(tmp_path):
    (tmp_path / "ch.yaml").write_text(
        "slug: test\nname: Test\nlanguage: tr\nkeywords: [a]\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: newscast\nscript_model: sonnet\n"
        "colors: {primary: '#000000', accent: '#ffffff', bg_gradient: ['#000000','#111111']}\n"
        "handle: '@x'\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.script_model == "sonnet"


def test_rss_channel_with_empty_keywords_is_rejected(tmp_path):
    """Regression: RSS-mode channel with empty keywords used to crash mid-pipeline
    at fetch_rss. Now it fails fast at load time."""
    (tmp_path / "ch.yaml").write_text(
        "slug: ch\nname: C\nkeywords: []\nlanguage: tr\n"
        "schedule_cron: '* * * * *'\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}\n"
        "handle: '@c'\noutput_dir: out\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="content_source='rss' but no keywords"):
        load_channel(tmp_path / "ch.yaml")


def test_generator_channel_with_empty_keywords_is_allowed(tmp_path):
    """Generator-mode channels legitimately have empty keywords."""
    (tmp_path / "ch.yaml").write_text(
        "slug: ch\nname: C\nkeywords: []\nlanguage: tr\n"
        "schedule_cron: '* * * * *'\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "content_source: generator\n"
        "generator:\n  topic: 'sözlük üzerine kısa şiirsel sözler ve özlü sözler'\n"
        "  forbidden_lookback: 100\n  max_retries: 3\n"
        "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}\n"
        "handle: '@c'\noutput_dir: out\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.content_source == "generator"
    assert c.keywords == []


def test_bg_video_config_defaults():
    from short_bot.config import BgVideoConfig
    cfg = BgVideoConfig()
    assert cfg.enabled is False
    assert cfg.scale == 0.88
    assert cfg.blur_px == 30
    assert cfg.dim == 0.4


def test_bg_video_config_accepts_valid_scale():
    from short_bot.config import BgVideoConfig
    BgVideoConfig(scale=0.88)
    BgVideoConfig(scale=0.80)


def test_bg_video_config_rejects_invalid_scale():
    from pydantic import ValidationError
    from short_bot.config import BgVideoConfig
    with pytest.raises(ValidationError):
        BgVideoConfig(scale=0.5)
    with pytest.raises(ValidationError):
        BgVideoConfig(scale=1.0)


def test_bg_video_config_blur_range():
    from pydantic import ValidationError
    from short_bot.config import BgVideoConfig
    BgVideoConfig(blur_px=0)
    BgVideoConfig(blur_px=80)
    with pytest.raises(ValidationError):
        BgVideoConfig(blur_px=-1)
    with pytest.raises(ValidationError):
        BgVideoConfig(blur_px=81)


def test_bg_video_config_dim_range():
    from pydantic import ValidationError
    from short_bot.config import BgVideoConfig
    BgVideoConfig(dim=0.0)
    BgVideoConfig(dim=1.0)
    with pytest.raises(ValidationError):
        BgVideoConfig(dim=-0.1)
    with pytest.raises(ValidationError):
        BgVideoConfig(dim=1.5)


def _minimal_channel_yaml(bg_video_block: str = "") -> str:
    """Return a YAML body that parses to a valid channel; optionally append a bg_video block."""
    return f"""\
slug: test-bg
name: Test BG
keywords: [x]
language: tr
schedule_cron: 0 * * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: newscast
colors:
  primary: '#c81e1e'
  accent: '#ffea3b'
  bg_gradient: ['#000000', '#111111']
handle: '@x'
output_dir: output/test-bg
enabled: true
cta:
  enabled: false
  text: ''
  icons: []
  duration_s: 0
  show_handle: false
{bg_video_block}
"""


def test_load_channel_bg_video_absent_yields_none(tmp_path):
    from short_bot.config import load_channel
    p = tmp_path / "c.yaml"
    p.write_text(_minimal_channel_yaml(), encoding="utf-8")
    c = load_channel(p)
    assert c.bg_video is None


def test_load_channel_bg_video_block_parses(tmp_path):
    from short_bot.config import load_channel
    p = tmp_path / "c.yaml"
    block = "bg_video:\n  enabled: true\n  scale: 0.80\n  blur_px: 20\n  dim: 0.3\n"
    p.write_text(_minimal_channel_yaml(block), encoding="utf-8")
    c = load_channel(p)
    assert c.bg_video is not None
    assert c.bg_video.enabled is True
    assert c.bg_video.scale == 0.80
    assert c.bg_video.blur_px == 20
    assert c.bg_video.dim == 0.3


def test_save_channel_round_trip_preserves_bg_video(tmp_path):
    import yaml
    from short_bot.config import load_channel, save_channel
    src = tmp_path / "c.yaml"
    block = "bg_video:\n  enabled: true\n  scale: 0.88\n  blur_px: 30\n  dim: 0.4\n"
    src.write_text(_minimal_channel_yaml(block), encoding="utf-8")
    c = load_channel(src)

    dst = tmp_path / "out.yaml"
    save_channel(dst, c)
    raw = yaml.safe_load(dst.read_text(encoding="utf-8"))
    assert raw["bg_video"]["enabled"] is True
    assert raw["bg_video"]["scale"] == 0.88
    assert raw["bg_video"]["blur_px"] == 30
    assert raw["bg_video"]["dim"] == 0.4


def test_save_channel_omits_bg_video_when_disabled_default(tmp_path):
    """Channels without bg_video shouldn't gain the block on save (keeps YAML clean)."""
    import yaml
    from short_bot.config import load_channel, save_channel
    src = tmp_path / "c.yaml"
    src.write_text(_minimal_channel_yaml(), encoding="utf-8")
    c = load_channel(src)
    dst = tmp_path / "out.yaml"
    save_channel(dst, c)
    raw = yaml.safe_load(dst.read_text(encoding="utf-8"))
    assert "bg_video" not in raw
