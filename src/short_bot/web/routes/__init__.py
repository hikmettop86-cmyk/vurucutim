"""Blueprint registration."""
from flask import Flask


def register_blueprints(app: Flask) -> None:
    from short_bot.web.routes import (
        dashboard, shorts, rss, channels,
        channel_new, channel_edit, preview, logs, settings,
        generator_test, system, youtube,
    )
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(shorts.bp)
    app.register_blueprint(rss.bp)
    app.register_blueprint(channels.bp)
    app.register_blueprint(channel_new.bp)
    app.register_blueprint(channel_edit.bp)
    app.register_blueprint(preview.bp)
    app.register_blueprint(logs.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(generator_test.bp)
    app.register_blueprint(system.bp)
    app.register_blueprint(youtube.bp)
