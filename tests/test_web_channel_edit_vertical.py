"""Panel kaydı dikeyi DÜŞÜRMEMELİ — izin listesine eklenmeyen alan sessizce
varsayılana döner (bkz. panel DNA palet tuzağı, trends kaynağı tuzağı)."""
from __future__ import annotations

import inspect
from pathlib import Path


def test_genel_duzenleme_dikeyi_kaydeder():
    from short_bot.web.routes import channel_edit
    src = inspect.getsource(channel_edit)
    assert "trends_vertical" in src


def test_yorum_duzenleme_dikeyi_kaydeder():
    from short_bot.web.routes import yorum
    src = inspect.getsource(yorum.edit_save)
    assert "trends_vertical" in src


def test_yorum_kurulumu_dikeyi_kaydeder():
    from short_bot.web.routes import yorum
    src = inspect.getsource(yorum.new_create)
    assert "trends_vertical" in src


def test_sablonlarda_dikey_secici_var():
    kok = Path("src/short_bot/web/templates/channels")
    for ad in ("edit.html.j2", "edit_yorum.html.j2", "new_yorum.html.j2"):
        metin = (kok / ad).read_text(encoding="utf-8")
        assert 'name="trends_vertical"' in metin, ad


def test_formda_alan_yoksa_eski_deger_korunur():
    """Başka bir kartın POST'u dikeyi sessizce silmemeli."""
    from short_bot.web.routes.yorum import _dikey_from_form
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context("/", method="POST", data={"name": "x"}):
        assert _dikey_from_form("para") == "para"


def test_bos_secim_dikeyi_kaldirir():
    from short_bot.web.routes.yorum import _dikey_from_form
    from flask import Flask
    app = Flask(__name__)
    with app.test_request_context("/", method="POST", data={"trends_vertical": ""}):
        assert _dikey_from_form("para") is None
