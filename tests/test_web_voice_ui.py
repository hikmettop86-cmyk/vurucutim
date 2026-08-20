"""Web paneli seslendirme arayüzü: düzenleme bölümü + /api/ai33/voices endpointi.

Hiçbir test gerçek ağ çağrısı yapmaz — voices endpointi ya anahtarsız kısa
devre yapar ya da ``list_voices`` monkeypatch'lenir.
"""
import pytest
import yaml

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


def test_edit_page_shows_voice_section(app):
    """Düzenleme sayfası tüm seslendirme form alanlarını içermeli."""
    body = app.test_client().get("/channels/test-anlatici/edit").data.decode("utf-8")
    assert "Seslendirme" in body
    for name in ("voice_enabled", "voice_id", "voice_speed", "voice_persona",
                 "voice_target_min", "voice_target_max"):
        assert f'name="{name}"' in body, f"{name} form alanı eksik"


def test_edit_page_prefills_existing_voice(app):
    """Kanalda voice blogu varsa voice_id degeri HTML'de gorunmeli."""
    _add_voice(app, {"enabled": True, "voice_id": "elevenlabs_prefill",
                     "speed": 1.1, "persona": "sakin anlatici",
                     "target_duration_s": [40, 55]})
    body = app.test_client().get("/channels/test-anlatici/edit").data.decode("utf-8")
    assert "elevenlabs_prefill" in body
    assert "sakin anlatici" in body


def test_voices_endpoint_without_key_returns_empty(app, monkeypatch):
    """Anahtar yoksa: 200 + bos liste + hata alani (arayuz dostu)."""
    monkeypatch.delenv("AI33_API_KEY", raising=False)
    resp = app.test_client().get("/api/ai33/voices")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["voices"] == []
    assert "error" in data and data["error"]


def test_voices_endpoint_returns_list(app, monkeypatch):
    """Anahtar varsa: list_voices ciktisi JSON olarak donmeli (ag yok)."""
    monkeypatch.setenv("AI33_API_KEY", "test-key")

    def fake_list_voices(**kwargs):
        return [
            {"voice_id": "elevenlabs_rachel", "name": "Rachel", "language": "en"},
            {"voice_id": "elevenlabs_deniz", "name": "Deniz", "language": "tr"},
        ]

    # Rota artık kütüphaneyi SAYFALAYARAK çeken fetch_all_voices'ı kullanıyor
    # (tek sayfada Türkçe sesler görünmüyordu); sahte onun yerine takılır.
    monkeypatch.setattr("short_bot.voice_picker.fetch_all_voices", fake_list_voices)

    resp = app.test_client().get("/api/ai33/voices")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "error" not in data
    ids = [v["voice_id"] for v in data["voices"]]
    assert ids == ["elevenlabs_rachel", "elevenlabs_deniz"]
    assert data["voices"][0]["name"] == "Rachel"
    assert data["voices"][1]["language"] == "tr"
