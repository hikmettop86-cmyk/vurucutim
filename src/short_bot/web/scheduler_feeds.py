"""RSS Havuzu'nun saatlik arka plan tazelemesi (APScheduler).

NEDEN VAR: kaynaklar yalnız operatör 'Yenile'ye bastığında çekiliyordu. Ölçüldü
(2026-08-24, kayıtlı 8 kaynak): Mynet 21 Temmuz'dan beri hiç çekilmemişti,
FOTOMAÇ beslemelerinin 24 saat içinde tek haberi yoktu. Yani panel açıldığında
liste çoğu zaman bayattı ve tazelemenin bedeli (RSS + görsel indirme) operatörün
beklediği saniyelere biniyordu.

Arka plan tazelemesi bunu tersine çevirir: bedel burada ödenir, panel cache'ten
anında açılır.

DERİN GÖRSEL ÇÖZÜMÜ yalnız burada açıktır. Google News RSS'i görsel taşımıyor ve
gerçek yayıncı adresine ulaşmak Playwright istiyor — ÖLÇÜLDÜ 5-7 sn/haber. Panel
isteğinde bu imkânsız (110 haberlik kaynak = 12 dakika), saatte bir arka planda
ise sorun değil.
"""
import logging

from short_bot.db import init_db, list_feeds, set_feed_meta

_log = logging.getLogger("short_bot.web.scheduler_feeds")

# Bir turda derin çözülecek EN FAZLA kaynak sayısı değil, kaynak BAŞINA süre
# tavanı yok: derin çözüm haber başına 5-7 sn ve kaynaklar sırayla işleniyor.
# Tur, bir sonraki saatlik tetiklemeye taşarsa APScheduler aynı işi üst üste
# başlatmasın diye job `max_instances=1` ile kurulur (bkz. init_feed_scheduler).


def refresh_all_feeds(*, app, derin: bool = True) -> None:
    """Açık tüm kaynakları sırayla tazele. Kaynak hatası turu durdurmaz.

    `app` alınır çünkü tazeleme yolu (çeviri sağlayıcısı, ayarlar, secrets)
    Flask uygulama bağlamına bağlı; iş parçacığı kendi bağlamını açar.
    """
    with app.app_context():
        from short_bot.web.routes.feeds import tazele
        eng = init_db(app.config["SHORTBOT_DB_PATH"])
        try:
            feeds = list_feeds(eng, enabled_only=True)
        except Exception:
            _log.exception("[RSS] kaynak listesi alınamadı")
            return
        for f in feeds:
            try:
                rows = tazele(eng, f, derin=derin)
                gorselli = sum(1 for r in rows if r.get("image"))
                _log.info("[RSS] %s: %d haber, %d görsel",
                          f.title or f.url, len(rows), gorselli)
            except Exception as e:  # noqa: BLE001 — bir kaynak turu durdurmaz
                # Hata KAYDEDİLİR ki panelde '⚠ çekilemedi' rozeti çıksın;
                # eldeki cache korunur (tazele cache'e ancak başarıda yazar).
                set_feed_meta(eng, f.id, last_error=str(e))
                _log.warning("[RSS] %s tazelenemedi: %s", f.title or f.url, e)


def init_feed_scheduler(app):
    """Saat başı tazeleme işini kur."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        refresh_all_feeds,
        CronTrigger(minute=5),      # saat başını üretim cron'larına bırak
        kwargs={"app": app},
        id="rss-hourly",
        replace_existing=True,
        # Derin çözüm yavaş: bir tur bir saati aşarsa ikinci tur BAŞLAMAMALI,
        # yoksa aynı kaynaklar üst üste çekilir ve Playwright örnekleri birikir.
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler
