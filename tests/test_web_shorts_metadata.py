"""Short detay sayfası: elle yükleyecek operatör için YouTube metni.

KULLANICI İSTEĞİ (2026-08-20): "bu ekrana indirip manuel yükleyenler için video
açıklaması etiketi falan da gözüksün."

Kilitlenen davranışlar:
  * Metin, otomatik yüklemenin göndereceğinin AYNISI (aynı build_snippet).
  * Bir kez üretilir, script_json'a SAKLANIR — her sayfa açılışında LLM çağırmak
    hem para harcar hem her seferinde başka bir başlık gösterirdi.
  * LLM düşse bile kutu boş kalmaz (LLM'siz yedek).
"""
from __future__ import annotations

import json

import pytest

from short_bot.web import create_app

_SETTINGS = ("ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
             "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
             "claude_models: {dna: opus, default: haiku}\n")

_CH = """\
slug: kanal
name: Kanal
keywords: [haber]
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
handle: '@kanal'
output_dir: output/kanal
enabled: true
"""

_SCRIPT = {"header_top": "ADALAR", "header_bottom": "YİNE SALLANDI",
           "photo_overlay": "KANDİLLİ: 3.1", "body_paragraph": "Marmara sallandı.",
           "highlights": [], "category": "deprem", "mood": "breaking"}


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(_SETTINGS, encoding="utf-8")
    (cfg_dir / "channels" / "kanal.yaml").write_text(_CH, encoding="utf-8")
    (tmp_path / "data").mkdir()
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=tmp_path / "data" / "secrets.yaml", scheduler=False)


def _short(tmp_path, script=None):
    from short_bot.db import init_db, record_short
    eng = init_db(tmp_path / "x.sqlite")
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"mp4")
    return eng, record_short(eng, channel="kanal", rss_item_guid="g1", title="T",
                             file_path=str(vid), duration_s=6,
                             script_json=json.dumps(script or _SCRIPT), render_ms=1)


def _fake_meta(monkeypatch, title="Adalar'da 3.1 deprem"):
    from short_bot.youtube.metadata_writer import YoutubeMetadata

    calls = {"n": 0}

    def _gen(**kw):
        calls["n"] += 1
        return YoutubeMetadata(title=title, description="Açıklama metni.\n\n#shorts",
                               tags=["deprem", "shorts", "son dakika"])
    monkeypatch.setattr("short_bot.web.routes.youtube.generate_youtube_metadata", _gen)
    return calls


def test_kutu_once_bos_ve_yaz_dugmesi_gosterir(app, tmp_path):
    _, sid = _short(tmp_path)
    body = app.test_client().get(f"/shorts/{sid}").data.decode("utf-8")
    assert "YouTube metni" in body and "✎ Yaz" in body
    assert "indirip elle yükleyeceksen" in body


def test_uretim_baslik_aciklama_etiket_gosterir_ve_saklar(app, tmp_path, monkeypatch):
    eng, sid = _short(tmp_path)
    calls = _fake_meta(monkeypatch)
    body = app.test_client().post(f"/shorts/{sid}/metadata").data.decode("utf-8")
    assert "Adalar&#39;da 3.1 deprem" in body or "Adalar'da 3.1 deprem" in body
    assert "Açıklama metni." in body
    assert "deprem, shorts, son dakika" in body          # virgüllü: YouTube kutusuna yapıştırılır
    assert "/100" in body                                 # başlık uzunluk sayacı

    # SAKLANDI: sayfa yeniden açılınca LLM'e gidilmez.
    from sqlalchemy import select
    from short_bot.db import shorts
    with eng.connect() as c:
        data = json.loads(c.execute(select(shorts.c.script_json)
                                    .where(shorts.c.id == sid)).scalar())
    assert data["youtube_meta"]["title"] == "Adalar'da 3.1 deprem"
    assert data["header_top"] == "ADALAR"                 # mevcut alanlar korunur

    page = app.test_client().get(f"/shorts/{sid}").data.decode("utf-8")
    assert "yeniden yaz" in page and "✎ Yaz" not in page
    assert calls["n"] == 1


def test_yeniden_yaz_zorlar(app, tmp_path, monkeypatch):
    _, sid = _short(tmp_path)
    calls = _fake_meta(monkeypatch)
    app.test_client().post(f"/shorts/{sid}/metadata")
    app.test_client().post(f"/shorts/{sid}/metadata")               # önbellekten
    assert calls["n"] == 1
    app.test_client().post(f"/shorts/{sid}/metadata", data={"force": "1"})
    assert calls["n"] == 2


def test_llm_duserse_kutu_bos_kalmaz(app, tmp_path, monkeypatch):
    """Yedek build_snippet'ten gelir — operatör yine kopyalayacak bir şey bulur."""
    _, sid = _short(tmp_path)

    def _boom(**kw):
        raise RuntimeError("model yok")
    monkeypatch.setattr("short_bot.web.routes.youtube.generate_youtube_metadata", _boom)
    body = app.test_client().post(f"/shorts/{sid}/metadata").data.decode("utf-8")
    assert "ADALAR" in body and "Üretilemedi" not in body


def test_silinmis_short_404(app, tmp_path):
    from datetime import datetime, timezone
    from sqlalchemy import update
    eng, sid = _short(tmp_path)
    from short_bot.db import shorts
    with eng.begin() as c:
        c.execute(update(shorts).where(shorts.c.id == sid)
                  .values(deleted_at=datetime.now(timezone.utc)))
    assert app.test_client().post(f"/shorts/{sid}/metadata").status_code == 404
