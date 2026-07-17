"""SP2: Kürate-klip onay UI (keşif ızgarası + arka-plan iş/poll)."""
import re
import time

import pytest


@pytest.fixture(autouse=True)
def _clear_curated_cache():
    # _last_search modül-globali → testler arası sızmasın (cache özelliği eklendi).
    from short_bot.web.routes import curated
    with curated._last_lock:
        curated._last_search.clear()
    yield
    with curated._last_lock:
        curated._last_search.clear()


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
    from short_bot.web import create_app
    app = create_app(config_dir=cfg_dir, db_path=tmp_path / "db.sqlite",
                     templates_dir=tmp_path / "templates",
                     music_root=tmp_path, cache_dir=tmp_path,
                     lock_dir=tmp_path, logs_dir=tmp_path,
                     output_root=tmp_path, scheduler=False)
    return app.test_client(), cfg_dir


def _make_curated_channel(cfg_dir, slug="cevherkanal"):
    from short_bot.config import ChannelConfig, ReelConfig, save_channel
    cfg = ChannelConfig(
        slug=slug, name="Cevher Kanal", keywords=[], rss_locale="",
        schedule_cron="0 9 * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=3, template="stat-hero",
        colors={"primary": "#000", "accent": "#fff", "bg_gradient": ["#000", "#111"]},
        handle="@cevher", output_dir=f"output/{slug}", enabled=True, language="tr",
        dna=None, content_source="curated",
        reel=ReelConfig(enabled=True, voice_id="v1",
                        subreddits=["likeus"], curated_min_ups=300))
    save_channel(cfg_dir / "channels" / f"{slug}.yaml", cfg)


_GEM = {
    "sub": "likeus", "ups": 124000, "comments": 812,
    "title": "Zıplayan örümcek denim ceketin üstünde",
    "duration": 24, "width": 1080, "height": 1920, "orient": "DİKEY",
    "video_url": "https://v.redd.it/abc/DASH_1080.mp4",
    "thumb": "https://preview.redd.it/abc.jpg",
    "permalink": "https://www.reddit.com/r/likeus/comments/abc/",
    "over18": False,
}


def test_curated_index_renders(tmp_path):
    c, cfg_dir = _client(tmp_path)
    _make_curated_channel(cfg_dir)
    r = c.get("/curated")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "Cevher Bul" in body
    assert "Cevher Kanal" in body                 # kanal seçicide
    assert 'name="channel_slug"' in body


def test_curated_index_nav_link_present(tmp_path):
    c, cfg_dir = _client(tmp_path)
    _make_curated_channel(cfg_dir)
    body = c.get("/curated").data.decode("utf-8")
    assert 'href="/curated"' in body              # nav linki


def test_curated_fetch_no_creds_shows_error(tmp_path, monkeypatch):
    # Kimlik yoksa Reddit kimliği yok → kullanıcıya hata gösterilir (üretim düşmez).
    # (Gerçek data/secrets.yaml'da kimlik olabilir → deterministik olsun diye boşla.)
    c, cfg_dir = _client(tmp_path)
    _make_curated_channel(cfg_dir)
    monkeypatch.setattr("short_bot.web.routes.curated._secrets", lambda: {})
    r = c.post("/curated/fetch", data={"channel_slug": "cevherkanal", "t": "week"})
    body = r.data.decode("utf-8")
    assert "Reddit API kimliği yok" in body


def test_curated_fetch_lists_gems(tmp_path, monkeypatch):
    c, cfg_dir = _client(tmp_path)
    _make_curated_channel(cfg_dir)
    # kimlik + find_gems mock (ağ yok)
    monkeypatch.setattr("short_bot.web.routes.curated._secrets",
                        lambda: {"reddit_client_id": "x", "reddit_client_secret": "y"})
    captured = {}

    def fake_find_gems(cid, csec, *, subreddits, t, min_ups, max_duration, **kw):
        captured.update(subreddits=subreddits, t=t, min_ups=min_ups,
                        max_duration=max_duration)
        return [_GEM]
    monkeypatch.setattr("short_bot.reddit_gems.find_gems", fake_find_gems)

    r = c.post("/curated/fetch", data={"channel_slug": "cevherkanal", "t": "month"})
    body = r.data.decode("utf-8")
    m = re.search(r"/curated/status/([0-9a-f]+)", body)
    assert m, "poll job_id render edilmedi"
    job_id = m.group(1)
    # arka-plan iş bitene kadar poll (mock hızlı)
    done = ""
    for _ in range(60):
        done = c.get(f"/curated/status/{job_id}").data.decode("utf-8")
        if "Zıplayan örümcek" in done:
            break
        time.sleep(0.05)
    assert "Zıplayan örümcek" in done              # cevher ızgarada
    assert "124,000" in done                       # upvote formatlı
    assert "DİKEY" in done                         # yön rozeti
    assert "Bu klibi üret" in done                 # seç butonu
    # kanal ayarları işe geçti (subreddit listesi + curated_min_ups + form t)
    assert captured["subreddits"] == ["likeus"]
    assert captured["t"] == "month"
    assert captured["min_ups"] == 300


def test_curated_produce_requires_selection(tmp_path):
    c, cfg_dir = _client(tmp_path)
    _make_curated_channel(cfg_dir)
    r = c.post("/curated/produce", data={"channel_slug": "", "video_url": ""})
    assert "Kanal ya da klip seçili değil" in r.data.decode("utf-8")


def test_curated_produce_launches_pipeline(tmp_path, monkeypatch):
    c, cfg_dir = _client(tmp_path)
    _make_curated_channel(cfg_dir)
    # produce artık run_pipeline üzerinden (Akış'ta görünsün) → launch_pipeline'ı mock'la.
    captured = {}
    monkeypatch.setattr("short_bot.web.routes.curated.launch_pipeline",
                        lambda **k: captured.update(k))
    r = c.post("/curated/produce", data={
        "channel_slug": "cevherkanal", "video_url": "https://v.redd.it/x/DASH.mp4",
        "title": "Test klip", "permalink": "https://www.reddit.com/x"})
    body = r.data.decode("utf-8")
    assert "üretimi başladı" in body and "Akış" in body     # Akış'a yönlendirir
    assert captured["curated_gem"]["video_url"] == "https://v.redd.it/x/DASH.mp4"
    assert captured["trigger"] == "manual_curated"


def test_curated_fetch_uses_category_subreddits(tmp_path, monkeypatch):
    c, cfg_dir = _client(tmp_path)
    _make_curated_channel(cfg_dir)
    monkeypatch.setattr("short_bot.web.routes.curated._secrets",
                        lambda: {"reddit_client_id": "x", "reddit_client_secret": "y"})
    captured = {}
    monkeypatch.setattr("short_bot.reddit_gems.find_gems",
                        lambda cid, csec, *, subreddits, **k: captured.update(
                            subreddits=subreddits) or [])
    from short_bot.web.routes.curated import CATEGORIES
    c.post("/curated/fetch", data={"channel_slug": "cevherkanal",
                                   "category": "Hayvanlar", "t": "week"})
    # kategori subreddit'leri kanal ayarını (['likeus']) EZDİ
    assert captured["subreddits"] == CATEGORIES["Hayvanlar"]


def test_decorate_sorts_vertical_first_and_marks_produced(tmp_path):
    from short_bot.web.routes.curated import _decorate
    gems = [
        {"permalink": "p1", "ups": 1000, "orient": "yatay", "duration": 20},
        {"permalink": "p2", "ups": 900, "orient": "DİKEY", "duration": 20},
    ]
    out = _decorate(gems, tmp_path / "nodb.sqlite")   # boş DB → hiçbiri üretilmemiş
    assert out[0]["permalink"] == "p2"                # dikey öne (skor ×2.5)
    assert all(not g["produced"] for g in out)


def test_decorate_marks_produced_by_video_id(tmp_path):
    # Aynı klibin FARKLI varyantı/permalinki bile 'üretildi' işaretlenmeli (video-ID dedup).
    import json
    from short_bot.db import init_db, record_short
    from short_bot.web.routes.curated import _decorate, _clip_key
    assert _clip_key("https://v.redd.it/xyz789/CMAF_1080.mp4?a=1") == "vreddit:xyz789"
    dbp = tmp_path / "db.sqlite"
    eng = init_db(dbp)
    record_short(eng, channel="c", rss_item_guid=None, title="t", file_path="x.mp4",
                 duration_s=10, render_ms=0,
                 script_json=json.dumps({"source_video_url":
                                         "https://v.redd.it/xyz789/DASH_720.mp4"}))
    gems = [{"permalink": "baska", "video_url": "https://v.redd.it/xyz789/CMAF_1080.mp4?a=1",
             "ups": 500, "orient": "DİKEY", "duration": 15}]
    out = _decorate(gems, dbp)
    assert out[0]["produced"] is True      # video-ID (vreddit:xyz789) eşleşti


def test_curated_cache_persists_last_search(tmp_path, monkeypatch):
    # Sekme değişip geri gelince (yeni GET /curated) son arama cache'ten gelmeli.
    c, cfg_dir = _client(tmp_path)
    _make_curated_channel(cfg_dir)
    monkeypatch.setattr("short_bot.web.routes.curated._secrets",
                        lambda: {"reddit_client_id": "x", "reddit_client_secret": "y"})
    monkeypatch.setattr("short_bot.reddit_gems.find_gems", lambda *a, **k: [_GEM])
    r = c.post("/curated/fetch", data={"channel_slug": "cevherkanal", "t": "week"})
    job_id = re.search(r"/curated/status/([0-9a-f]+)", r.data.decode()).group(1)
    for _ in range(60):
        if "Zıplayan örümcek" in c.get(f"/curated/status/{job_id}").data.decode():
            break
        time.sleep(0.05)
    idx = c.get("/curated").data.decode("utf-8")   # yeni sekme / geri dönüş
    assert "Zıplayan örümcek" in idx               # cache'ten geldi (kaybolmadı)


def test_ajan_removed(tmp_path):
    c, cfg_dir = _client(tmp_path)
    body = c.get("/channels").data.decode("utf-8")
    assert ">Ajan<" not in body                  # nav'dan kalktı
    assert c.get("/channels/agent").status_code == 404   # route yok


def test_new_curated_form_renders(tmp_path):
    c, cfg_dir = _client(tmp_path)
    body = c.get("/channels/new-curated").data.decode("utf-8")
    assert "Kürate Kanal Oluştur" in body
    assert 'name="voice_id"' in body and 'name="persona"' in body


def test_old_reel_wizard_redirects_to_curated(tmp_path):
    c, cfg_dir = _client(tmp_path)
    r = c.get("/channels/new-reel")
    assert r.status_code == 302 and "/channels/new-curated" in r.headers["Location"]


def test_new_curated_creates_channel(tmp_path, monkeypatch):
    _fake_pack = lambda lang: object()          # noqa: E731
    _fake_pack.cache_clear = lambda: None        # create_app'in set_user_dir'ı çağırır
    monkeypatch.setattr("short_bot.lang_pack.load_pack", _fake_pack)
    c, cfg_dir = _client(tmp_path)
    r = c.post("/channels/new-curated", data={
        "name": "Test Kürate", "voice_id": "V1", "language": "tr",
        "persona": "", "category": "Hayvanlar"})
    assert r.status_code == 302
    from short_bot.config import load_channel
    p = cfg_dir / "channels" / "test-kurate.yaml"
    assert p.exists()
    ch = load_channel(p)
    assert ch.content_source == "curated"
    assert ch.reel.enabled and ch.reel.voice_id == "V1"
    assert "AnimalsBeingJerks" in ch.reel.subreddits   # kategori subreddit'leri geçti
    assert ch.dna is None                              # kürate DNA gerektirmez


def test_curated_channel_uses_clean_edit(tmp_path, monkeypatch):
    # Kürate kanalı eski konu/seri/niş baggage'lı edit_reel yerine TEMİZ kürate edit'e gider.
    _fake_pack = lambda lang: object()          # noqa: E731
    _fake_pack.cache_clear = lambda: None
    monkeypatch.setattr("short_bot.lang_pack.load_pack", _fake_pack)
    c, cfg_dir = _client(tmp_path)
    c.post("/channels/new-curated", data={
        "name": "Kedi Nis", "voice_id": "V1", "category": "Hayvanlar"})
    r = c.get("/channels/kedi-nis/edit-reel")
    assert r.status_code == 302 and "/edit-curated" in r.headers["Location"]
    body = c.get("/channels/kedi-nis/edit-curated").data.decode("utf-8")
    assert "Kürate kanal" in body and 'name="voice_id"' in body
    assert "Niş Bulucu" not in body                # eski niş-bulucu baggage YOK
    assert 'name="generator_topic"' not in body    # eski konu baggage YOK


def test_edit_curated_save_updates(tmp_path, monkeypatch):
    _fake_pack = lambda lang: object()          # noqa: E731
    _fake_pack.cache_clear = lambda: None
    monkeypatch.setattr("short_bot.lang_pack.load_pack", _fake_pack)
    c, cfg_dir = _client(tmp_path)
    c.post("/channels/new-curated", data={
        "name": "Kedi Nis", "voice_id": "V1", "category": "Hayvanlar"})
    from short_bot.config import load_channel
    r = c.post("/channels/kedi-nis/edit-curated", data={
        "name": "Kedi Nis 2", "voice_id": "V2", "persona": "vahsi_mizah",
        "subreddits": "likeus, funnycats", "curated_time": "month",
        "curated_min_ups": "800", "enabled": "on"})
    assert r.status_code == 302
    ch = load_channel(cfg_dir / "channels" / "kedi-nis.yaml")
    assert ch.name == "Kedi Nis 2" and ch.reel.voice_id == "V2"
    assert ch.reel.persona == "vahsi_mizah"
    assert ch.reel.subreddits == ["likeus", "funnycats"]
    assert ch.reel.curated_time == "month" and ch.reel.curated_min_ups == 800
    assert ch.content_source == "curated"          # korundu
