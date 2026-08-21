"""Ayarlar → AI Sağlayıcıları.

KULLANICI İSTEĞİ (2026-08-21): "google ai bedava havuz ve diğer kullanabileceğim
ai apileri bunları aynı şekilde bu otomasyona taşı ayarlar kısmına tüm herşeyi
ile yerleştir ... claude cli bağımlılığından kurtulmak için".

Ölçüldü (arketip şablonu yazma, 33 KB prompt):
    claude_cli/opus                          112,7 sn
    google_studio/gemini-3.5-flash-lite        7,0 sn (ÜCRETSİZ)
    deepseek/deepseek-chat                    13,2 sn
Yani seçim gerçek bir fark yaratıyor ve KULLANICININ olmalı.
"""
from __future__ import annotations

import json

import pytest
import yaml

from short_bot.web import create_app


@pytest.fixture(autouse=True)
def _mock_catalog():
    from unittest.mock import patch
    with patch("short_bot.web.routes.settings.get_catalog",
               return_value={"groups": []}):
        yield


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8")
    d = tmp_path / "data"
    d.mkdir()
    a = create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                   secrets_path=d / "secrets.yaml", scheduler=False)
    a.config["_CFG"] = cfg_dir / "settings.yaml"
    a.config["_SEC"] = d / "secrets.yaml"
    return a


def _yaz(app, **form):
    return app.test_client().post("/settings", data=form, follow_redirects=True)


def _ayar(app):
    return yaml.safe_load(app.config["_CFG"].read_text(encoding="utf-8")) or {}


def _gizli(app):
    p = app.config["_SEC"]
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


# --- ekran ---------------------------------------------------------------

def test_sayfa_TUM_SAGLAYICILARI_listeler(app):
    from short_bot.ai_providers import SAGLAYICILAR
    body = app.test_client().get("/settings").data.decode("utf-8")
    for ad, s in SAGLAYICILAR.items():
        assert s.etiket in body, f"{ad} ekranda yok"


def test_sayfa_HER_ROL_icin_secim_gosterir(app):
    from short_bot.ai_providers import ROLLER
    body = app.test_client().get("/settings").data.decode("utf-8")
    for rol, etiket in ROLLER:
        assert f'name="rol_provider_{rol}"' in body, rol
        assert f'name="rol_model_{rol}"' in body, rol
        assert etiket in body


def test_sayfa_UCRETSIZ_olani_isaretler(app):
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert "ücretsiz" in body.lower()


def test_sayfa_OLCUM_notlarini_gosterir(app):
    """Kullanıcı hangi sağlayıcının ne kadar sürdüğünü görmeden seçemez."""
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert "112,7" in body and "7,0" in body


# --- rol seçimi kaydı -----------------------------------------------------

def test_rol_secimi_YAMLA_yazilir(app):
    _yaz(app, rol_provider_dna="google_studio",
         rol_model_dna="gemini-3.5-flash-lite")
    assert _ayar(app)["ai_roles"]["dna"] == {
        "provider": "google_studio", "model": "gemini-3.5-flash-lite"}


def test_bos_secim_rolu_KALDIRIR(app):
    _yaz(app, rol_provider_dna="google_studio", rol_model_dna="m")
    assert "dna" in _ayar(app).get("ai_roles", {})
    _yaz(app, rol_provider_dna="")
    assert "dna" not in _ayar(app).get("ai_roles", {})


def test_secim_resolve_ai_call_a_YANSIR(app):
    from short_bot.config import load_settings, resolve_ai_call
    _yaz(app, rol_provider_script="deepseek", rol_model_script="deepseek-chat",
         key_deepseek="sk-dd")
    a = load_settings(app.config["_CFG"])
    c = resolve_ai_call(a, _gizli(app), "script")
    assert c.backend == "deepseek" and c.model == "deepseek-chat"
    assert c.api_key == "sk-dd"


# --- sağlayıcı anahtarları ------------------------------------------------

@pytest.mark.parametrize("saglayici,alan", [
    ("deepseek", "deepseek_api_key"), ("qwen", "qwen_api_key"),
    ("gemini_direct", "gemini_api_key"), ("groq", "groq_api_key"),
    ("modelscope", "modelscope_api_key"), ("nvidia", "nvidia_api_key")])
def test_anahtar_secrets_e_yazilir(app, saglayici, alan):
    _yaz(app, **{f"key_{saglayici}": "gizli-deger"})
    assert _gizli(app)[alan] == "gizli-deger"


def test_anahtar_TEMIZLENEBILIR(app):
    _yaz(app, key_deepseek="sk-1")
    assert _gizli(app)["deepseek_api_key"] == "sk-1"
    _yaz(app, key_deepseek_clear="1")
    assert not _gizli(app).get("deepseek_api_key")


def test_bos_gonderim_MEVCUT_anahtari_silmez(app):
    """Formda alan boş bırakılırsa (kullanıcı yeniden yazmadı) key kalmalı."""
    _yaz(app, key_deepseek="sk-kal")
    _yaz(app, key_deepseek="")
    assert _gizli(app)["deepseek_api_key"] == "sk-kal"


def test_anahtar_EKRANDA_MASKELI(app):
    _yaz(app, key_deepseek="sk-1234567890abcd")
    body = app.test_client().get("/settings").data.decode("utf-8")
    assert "sk-1234567890abcd" not in body
    assert "abcd" in body


# --- ücretsiz havuz -------------------------------------------------------

def test_havuz_durumu_gosterilir(app, tmp_path):
    from short_bot import google_studio
    d = tmp_path / "pool"
    d.mkdir()
    (d / "google-keys.json").write_text(json.dumps({"keys": [
        {"id": "a", "key": "AIza", "enabled": True},
        {"id": "b", "key": "AIzb", "enabled": True}]}), encoding="utf-8")
    google_studio.set_pool_dir(d)
    try:
        body = app.test_client().get("/settings").data.decode("utf-8")
        assert "2" in body and "havuz" in body.lower()
    finally:
        google_studio.set_pool_dir(None)


def test_havuz_YOKSA_sayfa_acilir(app):
    from short_bot import google_studio
    google_studio.set_pool_dir(app.config["_CFG"].parent / "olmayan")
    try:
        assert app.test_client().get("/settings").status_code == 200
    finally:
        google_studio.set_pool_dir(None)


# --- HANGİ MODEL GERÇEKTEN KOŞACAK -----------------------------------------
#
# KULLANICI SORUSU (2026-08-21): "hangi ai ler çalışıyor, hepsini gemini flash
# lite 3.5 yapmıştım". Ayarında dört rolde de sağlayıcı seçiliydi ama MODEL
# KUTUSU BOŞTU; boşken sağlayıcının ilk örnek modeline düşülüyor. Ekranda bu
# hiç yazmıyordu, kullanıcı ne koştuğunu bilemiyordu.

def _gecerli_satir(app, rol):
    """Rolün "şu an geçerli" satırı — sayfanın başka yerindeki metne
    yakalanmasın diye işaretli bir bloktan okunur."""
    import re
    body = app.test_client().get("/settings").data.decode("utf-8")
    # İç içe <span> olduğu için ilk `</` ile durmuyoruz; blok sonuna kadar al.
    m = re.search(rf'data-gecerli="{rol}">(.*?)</span>\s*</span>', body, re.S)
    if not m:
        m = re.search(rf'data-gecerli="{rol}">(.{{0,400}})', body, re.S)
    return " ".join(m.group(1).split()) if m else ""


def test_MODEL_BOSKEN_gecerli_secim_ekranda_yazar(app):
    _yaz(app, rol_provider_dna="google_studio", rol_model_dna="")
    assert "gemini-3.5-flash-lite" in _gecerli_satir(app, "dna")


def test_MODEL_YAZILIRSA_o_yazar(app):
    _yaz(app, rol_provider_dna="google_studio",
         rol_model_dna="gemini-3.1-flash-lite")
    assert "gemini-3.1-flash-lite" in _gecerli_satir(app, "dna")


def test_ROL_SECILMEMISSE_hangi_yola_dustugu_yazar(app):
    """Boş rol `AI Kaynağı`na düşer; hangisi olduğu görünmeli."""
    satir = _gecerli_satir(app, "script")
    assert satir and ("Claude CLI" in satir or "claude_cli" in satir)


def test_ANAHTARSIZ_saglayici_secilirse_UYARIR(app):
    """DeepSeek seçilip anahtar girilmezse çağrı 'anahtar yok' diye patlar;
    kullanıcı bunu ÇAĞRI ANINDA değil AYAR anında görmeli."""
    _yaz(app, rol_provider_script="deepseek", rol_model_script="deepseek-chat")
    satir = _gecerli_satir(app, "script")
    assert "anahtar" in satir.lower(), satir


def test_ANAHTAR_VARSA_uyarmaz(app):
    _yaz(app, rol_provider_script="deepseek", rol_model_script="deepseek-chat",
         key_deepseek="sk-var")
    assert "anahtar" not in _gecerli_satir(app, "script").lower()
