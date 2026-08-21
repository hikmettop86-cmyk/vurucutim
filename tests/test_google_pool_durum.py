"""Ücretsiz Google havuzunun panelde GÖRÜNMESİ.

Havuz 38 anahtarla çalışıyordu ama ayarlar ekranında HİÇ görünmüyordu: kaç
anahtar var, kaçı yasaklı, bugün kaç çağrı yapıldı — hiçbiri. Havuz tükendiğinde
sistem sessizce OpenRouter'a düşüyor ve kullanıcı faturayı sonradan görüyor.
"""
from __future__ import annotations

import json

import pytest

from short_bot.google_studio import pool_durumu


def _havuz(tmp_path, anahtar=3, kapali=0):
    d = tmp_path / "google_pool"
    d.mkdir()
    keys = [{"id": f"k{i}", "key": f"AIza{i}", "label": f"hesap{i}", "enabled": True}
            for i in range(anahtar)]
    keys += [{"id": f"x{i}", "key": f"AIzaX{i}", "label": "kapali", "enabled": False}
             for i in range(kapali)]
    (d / "google-keys.json").write_text(
        json.dumps({"version": 1, "keys": keys}), encoding="utf-8")
    return d


def test_havuz_yoksa_KIRILMAZ(tmp_path):
    d = pool_durumu(tmp_path / "yok")
    assert d["var"] is False and d["anahtar"] == 0
    assert d["hata"]


def test_anahtar_sayilari(tmp_path):
    d = pool_durumu(_havuz(tmp_path, anahtar=3, kapali=2))
    assert d["var"] is True
    assert d["anahtar"] == 5 and d["etkin"] == 3


def test_gunluk_kullanim_ve_kapasite(tmp_path):
    d = _havuz(tmp_path, anahtar=2)
    (d / "state.json").write_text(json.dumps({
        "ptDate": "2026-08-21",
        "usage": {"k0:gemini": {"dayCount": 120, "status": "active"},
                  "k1:gemini": {"dayCount": 500, "status": "exhausted"}},
        "banned": {}}), encoding="utf-8")
    s = pool_durumu(d)
    assert s["bugun"] == 620
    assert s["gunluk_tavan"] == 2 * 500      # anahtar × DAILY_CAP
    assert s["tukenen"] == 1


def test_BANLI_anahtar_ayri_sayilir(tmp_path):
    d = _havuz(tmp_path, anahtar=2)
    (d / "state.json").write_text(json.dumps({
        "ptDate": "2026-08-21", "usage": {}, "banned": {"k1": True}}),
        encoding="utf-8")
    assert pool_durumu(d)["banli"] == 1


def test_bozuk_state_KIRILMAZ(tmp_path):
    d = _havuz(tmp_path, anahtar=1)
    (d / "state.json").write_text("{bozuk", encoding="utf-8")
    s = pool_durumu(d)
    assert s["var"] is True and s["bugun"] == 0
