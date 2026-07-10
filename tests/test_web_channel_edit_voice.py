"""channel_edit POST: voice blogunun korunmasi ve guncellenmesi."""
import pytest
import yaml

from short_bot.config import load_channel
from short_bot.web import create_app

CHANNEL_YAML = """\
slug: test-anlatici
name: Test Anlatici
keywords: [gundem]
language: tr
schedule_cron: 0 9 * * *
duration_s: 6
min_score: 7.0
max_candidates_per_run: 3
template: newscast
colors:
  primary: '#b91c1c'
  accent: '#ffea3b'
  bg_gradient: ['#2a3a5e', '#11182f']
handle: '@test'
output_dir: output/test
enabled: true
cta:
  enabled: false
  text: ''
  icons: []
  duration_s: 0
  show_handle: false
"""


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8",
    )
    (cfg_dir / "channels" / "test-anlatici.yaml").write_text(CHANNEL_YAML,
                                                             encoding="utf-8")
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=tmp_path / "data" / "secrets.yaml",
                      scheduler=False)


def _channel_path(app):
    return app.config["SHORTBOT_CONFIG_DIR"] / "channels" / "test-anlatici.yaml"


def _add_voice(app, voice: dict):
    """Mevcut kanal YAML'ina voice blogu ekle."""
    p = _channel_path(app)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["voice"] = voice
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def _post_form(**over):
    # Gerçek şablon (edit.html.j2) voice text/number alanlarını HER ZAMAN
    # gönderir — boş olsalar bile. İşaretsiz checkbox (voice_enabled) gönderilmez.
    # Regresyonu yakalayabilmek için varsayılan formda da bu boş alanlar bulunur.
    form = {
        "schedule_cron": "0 9 * * *", "duration_s": "6", "min_score": "7.0",
        "max_candidates_per_run": "3", "max_age_hours": "24",
        "handle": "@test", "enabled": "1", "cta_enabled": "0",
        "cta_text": "", "cta_duration_s": "0", "cta_show_handle": "0",
        "keywords": "gundem", "content_source": "rss",
        "voice_id": "", "voice_speed": "1.0",
        "voice_persona": "enerjik, meraklı anlatıcı",
        "voice_target_min": "45", "voice_target_max": "60",
    }
    form.update(over)
    return form


def test_post_without_voice_fields_preserves_existing_voice(app):
    """Regresyon kalkani: kanalda voice blogu varsa (checkbox gelmese, voice_id
    bos gonderilse bile) blok silinmez; voice_id fallback ile korunur."""
    path = _add_voice(app, {"enabled": True, "voice_id": "elevenlabs_keep",
                            "speed": 1.1, "target_duration_s": [45, 60]})
    app.test_client().post("/channels/test-anlatici/edit", data=_post_form())

    cfg = load_channel(path)
    assert cfg.voice is not None
    assert cfg.voice.voice_id == "elevenlabs_keep"
    # checkbox gelmedigi icin enabled kapanir; blok yine de korunur
    assert cfg.voice.enabled is False


def test_post_does_not_inject_voice_into_silent_channel(app):
    """Sessiz kanal (voice blogu YOK): sablon bos voice alanlari gonderse bile
    YAML'a voice blogu ENJEKTE edilmemeli."""
    path = _channel_path(app)
    assert load_channel(path).voice is None      # baslangicta sessiz
    app.test_client().post("/channels/test-anlatici/edit", data=_post_form())
    assert load_channel(path).voice is None      # hala sessiz — enjeksiyon yok


def test_post_enabling_voice_on_silent_channel_creates_block(app):
    """Sessiz kanalda checkbox + voice_id ile blok olusur."""
    path = _channel_path(app)
    assert load_channel(path).voice is None
    app.test_client().post("/channels/test-anlatici/edit", data=_post_form(
        voice_enabled="on", voice_id="elevenlabs_x",
    ))
    cfg = load_channel(path)
    assert cfg.voice is not None
    assert cfg.voice.enabled is True
    assert cfg.voice.voice_id == "elevenlabs_x"


def test_post_with_voice_fields_updates_voice(app):
    path = _channel_path(app)
    app.test_client().post("/channels/test-anlatici/edit", data=_post_form(
        voice_enabled="on", voice_id="elevenlabs_new", voice_speed="1.2",
        voice_persona="sakin anlatici",
        voice_target_min="40", voice_target_max="55",
    ))

    cfg = load_channel(path)
    assert cfg.voice.enabled is True
    assert cfg.voice.voice_id == "elevenlabs_new"
    assert cfg.voice.speed == 1.2
    assert cfg.voice.persona == "sakin anlatici"
    assert cfg.voice.target_duration_s == (40, 55)


def test_post_voice_disabled_keeps_block_but_disables(app):
    path = _add_voice(app, {"enabled": True, "voice_id": "elevenlabs_keep"})
    app.test_client().post("/channels/test-anlatici/edit", data=_post_form(
        voice_id="elevenlabs_keep",     # voice_enabled yok -> off
    ))
    cfg = load_channel(path)
    assert cfg.voice.enabled is False
    assert cfg.voice.voice_id == "elevenlabs_keep"


def test_post_enabling_voice_without_voice_id_flashes_error(app):
    path = _channel_path(app)
    resp = app.test_client().post(
        "/channels/test-anlatici/edit",
        data=_post_form(voice_enabled="on", voice_id=" "),
        follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True).lower()
    assert "ses seç" in body or "voice_id" in body
    assert load_channel(path).voice is None    # gecersiz konfig yazilmadi


def test_post_invalid_voice_speed_falls_back_to_default(app):
    path = _channel_path(app)
    app.test_client().post("/channels/test-anlatici/edit", data=_post_form(
        voice_enabled="on", voice_id="elevenlabs_x", voice_speed="abc",
    ))
    assert load_channel(path).voice.speed == 1.0
