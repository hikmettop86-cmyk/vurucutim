"""Takılı koşuyu arayüzden iptal edebilmek.

GERÇEK DURUM: süreci ölen bir koşu (çökme, kapatma, zaman aşımı) veritabanında
SONSUZA DEK "çalışıyor" kalır — kendini temizleyecek kimse yoktur. Kullanıcının
koşusu 50 dakika kuyrukta göründü.

İptal rotası VARDI ama yalnız KLASİK kanal düzenleme sayfasında görünüyordu. Reel
kanalları o sayfaya hiç uğramaz (/edit-reel'e yönlenirler), dolayısıyla takılı
koşuyu temizlemenin arayüzde HİÇBİR yolu yoktu.
"""
from datetime import datetime, timedelta

import pytest

from short_bot.db import init_db, start_run
from short_bot.web import create_app
from short_bot.web.routes.activity import STALE_RUN_AFTER_S

_CH = """slug: balinalar
name: Balina Dünyası
keywords: [balina]
language: tr
schedule_cron: "0 10 * * *"
duration_s: 40
min_score: 7.0
max_candidates_per_run: 3
max_age_hours: 24
template: stat-hero
colors: {primary: '#0a2540', accent: '#2de2e6', bg_gradient: ['#0A2540', '#04121F']}
handle: '@balina'
output_dir: output/balinalar
enabled: false
content_source: generator
generator: {topic: 'balinalar hakkında ilginç bilgiler'}
"""


@pytest.fixture
def app(tmp_path):
    cfg = tmp_path / "config"; (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\n", encoding="utf-8")
    (cfg / "channels" / "balinalar.yaml").write_text(_CH, encoding="utf-8")
    db = tmp_path / "db.sqlite"
    eng = init_db(db)
    a = create_app(config_dir=cfg, db_path=db, templates_dir=tmp_path / "t",
                   music_root=tmp_path, cache_dir=tmp_path, lock_dir=tmp_path,
                   logs_dir=tmp_path, output_root=tmp_path,
                   secrets_path=tmp_path / "secrets.yaml", scheduler=False)
    # Koşu, panel AÇILDIKTAN SONRA başlar — üretimde de böyle olur.
    #
    # Sıra önemli: açılış temizliği (cleanup_zombie_runs) artık 'running' bir satırın
    # KİLİDİNE bakıyor. Kilidi serbestse sahibi ölmüştür ve satır 'failed' işaretlenir.
    # Koşuyu create_app'ten ÖNCE açsaydık, açılış onu haklı olarak zombi sayardı ve
    # iptal edilecek bir şey kalmazdı. İptal düğmesi, panel CANLIYKEN asılı kalan
    # koşular için var — kilidi tutuluyor, süreç yaşıyor, üretim ilerlemiyor.
    start_run(eng, "balinalar", trigger="cli", log_path="x.log")
    return a


def test_calisan_kosu_iptal_edilebilir(app):
    from short_bot.web.models import Run
    c = app.test_client()
    resp = c.post("/runs/1/cancel")
    assert resp.status_code in (200, 302)
    with app.app_context():
        r = Run.query.filter_by(id=1).first()
        assert r.status == "cancelled"
        assert r.ended_at is not None, "iptal edilen koşu bitiş zamanı almalı"


def test_iptal_edilmis_kosu_tekrar_iptal_edilemez(app):
    from short_bot.web.models import Run
    c = app.test_client()
    c.post("/runs/1/cancel")
    c.post("/runs/1/cancel")
    with app.app_context():
        assert Run.query.filter_by(id=1).first().status == "cancelled"


def test_olmayan_kosu_404(app):
    assert app.test_client().post("/runs/999/cancel").status_code == 404


def test_canli_kosu_panelinde_iptal_dugmesi_var(app):
    """Düğme ARAYÜZDE olmalı — rota tek başına işe yaramıyordu."""
    body = app.test_client().get("/activity").data.decode("utf-8")
    assert "/runs/1/cancel" in body, "canlı koşu panelinde iptal düğmesi yok"


def test_htmx_partial_da_iptal_dugmesi_var(app):
    # Panel 3 saniyede bir kendini tazeliyor; düğme tazelemeden sonra da durmalı.
    body = app.test_client().get("/activity/live-runs").data.decode("utf-8")
    assert "/runs/1/cancel" in body


def test_takilmis_kosu_isaretleniyor(app):
    body = app.test_client().get("/activity/live-runs").data.decode("utf-8")
    assert "takılmış olabilir" in body
    assert str(STALE_RUN_AFTER_S) in body, "eşik şablona geçmeli"


def test_esik_makul():
    # Normal üretim 8-14 dk (ölçüldü). Eşik bunun üstünde ama makul olmalı.
    assert 15 * 60 <= STALE_RUN_AFTER_S <= 45 * 60
