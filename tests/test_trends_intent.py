"""Aşama 2-3: trend havuzunda arama-niyeti sırası (ChannelConfig.trends_intent).

ÖLÇÜM NOTU (2026-08-20, YouTube Analytics): arama payı tüm kanallarda %2,2–2,9.
Bu ayar trafiği devirmez; asıl işi aynı YouTube kanalına üreten iki formatın
(6 sn kart + seslendirmeli yorum) AYNI olayı iki kez anlatmasını önlemektir.
Bu yüzden FİLTRE değil SIRA tercihidir — tercih edilen tür yoksa kanal yine üretir.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from short_bot.models import NewsItem, ScoredItem
from short_bot.scorer import select_by_volume


def _s(title, volume, related, score=8.0):
    return ScoredItem(
        item=NewsItem(guid=title, title=title, link="l", source="s", pub_date=None,
                      thumb_url=None, description="d", trend_volume=volume,
                      trend_related=tuple(related)),
        score=score, reasoning="")


SORULU = _s("Asgari ücret", 20000, ("asgari ücrete zam gelecek mi", "asgari ücret"))
OLAY = _s("Deprem", 90000, ("istanbul deprem", "son dakika deprem"))
OLAY2 = _s("Derbi", 50000, ("galatasaray fenerbahçe",))



def _kanal(ad: str):
    """Depodaki kanalı oku; YOKSA testi ATLA.

    Bu dosyadaki iddialar kullanıcının CANLI kanal yapılandırması hakkında.
    Kanal silmek bir hata değil, operatör kararı — nitekim `deutschland-kompakt`
    2026-08-21'de silindi ve yedi test birden düştü. Aynı kırılganlık daha önce
    `yasashisa.yaml`da da yaşanmıştı.
    """
    import pytest
    from pathlib import Path

    from short_bot.config import load_channel
    p = Path(f"config/channels/{ad}.yaml")
    if not p.exists():
        pytest.skip(f"{ad} kanalı yok (silinmiş olabilir)")
    return load_channel(p)


def test_any_yalnizca_hacme_bakar():
    out = select_by_volume([SORULU, OLAY, OLAY2], min_score=6.0, n=3)
    assert [s.item.title for s in out] == ["Deprem", "Derbi", "Asgari ücret"]


def test_question_soru_tasiyani_one_alir():
    out = select_by_volume([SORULU, OLAY, OLAY2], min_score=6.0, n=3, intent="question")
    assert out[0].item.title == "Asgari ücret"          # hacmi en düşük olmasına rağmen
    assert [s.item.title for s in out[1:]] == ["Deprem", "Derbi"]   # kalanlar hacim sırası


def test_breaking_soru_tasimayani_one_alir():
    out = select_by_volume([SORULU, OLAY, OLAY2], min_score=6.0, n=3, intent="breaking")
    assert [s.item.title for s in out] == ["Deprem", "Derbi", "Asgari ücret"]


def test_niyet_filtre_degil_tercihtir():
    """Soru niyetli kanal, hiç soru yoksa BOŞ dönmez — havuzun kalanını üretir."""
    out = select_by_volume([OLAY, OLAY2], min_score=6.0, n=2, intent="question")
    assert [s.item.title for s in out] == ["Deprem", "Derbi"]


def test_puan_kapisi_niyetten_once_gelir():
    """Eşiğin altındaki soru, niyet tercihiyle geri gelmez."""
    zayif = _s("Hava durumu", 200000, ("yarın yağmur yağacak mı",), score=3.0)
    out = select_by_volume([zayif, OLAY], min_score=6.0, n=3, intent="question")
    assert [s.item.title for s in out] == ["Deprem"]


# --- kanal ayarı ---------------------------------------------------------------

def _yaml(intent_line=""):
    return f"""\
slug: t
name: T
keywords: []
language: tr
content_source: trends
trends_region: TR
schedule_cron: 0 * * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 5
template: flas
colors: {{primary: '#d0021b', accent: '#ffe600', bg_gradient: ['#3a3a3a', '#141414']}}
handle: '@t'
output_dir: out
enabled: true
{intent_line}"""


def test_varsayilan_any(tmp_path):
    from short_bot.config import load_channel
    p = tmp_path / "t.yaml"; p.write_text(_yaml(), encoding="utf-8")
    assert load_channel(p).trends_intent == "any"


@pytest.mark.parametrize("val", ["question", "breaking", "any"])
def test_gecerli_degerler(tmp_path, val):
    from short_bot.config import load_channel
    p = tmp_path / "t.yaml"; p.write_text(_yaml(f"trends_intent: {val}"), encoding="utf-8")
    assert load_channel(p).trends_intent == val


def test_yazim_hatasi_sessizce_kapanmaz(tmp_path):
    """Saga sınırı dersi: panel kaydı özelliği SESSİZCE kapatıyordu. Geçersiz
    değer 'any'e düşerse kullanıcı açık sanır, kapalı çalışır."""
    from short_bot.config import load_channel
    p = tmp_path / "t.yaml"; p.write_text(_yaml("trends_intent: sorular"), encoding="utf-8")
    with pytest.raises(ValueError, match="trends_intent"):
        load_channel(p)


def test_kaydetme_donusu_korur(tmp_path):
    from short_bot.config import load_channel, save_channel
    p = tmp_path / "t.yaml"; p.write_text(_yaml("trends_intent: question"), encoding="utf-8")
    cfg = load_channel(p)
    save_channel(p, cfg)
    assert load_channel(p).trends_intent == "question"


def test_gercek_kanallar_havuzu_boler():
    """gundem = kart/akış, gundem-yorum = cevap/arama. İkisi aynı olayı seçmesin."""
    from pathlib import Path
    from short_bot.config import load_channel
    assert _kanal("gundem").trends_intent == "breaking"
    assert _kanal("gundem-yorum").trends_intent == "question"
