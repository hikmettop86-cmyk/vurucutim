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

ÜÇ ŞEYİ ARA:

1. ABARTMA / YÜKSELTME — senaryo, konunun SÖYLEMEDİĞİ bir şeyi iddia ediyor mu?
   GERÇEK ÖRNEK (bu sistemde yaşandı): konu "kafein büyümeyi ENGELLER" diyordu,
   senaryo "bitkilerini ZEHİRLİYOR" yazdı. Engellemek ≠ zehirlemek. YANLIŞ.
   Benzer yükseltmeler: "nadiren" → "asla", "bağlantılı" → "sebep oluyor",
   "yavaşlatır" → "öldürür", "bazı" → "bütün".

2. BİLİMSEL HATA — senaryodaki herhangi bir iddia gerçekten yanlış mı?
   Bir ders kitabında bulunamayacak, uydurulmuş sayı/mekanizma/olay var mı?

3. MANŞET ÇELİŞKİSİ — kare-sıfır manşeti videonun SONUCUNU yalanlıyor mu?
   GERÇEK ÖRNEK: manşet "Doğal gübre olarak kahve telvesi" diyordu ama video
   "taze telve genç bitkilere ZARAR VERİR" diyor. Feed'de kaydıran biri manşeti bir
   ONAY sanır ve video ters çıkar.
   Manşet merak AÇABİLİR, soru SORABİLİR, cevabı SAKLAYABİLİR — ama videonun
   söylediğinin TERSİNİ İDDİA EDEMEZ.

ŞÜPHEDEYSEN SORUN YOK SAY. Yalnız NET hataları bildir — yanlış alarm her senaryoyu
boşuna yeniden yazdırır. Retorik vurgu ("inanılmaz", "şaşırtıcı") sorun DEĞİLDİR;
OLGUSAL yükseltme sorundur.

Sorun yoksa boş liste döndür.

SADECE JSON: {{"issues": [{{"claim": "<metinden BİREBİR alıntı>",
  "problem": "<TÜRKÇE tek cümle: ne yanlış>"}}]}}"""


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
