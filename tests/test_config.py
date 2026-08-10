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
    # Beğeni/abone CTA alanları KALDIRILDI (2026-07-16) — eski YAML'daki
    # 'cta:' bölümü sessizce yok sayılır, alan olarak taşınmaz.
    assert not hasattr(c, "cta_enabled")


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
  archetype: stadium
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
    assert cfg.dim == 0.7


def test_load_channel_max_age_hours_default(tmp_path):
    """Channels without max_age_hours field get the safe default of 24h."""
    (tmp_path / "ch.yaml").write_text(
        "slug: t\nname: T\nkeywords: [a]\nlanguage: tr\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: default\n"
        "colors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\n"
        "handle: x\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.max_age_hours == 24


def test_load_channel_max_age_hours_explicit(tmp_path):
    """Explicit max_age_hours overrides the default."""
    (tmp_path / "ch.yaml").write_text(
        "slug: t\nname: T\nkeywords: [a]\nlanguage: tr\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\nmax_age_hours: 6\ntemplate: default\n"
        "colors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\n"
        "handle: x\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    c = load_channel(tmp_path / "ch.yaml")
    assert c.max_age_hours == 6


def test_save_channel_round_trips_max_age_hours(tmp_path):
    """save_channel writes max_age_hours so it survives reload."""
    from short_bot.config import save_channel
    src = (
        "slug: t\nname: T\nkeywords: [a]\nlanguage: tr\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\nmax_age_hours: 12\ntemplate: default\n"
        "colors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\n"
        "handle: x\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n"
    )
    p = tmp_path / "ch.yaml"
    p.write_text(src, encoding="utf-8")
    c = load_channel(p)
    save_channel(p, c)
    c2 = load_channel(p)
    assert c2.max_age_hours == 12


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


def test_channel_config_dynamic_dna_default_false(tmp_path):
    """dynamic_dna defaults to False; YAML without the key loads cleanly."""
    from short_bot.config import load_channel
    yaml_text = """
slug: test-ch
name: Test
keywords: [a]
language: tr
schedule_cron: "0 * * * *"
duration_s: 25
min_score: 6.0
max_candidates_per_run: 3
template: newscast
colors: {primary: "#fff"}
handle: "@test"
output_dir: "out"
"""
    p = tmp_path / "ch.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    cfg = load_channel(p)
    assert cfg.dynamic_dna is False


def test_channel_config_dynamic_dna_round_trip(tmp_path):
    """dynamic_dna=True survives save → load."""
    from short_bot.config import ChannelConfig, load_channel, save_channel
    cfg = ChannelConfig(
        slug="test-ch", name="Test", keywords=["a"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@test", output_dir="out",
        enabled=True, language="tr",
        max_age_hours=24, dynamic_dna=True,
    )
    p = tmp_path / "ch.yaml"
    save_channel(p, cfg)
    cfg2 = load_channel(p)
    assert cfg2.dynamic_dna is True


def test_channel_config_dynamic_dna_false_not_written(tmp_path):
    """When dynamic_dna=False, the key is NOT written to YAML (keeps yamls clean)."""
    from short_bot.config import ChannelConfig, save_channel
    cfg = ChannelConfig(
        slug="test-ch", name="Test", keywords=["a"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@test", output_dir="out",
        enabled=True, language="tr",
        max_age_hours=24, dynamic_dna=False,
    )
    p = tmp_path / "ch.yaml"
    save_channel(p, cfg)
    text = p.read_text(encoding="utf-8")
    assert "dynamic_dna" not in text


def test_channel_config_negative_keywords_default_empty(tmp_path):
    """negative_keywords defaults to []; YAML without the key loads cleanly."""
    from short_bot.config import load_channel
    yaml_text = """
slug: test-ch
name: Test
keywords: [a]
language: tr
schedule_cron: "0 * * * *"
duration_s: 25
min_score: 6.0
max_candidates_per_run: 3
template: newscast
colors: {primary: "#fff"}
handle: "@test"
output_dir: "out"
"""
    p = tmp_path / "ch.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    cfg = load_channel(p)
    assert cfg.negative_keywords == []


def test_channel_config_negative_keywords_round_trip(tmp_path):
    """negative_keywords list survives save → load."""
    from short_bot.config import ChannelConfig, load_channel, save_channel
    cfg = ChannelConfig(
        slug="test-ch", name="Test", keywords=["a"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@test", output_dir="out",
        enabled=True, language="tr",
        max_age_hours=24, dynamic_dna=False,
        negative_keywords=["wwe", "wrestling"],
    )
    p = tmp_path / "ch.yaml"
    save_channel(p, cfg)
    cfg2 = load_channel(p)
    assert cfg2.negative_keywords == ["wwe", "wrestling"]


def test_channel_config_negative_keywords_empty_not_written(tmp_path):
    """When negative_keywords is empty, the key is NOT written to YAML."""
    from short_bot.config import ChannelConfig, save_channel
    cfg = ChannelConfig(
        slug="test-ch", name="Test", keywords=["a"], rss_locale="tr-TR",
        schedule_cron="0 * * * *", duration_s=25, min_score=6.0,
        max_candidates_per_run=3, template="newscast",
        colors={"primary": "#fff"}, handle="@test", output_dir="out",
        enabled=True, language="tr",
        max_age_hours=24, dynamic_dna=False,
        negative_keywords=[],
    )
    p = tmp_path / "ch.yaml"
    save_channel(p, cfg)
    text = p.read_text(encoding="utf-8")
    assert "negative_keywords" not in text


def test_load_settings_ai_backend_default_claude_cli(tmp_path):
    (tmp_path / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5000}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n",
        encoding="utf-8",
    )
    s = load_settings(tmp_path / "settings.yaml")
    assert s.ai_backend == "claude_cli"
    assert s.openrouter_models == {}


def test_load_settings_openrouter_block(tmp_path):
    (tmp_path / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5000}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "ai_backend: openrouter\n"
        "openrouter_models:\n  dna: anthropic/claude-opus-4.8\n"
        "  default: google/gemini-2.5-flash\n  script: anthropic/claude-sonnet-4.6\n",
        encoding="utf-8",
    )
    s = load_settings(tmp_path / "settings.yaml")
    assert s.ai_backend == "openrouter"
    assert s.openrouter_models["dna"] == "anthropic/claude-opus-4.8"
    assert s.openrouter_models["default"] == "google/gemini-2.5-flash"


def _settings_with(ai_backend, claude_models=None, openrouter_models=None):
    from short_bot.config import Settings
    return Settings(
        ffmpeg_path="ffmpeg", claude_cli_path="claude", playwright_browser="chromium",
        web_host="127.0.0.1", web_port=5005, fuzzy_dedup_threshold=0.85, log_level="INFO",
        claude_models=claude_models or {"dna": "opus", "default": "haiku", "script": "sonnet"},
        ai_backend=ai_backend, openrouter_models=openrouter_models or {},
    )


def test_resolve_ai_call_claude_cli():
    from short_bot.config import resolve_ai_call
    s = _settings_with("claude_cli")
    call = resolve_ai_call(s, {}, "script")
    assert call.backend == "claude_cli"
    assert call.model == "sonnet"
    assert call.api_key is None
    assert call.claude_path == "claude"


def test_resolve_ai_call_openrouter():
    from short_bot.config import resolve_ai_call
    s = _settings_with("openrouter", openrouter_models={
        "dna": "anthropic/claude-opus-4.8", "default": "google/gemini-2.5-flash",
        "script": "anthropic/claude-sonnet-4.6"})
    call = resolve_ai_call(s, {"openrouter_api_key": "sk-or-x"}, "script")
    assert call.backend == "openrouter"
    assert call.model == "anthropic/claude-sonnet-4.6"
    assert call.api_key == "sk-or-x"


def test_resolve_ai_call_openrouter_falls_back_to_default_model():
    from short_bot.config import resolve_ai_call
    s = _settings_with("openrouter", openrouter_models={"default": "google/gemini-2.5-flash"})
    call = resolve_ai_call(s, {"openrouter_api_key": "k"}, "dna")  # 'dna' tanımsız
    assert call.model == "google/gemini-2.5-flash"


def test_resolve_ai_call_claude_cli_falls_back_to_haiku():
    from short_bot.config import resolve_ai_call
    s = _settings_with("claude_cli", claude_models={"dna": "opus"})
    call = resolve_ai_call(s, {}, "default")  # 'default' tanımsız
    assert call.model == "haiku"


def test_resolve_ai_call_vision_openrouter():
    from short_bot.config import resolve_ai_call
    s = _settings_with("openrouter", openrouter_models={
        "default": "google/gemini-2.5-flash",
        "vision": "google/gemma-4-31b-it"})
    call = resolve_ai_call(s, {"openrouter_api_key": "k"}, "vision")
    assert call.backend == "openrouter"
    assert call.model == "google/gemma-4-31b-it"


def test_resolve_ai_call_vision_claude_cli_default():
    from short_bot.config import resolve_ai_call
    s = _settings_with("claude_cli", claude_models={
        "default": "haiku", "vision": "default"})
    call = resolve_ai_call(s, {}, "vision")
    assert call.backend == "claude_cli"
    assert call.model == "default"


def test_resolve_ai_call_vision_claude_cli_falls_back_to_default_when_unset():
    """settings.yaml'da claude_models.vision YOKSA bile vision rolu 'default'
    modele duser (haiku degil) — CLI vision-capable varsayilani korunur."""
    from short_bot.config import resolve_ai_call
    s = _settings_with("claude_cli", claude_models={"dna": "opus", "default": "haiku"})
    call = resolve_ai_call(s, {}, "vision")
    assert call.model == "default"



def test_save_channel_round_trips_categories(tmp_path):
    """categories YAML'dan okunur ve geri yazılır (reload'da kaybolmaz)."""
    from short_bot.config import save_channel
    src = (
        "slug: t\nname: T\nkeywords: [a]\nlanguage: tr\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: default\n"
        "categories: [transfer-gelen, avrupa-kura]\n"
        "colors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\n"
        "handle: x\noutput_dir: x\nenabled: true\n"
    )
    p = tmp_path / "ch.yaml"
    p.write_text(src, encoding="utf-8")
    c = load_channel(p)
    assert c.categories == ["transfer-gelen", "avrupa-kura"]
    save_channel(p, c)
    assert load_channel(p).categories == ["transfer-gelen", "avrupa-kura"]


def test_channel_without_categories_defaults_empty(tmp_path):
    """Liste tanımlamayan kanallar serbest etikette kalır."""
    src = (
        "slug: t\nname: T\nkeywords: [a]\nlanguage: tr\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: default\n"
        "colors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\n"
        "handle: x\noutput_dir: x\nenabled: true\n"
    )
    p = tmp_path / "ch.yaml"
    p.write_text(src, encoding="utf-8")
    assert load_channel(p).categories == []


def test_category_quota_round_trips(tmp_path):
    """Kategori kotası YAML'dan okunur ve geri yazılır."""
    from short_bot.config import save_channel
    src = (
        "slug: t\nname: T\nkeywords: [a]\nlanguage: tr\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: default\n"
        "category_quota_per_day: {transfer-gelen: 3, mac-skor: 1}\n"
        "colors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\n"
        "handle: x\noutput_dir: x\nenabled: true\n"
    )
    p = tmp_path / "ch.yaml"
    p.write_text(src, encoding="utf-8")
    c = load_channel(p)
    assert c.category_quota_per_day == {"transfer-gelen": 3, "mac-skor": 1}
    save_channel(p, c)
    assert load_channel(p).category_quota_per_day == {"transfer-gelen": 3, "mac-skor": 1}


def test_category_quota_defaults_empty(tmp_path):
    src = (
        "slug: t\nname: T\nkeywords: [a]\nlanguage: tr\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: default\n"
        "colors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\n"
        "handle: x\noutput_dir: x\nenabled: true\n"
    )
    p = tmp_path / "ch.yaml"
    p.write_text(src, encoding="utf-8")
    assert load_channel(p).category_quota_per_day == {}
