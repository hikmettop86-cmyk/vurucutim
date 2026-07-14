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

from short_bot.lang_pack import BADGE_MAX_CHARS  # noqa: F401 — dışarıdan import ediliyor
from short_bot.text_normalize import locale_upper

# Ark bu kadar bölümden sonra kesilir. Zincir uzadıkça konu, kanalın nişinden
# uzaklaşır (her bölüm bir öncekinin kapısından doğuyor — sürüklenme birikimlidir).
DEFAULT_ARC_MAX = 3


@dataclass(frozen=True)
class EpisodePlan:
    """Bu koşuda üretilecek bölümün kimliği ve ark bağlamı."""
    episode_no: int          # kanal ömrü boyunca artan (feed kimliği: "#47")
    arc_pos: int             # bu arkın kaçıncı bölümü (1 = yeni ark)
    continue_from: str = ""  # bir önceki bölümün açtığı kapı (bu bölüm ONU ödemeli)
    enabled: bool = True
    # --- PLANLI ARK (bkz. reel_arc). Zincirde bunlar boştur. ---
    # Bir sonraki bölümün konusu PLANDA ZATEN YAZILI → LLM cliffhanger'ı UYDURMAZ,
    # SÖYLER. Konu sapması yapısal olarak imkânsız hâle gelir.
    next_topic: str = ""     # planın sıradaki bölümü ("" = son bölüm ya da zincir modu)
    arc_title: str = ""      # serinin adı (ilk bölümde ilan edilir)
    arc_total: int = 0       # arkın toplam bölüm sayısı (0 = plan yok)

    @property
    def next_no(self) -> int:
        return self.episode_no + 1

    @property
    def is_new_arc(self) -> bool:
        return self.arc_pos <= 1

    @property
    def is_planned(self) -> bool:
        return self.arc_total > 0

    @property
    def is_arc_finale(self) -> bool:
        """Planın SON bölümü mü? (sonrasında yeni ark / bankadan konu gelir)"""
        return self.is_planned and not self.next_topic


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


def episode_badge(series_title: str, episode_no: int, *, pack) -> str:
    """Feed kimliği rozeti: "BİLİNMEYEN TARİH #47". Kare sıfırda görünür.

    Faceless kanalda FORMAT YÜZDÜR — izleyici seni yüzünden değil, feed'de tanıdığı
    biçimden hatırlar. Numara ayrıca serinin GERÇEK olduğunu kanıtlar: 47. bölüm
    varsa 48. de gelecektir, yani abonelik bir şey satın alır.
    """
    # locale_upper ŞART. Türkçede: Python'un .upper()'ı 'i' → 'I' yapar, oysa 'i'nin
    # büyüğü 'İ'dir; "BILINMEYEN TARIH" yazan bir marka rozeti, taşıması gereken özenin
    # yokluğunu ilan eder. Ama Türkçe eşlemesini ALMANCAYA uygulamak da aynı derecede
    # yanlış: "Bier Garten" → "BİER GARTEN". Büyütme dile özgüdür.
    t = locale_upper((series_title or "").strip(), pack.lang)
    if not t:
        return f"#{episode_no}"
    rozet = f"{t} #{episode_no}"
    if len(rozet) <= BADGE_MAX_CHARS:
        return rozet
    # Sığmıyorsa BAŞLIĞI kırp, numarayı ASLA — numara rozetin işlevidir.
    kuyruk = f"… #{episode_no}"
    return t[:max(1, BADGE_MAX_CHARS - len(kuyruk))].rstrip() + kuyruk


def trade_cta(next_no: int, *, pack) -> str:
    """Abone isteği bir TAKASTIR: söz verilen cevap karşılığında abone.

    "Daha fazlası için abone ol" araştırmanın adıyla andığı ölü ifadedir (izleyicinin
    beyni onu YouTube beyaz gürültüsü olarak filtreliyor). Numara veren bir istek ise
    somut bir şey vaat eder ve ne zaman geleceğini söyler.

    Şablon dil paketinden gelir ve ÜRETİM ANINDA doğrulanmıştır (render edilmiş hâli
    ≤ CTA_MAX_CHARS) — burada kırpma yapılmaz.
    """
    return pack.trade_cta.format(no=next_no)


def series_directive(plan: EpisodePlan, series_title: str, *, pack) -> str:
    """Senaryo LLM'ine geçen seri yönergesi.

    İki iş yaptırır:
      1. Bu bölüm, önceki bölümün açtığı kapıyı ÖDEMELİ (ark sürüyorsa).
      2. Bu bölüm YENİ bir kapı açmalı (open_loop) ve o cümleyi TEPEDEN SONRAKİ
         beat'in içine dokumalı — abone çipi tam orada ateşleniyor.

    Yönerge METİNLERİ dil paketinde. Almanca kanalın anlatım LLM'ine Türkçe talimat ve
    Türkçe örnek cümle vermek dil sızıntısı davetiyesidir; pedagoji (ödenmiş tepe +
    açık kapı) her dilde korunur, cümleler o dilde yeniden yazılır.
    """
    if not plan.enabled:
        return ""
    t = (series_title or pack.default_series_title).strip()
    s = pack.series
    satirlar = [s.header.format(title=t, no=plan.episode_no, next_no=plan.next_no)]

    if plan.continue_from:
        satirlar.append(s.paying_promise.format(promise=plan.continue_from,
                                                no=plan.episode_no))

    # PLANLI ARKIN İLK BÖLÜMÜ SERİYİ İLAN EDER. İzleyici bir VİDEOYA abone olmaz, bir
    # SERİYE abone olur: "3 bölümlük bir seri" demek, tek adımlık bir vaatten çok daha
    # güçlü bir abone sebebidir.
    if plan.is_planned and plan.is_new_arc:
        satirlar.append(s.announce_arc.format(arc_title=plan.arc_title,
                                              arc_total=plan.arc_total,
                                              no=plan.episode_no))

    if plan.is_arc_finale:
        # Son bölüm: ödenmemiş vaat BIRAKMAZ (plan bitti) ama seri devam ediyor.
        satirlar.append(s.finale.format(arc_title=plan.arc_title,
                                        next_no=plan.next_no, no=plan.episode_no))
        return "\n".join(satirlar)

    if plan.next_topic:
        # PLANLI ARK: kapı UYDURULMAZ, planda YAZILI. LLM'in işi onu SÖYLEMEK.
        satirlar.append(s.planned_loop.format(next_no=plan.next_no,
                                              next_topic=plan.next_topic))
        return "\n".join(satirlar)

    # ZİNCİR MODU: plan yok → kapıyı LLM'in kendisi bulur.
    satirlar.append(s.chain_loop.format(next_no=plan.next_no))
    return "\n".join(satirlar)


# LLM "2. bölümde açıklıyoruz" gibi META dili open_loop alanına sızdırıyor (ölçüldü:
# ilk gerçek koşuda tam olarak bunu yaptı). O metin bir sonraki bölümün ÜRETİM KONUSU
# olarak kullanılıyor — içinde bölüm numarası ve "anlatıyoruz" geçen bir konu tohumu,
# senaryo yazıcısını yanıltır. Prompt'ta yasakladık; burada da TEMİZLİYORUZ.
#
# Örüntünün KENDİSİ dil paketinde (pack.meta_tail_pattern): Almanca "erkläre ich in
# Folge 48" Türkçe regex'e takılmaz ve o kirli metin bir sonraki bölümün konusu olur.
# Sona ÇAPALI ($): cümlenin ortasındaki masum bir 'anlat' kelimesini yemesin.
_TAIL = re.compile(r"[\s.,;:—-]+$")


def clean_open_loop(text: str, *, pack) -> str:
    """Meta dili ayıkla: geriye KONUNUN KENDİSİ kalsın.

    'Ev kedilerinden iyi olmalarının bilimsel sırrını 2. bölümde açıklıyoruz.'
      → 'Ev kedilerinden iyi olmalarının bilimsel sırrı'   (konu tohumu)

    Temizlik sonrası çok az şey kalıyorsa (LLM cümlenin TAMAMINI meta yapmışsa)
    ham metni geri ver — yanlış kırpmaktansa gürültülü bir tohum yeğdir.
    """
    s = (text or "").strip()
    if not s:
        return ""
    meta = re.compile(pack.meta_tail_pattern, re.IGNORECASE)
    kirpik = _TAIL.sub("", meta.sub("", s)).strip()
    if len(kirpik.split()) < 3:
        return s
    return kirpik
