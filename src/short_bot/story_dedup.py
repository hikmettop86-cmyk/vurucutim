"""Aynı haberin ikinci kez video olmasını engelleyen SENARYO SONRASI kapı.

NEDEN VAR — mevcut dedup yanlış metni kıyaslıyor
─────────────────────────────────────────────────────────────────────────────
`dedup.filter_new` dört katman uyguluyor (GUID, bulanık başlık, RSS embedding,
üretilen-başlık embedding) ama DÖRDÜ DE adayı **RSS başlığından** okuyor.
Video RSS başlığını anlatmıyor: senaryo yazarı makalenin GÖVDESİNİ okuyup orada
ne varsa onu yazıyor. Ölçüldü (2026-08-22, galatasaray):

    #1783  RSS: "Uğurcan Çakır'dan Şampiyonlar Ligi için net mesaj"
           üretilen: "4-0 ERZURUM DEPLASMANI"

Yani filtre, videonun anlatacağı şeyi HİÇ görmüyor.

Sonuç: Metehan Baltacı'nın Gençlerbirliği'ne kiralanması 32 saat içinde ÜÇ KEZ
video oldu (#1738, #1818, #1825).

NEDEN EŞİK DÜŞÜRMEK ÇÖZMÜYOR
─────────────────────────────────────────────────────────────────────────────
Ölçüldü — üretilen manşetlerin kosinüsü:

    mükerrer çiftler          0,664 · 0,715
    aynı kanalda farklı haber medyan 0,408, ama MAKSİMUM 0,689

İki dağılım iç içe. Manşetler 2-5 kelime; ayırmaya yetmiyor. Gövde kelime
örtüşmesi de ayırmıyor (mükerrer 0,105-0,214, çarpışma 0,043-0,116).

NEDEN VARLIK ÇIKARIMI DA YETMİYOR
─────────────────────────────────────────────────────────────────────────────
Denendi: gövdeden ardışık büyük-harfli öbek çıkarmak Türkçede iyi ayırıyor
(üç Baltacı videosu "metehan baltacı"da buluşuyor, Erzurum çifti hiçbir şey
paylaşmıyor). Ama DİLE BAĞIMLI ve sessizce çöküyor:

    galatasaray   en sık öbek %4,3 — kulüp adı tek kelime, kendiliğinden eleniyor
    latidoblanco  "real madrid" %25-40 — kulüp adı İKİ kelime, her gövdede var
    nippon-hankyou HİÇ öbek yok — Japoncada büyük harf yok

Bu yüzden varlık çıkarımı KARAR MEKANİZMASI DEĞİL. Karar, son 72 saatin
senaryolarını okuyan bir yargıçta; varlık çıkarımı yalnızca aday çok olduğunda
hangilerinin yargıca gösterileceğini SIRALAR.

DOĞRULAMA (gerçek vakalarla, 2026-08-22): 4/4 doğru —
    Baltacı 3. kez → MÜKERRER (#1818)      Baltacı 2. kez → MÜKERRER (#1738)
    Erzurum farklı açı → geçti             Jelert ayrılığı → geçti
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

from pydantic import BaseModel, Field

from short_bot.claude_cli import run_json

log = logging.getLogger(__name__)

#: Kaç saat geriye bakılır. Ölçüldü: kaçan üç Baltacı videosu 32 saate
#: yayılmıştı; 72 saat onu rahat kapsıyor ve haber döngüsü zaten o kadar.
PENCERE_SAAT = 72

#: Yargıca en fazla kaç geçmiş hikâye gösterilir. Üstü hem istemi şişirir hem
#: modelin dikkatini dağıtır; altı gerçek mükerreri kaçırma riski.
EN_COK_ADAY = 12

#: Her geçmiş kaydın istemdeki uzunluğu. Manşet + gövdenin başı, olayı
#: tanımaya yetiyor.
OZET_KARAKTER = 300


@dataclass(frozen=True)
class GecmisHikaye:
    """Bu kanalın yakın geçmişte ürettiği bir video — yargıca gösterilen hâli."""
    short_id: int
    ozet: str


@dataclass(frozen=True)
class MukerrerKarari:
    """Yargının sonucu. `mukerrer_id` 0 ise mükerrer değil.

    `ozne` saga anahtarıdır ve mükerrerlikten BAĞIMSIZ döner: video geçse de
    kaydedilir. Aynı yargı çağrısı senaryoyu zaten okuyor, ayrı bir çağrıya
    gerek yok.
    """
    mukerrer_id: int = 0
    gerekce: str = ""
    ozne: str = ""

    def __bool__(self) -> bool:
        return self.mukerrer_id > 0


class _Karar(BaseModel):
    duplicate_of: int = Field(default=0)
    reason: str = Field(default="", max_length=300)
    subject: str = Field(default="", max_length=40)


_ISTEM = """You are the editor of a short-form news channel. Your job here is to stop
the channel from publishing the SAME news event twice.

Below is a NEW story we are about to publish, and the stories this channel ALREADY
published in the last {saat} hours.

Answer ONE question: does the NEW story make the SAME CORE CLAIM as one of the
published ones? Reject only if a viewer would say "this is the same video again".

Judge the CORE CLAIM, not the topic and not the wording.

  REJECT — same core claim:
    the same signing announced twice, the same score reported twice,
    the same decision announced twice. Different wording, angle or source
    does not make it a new story.

  ALLOW — these are DIFFERENT stories even though they share a topic:
    · ONE MATCH PRODUCES MANY STORIES. The result, a player's post-match quote,
      a pundit's criticism, the manager's comment and a player's scoring form
      are five different stories about one match. Only the SAME claim repeats.
    · A TRANSFER HAS STAGES: interest → official offer → clubs disagree →
      personal terms agreed → deal done → farewell. Each stage is NEW news.
      Reject only when the SAME stage is announced twice.
    · Any story that carries a development the published one does not have.

WHEN IN DOUBT, ALLOW. A wrongly rejected story costs the channel a whole video
for this run; a duplicate that slips through costs far less. Reject only when
you can name the single claim both stories make.

Also name the SUBJECT the new story is centred on — the person or club the news
is about. This is a saga key, not a label:
  · a person → SURNAME ONLY, lowercase, no accents ("baltaci", "leao", "lemina")
  · a club → short name, lowercase ("milan", "genclerbirligi")
  · NEVER the channel's own club — it appears in every story and is useless as a key
  · no clear single centre (a league round-up, a draw, several players at once)
    → empty string. Do not guess.
The same person must always be written the same way.

Return JSON: {{"duplicate_of": <id of the published story, or 0 if none>,
"reason": "<one short sentence, in English>",
"subject": "<surname or short club name, or empty>"}}

NEW STORY:
{yeni}

ALREADY PUBLISHED:
{gecmis}
"""


def hikaye_ozeti(script) -> str:
    """Senaryonun olayını tanıtan kısa özet — yargıca bu gider.

    Manşet + gövde: ikisi birlikte "ne oldu"yu taşıyor. Foto şeridi ve vurgular
    dışarıda; onlar aynı olayı başka kelimelerle tekrarlıyor ve istemi şişirmek
    dışında bir şey katmıyor.
    """
    ust = (getattr(script, "header_top", "") or "").strip()
    alt = (getattr(script, "header_bottom", "") or "").strip()
    govde = (getattr(script, "body_paragraph", "") or "").strip()
    return f"{ust} {alt} — {govde}"[:OZET_KARAKTER].strip()


# ── aday sıralaması ──────────────────────────────────────────────────────────

_KELIME = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)
_CUMLE = re.compile(r"[.!?…¡¿]+\s*")

#: Bir öbek son videoların bu kadarında geçiyorsa AYIRT EDİCİ DEĞİL, bağlamdır.
#: Ölçüldü: "real madrid" İspanyolca kanalın gövdelerinin %25-40'ında;
#: Türkçe kanallarda en sık öbek %4,3 ("can uzun" — gerçek bir oyuncu, onu
#: elemek istemeyiz). Eşik ikisinin arasında.
BAGLAM_ORANI = 0.20


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def isim_obekleri(metin: str) -> set[str]:
    """Gövdedeki ardışık büyük-harfli öbekler (≥2 kelime).

    Cümle başı ATLANIR: her cümle büyük harfle başlar, o bilgi taşımaz.
    Tek kelimelik adlar da atlanır — Türkçede kulüp adı ("Galatasaray") tek
    kelimedir ve her gövdede geçer.

    Büyük harfi olmayan yazı sistemlerinde (Japonca, Çince) BOŞ döner. Bu bir
    kusur değil, bilinen sınır: sıralama çöker, karar çökmez — yargıç yine de
    en yeni adayları görür.
    """
    out: set[str] = set()
    for cumle in _CUMLE.split(metin or ""):
        ks = _KELIME.findall(cumle)
        i = 0
        while i < len(ks):
            if i > 0 and ks[i][:1].isupper():
                grup = [ks[i]]
                j = i + 1
                while j < len(ks) and ks[j][:1].isupper():
                    grup.append(ks[j])
                    j += 1
                if len(grup) >= 2:
                    out.add(_fold(" ".join(grup)).split("'")[0])
                i = j
                continue
            i += 1
    return out


def adaylari_sirala(yeni_govde: str, gecmis: list[GecmisHikaye],
                    *, en_cok: int = EN_COK_ADAY) -> list[GecmisHikaye]:
    """Yargıca gösterilecek adayları seç: önce varlık paylaşanlar, sonra en yeniler.

    `gecmis` YENİDEN ESKİYE sıralı gelmeli. Liste `en_cok`u aşmıyorsa hiç
    sıralama yapılmaz — kırpma gerekmiyorsa varlık çıkarımının riskini almanın
    anlamı yok.
    """
    if len(gecmis) <= en_cok:
        return list(gecmis)

    obekler = {g.short_id: isim_obekleri(g.ozet) for g in gecmis}
    n = len(gecmis)
    sayac: dict[str, int] = {}
    for o in obekler.values():
        for x in o:
            sayac[x] = sayac.get(x, 0) + 1
    baglam = {x for x, k in sayac.items() if k / n >= BAGLAM_ORANI}

    yeni = isim_obekleri(yeni_govde) - baglam
    paylasan = [g for g in gecmis if (obekler[g.short_id] - baglam) & yeni]
    kalan = [g for g in gecmis if g not in paylasan]
    return (paylasan + kalan)[:en_cok]


# ── saga öznesi ──────────────────────────────────────────────────────────────

def _ozne_temizle(ham: str) -> str:
    """Yargıcın verdiği özneyi saga anahtarına indir.

    NEDEN SENARYODAN, PUANLAYICIDAN DEĞİL: puanlayıcı yalnız RSS BAŞLIĞINI
    görüyor ve Türkçe tıklama tuzağı başlıkçılığı ismi BİLE BİLE saklıyor —
    "Galatasaray'da bir ayrılık daha! Yeni takımı belli oldu", "sürpriz
    isimle yollar ayrılabilir", "Yıldız isim 6 milyon euroluk maaşa imza
    atacak", "Bir devrin sonu". Ölçüldü (2026-08-22): öznesi boş kalan sekiz
    videonun YEDİSİNDE isim başlıkta hiç geçmiyordu; hepsinde senaryonun
    `highlights` alanında geçiyordu. Yani anahtar başlıktan türetilemiyor.

    Sonucu somut: Baltacı transferinin üç videosundan İKİSİNDE (#1738, #1825)
    özne boştu ve saga cezası hiç tetiklenemedi.
    """
    ozne = (ham or "").strip()
    if not ozne:
        return ""
    from short_bot.topic_taxonomy import normalize_subject
    return normalize_subject(ozne)


# ── yargı ────────────────────────────────────────────────────────────────────

def mukerrer_mi(script, gecmis: list[GecmisHikaye], *,
                backend: str = "claude_cli", model: str = "default",
                api_key: str | None = None, claude_path: str = "claude",
                saat: int = PENCERE_SAAT,
                strict: bool = False) -> MukerrerKarari:
    """Yeni senaryo, yakın geçmişteki bir videoyla AYNI OLAYI mı anlatıyor?

    Geçmiş boşsa ya da yargı alınamazsa "mükerrer değil" döner: bu bir
    PENCERE, kapı değil — çeviri gibi, yokluğu üretimi durdurmamalı. Yanlış
    ELEME yanlış geçirmeden pahalıdır: kanal o koşuda videosuz kalır.

    ``strict``: hatayı yükselt (panelden elle çalıştırma / test için).
    """
    if not gecmis:
        return MukerrerKarari()
    ozet = hikaye_ozeti(script)
    if not ozet.strip(" —"):
        return MukerrerKarari()
    adaylar = adaylari_sirala(getattr(script, "body_paragraph", "") or "", gecmis)
    istem = _ISTEM.format(
        saat=saat, yeni=ozet,
        gecmis="\n".join(f"[{g.short_id}] {g.ozet}" for g in adaylar))
    try:
        karar = run_json(istem, _Karar, claude_path=claude_path, model=model,
                         backend=backend, api_key=api_key, retries=2, timeout_s=90)
    except Exception as e:  # noqa: BLE001 — pencere, kapı değil
        log.info(f"  mükerrerlik yargısı alınamadı ({e})")
        if strict:
            raise
        return MukerrerKarari()

    ozne = _ozne_temizle(karar.subject)
    gecerli = {g.short_id for g in adaylar}
    if karar.duplicate_of not in gecerli:
        # Model gösterilmeyen bir kimlik uydurduysa GÜVENME. Uydurulmuş bir
        # eşleşmeyle video elemek, mükerrer yayınlamaktan kötü.
        if karar.duplicate_of:
            log.info(f"  mükerrerlik yargısı listede olmayan kimlik verdi "
                     f"({karar.duplicate_of}) → yok sayıldı")
        return MukerrerKarari(ozne=ozne)
    return MukerrerKarari(karar.duplicate_of, (karar.reason or "").strip(), ozne)
