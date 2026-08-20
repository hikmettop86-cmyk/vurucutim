"""Blueprint registration."""
from flask import Flask


def register_blueprints(app: Flask) -> None:
    # RSS görüntüleyici / Trendler / İçgörüler SAYFALARI kaldırıldı (kullanılmıyordu).
    # Hesap tarafı DURUYOR: trends.aggregator trend_boost skorlamasını, learning
    # .aggregator ise generator prompt'una giren channel_insights'ı besler; ikisi de
    # scheduler.py'deki cron'lardan çalışır. Feed havuzu (/feeds) de durur — klasik
    # RSS kanalları (galatasaray, fenerbahce) oradan beslenir.
    from short_bot.web.routes import (
        dashboard, shorts, channels,
        channel_new, channel_edit, preview, logs, settings,
        generator_test, system, youtube, youtube_stats, youtube_overview,
        activity, community, feeds, reel_new, reel_edit,
        topic_bank, series, autopilot, lang_packs,
        curated, cartesia_api, yorum, gundem,
    )
    # Kanal formatı TEK yerden: liste parçaları düzenle bağlantısını ve rozeti
    # buradan alır (formats.channel_format) — if-zinciri kopyalanmasın.
    from short_bot.formats import FORMAT_LABELS, channel_format, edit_path
    app.jinja_env.globals.update(channel_format=channel_format, edit_path=edit_path,
                                 FORMAT_LABELS=FORMAT_LABELS)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(shorts.bp)
    app.register_blueprint(feeds.bp)
    app.register_blueprint(channels.bp)
    app.register_blueprint(channel_new.bp)
    app.register_blueprint(reel_new.bp)
    app.register_blueprint(reel_edit.bp)
    app.register_blueprint(channel_edit.bp)
    app.register_blueprint(preview.bp)
    app.register_blueprint(logs.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(generator_test.bp)
    app.register_blueprint(system.bp)
    app.register_blueprint(youtube.bp)
    app.register_blueprint(youtube_stats.bp)
    app.register_blueprint(youtube_overview.bp)
    app.register_blueprint(activity.bp)
    app.register_blueprint(topic_bank.bp)
    app.register_blueprint(series.bp)
    app.register_blueprint(autopilot.bp)
    app.register_blueprint(lang_packs.bp)
    app.register_blueprint(community.bp)
    app.register_blueprint(curated.bp)
    app.register_blueprint(cartesia_api.bp)
    app.register_blueprint(yorum.bp)
    app.register_blueprint(gundem.bp)
