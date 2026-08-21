"""Sohbet ekranları: format seçimi, kurma sohbeti, kanal sayfası.

İKİ DAVRANIŞ KRİTİK VE TESTLE SABİTLENDİ:
  1. Kanal sayfası açılırken LLM ÇAĞRILMAZ. Teşhis düz SQL'den gelir; her
     sayfa açılışında Claude CLI çalıştırmak hem yavaş hem gereksiz masraf.
  2. "Kanalı kur"a basılmadan HİÇBİR ŞEY YAZILMAZ — ne YAML, ne CSS.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

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


@pytest.fixture(autouse=True)
def _kimlik_sahte(monkeypatch):
    """HİÇBİR TEST GERÇEK OPUS ÇAĞIRMASIN.

    `kanali_kur` artık görsel kimlik üretiyor. Bu fixture eklenmeden önce iki
    test sessizce gerçek Opus'a gidiyordu: koşu 120 sn'de bitmedi ve kota
    yakıyordu. Kimliği ÖLÇEN testler kendi sahtesiyle bunu eziyor.
    """
    monkeypatch.setattr("short_bot.web.routes.channel_chat.generate_dna",
                        lambda **kw: _fake_dna())
    monkeypatch.setattr("short_bot.web.routes.channel_chat.smoke_render_dna",
                        lambda *a, **kw: (True, "ok"))
    # ARKETİP TASARIMI DA SAHTE. Kurulum artık tasarımı arka planda başlatıyor;
    # yamanmazsa her `/kur` testi gerçek Opus'a gider (canlıda ölçüldü: tur
    # başına ~2 dk, üç tur).
    from short_bot.archetype_design import TasarimSonucu
    monkeypatch.setattr(
        "short_bot.web.routes.channel_chat.adaylar_uret",
        lambda niyet, **kw: [TasarimSonucu(False, sebep="test", tur=1)])
    monkeypatch.setattr("short_bot.web.routes.channel_chat.gercek_render",
                        lambda **kw: (lambda *a: []))
    monkeypatch.setattr("short_bot.web.routes.channel_chat.gercek_vision",
                        lambda **kw: None)


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


# --- BEKLEME GÖSTERGESİ ----------------------------------------------------
#
# KULLANICI BİLDİRİMİ (2026-08-21): "kendi cümlenle yaz'a yazıyorum hiç tepki
# yok". Ölçüldü: bir sohbet turu canlıda 55-110 saniye sürüyor ve formda
# HİÇBİR bekleme göstergesi yoktu. `this.reset()` bile ancak istek bitince
# çalıştığı için ekran bir dakika boyunca donmuş görünüyordu — başarılı turda
# bile.

def _sohbet_sayfalari(app):
    c = app.test_client()
    return {"kurma": c.get("/channels/new/card").get_data(as_text=True),
            "kanal": c.get("/channels/kart").get_data(as_text=True)}


@pytest.mark.parametrize("nere", ["kurma", "kanal"])
def test_sohbet_formu_BEKLEME_GOSTERIR(app, nere):
    html = _sohbet_sayfalari(app)[nere]
    m = re.search(r'hx-indicator="#([\w-]+)"', html)
    assert m, "sohbet formunda bekleme göstergesi yok"
    assert f'id="{m.group(1)}"' in html, "gösterge elemanı sayfada yok"


@pytest.mark.parametrize("nere", ["kurma", "kanal"])
def test_sohbet_gonder_dugmesi_ISTEK_SURERKEN_kilitlenir(app, nere):
    """Kilitlenmezse kullanıcı ikinci kez basar ve iki tur paralel koşar."""
    assert "hx-disabled-elt" in _sohbet_sayfalari(app)[nere]


def test_bekleme_metni_SUREYI_soyler(app):
    """'Yükleniyor' yetmez: bir dakika bekleneceğini bilmek gerekiyor."""
    html = _sohbet_sayfalari(app)["kurma"]
    i = html.find('id="dusunuyor"')
    assert i > 0
    assert "dakika" in html[i:i + 400]


def test_kurulum_mesaji_CRON_DURUMUNU_dogru_soyler(app, monkeypatch):
    """Mesaj sabit "Cron KAPALI" diyordu; model `enabled: True` kararı verip
    kullanıcı onaylayınca mesaj yalan oluyordu."""
    from short_bot.channel_chat import Karar, SohbetCevabi
    c = app.test_client()
    oid = re.search(r'hx-post="/channels/sohbet/([0-9a-f]+)"',
                    c.get("/channels/new/card").get_data(as_text=True)).group(1)
    _sahte_llm(monkeypatch, SohbetCevabi(
        mesaj="kurdum",
        kararlar=[Karar(alan="name", deger="Aç Kanal", ozet="ad", gerekce="g"),
                  Karar(alan="keywords", deger=["a"], ozet="k", gerekce="g"),
                  Karar(alan="enabled", deger=True, ozet="açık", gerekce="g")]))
    c.post(f"/channels/sohbet/{oid}", data={"girdi": "kur"})
    c.post(f"/channels/sohbet/{oid}/uygula")
    m = c.post(f"/channels/sohbet/{oid}/kur", follow_redirects=True).get_data(as_text=True)
    assert "Cron AÇIK" in m
    assert "Cron KAPALI" not in m


# --- KURULUM GÖRSEL KİMLİK ÜRETMELİ ----------------------------------------
#
# CANLI ARIZA (2026-08-21): sohbetle kurulan "Beşiktaş Gündem" kanalı
# `template: flas` ve KIRMIZI/SARI paletle kaydedildi — Beşiktaş siyah-beyaz.
# YAML'da `dna:` bloğu HİÇ YOKTU ve `templates/css/<slug>.css` yazılmamıştı.
#
# Sebep: eski sihirbaz (`channel_new.save`) `generate_dna` + `smoke_render_dna`
# + `build_css_override` koşuyordu; sohbetin `kanali_kur`'u YALNIZ YAML
# yazıyordu. Planda "Adım 5: YAML + CSS + konu bankası" işaretliydi ama CSS ve
# DNA hiç bağlanmamıştı.

def _fake_dna(archetype="stat-hero", primary="#000000"):
    from short_bot.dna import DnaFonts, DnaPalette, DnaSpec, DnaTone
    return DnaSpec(archetype=archetype,
                   palette=DnaPalette(primary=primary, accent="#ffffff",
                                      bg_gradient=["#111111", "#000000"],
                                      body_bg=["#111111", "#000000"]),
                   fonts=DnaFonts(), tone=DnaTone(voice="x", style="y"),
                   persona_summary="siyah beyaz kartal")


def _kur(app, monkeypatch, *, dna_ok=True, smoke=(True, "ok")):
    from short_bot.channel_chat import Karar, SohbetCevabi
    c = app.test_client()
    oid = re.search(r'hx-post="/channels/sohbet/([0-9a-f]+)"',
                    c.get("/channels/new/card").get_data(as_text=True)).group(1)
    _sahte_llm(monkeypatch, SohbetCevabi(mesaj="kurdum", kararlar=[
        Karar(alan="name", deger="Beşiktaş Gündem", ozet="ad", gerekce="g"),
        Karar(alan="keywords", deger=["Beşiktaş", "BJK"], ozet="kelime",
              gerekce="g")]))

    def _dna(**kw):
        if not dna_ok:
            raise RuntimeError("Opus cevap vermedi")
        return _fake_dna()
    monkeypatch.setattr("short_bot.web.routes.channel_chat.generate_dna", _dna)
    monkeypatch.setattr("short_bot.web.routes.channel_chat.smoke_render_dna",
                        lambda *a, **kw: smoke)
    c.post(f"/channels/sohbet/{oid}", data={"girdi": "Beşiktaş kanalı"})
    c.post(f"/channels/sohbet/{oid}/uygula")
    r = c.post(f"/channels/sohbet/{oid}/kur", follow_redirects=True)
    return c, oid, r


def test_kurulan_kanal_DNA_TASIR(app, monkeypatch):
    _kur(app, monkeypatch)
    cfg = load_channel(app.config["_CH_DIR"] / "besiktas-gundem.yaml")
    assert cfg.dna is not None, "kanal DNA'sız kuruldu"
    assert cfg.template == "stat-hero" == cfg.dna.archetype
    assert cfg.colors["primary"] == "#000000", "taslağın sabit paleti kalmış"


def test_kurulan_kanalin_CSSI_yazilir(app, monkeypatch):
    _kur(app, monkeypatch)
    css = app.config["SHORTBOT_TEMPLATES_DIR"] / "css" / "besiktas-gundem.css"
    assert css.exists() and css.read_text(encoding="utf-8").strip()


def test_DNA_URETILEMEZSE_kanal_KURULMAZ(app, monkeypatch):
    """Kimliksiz kanal, kullanıcının şikâyet ettiği kanaldır. Oturum korunur ki
    sohbet kaybolmasın; kullanıcı tekrar dener."""
    c, oid, r = _kur(app, monkeypatch, dna_ok=False)
    assert not (app.config["_CH_DIR"] / "besiktas-gundem.yaml").exists()
    assert "Opus cevap vermedi" in r.get_data(as_text=True)
    assert c.get(f"/channels/sohbet/{oid}").status_code == 200, "oturum düştü"


def test_SMOKE_RENDER_patlarsa_kanal_KURULMAZ(app, monkeypatch):
    """Bozuk yerleşim üreten DNA diske yazılmamalı (eski sihirbazın kapısı)."""
    c, oid, r = _kur(app, monkeypatch, smoke=(False, "kare düz renk"))
    assert not (app.config["_CH_DIR"] / "besiktas-gundem.yaml").exists()
    assert "kare düz renk" in r.get_data(as_text=True)


def test_EKSIK_kanal_diske_yazilmaz(app, monkeypatch):
    """`load_channel` kaydedicinin bilmediği kuralları uyguluyor: rss kaynaklı
    kanal keywords ister. Sohbet yalnız `name` kararı verirse eskiden dosya
    YAZILIYOR ve sonra okunamıyordu (kanal sayfası patlıyordu)."""
    from short_bot.channel_chat import Karar, SohbetCevabi
    c = app.test_client()
    oid = re.search(r'hx-post="/channels/sohbet/([0-9a-f]+)"',
                    c.get("/channels/new/card").get_data(as_text=True)).group(1)
    _sahte_llm(monkeypatch, SohbetCevabi(mesaj="ok", kararlar=[
        Karar(alan="name", deger="Kelimesiz", ozet="ad", gerekce="g")]))
    c.post(f"/channels/sohbet/{oid}", data={"girdi": "kanal"})
    c.post(f"/channels/sohbet/{oid}/uygula")
    r = c.post(f"/channels/sohbet/{oid}/kur", follow_redirects=True)
    assert not (app.config["_CH_DIR"] / "kelimesiz.yaml").exists()
    assert "keywords" in r.get_data(as_text=True)
    # Sınama dosyası da ARKADA KALMAMALI.
    assert not list(app.config["_CH_DIR"].glob(".*"))


# --- YENİ ARKETİP TASARIMI -------------------------------------------------
#
# `archetype_design.tasarla` yazıldı ama HİÇBİR YERDEN ÇAĞRILMIYORDU (grep: 0
# çağrı). Kullanıcının istediği "kendi tasarlasın" yeteneği ölü koddu.
# Tasarım dakikalar sürüyor (LLM → 3 render → vision) → arka plan işi.

def _sahte_tasarim(monkeypatch, ok=True, slug="kartal", sebep="geçemedi"):
    from short_bot.archetype_design import TasarimSonucu
    cagri = []

    def _t(niyet, **kw):
        cagri.append((niyet, kw.get("ad")))
        return [TasarimSonucu(ok, slug=slug if ok else "",
                              sebep="" if ok else sebep, tur=1,
                              html="<!DOCTYPE html><html></html>" if ok else "")]
    monkeypatch.setattr("short_bot.web.routes.channel_chat.adaylar_uret", _t)
    monkeypatch.setattr("short_bot.web.routes.channel_chat.gercek_render",
                        lambda **kw: (lambda *a: []))
    monkeypatch.setattr("short_bot.web.routes.channel_chat.gercek_vision",
                        lambda **kw: None)
    return cagri


def test_arketip_tasarimi_ARKA_PLANDA_baslar(app, monkeypatch):
    _sahte_tasarim(monkeypatch)
    r = app.test_client().post("/channels/kart/arketip",
                               data={"niyet": "siyah beyaz, kartal"})
    assert r.status_code == 200
    govde = r.get_data(as_text=True)
    assert "arketip-durum/" in govde, "durum yoklaması bağlanmamış"


def test_arketip_isi_NIYETI_tasarima_gecirir(app, monkeypatch):
    """Bu test eskiden "başarılı olunca kanal o şablona geçer" diyordu.

    Artık iş KANALA DOKUNMUYOR: üç aday üretip kullanıcıya seçtiriyor
    (kullanıcı kararı 2026-08-21). Uygulama `arketip-sec` rotasında —
    `test_SECIM_kanali_o_sablona_gecirir` orayı sınıyor.
    """
    from short_bot.web.routes.channel_chat import _arketip_isi
    cagri = _sahte_tasarim(monkeypatch, slug="kartal")
    with app.app_context():
        _arketip_isi("j1", niyet="siyah beyaz", ad="Kart",
                     slug="kart", channels_dir=app.config["_CH_DIR"],
                     templates_dir=app.config["SHORTBOT_TEMPLATES_DIR"],
                     settings=app.config["SHORTBOT_SETTINGS"], secrets={})
    assert cagri and cagri[0][0] == "siyah beyaz"
    assert load_channel(app.config["_CH_DIR"] / "kart.yaml").template == "newscast"


def test_HICBIR_ADAY_gecemezse_kanal_DEGISMEZ(app, monkeypatch):
    """Kapılardan geçemeyen şablon kaydedilmiyor; kanal da bozuk bir şablona
    geçirilmemeli ve sebep panelde kalmalı."""
    from short_bot.web.routes.channel_chat import _arketip_isi, _is_oku
    _sahte_tasarim(monkeypatch, ok=False, sebep="manşet kesilmiş")
    with app.app_context():
        _arketip_isi("j2", niyet="x", ad="Kart", slug="kart",
                     channels_dir=app.config["_CH_DIR"],
                     templates_dir=app.config["SHORTBOT_TEMPLATES_DIR"],
                     settings=app.config["SHORTBOT_SETTINGS"], secrets={})
    assert load_channel(app.config["_CH_DIR"] / "kart.yaml").template == "newscast"
    i = _is_oku("j2")
    assert i["durum"] == "hata"
    assert "manşet kesilmiş" in i["adaylar"][0]["sebep"]


def test_kanal_sayfasi_GORSEL_KIMLIGI_gosterir(app):
    """Kullanıcının şikâyeti tasarımdı ama sayfa tasarımı hiç göstermiyordu."""
    html = app.test_client().get("/channels/kart").get_data(as_text=True)
    assert "newscast" in html, "arketip adı görünmüyor"
    assert 'action="/channels/kart/arketip"' in html


def test_TEK_BOZUK_KARAR_partiyi_dusurmez(app, monkeypatch):
    """Kart kanalında `voice.enabled` uygulanamaz. Eskiden filtre yalnız alan
    ADINI sınıyordu; karar onay listesine giriyor, `uygula` partinin tamamını
    reddediyordu — `name` bile yazılmıyordu."""
    from short_bot.channel_chat import Karar, SohbetCevabi
    c = app.test_client()
    oid = re.search(r'hx-post="/channels/sohbet/([0-9a-f]+)"',
                    c.get("/channels/new/card").get_data(as_text=True)).group(1)
    _sahte_llm(monkeypatch, SohbetCevabi(mesaj="ok", kararlar=[
        Karar(alan="name", deger="Sağlam", ozet="ad", gerekce="g"),
        Karar(alan="voice.enabled", deger=True, ozet="ses", gerekce="g"),
        Karar(alan="keywords", deger=["a"], ozet="k", gerekce="g")]))
    tur = c.post(f"/channels/sohbet/{oid}", data={"girdi": "kur"}).get_data(as_text=True)
    assert 'value="voice.enabled"' not in tur, "imkânsız karar onaya sunuldu"
    assert "voice" in tur, "elenen karar kullanıcıya söylenmedi"
    c.post(f"/channels/sohbet/{oid}/uygula")
    c.post(f"/channels/sohbet/{oid}/kur", follow_redirects=True)
    assert (app.config["_CH_DIR"] / "saglam.yaml").exists(), "kanal kurulmadı"


# --- KURULUM SIFIRDAN TASARIM BAŞLATIR -------------------------------------
#
# KULLANICI BİLDİRİMİ (2026-08-21): "bayern münich için üretim bu hala eski
# arketipler üzerinden yamalıyor sıfırdan üretmiyor". Doğru: `generate_dna`
# arketipi 40 hazır şablondan SEÇİYOR ve üstüne `custom_css` yamıyor.
# `bayern-munih-gundem.yaml` → template: stadium.
#
# Kanal HEMEN kurulur (DNA ~70 sn), yeni şablon ARKA PLANDA tasarlanır
# (ölçüldü: 376 sn, 2. turda geçti). Geçerse kanal ona döner, geçmezse DNA'nın
# seçtiği arketiple kalır ve sebep panelde YAZILI kalır — sessizce eskiye
# dönmek kullanıcının şikâyetini geri getirirdi.

def test_kurulum_SIFIRDAN_TASARIMI_baslatir(app, monkeypatch):
    from short_bot.web.routes.channel_chat import slug_isi
    _kur(app, monkeypatch)
    i = slug_isi("besiktas-gundem")
    assert i is not None, "kurulumda arketip tasarımı hiç başlamadı"
    # DURUM SABİTLENMEZ: iş arka planda koşuyor, testin baktığı anda bitmiş de
    # olabilir. Sabitlenen şey işin BAŞLADIĞI ve niyetin yazıldığı.
    assert i["niyet"]


def test_tasarim_niyeti_KANALIN_KIMLIGINDEN_turer(app, monkeypatch):
    """Niyet boşsa model jenerik bir haber kartı yazar — kanalın kimliği
    (ad + DNA paleti/personası) niyete girmeli."""
    from short_bot.web.routes.channel_chat import slug_isi
    _kur(app, monkeypatch)
    niyet = slug_isi("besiktas-gundem")["niyet"]
    assert "Beşiktaş Gündem" in niyet
    assert "#000000" in niyet, "palet niyete girmiyor"
    assert "siyah beyaz kartal" in niyet, "persona niyete girmiyor"


def test_kanal_sayfasi_KOSAN_TASARIMI_gosterir(app, monkeypatch):
    """Tasarım koşarken kullanıcı bunu görmeli, yoksa "yine eski arketip" sanır."""
    import threading as _th
    from short_bot.archetype_design import TasarimSonucu
    bekle = _th.Event()
    monkeypatch.setattr(
        "short_bot.web.routes.channel_chat.adaylar_uret",
        lambda niyet, **kw: (bekle.wait(10),
                             [TasarimSonucu(False, sebep="x")])[1])
    try:
        _kur(app, monkeypatch)
        html = app.test_client().get(
            "/channels/besiktas-gundem").get_data(as_text=True)
        assert "arketip-durum/" in html, "koşan tasarım sayfada görünmüyor"
        assert "üç ayrı tasarım dilinde" in html
    finally:
        bekle.set()


def test_tasarim_GECEMEZSE_sebep_kanal_sayfasinda_YAZILI_kalir(app, monkeypatch):
    """Sessizce eski arketiple kalmak kullanıcının şikâyetini geri getirirdi."""
    from short_bot.web.routes.channel_chat import slug_isi
    _kur(app, monkeypatch)          # autouse sahte aday "test" sebebiyle düşer
    for _ in range(50):
        if (slug_isi("besiktas-gundem") or {}).get("durum") == "hata":
            break
        time.sleep(0.05)
    html = app.test_client().get("/channels/besiktas-gundem").get_data(as_text=True)
    assert "kaydedilmedi" in html or "geçemedi" in html
    assert "test" in html


def test_SECIM_KANALI_OKUNAMAZ_hale_getiremez(app, monkeypatch):
    """Seçilen şablon `DnaSpec.archetype` doğrulamasından geçmezse kanal
    YAML'ı okunamaz olur — canlıda tam bu oldu ("unknown archetype:
    'bayern-m-nih'"). Kayıt düzeltildi ama kapı da olmalı: şablon geçici,
    kanal kalıcı."""
    from short_bot.archetype_design import TasarimSonucu
    from short_bot.web.routes.channel_chat import _arketip_isi
    import short_bot.dna as dna
    _kur(app, monkeypatch)
    monkeypatch.setattr(
        "short_bot.web.routes.channel_chat.adaylar_uret",
        lambda niyet, **kw: [TasarimSonucu(True, slug="kayitsiz", tur=1,
                                           html="<!DOCTYPE html><html></html>")])
    with app.app_context():
        _arketip_isi("jz", niyet="x", ad="Beşiktaş Gündem",
                     slug="besiktas-gundem",
                     channels_dir=app.config["_CH_DIR"],
                     templates_dir=app.config["SHORTBOT_TEMPLATES_DIR"],
                     settings=app.config["SHORTBOT_SETTINGS"], secrets={})
    # Kayıt YAPILMIYOR gibi davran → arketip geçersiz kalır.
    monkeypatch.setattr(dna, "register_designed_archetype", lambda *a, **k: None)
    app.test_client().post("/channels/arketip-sec/jz/0", follow_redirects=True)
    cfg = load_channel(app.config["_CH_DIR"] / "besiktas-gundem.yaml")
    assert cfg.template == "stat-hero" and cfg.dna.archetype == "stat-hero"


# --- ÜÇ ADAY, KULLANICI SEÇER (panel) --------------------------------------
#
# KULLANICI KARARI (2026-08-21): "3 aday üret, ben seçeyim" + "kullanıcı ne
# oluşturduğunu görmeli".

def _sahte_adaylar(monkeypatch, kareli=True):
    from short_bot.archetype_design import TasarimSonucu

    def _uret(niyet, *, ad, templates_dir, kanit_dir=None, **kw):
        out = []
        for i, yon in enumerate(("wired", "nike", "spacex")):
            kareler = ()
            if kareli and kanit_dir is not None:
                from pathlib import Path
                d = Path(kanit_dir) / f"aday{i}"
                d.mkdir(parents=True, exist_ok=True)
                (d / "kare0.png").write_bytes(b"\x89PNG-sahte")
                kareler = (d / "kare0.png",)
            out.append(TasarimSonucu(
                ok=(i != 2), slug=f"aday{i}", html="<!DOCTYPE html><html></html>",
                kareler=kareler, yon=yon, tur=1,
                sebep="" if i != 2 else "manşet kesilmiş"))
        return out
    monkeypatch.setattr("short_bot.web.routes.channel_chat.adaylar_uret", _uret)
    monkeypatch.setattr("short_bot.web.routes.channel_chat.gercek_render",
                        lambda **kw: (lambda *a: []))
    monkeypatch.setattr("short_bot.web.routes.channel_chat.gercek_vision",
                        lambda **kw: None)
    monkeypatch.setattr("short_bot.web.routes.channel_chat._tasarim_llm",
                        lambda a, b: (lambda p: ""))


def _isi_kosur(app, monkeypatch, slug="kart"):
    from short_bot.web.routes.channel_chat import _arketip_isi, _is_oku
    with app.app_context():
        _arketip_isi("ja", niyet="x", ad="Kart", slug=slug,
                     channels_dir=app.config["_CH_DIR"],
                     templates_dir=app.config["SHORTBOT_TEMPLATES_DIR"],
                     settings=app.config["SHORTBOT_SETTINGS"], secrets={},
                     kanit_dir=app.config["SHORTBOT_CACHE_DIR"] / "arketip" / "ja")
    return _is_oku("ja")


def test_is_UC_ADAY_dondurur(app, monkeypatch):
    _sahte_adaylar(monkeypatch)
    i = _isi_kosur(app, monkeypatch)
    assert i["durum"] == "secim"
    assert len(i["adaylar"]) == 3
    assert [a["yon"] for a in i["adaylar"]] == ["wired", "nike", "spacex"]


def test_adaylar_SECILENE_KADAR_kanala_dokunmaz(app, monkeypatch):
    _sahte_adaylar(monkeypatch)
    _isi_kosur(app, monkeypatch)
    assert load_channel(app.config["_CH_DIR"] / "kart.yaml").template == "newscast"


def test_DUSEN_aday_da_SEBEBIYLE_gosterilir(app, monkeypatch):
    _sahte_adaylar(monkeypatch)
    i = _isi_kosur(app, monkeypatch)
    dusen = [a for a in i["adaylar"] if not a["ok"]]
    assert len(dusen) == 1 and "manşet kesilmiş" in dusen[0]["sebep"]


def test_kare_ROTASI_png_dondurur(app, monkeypatch):
    _sahte_adaylar(monkeypatch)
    _isi_kosur(app, monkeypatch)
    r = app.test_client().get("/channels/arketip-kare/ja/0/0")
    assert r.status_code == 200 and r.data.startswith(b"\x89PNG")


def test_kare_ROTASI_dizin_disina_cikamaz(app, monkeypatch):
    """Yol gezinme: kare indeksleri sayı olmalı, dosya yolu kullanıcıdan gelmemeli."""
    _sahte_adaylar(monkeypatch)
    _isi_kosur(app, monkeypatch)
    c = app.test_client()
    assert c.get("/channels/arketip-kare/ja/0/99").status_code == 404
    assert c.get("/channels/arketip-kare/ja/99/0").status_code == 404
    assert c.get("/channels/arketip-kare/yokis/0/0").status_code == 404


def test_SECIM_kanali_o_sablona_gecirir(app, monkeypatch):
    _sahte_adaylar(monkeypatch)
    _isi_kosur(app, monkeypatch)
    import short_bot.archetype_design as AD
    monkeypatch.setattr(AD, "aday_kaydet",
                        lambda s, *, ad, templates_dir, sorgular=(): "secilen")
    monkeypatch.setattr(AD, "pexels_sorgulari",
                        lambda ad, **kw: ["a shot", "b shot", "c shot"])
    import short_bot.dna as dna
    dna.register_designed_archetype("secilen", "Seçilen")
    r = app.test_client().post("/channels/arketip-sec/ja/1", follow_redirects=True)
    assert r.status_code == 200
    assert load_channel(app.config["_CH_DIR"] / "kart.yaml").template == "secilen"


def test_GECMEYEN_aday_secilemez(app, monkeypatch):
    _sahte_adaylar(monkeypatch)
    _isi_kosur(app, monkeypatch)
    r = app.test_client().post("/channels/arketip-sec/ja/2", follow_redirects=True)
    assert load_channel(app.config["_CH_DIR"] / "kart.yaml").template == "newscast"
    assert "geçemedi" in r.get_data(as_text=True) or "seçilemez" in r.get_data(as_text=True)


def test_kurulumda_DIL_KARARI_uygulanir(app, monkeypatch):
    """KULLANICI BİLDİRİMİ: "İngilizce yap diyorum, kanalı Türkçe yapıyor"."""
    from short_bot.channel_chat import Karar, SohbetCevabi
    c = app.test_client()
    oid = re.search(r'hx-post="/channels/sohbet/([0-9a-f]+)"',
                    c.get("/channels/new/card").get_data(as_text=True)).group(1)
    _sahte_llm(monkeypatch, SohbetCevabi(mesaj="ok", kararlar=[
        Karar(alan="name", deger="US Breaking News", ozet="ad", gerekce="g"),
        Karar(alan="language", deger="en", ozet="dil", gerekce="g"),
        Karar(alan="keywords", deger=["breaking news"], ozet="k", gerekce="g")]))
    tur = c.post(f"/channels/sohbet/{oid}", data={"girdi": "US breaking news"})
    assert 'value="language"' in tur.get_data(as_text=True), "dil kararı elendi"
    c.post(f"/channels/sohbet/{oid}/uygula")
    c.post(f"/channels/sohbet/{oid}/kur", follow_redirects=True)
    cfg = load_channel(app.config["_CH_DIR"] / "us-breaking-news.yaml")
    assert cfg.language == "en"
    assert "TR" not in cfg.rss_locale


def test_KURULMUS_kanalda_dil_karari_ELENIR(app, monkeypatch):
    from short_bot.channel_chat import Karar, SohbetCevabi
    c = app.test_client()
    oid = re.search(r'hx-post="/channels/sohbet/([0-9a-f]+)"',
                    c.get("/channels/kart").get_data(as_text=True)).group(1)
    _sahte_llm(monkeypatch, SohbetCevabi(mesaj="ok", kararlar=[
        Karar(alan="language", deger="en", ozet="dil", gerekce="g")]))
    tur = c.post(f"/channels/sohbet/{oid}", data={"girdi": "ingilizce yap"})
    govde = tur.get_data(as_text=True)
    assert 'value="language"' not in govde
    assert "language" in govde, "elenen karar kullanıcıya söylenmedi"


def test_prompt_KULLANICININ_DILINI_algilamasini_soyler():
    from short_bot.channel_chat import prompt_kur, taslak
    p = prompt_kur(cfg=taslak("card"), gecmis=[], girdi="US breaking news",
                   fmt="card", kurulum=True)
    assert "dil" in p.lower()
    i = p.lower().find("language")
    assert i > 0


# --- PANEL HANGİ AI'IN KOŞTUĞUNU DOĞRU SÖYLEMELİ ---------------------------
#
# KULLANICI SORUSU (2026-08-21): "burda hangi ai ler çalışıyor, ben hepsini
# gemini flash lite 3.5 yapmıştım". Sormak zorunda kalmasının sebebi: sohbet
# başlığında SABİT "Claude CLI · Sonnet 5" yazıyordu ve ayara hiç bakmıyordu.

def test_sohbet_basligi_GERCEK_saglayiciyi_yazar(app):
    yol = app.config["_CFG"] if "_CFG" in app.config else None
    import yaml
    p = app.config["SHORTBOT_CONFIG_DIR"] / "settings.yaml"
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    d["ai_roles"] = {"script": {"provider": "google_studio",
                                "model": "gemini-3.5-flash-lite"}}
    p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    from short_bot.config import load_settings
    app.config["SHORTBOT_SETTINGS"] = load_settings(p)

    html = app.test_client().get("/channels/kart").get_data(as_text=True)
    assert "gemini-3.5-flash-lite" in html
    assert "Claude CLI · Sonnet 5" not in html


def test_sohbet_basligi_AYAR_YOKSA_claude_cli_der(app):
    html = app.test_client().get("/channels/kart").get_data(as_text=True)
    assert "claude_cli" in html or "Claude CLI" in html


# --- KARE YOLU MUTLAK OLMALI -----------------------------------------------
#
# CANLI ARIZA (2026-08-21): panelde üç aday geldi ama karelerin hepsi KIRIK
# görsel çıktı. Rota 404 değil 500 veriyordu:
#
#   FileNotFoundError: 'D:\short\src\short_bot\web\data\cache\arketip\...'
#
# `cache_dir` varsayılanı GÖRELİ ("data/cache"). `Path.exists()` CWD'ye göre
# doğru cevap veriyor ama Flask'ın `send_file`ı göreli yolu APP ROOT'a
# (`src/short_bot/web`) göre çözüyor. Testler `tmp_path` (mutlak) kullandığı
# için bunu HİÇ yakalamıyordu.

def test_kanit_dizini_MUTLAK(app):
    from short_bot.web.routes.channel_chat import _kanit_dir
    app.config["SHORTBOT_CACHE_DIR"] = Path("data/cache")   # göreli, üretimdeki gibi
    with app.app_context():
        d = _kanit_dir("abc")
    assert d.is_absolute(), d


def test_GORELI_cache_dizininde_de_kare_servis_edilir(app, monkeypatch, tmp_path):
    """Üretimdeki asıl vaka: göreli cache dizini."""
    import os
    from short_bot.archetype_design import TasarimSonucu
    from short_bot.web.routes.channel_chat import _ISLER, _is_yaz
    monkeypatch.chdir(tmp_path)
    app.config["SHORTBOT_CACHE_DIR"] = Path("data/cache")
    with app.app_context():
        from short_bot.web.routes.channel_chat import _kanit_dir
        d = _kanit_dir("jg") / "aday"
    d.mkdir(parents=True, exist_ok=True)
    (d / "kare0.png").write_bytes(b"\x89PNG-x")
    _is_yaz("jg", durum="secim", slug="kart", adaylar=[])
    _ISLER["jg"]["_ham"] = [TasarimSonucu(True, kareler=(d / "kare0.png",))]
    r = app.test_client().get("/channels/arketip-kare/jg/0/0")
    assert r.status_code == 200, r.status_code
    assert r.data.startswith(b"\x89PNG")
