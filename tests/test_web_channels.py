import pytest

from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: haiku\n",
        encoding="utf-8",
    )
    (cfg_dir / "channels" / "demo-tr.yaml").write_text(
        "slug: demo-tr\nname: Demo TR\nlanguage: tr\nkeywords: [a]\n"
        "schedule_cron: '0 * * * *'\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#c81e1e', accent: '#ffea3b', bg_gradient: ['#1a3b6b','#0a1a3b']}\n"
        "handle: '@demo'\noutput_dir: output/demo\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite", scheduler=False)


def test_channels_list_shows_channel(app):
    client = app.test_client()
    resp = client.get("/channels")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "demo-tr" in body
    assert "Demo TR" in body
    assert "newscast" in body


def test_channel_edit_get_renders(app):
    client = app.test_client()
    resp = client.get("/channels/demo-tr/edit")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "demo-tr" in body
    assert "Demo TR" in body


def test_channel_edit_404_when_missing(app):
    client = app.test_client()
    resp = client.get("/channels/nonexistent/edit")
    assert resp.status_code == 404


def test_channel_edit_post_saves(app, tmp_path):
    client = app.test_client()
    resp = client.post("/channels/demo-tr/edit", data={
        "keywords": "yeni, kelimeler",
        "schedule_cron": "0 8,16 * * *",
        "handle": "@updated",
        "duration_s": "10",
        "min_score": "7.0",
        "enabled": "1",
    })
    assert resp.status_code in (200, 302)
    # Reload and verify persistence
    from short_bot.config import load_channel
    cfg_dir = app.config["SHORTBOT_CONFIG_DIR"]
    cfg = load_channel(cfg_dir / "channels" / "demo-tr.yaml")
    assert cfg.handle == "@updated"
    assert cfg.duration_s == 10


def test_channel_edit_renders_dna_editor_when_dna_present(app, tmp_path):
    # Add a channel with DNA
    cfg_dir = app.config["SHORTBOT_CONFIG_DIR"]
    (cfg_dir / "channels" / "with-dna.yaml").write_text(
        """slug: with-dna
name: With DNA
language: tr
keywords: [a]
schedule_cron: '0 * * * *'
duration_s: 6
min_score: 6.0
max_candidates_per_run: 10
template: stadium
colors: {primary: '#0a4d2a', accent: '#ffd700', bg_gradient: ['#1a8b3a','#0a4d1a']}
handle: '@x'
output_dir: output/with-dna
enabled: true
cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}
dna:
  archetype: stadium
  palette:
    primary: '#0a4d2a'
    accent: '#ffd700'
    bg_gradient: ['#1a8b3a', '#0a4d1a']
    body_bg: ['#0a1a0a', '#000000']
  fonts: {headline: Oswald, body: Inter, google_imports: []}
  tone: {voice: x, style: y, forbidden: [], sentence_max_words: 14, paragraph_sentences: [3, 4], body_max_chars: 280, headline_style_hint: ''}
  banner_shape: slanted
  highlight_style: marker
  chip_style: pill
  category_icon: '⚽'
  search_query_template: '{header_top}'
  persona_summary: ''
""", encoding="utf-8")
    client = app.test_client()
    resp = client.get("/channels/with-dna/edit")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'type="color"' in body
    assert "Oswald" in body  # font dropdown current value
    assert "slanted" in body  # banner shape


def test_channel_edit_saves_dna_palette_change(app, tmp_path):
    cfg_dir = app.config["SHORTBOT_CONFIG_DIR"]
    yaml_path = cfg_dir / "channels" / "demo-tr.yaml"
    # Add DNA to demo-tr first
    yaml_path.write_text(
        """slug: demo-tr
name: Demo TR
language: tr
keywords: [a]
schedule_cron: '0 * * * *'
duration_s: 6
min_score: 6.0
max_candidates_per_run: 10
template: newscast
colors: {primary: '#c81e1e', accent: '#ffea3b', bg_gradient: ['#1a3b6b','#0a1a3b']}
handle: '@demo'
output_dir: output/demo
enabled: true
cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}
dna:
  archetype: newscast
  palette:
    primary: '#c81e1e'
    accent: '#ffea3b'
    bg_gradient: ['#1a3b6b', '#0a1a3b']
    body_bg: ['#1a1a2a', '#0a0a1a']
  fonts: {headline: Inter, body: Inter, google_imports: []}
  tone: {voice: x, style: y, forbidden: [], sentence_max_words: 14, paragraph_sentences: [3, 5], body_max_chars: 350, headline_style_hint: ''}
  banner_shape: flat
  highlight_style: bg-flat
  chip_style: rounded
  category_icon: ''
  search_query_template: '{header_top}'
  persona_summary: ''
""", encoding="utf-8")
    client = app.test_client()
    client.post("/channels/demo-tr/edit", data={
        "keywords": "a", "schedule_cron": "0 * * * *",
        "handle": "@demo", "duration_s": "6", "min_score": "6.0", "enabled": "1",
        "dna_primary": "#ff0000", "dna_accent": "#00ff00",
        "dna_font_headline": "Bebas Neue", "dna_font_body": "Roboto",
        "dna_banner_shape": "ribbon", "dna_highlight_style": "marker",
        "dna_chip_style": "pill", "dna_category_icon": "🎬",
    })
    from short_bot.config import load_channel
    cfg = load_channel(yaml_path)
    assert cfg.dna.palette.primary == "#ff0000"
    assert cfg.dna.palette.accent == "#00ff00"
    assert cfg.dna.fonts.headline == "Bebas Neue"
    assert cfg.dna.banner_shape == "ribbon"
