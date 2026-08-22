import pytest
from flask import Flask

from short_bot.db import init_db, mark_processed, record_short
from short_bot.web.extensions import db
from short_bot.web.models import Short, ProcessedItem, Run, RssItem


@pytest.fixture
def app(tmp_path):
    db_path = tmp_path / "x.sqlite"
    init_db(db_path)
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


def test_models_map_to_existing_schema(app):
    """ORM models should query Phase 1 tables without `db.create_all()` conflict."""
    with app.app_context():
        # Tables already exist from init_db; just query them
        assert ProcessedItem.query.count() == 0
        assert Short.query.count() == 0
        assert Run.query.count() == 0
        assert RssItem.query.count() == 0


def test_short_file_url_property(app):
    with app.app_context():
        from short_bot.db import init_db as _init
        eng = _init(app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""))
        sid = record_short(
            eng, channel="test", rss_item_guid="g1", title="X",
            file_path="output/test/2026-05-05_x.mp4", duration_s=6,
            script_json="{}", render_ms=1000,
        )
    with app.app_context():
        s = Short.query.get(sid)
        assert s.file_url == "/output/test/2026-05-05_x.mp4"
