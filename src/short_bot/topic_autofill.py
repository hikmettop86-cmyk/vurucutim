"""Konu bankası OTOMATİK DOLDURMA — su seviyesi düşünce yenile.

NEDEN VAR (ölçüldü, gerçek kanallar):
    otomasyon günde 3 video   → ~2-3 banka konusu tüketir
                                (2 bağımsız video + arkın tohumu)
    haftalık tazeleme         → ~6 konu ekler
    NET                       → haftada -11 ile -15 konu

    bilim-tarihinin: 22 aktif konu → ~9 GÜNDE biter
    vucudun:         28 aktif konu → ~11 GÜNDE biter

Eski tek mekanizma Pazartesi 05:00 cron'uydu ve o da bankanın SAYISINA değil, son
yenileme TARİHİNE bakıyordu (7 günden eskiyse yenile). Yani banka Salı günü kurusa
kullanıcı Pazartesiye kadar bekliyordu.

BANKA KURUYUNCA NE OLUR: üretim durmaz — ama SESSİZCE BOZULUR.
  • Seri durur: ark için tohum yok (autopilot_arc: "konu bankası boş").
  • Bağımsız videolar kanıtlanmış konu olmadan üretilir; LLM konuyu uydurur.
  • Hiçbir yerde alarm çalmaz.
Bu yüzden hem OTOMATİK DOLDURMA hem de GÖRÜNÜR UYARI gerekiyor.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

# Bu seviyenin altına inince doldur. Otomasyon günde ~2-3 konu yiyor; 10 konu
# ~4 günlük tampon bırakır — madencilik (YouTube API + LLM) birkaç dakika sürüyor,
# sıfırı beklemek üretimi aç bırakır.
LOW_WATER = 10
# Kota koruması: aynı kanal bu süreden önce yeniden madenlenmez. Bir yenileme ~400
# YouTube API birimi; günlük kota anahtar başına 10.000.
MIN_REFRESH_HOURS = 6


def needs_refill(active_count: int, last_attempt: datetime | None,
                 now: datetime, *, low_water: int = LOW_WATER,
                 min_hours: int = MIN_REFRESH_HOURS) -> bool:
    """Doldurulsun mu? Su seviyesi düşük VE kota bekleme süresi geçmiş olmalı.

    Ölçüt son EKLEME değil son DENEME: niş tükenip madencilik sıfır konu eklediğinde
    ekleme tarihi donar ve kota koruması bir daha asla tetiklenmez.
    """
    if active_count >= low_water:
        return False
    if last_attempt is None:
        return True
    if last_attempt.tzinfo is None:
        last_attempt = last_attempt.replace(tzinfo=timezone.utc)
    return (now - last_attempt) >= timedelta(hours=min_hours)


def autofill(eng, cfg, *, api_keys, llm_call, now: datetime | None = None,
             low_water: int = LOW_WATER, http_get=None) -> int:
    """Kanalın bankası düşükse doldur. Eklenen konu sayısını döndürür (0 = dokunulmadı).

    HİÇBİR HÂLDE ÇÖKMEZ — madencilik başarısız olursa üretim yine koşar (LLM konu
    üretir). Ama LOGA GEÇER: banka kuruduysa sebebi burada aranır.
    """
    from short_bot.db import active_bank_count, kv_touch, kv_updated_at
    from short_bot.reel_relevance import derive_footage_anchor
    from short_bot.topic_miner import refresh_topic_bank

    if cfg.content_source != "generator" or cfg.generator is None:
        return 0
    if not api_keys:
        return 0

    now = now or datetime.now(timezone.utc)
    anahtar = f"bank_attempt:{cfg.slug}"
    kalan = active_bank_count(eng, cfg.slug)
    if not needs_refill(kalan, kv_updated_at(eng, anahtar), now, low_water=low_water):
        return 0

    log.info(f"[banka] {cfg.slug}: {kalan} aktif konu kaldı (eşik {low_water}) "
             f"→ otomatik dolduruluyor")
    # Damga madencilikten ÖNCE düşer: deneme patlasa ya da sıfır konu eklese bile
    # kota koruması işlesin.
    kv_touch(eng, anahtar)
    tmpl = getattr(getattr(cfg, "dna", None), "search_query_template", "") or ""
    try:
        res = refresh_topic_bank(
            eng, cfg.slug, cfg.generator.topic, language=cfg.language,
            api_keys=api_keys, anchor=derive_footage_anchor(tmpl),
            llm_call=llm_call, http_get=http_get,
            keywords=list(cfg.keywords or []),
            reference_channels=list(cfg.reference_channels or []))
    except Exception as e:   # noqa: BLE001 — üretimi DURDURMAMALI
        log.warning(f"[banka] {cfg.slug}: otomatik doldurma başarısız ({e}) — "
                    f"banka {kalan} konuda kaldı. Referans kanal ekleyin ya da "
                    f"'Yenile'ye elle basın.")
        return 0

    yeni = active_bank_count(eng, cfg.slug)
    log.info(f"[banka] {cfg.slug}: +{res['added']} konu → {kalan} → {yeni} aktif")
    if yeni < low_water:
        # Doldurma koştu ama seviye HÂLÂ düşük → niş tükeniyor olabilir.
        log.warning(f"[banka] {cfg.slug}: doldurmadan SONRA da {yeni} konu var "
                    f"(eşik {low_water}) → niş tükeniyor olabilir. En güçlü çare: "
                    f"Konu Bankası sayfasından REFERANS KANAL ekleyin.")
    return int(res["added"])
