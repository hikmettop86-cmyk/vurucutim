"""Takip videosu: aynı konuya 24-48 saat sonra "ne oldu" güncellemesi.

NEDEN (ölçüm, 2026-08-20 — YouTube Analytics, Aslan Gündem):
  * Bizi bulan arama terimleri HER GÜN aynı: "galatasaray transfer son dakika",
    "gs transfer", "galatasaray son dakika". Talep tek seferlik değil, TEKRAR
    EDEN bir sorgu akışı.
  * 60+ gün önce yüklenen videolarda izlenmenin %17,3'ü aramadan geliyor
    (akış onları çoktan bıraktı). Yani eski video ölmüyor, kuyruğa geçiyor.
Bu ikisi birlikte şunu söyler: bir konuyu bir kez anlatıp bırakmak, tekrar eden
talebi tek bir eskiyen videoya bağlamak demek.

NEDEN OTOMATİK DEĞİL: tekrarı önleyen bütün mekanizmalar (dedup, saga sınırı,
processed_items) tam da bunu engellemek için var ve haklılar — otomatik takip,
aynı haberi iki kez anlatan bot demek olurdu. Takip BİLİNÇLİ bir karardır:
Gündem masasında "takip üret" düğmesiyle tetiklenir ve önceki videonun metni
prompta girer ki yeni video AYNI ŞEYİ tekrar anlatmasın.
"""
from __future__ import annotations

import json as _json

from sqlalchemy import select

from short_bot.db import shorts


def previous_coverage(eng, guid: str, *, channel: str | None = None) -> dict | None:
    """Bu haberin daha önce üretilmiş EN SON videosu.

    ``{"title": …, "text": …, "created_at": …, "channel": …}`` ya da None.
    ``text`` anlatım/gövde metnidir — takip promptu "bunu tekrar etme" diye
    kullanır. Silinmiş (deleted_at dolu) videolar sayılmaz: kullanıcı onu
    kaldırdıysa konu yeniden anlatılabilir demektir.
    """
    q = (select(shorts.c.title, shorts.c.script_json, shorts.c.created_at,
                shorts.c.channel)
         .where(shorts.c.rss_item_guid == guid)
         .where(shorts.c.deleted_at.is_(None))
         .order_by(shorts.c.id.desc()))
    if channel:
        q = q.where(shorts.c.channel == channel)
    with eng.connect() as conn:
        row = conn.execute(q).fetchone()
    if row is None:
        return None
    text = ""
    try:
        data = _json.loads(row.script_json or "{}") or {}
        text = (data.get("narration_text") or data.get("body_paragraph") or "").strip()
    except (ValueError, TypeError):
        text = ""
    return {"title": row.title or "", "text": text,
            "created_at": row.created_at, "channel": row.channel}


def summarize(prev: dict | None, *, max_chars: int = 700) -> str:
    """Takip promptuna girecek özet metin. Boş dönerse takip bloğu yazılmaz."""
    if not prev:
        return ""
    parts = []
    when = prev.get("created_at")
    when_s = ""
    if when is not None:
        when_s = when.strftime("%d.%m %H:%M") if hasattr(when, "strftime") else str(when)[:16]
    if prev.get("title"):
        parts.append(f"[{when_s}] {prev['title']}" if when_s else prev["title"])
    if prev.get("text"):
        parts.append(prev["text"][:max_chars])
    return "\n".join(parts).strip()


def followup_block(item) -> str:
    """Her iki yazara (kart + yorum) eklenen İngilizce prompt bloğu.

    ``NewsItem.followup_of`` boşsa boş döner — normal üretim bit bit aynı kalır.
    """
    prev = (getattr(item, "followup_of", "") or "").strip()
    if not prev:
        return ""
    return (
        "\nFOLLOW-UP VIDEO (we already covered this story):\n"
        f"{prev}\n"
        "- This video is an UPDATE, not a repeat. Lead with what is NEW since that "
        "video: the decision, the denial, the number that changed, what happened next.\n"
        "- Do NOT restate the earlier facts as news. One short line of context is "
        "allowed only if the update is unintelligible without it.\n"
        "- Do NOT reference 'our previous video', the channel, or the viewer's memory. "
        "Someone seeing this for the first time must understand it on its own.\n"
        "- If the article body contains NOTHING new beyond the earlier coverage, write "
        "the strongest single new detail it does contain rather than padding.\n"
    )
