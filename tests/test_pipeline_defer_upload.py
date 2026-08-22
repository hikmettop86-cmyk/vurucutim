"""ÇİFTE YÜKLEME ENGELİ.

Autopilot videoyu KENDİ yükleyecek (gizli + publishAt, slot saatine). Pipeline aynı
videoyu bir de anında (public) yüklerse kanalda İKİ video olur ve bütün zamanlama
çöker. HİÇBİR HATA VERMEZ — sadece yanlış davranır.

ÖLÇÜM NOKTASI: ``run_auto_upload`` (gerçek YouTube çağrısı) çağrıldı mı?
_maybe_auto_upload'ı komple patch'lemek YETMEZ — o zaman yalnız "bayrak geçti mi"
ölçülür ve biri içerideki korumayı silse test yine geçerdi.
"""
import dataclasses
from pathlib import Path
from unittest.mock import patch

import pytest

from short_bot.config import YoutubeChannelConfig
from short_bot.pipeline import run_pipeline
from tests.test_pipeline_series import _channel, _result, _settings


class _Creds:
    expired = False
    refresh_token = None


def _cfg(tmp_path):
    c = _channel(tmp_path)
    c.reel.series_enabled = False        # seri bu testin konusu değil
    # auto_upload AÇIK: kapıların hepsi geçilsin ki tek engel 'defer' olsun.
    return dataclasses.replace(
        c, youtube=YoutubeChannelConfig(auto_upload=True, min_score_for_upload=0.0))


def _kos(cfg, tmp_path, db, *, defer, patlat=False):
    yuklendi = []
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)

    def _sahte_reel(**kw):
        if patlat:
            raise RuntimeError("uretim patladi")
        Path(kw["out_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kw["out_path"]).write_bytes(b"mp4")
        return Path(kw["out_path"])

    class _Sonuc:
        video_id = "V"; video_url = "https://youtu.be/V"

    with patch("short_bot.pipeline.generate_quote",
               return_value=_result("Bir konu basligi buraya")), \
         patch("short_bot.pipeline._reel_produce_or_none", side_effect=_sahte_reel), \
         patch("short_bot.pipeline._yt_auth.load_credentials",
               return_value=_Creds()), \
         patch("short_bot.pipeline.get_last_youtube_upload_at", return_value=None), \
         patch("short_bot.pipeline.run_auto_upload",
               side_effect=lambda **kw: (yuklendi.append(kw["short_id"]), _Sonuc())[1]):
        r = run_pipeline(channel=cfg, settings=_settings(), db_path=db,
                         music_root=tmp_path, templates_dir=tmp_path,
                         cache_dir=tmp_path / "c", lock_dir=tmp_path / "l",
                         logs_dir=logs, trigger="test", defer_upload=defer)
    return r, yuklendi


def test_defer_upload_ACIKKEN_YouTube_e_YUKLENMEZ(tmp_path):
    """Bu geçmezse autopilot açık her kanalda her video İKİ KEZ yüklenir."""
    r, yuklendi = _kos(_cfg(tmp_path), tmp_path, tmp_path / "db.sqlite", defer=True)
    assert r.status == "success"
    assert yuklendi == [], "defer_upload=True iken pipeline YÜKLEDİ → ÇİFTE YÜKLEME"


def test_defer_upload_KAPALIYKEN_eski_davranis(tmp_path):
    """Geriye uyum: autopilot kullanmayan kanallar aynen çalışmalı.

    Bu test aynı zamanda YUKARIDAKİ testin gerçekten bir şey ölçtüğünü kanıtlar:
    aynı kurulumda defer=False iken yükleme GERÇEKTEN oluyor.
    """
    r, yuklendi = _kos(_cfg(tmp_path), tmp_path, tmp_path / "db.sqlite", defer=False)
    assert r.status == "success"
    assert yuklendi == [r.short_id], "normal koşu yüklemiyor → geriye uyum kırıldı"


def test_RunResult_short_id_tasir(tmp_path):
    """Autopilot slotu short_id'ye bağlamak ZORUNDA — yükleme üretimden ayrı koşuyor
    ve hangi videoyu yükleyeceğini yalnız kimlikten bilebilir."""
    r, _ = _kos(_cfg(tmp_path), tmp_path, tmp_path / "db.sqlite", defer=True)
    assert r.short_id is not None and r.short_id > 0


def test_basarisiz_kosuda_short_id_None(tmp_path):
    """Slot 'produced' işaretlenmemeli — yoksa autopilot var olmayan bir videoyu
    yüklemeye çalışır."""
    r, _ = _kos(_cfg(tmp_path), tmp_path, tmp_path / "db.sqlite",
                defer=True, patlat=True)
    assert r.status == "failed"
    assert r.short_id is None
