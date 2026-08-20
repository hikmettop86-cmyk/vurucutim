"""Gündem Yorum çeşitleme motoru — her video kendi biçiminde olsun.

GERÇEK VAKA (2026-08-20, kullanıcı bildirdi): Batrakov videosu şu iskelette çıktı —
"Bakın… KAP'a göre… Google Trends'te yirmi bin kişi aradı, aramalar yüzde üç yüz arttı…
Öte yandan… Bence risk var ama… Peki sizce bu transfer tutar mı?" Her video aynı sırayla
aynı kalıpları kullanınca izleyici "bunu yapay zekâ yazdı" diyor. İki kusur vardı:

1. ARAMA VERİSİNİ SESLİ SÖYLEMEK. Trends verisi konuyu SEÇMEK için var; videoda
   "yirmi bin kişi aradı" demek kimsenin umurunda değil ve otomasyonu ele veriyor.
   Artık prompt bunu YASAKLIYOR (bkz. narration_writer.BANNED_PHRASES).
2. TEK İSKELET. Sabit "olgu → bağlantı → denge → bence → peki sizce?" dizisi.
   Artık her video üç bankadan (açılış · yaklaşım · kapanış) çekiyor.

Seçim deterministik (aynı haber → aynı biçim, yeniden üretim tutarlı) ama SON
ÜRETİLENLERİ dışlar: art arda iki video aynı açılış/yaklaşımı kullanamaz.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

# --- Açılış: ilk cümle nasıl kurulur (hook) ----------------------------------------
OPENINGS: tuple[tuple[str, str], ...] = (
    ("soru", "Açılış CÜMLESİ bir soru olsun — izleyicinin kafasındaki soruyu sen sor. "
             "Klişe 'Peki …?' kalıbıyla değil, doğrudan."),
    ("sahne", "Açılışta olayın geçtiği ANI tarif et: yer, saat, kim ne yapıyor. "
              "Yorum sonra gelsin."),
    ("rakam", "Açılışta olayın en çarpıcı SAYISI olsun (tutar, süre, sayı) ve neden "
              "çarpıcı olduğunu tek cümlede söyle."),
    ("celiski", "Açılışta iki bilgiyi çarpıştır: 'X deniyordu, oysa Y oldu'."),
    ("itiraz", "Açılışta yaygın bir kanıya itiraz et: herkesin sandığı şeyin neden "
               "eksik olduğunu söyle."),
    ("sonuc", "Açılışta doğrudan SONUCU/hükmü söyle, gerekçesini arkadan getir."),
    ("kisisel", "Açılışta olayın izleyicinin hayatına dokunan tarafını söyle "
                "(cebine, gününe, mahallesine ne oluyor)."),
    ("alinti", "Açılışta olayın içindeki kişinin kendi sözünü aktar, sonra bağla."),
)

# --- Yaklaşım: videonun omurgası ----------------------------------------------------
ANGLES: tuple[tuple[str, str], ...] = (
    ("kronoloji", "Olayı sırayla anlat: ne oldu, sonra ne oldu, şimdi nerede. "
                  "Yorumu en sona sakla."),
    ("neden", "Asıl soruyu 'neden şimdi?' üzerine kur: bu olayı bugün mümkün kılan "
              "şey ne."),
    ("iki_taraf", "İki tarafın da hesabını anlat: kim ne kazanıyor, kim ne kaybediyor. "
                  "Sonunda hangisinin daha güçlü durduğunu söyle."),
    ("kiyas", "Olayı benzer bir örneğe yasla (kaynaklarda geçen bir önceki olay/sayı) "
              "ve farkı göster."),
    ("sonrasi", "Ağırlığı 'bundan sonra ne olur'a ver: hangi adım atılırsa ne değişir."),
    ("detay", "Herkesin atladığı KÜÇÜK ayrıntıyı merkeze al ve neden önemli olduğunu "
              "göster."),
    ("kim", "Olayın merkezindeki kişiyi/kurumu tanıt: ne yaptı, geçmişi ne, "
            "bu hamle ona benziyor mu."),
    ("soru_cevap", "İzleyicinin sorabileceği üç somut soruyu sırayla cevapla — "
                   "soruları yüksek sesle sormadan, cevapları akıcı anlat."),
)

# --- Kapanış: son cümle -------------------------------------------------------------
CLOSINGS: tuple[tuple[str, str], ...] = (
    ("hukum", "Kapanışta net ama adil bir hüküm ver. Soru sorma."),
    ("izle", "Kapanışta neyin izleneceğini söyle: hangi tarih/adım her şeyi belli edecek."),
    ("soru", "Kapanışta izleyiciye TEK gerçek soru sor — 'sizce ... mı?' kalıbını "
             "kullanmadan, somut bir tercih sorusu."),
    ("tersine", "Kapanışta açılıştaki cümleyi tersine çevir ya da yeni anlamıyla tekrarla."),
    ("sade", "Kapanışta yorum yapma: durumu tek cümlede sade biçimde bırak."),
    ("uyari", "Kapanışta gözden kaçan riski/koşulu hatırlat."),
    ("insan", "Kapanışta olayın insan tarafını hatırlat: bunun ucunda kim var."),
)


@dataclass(frozen=True)
class YorumVariation:
    opening_key: str
    opening: str
    angle_key: str
    angle: str
    closing_key: str
    closing: str

    @property
    def key(self) -> str:
        return f"{self.opening_key}/{self.angle_key}/{self.closing_key}"


def _idx(seed_text: str, salt: str, n: int) -> int:
    """Stabil, süreçten bağımsız indeks (hash() salt'lıdır, kullanılmaz)."""
    h = hashlib.sha1(f"{seed_text}:{salt}".encode("utf-8")).hexdigest()
    return int(h, 16) % n


def _pick(bank: tuple[tuple[str, str], ...], seed_text: str, salt: str,
          used: set[str]) -> tuple[str, str]:
    """Bankadan seç; son videolarda kullanılanları ATLA. Hepsi kullanıldıysa
    (banka tükendi) sıradan seçime döner — üretim asla durmaz."""
    start = _idx(seed_text, salt, len(bank))
    for step in range(len(bank)):
        cand = bank[(start + step) % len(bank)]
        if cand[0] not in used:
            return cand
    return bank[start]


def pick_variation(*, seed_text: str, recent: Sequence[str] = ()) -> YorumVariation:
    """``recent``: son videoların ``key`` değerleri (yeniden eskiye).

    Son 3 videonun açılışı/yaklaşımı ve son 2 videonun kapanışı dışlanır — daha
    geniş pencere bankaları tüketip çeşitliliği azaltıyor."""
    def _used(pos: int, window: int) -> set[str]:
        out = set()
        for k in list(recent)[:window]:
            parts = str(k).split("/")
            if len(parts) == 3 and parts[pos]:
                out.add(parts[pos])
        return out

    o = _pick(OPENINGS, seed_text, "opening", _used(0, 3))
    a = _pick(ANGLES, seed_text, "angle", _used(1, 3))
    c = _pick(CLOSINGS, seed_text, "closing", _used(2, 2))
    return YorumVariation(opening_key=o[0], opening=o[1], angle_key=a[0], angle=a[1],
                          closing_key=c[0], closing=c[1])
