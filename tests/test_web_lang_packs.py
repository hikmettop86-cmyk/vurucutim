"""Dil paketleri paneli.

Kullanıcının asıl korkusu SESSİZ BOZULMA. Paketi olmayan bir dilde kanal kurulursa:
ekrana Türkçe "ABONE OL" çipi basılır, rozet "BİER GARTEN" yazar (Türkçe noktalı İ) ve
aşınmış-kalıp denetçisi hiçbir şey yakalamaz. Üçü de sessiz — hata yok, log yok.

Bu yüzden panel iki iş yapar: paketi GÖSTERİR ve paketi olmayan dilde kanal kurulmasını
ENGELLER.
"""
import json

import pytest

from short_bot.db import init_db
from short_bot.lang_pack import load_pack, set_user_dir
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
reel: {enabled: true, voice_id: v1}
"""


def _app(tmp_path):
    cfg = tmp_path / "config"
    (cfg / "channels").mkdir(parents=True, exist_ok=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8")
    (cfg / "channels" / "k.yaml").write_text(_CH, encoding="utf-8")
    db = tmp_path / "db.sqlite"
    init_db(db)
    app = create_app(config_dir=cfg, db_path=db, templates_dir=tmp_path / "t",
                     music_root=tmp_path, cache_dir=tmp_path, lock_dir=tmp_path,
                     logs_dir=tmp_path, output_root=tmp_path,
                     secrets_path=tmp_path / "s.yaml", scheduler=False)
    return app, cfg


@pytest.fixture(autouse=True)
def _yalitim():
    """`lang_pack._user_dir` modül-global ve `load_pack` lru_cache'li; create_app onu
    kuruyor. Sıfırlanmazsa testler birbirini kirletir ve sonuç test SIRASINA bağlı olur."""
    yield
    set_user_dir(None)


# --- LİSTELEME -------------------------------------------------------------

def test_KODLA_GELEN_paketler_gorunur(tmp_path):
    a, _ = _app(tmp_path)
    body = a.test_client().get("/lang-packs").data.decode("utf-8")
    assert "Türkçe" in body
    assert "English" in body
    assert "kodla gelir" in body


def test_URETILMIS_paket_isaretlenir(tmp_path):
    """de.json Sonnet 5 üretti — kullanıcı hangisinin LLM çıktısı olduğunu bilmeli."""
    a, _ = _app(tmp_path)
    body = a.test_client().get("/lang-packs").data.decode("utf-8")
    assert "Deutsch" in body
    assert "Sonnet 5 üretti" in body or "kodla gelir" in body


def test_URETILMEMIS_dil_EKSIK_gorunur(tmp_path):
    a, _ = _app(tmp_path)
    body = a.test_client().get("/lang-packs").data.decode("utf-8")
    assert "Français" in body
    assert "Paket yok" in body
    assert "üret" in body.lower()


def test_CTA_metinleri_PANELDE_gorunur(tmp_path):
    """Almanca kanal açan biri ekranda NE YAZACAĞINI görebilmeli."""
    a, _ = _app(tmp_path)
    body = a.test_client().get("/lang-packs").data.decode("utf-8")
    assert "ABONE OL" in body            # Türkçe paket
    assert "ABONNIEREN" in body          # Almanca paket


# --- SİHİRBAZ KAPISI: SESSİZ DÜŞME YASAĞININ PANEL UCU ---------------------

def test_paket_YOKKEN_o_dilde_kanal_KURULAMAZ(tmp_path):
    a, cfg = _app(tmp_path)
    r = a.test_client().post("/channels/new-reel", data={
        "name": "Jardin", "topic": "jardinage interessant et surprenant",
        "language": "fr", "voice_id": "elevenlabs_x",
    }, follow_redirects=True)
    body = r.data.decode("utf-8")
    assert "dil paketi" in body.lower()
    # Kanal YAML'ı YAZILMAMALI.
    assert not list((cfg / "channels").glob("jardin*.yaml")), "paket yokken kanal kuruldu"


def test_paketi_OLAN_dil_kapiya_takilmaz(tmp_path, monkeypatch):
    """Almanca paketi var → sihirbaz dil kapısını geçmeli (DNA üretimine kadar gitmeli)."""
    import short_bot.web.routes.reel_new as RN
    gorulen = {}

    def _dur(*a, **kw):
        gorulen["gecti"] = True
        raise RuntimeError("dna burada durduruldu")

    monkeypatch.setattr(RN, "generate_dna", _dur, raising=False)
    a, _ = _app(tmp_path)
    a.test_client().post("/channels/new-reel", data={
        "name": "Bier Garten", "topic": "ueberraschende Fakten ueber Bier",
        "language": "de", "voice_id": "elevenlabs_x",
    })
    assert gorulen.get("gecti"), "Almanca paketi VAR ama sihirbaz dil kapısında durdu"


# --- ELLE DÜZENLEME: BOZUK PAKET KAYDEDİLMEZ ------------------------------

def test_BOZUK_paket_KAYDEDILMEZ(tmp_path):
    """Bozuk paket sessizce kabul edilirse Almanca kanal bozuk çalışır."""
    a, _ = _app(tmp_path)
    tr = load_pack("tr").model_dump()
    tr["lang"] = "de"
    tr["cta_texts"] = ["A" * 30, "b", "c", "d"]      # 30 karakter → çip taşar
    r = a.test_client().post("/lang-packs/de",
                             data={"json": json.dumps(tr, ensure_ascii=False)},
                             follow_redirects=True)
    body = r.data.decode("utf-8")
    assert "REDDED" in body.upper()
    assert "24" in body, "sebep söylenmedi"


def test_GECERSIZ_JSON_reddedilir(tmp_path):
    a, _ = _app(tmp_path)
    r = a.test_client().post("/lang-packs/de", data={"json": "{bu json degil"},
                             follow_redirects=True)
    assert "Geçersiz" in r.data.decode("utf-8")


def test_GECERLI_paket_KAYDEDILIR(tmp_path):
    a, cfg = _app(tmp_path)
    de = load_pack("de").model_dump()
    de["default_series_title"] = "Bier Fakten"
    r = a.test_client().post("/lang-packs/de",
                             data={"json": json.dumps(de, ensure_ascii=False)},
                             follow_redirects=True)
    assert "kaydedildi" in r.data.decode("utf-8")
    yazilan = json.loads((cfg / "langpacks" / "de.json").read_text(encoding="utf-8"))
    assert yazilan["default_series_title"] == "Bier Fakten"


def test_desteklenmeyen_dil_REDDEDILIR(tmp_path):
    a, _ = _app(tmp_path)
    r = a.test_client().post("/lang-packs/zz", data={"json": "{}"},
                             follow_redirects=True)
    assert "Desteklenmeyen" in r.data.decode("utf-8")
