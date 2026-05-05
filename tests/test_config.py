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
        "slug: test\nname: Test\nkeywords: [a, b]\nrss_locale: hl=tr&gl=TR&ceid=TR:tr\n"
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
        "slug: 'BAD SLUG!'\nname: x\nkeywords: []\nrss_locale: ''\n"
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
    (tmp_path / "a.yaml").write_text("slug: a\nname: A\nkeywords: []\nrss_locale: ''\nschedule_cron: ''\nduration_s: 30\nmin_score: 0\nmax_candidates_per_run: 1\ntemplate: default\ncolors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\nhandle: x\noutput_dir: x\nenabled: true\ncta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("slug: b\nname: B\nkeywords: []\nrss_locale: ''\nschedule_cron: ''\nduration_s: 30\nmin_score: 0\nmax_candidates_per_run: 1\ntemplate: default\ncolors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\nhandle: x\noutput_dir: x\nenabled: false\ncta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n", encoding="utf-8")
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
        "slug: test\nname: Test\nkeywords: []\nrss_locale: ''\n"
        "schedule_cron: ''\nduration_s: 30\nmin_score: 0\n"
        "max_candidates_per_run: 1\ntemplate: default\n"
        "handle: '@x'\noutput_dir: x\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    with pytest.raises(KeyError):
        load_channel(tmp_path / "ch.yaml")


def test_list_channels_includes_disabled_when_not_filtered(tmp_path):
    (tmp_path / "a.yaml").write_text("slug: a\nname: A\nkeywords: []\nrss_locale: ''\nschedule_cron: ''\nduration_s: 30\nmin_score: 0\nmax_candidates_per_run: 1\ntemplate: default\ncolors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\nhandle: x\noutput_dir: x\nenabled: true\ncta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("slug: b\nname: B\nkeywords: []\nrss_locale: ''\nschedule_cron: ''\nduration_s: 30\nmin_score: 0\nmax_candidates_per_run: 1\ntemplate: default\ncolors: {primary: '#0', accent: '#1', bg_gradient: ['#2','#3']}\nhandle: x\noutput_dir: x\nenabled: false\ncta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n", encoding="utf-8")
    chans = list_channels(tmp_path, enabled_only=False)
    slugs = {c.slug for c in chans}
    assert slugs == {"a", "b"}


def test_save_channel_round_trips(tmp_path):
    """ChannelConfig → save → load should preserve all fields including Turkish chars and emojis."""
    from short_bot.config import save_channel
    src_path = tmp_path / "orig.yaml"
    src_path.write_text(
        "slug: test-rt\nname: 'Türkçe Ad'\nkeywords: ['son dakika', 'asgari ücret']\n"
        "rss_locale: hl=tr&gl=TR&ceid=TR:tr\nschedule_cron: '0 * * * *'\n"
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
