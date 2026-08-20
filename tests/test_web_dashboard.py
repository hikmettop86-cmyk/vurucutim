"""Kokpit ekranı (panelin açılış sayfası).

Ekranın işi "kaç video var" değil "şu an benden ne bekleniyor" sorusuna cevap
vermek. Testler bu sözleşmeyi kilitliyor; en önemlisi de eski ekranın ölçüm
hatasının geri gelmemesi (bkz. ``test_kokpit_silinmis_uretimi_de_gosterir``).
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from short_bot.dashboard_stats import STALE_RUN_MINUTES
from short_bot.db import (finish_run, init_db, record_short,
                          record_youtube_upload, start_run)
from short_bot.web import create_app

CHANNEL_YAML = """\
slug: demo
name: Demo Kanal
keywords: [x]
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
handle: '@demo'
output_dir: output/demo
enabled: true
"""


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _soft_delete(eng, short_id):
    with eng.begin() as conn:
        conn.execute(text("UPDATE shorts SET deleted_at = :t WHERE id = :i"),
                     {"t": _utcnow().strftime("%Y-%m-%d %H:%M:%S.%f"), "i": short_id})


def _make_app(tmp_path, *, seed=None):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8",
    )
    (cfg_dir / "channels" / "demo.yaml").write_text(CHANNEL_YAML, encoding="utf-8")
    db_path = tmp_path / "x.sqlite"
    eng = init_db(db_path)
    if seed is not None:
        seed(eng)
    app = create_app(config_dir=cfg_dir, db_path=db_path, scheduler=False)
    app.config["_ENG"] = eng
    return app


@pytest.fixture
def app(tmp_path):
    """Varsayılan senaryo: 2 üretim (biri yayında, ikisi de silinmiş) + 1 çöken koşu.

    İkisinin de silinmiş olması bilinçli — üretimdeki gerçek durum bu.
    """
    def seed(eng):
        yayinda = record_short(eng, channel="demo", rss_item_guid="g1", title="Alpha",
                               file_path="output/demo/a.mp4", duration_s=6,
                               script_json="{}", render_ms=1000)
        record_youtube_upload(eng, short_id=yayinda, video_id="v1",
                              status="success", error=None, video_url="https://y/v1")
        _soft_delete(eng, yayinda)

        elenen = record_short(eng, channel="demo", rss_item_guid="g2", title="Beta",
                              file_path="output/demo/b.mp4", duration_s=6,
                              script_json="{}", render_ms=1000)
        _soft_delete(eng, elenen)

        rid = start_run(eng, "demo", trigger="cron", log_path="x.log")
        finish_run(eng, rid, status="failed", short_id=None, error="patladi")

    return _make_app(tmp_path, seed=seed)


# ----------------------------------------------------------- temel ölçüm ----

def test_kokpit_silinmis_uretimi_de_gosterir(app):
    """ASIL REGRESYON: eski ekran ``deleted_at IS NULL`` sayıyordu.

    Operatör beğendiğini yükleyip listeden sildiği için üretilen her video
    eninde sonunda silinmiş oluyor ve sayaçlar sıfıra düşüyordu — ekranda
    0 · 0 · 0 yazarken 45 video üretilmişti.
    """
    body = app.test_client().get("/").data.decode("utf-8")
    assert "Kokpit" in body
    # 2 üretildi → 1 yayına → 1 elendi
    assert "üretildi" in body
    assert "yayına" in body
    assert "elendi" in body


def test_kokpit_karar_kirilimini_gosterir(app):
    body = app.test_client().get("/").data.decode("utf-8")
    assert "Karar verilenlerin" in body
    assert "%50" in body          # 1 yayına / 2 karar


def test_kokpit_kanal_tablosu_satiri_uretir(app):
    body = app.test_client().get("/").data.decode("utf-8")
    assert "Demo Kanal" in body
    assert "demo" in body
    assert "Sıradaki" in body     # ham cron yerine saat sütunu


def test_kokpit_ham_cron_ifadesi_gostermez(app):
    """Operatör '0 * * * *' okumaz; sıradaki saat gösterilir."""
    body = app.test_client().get("/").data.decode("utf-8")
    assert "0 * * * *" not in body


# --------------------------------------------------------- pencere seçici ----

def test_pencere_secici_calisir(app):
    body = app.test_client().get("/?w=7g").data.decode("utf-8")
    assert body.count("bg-claude-text text-claude-bg") == 1   # tek seçili

    body24 = app.test_client().get("/").data.decode("utf-8")
    assert "son 24 saatin üretimi" in body24


def test_gecersiz_pencere_varsayilana_duser(app):
    """Elle yazılmış querystring ekranı bozmamalı."""
    resp = app.test_client().get("/?w=uydurma")
    assert resp.status_code == 200
    assert "son 24 saatin üretimi" in resp.data.decode("utf-8")


# ----------------------------------------------------------- iş kuyruğu -----

def test_bekleyen_video_kuyrukta_gorunur(tmp_path):
    def seed(eng):
        record_short(eng, channel="demo", rss_item_guid="g1", title="Bekleyen",
                     file_path="output/demo/a.mp4", duration_s=6,
                     script_json="{}", render_ms=1)

    app = _make_app(tmp_path, seed=seed)
    body = app.test_client().get("/").data.decode("utf-8")
    assert "incelenmeyi bekliyor" in body


def test_is_yoksa_her_sey_yolunda_yazar(tmp_path):
    """Boş kuyruk, boş bir liste değil açık bir cevap olmalı."""
    app = _make_app(tmp_path)
    body = app.test_client().get("/").data.decode("utf-8")
    assert "Her şey yolunda" in body


def test_kalici_durum_kuyruga_girmez(tmp_path):
    """Kapalı kanal 'yapılacak iş' değildir — her gün aynı satırı gösteren
    liste okunmayan listedir. Kalıcı durum tabloda yaşar."""
    cfg = CHANNEL_YAML.replace("enabled: true", "enabled: false")

    def seed(eng):
        pass

    app = _make_app(tmp_path, seed=seed)
    (app.config["SHORTBOT_CONFIG_DIR"] / "channels" / "demo.yaml").write_text(
        cfg, encoding="utf-8")
    body = app.test_client().get("/").data.decode("utf-8")
    assert "Her şey yolunda" in body
    # Kuyrukta HİÇBİR madde olmamalı. Görünen metne bakmak yetmiyordu:
    # fırlatıcının tooltip'i de "kanal kapalı" yazıyor.
    assert "data-task=" not in body


def test_uretim_yapan_kapali_kanal_kuyruga_girer(tmp_path):
    """Kapalı ama elle çalıştırılmış kanal GERÇEK bir sinyal: cron'u açmak
    unutulmuş olabilir."""
    def seed(eng):
        sid = record_short(eng, channel="demo", rss_item_guid="g1", title="A",
                           file_path="output/demo/a.mp4", duration_s=6,
                           script_json="{}", render_ms=1)
        _soft_delete(eng, sid)

    app = _make_app(tmp_path, seed=seed)
    (app.config["SHORTBOT_CONFIG_DIR"] / "channels" / "demo.yaml").write_text(
        CHANNEL_YAML.replace("enabled: true", "enabled: false"), encoding="utf-8")
    body = app.test_client().get("/").data.decode("utf-8")
    assert "elle çalıştırılmış" in body


# ------------------------------------------------------- takılı koşular -----

def _stale_run(app, channel="demo"):
    """Takılı koşuyu uygulama KURULDUKTAN SONRA ekler.

    ``create_app`` açılışta ``cleanup_zombie_runs`` çağırıyor ve testte üretim
    kilidi hiç oluşmadığı için her 'running' satır oracıkta temizlenir —
    fixture içinde ekleseydik test hiçbir şeyi ölçmezdi.
    """
    eng = app.config["_ENG"]
    rid = start_run(eng, channel, trigger="cron", log_path="x.log")
    eski = _utcnow() - timedelta(minutes=STALE_RUN_MINUTES + 10)
    with eng.begin() as conn:
        conn.execute(text("UPDATE runs SET started_at = :t WHERE id = :i"),
                     {"t": eski.strftime("%Y-%m-%d %H:%M:%S.%f"), "i": rid})
    return rid


def test_takili_kosu_kuyrukta_gorunur(tmp_path):
    app = _make_app(tmp_path)
    _stale_run(app)
    body = app.test_client().get("/").data.decode("utf-8")
    assert "takılı kalmış" in body
    assert "/dashboard/close-stalled" in body


def test_takili_kosu_kapatma_endpointi(tmp_path):
    app = _make_app(tmp_path)
    _stale_run(app)
    client = app.test_client()
    assert "takılı kalmış" in client.get("/").data.decode("utf-8")

    r = client.post("/dashboard/close-stalled", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/")

    assert "takılı kalmış" not in client.get("/").data.decode("utf-8")


def test_takili_kosu_kapatma_kanal_kilidini_birakir(tmp_path):
    """Kilit ortada kalırsa kanal bir daha üretemez — temizlik onu da alır."""
    app = _make_app(tmp_path)
    _stale_run(app)
    kilit = app.config["SHORTBOT_LOCK_DIR"] / "demo.lock"
    kilit.parent.mkdir(parents=True, exist_ok=True)
    kilit.write_text("1", encoding="utf-8")

    app.test_client().post("/dashboard/close-stalled")
    assert not kilit.exists()


def test_takili_kosu_kapatma_htmx(tmp_path):
    app = _make_app(tmp_path)
    _stale_run(app)
    r = app.test_client().post("/dashboard/close-stalled",
                               headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert r.headers.get("HX-Redirect") == "/"


def test_takili_kosu_yokken_endpoint_yine_calisir(tmp_path):
    app = _make_app(tmp_path)
    r = app.test_client().post("/dashboard/close-stalled", follow_redirects=False)
    assert r.status_code == 302


# ------------------------------------------------------------- hatalar ------

def test_coken_kosu_kuyrukta_gorunur(app):
    body = app.test_client().get("/").data.decode("utf-8")
    assert "hatayla bitti" in body
    assert "patladi" in body
    assert "/dashboard/clear-errors" in body


def test_hatalari_temizle_kosulari_siler(app):
    client = app.test_client()
    assert "hatayla bitti" in client.get("/").data.decode("utf-8")

    r = client.post("/dashboard/clear-errors", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/")

    assert "hatayla bitti" not in client.get("/").data.decode("utf-8")


def test_hatalari_temizle_htmx(app):
    r = app.test_client().post("/dashboard/clear-errors",
                               headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert r.headers.get("HX-Redirect") == "/"


def test_hata_yokken_temizleme_yine_calisir(app):
    client = app.test_client()
    client.post("/dashboard/clear-errors")
    r = client.post("/dashboard/clear-errors", follow_redirects=False)
    assert r.status_code == 302


# ------------------------------------------------------ bağlantı uyarısı ----

def test_baglantisiz_kanal_uretiyorsa_uyarir(app):
    """Üretim yapıyor ama YouTube'a bağlı değil = kasada birikiyor."""
    body = app.test_client().get("/").data.decode("utf-8")
    assert "YouTube'a bağlı değil" in body


# ------------------------------------------------------- üretim listesi -----

def test_uretim_listesi_her_kanal_icin_satir_uretir(app):
    body = app.test_client().get("/").data.decode("utf-8")
    assert "Üretimi tetikle" in body
    assert 'hx-vals=\'{"slug": "demo"}\'' in body
    assert "▶ Üret" in body


def test_uretim_listesi_kanal_turunu_gosterir(app):
    """Tür RENKLE değil YAZIYLA: bu ekranda renk zaten durum anlatıyor."""
    body = app.test_client().get("/").data.decode("utf-8")
    assert "Tür ve kaynak" in body
    assert "Kart" in body          # sessiz kart formatı
    assert "RSS" in body


def test_uretim_listesi_baglantisiz_kanalda_bas_harf_gosterir(app):
    """Logo yoksa baş harf — aynı anda 'YouTube'a bağlı değil' göstergesi."""
    body = app.test_client().get("/").data.decode("utf-8")
    assert "YouTube'a bağlı değil" in body
    assert "/youtube-avatars/" not in body      # kimlik yok → avatar da yok


def test_son_uretim_bagil_zaman_gosterir(tmp_path):
    """Ham saat UTC yazılıyordu ve yerel saatmiş gibi okunuyordu."""
    def seed(eng):
        sid = record_short(eng, channel="demo", rss_item_guid="g1", title="A",
                           file_path="output/demo/a.mp4", duration_s=6,
                           script_json="{}", render_ms=1)
        _soft_delete(eng, sid)

    app = _make_app(tmp_path, seed=seed)
    body = app.test_client().get("/").data.decode("utf-8")
    assert "Son üretim" in body
    assert "önce" in body


def test_pencere_disinda_ureten_kanal_hic_uretmedi_demez(tmp_path):
    """REGRESYON: son üretim penceresinden değil, tüm geçmişten okunur."""
    def seed(eng):
        sid = record_short(eng, channel="demo", rss_item_guid="g1", title="A",
                           file_path="output/demo/a.mp4", duration_s=6,
                           script_json="{}", render_ms=1)
        eski = _utcnow() - timedelta(days=3)
        with eng.begin() as conn:
            conn.execute(text("UPDATE shorts SET created_at = :t WHERE id = :i"),
                         {"t": eski.strftime("%Y-%m-%d %H:%M:%S.%f"), "i": sid})

    app = _make_app(tmp_path, seed=seed)
    body = app.test_client().get("/").data.decode("utf-8")
    assert "3 gün önce" in body
    assert "hiç üretmedi" not in body


def test_izlenme_sutunu_olcum_yoksa_sebebini_yazar(app):
    """Boş bırakmak yerine neden hesaplanamadığını söylemeli."""
    body = app.test_client().get("/").data.decode("utf-8")
    assert "İzlenme / gün" in body
    assert "kanal bağlı değil" in body


# --------------------------------------------------------- üst menü --------

def test_ust_menude_gunluk_olmayan_baslik_yok(app):
    """Cevher/Cron/Diller çubuktan indi — ama kaybolmadı."""
    body = app.test_client().get("/").data.decode("utf-8")
    assert "Daha fazla" in body
    # Hiçbiri kaybolmadı — hepsi açılırın İÇİNDE, yani "Daha fazla"dan SONRA.
    acilir = body.index("Daha fazla")
    for baslik in ("Cevher", "Cron", "Diller", "Loglar"):
        assert baslik in body, baslik
        assert body.index(baslik) > acilir, f"{baslik} hâlâ üst çubukta"
    # Günlük kullanılanlar çubukta kaldı.
    for baslik in ("Kokpit", "Shorts", "Kanallar", "YouTube"):
        assert body.index(baslik) < acilir, f"{baslik} çubuktan düşmüş"


def test_shorts_rozeti_bekleyen_sayisini_gosterir(tmp_path):
    """Asıl iş menüden görünmeli: hangi sayfada olursan ol."""
    def seed(eng):
        record_short(eng, channel="demo", rss_item_guid="g1", title="Bekleyen",
                     file_path="output/demo/a.mp4", duration_s=6,
                     script_json="{}", render_ms=1)

    app = _make_app(tmp_path, seed=seed)
    body = app.test_client().get("/").data.decode("utf-8")
    assert "text-claude-wait" in body
    assert "Shorts" in body


# ---------------------------------------------------- kaynak / dil etiketi --

def test_kaynak_etiketi_dili_tekrarlamaz(tmp_path):
    """REGRESYON: kaynak adına bölge katılınca "Trends TR · TR" çıkıyordu."""
    from short_bot.web.routes.dashboard import _locale_label, _source_label

    class Sahte:
        content_source = "trends"
        trends_region = "TR"
        language = "tr"

    assert _source_label(Sahte()) == "Trends"
    assert _locale_label(Sahte()) == "TR"


def test_kaynak_bolgesi_dilden_farkliysa_ikisi_de_gosterilir():
    """trends_region ile language AYNI ayar değil: biri neyin çekildiğini,
    diğeri hangi dilde yazıldığını belirler."""
    from short_bot.web.routes.dashboard import _locale_label

    class Karma:
        content_source = "trends"
        trends_region = "US"
        language = "tr"

    assert _locale_label(Karma()) == "US→TR"


def test_rss_kanalinda_yalniz_dil_gosterilir():
    from short_bot.web.routes.dashboard import _locale_label, _source_label

    class Rss:
        content_source = "rss"
        trends_region = ""
        language = "es"

    assert _source_label(Rss()) == "RSS"
    assert _locale_label(Rss()) == "ES"
