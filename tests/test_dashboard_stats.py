"""Kokpit sorgu katmanı.

Buradaki testlerin çoğu TEK bir üretim hatasını kilitliyor: eski dashboard
``deleted_at IS NULL`` sayarak "üretim" ölçtüğünü sanıyordu. Operatörün akışı
üret → incele → (beğenirse yükle) → LİSTEDEN SİL olduğu için üretilen her
video eninde sonunda silinmiş işaretleniyor ve sayaçlar sıfıra düşüyordu:
ekranda 0 · 0 · 0 yazarken son 24 saatte 45 video üretilmişti.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from short_bot.dashboard_stats import (STALE_RUN_MINUTES, daily_production,
                                       empty_runs, failed_runs,
                                       hourly_production,
                                       production_by_channel,
                                       production_summary, stalled_runs,
                                       to_local)
from short_bot.db import (init_db, record_short, record_youtube_upload,
                          start_run)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def eng(tmp_path):
    return init_db(tmp_path / "x.sqlite")


def _short(eng, channel="ch", title="A", *, at=None) -> int:
    sid = record_short(eng, channel=channel, rss_item_guid=f"g-{title}-{channel}",
                       title=title, file_path=f"output/{channel}/{title}.mp4",
                       duration_s=6, script_json="{}", render_ms=1)
    if at is not None:
        with eng.begin() as conn:
            conn.execute(text("UPDATE shorts SET created_at = :t WHERE id = :i"),
                         {"t": at.strftime("%Y-%m-%d %H:%M:%S.%f"), "i": sid})
    return sid


def _soft_delete(eng, short_id):
    with eng.begin() as conn:
        conn.execute(text("UPDATE shorts SET deleted_at = :t WHERE id = :i"),
                     {"t": _utcnow().strftime("%Y-%m-%d %H:%M:%S.%f"), "i": short_id})


def _upload(eng, short_id, *, video_id="v1", status="success"):
    return record_youtube_upload(eng, short_id=short_id, video_id=video_id,
                                 status=status, error=None,
                                 video_url=f"https://y/{video_id}")


# ---------------------------------------------------------------- üretim ----

def test_uretim_silinmis_videolari_da_sayar(eng):
    """ASIL REGRESYON: silinmiş video üretilmemiş sayılmaz."""
    sid = _short(eng)
    _soft_delete(eng, sid)

    s = production_summary(eng, hours=24)
    assert s.produced == 1


def test_yuklenip_silinen_video_yayina_gitmis_sayilir(eng):
    """Operatörün akışı: beğendiğini YÜKLER, sonra listeden siler."""
    sid = _short(eng)
    _upload(eng, sid)
    _soft_delete(eng, sid)

    s = production_summary(eng, hours=24)
    assert (s.produced, s.uploaded, s.dropped, s.pending) == (1, 1, 0, 0)


def test_yuklenmeden_silinen_video_elenmis_sayilir(eng):
    sid = _short(eng)
    _soft_delete(eng, sid)

    s = production_summary(eng, hours=24)
    assert (s.uploaded, s.dropped, s.pending) == (0, 1, 0)


def test_silinmemis_video_bekliyor_sayilir(eng):
    """Henüz karar verilmemiş video ne kabul ne ret — kendi kovasında."""
    _short(eng)

    s = production_summary(eng, hours=24)
    assert (s.uploaded, s.dropped, s.pending) == (0, 0, 1)


def test_ayni_video_iki_yukleme_satiriyla_bir_kez_sayilir(eng):
    """Başarısız deneme + yeniden yükleme aynı videoyu iki kez saydırmamalı.

    Üretimde ölçüldü: 9 short'un iki yükleme satırı var. DISTINCT olmadan
    outer join videoyu çoğaltıyor ve üretilenden fazla "yüklendi" çıkıyor.
    """
    sid = _short(eng)
    _upload(eng, sid, video_id="v1", status="failed")
    _upload(eng, sid, video_id="v1")
    _upload(eng, sid, video_id="v1")

    s = production_summary(eng, hours=24)
    assert s.produced == 1
    assert s.uploaded == 1
    assert s.dropped == 0


def test_basarisiz_yukleme_yayina_gitti_saymaz(eng):
    sid = _short(eng)
    _upload(eng, sid, status="failed")
    _soft_delete(eng, sid)

    s = production_summary(eng, hours=24)
    assert s.uploaded == 0
    assert s.dropped == 1


def test_kabul_orani_paydaya_bekleyenleri_katmaz(eng):
    """Bekleyen video oranı sahte biçimde düşürmemeli."""
    yuklenen = _short(eng, title="A")
    _upload(eng, yuklenen)
    _soft_delete(eng, yuklenen)
    elenen = _short(eng, title="B")
    _soft_delete(eng, elenen)
    _short(eng, title="C")   # bekliyor — paydaya girmemeli

    s = production_summary(eng, hours=24)
    assert s.pending == 1
    assert s.accept_rate == pytest.approx(0.5)


def test_kabul_orani_karar_yoksa_none(eng):
    _short(eng)
    assert production_summary(eng, hours=24).accept_rate is None


def test_pencere_disindaki_uretim_sayilmaz(eng):
    _short(eng, title="eski", at=_utcnow() - timedelta(hours=48))
    _short(eng, title="yeni")

    assert production_summary(eng, hours=24).produced == 1
    assert production_summary(eng, hours=72).produced == 2


def test_kanal_kirilimi_coktan_aza_siralanir(eng):
    for i in range(3):
        _short(eng, channel="cok", title=f"c{i}")
    _short(eng, channel="az", title="a0")

    kanallar = production_by_channel(eng, hours=24)
    assert [c.slug for c in kanallar] == ["cok", "az"]
    assert kanallar[0].produced == 3


# ---------------------------------------------------------------- sağlık ----

def test_takili_kosu_esigin_altinda_sayilmaz(eng):
    """Az önce başlamış bir koşu gerçekten çalışıyor olabilir."""
    start_run(eng, "ch", trigger="cron", log_path="x.log")
    assert stalled_runs(eng) == []


def test_takili_kosu_esigin_ustunde_yakalanir(eng):
    rid = start_run(eng, "ch", trigger="cron", log_path="x.log")
    eski = _utcnow() - timedelta(minutes=STALE_RUN_MINUTES + 10)
    with eng.begin() as conn:
        conn.execute(text("UPDATE runs SET started_at = :t WHERE id = :i"),
                     {"t": eski.strftime("%Y-%m-%d %H:%M:%S.%f"), "i": rid})

    takili = stalled_runs(eng)
    assert len(takili) == 1
    assert takili[0].channel == "ch"


def test_takili_kosu_temizlendikten_sonra_gorunmez(eng, tmp_path):
    """Temizliği bu modül YAPMAZ, ``db.cleanup_zombie_runs``a devreder.

    Ayrı bir uygulama yazmak yanlış olurdu: oradaki ölçüt yaş değil CANLILIK
    (üretim kilidi sahipsizse koşu kaç dakikalık olursa olsun ölmüştür) ve
    kilidi de o siliyor. Burada yalnızca dedektörün temizlik sonrası sustuğu
    doğrulanır.
    """
    from short_bot.db import cleanup_zombie_runs

    rid = start_run(eng, "ch", trigger="cron", log_path="x.log")
    eski = _utcnow() - timedelta(minutes=STALE_RUN_MINUTES + 10)
    with eng.begin() as conn:
        conn.execute(text("UPDATE runs SET started_at = :t WHERE id = :i"),
                     {"t": eski.strftime("%Y-%m-%d %H:%M:%S.%f"), "i": rid})
    assert len(stalled_runs(eng)) == 1

    assert cleanup_zombie_runs(eng, tmp_path / "locks",
                               age_minutes=STALE_RUN_MINUTES) == 1
    assert stalled_runs(eng) == []

    # Satır silinmez; hata olarak işaretlenir ve hata paneline düşer.
    assert failed_runs(eng, hours=24)[0]["channel"] == "ch"


def test_bos_donen_kosular_hata_degil_ama_raporlanir(eng):
    """'no_candidates' failed değildir — eski ekranda hiç görünmüyordu."""
    from short_bot.db import finish_run
    for _ in range(2):
        rid = start_run(eng, "bos", trigger="cron", log_path="x.log")
        finish_run(eng, rid, status="no_candidates", short_id=None)
    rid = start_run(eng, "iyi", trigger="cron", log_path="x.log")
    finish_run(eng, rid, status="success", short_id=None)

    assert empty_runs(eng, days=7) == [("bos", 2)]
    assert failed_runs(eng, hours=24) == []


def test_coken_kosular_hata_metniyle_doner(eng):
    from short_bot.db import finish_run
    rid = start_run(eng, "ch", trigger="cron", log_path="x.log")
    finish_run(eng, rid, status="failed", short_id=None, error="patladi")

    hatalar = failed_runs(eng, hours=24)
    assert len(hatalar) == 1
    assert hatalar[0]["error"] == "patladi"
    assert hatalar[0]["channel"] == "ch"


# ------------------------------------------------------------ zaman serisi --

def test_saat_seridi_bos_saatleri_de_icerir(eng):
    """Şerit gerçek bir zaman ekseni olmalı — üretimsiz saatler atlanmamalı."""
    _short(eng)
    kovalar = hourly_production(eng, hours=24)
    assert len(kovalar) == 25          # 24 saat + içinde bulunulan saat
    assert sum(k["produced"] for k in kovalar) == 1


def test_saat_seridi_yerel_saate_cevirir(eng):
    """Damgalar UTC tutuluyor; kullanıcı kendi saatini görmeli."""
    sid = _short(eng)
    with eng.connect() as conn:
        ham = conn.execute(text("SELECT created_at FROM shorts WHERE id = :i"),
                           {"i": sid}).scalar()
    utc = datetime.strptime(str(ham), "%Y-%m-%d %H:%M:%S.%f")
    beklenen = to_local(utc).hour

    dolu = [k for k in hourly_production(eng, hours=24) if k["produced"]]
    assert dolu[0]["hour"] == beklenen


def test_gunluk_seri_istenen_gun_sayisinda(eng):
    _short(eng)
    seri = daily_production(eng, days=7)
    assert len(seri["ch"]) == 7
    assert seri["ch"][-1] == 1          # bugün en sonda


def test_to_local_naive_ve_aware_girdiyi_kabul_eder(eng):
    naive = datetime(2026, 8, 20, 12, 0, 0)
    aware = naive.replace(tzinfo=timezone.utc)
    assert to_local(naive) == to_local(aware)
    assert to_local(None) is None


# --------------------------------------------------- izlenme / son üretim ---

def _snapshot(eng, channel, tarih, views, subs=100):
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO youtube_channel_stats "
            "(channel, snapshot_date, subscribers, total_views, updated_at) "
            "VALUES (:c, :d, :s, :v, :u)"),
            {"c": channel, "d": tarih, "s": subs, "v": views,
             "u": _utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")})


def test_izlenme_gunluk_ortalamaya_bolunur(eng):
    """Anlık görüntüler her gün alınmıyor; iki günlük artış ikiye bölünmeli.

    Bu yüzden sütun "son 24 saat" DEĞİL "günlük ortalama" diye yazılıyor.
    """
    from datetime import date, timedelta as td
    from short_bot.dashboard_stats import channel_view_rate
    bugun = date.today()
    _snapshot(eng, "ch", (bugun - td(days=2)).isoformat(), 1_000_000)
    _snapshot(eng, "ch", bugun.isoformat(), 1_200_000)

    oran = channel_view_rate(eng)["ch"]
    assert oran.per_day == 100_000
    assert "2 günde" in oran.note
    assert oran.stale is False


def test_izlenme_tek_olcumle_hesaplanamaz(eng):
    from datetime import date
    from short_bot.dashboard_stats import channel_view_rate
    _snapshot(eng, "ch", date.today().isoformat(), 500)

    oran = channel_view_rate(eng)["ch"]
    assert oran.per_day is None
    assert "tek ölçüm" in oran.note


def test_izlenme_eski_olcum_isaretlenir(eng):
    """Sayı gösterilir ama güncel sanılmasın diye 'eski' bayrağı kalkar."""
    from datetime import date, timedelta as td
    from short_bot.dashboard_stats import channel_view_rate
    eski_gun = date.today() - td(days=20)
    _snapshot(eng, "ch", (eski_gun - td(days=1)).isoformat(), 100)
    _snapshot(eng, "ch", eski_gun.isoformat(), 200)

    oran = channel_view_rate(eng)["ch"]
    assert oran.per_day == 100
    assert oran.stale is True
    assert "ölçüm yok" in oran.note


def test_izlenme_hic_kaydi_olmayan_kanal_sozlukte_yok(eng):
    """Route bunu 'istatistik hiç toplanmamış' diye dolduruyor."""
    from short_bot.dashboard_stats import channel_view_rate
    assert channel_view_rate(eng) == {}


def test_son_uretim_pencereden_bagimsiz(eng):
    """24 saatte üretmemiş kanal 'hiç üretmedi' GÖRÜNMEMELİ.

    Son üretimin işi zaten pencerenin dışını göstermek: bir kanalın sustuğunu
    ancak böyle fark edersin.
    """
    from short_bot.dashboard_stats import last_production, relative_time
    _short(eng, channel="eski", title="x", at=_utcnow() - timedelta(days=3))

    son = last_production(eng)
    assert "eski" in son
    assert relative_time(son["eski"]) == "3 gün önce"

    # Pencere içi özet onu hiç görmüyor — iki ölçü ayrı.
    assert production_summary(eng, hours=24).produced == 0


def test_bagil_zaman_esikleri(eng):
    from short_bot.dashboard_stats import relative_time
    simdi = to_local(_utcnow())
    assert relative_time(_utcnow() - timedelta(minutes=5)) == "5 dk önce"
    assert relative_time(_utcnow() - timedelta(minutes=95)) == "1 sa önce"
    assert relative_time(_utcnow() - timedelta(days=2, hours=3)) == "2 gün önce"
    assert relative_time(None) == "hiç üretmedi"
