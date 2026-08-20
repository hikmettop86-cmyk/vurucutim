"""Aşama 4: takip videosu — aynı konuya 24-48 saat sonra "ne oldu" güncellemesi.

Dayanak (ölçüm 2026-08-20): bizi bulan arama terimleri her gün AYNI
("galatasaray transfer son dakika") ve 60+ günlük videolarda izlenmenin %17,3'ü
aramadan geliyor. Talep tekrar ediyor; tek bir eskiyen video onu karşılamıyor.

Takip OTOMATİK DEĞİLDİR: dedup/saga tekrarı önlemekte haklı. Takip yalnız
Gündem masasındaki düğmeyle, önceki metin prompta girerek tetiklenir.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone

import pytest

from short_bot.followup import followup_block, previous_coverage, summarize
from short_bot.models import NewsItem


def _item(**kw):
    base = dict(guid="https://a/1", title="Batrakov geliyor", link="https://a/1",
                source="NTV", pub_date=None, thumb_url=None, description="d")
    base.update(kw)
    return NewsItem(**base)


def _rec(eng, *, guid, channel, title, narration="", body="", deleted=False):
    from short_bot.db import record_short, shorts
    sid = record_short(eng, channel=channel, rss_item_guid=guid, title=title,
                       file_path="f.mp4", duration_s=6,
                       script_json=json.dumps({"narration_text": narration,
                                               "body_paragraph": body}),
                       render_ms=1)
    if deleted:
        with eng.begin() as c:
            c.execute(shorts.update().where(shorts.c.id == sid)
                      .values(deleted_at=datetime.now(timezone.utc)))
    return sid


@pytest.fixture
def eng(tmp_path):
    from short_bot.db import init_db
    return init_db(tmp_path / "t.sqlite")


def test_onceki_kayit_bulunur_ve_en_yenisi_secilir(eng):
    _rec(eng, guid="g1", channel="gundem", title="ESKİ", narration="ilk anlatım")
    _rec(eng, guid="g1", channel="gundem", title="YENİ", narration="ikinci anlatım")
    prev = previous_coverage(eng, "g1")
    assert prev["title"] == "YENİ" and prev["text"] == "ikinci anlatım"


def test_silinmis_video_takip_dayanagi_sayilmaz(eng):
    """Kullanıcı videoyu kaldırdıysa konu yeniden anlatılabilir demektir."""
    _rec(eng, guid="g1", channel="gundem", title="KALDIRILDI", narration="x", deleted=True)
    assert previous_coverage(eng, "g1") is None


def test_kanal_kisitli_arama_ve_geri_dusme(eng):
    _rec(eng, guid="g1", channel="gundem", title="KART", narration="kart metni")
    assert previous_coverage(eng, "g1", channel="gundem-yorum") is None
    assert previous_coverage(eng, "g1", channel="gundem")["title"] == "KART"
    assert previous_coverage(eng, "g1")["title"] == "KART"      # kanalsız → herhangi biri


def test_anlatim_yoksa_govdeye_duser(eng):
    _rec(eng, guid="g1", channel="gundem", title="T", narration="", body="gövde metni")
    assert previous_coverage(eng, "g1")["text"] == "gövde metni"


def test_bozuk_script_json_cokmez(eng):
    from short_bot.db import record_short
    record_short(eng, channel="gundem", rss_item_guid="g1", title="T", file_path="f",
                 duration_s=6, script_json="{bozuk", render_ms=1)
    assert previous_coverage(eng, "g1")["text"] == ""


def test_summarize_tarih_ve_basligi_tasir():
    prev = {"title": "BATRAKOV GELİYOR", "text": "Sağlık kontrolüne gitti.",
            "created_at": datetime(2026, 8, 19, 10, 0)}
    out = summarize(prev)
    assert "19.08 10:00" in out and "BATRAKOV" in out and "Sağlık kontrolüne" in out
    assert summarize(None) == ""


def test_summarize_uzun_metni_kirpar():
    prev = {"title": "T", "text": "x" * 5000, "created_at": None}
    assert len(summarize(prev, max_chars=100)) < 200


# --- prompt'lara giriş ---------------------------------------------------------

def test_blok_yalnizca_takipte_yazilir():
    assert followup_block(_item()) == ""
    b = followup_block(_item(followup_of="[19.08] ÖNCEKİ"))
    assert "FOLLOW-UP VIDEO" in b and "[19.08] ÖNCEKİ" in b


def test_blok_tekrari_yasaklar_ama_kanaldan_bahsettirmez():
    b = followup_block(_item(followup_of="önceki"))
    assert "UPDATE, not a repeat" in b
    assert "Do NOT restate the earlier facts" in b
    # İzleyici önceki videoyu görmemiş olabilir: "geçen videoda dediğimiz gibi" YASAK
    assert "previous video" in b and "on its own" in b


def test_kart_promptuna_girer():
    """6 sn kart yolu da takip modunu görür — takip yalnız yoruma özel değil."""
    from short_bot.config import ChannelConfig
    from short_bot.script_writer import build_script_prompt_for_channel
    ch = ChannelConfig(
        slug="gundem", name="G", keywords=[], rss_locale="hl=tr&gl=TR&ceid=TR:tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0, max_candidates_per_run=5,
        template="flas", colors={"primary": "#d0021b", "accent": "#ffe600",
                                 "bg_gradient": ["#3a3a3a", "#141414"]},
        handle="@g", output_dir="out", enabled=True, language="tr", content_source="trends")
    p = build_script_prompt_for_channel(
        _item(followup_of="[19.08] BATRAKOV GELİYOR"), "gövde", ch)
    assert "FOLLOW-UP VIDEO" in p and "BATRAKOV GELİYOR" in p
    assert "FOLLOW-UP VIDEO" not in build_script_prompt_for_channel(_item(), "gövde", ch)


def test_yorum_promptuna_girer():
    from short_bot.narration_writer import build_yorum_prompt
    from short_bot.config import ChannelConfig, VoiceConfig
    ch = ChannelConfig(
        slug="gundem-yorum", name="G", keywords=[], rss_locale="hl=tr&gl=TR&ceid=TR:tr",
        schedule_cron="0 * * * *", duration_s=6, min_score=6.0, max_candidates_per_run=5,
        template="flas", colors={"primary": "#d0021b", "accent": "#ffe600",
                                 "bg_gradient": ["#3a3a3a", "#141414"]},
        handle="@g", output_dir="out", enabled=True, language="tr", content_source="trends",
        voice=VoiceConfig(enabled=True, provider="cartesia", voice_id="v", speed=1.05,
                          target_duration_s=(35, 50)))
    p = build_yorum_prompt(_item(followup_of="[19.08] BATRAKOV GELİYOR"), "gövde", ch,
                           extra_sources=[])
    assert "FOLLOW-UP VIDEO" in p and "BATRAKOV GELİYOR" in p
    assert "FOLLOW-UP VIDEO" not in build_yorum_prompt(_item(), "gövde", ch, extra_sources=[])


def test_newsitem_alani_replace_ile_dolar():
    it = dataclasses.replace(_item(), followup_of="özet")
    assert it.followup_of == "özet" and _item().followup_of == ""
