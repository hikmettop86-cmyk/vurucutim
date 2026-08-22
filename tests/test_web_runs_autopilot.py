"""OTOMASYON AÇIKKEN ELLE ÜRETİM DE SLOTA BAĞLANIR.

GERÇEK HATA (gerçek kanalda ölçüldü): otomasyon açıkken "Şimdi üret"e basmak videoyu
ANINDA ve PUBLIC yayınlıyordu — slot düzeninin tam dışında. İnsan ritmi için kurduğumuz
her şey (taban saatler, rastgele yürüyüş, publishAt) tek tıkla deliniyordu. Üstelik o
video hiçbir slotu doldurmadığı için autopilot aynı gün bir tane DAHA üretiyordu.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from short_bot.db import (init_db, plan_slots, record_short, slots_for_date)
from short_bot.web.runs import launch_pipeline

UTC = timezone.utc


class _AP:
    def __init__(self, enabled=True):
        self.enabled = enabled


class _Ch:
    def __init__(self, autopilot=None):
        self.slug = "k"
        self.autopilot = autopilot


class _Res:
    def __init__(self, short_id, run_id=None, status="success"):
        self.status = status
        self.short_id = short_id
        self.run_id = run_id
        self.error = None


def _kur(tmp_path):
    db = tmp_path / "db.sqlite"
    eng = init_db(db)
    plan_slots(eng, "k", "2026-07-14", [
        {"slot_index": 0, "slot_at_utc": datetime(2026, 7, 14, 9, tzinfo=UTC),
         "jitter_min": 0, "kind": "series"},
        {"slot_index": 1, "slot_at_utc": datetime(2026, 7, 14, 13, tzinfo=UTC),
         "jitter_min": 0, "kind": "standalone"}])
    return db, eng


def _cagir(tmp_path, db, cfg, res):
    gorulen = {}

    def _fake(**kw):
        gorulen["defer"] = kw.get("defer_upload")
        return res

    with patch("short_bot.web.runs.run_pipeline", side_effect=_fake):
        t = launch_pipeline(channel=cfg, settings=None, db_path=db,
                            music_root=tmp_path, templates_dir=tmp_path,
                            cache_dir=tmp_path, lock_dir=tmp_path,
                            logs_dir=tmp_path, trigger="manual")
        t.join(timeout=5)
    return gorulen


def test_otomasyon_ACIKKEN_elle_uretim_YUKLEMEZ(tmp_path):
    """Anında public yayın, ritmi tek tıkla deler."""
    db, eng = _kur(tmp_path)
    sid = record_short(eng, channel="k", rss_item_guid=None, title="T",
                       file_path="v.mp4", duration_s=40, script_json="{}",
                       render_ms=1)
    g = _cagir(tmp_path, db, _Ch(_AP(True)), _Res(sid))
    assert g["defer"] is True, "otomasyon açıkken elle üretim ANINDA yükledi"


def test_elle_uretilen_video_SONRAKI_BOS_SLOTA_baglanir(tmp_path):
    db, eng = _kur(tmp_path)
    sid = record_short(eng, channel="k", rss_item_guid=None, title="T",
                       file_path="v.mp4", duration_s=40, script_json="{}",
                       render_ms=1)
    _cagir(tmp_path, db, _Ch(_AP(True)), _Res(sid))

    s = slots_for_date(eng, "k", "2026-07-14")
    assert s[0]["status"] == "produced", "ilk boş slota bağlanmadı"
    assert s[0]["short_id"] == sid
    assert s[1]["status"] == "planned", "yalnız BİR slot doldurulmalı"


def test_bos_slot_yoksa_YUKLENMEZ(tmp_path):
    """Ritim dışında yayınlamaktansa beklemek yeğdir."""
    from short_bot.db import slot_set_status
    db, eng = _kur(tmp_path)
    sid = record_short(eng, channel="k", rss_item_guid=None, title="T",
                       file_path="v.mp4", duration_s=40, script_json="{}",
                       render_ms=1)
    for s in slots_for_date(eng, "k", "2026-07-14"):
        slot_set_status(eng, s["id"], "published", short_id=sid)

    yeni = record_short(eng, channel="k", rss_item_guid=None, title="T2",
                        file_path="v2.mp4", duration_s=40, script_json="{}",
                        render_ms=1)
    g = _cagir(tmp_path, db, _Ch(_AP(True)), _Res(yeni))
    assert g["defer"] is True
    # Hiçbir slot bu videoya bağlanmamalı
    assert all(s["short_id"] == sid
               for s in slots_for_date(eng, "k", "2026-07-14"))


def test_otomasyon_KAPALIYKEN_eski_davranis(tmp_path):
    """Geriye uyum: autopilot kullanmayan kanalda elle üretim aynen yükler."""
    db, eng = _kur(tmp_path)
    sid = record_short(eng, channel="k", rss_item_guid=None, title="T",
                       file_path="v.mp4", duration_s=40, script_json="{}",
                       render_ms=1)
    g = _cagir(tmp_path, db, _Ch(_AP(False)), _Res(sid))
    assert g["defer"] is False

    g2 = _cagir(tmp_path, db, _Ch(None), _Res(sid))
    assert g2["defer"] is False


def test_basarisiz_uretim_slota_BAGLANMAZ(tmp_path):
    db, eng = _kur(tmp_path)
    _cagir(tmp_path, db, _Ch(_AP(True)),
           _Res(None, status="failed"))
    assert all(s["status"] == "planned"
               for s in slots_for_date(eng, "k", "2026-07-14"))
