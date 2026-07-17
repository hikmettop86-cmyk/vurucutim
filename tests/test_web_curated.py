"""SP2: Kürate-klip onay UI (keşif ızgarası + arka-plan iş/poll)."""
import re
import time

import pytest


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


def test_curated_produce_flashes_and_redirects(tmp_path):
    c, cfg_dir = _client(tmp_path)
    _make_curated_channel(cfg_dir)
    r = c.post("/curated/produce", data={
        "channel_slug": "cevherkanal", "title": "Zıplayan örümcek",
        "video_url": "https://v.redd.it/abc/DASH_1080.mp4"})
    assert r.status_code == 302
    assert "/curated" in r.headers["Location"]
