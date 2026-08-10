"""Kanal performans denetimi — kanal ayarlarını veriyle belirlemek için.

Bu modül, bir kanalın yayınlanmış videolarından ayar önerileri çıkarır:
hangi konu kotalanmalı, hangi manşet kalıbı yıpranmış, manşet bütçesi
şablonun gerçek kapasitesine uyuyor mu.

NEDEN: iki futbol kanalının ölçümü ters yönlerde çıktı — avrupa-kura
Galatasaray'da endeks 1.69 (en iyi), Fenerbahçe'de 0.42 (en kötü); "BOMBA"
GS'de 42 kullanımla %82'ye düşmüşken FB'de 12 kullanımla %195 getiriyordu.
Yani ayarlar KOPYALANAMAZ, her kanal için ölçülmeli. Standart olması gereken
şey değerler değil, yöntem.
"""
from __future__ import annotations

import re
import statistics as st
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

# Zaman penceresi: videonun endeksi, ±KOMSU_GUN içinde yayınlanmış videoların
# medyanına oranıdır. Kanal büyürken ham görüntülenme karşılaştırması kategori
# farkını zaman etkisiyle karıştırıyor.
_KOMSU_GUN = 10
_MIN_SAMPLES = 4
_MIN_USES = 5

# Türkçe I/İ eşlemesi: Python'un .lower()'ı "HAZIRLIK" → "hazirlik" verir
# (noktalı i) ve "hazırlık" ile eşleşmez. locale_fold'un yaptığı işin
# başlık-analizi için yeten sadeleştirilmiş hâli.
_TR_FOLD = str.maketrans("ıİIğĞüÜşŞöÖçÇ", "iiigguussoocc")

# Manşetlerde taşıyıcı olmayan kelimeler — yıpranma analizinde gürültü.
_STOPWORDS = {
    "ve", "ile", "için", "bir", "bu", "da", "de", "mi", "mı", "ne", "o",
    "the", "a", "of", "to", "in", "on", "for", "und", "der", "die", "das",
}


def _fold(text: str) -> str:
    return text.translate(_TR_FOLD).lower().replace("i̇", "i")


def _with_index(rows: Iterable[dict]) -> list[dict]:
    """Her satıra kendi dönemine göre normalize `index` ekle."""
    usable = [r for r in rows if r.get("views") and r.get("uploaded_at")]
    out: list[dict] = []
    for r in usable:
        dt = r["uploaded_at"]
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt)
        komsu = [
            x["views"] for x in usable
            if abs((_as_dt(x["uploaded_at"]) - dt).days) <= _KOMSU_GUN
        ]
        out.append({**r, "index": r["views"] / st.median(komsu)})
    return out


def _as_dt(value) -> datetime:
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def topic_index(rows: Iterable[dict], *,
                min_samples: int = _MIN_SAMPLES) -> list[dict]:
    """Kategori başına zaman-normalize performans, iyiden kötüye sıralı.

    `rows`: {"title", "category", "views", "uploaded_at"} sözlükleri.
    n < min_samples olan kategoriler elenir — üç videodan ayar çıkarılmaz.
    """
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in _with_index(rows):
        by_cat[(r.get("category") or "?")].append(r)

    out = []
    for cat, items in by_cat.items():
        if len(items) < min_samples:
            continue
        out.append({
            "category": cat,
            "n": len(items),
            "index": round(st.median(x["index"] for x in items), 2),
            "median_views": int(st.median(x["views"] for x in items)),
        })
    out.sort(key=lambda x: -x["index"])
    return out


def worn_phrases(rows: Iterable[dict], *, min_uses: int = _MIN_USES,
                 worn_below: float = 0.9) -> list[dict]:
    """Manşetlerde sık geçen kelimelerin performansı, kötüden iyiye sıralı.

    Klişe yıpranmasını elle aramak yerine kanalın kendi başlıklarından bulur:
    çok kullanılıp ortalamanın altında kalan kelime `worn=True` işaretlenir.
    """
    indexed = _with_index(rows)
    by_word: dict[str, list[float]] = defaultdict(list)
    for r in indexed:
        kelimeler = {
            w for w in re.findall(r"\w+", _fold(r.get("title") or ""))
            if len(w) > 2 and w not in _STOPWORDS and not w.isdigit()
        }
        for w in kelimeler:
            by_word[w].append(r["index"])

    out = []
    for word, indices in by_word.items():
        if len(indices) < min_uses:
            continue
        idx = round(st.median(indices), 2)
        out.append({
            "phrase": word,
            "uses": len(indices),
            "index": idx,
            "worn": idx < worn_below,
        })
    out.sort(key=lambda x: x["index"])
    return out


def headline_truncation_rate(rows: Iterable[dict]) -> dict[str, Any]:
    """Manşetlerin ne kadarı kırpma işaretiyle bitiyor.

    Yüksek oran, prompt'taki karakter bütçesinin şablonun gerçek görsel
    kapasitesini aştığını gösterir (ölçüldüğünde galatasaray %59, fenerbahce
    %52 idi; prompt 25 diyordu, stadium ~10 alıyordu).
    """
    rows = list(rows)
    total = len(rows)
    if not total:
        return {"rate": 0.0, "truncated": 0, "total": 0}
    kesik = sum(1 for r in rows if "…" in (r.get("title") or ""))
    return {"rate": round(kesik / total, 3), "truncated": kesik, "total": total}


# Kota eşiği: bu endeksin altındaki konu "kanıtlı zayıf" sayılır. Kota ancak
# performansı düşük konuya konur — en çok üretilene DEĞİL. Gerçek hata buydu:
# ilk kota en çok üretilen konuya konuldu, oysa o konu iki kanalda da ortalama
# performanslıydı (GS 0.99, FB 1.07) ve kısıtlamak üretimi daha zayıf konulara
# itti (kadro-karari 0.63).
_QUOTA_INDEX_THRESHOLD = 0.85
_QUOTA_MIN_SAMPLES = 6


def load_channel_rows(eng, channel: str) -> list[dict]:
    """Kanalın yayınlanmış videolarını denetim biçiminde getir."""
    import json

    from sqlalchemy import select

    from short_bot.db import shorts, youtube_uploads, youtube_video_stats

    with eng.connect() as conn:
        rows = conn.execute(
            select(shorts.c.id, shorts.c.title, shorts.c.script_json,
                   youtube_uploads.c.video_id, youtube_uploads.c.uploaded_at)
            .select_from(shorts.join(
                youtube_uploads, youtube_uploads.c.short_id == shorts.c.id))
            .where(shorts.c.channel == channel)
            .where(youtube_uploads.c.status == "success")
        ).all()
        views_by_vid: dict[str, int] = {}
        if rows:
            stats = conn.execute(
                select(youtube_video_stats.c.video_id,
                       youtube_video_stats.c.snapshot_date,
                       youtube_video_stats.c.views)
                .where(youtube_video_stats.c.video_id.in_(
                    [r.video_id for r in rows if r.video_id]))
            ).all()
            latest: dict[str, str] = {}
            for s in stats:
                if s.video_id not in latest or s.snapshot_date > latest[s.video_id]:
                    latest[s.video_id] = s.snapshot_date
                    views_by_vid[s.video_id] = int(s.views or 0)

    out = []
    for r in rows:
        try:
            payload = json.loads(r.script_json or "{}") or {}
        except (TypeError, ValueError):
            payload = {}
        out.append({
            "short_id": r.id,
            "title": r.title or "",
            "category": payload.get("category") or "?",
            "views": views_by_vid.get(r.video_id),
            "uploaded_at": r.uploaded_at,
        })
    return out


def audit_channel(eng, channel: str) -> dict[str, Any]:
    """Kanalın ayarları için veriye dayalı rapor + öneriler.

    Elle yapılan analizi tekrarlanabilir kılar. Öneriler UYGULANMAZ; operatör
    görüp karar verir, çünkü küçük örneklem yanıltabilir.
    """
    rows = load_channel_rows(eng, channel)
    olculebilir = [r for r in rows if r["views"]]
    topics = topic_index(rows)
    quota = [
        {"category": t["category"], "index": t["index"], "n": t["n"],
         "suggested_limit": 1}
        for t in topics
        if t["index"] < _QUOTA_INDEX_THRESHOLD and t["n"] >= _QUOTA_MIN_SAMPLES
    ]
    return {
        "channel": channel,
        "sample_size": len(olculebilir),
        "topics": topics,
        "quota_suggestions": quota,
        "worn_phrases": [w for w in worn_phrases(rows) if w["worn"]][:10],
        "headline_truncation": headline_truncation_rate(rows),
    }
