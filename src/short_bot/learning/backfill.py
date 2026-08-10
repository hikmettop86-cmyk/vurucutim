"""Geçmiş shorts kayıtlarını canonical kategoriye yeniden etiketler.

Scorer'ın kategori ipucu 30 günlük pencereden besleniyor. Kanal canonical
listeye geçtiğinde bu pencere bir ay boyunca eski serbest etiketleri
("transfer", "futbol", "spor") göstermeye devam eder — hepsi aynı şeyi
anlatan, ayırt edici olmayan kovalar. Yeniden etiketleme ipucunu hemen
kullanılır hale getirir.

Etiketleme kararını ÇAĞIRAN verir ({short_id: kategori}); burada yalnız
yazma işi yapılır. Orijinal etiket `category_original` alanında saklanır,
böylece yanlış bir eşleme geri alınabilir.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.engine import Engine

from short_bot.db import shorts


def apply_category_backfill(eng: Engine, mapping: dict[int, str]) -> int:
    """`{short_id: canonical_kategori}` uygula. Güncellenen kayıt sayısını döner."""
    if not mapping:
        return 0
    updated = 0
    with eng.begin() as conn:
        rows = conn.execute(
            select(shorts.c.id, shorts.c.script_json)
            .where(shorts.c.id.in_(list(mapping)))
        ).all()
        for short_id, script_json in rows:
            try:
                payload = json.loads(script_json or "{}") or {}
            except (TypeError, ValueError):
                continue
            # İlk backfill'de orijinali sakla; tekrar çalıştırılırsa ezme.
            if "category_original" not in payload:
                payload["category_original"] = payload.get("category", "")
            payload["category"] = mapping[short_id]
            conn.execute(
                shorts.update()
                .where(shorts.c.id == short_id)
                .values(script_json=json.dumps(payload, ensure_ascii=False))
            )
            updated += 1
    return updated
