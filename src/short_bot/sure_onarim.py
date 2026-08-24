"""``shorts.duration_s`` geriye dönük onarımı.

Seslendirmeli kanallarda süre KART süresi (6) olarak kaydedilmişti; gerçek
videolar 24-49 saniyeydi (bkz. ``pipeline._yayinlanan_sure_s``). Kaynak
düzeltildi ama geçmiş satırlar yanlış kaldı: panel, akış ve analiz onları
okuyor.

Bu modül SADECE ölçebildiğini düzeltir:
  · dosyası diskte duran satırlar (yüklenip silinenlerin dosyası yok),
  · ffprobe süreyi okuyabiliyorsa,
  · fark eşiği aşıyorsa (kayan nokta yuvarlaması yüzünden değişiklik yapmaz).

Dosyası olmayan satır DEĞİŞTİRİLMEZ: uydurulmuş bir süre, yanlış süreden
kötüdür — yanlış olan hiç değilse ölçülebilir.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import Engine

from short_bot.db import shorts

#: Bu farkın altındaki sapma yuvarlamadır, kusur değil.
ESIK_S = 1.5


@dataclass(frozen=True)
class Onarim:
    short_id: int
    channel: str
    eski: int | None
    yeni: int


def _olc(yol: Path, ffprobe: str) -> float:
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(yol)],
            capture_output=True, text=True, timeout=20)
        return float((out.stdout or "0").strip() or 0)
    except Exception:  # noqa: BLE001 — okunamayan dosya atlanır
        return 0.0


def _cozumle(ham: str, kok: Path) -> Path:
    p = Path(ham)
    return p if p.is_absolute() else (kok / ham)


def onarim_listesi(eng: Engine, *, proje_koku: Path, ffprobe: str = "ffprobe",
                   limit: int | None = None,
                   olc=None) -> list[Onarim]:
    """Düzeltilecek satırlar — HİÇBİR ŞEY YAZMAZ.

    `olc` testler için: (Path) -> saniye.
    """
    olcum = olc or (lambda p: _olc(p, ffprobe))
    q = (select(shorts.c.id, shorts.c.channel, shorts.c.duration_s,
                shorts.c.file_path)
         .where(shorts.c.file_path.is_not(None))
         .order_by(shorts.c.id.desc()))
    if limit:
        q = q.limit(limit)
    cikti: list[Onarim] = []
    with eng.connect() as conn:
        satirlar = conn.execute(q).all()
    for r in satirlar:
        yol = _cozumle(r.file_path, proje_koku)
        if not yol.exists():
            continue
        sure = olcum(yol)
        if sure <= 0:
            continue
        if abs(sure - (r.duration_s or 0)) <= ESIK_S:
            continue
        cikti.append(Onarim(int(r.id), r.channel, r.duration_s, int(round(sure))))
    return cikti


def uygula(eng: Engine, onarimlar: list[Onarim]) -> int:
    """Listeyi yaz. Boş listede hiçbir sorgu koşmaz."""
    if not onarimlar:
        return 0
    with eng.begin() as conn:
        for o in onarimlar:
            conn.execute(shorts.update()
                         .where(shorts.c.id == o.short_id)
                         .values(duration_s=o.yeni))
    return len(onarimlar)
