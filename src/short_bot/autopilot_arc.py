"""Ark oto-yenileme (autopilot).

Günde 3 video üreten bir kanalda 3 bölümlük ark BİR GÜNDE biter. Ertesi gün onaylı ark
kalmazsa sistem bankadan tek konu üretmeye düşer ve SERİ DURUR — yani Faz 3'ün bütün
abone mekanizması (numaralı bölüm, açık kapı, takas CTA) çalışmaz hâle gelir. Kanal
"numaralı ama birbiriyle ilgisiz videolar" üretmeye başlar; bu, seri olmamaktan da
kötüdür çünkü izleyiciye verilmiş bir söz tutulmamış olur.

Kullanıcının kararı: OTOMATİK PLANLA + OTOMATİK ONAYLA.

TEK İSTİSNA — KULLANICININ BEKLEYEN TASLAĞI. Onun incelemesini ezip kendi arkımızı
üretime almak, onay mekanizmasına duyduğu güveni yıkar: bir daha panele bakmaz.
O durumda seri o bölümde ilerlemez (bankadan tek konu) ve panel bunu söyler.
"""
from __future__ import annotations

import logging

from short_bot.db import (active_arc, active_bank_topics, approve_arc, create_arc,
                          draft_arc, mark_bank_topic_used)
from short_bot.reel_arc import plan_arc

log = logging.getLogger(__name__)


def ensure_arc(eng, cfg, *, llm_call) -> bool:
    """Onaylı ark yoksa bankadan tohum al, ark planla ve OTO-ONAYLA.

    Dönüş: yeni ark üretime alındıysa True.
    HİÇBİR HÂLDE ÇÖKMEZ — ark kurulamazsa üretim yine koşar (LLM konu üretir).
    Duran bir otomasyon, serisi ilerlemeyen bir otomasyondan kötüdür.
    """
    reel = getattr(cfg, "reel", None)
    if reel is None or not reel.enabled or not reel.series_enabled:
        return False
    if getattr(reel, "arc_mode", "chain") != "planned":
        return False
    if active_arc(eng, cfg.slug) is not None:
        return False                      # ark sürüyor, dokunma
    if draft_arc(eng, cfg.slug) is not None:
        log.info(f"[autopilot] {cfg.slug}: kullanıcının taslağı onay bekliyor → "
                 f"OTO-ONAY YOK (seri bu bölümde ilerlemeyecek)")
        return False

    aktifler = active_bank_topics(eng, cfg.slug, limit=1)
    if not aktifler:
        log.warning(f"[autopilot] {cfg.slug}: konu bankası boş → ark planlanamadı")
        return False
    tohum, bank_id = aktifler[0]["topic"], aktifler[0]["id"]

    if llm_call is None:
        log.warning(f"[autopilot] {cfg.slug}: LLM ayarlı değil → ark planlanamadı")
        return False

    plan = plan_arc(tohum, channel=cfg, n=reel.series_arc_length, llm_call=llm_call)
    if plan is None:
        log.warning(f"[autopilot] {cfg.slug}: ark planlanamadı (LLM)")
        return False

    arc_id = create_arc(eng, cfg.slug, title=plan.title, seed_topic=tohum,
                        plan=[{"topic": e.topic, "promise": e.promise}
                              for e in plan.episodes])
    approve_arc(eng, arc_id)              # OTO-ONAY: kullanıcı tam otomasyon seçti
    mark_bank_topic_used(eng, bank_id)    # aynı tohumdan iki ark planlanmasın
    log.info(f"[autopilot] {cfg.slug}: yeni ark '{plan.title}' "
             f"({len(plan.episodes)} bölüm) OTO-ONAYLANDI")
    return True
