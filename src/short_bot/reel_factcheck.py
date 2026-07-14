"""Anlatım OLGU DENETİMİ: senaryo, konuyu ABARTIYOR mu, UYDURUYOR mu?

GERÇEK HATA (Almanca kanal, short 795 — kare kare incelendi):
    konu bankasındaki cümle DOĞRUYDU:
        "Frischer Kaffeesatz um junge Pflanzen? Koffein HEMMT dort das Wachstum."
        (kafein büyümeyi ENGELLER — allelopati, bilimsel olarak doğru)
    ama ANLATIM onu yükseltti:
        "...der deine grünen Freunde im Topf langsam VERGIFTET."   (ZEHİRLİYOR)
        ekran kartı: "VERGIFTUNGSGEFAHR"                            (ZEHİRLENME TEHLİKESİ)
    Kafein bitkiyi zehirlemez. Bu YANLIŞ.

NEDEN OLDU: anlatım prompt'unda hook kuralları, beat yapısı, footage kuralları ve
klişe yasakları var — ama OLGUSAL SADAKAT diyen tek satır yoktu. Üstelik prompt
"TEPE → EN ŞOK EDİCİ bilgi" diyerek abartmayı fiilen TEŞVİK ediyordu.

KONU BANKASINDA doğrulama kapısı var (topic_propose.verify_topics) ve o kapı bu konuyu
doğru bulmuştu. Boşluk ANLATIMDAYDI: doğru bir konu, yanlış bir videoya dönüşebiliyor.

Kanalın otoritesi ÜRÜNÜDÜR; bir tek yanlış video onu yakar. O yüzden burada da bir
kapı var — ve prompt'a güvenmenin yetmediğini ölçtük.

İKİNCİ İŞ — KAPAK ÇELİŞKİSİ: aynı videoda kare-sıfır manşeti "KAFFEESATZ ALS
NATÜRLICHER DÜNGER" (doğal gübre olarak kahve telvesi) diyordu, oysa video tam TERSİNİ
söylüyor. Feed'de kaydıran biri onu bir ONAY sanır. Manşet merak açabilir, soru
sorabilir — ama videonun SONUCUNU YALANLAYAMAZ.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

from short_bot.claude_cli import run_json

log = logging.getLogger(__name__)

_LANG_NAMES = {"tr": "Türkçe", "en": "İngilizce", "de": "Almanca",
               "es": "İspanyolca", "fr": "Fransızca"}


class Issue(BaseModel):
    claim: str       # metindeki sorunlu ifade (BİREBİR alıntı)
    problem: str     # ne yanlış
    # "fact"  → anlatımda olgusal hata/abartma. CİDDİ: ısrar ederse üretim DURUR.
    # "cover" → yalnız kare-sıfır manşeti çelişiyor. TEK ALAN: onu yeniden üretiriz,
    #           videoyu ÖLDÜRMEYİZ. (Orantısızlık ölçüldü: 4 kelimelik bir manşet
    #           yüzünden 7 dakikalık bir üretim çöpe gitti.)
    kind: str = "fact"


class _Issues(BaseModel):
    issues: list[Issue]


def _prompt(topic: str, cover_title: str, text: str, lang: str) -> str:
    return f"""Bir YouTube Shorts senaryosunu OLGUSAL DOĞRULUK açısından denetle.

KONU (doğrulanmış, kaynak olgu budur):
{topic}

KARE-SIFIR MANŞETİ (feed'de görünen ilk şey):
{cover_title}

SENARYO ({lang}):
{text}

ÖNCE ŞUNU ANLA — NE ARAMIYORUZ:

Konu TEK CÜMLELİK BİR TOHUMDUR. Anlatımın İŞİ onu genişletmektir; 40 saniyelik bir
video tohum cümlesinden ibaret olamaz. Senaryonun konuda GEÇMEYEN ama DOĞRU olan
şeyler söylemesi BEKLENİR ve SORUN DEĞİLDİR.

  konu   : "su damlaları yaprakları yakar efsanesi yanlıştır"
  senaryo: "damlalar zarar vermeden çok önce buharlaşır"      ← tohumda YOK ama DOĞRU
                                                                → SORUN DEĞİL

Ölçüt "tohumda var mı" DEĞİL, "DOĞRU mu".

ÜÇ ŞEYİ ARA:

1. YANLIŞ İDDİA — senaryoda GERÇEKTEN YANLIŞ bir şey var mı?
   Uydurulmuş bir sayı, olmayan bir mekanizma, yaşanmamış bir olay?
   Bir ders kitabında ya da yerleşik bilgide karşılığı OLMAYAN bir iddia?

2. ABARTMA / YÜKSELTME — bir olguyu, onu YANLIŞ yapacak kadar şişirmiş mi?
   GERÇEK ÖRNEK (bu sistemde yaşandı): konu "kafein büyümeyi ENGELLER" diyordu,
   senaryo "bitkilerini ZEHİRLİYOR" yazdı. Engellemek ≠ zehirlemek. Bu YANLIŞ.
   Benzer yükseltmeler: "nadiren" → "asla", "bağlantılı" → "sebep oluyor",
   "yavaşlatır" → "öldürür", "bazı" → "bütün".
   DİKKAT: yükseltme ancak SONUCU YANLIŞ YAPIYORSA sorundur. Doğru kalan bir
   genişletme ya da retorik vurgu ("inanılmaz", "şaşırtıcı") SORUN DEĞİLDİR.

3. MANŞET ÇELİŞKİSİ — kare-sıfır manşeti videonun SONUCUNU yalanlıyor mu?
   GERÇEK ÖRNEK: manşet "Doğal gübre olarak kahve telvesi" diyordu ama video
   "taze telve genç bitkilere ZARAR VERİR" diyor. Feed'de kaydıran biri manşeti bir
   ONAY sanır ve video ters çıkar.
   Manşet merak AÇABİLİR, soru SORABİLİR, cevabı SAKLAYABİLİR — ama videonun
   söylediğinin TERSİNİ İDDİA EDEMEZ.

ŞÜPHEDEYSEN SORUN YOK SAY. Yalnız senaryoyu YANLIŞ yapan şeyleri bildir.

Şunlar SORUN DEĞİLDİR ve bildirilmemelidir:
  • konuda geçmeyen ama DOĞRU olan ek bilgi (anlatımın işi budur)
  • "çalışmalar gösteriyor", "araştırmalar" gibi genel atıflar — iddia DOĞRUYSA
  • retorik vurgu, merak dili, gerilim kurma
  • konunun ima ettiği ama açıkça yazmadığı doğru mekanizmalar

Bir yanlış alarm, sağlam bir videoyu boşuna yeniden yazdırır ya da üretimi öldürür.

Sorun yoksa boş liste döndür.

"kind" alanı: manşetle ilgiliyse "cover", anlatım metniyle ilgiliyse "fact".

SADECE JSON: {{"issues": [{{"claim": "<metinden BİREBİR alıntı>",
  "problem": "<TÜRKÇE tek cümle: ne yanlış>",
  "kind": "fact" | "cover"}}]}}"""


def check_narration(topic: str, *, cover_title: str, text: str, language: str,
                    claude_path: str = "claude", model: str = "default",
                    backend: str = "claude_cli", api_key: str | None = None,
                    invoke=None) -> list[Issue]:
    """Senaryodaki olgusal sorunlar. Boş liste = temiz.

    DENETİM ÇÖKERSE BOŞ LİSTE döner (üretim DURMAZ) — ama loglanır. Tek bir LLM
    arızası yüzünden video üretmemek, yanlış video üretmekten de kötü olurdu; ama
    sessiz kalmak kabul edilemez.
    """
    if not (text or "").strip():
        return []
    lang = _LANG_NAMES.get(language, "Türkçe")
    p = _prompt(topic, cover_title or "(yok)", text, lang)
    try:
        if invoke is not None:
            v = invoke(p, _Issues)
        else:
            v = run_json(p, _Issues, claude_path=claude_path, model=model,
                         backend=backend, api_key=api_key, retries=1, timeout_s=120)
    except Exception as e:   # noqa: BLE001 — denetim çökse de üretim durmamalı
        log.warning(f"  senaryo olgu denetimi çalışmadı ({e}) → atlanıyor")
        return []
    return [i for i in v.issues if (i.claim or "").strip()]


class _Cover(BaseModel):
    cover_title: str


def rewrite_cover_title(topic: str, *, text: str, bad_title: str, problem: str,
                        language: str, claude_path: str = "claude",
                        model: str = "default", backend: str = "claude_cli",
                        api_key: str | None = None, invoke=None) -> str:
    """Yalnız KARE-SIFIR MANŞETİNİ yeniden üret. Başarısızsa boş dizge.

    NEDEN AYRI (ölçüldü): manşet çelişkisi bütün üretimi ÖLDÜRÜYORDU. Gerçek koşu —
    konu "yapraklardaki su damlaları güneşte yakar EFSANESİ YANLIŞTIR" idi; model
    manşeti "SU DAMLASI TEHLİKE BAHÇE" yazdı (efsaneyi DOĞRUYMUŞ gibi ilan etti),
    iki denemede de düzeltemedi ve 7 dakikalık üretim çöpe gitti.

    Manşet TEK BİR ALAN. Anlatım metni sağlamsa videoyu öldürmek orantısızdır: o alanı
    hedefli bir çağrıyla yeniden üretiriz.
    """
    lang = _LANG_NAMES.get(language, "Türkçe")
    p = f"""Bir YouTube Shorts videosunun KARE-SIFIR MANŞETİNİ yaz.

VİDEONUN KONUSU:
{topic}

VİDEONUN ANLATIMI ({lang}):
{text}

REDDEDİLEN MANŞET: "{bad_title}"
NEDEN REDDEDİLDİ: {problem}

MANŞET KURALLARI:
- {lang} dilinde, 3-6 KELİME, BÜYÜK harfle basılacak. Nokta/emoji YOK.
- Feed'de izleyicinin gördüğü İLK ŞEY budur; video orada avuç içi kadar görünür.
- Merak AÇAR, cevabı VERMEZ.
- VİDEONUN SONUCUNU YALANLAYAMAZ. Manşet ile video aynı tarafta olmalı.

BİR EFSANEYİ YIKIYORSAN (bu videoda olduğu gibi): manşet efsaneyi DOĞRUYMUŞ GİBİ
İLAN EDEMEZ. Efsaneyi EFSANE OLARAK adlandır ya da onu SORGULA:
    ✗ "SU DAMLASI TEHLİKE BAHÇE"      ← efsaneyi doğru sayıyor; video tersini diyor
    ✓ "DER LUPEN-MYTHOS"              ← efsaneyi efsane olarak adlandırıyor
    ✓ "VERBRENNEN TROPFEN WIRKLICH?"  ← soruyor, cevabı saklıyor
Merak, efsaneyi ONAYLAMAKTAN değil SORGULAMAKTAN doğar.

SADECE JSON: {{"cover_title": "<{lang} 3-6 kelime>"}}"""
    try:
        if invoke is not None:
            v = invoke(p, _Cover)
        else:
            v = run_json(p, _Cover, claude_path=claude_path, model=model,
                         backend=backend, api_key=api_key, retries=2, timeout_s=90)
        return (v.cover_title or "").strip()
    except Exception as e:   # noqa: BLE001 — manşet videoyu öldürmez
        log.warning(f"  manşet yeniden üretilemedi ({e})")
        return ""


def fact_feedback(issues: list[Issue]) -> str:
    """Bulunan sorunları LLM'e BİREBİR göster. Soyut 'abartma' uyarısı işe yaramıyor;
    ne yaptığını alıntılayarak söylemek işe yarıyor (aşınmış-kalıp kapısında ölçüldü).
    """
    lines = "\n".join(f'  ✗ "{i.claim}"\n     → {i.problem}' for i in issues)
    return (f"\n\nHATA — OLGUSAL SADAKAT: Senaryonda konunun SÖYLEMEDİĞİ şeyler var:\n"
            f"{lines}\n"
            f"Kanalın OTORİTESİ ürünüdür; bir tek yanlış iddia onu yakar. Konuyu "
            f"ABARTMADAN, olduğu gibi anlat — merak ve gerilim ANLATIM BİÇİMİNDEN "
            f"gelir, olguyu şişirmekten değil. Kare-sıfır manşeti de videonun "
            f"sonucunu YALANLAYAMAZ. Yeniden yaz.\n")
