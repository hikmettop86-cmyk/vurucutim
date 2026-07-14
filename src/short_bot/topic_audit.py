"""Bankadaki MEVCUT konuları denetle — çöpü 'rejected' işaretle.

NEDEN VAR (ölçüldü): konu damıtması sistemin EN UCUZ modelinde (gemini-3.1-flash-lite)
koşuyordu ve banka çöp biriktirdi:

    vucudun-gizli-onarim-gucu :  27 aktif konudan 23'ü ÇÖP (%85)
    bilim-tarihinin-sok-anlari:  21 aktif konudan  5'i ÇÖP (%23)

Bazıları sadece boş değil, BİLİMSEL OLARAK YANLIŞ:
    "Vücudunuz muzu sindirim sistemi boyunca SANİYELER İÇİNDE…"      ← saatler sürer
    "Kanser, bağışıklık sisteminin kendi hücrelerini tanıyamamasıdır" ← nedensellik ters

Bunlar bankada ÜRETİLMEYİ BEKLİYORDU. Kanalın otoritesi ürünüdür; bir tek yanlış video
onu yakar.

Yeni konular artık üretim anında doğrulanıyor (topic_propose.verify_topics). Bu modül
ESKİ kayıtlar için: tek seferlik temizlik + panelden talep üzerine.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def audit_bank(eng, channel: str, *, language: str, llm) -> dict:
    """AKTİF konuları denetle, çöpü 'rejected' işaretle.

    ``{"checked": N, "rejected": M}``

    'used' konulara DOKUNULMAZ — video zaten üretildi, onları reddetmenin anlamı yok.

    Denetim ÇÖKERSE hiçbir şey reddedilmez: ``verify_topics`` o hâlde hepsini
    ``solid=True`` döndürür. Sağlam konuları silmektense hiçbir şey yapmamak yeğdir.
    """
    from short_bot.db import all_bank_topics, reject_bank_topic
    from short_bot.topic_propose import verify_topics

    aktif = [r for r in all_bank_topics(eng, channel) if r["status"] == "active"]
    if not aktif:
        return {"checked": 0, "rejected": 0}

    yargilar = verify_topics([r["topic"] for r in aktif], language=language, llm=llm)

    red = 0
    for r, y in zip(aktif, yargilar):
        if y.solid:
            continue
        reject_bank_topic(eng, r["id"])
        red += 1
        log.info(f"[denetim] {channel}: REDDEDİLDİ ({y.reason}) → {r['topic'][:60]}")

    log.info(f"[denetim] {channel}: {len(aktif)} konu denetlendi, {red} reddedildi")
    return {"checked": len(aktif), "rejected": red}
