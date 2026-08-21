"""Kanal teşhisi — LLM'siz, yalnız ölçülebilir olan.

TASARIM KISITI (ölçüldü, 2026-08-21): `shorts` tablosunda ve `script_json`
içinde PUAN alanı YOK. Bu yüzden "elenenlerin kaçı yükleme eşiğinin hemen
altındaydı" sorusu bu şemadan CEVAPLANAMAZ ve öyle bir bulgu üretilmez.
Uydurma sayı üretmektense bulguyu hiç üretmemek doğrudur.

Cevaplanabilenler: manşet taşma riski (başlık uzunluğu vs DNA sınırı), yayın
durgunluğu (son başarılı yükleme), boş koşu oranı (üretmeden biten koşular),
otomatik yükleme kapalıyken biriken video.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from short_bot.db import init_db, record_short, record_youtube_upload, runs


def _cfg(**kw):
    from short_bot.config import ChannelConfig
    base = dict(slug="ch", name="C", keywords=["a"],
                rss_locale="hl=tr&gl=TR&ceid=TR:tr", schedule_cron="0 9 * * *",
                duration_s=6, min_score=6.0, max_candidates_per_run=10,
                template="newscast",
                colors={"primary": "#000", "accent": "#111",
                        "bg_gradient": ["#000", "#111"]},
                handle="@ch", output_dir="out", enabled=True, language="tr")
    base.update(kw)
    return ChannelConfig(**base)


@pytest.fixture
def eng(tmp_path):
    return init_db(tmp_path / "d.sqlite")


def _short(eng, *, title="Kısa manşet", gun_once=0, script=None):
    import json
    sid = record_short(eng, channel="ch", rss_item_guid=None, title=title,
                       file_path="x.mp4", duration_s=6, render_ms=1,
                       script_json=json.dumps(script or {"header_top": "A",
                                                         "header_bottom": title}))
    if gun_once:
        from sqlalchemy import text
        ts = (datetime.now(timezone.utc) - timedelta(days=gun_once)).strftime("%Y-%m-%d %H:%M:%S")
        with eng.begin() as c:
            c.execute(text("UPDATE shorts SET created_at=:t WHERE id=:i"), {"t": ts, "i": sid})
    return sid


# --- yayın durgunluğu ------------------------------------------------------

def test_yayin_durgunlugu_bulunur(eng):
    from short_bot.channel_diag import bulgular
    for g in (12, 10, 9):
        _short(eng, gun_once=g)
    sid = _short(eng, gun_once=11)
    record_youtube_upload(eng, short_id=sid, video_id="v1",
                          video_url="u", status="success", error=None)
    from sqlalchemy import text
    with eng.begin() as c:
        c.execute(text("UPDATE youtube_uploads SET uploaded_at=:t"),
                  {"t": (datetime.now(timezone.utc) - timedelta(days=11))
                   .strftime("%Y-%m-%d %H:%M:%S")})
    b = {x.kod: x for x in bulgular(eng, _cfg())}
    assert "yayin_durgun" in b
    assert "11" in b["yayin_durgun"].ozet


def test_yayin_durgunlugunun_OTOMATIK_DUZELTMESI_YOK(eng):
    """Bu bir ayar hatası değil, operatör kararı. Claude her şeye çözüm
    üretirse çözümü olmayanı da çözülmüş gösterir."""
    from short_bot.channel_diag import bulgular
    _short(eng, gun_once=20)
    b = {x.kod: x for x in bulgular(eng, _cfg())}
    assert b["yayin_durgun"].duzeltme == []


def test_hic_uretim_yoksa_durgunluk_bulgusu_URETILMEZ(eng):
    """Yeni kanalda 'yayın yok' bir sorun değil, henüz başlamamış demektir."""
    from short_bot.channel_diag import bulgular
    assert not [x for x in bulgular(eng, _cfg()) if x.kod == "yayin_durgun"]


# --- otomatik yükleme kapalı ----------------------------------------------

def test_otomatik_yukleme_kapaliyken_birikme_bulunur(eng):
    from short_bot.config import YoutubeChannelConfig
    from short_bot.channel_diag import bulgular
    for _ in range(6):
        _short(eng, gun_once=2)
    cfg = _cfg(youtube=YoutubeChannelConfig(auto_upload=False))
    b = {x.kod: x for x in bulgular(eng, cfg)}
    assert "yukleme_kapali" in b
    assert b["yukleme_kapali"].duzeltme == [("youtube.auto_upload", False, True)]


def test_otomatik_yukleme_ACIKKEN_bulgu_yok(eng):
    from short_bot.config import YoutubeChannelConfig
    from short_bot.channel_diag import bulgular
    for _ in range(6):
        _short(eng, gun_once=2)
    cfg = _cfg(youtube=YoutubeChannelConfig(auto_upload=True))
    assert not [x for x in bulgular(eng, cfg) if x.kod == "yukleme_kapali"]


# --- boş koşu --------------------------------------------------------------

def test_bos_kosu_orani_bulunur(eng):
    from short_bot.channel_diag import bulgular
    sid = _short(eng, gun_once=1)       # runs.short_id FK -> shorts.id
    with eng.begin() as c:
        for i in range(10):
            c.execute(runs.insert().values(
                channel="ch", trigger="cron", status="success",
                started_at=datetime.now(timezone.utc) - timedelta(days=1),
                ended_at=datetime.now(timezone.utc) - timedelta(days=1),
                short_id=(sid if i < 3 else None)))
    b = {x.kod: x for x in bulgular(eng, _cfg())}
    assert "bos_kosu" in b
    # 10 koşunun 7'si üretmeden bitti
    assert "7" in b["bos_kosu"].ozet
    assert b["bos_kosu"].duzeltme, "boş koşunun eyleme dönük düzeltmesi olmalı"


# --- puan verisi olmadığı için ÜRETİLMEYEN bulgu ---------------------------

def test_esik_alti_bulgusu_URETILMEZ(eng):
    """`shorts` şemasında puan yok — 'eşiğin hemen altında elendi' ölçülemez.

    Bu testin varlık sebebi: mockup'ta böyle bir öneri gösterilmişti ve
    veriyle desteklenmiyordu. Uydurma sayı üretmektense bulguyu hiç
    üretmemek doğrudur; şemaya puan eklenirse bu test bilinçli olarak
    güncellenir."""
    from short_bot.channel_diag import bulgular
    for _ in range(10):
        _short(eng, gun_once=1)
    assert not [x for x in bulgular(eng, _cfg()) if "esik" in x.kod]


# --- bulgu sözleşmesi ------------------------------------------------------

def test_her_bulgu_ozet_ve_gerekce_tasir(eng):
    from short_bot.channel_diag import bulgular
    _short(eng, gun_once=20)
    for b in bulgular(eng, _cfg()):
        assert b.ozet and b.gerekce, f"{b.kod}: boş metin"
        assert isinstance(b.duzeltme, list)
