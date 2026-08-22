"""Zamanlı yükleme: gizli + publishAt.

YOUTUBE'UN KURALI: publishAt YALNIZ privacyStatus=private iken geçerlidir. Public bir
videoya publishAt vermek SESSİZCE yok sayılır → video ANINDA yayınlanır ve bütün
zamanlama çöker. uploader.build_status bunu zaten biliyor; asıl risk KATMAN GEÇİRME:
run_auto_upload publish_at'i uploader'a iletmezse hiçbir şey zamanlanmaz.
"""
from pathlib import Path

import pytest

from short_bot.youtube.uploader import build_status


def test_publish_at_verilince_GIZLI_olur():
    s = build_status(privacy_status="public", ai_content=True,
                     publish_at="2026-07-14T13:04:00Z")
    assert s["privacyStatus"] == "private", "publishAt public iken YOK SAYILIR"
    assert s["publishAt"] == "2026-07-14T13:04:00Z"


def test_publish_at_yoksa_eski_davranis():
    s = build_status(privacy_status="public", ai_content=True)
    assert s["privacyStatus"] == "public"
    assert "publishAt" not in s


def test_run_auto_upload_publish_at_i_GECIRIR(monkeypatch, tmp_path):
    """KATMAN GEÇİRME. Geçirmezse publishAt hiç uygulanmaz ve video anında yayınlanır
    — slot saati tamamen anlamsızlaşır."""
    import short_bot.youtube.auto_upload as A

    gorulen = {}

    class _Row:
        id = 1
        file_path = str(tmp_path / "v.mp4")
        script_json = "{}"

    class _YT:
        privacy_status = "public"
        ai_content = True
        category_id = "24"

    class _Ch:
        slug = "k"
        handle = "@k"
        keywords = []
        language = "tr"
        youtube = _YT()

    (tmp_path / "v.mp4").write_bytes(b"x")

    monkeypatch.setattr(A, "_load_short_for_upload",
                        lambda eng, short_id: (_Row(), None, None))
    monkeypatch.setattr(A, "generate_youtube_metadata",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("atla")))
    monkeypatch.setattr(A, "upload_video",
                        lambda **kw: (gorulen.update(status=kw["status"]), "VID")[1])
    monkeypatch.setattr(A, "record_youtube_upload", lambda *a, **kw: None)
    monkeypatch.setattr(A, "load_channel_proxy_url", lambda *a, **kw: None)

    r = A.run_auto_upload(eng=None, short_id=1, channel=_Ch(), credentials=None,
                          publish_at="2026-07-14T13:04:00Z")
    assert r.video_id == "VID"
    assert gorulen["status"]["privacyStatus"] == "private"
    assert gorulen["status"]["publishAt"] == "2026-07-14T13:04:00Z"


def test_publish_at_verilmezse_ANINDA_yayin(monkeypatch, tmp_path):
    """Geriye uyum: live_upload modu ve normal auto-upload publishAt vermez."""
    import short_bot.youtube.auto_upload as A

    gorulen = {}

    class _Row:
        id = 1
        file_path = str(tmp_path / "v.mp4")
        script_json = "{}"

    class _YT:
        privacy_status = "public"
        ai_content = True
        category_id = "24"

    class _Ch:
        slug = "k"; handle = "@k"; keywords = []; language = "tr"; youtube = _YT()

    (tmp_path / "v.mp4").write_bytes(b"x")
    monkeypatch.setattr(A, "_load_short_for_upload",
                        lambda eng, short_id: (_Row(), None, None))
    monkeypatch.setattr(A, "generate_youtube_metadata",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("atla")))
    monkeypatch.setattr(A, "upload_video",
                        lambda **kw: (gorulen.update(status=kw["status"]), "VID")[1])
    monkeypatch.setattr(A, "record_youtube_upload", lambda *a, **kw: None)
    monkeypatch.setattr(A, "load_channel_proxy_url", lambda *a, **kw: None)

    A.run_auto_upload(eng=None, short_id=1, channel=_Ch(), credentials=None)
    assert gorulen["status"]["privacyStatus"] == "public"
    assert "publishAt" not in gorulen["status"]

