"""Autopilot cron'ları KAYITLI mı?

Kayıtlı değilse hiçbir şey olmaz — ve bu SESSİZDİR: panelde slotlar "planlandı"
görünür, ama kimse üretmez. Kullanıcı günlerce bekler.
"""
import pytest

from short_bot.db import init_db, slots_in_range
from short_bot.web import create_app

_CH = """slug: k
name: Kanal
keywords: [x]
language: tr
schedule_cron: "0 10 * * *"
duration_s: 40
min_score: 7.0
max_candidates_per_run: 3
max_age_hours: 24
template: stat-hero
colors: {primary: '#000000', accent: '#ffffff', bg_gradient: ['#000000', '#111111']}
handle: '@k'
output_dir: output/k
enabled: true
content_source: generator
generator: {topic: 'ilginc bilgiler burada'}
autopilot:
  enabled: true
  daily_count: 2
"""

_KAPALI = _CH.replace("autopilot:\n  enabled: true", "autopilot:\n  enabled: false")


def _app(tmp_path, yaml_text=_CH):
    cfg = tmp_path / "config"
    (cfg / "channels").mkdir(parents=True, exist_ok=True)   # ikinci açılış için
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8")
    (cfg / "channels" / "k.yaml").write_text(yaml_text, encoding="utf-8")
    return create_app(config_dir=cfg, db_path=tmp_path / "db.sqlite",
                      templates_dir=tmp_path / "t", music_root=tmp_path,
                      cache_dir=tmp_path, lock_dir=tmp_path, logs_dir=tmp_path,
                      output_root=tmp_path, secrets_path=tmp_path / "s.yaml",
                      scheduler=True)


def test_autopilot_cronlari_KAYITLI(tmp_path):
    app = _app(tmp_path)
    try:
        ids = {j.id for j in app.scheduler.get_jobs()}
        assert "_autopilot_plan" in ids
        assert "_autopilot_tick" in ids
    finally:
        app.scheduler.shutdown(wait=False)


def test_autopilot_acik_kanalin_CRON_u_kayitli_DEGIL(tmp_path):
    """ÇİFTE ÜRETİM ENGELİ — scheduler seviyesinde."""
    app = _app(tmp_path)
    try:
        ids = {j.id for j in app.scheduler.get_jobs()}
        assert "k" not in ids, \
            "autopilot açıkken kanal cron'u da kayıtlı → günde 2 yerine 3 video"
    finally:
        app.scheduler.shutdown(wait=False)


def test_autopilot_KAPALI_kanalin_cronu_KAYITLI(tmp_path):
    """Geriye uyum: autopilot kullanmayan kanal aynen cron'la koşmalı."""
    app = _app(tmp_path, _KAPALI)
    try:
        ids = {j.id for j in app.scheduler.get_jobs()}
        assert "k" in ids, "normal kanal cron'u kaybolmuş → geriye uyum kırıldı"
    finally:
        app.scheduler.shutdown(wait=False)


def test_ACILISTA_slotlar_planlanir(tmp_path):
    """Gece cron'u kaçtıysa (uygulama kapalıydı) gün TAMAMEN boş geçerdi."""
    app = _app(tmp_path)
    try:
        eng = init_db(tmp_path / "db.sqlite")
        s = slots_in_range(eng, "k", "2000-01-01", "2999-12-31")
        assert len(s) >= 2, "açılışta slot planlanmadı"
        # bugün + yarın
        assert len({x["slot_local_date"] for x in s}) == 2
    finally:
        app.scheduler.shutdown(wait=False)


def test_acilista_planlama_IDEMPOTENT(tmp_path):
    """Uygulama iki kez açılırsa kopya slot OLUŞMAMALI."""
    app1 = _app(tmp_path)
    eng = init_db(tmp_path / "db.sqlite")
    once = len(slots_in_range(eng, "k", "2000-01-01", "2999-12-31"))
    app1.scheduler.shutdown(wait=False)

    app2 = _app(tmp_path)
    try:
        sonra = len(slots_in_range(eng, "k", "2000-01-01", "2999-12-31"))
        assert sonra == once, "ikinci açılışta kopya slot oluştu → KOPYA VİDEO"
    finally:
        app2.scheduler.shutdown(wait=False)
