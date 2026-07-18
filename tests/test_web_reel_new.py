"""Niş bulucu route'ları (/channels/new-reel/find-niches, /niche-status).

NOT: Eski reel kanal-oluşturma SİHİRBAZI (GET/POST /channels/new-reel) kullanıcının
açık talebiyle KALDIRILDI (commit da87a24: 'eski reel stilini sil, Kürate koy; Ajan'ı da
kaldır') → artık /channels/new-curated'a 302 yönlendiriyor. O sihirbazın + liste
butonu/rozetinin testleri buradan çıkarıldı (yeni akış test_web_curated.py'de). Bu dosyada
YALNIZ hâlâ kayıtlı/çalışan niş-bulucu route'larının testleri kaldı.
"""
import re
from unittest.mock import patch

from short_bot.web import create_app


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


def test_niche_find_ai_mode_uses_find_niches_ai(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.threading.Thread", _SyncThread), \
         patch("short_bot.web.routes.reel_new.find_niches_ai",
               return_value=_NICHE_SAMPLE) as ai_mock, \
         patch("short_bot.web.routes.reel_new.find_niches_data") as data_mock:
        r1 = c.post("/channels/new-reel/find-niches",
                    data={"topic": "bilim", "mode": "ai", "language": "de"})
        job_id = re.search(r"niche-status/([0-9a-f]+)", r1.data.decode("utf-8")).group(1)
        r2 = c.get(f"/channels/new-reel/niche-status/{job_id}")
    assert ai_mock.called
    assert not data_mock.called
    assert ai_mock.call_args.kwargs.get("language") == "de"
    assert "İnsan Vücudu" in r2.data.decode("utf-8")


def test_niche_find_start_returns_running(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.threading.Thread", _SyncThread), \
         patch("short_bot.web.routes.reel_new.find_niches_data", return_value=_NICHE_SAMPLE):
        r = c.post("/channels/new-reel/find-niches", data={"topic": "bilim gerçekleri"})
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "aranıyor" in body
    assert "/channels/new-reel/niche-status/" in body


def test_niche_status_done_renders_cards(tmp_path):
    c = _client(tmp_path)
    with patch("short_bot.web.routes.reel_new.threading.Thread", _SyncThread), \
         patch("short_bot.web.routes.reel_new.find_niches_data", return_value=_NICHE_SAMPLE):
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
         patch("short_bot.web.routes.reel_new.find_niches_data",
               side_effect=RuntimeError("claude CLI bulunamadı: claude")):
        r1 = c.post("/channels/new-reel/find-niches", data={"topic": "x"})
        job_id = re.search(r"niche-status/([0-9a-f]+)", r1.data.decode("utf-8")).group(1)
        r2 = c.get(f"/channels/new-reel/niche-status/{job_id}")
    body = r2.data.decode("utf-8")
    assert "Niş bulunamadı" in body
    assert "claude CLI bulunamadı" in body
