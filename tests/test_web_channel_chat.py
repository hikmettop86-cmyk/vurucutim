"""Sohbet ekranları: format seçimi, kurma sohbeti, kanal sayfası.

İKİ DAVRANIŞ KRİTİK VE TESTLE SABİTLENDİ:
  1. Kanal sayfası açılırken LLM ÇAĞRILMAZ. Teşhis düz SQL'den gelir; her
     sayfa açılışında Claude CLI çalıştırmak hem yavaş hem gereksiz masraf.
  2. "Kanalı kur"a basılmadan HİÇBİR ŞEY YAZILMAZ — ne YAML, ne CSS.
"""
from __future__ import annotations

import re

import pytest

from short_bot.config import load_channel
from short_bot.web import create_app

_SETTINGS = (
    "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
    "web: {host: 127.0.0.1, port: 5005}\n"
    "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
)
_KANAL = (
    "slug: kart\nname: Kart\nhandle: '@kart'\nkeywords: [a]\nlanguage: tr\n"
    "schedule_cron: '0 9 * * *'\nduration_s: 6\nmin_score: 6.0\n"
    "max_candidates_per_run: 10\ntemplate: newscast\n"
    "colors: {primary: '#000', accent: '#111', bg_gradient: ['#000','#111']}\n"
    "output_dir: out\nenabled: true\n"
)


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(_SETTINGS, encoding="utf-8")
    (cfg_dir / "channels" / "kart.yaml").write_text(_KANAL, encoding="utf-8")
    a = create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                   templates_dir=tmp_path / "templates", music_root=tmp_path / "m",
                   cache_dir=tmp_path / "c", lock_dir=tmp_path / "l",
                   logs_dir=tmp_path / "lg", output_root=tmp_path / "o",
                   scheduler=False)
    a.config["_CH_DIR"] = cfg_dir / "channels"
    return a


def _sahte_llm(monkeypatch, cevap, sayac=None):
    """channel_chat rotasının kullandığı LLM'i değiştirir."""
    def _f():
        def _cagir(prompt, schema, **kw):
            if sayac is not None:
                sayac.append(prompt)
            return cevap
        return _cagir
    monkeypatch.setattr("short_bot.web.routes.channel_chat._llm", _f)


# --- format seçimi ---------------------------------------------------------

def test_format_secimi_dort_karti_gosterir(app):
    html = app.test_client().get("/channels/new").get_data(as_text=True)
    for ad in ("Kart", "Sesli", "Gündem Yorum", "Kürate"):
        assert ad in html


def test_format_karti_o_formattaki_kanallari_gosterir(app):
    """Soyut format adı yerine tanıdık örnek."""
    html = app.test_client().get("/channels/new").get_data(as_text=True)
    assert "kart" in html          # tek kanalımız card formatında


def test_bilinmeyen_format_404(app):
    assert app.test_client().get("/channels/new/uydurma").status_code == 404


# --- kurma sohbeti ---------------------------------------------------------

@pytest.mark.parametrize("fmt", ["card", "voiced", "yorum", "curated"])
def test_kurma_sohbeti_acilir(app, fmt):
    r = app.test_client().get(f"/channels/new/{fmt}")
    assert r.status_code == 200
    assert "Kanalı kur" in r.get_data(as_text=True)


def test_kurma_sohbeti_ACILIRKEN_LLM_CAGIRMAZ(app, monkeypatch):
    sayac = []
    _sahte_llm(monkeypatch, None, sayac)
    app.test_client().get("/channels/new/yorum")
    assert sayac == [], "sayfa açılışında LLM çağrıldı"


def test_sohbet_turu_karar_dondurur(app, monkeypatch):
    from short_bot.channel_chat import Karar, SohbetCevabi
    _sahte_llm(monkeypatch, SohbetCevabi(
        mesaj="Kurdum.",
        kararlar=[Karar(alan="name", deger="Wien Klartext",
                        ozet="Adı Wien Klartext", gerekce="Şehir adı daha çok aranıyor")],
        oneriler=["günde 3 olsun"]))
    c = app.test_client()
    oid = re.search(r"/channels/sohbet/([0-9a-f]+)",
                    c.get("/channels/new/yorum").get_data(as_text=True)).group(1)
    html = c.post(f"/channels/sohbet/{oid}", data={"girdi": "Avusturya gündemi"}).get_data(as_text=True)
    assert "Adı Wien Klartext" in html
    assert "Şehir adı daha çok aranıyor" in html      # GEREKÇE gösterilmeli
    assert "günde 3 olsun" in html                     # öneri çipi


def test_kurmadan_once_HICBIR_SEY_YAZILMAZ(app, monkeypatch):
    from short_bot.channel_chat import Karar, SohbetCevabi
    _sahte_llm(monkeypatch, SohbetCevabi(
        mesaj="ok", kararlar=[Karar(alan="name", deger="Yeni", ozet="", gerekce="")]))
    c = app.test_client()
    once = list(app.config["_CH_DIR"].glob("*.yaml"))
    oid = re.search(r"/channels/sohbet/([0-9a-f]+)",
                    c.get("/channels/new/card").get_data(as_text=True)).group(1)
    c.post(f"/channels/sohbet/{oid}", data={"girdi": "kanal kur"})
    c.post(f"/channels/sohbet/{oid}/uygula", data={"alan": "name"})
    assert list(app.config["_CH_DIR"].glob("*.yaml")) == once


def test_kanali_kur_yaml_yazar_ve_CRON_KAPALI(app, monkeypatch):
    from short_bot.channel_chat import Karar, SohbetCevabi
    _sahte_llm(monkeypatch, SohbetCevabi(
        mesaj="ok", kararlar=[Karar(alan="name", deger="Wien Klartext",
                                    ozet="", gerekce="")]))
    c = app.test_client()
    oid = re.search(r"/channels/sohbet/([0-9a-f]+)",
                    c.get("/channels/new/yorum").get_data(as_text=True)).group(1)
    c.post(f"/channels/sohbet/{oid}", data={"girdi": "Avusturya"})
    c.post(f"/channels/sohbet/{oid}/uygula", data={"alan": "name"})
    c.post(f"/channels/sohbet/{oid}/kur", follow_redirects=True)
    p = app.config["_CH_DIR"] / "wien-klartext.yaml"
    assert p.exists(), "kanal kurulmadı"
    cfg = load_channel(p)
    assert cfg.name == "Wien Klartext"
    assert cfg.enabled is False, "yeni kanal cron'u AÇIK kuruldu"


def test_adsiz_kanal_kurulmaz(app, monkeypatch):
    _sahte_llm(monkeypatch, None)
    c = app.test_client()
    oid = re.search(r"/channels/sohbet/([0-9a-f]+)",
                    c.get("/channels/new/card").get_data(as_text=True)).group(1)
    r = c.post(f"/channels/sohbet/{oid}/kur", follow_redirects=True)
    assert "adı yok" in r.get_data(as_text=True)


def test_llm_patlarsa_kullaniciya_SEBEP_soylenir(app, monkeypatch):
    def _f():
        def _patla(prompt, schema, **kw):
            raise RuntimeError("model yok")
        return _patla
    monkeypatch.setattr("short_bot.web.routes.channel_chat._llm", _f)
    c = app.test_client()
    oid = re.search(r"/channels/sohbet/([0-9a-f]+)",
                    c.get("/channels/new/card").get_data(as_text=True)).group(1)
    html = c.post(f"/channels/sohbet/{oid}", data={"girdi": "x"}).get_data(as_text=True)
    assert "model yok" in html
    assert "elle düzenleyebilirsin" in html


def test_yasak_alan_oneren_karar_ELENIR(app, monkeypatch):
    """LLM slug yazmaya kalkarsa kullanıcıya onay düğmesi gösterip sonra
    patlamak yerine burada elenir."""
    from short_bot.channel_chat import Karar, SohbetCevabi
    _sahte_llm(monkeypatch, SohbetCevabi(
        mesaj="ok", kararlar=[Karar(alan="slug", deger="hack", ozet="", gerekce=""),
                              Karar(alan="name", deger="İyi", ozet="İyi", gerekce="")]))
    c = app.test_client()
    oid = re.search(r"/channels/sohbet/([0-9a-f]+)",
                    c.get("/channels/new/card").get_data(as_text=True)).group(1)
    html = c.post(f"/channels/sohbet/{oid}", data={"girdi": "x"}).get_data(as_text=True)
    assert "uygulanamadı" in html
    assert "İyi" in html          # geçerli karar hayatta kalmalı


# --- kanal sayfası ---------------------------------------------------------

def test_kanal_sayfasi_acilir(app):
    r = app.test_client().get("/channels/kart")
    assert r.status_code == 200


def test_kanal_sayfasi_ACILIRKEN_LLM_CAGIRMAZ(app, monkeypatch):
    """Teşhis düz SQL'den gelir; model yalnız kullanıcı yazınca devreye girer."""
    sayac = []
    _sahte_llm(monkeypatch, None, sayac)
    app.test_client().get("/channels/kart")
    assert sayac == [], "sayfa açılışında LLM çağrıldı"


def test_olmayan_kanal_404(app):
    assert app.test_client().get("/channels/yok-boyle").status_code == 404


def test_kanal_sayfasi_elle_duzenleme_yolunu_KAPATMAZ(app):
    """Sohbet ana yol ama form arkada duruyor — LLM erişilemezse ya da bir
    alanı yanlış anlarsa YAML'ı elle açmak zorunda kalmamalısın."""
    html = app.test_client().get("/channels/kart").get_data(as_text=True)
    assert "/channels/kart/edit" in html
    assert "elle düzenle" in html
