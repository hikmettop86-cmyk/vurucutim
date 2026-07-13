"""PLANLI ARK: seriyi keşfetmek yerine TASARLAMAK.

ZİNCİR (reel_series) NE YAPIYORDU: her bölüm bir kapı açıyor, o kapı bir sonrakinin
konusu oluyordu. Ark KEŞFEDİLİYORDU — nereye gideceğini kimse önceden bilmiyor. İki
zayıflığı var:
  • SAPMA BİRİKİMLİ. Her bölüm bir öncekinin kapısından doğduğu için küçük sapmalar
    üst üste biniyor; üçüncü bölümde kanal kendi nişinin dışına çıkabiliyor.
  • VAAT TEK ADIM. İzleyiciye "sıradakinde şunu anlatacağım" diyebiliyoruz, ama
    "bu 3 bölümlük bir seri ve sonunda şunu öğreneceksin" diyemiyoruz. Oysa asıl
    abone sebebi ikincisidir: bir SERİYE abone olunur, bir sonraki videoya değil.

PLANLI ARK: bankadan bir konu alınır ve TEK bir LLM çağrısıyla N bölümlük tutarlı
bir yaya bölünür. Plan panelde ONAYA düşer (kullanıcı görür, değiştirir, onaylar).
Sonra otomasyon bölüm bölüm üretir.

YAPISAL KAZANÇ: bir sonraki bölümün konusu PLANDA ZATEN YAZILI. Yani cliffhanger'ı
LLM UYDURMUYOR — sadece SÖYLÜYOR. Konu sapması imkânsız hâle geliyor, çünkü sapacak
bir yer yok.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field, field_validator

from short_bot.claude_cli import run_json
from short_bot.text_normalize import strip_non_turkish_diacritics

log = logging.getLogger(__name__)

MIN_ARC = 2
MAX_ARC = 6
TOPIC_MAX = 120
TITLE_MAX = 40


class ArcEpisode(BaseModel):
    """Arkın bir bölümü. ``topic`` üretim konusu, ``promise`` izleyiciye söylenen vaat."""
    topic: str = Field(min_length=8, max_length=TOPIC_MAX)
    promise: str = Field(default="", max_length=140)

    @field_validator("topic", "promise", mode="before")
    @classmethod
    def _norm(cls, v):
        return strip_non_turkish_diacritics(v).strip() if isinstance(v, str) else v


class ArcPlan(BaseModel):
    title: str = Field(min_length=3, max_length=TITLE_MAX)
    episodes: list[ArcEpisode] = Field(min_length=MIN_ARC, max_length=MAX_ARC)

    @field_validator("title", mode="before")
    @classmethod
    def _norm_title(cls, v):
        return strip_non_turkish_diacritics(v).strip() if isinstance(v, str) else v

    def topics(self) -> list[str]:
        return [e.topic for e in self.episodes]


def _prompt(topic: str, channel, n: int) -> str:
    niche = (getattr(getattr(channel, "generator", None), "topic", "") or channel.name)
    return f"""Sen bir YouTube Shorts SERİ PLANLAYICISISIN. Aşağıdaki tek konuyu,
{n} BÖLÜMLÜK tutarlı bir SERİYE böl.

KANAL NİŞİ: {niche}
BAŞLANGIÇ KONUSU: {topic}

=== NEDEN SERİ (bunu anlamadan iyi plan çıkmaz) ===
İzleyici bir VİDEOYA abone olmaz, bir SERİYE abone olur. Her bölüm kendi başına tam
bir video olmalı (kendi tepesi, kendi ödemesi) — AMA bir sonrakine somut bir BORÇ
bırakmalı. Seri, o borçların zinciridir.

=== KURALLAR ===
1. TIRMANIŞ: bölümler giderek daha ŞAŞIRTICI olmalı. En vurucu bilgi SON bölümde.
   İlk bölüme en iyi bilgiyi koyarsan geri kalanı yokuş aşağı olur.
2. HER BÖLÜM AYRI BİR SORU yanıtlar — aynı konunun farklı yüzleri değil, birbirinin
   ÜSTÜNE ÇIKAN sorular.
3. HER BÖLÜM KENDİ BAŞINA TAM: tek başına izleyen biri de doyar. Yarım bırakma.
4. KONULAR SOMUT VE ÜRETİLEBİLİR olmalı: her biri 40 saniyelik bir videonun konusu.
   Soyut başlık YASAK ("Kedilerin gizemi" ✗ / "Kedi kulağının 32 kası" ✓).
5. NİŞTEN ÇIKMA: {n} bölümün hepsi kanalın nişinde kalmalı.

Her bölüm için:
- "topic": o bölümün ÜRETİM KONUSU (bir cümle, somut, {TOPIC_MAX} karakteri geçmesin).
  Bölüm numarası / "sonraki bölümde" gibi meta dil GİRMEZ — sadece konu.
- "promise": bir ÖNCEKİ bölümün izleyiciye bu bölüm için vereceği söz (tek cümle).
  İlk bölümün promise'i BOŞ olur (ondan önce bölüm yok).

Ayrıca "title": serinin adı ({TITLE_MAX} karakteri geçmesin, 2-5 kelime).

SADECE JSON:
{{"title": "<seri adı>",
 "episodes": [{{"topic": "...", "promise": ""}}, ... tam {n} adet]}}"""


def validate_plan(plan: ArcPlan, *, n: int) -> ArcPlan:
    """Bölüm sayısını hedefe oturt; ilk bölümün vaadini BOŞALT.

    LLM istenen sayıyı tutturamayabiliyor. Fazlaysa SONDAN kırpmayız — SONDAKİ bölüm
    en vurucu olan; baştan kırpmak da tırmanışı bozar. Fazla bölümü ORTADAN atarız.
    Eksikse olduğu gibi kabul: kısa ama tutarlı bir ark, uydurulmuş bir bölümden iyidir.
    """
    eps = list(plan.episodes)
    while len(eps) > n and len(eps) > MIN_ARC:
        eps.pop(len(eps) // 2)      # ortadan at: ilk kanca ve son tepe korunur
    # İlk bölümün "promise"i anlamsız: ondan önce bir bölüm yok.
    if eps:
        eps[0] = ArcEpisode(topic=eps[0].topic, promise="")
    return ArcPlan(title=plan.title, episodes=eps)


def plan_arc(topic: str, *, channel, n: int, llm_call) -> "ArcPlan | None":
    """Konuyu N bölümlük bir arka böl. LLM hatası → None (çağıran zincire düşer)."""
    n = max(MIN_ARC, min(MAX_ARC, int(n)))
    try:
        raw = run_json(_prompt(topic, channel, n), ArcPlan,
                       claude_path=llm_call.claude_path, model=llm_call.model,
                       backend=llm_call.backend, api_key=llm_call.api_key,
                       retries=2, timeout_s=90)
    except Exception as e:   # noqa: BLE001
        log.warning(f"ark planlanamadı ({e})")
        return None
    plan = validate_plan(raw, n=n)
    log.info(f"  ark planlandı: '{plan.title}' — "
             + " | ".join(f"{i + 1}) {e.topic[:40]}" for i, e in enumerate(plan.episodes)))
    return plan


# --- SERİ BAŞLIĞI ÖNERİSİ ---------------------------------------------------

def _fallback_title(channel) -> str:
    """LLM'siz yedek: kanal adından 2-3 kelime. Kaba ama BOŞ başlıktan iyidir."""
    kelimeler = (channel.name or "").split()
    return " ".join(kelimeler[:3])[:TITLE_MAX].strip()


def suggest_series_title(channel, llm_call=None) -> str:
    """Kanal DNA'sından seri başlığı öner. LLM yoksa/hata verirse kanal adına düş."""
    dna = getattr(channel, "dna", None)
    if llm_call is None or dna is None:
        return _fallback_title(channel)
    persona = getattr(dna, "persona_summary", "") or ""
    niche = (getattr(getattr(channel, "generator", None), "topic", "") or channel.name)

    class _T(BaseModel):
        title: str = Field(min_length=3, max_length=TITLE_MAX)

    p = f"""Bu YouTube Shorts kanalı için bir SERİ ADI öner.

KANAL: {channel.name}
NİŞ: {niche}
KİMLİK: {persona}

Seri adı her videonun KARE SIFIRINDA rozet olarak görünecek: "SERİ ADI #47".
Bu yüzden:
- 2-4 KELİME. Uzun ad rozete sığmaz ({TITLE_MAX} karakter sınırı, numara da dahil).
- Bir SERİ adı gibi dursun, kanal adının kopyası gibi değil.
- Merak açsın, kategori bildirmesin.
  KÖTÜ: "Bilim Videoları"   ← etiket
  İYİ:  "Bilinmeyen Bilim"  ← bir şey vaat ediyor

SADECE JSON: {{"title": "<seri adı>"}}"""
    try:
        r = run_json(p, _T, claude_path=llm_call.claude_path, model=llm_call.model,
                     backend=llm_call.backend, api_key=llm_call.api_key,
                     retries=1, timeout_s=45)
        return strip_non_turkish_diacritics(r.title).strip()[:TITLE_MAX]
    except Exception as e:   # noqa: BLE001
        log.warning(f"seri başlığı önerilemedi ({e}) → kanal adına düşülüyor")
        return _fallback_title(channel)
