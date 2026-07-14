"""Konu bankası otomatik doldurma — SU SEVİYESİ.

ÖLÇÜLDÜ (gerçek kanallar):
    otomasyon günde 3 video → ~2-3 banka konusu tüketir
    haftalık tazeleme       → ~6 konu ekler
    NET                     → haftada -11 ile -15 konu

    bilim-tarihinin: 22 aktif konu → ~9 GÜNDE biter
    vucudun:         28 aktif konu → ~11 GÜNDE biter

Eski tek mekanizma Pazartesi 05:00 cron'uydu ve bankanın SAYISINA değil, son yenileme
TARİHİNE bakıyordu. Banka Salı kurusa kullanıcı Pazartesiye kadar beklerdi.

BANKA KURUYUNCA üretim DURMAZ ama SESSİZCE BOZULUR: seri durur (ark için tohum yok),
bağımsız videolar kanıtlanmış konu olmadan üretilir.
"""
from datetime import datetime, timedelta, timezone

import short_bot.topic_miner as MINER
from short_bot.db import active_bank_count, init_db, insert_bank_topics
from short_bot.topic_autofill import (LOW_WATER, MIN_REFRESH_HOURS, autofill,
                                      needs_refill)

UTC = timezone.utc
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


# --- KARAR: doldurulsun mu? ------------------------------------------------

def test_seviye_YUKSEKSE_dokunma():
    assert needs_refill(LOW_WATER, None, NOW) is False
    assert needs_refill(LOW_WATER + 5, None, NOW) is False


def test_seviye_DUSUKSE_doldur():
    assert needs_refill(LOW_WATER - 1, None, NOW) is True
    assert needs_refill(0, None, NOW) is True


def test_KOTA_korumasi_cok_sik_yenilemez():
    """Bir yenileme ~400 YouTube API birimi. Her tick'te yenilemek kotayı yakar."""
    az_once = NOW - timedelta(hours=MIN_REFRESH_HOURS - 1)
    assert needs_refill(2, az_once, NOW) is False

    eskiden = NOW - timedelta(hours=MIN_REFRESH_HOURS + 1)
    assert needs_refill(2, eskiden, NOW) is True


def test_naive_datetime_cokmez():
    """DB naive datetime döndürüyor — UTC varsayılmalı."""
    eski = (NOW - timedelta(hours=MIN_REFRESH_HOURS + 1)).replace(tzinfo=None)
    assert needs_refill(2, eski, NOW) is True


def test_esik_makul():
    # Otomasyon günde ~2-3 konu yiyor. Sıfırı beklemek üretimi aç bırakır;
    # madencilik birkaç dakika sürüyor.
    assert 5 <= LOW_WATER <= 20
    assert 2 <= MIN_REFRESH_HOURS <= 24


# --- UÇTAN UCA -------------------------------------------------------------

class _Gen:
    topic = "ilginc bilgiler burada"


class _Ch:
    slug = "k"
    name = "Kanal"
    language = "tr"
    content_source = "generator"
    generator = _Gen()
    keywords = []
    reference_channels = []
    dna = None


def _eng(tmp_path):
    return init_db(tmp_path / "db.sqlite")


def _doldur(eng, n):
    insert_bank_topics(eng, "k", [
        {"topic": f"Konu {i} burada uzun", "source_title": f"V{i}",
         "views": 1, "subs": 1} for i in range(n)])


def test_banka_DOLUYSA_madencilik_KOSMAZ(tmp_path, monkeypatch):
    kosti = []
    monkeypatch.setattr(MINER, "refresh_topic_bank",
                        lambda *a, **kw: kosti.append(1) or {"added": 0})
    eng = _eng(tmp_path)
    _doldur(eng, LOW_WATER + 3)
    assert autofill(eng, _Ch(), api_keys=["K"], llm_call=object(), now=NOW) == 0
    assert kosti == [], "banka doluyken boşuna kota yakıldı"


def test_banka_AZALINCA_doldurulur(tmp_path, monkeypatch):

    def _fake(eng, slug, niche, **kw):
        insert_bank_topics(eng, slug, [
            {"topic": f"Yeni konu {i} burada", "source_title": f"N{i}",
             "views": 1, "subs": 1} for i in range(6)])
        return {"added": 6, "skipped_dup": 0}

    monkeypatch.setattr(MINER, "refresh_topic_bank", _fake)
    eng = _eng(tmp_path)
    _doldur(eng, 3)
    assert active_bank_count(eng, "k") == 3

    eklenen = autofill(eng, _Ch(), api_keys=["K"], llm_call=object(), now=NOW)
    assert eklenen == 6
    assert active_bank_count(eng, "k") == 9


def test_madencilik_PATLARSA_cokmez(tmp_path, monkeypatch):
    """Üretim yine koşmalı (LLM konu üretir) — ama loga geçmeli."""

    def _patla(*a, **kw):
        raise RuntimeError("kota doldu")

    monkeypatch.setattr(MINER, "refresh_topic_bank", _patla)
    eng = _eng(tmp_path)
    _doldur(eng, 2)
    assert autofill(eng, _Ch(), api_keys=["K"], llm_call=object(), now=NOW) == 0


def test_API_anahtari_yoksa_dokunma(tmp_path):
    eng = _eng(tmp_path)
    _doldur(eng, 2)
    assert autofill(eng, _Ch(), api_keys=[], llm_call=object(), now=NOW) == 0


def test_generator_olmayan_kanal_atlanir(tmp_path, monkeypatch):
    kosti = []
    monkeypatch.setattr(MINER, "refresh_topic_bank",
                        lambda *a, **kw: kosti.append(1) or {"added": 0})

    class _Rss(_Ch):
        content_source = "rss"
        generator = None

    eng = _eng(tmp_path)
    assert autofill(eng, _Rss(), api_keys=["K"], llm_call=object(), now=NOW) == 0
    assert kosti == []


def test_SIFIR_konu_eklense_bile_kota_korumasi_isler(tmp_path, monkeypatch):
    """NİŞ TÜKENDİ SENARYOSU — en sinsi kota sızıntısı.

    Ölçüt 'son EKLENEN konunun tarihi' olsaydı: madencilik 0 konu ekler → o tarih
    donar → her 4 saatlik tick 'yenile'nin zamanı geldi der → günde 6 × ~400 birim
    boşa yanar. Ölçüt son DENEME olmalı.
    """
    calls = []
    monkeypatch.setattr(MINER, "refresh_topic_bank",
                        lambda *a, **kw: calls.append(1) or {"added": 0,
                                                             "skipped_dup": 12})
    eng = _eng(tmp_path)
    _doldur(eng, 2)

    assert autofill(eng, _Ch(), api_keys=["K"], llm_call=object(), now=NOW) == 0
    assert len(calls) == 1

    # 4 saat sonraki tick: banka hâlâ 2, hiç konu eklenmedi → YİNE DE koşmamalı.
    sonra = NOW + timedelta(hours=4)
    assert autofill(eng, _Ch(), api_keys=["K"], llm_call=object(), now=sonra) == 0
    assert len(calls) == 1, "kota koruması delindi — niş tükenince tekrar tekrar madenledi"

    # Bekleme süresi dolunca tekrar dener.
    cok_sonra = NOW + timedelta(hours=MIN_REFRESH_HOURS + 1)
    autofill(eng, _Ch(), api_keys=["K"], llm_call=object(), now=cok_sonra)
    assert len(calls) == 2


def test_madencilik_PATLASA_da_kota_korumasi_isler(tmp_path, monkeypatch):
    """Damga madencilikten ÖNCE düşmeli — yoksa her patlama yeni deneme davet eder."""
    calls = []

    def _patla(*a, **kw):
        calls.append(1)
        raise RuntimeError("kota doldu")

    monkeypatch.setattr(MINER, "refresh_topic_bank", _patla)
    eng = _eng(tmp_path)
    _doldur(eng, 2)

    autofill(eng, _Ch(), api_keys=["K"], llm_call=object(), now=NOW)
    autofill(eng, _Ch(), api_keys=["K"], llm_call=object(), now=NOW + timedelta(hours=4))
    assert len(calls) == 1, "patlayan madencilik hemen yeniden denendi"


def test_doldurmadan_SONRA_da_dusukse_UYARIR(tmp_path, monkeypatch, caplog):
    """Niş tükeniyor olabilir — kullanıcıya REFERANS KANAL öner."""
    import logging

    monkeypatch.setattr(MINER, "refresh_topic_bank",
                        lambda *a, **kw: {"added": 1, "skipped_dup": 9})
    eng = _eng(tmp_path)
    _doldur(eng, 2)
    with caplog.at_level(logging.WARNING):
        autofill(eng, _Ch(), api_keys=["K"], llm_call=object(), now=NOW)
    assert "niş tükeniyor" in caplog.text.lower()
    assert "REFERANS KANAL" in caplog.text


# --- SAYAÇ ----------------------------------------------------------------

def test_active_bank_count_yalniz_AKTIFI_sayar(tmp_path):
    from short_bot.db import all_bank_topics, mark_bank_topic_used, reject_bank_topic
    eng = _eng(tmp_path)
    _doldur(eng, 5)
    rows = all_bank_topics(eng, "k")
    mark_bank_topic_used(eng, rows[0]["id"])
    reject_bank_topic(eng, rows[1]["id"])
    assert active_bank_count(eng, "k") == 3


def test_bos_banka_sifir(tmp_path):
    assert active_bank_count(_eng(tmp_path), "k") == 0
