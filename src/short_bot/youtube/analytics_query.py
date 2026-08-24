"""Yayın kokpitinin ölçüm katmanı — ham snapshot'lardan KARAR verilebilir sayılar.

Bu modülün varlık sebebi tek bir ölçüm tuzağı: **1. gün izlenmesi doğrudan
kıyaslanamaz.**

`youtube_video_stats` günde bir kez, sabit bir saatte (üretimde 00:00) yazılıyor.
"1. gün" ise TAKVİM günü. Dolayısıyla 08:00'de yüklenen bir videonun ilk okuması
16 saatlik, 21:00'de yüklenenin ki 3 saatlik birikimi gösteriyor — ve ikisi aynı
sütunda, aynı medyanla kıyaslanıyor.

ÖLÇÜLDÜ (2026-08-22, galatasaray n=356 / fenerbahce n=235; yalnız 7+ günlük
videolar, yani nihai izlenmesi oturmuş olanlar):

    ölçüm penceresi | 1. gün medyanı | NİHAİ medyan (kanal medyanına oran)
      0- 6 saat     |          7.955 |  0,98×
      6-12 saat     |         20.945 |  1,16×
     12-18 saat     |         22.964 |  1,01×

Nihai başarı kovalar arasında DÜZ; 1. gün okuması 2,9 kat oynuyor. Yani ham
kıyas, akşam yüklenen her videoyu sistematik olarak "başarısız" damgalıyordu —
üretimin yaklaşık üçte biri.

DÜZELTME: her video, ölçüm penceresi KENDİSİNE EN YAKIN videoların medyanıyla
kıyaslanır (`erken_olcek`). Düzeltme sinyali zayıflatmıyor, GÜÇLENDİRİYOR —
1. gün oranı ile nihai izlenme arasındaki Spearman rho (p < 0,0001):

    yöntem                 galatasaray   fenerbahce
    ham medyan                 +0,475      +0,638
    6 saatlik sabit kova       +0,521      +0,706
    komşuluk medyanı (K=31)    +0,626      +0,763

Sabit kova YETMEDİ: 0-6 saat kovasının içinde bile medyan 712'den (0-1 sa)
14.371'e (5-6 sa) çıkıyor. Kova kenarı nereye konursa konsun sorun bir alt
ölçekte tekrarlıyor; çözüm kova değil KOMŞULUK.

Düzeltilmiş oranın alt çeyreği nihai olarak 0,57×/0,36×, üst çeyreği
1,76×/2,27× alıyor — yani erken oran, nihai başarıyı üç ila altı kat ayırıyor.
Erken sinyal gerçek; yalnız doğru paydaya bölünmesi gerekiyordu.
"""
from __future__ import annotations

import bisect
import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

# ── ayarlar ──────────────────────────────────────────────────────────────────

#: Erken performans ölçeğinde kaç komşu videonun medyanı alınır.
#:
#: SABİT KOVA DENENDİ VE YETMEDİ. Altı saatlik kovalarla 0-6 aralığının içinde
#: medyan 712'den (0-1 sa) 14.371'e (5-6 sa) çıkıyor — yirmi kat. Gece yarısına
#: yakın yüklenen video, kendisinden beş kat uzun ölçülmüş videolarla aynı
#: paydaya bölünüyordu. Kovanın kenarı nereye konursa konsun bu sorun bir alt
#: ölçekte tekrar ediyor; çözüm kova değil KOMŞULUK.
#:
#: K, nihai izlenmeyi yordama gücüne göre seçildi (Spearman rho, yalnız 7+
#: günlük videolar):
#:      yöntem            galatasaray   fenerbahce
#:      ham medyan            +0,475      +0,638
#:      6 saatlik kova        +0,521      +0,706
#:      komşuluk K=25         +0,612      +0,760
#:      komşuluk K=31         +0,626      +0,763
#:      komşuluk K=41         +0,624      +0,750
#: 25-41 arası düz; 31 ikisinin de tepesine yakın.
KOMSULUK = 31

#: Bir medyanın yazılması için gereken en az ölçüm. Altındaysa medyan
#: HESAPLANMAZ ve None döner: uydurulmuş bir kıyas noktası, kıyas noktası
#: olmamasından kötüdür (90 izlenmelik İspanyolca videoyu galatasaray'ın
#: 17.848'ine bölmek "0,0×" veriyordu — hüküm değil, ölçü hatası).
MIN_ORNEK = 8

#: Kaç günden sonra bir videonun nihai izlenmesi oturmuş sayılır. Yörünge
#: ölçümü: izlenmenin %91'i 4. güne kadar geliyor, sonrası düz.
OLGUNLUK_GUN = 4

#: Yörünge eğrisinin çizildiği ufuk (gün).
YORUNGE_UFKU = 14

#: Karşılaştırmanın anlamlı olduğu en küçük grup. Ölçülmüş gürültü tabanından:
#: video başına medyan 4 abone, 20 videoluk grupla ancak %19+ fark ayırt
#: edilebiliyor (2026-08-18 permütasyon testi).
OLCUM_TABANI = 20


def saptanabilir_fark(n: int) -> float:
    """`n` videoluk bir grupta ayırt edilebilen en küçük fark (yüzde).

    İki ölçülmüş noktadan türetildi: n=20 → %19, n=40 → %13.
    """
    if n <= 0:
        return 100.0
    return 85.0 / (n ** 0.5)


@dataclass(frozen=True)
class ErkenOlcek:
    """Ölçüm penceresine göre yerel medyan eğrisi — erken performansın paydası.

    Bir videonun ilk okuması, penceresi KENDİSİNE EN YAKIN `k` videonun
    medyanına bölünür. Böylece 21 dakikalık bir ölçüm 21 dakikalık ölçümlerle,
    16 saatlik olan 16 saatliklerle kıyaslanır.
    """
    saatler: tuple[float, ...]      # artan sırada
    okumalar: tuple[int, ...]       # `saatler` ile aynı sırada
    k: int

    def __bool__(self) -> bool:
        return bool(self.saatler)

    @property
    def ornek(self) -> int:
        return len(self.saatler)

    @property
    def yerel_mi(self) -> bool:
        """Pencere düzeltmesi GERÇEKTEN etkin mi?

        Komşuluk havuzun tamamına eşitse her video aynı paydaya bölünür ve
        ölçek sessizce ham medyana döner. Sayı yine üretilir (yoklukta hiçbir
        şey göstermemekten iyidir) ama arayüz bunu düzeltilmiş sanmamalı.
        """
        return 0 < self.k < len(self.saatler)

    def medyan(self, saat: float) -> int | None:
        """`saat` penceresindeki bir videodan beklenen ilk okuma.

        Komşular MESAFEYE göre seçilir, indekse göre değil. İndeks üzerinden
        pencereyi ortalamak, iki yoğunluk kümesinin arasına düşen bir sorguda
        ikisinden de eşit sayıda alıyordu: 15,5 saatlik bir video, hepsi 16
        saatte ölçülmüş komşuları varken 3 saatliklerle karıştırılıyor ve
        medyan ikisinin ortasına düşüyordu.
        """
        if not self.saatler:
            return None
        i = bisect.bisect_left(self.saatler, saat)
        sol, sag = i - 1, i
        secilen: list[int] = []
        while len(secilen) < self.k and (sol >= 0 or sag < len(self.saatler)):
            if sol < 0:
                sagi_al = True
            elif sag >= len(self.saatler):
                sagi_al = False
            else:
                sagi_al = (self.saatler[sag] - saat) <= (saat - self.saatler[sol])
            if sagi_al:
                secilen.append(self.okumalar[sag]); sag += 1
            else:
                secilen.append(self.okumalar[sol]); sol -= 1
        return int(statistics.median(secilen))


# ── veri tipleri ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VideoOlcumu:
    """Bir yayınlanmış videonun kokpite giren bütün ölçüleri."""
    video_id: str
    short_id: int
    channel: str
    title: str
    duration_s: int | None
    uploaded_at: datetime

    views: int
    likes: int
    comments: int
    subscribers_gained: int
    avg_view_percentage: float
    avg_view_duration_s: float

    #: Yükleme sonrası 0..`YORUNGE_UFKU`. günün kümülatif izlenmesi (yoksa None).
    #: Hem satır grafiği (ilk 7 gün) hem kanal yörüngesi bundan çıkar — ikinci
    #: bir sorgu açmamak için tek yerde tutuluyor.
    yorunge: list[int | None] = field(default_factory=list)

    #: 1. günün okuması ve o okumanın GERÇEK penceresi (saat).
    ilk_okuma: int | None = None
    ilk_pencere_saat: float | None = None

    @property
    def yas_gun(self) -> float:
        """Videonun yaşı, gün.

        `uploaded_at` NAİF UTC (tablodaki damga). `datetime.now()` ise naif
        YEREL saat verir; ikisini çıkarmak yaşı yerel farkı kadar (Türkiye'de
        3 saat) ŞİŞİRİYORDU — video `OLGUNLUK_GUN` eşiğini 3 saat erken
        geçiyor, "oran henüz olgunlaşmadı" uyarısı vaktinden önce kalkıyordu.
        Aynı tuzak modül başlığında da yazıyor: panel eskiden UTC'yi yerel
        saatmiş gibi okuyordu.
        """
        simdi = datetime.now(timezone.utc).replace(tzinfo=None)
        return (simdi - self.uploaded_at).total_seconds() / 86400

    @property
    def olgun(self) -> bool:
        """Nihai izlenmesi oturmuş mu? Oturmadan `kat` hüküm sayılmaz."""
        return self.yas_gun >= OLGUNLUK_GUN

    @property
    def like_1k(self) -> float:
        return (self.likes / self.views * 1000) if self.views else 0.0


@dataclass(frozen=True)
class KanalOzeti:
    slug: str
    video_sayisi: int
    toplam_izlenme: int
    medyan_izlenme: int
    p90_izlenme: int
    toplam_begeni: int
    #: Gözlem penceresinde kazanılan abone / kazanılan bin izlenme
    #: (bkz. `abone_1k`). İki tuzağı birden atlatır: video satırındaki
    #: `subscribers_gained` 7 GÜNLÜK bir PENCERE metriğidir ve toplanınca
    #: kanalın gerçeğinin onda birini veriyordu; kümülatifi kümülatife bölmek
    #: ise geçmişi sıfırlanmış kanallarda 296 abone/1000 izlenme üretiyordu.
    abone_1k: float | None
    aboneler: int | None
    kanal_izlenmesi: int | None
    son_snapshot: str | None


# ── ham çekim ────────────────────────────────────────────────────────────────

_HAM_SQL = """
SELECT s.id            AS short_id,
       s.channel       AS channel,
       s.title         AS title,
       s.duration_s    AS duration_s,
       u.video_id      AS video_id,
       u.uploaded_at   AS uploaded_at,
       vs.snapshot_date        AS snapshot_date,
       vs.updated_at           AS updated_at,
       vs.views                AS views,
       vs.likes                AS likes,
       vs.comments             AS comments,
       vs.subscribers_gained   AS subscribers_gained,
       vs.avg_view_percentage  AS avg_view_percentage,
       vs.avg_view_duration_s  AS avg_view_duration_s
FROM youtube_uploads u
JOIN shorts s              ON s.id = u.short_id
JOIN youtube_video_stats vs ON vs.video_id = u.video_id
WHERE u.status = 'success'
"""
# `shorts.deleted_at` DENETLENMEZ: yayınlanmış videoların neredeyse hepsi
# operatörün listesinden silinmiştir; elemek tabloyu boşaltırdı.


def _zaman(x) -> datetime | None:
    if x is None:
        return None
    if isinstance(x, datetime):
        return x
    try:
        return datetime.fromisoformat(str(x))
    except ValueError:
        return None


def video_olcumleri(eng: Engine, *, channel: str | None = None) -> list[VideoOlcumu]:
    """Yayınlanmış her videonun tek satırlık ölçüsü — en taze snapshot'tan.

    Yörünge, ilk okuma ve ilk okumanın penceresi de burada hesaplanır: hepsi
    aynı satır kümesinden çıkıyor, ikinci bir sorgu gereksiz.
    """
    sql = _HAM_SQL + (" AND s.channel = :ch" if channel else "")
    with eng.connect() as conn:
        satirlar = conn.execute(text(sql), {"ch": channel} if channel else {}).all()

    gruplar: dict[str, list] = {}
    for r in satirlar:
        gruplar.setdefault(r.video_id, []).append(r)

    cikti: list[VideoOlcumu] = []
    for vid, rs in gruplar.items():
        rs.sort(key=lambda r: r.snapshot_date)
        son = rs[-1]
        yuklendi = _zaman(son.uploaded_at)
        if yuklendi is None:
            continue
        yukleme_gunu = yuklendi.date()

        yorunge: list[int | None] = [None] * (YORUNGE_UFKU + 1)
        ilk_okuma = ilk_pencere = None
        for r in rs:
            try:
                fark = (date.fromisoformat(r.snapshot_date) - yukleme_gunu).days
            except ValueError:
                continue
            if 0 <= fark <= YORUNGE_UFKU:
                yorunge[fark] = int(r.views or 0)
            if fark == 1 and ilk_okuma is None:
                # `updated_at` yeniden yazılabilir (elle "Stats güncelle" aynı
                # gün ikinci kez koşarsa). Sorun DEĞİL: izlenme sayısı da aynı
                # anda tazeleniyor, yani (pencere, okuma) çifti hep tutarlı —
                # yalnız pencere uzar, komşuluk ölçeği de onu doğru yerden
                # kıyaslar. Satır (video_id, snapshot_date) ile anahtarlı
                # olduğu için sonraki günlerin tazelemesi bu satıra dokunmaz.
                ilk_okuma = int(r.views or 0)
                olculdu = _zaman(r.updated_at)
                if olculdu is not None:
                    saat = (olculdu - yuklendi).total_seconds() / 3600
                    # 0-24 saat dışı = snapshot atlanmış ya da saat kaymış;
                    # pencere bilinmiyorsa KOVA SEÇİLMEZ, ham kıyasa düşülmez.
                    ilk_pencere = saat if 0 < saat <= 24 else None

        cikti.append(VideoOlcumu(
            video_id=vid, short_id=int(son.short_id), channel=son.channel,
            title=son.title or "", duration_s=son.duration_s, uploaded_at=yuklendi,
            views=int(son.views or 0), likes=int(son.likes or 0),
            comments=int(son.comments or 0),
            subscribers_gained=int(son.subscribers_gained or 0),
            avg_view_percentage=float(son.avg_view_percentage or 0.0),
            avg_view_duration_s=float(son.avg_view_duration_s or 0.0),
            yorunge=yorunge, ilk_okuma=ilk_okuma, ilk_pencere_saat=ilk_pencere,
        ))
    cikti.sort(key=lambda v: v.uploaded_at, reverse=True)
    return cikti


# ── pencere eşlemeli erken eşik ──────────────────────────────────────────────

def erken_olcek(olcumler: list[VideoOlcumu], *, k: int = KOMSULUK) -> ErkenOlcek:
    """Kanalın erken performans ölçeğini kurar.

    Havuzun tamamının medyanı kullanılamaz: ölçüm penceresine göre 1. gün
    okuması yirmi kat oynuyor ve bu oynama videonun kalitesinden değil,
    snapshot'ın ne zaman düştüğünden geliyor.

    `MIN_ORNEK` altında ÖLÇEK KURULMAZ (boş döner) — uydurulmuş bir payda,
    payda olmamasından kötüdür.
    """
    ciftler = sorted(
        (v.ilk_pencere_saat, v.ilk_okuma) for v in olcumler
        if v.ilk_okuma is not None and v.ilk_pencere_saat is not None
    )
    if len(ciftler) < MIN_ORNEK:
        return ErkenOlcek((), (), k)
    # KOMŞULUK VERİDEN KÜÇÜK KALMALI. `k` örneklem sayısına eşitlenirse
    # "komşuluk" bütün havuz olur ve ölçek sessizce ham medyana döner —
    # düzeltmenin tamamı kaybolur, üstelik fark edilmeden. Üçte bir tavanı
    # küçük kanallarda da yerelliği korur, `MIN_ORNEK` tabanı medyanı
    # dalgalanmaya bırakmaz.
    yerel = min(k, max(MIN_ORNEK, len(ciftler) // 3))
    return ErkenOlcek(tuple(s for s, _ in ciftler), tuple(o for _, o in ciftler), yerel)


def erken_oran(video: VideoOlcumu, olcek: ErkenOlcek) -> float | None:
    """Erken performans: ilk okuma ÷ aynı pencere komşuluğunun medyanı.

    None dönerse hüküm verilemez — okuma yok, pencere bilinmiyor ya da kanalda
    henüz ölçek kuracak kadar veri birikmemiş.
    """
    if video.ilk_okuma is None or video.ilk_pencere_saat is None:
        return None
    beklenen = olcek.medyan(video.ilk_pencere_saat)
    if not beklenen:
        return None
    return video.ilk_okuma / beklenen


# ── yörünge ──────────────────────────────────────────────────────────────────

def yorunge_medyani(olcumler: list[VideoOlcumu],
                    *, ufuk: int = YORUNGE_UFKU) -> dict[int, tuple[int, int]]:
    """Gün → (medyan kümülatif izlenme, örneklem). Sayfanın omurgası.

    Ölçüm (galatasaray, n≈390): 1. gün 17.848 · 2. gün 37.452 · 4. gün 47.297 ·
    14. gün 52.111. Yani ömür boyu izlenmenin %72'si ilk 48 saatte, %91'i ilk
    4 günde geliyor; 4. günden sonra eğri düz. Beklemenin bilgi değeri yok.

    Girdi olarak `video_olcumleri` çıktısını alır — yörünge zaten orada
    kurulmuş durumda ve on dört kanal için ayrı sorgu açmak gereksiz.
    """
    kovalar: dict[int, list[int]] = {}
    for v in olcumler:
        for gun, izlenme in enumerate(v.yorunge[:ufuk + 1]):
            if izlenme is not None:
                kovalar.setdefault(gun, []).append(izlenme)
    return {g: (int(statistics.median(vs)), len(vs))
            for g, vs in sorted(kovalar.items()) if len(vs) >= MIN_ORNEK}


# ── kanal özetleri ───────────────────────────────────────────────────────────

#: `abone_1k` hesaplanabilmesi için gözlem penceresinde birikmesi gereken en az
#: izlenme. Bin izlenmenin altında "bin izlenme başına" bir oran uydurmaktır.
_ABONE_1K_TABANI = 1_000


def abone_1k(seri: list) -> float | None:
    """Gözlem penceresinde KAZANILAN abone ÷ kazanılan izlenme (×1000).

    KÜMÜLATİFİ KÜMÜLATİFE BÖLMEK YANLIŞTI. `subscribers` ve `total_views`
    kanalın bütün ömrünü taşıyor; snapshot geçmişi kanalın ortasında başlamışsa
    (ya da kanal silinip yeniden doldurulmuşsa) pay ile payda aynı popülasyondan
    gelmiyor. Ölçülen sonuç: deutschland-klartext 164 abone / 553 izlenme →
    "296 abone/1000 izlenme". Aboneler o 553 izlenmeden gelmedi.

    Fark üzerinden hesaplanan oran bu tuzağa düşmez ve gerçek ölçümle örtüşüyor:
    galatasaray için 0,0925 (bağımsız Studio ölçümü 0,101).

    İki snapshot yoksa ya da izlenme artışı `_ABONE_1K_TABANI` altındaysa None —
    oran yok demek, sıfır ya da uydurma bir sayı demekten iyidir.
    """
    if len(seri) < 2:
        return None
    ilk, son = seri[0], seri[-1]
    izlenme_farki = int(son.total_views or 0) - int(ilk.total_views or 0)
    abone_farki = int(son.subscribers or 0) - int(ilk.subscribers or 0)
    if izlenme_farki < _ABONE_1K_TABANI or abone_farki < 0:
        return None
    return round(abone_farki / izlenme_farki * 1000, 3)


def _p90(sirali: list[int]) -> int:
    """90. yüzdelik — YAKIN SIRA (nearest-rank) yöntemi.

    Eskiden `sirali[int(n * 0.9)]` idi ve n=10'da 9. indisi, yani MAKSİMUMU
    veriyordu: 10 videolu bir kanalda "p90" sütunu en iyi videonun izlenmesini
    yazıyor, medyanla yan yana durunca dağılım olduğundan geniş görünüyordu.
    Yakın sıra ceil(0,9·n)-1 verir; n=10'da 8. indis.

    n < 10 iken p90 zaten maksimuma eşittir — bu yöntemin kusuru değil,
    örneklemin gerçeği. Tablo küçük örneklemi ayrıca "gürültü tabanı"
    sütununda işaretliyor.
    """
    if not sirali:
        return 0
    return int(sirali[max(0, math.ceil(0.9 * len(sirali)) - 1)])


def kanal_ozetleri(eng: Engine,
                   olcumler: list[VideoOlcumu] | None = None) -> list[KanalOzeti]:
    """Kanal başına toplam. `abone_1k` GÖZLEM PENCERESİNDEKİ FARK'tan gelir."""
    if olcumler is None:
        olcumler = video_olcumleri(eng)

    with eng.connect() as conn:
        kanal_satirlari = conn.execute(text("""
            SELECT channel, snapshot_date, subscribers, total_views
            FROM youtube_channel_stats ORDER BY channel, snapshot_date
        """)).all()
    seriler: dict[str, list] = {}
    for r in kanal_satirlari:
        seriler.setdefault(r.channel, []).append(r)
    kanal_son = {k: v[-1] for k, v in seriler.items()}

    gruplar: dict[str, list[VideoOlcumu]] = {}
    for v in olcumler:
        gruplar.setdefault(v.channel, []).append(v)

    cikti: list[KanalOzeti] = []
    for slug, vs in gruplar.items():
        izlenmeler = sorted(v.views for v in vs)
        k = kanal_son.get(slug)
        aboneler = int(k.subscribers) if k else None
        kanal_izlenmesi = int(k.total_views) if k else None
        cikti.append(KanalOzeti(
            slug=slug,
            video_sayisi=len(vs),
            toplam_izlenme=sum(izlenmeler),
            medyan_izlenme=int(statistics.median(izlenmeler)) if izlenmeler else 0,
            p90_izlenme=_p90(izlenmeler),
            toplam_begeni=sum(v.likes for v in vs),
            abone_1k=abone_1k(seriler.get(slug, [])),
            aboneler=aboneler,
            kanal_izlenmesi=kanal_izlenmesi,
            son_snapshot=k.snapshot_date if k else None,
        ))
    cikti.sort(key=lambda o: -o.toplam_izlenme)
    return cikti


def kanal_serisi(eng: Engine, *, channel: str, gun: int = 45) -> list[dict]:
    """Kanalın abone/izlenme snapshot dizisi (eskiden yeniye)."""
    esik = (date.today() - timedelta(days=gun)).isoformat()
    with eng.connect() as conn:
        satirlar = conn.execute(text("""
            SELECT snapshot_date, subscribers, total_views
            FROM youtube_channel_stats
            WHERE channel = :ch AND snapshot_date >= :esik
            ORDER BY snapshot_date
        """), {"ch": channel, "esik": esik}).all()
    return [{"d": r.snapshot_date, "subs": int(r.subscribers or 0),
             "views": int(r.total_views or 0)} for r in satirlar]


# ── hacim kaldıracı ──────────────────────────────────────────────────────────

def hacim_serisi(olcumler: list[VideoOlcumu], *, gun: int = 70) -> list[dict]:
    """Gün → (o gün yüklenen video sayısı, o videoların topladığı izlenme).

    Ölçüm (2026-08-18, n=157 permütasyon testi) izlenmeyi yordayan TEK
    değişkenin günlük üretim adedi olduğunu gösterdi: 5/gün → 208k, 8/gün →
    411k. Kategori (p=0,69), yükleme saati (p=0,15), başlık uzunluğu (p=0,45)
    ve seçim puanı (p=0,37) gürültü. Sayfa bu yüzden "en iyi saat" grafiği
    değil, HACİM grafiği gösterir.
    """
    gunler: dict[str, dict] = {}
    for v in olcumler:
        g = v.uploaded_at.date().isoformat()
        d = gunler.setdefault(g, {"g": g, "n": 0, "views": 0})
        d["n"] += 1
        d["views"] += v.views
    return [gunler[g] for g in sorted(gunler)][-gun:]


# ── dağılım ──────────────────────────────────────────────────────────────────

def dagilim_bantlari(olcumler: list[VideoOlcumu], *, bant: int = 25_000,
                     kova_sayisi: int = 10) -> list[int]:
    """İzlenme histogramı. İlk kova "<10 B", sonrası `bant` genişliğinde."""
    say = [0] * kova_sayisi
    for v in olcumler:
        i = 0 if v.views < 10_000 else min(kova_sayisi - 1, v.views // bant + 1)
        say[int(i)] += 1
    return say


# ── yardımcı defterler ───────────────────────────────────────────────────────

def trafik_karmasi(eng: Engine) -> dict[str, dict]:
    """`kv` defterindeki trafik ölçüleri (arama payı vs Shorts akışı)."""
    with eng.connect() as conn:
        satirlar = conn.execute(
            text("SELECT k, v FROM kv WHERE k LIKE 'traffic:%'")).all()
    cikti = {}
    for r in satirlar:
        try:
            cikti[r.k.split(":", 1)[1]] = json.loads(r.v)
        except (ValueError, IndexError):
            continue
    return cikti


def arama_terimleri(eng: Engine, *, limit: int = 60) -> list[dict]:
    with eng.connect() as conn:
        satirlar = conn.execute(text("""
            SELECT channel, term, views FROM youtube_search_terms
            ORDER BY views DESC LIMIT :lim
        """), {"lim": limit}).all()
    return [{"channel": r.channel, "term": r.term, "views": int(r.views or 0)}
            for r in satirlar]
