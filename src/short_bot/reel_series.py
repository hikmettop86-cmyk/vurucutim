"""SERİ / CLIFFHANGER MİMARİSİ — aboneliği bir RİCA olmaktan çıkarıp TAKASA çevirir.

TEŞHİS (çalışma belgesi, §3.1): "kendi kendine yeten video = abone olmak için sebep
yok". Videomuz tam cevabı veriyor, izleyici bilgiyi alıyor, merak KAPANIYOR — geriye
abonelikle çözülecek KARŞILANMAMIŞ bir ihtiyaç kalmıyor. Daha iyi bilgi bunu çözmez;
bu bir YAPI sorunudur.

ÇÖZÜM — ÖDENMİŞ TEPE + AÇIK KAPI. Video kendi vaadini TUTAR (tepe gelir, beğeni
tetiklenir: beğeni bir karar değil duygusal boşalmadır, boşalacak tepe yoksa beğeni
de yok). Tepeden HEMEN SONRA yeni ve SPESİFİK bir kapı açılır — ve o kapının cevabı
bir sonraki BÖLÜMDEDİR. Abone isteği artık "daha fazlası için abone ol" değil, bir
TAKAS: söz verilen cevap karşılığında abone.

Tepeyi ALIKOYMAK (videoyu tam ödeme anında kesmek) daha sert bir takas olurdu ama
videoyu sakatlar: tepe yoksa beğeni gelmez ve izleyici kandırıldığını hisseder.
Ödenmiş tepe + açık kapı, ikisini birden verir.

ARK: açılan kapı (``open_loop``) yalnız bir cümle değil, BİR SONRAKİ BÖLÜMÜN KONU
TOHUMUDUR. Konu planlaması böylece video düzeyinden ARK düzeyine çıkar. Ark sonsuza
kadar zincirlenmez — ``arc_max`` bölümden sonra kesilir ve konu bankasından taze bir
konu alınır (yoksa zincir kendi nişinden uzaklaşıp sürüklenir).

ZAMANLAMA (belge §3.3): cliffhanger cümlesi TEPEDEN HEMEN SONRA konuşulmalı — abone
çipinin ateşlendiği an (t≈peak+1.3sn) tam orasıdır. Sonda söylenirse istek, sözü
duyulmadan önce ekrana gelir ve takas çöker. Bu yüzden LLM'e cliffhanger'ı tepeden
SONRAKİ beat'in içine dokutuyoruz; ayrı bir segment açmıyoruz (segment indeksleri
tüm zincirde varsayım — hook=0, beat'ler=1..N, close=N+1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from short_bot.text_normalize import turkish_upper

# Ark bu kadar bölümden sonra kesilir. Zincir uzadıkça konu, kanalın nişinden
# uzaklaşır (her bölüm bir öncekinin kapısından doğuyor — sürüklenme birikimlidir).
DEFAULT_ARC_MAX = 3
# Rozet ve CTA tek satır: kadraja sığmalı (bkz. reel_subscribe.CTA_MAX_CHARS).
BADGE_MAX_CHARS = 28


@dataclass(frozen=True)
class EpisodePlan:
    """Bu koşuda üretilecek bölümün kimliği ve ark bağlamı."""
    episode_no: int          # kanal ömrü boyunca artan (feed kimliği: "#47")
    arc_pos: int             # bu arkın kaçıncı bölümü (1 = yeni ark)
    continue_from: str = ""  # bir önceki bölümün açtığı kapı (bu bölüm ONU ödemeli)
    enabled: bool = True

    @property
    def next_no(self) -> int:
        return self.episode_no + 1

    @property
    def is_new_arc(self) -> bool:
        return self.arc_pos <= 1


def plan_episode(last: dict | None, *, arc_max: int = DEFAULT_ARC_MAX) -> EpisodePlan:
    """Bir sonraki bölümü planla. ``last`` = kanalın en son bölüm kaydı (ya da None).

    Ark SÜRER eğer: önceki bölüm bir kapı açtıysa VE ark henüz ``arc_max``a
    ulaşmadıysa. Aksi hâlde yeni ark (konu bankasından taze konu gelir).
    """
    if not last:
        return EpisodePlan(episode_no=1, arc_pos=1)
    no = int(last.get("episode_no") or 0) + 1
    kapi = (last.get("open_loop") or "").strip()
    pos = int(last.get("arc_pos") or 1)
    if kapi and pos < max(1, arc_max):
        return EpisodePlan(episode_no=no, arc_pos=pos + 1, continue_from=kapi)
    return EpisodePlan(episode_no=no, arc_pos=1)


def episode_badge(series_title: str, episode_no: int) -> str:
    """Feed kimliği rozeti: "BİLİNMEYEN TARİH #47". Kare sıfırda görünür.

    Faceless kanalda FORMAT YÜZDÜR — izleyici seni yüzünden değil, feed'de tanıdığı
    biçimden hatırlar. Numara ayrıca serinin GERÇEK olduğunu kanıtlar: 47. bölüm
    varsa 48. de gelecektir, yani abonelik bir şey satın alır.
    """
    # turkish_upper ŞART: Python'un .upper()'ı 'i' → 'I' yapar, oysa Türkçede 'i'nin
    # büyüğü 'İ'dir. "BILINMEYEN TARIH" yazan bir marka rozeti, taşıması gereken
    # özenin yokluğunu ilan eder.
    t = turkish_upper((series_title or "").strip())
    if not t:
        return f"#{episode_no}"
    rozet = f"{t} #{episode_no}"
    if len(rozet) <= BADGE_MAX_CHARS:
        return rozet
    # Sığmıyorsa BAŞLIĞI kırp, numarayı ASLA — numara rozetin işlevidir.
    kuyruk = f"… #{episode_no}"
    return t[:max(1, BADGE_MAX_CHARS - len(kuyruk))].rstrip() + kuyruk


def trade_cta(next_no: int) -> str:
    """Abone isteği bir TAKASTIR: söz verilen cevap karşılığında abone.

    "Daha fazlası için abone ol" araştırmanın adıyla andığı ölü ifadedir (izleyicinin
    beyni onu YouTube beyaz gürültüsü olarak filtreliyor). Numara veren bir istek ise
    somut bir şey vaat eder ve ne zaman geleceğini söyler.
    """
    return f"#{next_no} yarın — ABONE OL"


def series_directive(plan: EpisodePlan, series_title: str) -> str:
    """Senaryo LLM'ine geçen seri yönergesi.

    İki iş yaptırır:
      1. Bu bölüm, önceki bölümün açtığı kapıyı ÖDEMELİ (ark sürüyorsa).
      2. Bu bölüm YENİ bir kapı açmalı (open_loop) ve o cümleyi TEPEDEN SONRAKİ
         beat'in içine dokumalı — abone çipi tam orada ateşleniyor.
    """
    if not plan.enabled:
        return ""
    t = (series_title or "İlginç Bilgiler").strip()
    satirlar = [
        f"Bu, '{t}' serisinin {plan.episode_no}. BÖLÜMÜ. Bir sonraki bölüm "
        f"{plan.next_no} numaralı olacak.",
    ]
    if plan.continue_from:
        satirlar.append(
            f"BU BÖLÜM BİR SÖZÜ ÖDÜYOR. Önceki bölüm izleyiciye şunu vaat etti:\n"
            f'  "{plan.continue_from}"\n'
            f"Videonun TEPESİ (peak_beat) tam olarak BU SÖZÜ ödemeli. İzleyici bu "
            f"cevap için abone oldu; başka bir şey anlatırsan takas bozulur ve bir "
            f"daha güvenmez.")
    satirlar.append(
        f"AÇIK KAPI — ZORUNLU. Bu bölüm kendi tepesini TAM ÖDER, ama kapanmaz: "
        f"tepenin AÇIĞA ÇIKARDIĞI yeni ve SPESİFİK bir konu bırakır; onun cevabı "
        f"{plan.next_no}. bölümdedir. Bu İKİ AYRI ÇIKTI ister:\n"
        f"\n"
        f"  1) 'open_loop' ALANI = BİR SONRAKİ BÖLÜMÜN KONUSU (konuşulmaz).\n"
        f"     Bu metin {plan.next_no}. bölümün üretim konusu olarak AYNEN kullanılacak.\n"
        f"     Bölüm numarası / 'sonraki bölümde' / 'anlatacağım' GİRMEZ — sadece konu.\n"
        f"     ✗ 'Bunun sırrını {plan.next_no}. bölümde açıklıyoruz.'\n"
        f"     ✓ 'Fener balığının ışığını üreten simbiyotik bakteri'\n"
        f"\n"
        f"  2) TEPEDEN SONRAKİ BEAT'İN METNİ = SÖYLENEN cliffhanger.\n"
        f"     Aynı konuyu ORADA, KENDİ SÖZCÜKLERİYLE an ve {plan.next_no}. bölüme "
        f"havale et. Kapanışta DEĞİL — abone isteği ekranda tam o anda beliriyor; "
        f"söz daha söylenmemişse istek boşa düşer.\n"
        f"     ✗ 'Ama hikâye burada bitmiyor.'   ← neyin geleceğini söylemiyor\n"
        f"     ✓ 'Ama o ışık balığın kendi değil — onu üreten bakteriyi "
        f"{plan.next_no}. bölümde anlatıyorum.'\n"
        f"\n"
        f"  İKİSİ AYNI KONUYU paylaşmalı (ortak sözcükler): alan konuyu ADLANDIRIR, "
        f"beat onu SÖYLER.")
    return "\n".join(satirlar)


# LLM "2. bölümde açıklıyoruz" gibi META dili open_loop alanına sızdırıyor (ölçüldü:
# ilk gerçek koşuda tam olarak bunu yaptı). O metin bir sonraki bölümün ÜRETİM KONUSU
# olarak kullanılıyor — içinde bölüm numarası ve "anlatıyoruz" geçen bir konu tohumu,
# senaryo yazıcısını yanıltır. Prompt'ta yasakladık; burada da TEMİZLİYORUZ.
# Karakter sınıfları HEM Türkçe HEM ASCII'yi tanır: LLM çıktısı normalde Türkçe
# ('bölümde') ama aksan temizliğinden geçmiş ya da ASCII yazılmış metinler de gelebilir.
_B = r"b[öo]l[üu]m"                                   # bölüm
_V = r"(anlat|a[çc][ıi]kl|g[öo]ster|s[öo]yl|payla[şs])"   # anlatacağım / açıklıyoruz / ...
# "… <konu> 2. bölümde açıklıyoruz." → sondaki HAVALE cümleciğini sök, konuyu bırak.
# Sona ÇAPALI ($): cümlenin ortasındaki masum bir 'anlat' kelimesini yemesin.
_META = re.compile(
    rf"\s*[—,;:-]*\s*"
    rf"(\d+\s*\.?\s*{_B}\w*|(bir\s+)?sonraki\s+{_B}\w*|yar[ıi]n)"
    rf"[^.]*?{_V}\w*\s*[.!?]?\s*$",
    re.IGNORECASE)
_TAIL = re.compile(r"[\s.,;:—-]+$")


def clean_open_loop(text: str) -> str:
    """Meta dili ayıkla: geriye KONUNUN KENDİSİ kalsın.

    'Ev kedilerinden iyi olmalarının bilimsel sırrını 2. bölümde açıklıyoruz.'
      → 'Ev kedilerinden iyi olmalarının bilimsel sırrı'   (konu tohumu)

    Temizlik sonrası çok az şey kalıyorsa (LLM cümlenin TAMAMINI meta yapmışsa)
    ham metni geri ver — yanlış kırpmaktansa gürültülü bir tohum yeğdir.
    """
    s = (text or "").strip()
    if not s:
        return ""
    kirpik = _TAIL.sub("", _META.sub("", s)).strip()
    if len(kirpik.split()) < 3:
        return s
    return kirpik
