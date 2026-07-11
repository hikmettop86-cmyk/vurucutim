import re
from unittest.mock import patch

from short_bot.web import create_app
from short_bot.dna import DnaPalette, DnaFonts, DnaTone, DnaSpec


class _SyncThread:
    """threading.Thread yerine: target'ı start()'ta senkron çalıştırır (deterministik test)."""
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        if self._t:
            self._t(*self._a, **self._k)


_NICHE_SAMPLE = [
    {"nis": "İnsan Vücudu", "neden": "Stay Education outlier 31.",
     "konu_tohumu": "Nefesini 60 saniye tutunca ne olur?"},
    {"nis": "Savaş Tarihi", "neden": "The Art Of War 1.6M abone.",
     "konu_tohumu": "Bu tankın gizli kusuru neydi?"},
]


def _client(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text("""\
ffmpeg_path: ffmpeg
claude_cli_path: claude
playwright_browser: chromium
web: {host: 127.0.0.1, port: 5005}
fuzzy_dedup_threshold: 0.85
log_level: INFO
claude_models: {dna: opus, default: haiku}
""", encoding="utf-8")
    app = create_app(config_dir=cfg_dir, db_path=tmp_path / "db.sqlite",
                     templates_dir=tmp_path / "templates",
                     music_root=tmp_path, cache_dir=tmp_path,
                     lock_dir=tmp_path, logs_dir=tmp_path,
                     output_root=tmp_path, scheduler=False)
    return app.test_client()


def _fake_dna():
    return DnaSpec(
        archetype="stat-hero",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(),
        tone=DnaTone(voice="x", style="y"),
        persona_summary="x",
    )


def test_reel_wizard_get_renders_key_fields(tmp_path):
    c = _client(tmp_path)
    r = c.get("/channels/new-reel")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert 'action="/channels/new-reel"' in body
    assert 'name="topic"' in body
    assert 'name="voice_id"' in body
    assert 'name="name"' in body
    assert 'name="variation_on"' in body
    assert 'name="cta_enabled"' in body
    assert 'name="produce_now"' in body
    # niş çipleri
    assert "Hayvanlar" in body
    assert "Uzay" in body


def test_reel_post_writes_channel_yaml(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        r = c.post("/channels/new-reel", data={
            "name": "Evrenin Sırları", "language": "tr",
            "topic": "uzay, gezegenler ve kara delikler hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
            "highlight_color": "#38bdf8",
            "cut_pacing": "auto", "music_mood": "upbeat",
            "variation_on": "on", "cta_enabled": "on",
            "comment_question": "on",
            "produce_now": "0",
        })
    assert r.status_code in (200, 302)
    yaml_path = tmp_path / "config" / "channels" / "evrenin-sirlari.yaml"
    assert yaml_path.exists()
    contents = yaml_path.read_text(encoding="utf-8")
    assert "content_source: generator" in contents
    assert "generator:" in contents
    assert "kara delikler" in contents
    assert "reel:" in contents
    assert "enabled: true" in contents
    assert "Q2IX97JeHBY3vNGzgM5s" in contents
    assert "#38bdf8" in contents


def test_reel_post_variation_off_sets_vary_false(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        c.post("/channels/new-reel", data={
            "name": "Sakin Kanal", "language": "tr",
            "topic": "doğa ve vahşi yaşam hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
            "highlight_color": "#38bdf8",
            # variation_on / cta_enabled / comment_question GÖNDERİLMEDİ → kapalı
            "produce_now": "0",
        })
    from short_bot.config import load_channel
    cfg = load_channel(tmp_path / "config" / "channels" / "sakin-kanal.yaml")
    assert cfg.reel.hook_angle_vary is False
    assert cfg.reel.accent_vary is False
    assert cfg.reel.transition_vary is False
    assert cfg.reel.cta_enabled is False
    assert cfg.reel.comment_question is False


def test_reel_post_empty_voice_no_channel(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        r = c.post("/channels/new-reel", data={
            "name": "Sessiz Kanal", "language": "tr",
            "topic": "uzay ve gezegenler hakkında ilginç bilgiler",
            "voice_id": "",
        })
    assert r.status_code in (200, 302)
    assert not (tmp_path / "config" / "channels" / "sessiz-kanal.yaml").exists()


def test_reel_post_short_topic_no_channel(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        r = c.post("/channels/new-reel", data={
            "name": "Kisa Konu", "language": "tr",
            "topic": "uzay",  # < 10 karakter
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
        })
    assert r.status_code in (200, 302)
    assert not (tmp_path / "config" / "channels" / "kisa-konu.yaml").exists()


def test_reel_post_slug_collision_gets_suffix(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        data = {
            "name": "Balina Dünyası", "language": "tr",
            "topic": "balinalar ve deniz memelileri hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
            "highlight_color": "#38bdf8",
        }
        c.post("/channels/new-reel", data=dict(data))
        c.post("/channels/new-reel", data=dict(data))
    ch = tmp_path / "config" / "channels"
    assert (ch / "balina-dunyasi.yaml").exists()
    assert (ch / "balina-dunyasi-2.yaml").exists()


def test_reel_post_produce_now_launches_pipeline(tmp_path):
    c = _client(tmp_path)
    calls = []
    def _fake_launch(**kwargs):
        calls.append(kwargs)
        return None
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()), \
         patch("short_bot.web.routes.reel_new.launch_pipeline", _fake_launch):
        c.post("/channels/new-reel", data={
            "name": "Hemen Üret", "language": "tr",
            "topic": "bilim ve doğa hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
            "highlight_color": "#38bdf8",
            "produce_now": "1",
        })
    assert len(calls) == 1
    assert calls[0]["channel"].slug == "hemen-uret"
    assert calls[0]["trigger"] == "manual"


def test_reel_post_no_produce_now_does_not_launch(tmp_path):
    c = _client(tmp_path)
    calls = []
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()), \
         patch("short_bot.web.routes.reel_new.launch_pipeline",
               lambda **k: calls.append(k)):
        c.post("/channels/new-reel", data={
            "name": "Sonra Üret", "language": "tr",
            "topic": "tarih hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
            "highlight_color": "#38bdf8",
            "produce_now": "0",
        })
    assert calls == []


def test_channel_list_has_reel_button(tmp_path):
    c = _client(tmp_path)
    r = c.get("/channels")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "/channels/new-reel" in body
    assert "Reel" in body


def test_channel_list_shows_reel_badge(tmp_path):
    c = _client(tmp_path)
    # önce reel kanalı oluştur
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        c.post("/channels/new-reel", data={
            "name": "Reel Kanal", "language": "tr",
            "topic": "uzay ve gezegenler hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
            "highlight_color": "#38bdf8",
        })
    r = c.get("/channels")
    body = r.data.decode("utf-8")
    assert "🎬" in body


def test_reel_channel_card_is_distinct(tmp_path):
    """Reel kanalı, standart karttan görsel/işlevsel olarak ayrık render edilmeli:
    kart rozeti '🎬 REEL', reel'e özgü çipler (süre + abone kartı), satırda 'Reel'."""
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.generate_dna", return_value=_fake_dna()):
        c.post("/channels/new-reel", data={
            "name": "Ayrik Reel", "language": "tr",
            "topic": "uzay ve gezegenler hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s", "highlight_color": "#38bdf8",
            "cta_enabled": "on",
        })
    body = c.get("/channels").data.decode("utf-8")
    assert "🎬 REEL" in body          # ayrık kart rozeti (kart görünümü)
    assert "🎬 Reel" in body          # satır göstergesi (tablo görünümü)
    assert "abone kartı" in body      # reel'e özgü özellik çipi
    assert "25-45sn" in body          # reel süre çipi (standart kartta yok)
    assert "#38bdf8" in body          # marka rengi kenarlık/şerit


def test_reel_post_invalid_pacing_fails_before_dna(tmp_path):
    """Geçersiz Literal (cut_pacing) ücretli DNA çağrısından ÖNCE hata vermeli:
    kanal yazılmaz VE generate_dna hiç çağrılmaz (kredi harcanmaz)."""
    c = _client(tmp_path)
    dna_calls = []

    def _rec(**kwargs):
        dna_calls.append(kwargs)
        return _fake_dna()

    with patch("short_bot.web.routes.reel_new.generate_dna", _rec):
        r = c.post("/channels/new-reel", data={
            "name": "Bozuk Tempo", "language": "tr",
            "topic": "uzay ve gezegenler hakkında ilginç bilgiler",
            "voice_id": "Q2IX97JeHBY3vNGzgM5s",
            "cut_pacing": "xyz",  # ReelConfig Literal dışı
        })
    assert r.status_code in (200, 302)
    assert not (tmp_path / "config" / "channels" / "bozuk-tempo.yaml").exists()
    assert dna_calls == []


def test_reel_wizard_chip_click_uses_key_only(tmp_path):
    """Regression: niş çip @click'i topic'i tojson ile GEÇMEMELİ — çift tırnak
    HTML niteliğini erken kapatıp tıklamayı bozuyordu. Sadece key geçilir; topic
    ayrı bir JSON data island'dan okunur."""
    c = _client(tmp_path)
    body = c.get("/channels/new-reel").data.decode("utf-8")
    # Tek argümanlı, güvenli çağrı:
    assert "pick('hayvanlar')" in body
    # Kırık iki-argümanlı biçim OLMAMALI:
    assert "pick('hayvanlar', " not in body
    # Topic verisi ayrı JSON island'da:
    assert 'id="niche-data"' in body
    assert "okyanus devleri" in body


def test_niche_wizard_has_both_finders_and_langs(tmp_path):
    c = _client(tmp_path)
    body = c.get("/channels/new-reel").data.decode("utf-8")
    assert "NexLev Niş Bulucu" in body
    assert "AI Niş Bulucu" in body
    assert 'hx-post="/channels/new-reel/find-niches"' in body
    assert 'id="niche-results"' in body
    assert "reelPickNiche" in body
    # çok dilli dropdown
    for code in ('value="de"', 'value="es"', 'value="fr"'):
        assert code in body


def test_niche_find_ai_mode_uses_find_niches_ai(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.threading.Thread", _SyncThread), \
         patch("short_bot.web.routes.reel_new.find_niches_ai",
               return_value=_NICHE_SAMPLE) as ai_mock, \
         patch("short_bot.web.routes.reel_new.find_niches") as nex_mock:
        r1 = c.post("/channels/new-reel/find-niches",
                    data={"topic": "bilim", "mode": "ai", "language": "de"})
        job_id = re.search(r"niche-status/([0-9a-f]+)", r1.data.decode("utf-8")).group(1)
        r2 = c.get(f"/channels/new-reel/niche-status/{job_id}")
    assert ai_mock.called
    assert not nex_mock.called
    assert ai_mock.call_args.kwargs.get("language") == "de"
    assert "İnsan Vücudu" in r2.data.decode("utf-8")


def test_niche_find_start_returns_running(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.threading.Thread", _SyncThread), \
         patch("short_bot.web.routes.reel_new.find_niches", return_value=_NICHE_SAMPLE):
        r = c.post("/channels/new-reel/find-niches", data={"topic": "bilim gerçekleri"})
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "aranıyor" in body
    assert "/channels/new-reel/niche-status/" in body


def test_niche_status_done_renders_cards(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.threading.Thread", _SyncThread), \
         patch("short_bot.web.routes.reel_new.find_niches", return_value=_NICHE_SAMPLE):
        r1 = c.post("/channels/new-reel/find-niches", data={"topic": "bilim"})
        job_id = re.search(r"niche-status/([0-9a-f]+)", r1.data.decode("utf-8")).group(1)
        r2 = c.get(f"/channels/new-reel/niche-status/{job_id}")
    body = r2.data.decode("utf-8")
    assert "İnsan Vücudu" in body
    assert "Nefesini 60 saniye" in body
    assert "reelPickNiche" in body


def test_niche_status_unknown_job_shows_error(tmp_path):
    c = _client(tmp_path)
    r = c.get("/channels/new-reel/niche-status/deadbeef00")
    assert r.status_code == 200
    assert "bulunamadı" in r.data.decode("utf-8")


def test_niche_find_error_surfaces_to_user(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.threading.Thread", _SyncThread), \
         patch("short_bot.web.routes.reel_new.find_niches",
               side_effect=RuntimeError("claude CLI bulunamadı: claude")):
        r1 = c.post("/channels/new-reel/find-niches", data={"topic": "x"})
        job_id = re.search(r"niche-status/([0-9a-f]+)", r1.data.decode("utf-8")).group(1)
        r2 = c.get(f"/channels/new-reel/niche-status/{job_id}")
    body = r2.data.decode("utf-8")
    assert "Niş bulunamadı" in body
    assert "claude CLI bulunamadı" in body
