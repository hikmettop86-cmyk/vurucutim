"""Otomasyon paneli.

Görünmeyen bir otomasyon, güvenilemeyen bir otomasyondur. Üstelik otomasyon açıkken
kanalın cron'u KAPANIYOR — kullanıcı "neden üretmiyor?" diye sorduğunda bakabileceği
tek yer burası.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from short_bot.db import init_db, plan_slots, slot_set_status, slots_for_date
from short_bot.web import create_app

UTC = timezone.utc

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
reel:
  enabled: true
  voice_id: v1
  series_enabled: true
  series_title: Seri
"""
_ACIK = _CH + "autopilot:\n  enabled: true\n  daily_count: 2\n"


def _app(tmp_path, yaml_text=_CH):
    cfg = tmp_path / "config"
    (cfg / "channels").mkdir(parents=True, exist_ok=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8")
    (cfg / "channels" / "k.yaml").write_text(yaml_text, encoding="utf-8")
    db = tmp_path / "db.sqlite"
    init_db(db)
    app = create_app(config_dir=cfg, db_path=db, templates_dir=tmp_path / "t",
                     music_root=tmp_path, cache_dir=tmp_path, lock_dir=tmp_path,
                     logs_dir=tmp_path, output_root=tmp_path,
                     secrets_path=tmp_path / "s.yaml", scheduler=False)
    return app, db


def _bugun():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Europe/Istanbul")).date().isoformat()


# --- AÇ / KAPAT ------------------------------------------------------------

def test_kapaliyken_ACIKLAMA_ve_ACMA_dugmesi(tmp_path):
    a, _ = _app(tmp_path)
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "Otomasyon kapalı" in body
    assert "/autopilot/enable" in body
    assert "insan gibi gezinir" in body, "kullanıcı NEDEN açması gerektiğini anlamalı"
    assert "çifte üretim" in body, "cron'un kapanacağı söylenmeli"


def test_ACMA_dugmesi_YAMLa_yazar(tmp_path):
    from short_bot.config import load_channel
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/k/autopilot/enable")
    assert r.status_code in (200, 302)
    cfg = load_channel(a.config["SHORTBOT_CONFIG_DIR"] / "channels" / "k.yaml")
    assert cfg.autopilot is not None and cfg.autopilot.enabled is True
    assert cfg.autopilot.daily_count == 3           # varsayılan


# ---------------------------------------------------------------------------
# SLOTLAR HEMEN PLANLANMALI.
#
# GERÇEK HATA (gerçek kanalda ölçüldü): planlama YALNIZ uygulama açılışında ve gece
# 03:30'da koşuyordu. Kullanıcı otomasyonu açtı, ayarları kaydetti — ve panel 0 slot
# gösterdi. "Birkaç dakika içinde planlanacak" diyordu ama YALANDI: 5 dakikalık tick
# üretim yapıyor, PLANLAMA YAPMIYORDU. Sabah 03:30'a kadar hiçbir şey olmayacaktı.
# ---------------------------------------------------------------------------

def test_ACINCA_slotlar_HEMEN_planlanir(tmp_path):
    from short_bot.db import slots_in_range
    a, db = _app(tmp_path)
    a.test_client().post("/channels/k/autopilot/enable")
    s = slots_in_range(init_db(db), "k", "2000-01-01", "2999-12-31")
    assert len(s) >= 3, "otomasyon açıldı ama slot yazılmadı → kullanıcı boş sayfa görür"


def test_KANAL_etkinlesince_slotlar_HEMEN_planlanir(tmp_path):
    """Kanal kapalıyken planlama HİÇ koşmuyor — açılır açılmaz koşmalı."""
    from short_bot.db import slots_in_range
    a, db = _app(tmp_path, _ACIK.replace("enabled: true\ncontent_source",
                                         "enabled: false\ncontent_source"))
    assert slots_in_range(init_db(db), "k", "2000-01-01", "2999-12-31") == []

    a.test_client().post("/channels/k/autopilot/enable-channel")
    s = slots_in_range(init_db(db), "k", "2000-01-01", "2999-12-31")
    assert len(s) >= 2, "kanal etkinleşti ama slot yazılmadı"


def test_AYAR_kaydedilince_slotlar_HEMEN_yeniden_planlanir(tmp_path):
    from short_bot.db import slots_for_date
    a, db = _app(tmp_path, _ACIK)
    a.test_client().post("/channels/k/autopilot/enable")

    a.test_client().post("/channels/k/autopilot/settings", data={
        "daily_count": "4", "series_per_day": "1", "active_lo": "10",
        "active_hi": "22", "produce_lead_hours": "1", "jitter_minutes": "15",
        "publish_mode": "publish_at"})

    s = slots_for_date(init_db(db), "k", _bugun())
    assert len(s) == 4, f"yeni ayara göre 4 slot beklenirdi, {len(s)} var"
    assert s[0]["kind"] == "series"
    assert [x["kind"] for x in s[1:]] == ["standalone"] * 3


def test_KAPATMA_dugmesi(tmp_path):
    from short_bot.config import load_channel
    a, _ = _app(tmp_path, _ACIK)
    a.test_client().post("/channels/k/autopilot/disable")
    cfg = load_channel(a.config["SHORTBOT_CONFIG_DIR"] / "channels" / "k.yaml")
    assert cfg.autopilot.enabled is False
    assert cfg.autopilot.daily_count == 2, "kapatmak öteki ayarları SIFIRLAMAMALI"


# --- SLOTLAR ---------------------------------------------------------------

def test_slotlar_SAATLERIYLE_gorunur(tmp_path):
    a, db = _app(tmp_path, _ACIK)
    eng = init_db(db)
    plan_slots(eng, "k", _bugun(), [
        {"slot_index": 0, "slot_at_utc": datetime.now(UTC) + timedelta(hours=2),
         "jitter_min": 3}])
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "planlandı" in body


def test_BASARISIZ_slot_ve_HATASI_gorunur(tmp_path):
    """Hata metni gizlenirse kullanıcı neden üretilmediğini asla öğrenemez."""
    a, db = _app(tmp_path, _ACIK)
    eng = init_db(db)
    plan_slots(eng, "k", _bugun(), [
        {"slot_index": 0, "slot_at_utc": datetime.now(UTC), "jitter_min": 0}])
    sid = slots_for_date(eng, "k", _bugun())[0]["id"]
    slot_set_status(eng, sid, "failed", error="ai33 preflight basarisiz")

    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "başarısız" in body
    assert "ai33 preflight basarisiz" in body, "hata metni gizlenmemeli"


def test_OZET_sayilari_dogru(tmp_path):
    a, db = _app(tmp_path, _ACIK)
    eng = init_db(db)
    g = _bugun()
    plan_slots(eng, "k", g, [
        {"slot_index": i, "slot_at_utc": datetime.now(UTC) + timedelta(hours=i),
         "jitter_min": 0} for i in range(3)])
    s = slots_for_date(eng, "k", g)
    slot_set_status(eng, s[0]["id"], "published")
    slot_set_status(eng, s[1]["id"], "scheduled")
    slot_set_status(eng, s[2]["id"], "failed", error="x")

    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "Yayında" in body and "Zamanlandı" in body and "Başarısız" in body


def test_slot_yoksa_aciklama(tmp_path):
    a, _ = _app(tmp_path, _ACIK)
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "Slot yok" in body


def test_kanal_kapaliyken_bos_durum_UYARIYLA_CELISMEZ(tmp_path):
    """"Planlayıcı birkaç dakika içinde yazacak" demek YALAN olurdu: asla yazmayacak."""
    a, _ = _app(tmp_path, _ACIK.replace("enabled: true\ncontent_source",
                                        "enabled: false\ncontent_source"))
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "Kanal devre dışı — slot planlanmıyor" in body
    assert "birkaç dakika içinde yazacak" not in body


# --- BAĞLANTILAR -----------------------------------------------------------

def test_kanal_kartinda_otomasyon_baglantisi(tmp_path):
    """Otomasyon KAPALIYKEN de görünmeli — yoksa keşfedilemez (seri düğmesindeki
    kısır döngünün aynısı)."""
    a, _ = _app(tmp_path)
    body = a.test_client().get("/channels").data.decode("utf-8")
    assert "/autopilot" in body


def test_seri_sayfasinda_SIMDI_URET_dugmesi(tmp_path):
    """Kullanıcının şikâyeti: 'üret diye bir buton yok'."""
    a, _ = _app(tmp_path)
    body = a.test_client().get("/channels/k/series").data.decode("utf-8")
    assert "/series/produce-now" in body
    assert "Şimdi üret" in body


def test_SIMDI_URET_pipeline_i_baslatir(tmp_path, monkeypatch):
    import short_bot.web.runs as R
    cagrildi = []
    monkeypatch.setattr(R, "launch_pipeline",
                        lambda **kw: cagrildi.append(kw["channel"].slug))
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/k/series/produce-now")
    assert r.status_code in (200, 302)
    assert cagrildi == ["k"]


def test_olmayan_kanal_404(tmp_path):
    a, _ = _app(tmp_path)
    assert a.test_client().get("/channels/yok/autopilot").status_code == 404


# ---------------------------------------------------------------------------
# AYARLAR — otomasyonu İZLEDİĞİN yerde.
# Kullanıcı şikâyeti: "günde kaç video yükleneceği ayarı arayüzde yok".
# ---------------------------------------------------------------------------

def test_ayar_formu_GUNDE_KAC_VIDEO_iceriyor(tmp_path):
    a, _ = _app(tmp_path, _ACIK)
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "/autopilot/settings" in body
    assert 'name="daily_count"' in body
    assert 'name="series_per_day"' in body
    assert 'name="active_lo"' in body and 'name="active_hi"' in body
    assert 'name="produce_lead_hours"' in body
    assert 'name="publish_mode"' in body


def test_ayar_formu_SERI_KURALINI_aciklar(tmp_path):
    """Kullanıcı 1'i neden bırakması gerektiğini anlamalı."""
    a, _ = _app(tmp_path, _ACIK)
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "#2 yarın" in body
    assert "bir günde biter" in body


def test_ayarlar_YAMLa_yazilir(tmp_path):
    from short_bot.config import load_channel
    a, _ = _app(tmp_path, _ACIK)
    r = a.test_client().post("/channels/k/autopilot/settings", data={
        "daily_count": "4", "series_per_day": "1",
        "active_lo": "9", "active_hi": "23",
        "produce_lead_hours": "2", "jitter_minutes": "20",
        "publish_mode": "live_upload"})
    assert r.status_code in (200, 302)
    cfg = load_channel(a.config["SHORTBOT_CONFIG_DIR"] / "channels" / "k.yaml")
    assert cfg.autopilot.daily_count == 4
    assert cfg.autopilot.active_hours == (9, 23)
    assert cfg.autopilot.produce_lead_hours == 2
    assert cfg.autopilot.jitter_minutes == 20
    assert cfg.autopilot.publish_mode == "live_upload"
    assert cfg.autopilot.enabled is True, "kaydetmek otomasyonu KAPATMAMALI"


def test_gecersiz_ayar_REDDEDILIR(tmp_path):
    """12 slot / 2 saat → slotlar 10 dk arayla. Sessizce kabul edilirse plan bozulur."""
    from short_bot.config import load_channel
    a, _ = _app(tmp_path, _ACIK)
    a.test_client().post("/channels/k/autopilot/settings", data={
        "daily_count": "12", "series_per_day": "1",
        "active_lo": "10", "active_hi": "12",
        "produce_lead_hours": "1", "jitter_minutes": "15",
        "publish_mode": "publish_at"})
    cfg = load_channel(a.config["SHORTBOT_CONFIG_DIR"] / "channels" / "k.yaml")
    assert cfg.autopilot.daily_count == 2, "geçersiz ayar YAML'a yazıldı"


def test_ayar_degisince_ESKI_planli_slotlar_YASAMAZ(tmp_path):
    """Eski ayara göre yazılmış slotlar kalırsa yeni ayar günlerce devreye girmez."""
    from short_bot.db import plan_slots, slots_for_date
    a, db = _app(tmp_path, _ACIK)
    eng = init_db(db)
    g = _bugun()
    eski_saat = datetime.now(UTC) + timedelta(hours=6)
    plan_slots(eng, "k", g, [
        {"slot_index": 0, "slot_at_utc": eski_saat, "jitter_min": 99,
         "kind": "standalone"}])

    a.test_client().post("/channels/k/autopilot/settings", data={
        "daily_count": "4", "series_per_day": "1", "active_lo": "10",
        "active_hi": "22", "produce_lead_hours": "1", "jitter_minutes": "15",
        "publish_mode": "publish_at"})

    s = slots_for_date(eng, "k", g)
    assert len(s) == 4, "yeni ayara göre yeniden planlanmadı"
    assert all(x["jitter_min"] != 99 for x in s), "eski slot hayatta kaldı"
    assert s[0]["kind"] == "series", "seri slotu yeni ayara göre işaretlenmedi"


def test_URETILMIS_slot_ayar_degisince_SILINMEZ(tmp_path):
    """Gerçekleşmiş olayların kaydı — silmek geçmişi yeniden yazmak olurdu."""
    from short_bot.db import (plan_slots, record_short, slot_set_status,
                              slots_for_date)
    a, db = _app(tmp_path, _ACIK)
    eng = init_db(db)
    g = _bugun()
    plan_slots(eng, "k", g, [
        {"slot_index": 0, "slot_at_utc": datetime.now(UTC), "jitter_min": 0,
         "kind": "series"},
        {"slot_index": 1, "slot_at_utc": datetime.now(UTC) + timedelta(hours=3),
         "jitter_min": 0, "kind": "standalone"}])
    sid = record_short(eng, channel="k", rss_item_guid=None, title="T",
                       file_path="v.mp4", duration_s=40, script_json="{}",
                       render_ms=1)
    s = slots_for_date(eng, "k", g)
    slot_set_status(eng, s[0]["id"], "published", short_id=sid)

    a.test_client().post("/channels/k/autopilot/settings", data={
        "daily_count": "4", "series_per_day": "1", "active_lo": "10",
        "active_hi": "22", "produce_lead_hours": "1", "jitter_minutes": "15",
        "publish_mode": "publish_at"})

    kalan = slots_for_date(eng, "k", g)
    # Üretilmiş slot AYNEN durur; kalanlar yeni ayara göre yeniden yazılır.
    uretilmis = [x for x in kalan if x["status"] == "published"]
    assert len(uretilmis) == 1, "üretilmiş slot silindi → geçmiş yeniden yazıldı"
    assert uretilmis[0]["short_id"] == sid
    assert len(kalan) == 4, "kalan slotlar yeni ayara göre planlanmadı"


def test_slot_TURU_panelde_gorunur(tmp_path):
    """Hangi slot seri bölümü, hangisi bağımsız — takip bunun üstüne kuruluyor."""
    from short_bot.db import plan_slots
    a, db = _app(tmp_path, _ACIK)
    eng = init_db(db)
    g = _bugun()
    plan_slots(eng, "k", g, [
        {"slot_index": 0, "slot_at_utc": datetime.now(UTC) + timedelta(hours=1),
         "jitter_min": 0, "kind": "series"},
        {"slot_index": 1, "slot_at_utc": datetime.now(UTC) + timedelta(hours=4),
         "jitter_min": 0, "kind": "standalone"}])
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "SERİ BÖLÜMÜ" in body
    assert "bağımsız konu" in body


# --- SESSİZ BOZULMA UYARILARI ----------------------------------------------
# İkisi de gerçek: otomasyon "açık" görünür ama hiçbir şey olmaz ve kullanıcı
# nedenini asla öğrenemez. Uçtan uca doğrulamada bulundu.

_KAPALI_KANAL = _ACIK.replace("enabled: true\ncontent_source",
                              "enabled: false\ncontent_source")


def test_KANAL_DEVRE_DISIYSA_uyarir(tmp_path):
    """Otomasyon açık ama kanal enabled:false → hiçbir slot planlanmaz.
    Panel bunu SÖYLEMEZSE kullanıcı günlerce bekler."""
    a, _ = _app(tmp_path, _KAPALI_KANAL)
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "DEVRE DIŞI" in body
    assert "hiçbir slot planlanmayacak" in body


def test_uyari_COZUM_DUGMESI_tasir(tmp_path):
    """SÖYLEMEK YETMEZ. 'Ayarlar'dan etkinleştir' demek kullanıcıyı başka sayfaya
    yollamaktır; sorunu gösteren sayfa çözümü de sunmalı."""
    a, _ = _app(tmp_path, _KAPALI_KANAL)
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "/autopilot/enable-channel" in body
    assert "Kanalı etkinleştir" in body


def test_cozum_dugmesi_NE_OLACAGINI_soyler(tmp_path):
    """Bu düğmeye basınca GERÇEKTEN üretim ve YouTube yüklemesi başlar — kredi ve
    kota harcanır. Kullanıcı ne olacağını önceden bilmeli."""
    a, _ = _app(tmp_path, _KAPALI_KANAL + "youtube:\n  auto_upload: true\n")
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "yayınlanacak" in body
    assert "kota" in body or "kredisi" in body


def test_KANALI_ETKINLESTIR_dugmesi_YAMLa_yazar(tmp_path):
    from short_bot.config import load_channel
    a, _ = _app(tmp_path, _KAPALI_KANAL)
    r = a.test_client().post("/channels/k/autopilot/enable-channel")
    assert r.status_code in (200, 302)
    cfg = load_channel(a.config["SHORTBOT_CONFIG_DIR"] / "channels" / "k.yaml")
    assert cfg.enabled is True
    assert cfg.autopilot.enabled is True, "otomasyon ayarı KORUNMALI"


def test_AUTO_UPLOAD_KAPALIYSA_uyarir_ve_ACMA_dugmesi(tmp_path):
    """Videolar üretilir ama yüklenmez — kullanıcı bunu önceden bilmeli."""
    a, _ = _app(tmp_path, _ACIK + "youtube:\n  auto_upload: false\n")
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "yükleme KAPALI" in body
    assert "elle yüklersin" in body
    assert "/autopilot/enable-upload" in body


def test_YUKLEMEYI_AC_dugmesi_YAMLa_yazar(tmp_path):
    from short_bot.config import load_channel
    a, _ = _app(tmp_path, _ACIK + "youtube:\n  auto_upload: false\n")
    a.test_client().post("/channels/k/autopilot/enable-upload")
    cfg = load_channel(a.config["SHORTBOT_CONFIG_DIR"] / "channels" / "k.yaml")
    assert cfg.youtube.auto_upload is True


def test_youtube_blogu_yokken_de_yukleme_acilabilir(tmp_path):
    from short_bot.config import load_channel
    a, _ = _app(tmp_path, _ACIK)          # youtube bloğu YOK
    a.test_client().post("/channels/k/autopilot/enable-upload")
    cfg = load_channel(a.config["SHORTBOT_CONFIG_DIR"] / "channels" / "k.yaml")
    assert cfg.youtube is not None and cfg.youtube.auto_upload is True


def _banka_doldur(db, n):
    from short_bot.db import insert_bank_topics
    insert_bank_topics(init_db(db), "k", [
        {"topic": f"Kanıtlanmış konu {i}", "source_title": f"V{i}",
         "views": 1, "subs": 1} for i in range(n)])


def test_KONU_BANKASI_KURUYORSA_uyarir(tmp_path):
    """ÜÇÜNCÜ sessiz bozulma: otomasyon açık, kanal açık, yükleme açık — ama konu
    bankası boş. Üretim DURMAZ, sessizce BOZULUR: seri durur (ark için tohum yok),
    bağımsız videolar kanıtlanmış konu olmadan üretilir.

    ÖLÇÜLDÜ: banka haftada 11-15 konu kuruyor; 22 konu ~9 günde bitiyor."""
    from short_bot.topic_autofill import LOW_WATER
    a, db = _app(tmp_path, _ACIK + "youtube:\n  auto_upload: true\n")
    _banka_doldur(db, LOW_WATER - 1)
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "KONU BANKASI AZALDI" in body
    assert f"{LOW_WATER - 1} aktif konu" in body
    assert "REFERANS KANAL" in body
    assert "/topic-bank/refresh" in body, "uyarı çözüm düğmesi taşımıyor"


def test_banka_DOLUYSA_banka_uyarisi_YOK(tmp_path):
    from short_bot.topic_autofill import LOW_WATER
    a, db = _app(tmp_path, _ACIK + "youtube:\n  auto_upload: true\n")
    _banka_doldur(db, LOW_WATER + 5)
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "KONU BANKASI AZALDI" not in body


def test_her_sey_yolundaysa_UYARI_YOK(tmp_path):
    from short_bot.topic_autofill import LOW_WATER
    a, db = _app(tmp_path, _ACIK + "youtube:\n  auto_upload: true\n")
    _banka_doldur(db, LOW_WATER + 5)
    body = a.test_client().get("/channels/k/autopilot").data.decode("utf-8")
    assert "DEVRE DIŞI" not in body
    assert "yükleme KAPALI" not in body
    assert "KONU BANKASI AZALDI" not in body
    assert "/autopilot/enable-channel" not in body
