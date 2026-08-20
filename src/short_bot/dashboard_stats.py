"""Kokpit (dashboard) ekranını besleyen sorgular.

Buradaki her fonksiyon saf SQL/Engine üzerinde çalışır — Flask'a bağlı değildir,
bu yüzden doğrudan test edilebilir.

İKİ TUZAK bu modülün tamamını şekillendiriyor:

1. ``shorts.deleted_at`` "çöp" DEĞİL, operatörün KARARIDIR. Ölçülen akış:
   üret → incele → beğenirse YÜKLE ve listeden sil, beğenmezse doğrudan sil.
   Dolayısıyla ``deleted_at IS NULL`` sayan bir sayaç "üretim" değil "gelen
   kutusu" ölçer; operatör listeyi boşalttığında sıfıra düşer. Eski dashboard
   toplam/bugün/son-1-saat sayaçlarını böyle kuruyordu ve son 24 saatte 45
   video üretilmişken ekranda 0 · 0 · 0 yazıyordu. Üretim ölçülürken
   ``deleted_at``e BAKILMAZ; karar ayrı bir eksen olarak raporlanır
   (yayına giden / elenen / henüz incelenmemiş).

2. Bir short'un BİRDEN ÇOK yükleme satırı olabilir (başarısız deneme +
   yeniden yükleme; üretimde 9 short'un iki satırı var). Outer join o videoyu
   satır sayısı kadar çoğaltır ve tek video iki kez sayılır. Bu yüzden
   yüklenmişlik her yerde ``DISTINCT short_id`` alt sorgusuyla ölçülür.

Zaman damgaları: ``created_at``/``started_at`` naive **UTC** tutulur
(``db._utcnow()`` tz-aware UTC üretir, SQLite dialect'i tzinfo'yu düşürür).
Cron eşleşmesi bunu doğruluyor: ``0 */4`` kanalının koşuları 17:00 ve 21:00
UTC damgalı, yerel saatle 20:00 ve 00:00. Ekranda gösterilmeden önce
``to_local()`` ile çevrilirler — panel eskiden UTC'yi yerel saatmiş gibi
yazıyordu.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

# Bir koşu bu kadar süredir "running" görünüyorsa artık çalışmıyordur: panel
# yeniden başlatıldığında (ya da süreç öldüğünde) ``finish_run`` hiç
# çağrılmaz ve satır sonsuza dek "running" kalır. En uzun gerçek koşu
# (seslendirmeli + whisper hizalama) ölçülen en kötü hâlde ~13 dakika;
# 90 dakika onun çok üstünde, yanlış pozitif vermez.
STALE_RUN_MINUTES = 90


def _utcnow() -> datetime:
    """Naive UTC — tablodaki damgalarla aynı eksende."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(dt: datetime | None) -> datetime | None:
    """Tablodaki UTC damgasını yerel saate çevirir.

    Hem naive (yeni satırlar) hem tz-aware (bazı eski satırlar) girdiyi
    kabul eder — ikisi de üretimde mevcut.
    """
    if dt is None:
        return None
    aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return aware.astimezone()


def _cut(hours: float) -> str:
    """SQLite karşılaştırması için pencere başlangıcı."""
    return (_utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S.%f")


# --------------------------------------------------------------------------
# Üretim
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ChannelProduction:
    """Bir kanalın pencere içindeki üretimi ve o üretime dair KARAR."""
    slug: str
    produced: int
    uploaded: int      # YouTube'a gitti (panel üzerinden)
    pending: int       # henüz incelenmemiş — gelen kutusunda duruyor
    dropped: int       # yüklenmeden silindi (operatör elemiş)
    last_at: datetime | None   # UTC

    @property
    def decided(self) -> int:
        return self.uploaded + self.dropped

    @property
    def accept_rate(self) -> float | None:
        """Karar verilenlerin kaçta kaçı yayına gitti (0..1).

        Payda karar verilenlerdir, üretilenler değil: gelen kutusunda bekleyen
        video henüz ne kabul ne ret, onu paydaya koymak oranı sahte biçimde
        düşürür.
        """
        if self.decided == 0:
            return None
        return self.uploaded / self.decided


_PRODUCTION_SQL = """
SELECT s.channel                                                   AS slug,
       COUNT(*)                                                    AS produced,
       SUM(CASE WHEN ok.short_id IS NOT NULL THEN 1 ELSE 0 END)    AS uploaded,
       SUM(CASE WHEN ok.short_id IS NULL AND s.deleted_at IS NULL
                THEN 1 ELSE 0 END)                                 AS pending,
       MAX(s.created_at)                                           AS last_at
FROM shorts s
LEFT JOIN (SELECT DISTINCT short_id FROM youtube_uploads
           WHERE status = 'success') ok
       ON ok.short_id = s.id
WHERE s.created_at IS NOT NULL
  AND datetime(s.created_at) >= datetime(:cutoff)
GROUP BY s.channel
"""


def _parse_dt(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(raw), fmt)
        except ValueError:
            continue
    return None


def production_by_channel(eng: Engine, *, hours: float = 24) -> list[ChannelProduction]:
    """Pencere içinde kanal başına üretim + karar dağılımı, çoktan aza."""
    with eng.connect() as conn:
        rows = conn.execute(text(_PRODUCTION_SQL), {"cutoff": _cut(hours)}).all()
    out = []
    for r in rows:
        produced, uploaded, pending = int(r.produced), int(r.uploaded), int(r.pending)
        out.append(ChannelProduction(
            slug=r.slug,
            produced=produced,
            uploaded=uploaded,
            pending=pending,
            dropped=produced - uploaded - pending,
            last_at=_parse_dt(r.last_at),
        ))
    out.sort(key=lambda c: (-c.produced, c.slug))
    return out


@dataclass(frozen=True)
class ProductionSummary:
    produced: int
    uploaded: int
    pending: int
    dropped: int
    channels: list[ChannelProduction]

    @property
    def accept_rate(self) -> float | None:
        decided = self.uploaded + self.dropped
        return None if decided == 0 else self.uploaded / decided


def production_summary(eng: Engine, *, hours: float = 24) -> ProductionSummary:
    """Pencerenin toplamı + kanal kırılımı.

    Takvim günü YERİNE kayan pencere kullanılır: takvim sayacı gece yarısı
    sıfırlanıp sabahın erken saatlerinde ekranı boş gösteriyordu.
    """
    chans = production_by_channel(eng, hours=hours)
    return ProductionSummary(
        produced=sum(c.produced for c in chans),
        uploaded=sum(c.uploaded for c in chans),
        pending=sum(c.pending for c in chans),
        dropped=sum(c.dropped for c in chans),
        channels=chans,
    )


_TIMELINE_SQL = """
SELECT s.created_at                                       AS created_at,
       CASE WHEN ok.short_id IS NOT NULL THEN 1 ELSE 0 END AS uploaded
FROM shorts s
LEFT JOIN (SELECT DISTINCT short_id FROM youtube_uploads
           WHERE status = 'success') ok
       ON ok.short_id = s.id
WHERE s.created_at IS NOT NULL
  AND datetime(s.created_at) >= datetime(:cutoff)
"""


def hourly_production(eng: Engine, *, hours: float = 24) -> list[dict]:
    """Son `hours` saatin YEREL saat kovalarına dağılmış üretimi.

    Kovalama Python tarafında yapılır: SQLite'ın ``strftime``i UTC üzerinde
    çalışır ve kullanıcının gördüğü saatle üç saat kayardı.

    Dönen liste kronolojiktir — en eski kova başta — ve pencere boyunca
    üretim olmayan saatler de sıfır olarak yer alır, böylece şerit gerçek
    bir zaman ekseni olur.
    """
    with eng.connect() as conn:
        rows = conn.execute(text(_TIMELINE_SQL), {"cutoff": _cut(hours)}).all()

    buckets: dict[datetime, list[int]] = {}
    for r in rows:
        dt = to_local(_parse_dt(r.created_at))
        if dt is None:
            continue
        key = dt.replace(minute=0, second=0, microsecond=0)
        b = buckets.setdefault(key, [0, 0])
        b[0] += 1
        b[1] += int(r.uploaded)

    now_local = to_local(_utcnow())
    start = (now_local - timedelta(hours=hours)).replace(minute=0, second=0, microsecond=0)
    end = now_local.replace(minute=0, second=0, microsecond=0)

    out = []
    cur = start
    while cur <= end:
        produced, uploaded = buckets.get(cur, [0, 0])
        out.append({
            "hour": cur.hour,
            "at": cur,
            "produced": produced,
            "uploaded": uploaded,
            "other": produced - uploaded,
        })
        cur += timedelta(hours=1)
    return out


def daily_production(eng: Engine, *, days: int = 7) -> dict[str, list[int]]:
    """Kanal → son `days` günün günlük üretim sayıları (eskiden yeniye).

    Tablodaki mini grafiği besler. Gün sınırları YEREL tarihe göre çizilir.
    """
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT channel, created_at FROM shorts "
                 "WHERE created_at IS NOT NULL "
                 "  AND datetime(created_at) >= datetime(:cutoff)"),
            {"cutoff": _cut(days * 24)},
        ).all()

    today = to_local(_utcnow()).date()
    gunler = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    index = {g: i for i, g in enumerate(gunler)}

    out: dict[str, list[int]] = {}
    for r in rows:
        dt = to_local(_parse_dt(r.created_at))
        if dt is None:
            continue
        i = index.get(dt.date())
        if i is None:
            continue
        out.setdefault(r.channel, [0] * days)[i] += 1
    return out


# --------------------------------------------------------------------------
# Sağlık
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class StalledRun:
    id: int
    channel: str
    trigger: str
    started_at: datetime | None   # UTC


def stalled_runs(eng: Engine, *, minutes: int = STALE_RUN_MINUTES) -> list[StalledRun]:
    """Bitiş damgası hiç yazılmamış, çoktan ölmüş koşular.

    Navigasyondaki "N çalışıyor" rozeti bunları canlı sanıp sayıyordu; panel
    hiç boşta görünmüyordu. Gerçek bir arıza değiller ama gerçek bir yalanlar.
    """
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT id, channel, trigger, started_at FROM runs "
                 "WHERE status = 'running' "
                 "  AND datetime(started_at) < datetime(:cutoff) "
                 "ORDER BY started_at DESC"),
            {"cutoff": _cut(minutes / 60)},
        ).all()
    return [StalledRun(id=int(r.id), channel=r.channel,
                       trigger=r.trigger or "", started_at=_parse_dt(r.started_at))
            for r in rows]


def empty_runs(eng: Engine, *, days: int = 7) -> list[tuple[str, int]]:
    """Çökmeden, aday bulamadan biten koşular — kanal başına, çoktan aza.

    Hata sayacına düşmezler (``status`` 'failed' değil) ama bir kanalın
    sessizce hiçbir şey üretmemesinin en yaygın sebebidir.
    """
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT channel, COUNT(*) AS n FROM runs "
                 "WHERE status = 'no_candidates' "
                 "  AND datetime(started_at) >= datetime(:cutoff) "
                 "GROUP BY channel ORDER BY n DESC, channel"),
            {"cutoff": _cut(days * 24)},
        ).all()
    return [(r.channel, int(r.n)) for r in rows]


def failed_runs(eng: Engine, *, hours: float = 24, limit: int = 5) -> list[dict]:
    """Gerçekten çöken koşular, en yeniden eskiye."""
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT id, channel, trigger, started_at, error FROM runs "
                 "WHERE status = 'failed' "
                 "  AND datetime(started_at) >= datetime(:cutoff) "
                 "ORDER BY started_at DESC LIMIT :lim"),
            {"cutoff": _cut(hours), "lim": limit},
        ).all()
    return [{"id": int(r.id), "channel": r.channel, "trigger": r.trigger or "",
             "started_at": _parse_dt(r.started_at), "error": r.error or ""}
            for r in rows]


# --------------------------------------------------------------------------
# Karşılığı — YouTube
# --------------------------------------------------------------------------

def channel_growth(eng: Engine, *, days: int = 7) -> list[dict]:
    """Bağlı kanalların abone sayısı ve pencere içindeki artışı.

    Anlık görüntüler her gün alınmıyor (kanal yeni bağlanmış olabilir, panel
    kapalı kalmış olabilir); bu yüzden "en yeni" ve "penceredeki en eski"
    kayıt alınır ve artış ikisinin farkıdır. Tek kayıt varsa artış ``None``
    kalır — sıfır yazmak "büyüme durdu" gibi okunurdu.
    """
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT channel, snapshot_date, subscribers, total_views "
                 "FROM youtube_channel_stats "
                 "WHERE snapshot_date >= date('now', :delta) "
                 "ORDER BY channel, snapshot_date"),
            {"delta": f"-{days} days"},
        ).all()

    by_channel: dict[str, list] = {}
    for r in rows:
        by_channel.setdefault(r.channel, []).append(r)

    out = []
    for slug, snaps in by_channel.items():
        first, last = snaps[0], snaps[-1]
        out.append({
            "channel": slug,
            "subscribers": int(last.subscribers or 0),
            "total_views": int(last.total_views or 0),
            "delta": (int(last.subscribers or 0) - int(first.subscribers or 0))
                     if len(snaps) > 1 else None,
            "snapshot_date": last.snapshot_date,
        })
    out.sort(key=lambda d: -d["subscribers"])
    return out


def top_videos(eng: Engine, *, days: int = 7, limit: int = 5) -> list[dict]:
    """Pencerede en çok izlenen videolar, başlık ve kanalıyla.

    ``shorts`` join'i ``deleted_at``e BAKMAZ: yayınlanmış videoların neredeyse
    hepsi listeden silinmiştir (operatörün akışı), silinmişleri elemek bu
    tabloyu tamamen boşaltırdı.
    """
    with eng.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT v.video_id                       AS video_id,
                       MAX(v.views)                     AS views,
                       MAX(v.subscribers_gained)        AS subs,
                       MAX(v.avg_view_percentage)       AS pct
                FROM youtube_video_stats v
                WHERE v.snapshot_date >= date('now', :delta)
                GROUP BY v.video_id
                ORDER BY views DESC
                LIMIT :lim
            """),
            {"delta": f"-{days} days", "lim": limit},
        ).all()

        out = []
        for r in rows:
            meta = conn.execute(
                text("SELECT s.title AS title, s.channel AS channel "
                     "FROM shorts s JOIN youtube_uploads u ON u.short_id = s.id "
                     "WHERE u.video_id = :vid LIMIT 1"),
                {"vid": r.video_id},
            ).first()
            out.append({
                "video_id": r.video_id,
                "views": int(r.views or 0),
                "subs": int(r.subs or 0),
                "pct": float(r.pct or 0.0),
                "title": meta.title if meta else "(panelde kaydı yok)",
                "channel": meta.channel if meta else "",
            })
    return out


@dataclass(frozen=True)
class ViewRate:
    """Bir YouTube kanalının günlük izlenme kazancı.

    ``per_day`` None ise ``note`` NEDEN hesaplanamadığını söyler; boş bırakmak
    yerine sebebi yazmak bilinçli, çünkü ölçümün kendisi eksik olabiliyor
    (ölçüldü: on kanaldan yalnız ikisinde hesaplanabiliyordu).
    """
    per_day: int | None
    note: str
    stale: bool = False


# Son anlık görüntü bu kadar günden eskiyse sayı hâlâ gösterilir ama
# "eskimiş" diye işaretlenir — sessizce güncel sanılmasın.
VIEW_RATE_STALE_DAYS = 3


def channel_view_rate(eng: Engine, *, days: int = 30) -> dict[str, ViewRate]:
    """Kimlik slug'ı → günlük izlenme artışı.

    "Son 24 saat" DEĞİL, **günlük ortalama**: ``youtube_channel_stats``
    kümülatif toplam tutuyor ve anlık görüntüler her gün alınmıyor (ölçüldü:
    12, 14, 16, 17, 18, 20 Ağustos). En taze artış çoğu zaman iki günlük bir
    aralıktan çıkıyor, dolayısıyla "24 saat" yazmak yanlış olurdu. Aralık
    ``note`` içinde açıkça belirtilir.

    Anahtar KANAL SLUG'I DEĞİL KİMLİK SLUG'IDIR: iki format tek YouTube
    kanalını paylaşabiliyor (Klartext → Kompakt), istatistik de tektir.
    """
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT channel, snapshot_date, total_views "
                 "FROM youtube_channel_stats "
                 "WHERE snapshot_date >= date('now', :delta) "
                 "ORDER BY channel, snapshot_date"),
            {"delta": f"-{days} days"},
        ).all()

    by_channel: dict[str, list] = {}
    for r in rows:
        by_channel.setdefault(r.channel, []).append(r)

    bugun = to_local(_utcnow()).date()
    out: dict[str, ViewRate] = {}
    for slug, snaps in by_channel.items():
        if len(snaps) < 2:
            out[slug] = ViewRate(None, "tek ölçüm var, artış hesaplanamıyor")
            continue
        onceki, son = snaps[-2], snaps[-1]
        try:
            d0 = datetime.strptime(onceki.snapshot_date, "%Y-%m-%d").date()
            d1 = datetime.strptime(son.snapshot_date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            out[slug] = ViewRate(None, "ölçüm tarihleri okunamadı")
            continue

        aralik = (d1 - d0).days
        if aralik <= 0:
            out[slug] = ViewRate(None, "tek ölçüm var, artış hesaplanamıyor")
            continue

        fark = int(son.total_views or 0) - int(onceki.total_views or 0)
        gunluk = max(0, round(fark / aralik))
        yas = (bugun - d1).days
        if yas > VIEW_RATE_STALE_DAYS:
            out[slug] = ViewRate(gunluk, f"{d1.strftime('%d.%m')} tarihinden beri "
                                         "ölçüm yok", stale=True)
        else:
            gun_adi = "günde" if aralik == 1 else f"{aralik} günde"
            out[slug] = ViewRate(gunluk, f"son {gun_adi} ölçüldü")
    return out


def relative_time(dt: datetime | None, *, now: datetime | None = None) -> str:
    """UTC damgadan "47 dk önce" / "2 sa önce" / "11 gün önce".

    Eşikler: saat altında dakika (üretim az önce mi oldu), gün altında saat,
    üstünde gün. Panel eskiden ham saat yazıyordu ve o saat UTC'ydi —
    operatör 21:06 görüp yerel 00:06'yı hesaplamak zorunda kalıyordu.
    """
    if dt is None:
        return "hiç üretmedi"
    yerel = to_local(dt)
    simdi = now or to_local(_utcnow())
    dk = int((simdi - yerel).total_seconds() // 60)
    if dk < 1:
        return "az önce"
    if dk < 60:
        return f"{dk} dk önce"
    if dk < 1440:
        return f"{dk // 60} sa önce"
    return f"{dk // 1440} gün önce"


def minutes_since(dt: datetime | None) -> int | None:
    """`relative_time` ile aynı eksende dakika — eşik kıyasları için."""
    if dt is None:
        return None
    return int((to_local(_utcnow()) - to_local(dt)).total_seconds() // 60)


def last_production(eng: Engine) -> dict[str, datetime]:
    """Kanal → en son ne zaman video üretti (UTC), PENCEREDEN BAĞIMSIZ.

    Pencere içi üretimden türetmek bir hataydı: 24 saatte üretmemiş bir kanal
    "hiç üretmedi" görünüyordu, oysa iki gün önce üretmişti. "Son üretim"in
    işi zaten pencerenin DIŞINI göstermek — bir kanalın sustuğunu ancak
    böyle fark edersin.
    """
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT channel, MAX(created_at) AS son FROM shorts "
                 "WHERE created_at IS NOT NULL GROUP BY channel")
        ).all()
    out: dict[str, datetime] = {}
    for r in rows:
        dt = _parse_dt(r.son)
        if dt is not None:
            out[r.channel] = dt
    return out
