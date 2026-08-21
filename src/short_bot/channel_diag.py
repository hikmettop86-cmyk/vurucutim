"""Kanal teşhisi — kanal sayfası açılırken LLM ÇAĞIRMADAN ne söylenebilir.

NEDEN LLM YOK: kanal sayfası her açılışında bir LLM çağrısı hem yavaş (Claude
CLI her çağrıda yeni süreç açıyor, ölçüldü) hem gereksiz masraf. Buradaki
bulguların hepsi ÖLÇÜM: kaç gündür yayın yok, kaç koşu üretmeden bitti,
otomatik yükleme kapalıyken kaç video birikti. LLM yalnız kullanıcı bir şey
YAZINCA devreye girer.

NE ÖLÇÜLEMEZ (bilinçli boşluk): `shorts` tablosunda ve `script_json` içinde
PUAN alanı yok. Bu yüzden "elenenlerin kaçı yükleme eşiğinin hemen altındaydı"
sorusu bu şemadan cevaplanamaz ve öyle bir bulgu ÜRETİLMEZ. Uydurma sayı
üretmektense bulguyu hiç üretmemek doğrudur. Şemaya puan eklenirse buraya yeni
bir bulgu gelir.

ÇÖZÜMÜ OLMAYAN BULGU BİLDİRİLİR, DÜZELTİLMEZ: "11 gündür yayın yok" bir ayar
hatası değil, operatör kararıdır (kanal duracak mı, devam mı?). `duzeltme`
listesi boş kalır. Her şeye çözüm üreten bir asistan, çözümü olmayanı da
çözülmüş gösterir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

# Bu kadar gün yayın yoksa bildir. Kanalların çoğu günde 1-6 üretiyor; bir
# haftalık sessizlik operatörün fark etmesi gereken bir şeydir.
YAYIN_DURGUN_GUN = 7
# Bu kadar günün koşularına bakılır.
KOSU_PENCERE_GUN = 7
# Boş koşu oranı bunu aşarsa bildir. Haber akışının kuruduğu günler normaldir;
# yarıdan fazlası boşsa ayar sorunu.
BOS_KOSU_ORANI = 0.5
BOS_KOSU_MIN = 4          # bu sayının altında koşu varken oran anlamsız
# Otomatik yükleme kapalıyken bu kadar video birikmişse bildir.
BIRIKME_ESIGI = 5


@dataclass(frozen=True)
class Bulgu:
    """Tek bir teşhis.

    `duzeltme`: (alan_yolu, eski_deger, yeni_deger) üçlüleri. BOŞ liste
    "çözümü var ama ben veremem" değil, "bu bir ayar sorunu değil" demektir.
    """
    kod: str
    ozet: str
    gerekce: str
    duzeltme: list[tuple[str, object, object]] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cut(gun: int) -> str:
    """SQLite'ta saklanan naif-UTC damgalarıyla karşılaştırılabilir eşik."""
    return (_utcnow() - timedelta(days=gun)).strftime("%Y-%m-%d %H:%M:%S")


def _sayi(eng: Engine, sql: str, **p) -> int:
    with eng.connect() as c:
        return int(c.execute(text(sql), p).scalar() or 0)


def _yayin_durgun(eng: Engine, cfg) -> Bulgu | None:
    uretim = _sayi(eng, "SELECT COUNT(*) FROM shorts WHERE channel = :ch",
                   ch=cfg.slug)
    if not uretim:
        return None            # yeni kanal — "yayın yok" bir sorun değil

    with eng.connect() as c:
        son = c.execute(text("""
            SELECT MAX(u.uploaded_at) FROM youtube_uploads u
            JOIN shorts s ON s.id = u.short_id
            WHERE s.channel = :ch AND u.status = 'success'
        """), {"ch": cfg.slug}).scalar()

    if son:
        try:
            gun = (_utcnow() - datetime.fromisoformat(str(son)).replace(
                tzinfo=timezone.utc)).days
        except ValueError:
            return None
        if gun < YAYIN_DURGUN_GUN:
            return None
        ozet = f"{gun} gündür tek video yayınlanmadı"
        gerekce = (f"Kanal {uretim} video üretmiş ama son başarılı yükleme "
                   f"{gun} gün önce. Üretim çalışıyor, yayın durmuş.")
    else:
        ozet = "Hiç video yayınlanmamış"
        gerekce = (f"{uretim} video üretilmiş ama YouTube'a hiçbiri gitmemiş. "
                   f"Bağlantı yoksa kurulmalı, varsa yükleme elle yapılıyor demektir.")

    # Bilinçli olarak BOŞ: kanal duracak mı devam mı — bu operatör kararı.
    return Bulgu(kod="yayin_durgun", ozet=ozet, gerekce=gerekce, duzeltme=[])


def _yukleme_kapali(eng: Engine, cfg) -> Bulgu | None:
    yt = getattr(cfg, "youtube", None)
    if yt is not None and getattr(yt, "auto_upload", False):
        return None
    bekleyen = _sayi(eng, """
        SELECT COUNT(*) FROM shorts s
        WHERE s.channel = :ch AND s.deleted_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM youtube_uploads u
                          WHERE u.short_id = s.id AND u.status = 'success')
    """, ch=cfg.slug)
    if bekleyen < BIRIKME_ESIGI:
        return None
    return Bulgu(
        kod="yukleme_kapali",
        ozet=f"{bekleyen} video karar bekliyor, otomatik yükleme kapalı",
        gerekce=("Otomatik yükleme kapalıyken her video elle onaylanmayı bekler. "
                 "Biriken video, izleyiciye ulaşmayan üretimdir."),
        duzeltme=[("youtube.auto_upload", False, True)])


def _bos_kosu(eng: Engine, cfg) -> Bulgu | None:
    with eng.connect() as c:
        r = c.execute(text("""
            SELECT COUNT(*) AS toplam,
                   SUM(CASE WHEN short_id IS NULL THEN 1 ELSE 0 END) AS bos
            FROM runs
            WHERE channel = :ch AND started_at >= :kes AND ended_at IS NOT NULL
        """), {"ch": cfg.slug, "kes": _cut(KOSU_PENCERE_GUN)}).mappings().first()
    toplam, bos = int(r["toplam"] or 0), int(r["bos"] or 0)
    if toplam < BOS_KOSU_MIN or not bos or bos / toplam < BOS_KOSU_ORANI:
        return None

    duzeltme: list[tuple[str, object, object]] = []
    # İki gerçek kaldıraç var ve ikisi de kanalın kendi alanı. Hangisinin
    # önerileceği kanalın kaynağına bağlı: RSS'te tazelik penceresi, puan
    # eşiğinden daha sık boş koşuya sebep oluyor.
    if getattr(cfg, "content_source", "rss") in ("rss", "feed"):
        if cfg.max_age_hours and cfg.max_age_hours <= 24:
            duzeltme.append(("max_age_hours", cfg.max_age_hours,
                             cfg.max_age_hours * 2))
    if cfg.min_score > 5.0:
        duzeltme.append(("min_score", cfg.min_score, round(cfg.min_score - 1, 1)))

    return Bulgu(
        kod="bos_kosu",
        ozet=f"Son {KOSU_PENCERE_GUN} günde {toplam} koşunun {bos}'i üretmeden bitti",
        gerekce=("Koşu çalışıyor ama elinde aday kalmıyor: ya haber penceresi "
                 "çok dar, ya puan eşiği çok yüksek."),
        duzeltme=duzeltme)


def bulgular(eng: Engine, cfg) -> list[Bulgu]:
    """Kanalın teşhisi. LLM çağrısı YOK — hepsi ölçüm.

    Sıra kasıtlı: önce eyleme dönük olanlar, sonra karar isteyen.
    """
    out = [b for b in (_yukleme_kapali(eng, cfg),
                       _bos_kosu(eng, cfg),
                       _yayin_durgun(eng, cfg)) if b is not None]
    return out
