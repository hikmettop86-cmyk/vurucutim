"""Panel: Cartesia anahtarı (ayarlar), /api/cartesia/* uçları, ses kartında sağlayıcı alanları."""
from __future__ import annotations

import pytest
import yaml

from short_bot.web import create_app


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
    (cfg_dir / "channels" / "demo.yaml").write_text("""\
slug: demo
name: Demo
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
handle: '@demo'
output_dir: output/demo
enabled: true
""", encoding="utf-8")
    (tmp_path / "data").mkdir()
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=tmp_path / "data" / "secrets.yaml",
                      scheduler=False)


def _secrets(tmp_path):
    p = tmp_path / "data" / "secrets.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


# --- ayarlar ----------------------------------------------------------------------

def test_settings_page_has_cartesia_key_field(app):
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert 'name="cartesia_api_key"' in body
    assert "Cartesia" in body


def test_settings_post_saves_and_clears_cartesia_key(app, tmp_path):
    c = app.test_client()
    c.post("/settings", data={"cartesia_api_key": "sk_car_test"})
    assert _secrets(tmp_path)["cartesia_api_key"] == "sk_car_test"
    body = c.get("/settings").data.decode("utf-8")
    assert "sk_car_test" not in body and "…" in body or "****" in body or "sk_c" in body
    c.post("/settings", data={"cartesia_api_key_clear": "1"})
    assert "cartesia_api_key" not in _secrets(tmp_path)


def test_settings_shows_monthly_usage(app, tmp_path, monkeypatch):
    from short_bot.tts import cartesia_client as cc
    monkeypatch.setattr(cc, "month_usage", lambda d, now=None: 12345)
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert "12.345" in body or "12345" in body


# --- api --------------------------------------------------------------------------

def test_api_voices_requires_key(app):
    r = app.test_client().get("/api/cartesia/voices?language=tr")
    assert r.status_code == 200
    assert r.get_json()["voices"] == [] and "anahtar" in r.get_json()["error"].lower()


def test_api_voices_passes_language(app, tmp_path, monkeypatch):
    app.test_client().post("/settings", data={"cartesia_api_key": "k"})
    from short_bot.web.routes import cartesia_api
    seen = {}

    def _fake(*, api_key, language=None, q=None, **kw):
        seen.update(api_key=api_key, language=language, q=q)
        return [{"voice_id": "a", "name": "Taylan", "language": "tr", "gender": "masculine",
                 "is_pro": False, "is_owner": False, "preview_url": "https://p/a.wav", "description": ""}]
    monkeypatch.setattr(cartesia_api, "list_voices", _fake)
    r = app.test_client().get("/api/cartesia/voices?language=de&q=Tay")
    assert seen == {"api_key": "k", "language": "de", "q": "Tay"}
    assert r.get_json()["voices"][0]["name"] == "Taylan"


def test_api_health_returns_state_and_message(app, monkeypatch):
    app.test_client().post("/settings", data={"cartesia_api_key": "k"})
    from short_bot.web.routes import cartesia_api
    monkeypatch.setattr(cartesia_api, "health_check", lambda **kw: "model")
    r = app.test_client().post("/api/cartesia/health", data={"voice_id": "v", "model": "sonic-9"})
    j = r.get_json()
    assert j["state"] == "model" and j["ok"] is False and "model" in j["message"].lower()


def test_api_probe_models(app, monkeypatch):
    app.test_client().post("/settings", data={"cartesia_api_key": "k"})
    from short_bot.web.routes import cartesia_api
    monkeypatch.setattr(cartesia_api, "probe_models",
                        lambda **kw: [{"id": "sonic-3.5", "ok": True, "reason": ""}])
    r = app.test_client().post("/api/cartesia/models/probe")
    assert r.get_json()["models"][0]["ok"] is True
    assert r.get_json()["credits"] == 2 * len(cartesia_api.KNOWN_MODELS)


def test_api_clone_uploads_file(app, monkeypatch):
    import io
    app.test_client().post("/settings", data={"cartesia_api_key": "k"})
    from short_bot.web.routes import cartesia_api
    seen = {}

    def _fake(**kw):
        seen.update(kw)
        return "new-id", True
    monkeypatch.setattr(cartesia_api, "clone_voice", _fake)
    r = app.test_client().post("/api/cartesia/clone",
                               data={"name": "Ben", "language": "tr",
                                     "clip": (io.BytesIO(b"RIFF" + b"\0" * 4096), "ref.wav")},
                               content_type="multipart/form-data")
    j = r.get_json()
    assert j["voice_id"] == "new-id" and j["trimmed"] is True
    assert seen["name"] == "Ben" and seen["language"] == "tr"
    assert str(seen["clip_path"]).endswith(".wav")


# --- ses kartı --------------------------------------------------------------------

def test_edit_page_has_provider_and_cartesia_controls(app):
    body = app.test_client().get("/channels/demo/edit").data.decode("utf-8")
    for needle in ('name="voice_provider"', 'value="cartesia"', 'name="voice_model"',
                   'name="voice_volume"', 'name="voice_emotion"', 'id="btn-cartesia-voices"',
                   'id="btn-cartesia-health"', 'id="btn-cartesia-probe"', 'id="cartesia-clone-file"'):
        assert needle in body, needle


def test_edit_post_saves_cartesia_voice_fields(app, tmp_path):
    form = {"schedule_cron": "0 * * * *", "duration_s": "6", "min_score": "6.0",
            "max_candidates_per_run": "5", "handle": "@demo", "enabled": "1",
            "voice_enabled": "on", "voice_provider": "cartesia", "voice_id": "c1cf",
            "voice_speed": "1.05", "voice_model": "sonic-preview", "voice_volume": "1.3",
            "voice_emotion": "[sakin]", "voice_persona": "p", "voice_target_min": "35",
            "voice_target_max": "50", "voice_music_volume": "0.05"}
    r = app.test_client().post("/channels/demo/edit", data=form)
    assert r.status_code in (200, 302)
    v = yaml.safe_load((tmp_path / "config" / "channels" / "demo.yaml").read_text(encoding="utf-8"))["voice"]
    assert v["provider"] == "cartesia" and v["model"] == "sonic-preview"
    assert v["volume"] == 1.3 and v["emotion"] == "[sakin]" and v["voice_id"] == "c1cf"


def test_edit_post_rejects_cartesia_speed_below_floor(app, tmp_path):
    form = {"schedule_cron": "0 * * * *", "duration_s": "6", "min_score": "6.0",
            "max_candidates_per_run": "5", "handle": "@demo", "enabled": "1",
            "voice_enabled": "on", "voice_provider": "cartesia", "voice_id": "c1cf",
            "voice_speed": "0.5"}
    r = app.test_client().post("/channels/demo/edit", data=form, follow_redirects=True)
    assert r.status_code == 200
    raw = yaml.safe_load((tmp_path / "config" / "channels" / "demo.yaml").read_text(encoding="utf-8"))
    assert "voice" not in raw
