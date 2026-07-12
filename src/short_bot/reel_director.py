"""AI video kurgucusu: anlatımı okuyup TUTARLI kurgu kararları verir.

SORUN: kurgu kararları (tempo/efekt/SFX/müzik/marker/renk/layout) seed'in SHA-1
hash'iyle küçük havuzlardan RASTGELE seçiliyordu — içerikten habersiz. Hüzünlü bir
konuya neşeli "ding" gelebiliyordu; her video aynı kalıba oturuyordu.

MİMARİ İLKE: **Kurgucu ÖNERİR, kod DOĞRULAR.** LLM uydurma değer/kategori üretse
bile çökertmez — ``validate_plan`` her alanı mevcut havuza karşı denetler, geçersizi
BOŞALTIR ve çağıran o alan için eski seed-hash davranışına düşer (fail-open).
LLM'e dosya adı VERİLMEZ, yalnız kategoriler verilir → dosya uyduramaz.

İŞ BÖLÜMÜ — her alan, CANLI ÖLÇÜMDE hangi mekanizma işe yarıyorsa ona verildi:

Kurgucuda (3 zıt konuda gerçekten ayrıştırdı):
  mood, cut_effect (3/3 farklı), music_mood (konuyu izledi), sfx_plan (3/3 farklı)

Seed-hash'te (kurgucu MOD ÇÖKÜŞÜNE gitti — sorulmuyor bile):
  cut_pacing  → flash-lite 3 zıt konuda da "medium" dedi; prompt'a açık ölçüt
                eklendi ("ortayı seçmek kolaycılıktır"), yine 3/3 "medium".
  layout      → 2 zıt konuda da "classic"
  marker_kit  → 2 zıt konuda da "spotlight"

İlke: LLM ayrım yapamadığı alanda bilgi KATMAZ, yalnız yanlılık katar — ve her
video aynı değeri alır, yani tam da kırmak istediğimiz parmak izini üretir.
Seed-hash orada çeşitliliği GARANTİ eder. Bir alanı kurgucuya vermeden önce
ölç: zıt konularda farklı cevap veriyor mu?
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

from short_bot.assets_library import MUSIC_MOOD_VOCAB
from short_bot.claude_cli import run_json
from short_bot.reel_variation import CUT_EFFECTS

log = logging.getLogger(__name__)

MOODS = ("tense", "curious", "epic", "calm", "dark", "upbeat")


def _music_moods(library_index: dict) -> list[str]:
    """Diskteki müzik klasörlerinden yalnız GERÇEK ruh halleri.

    assets/music/ altındaki her klasör ruh hali değil: pick_music orayı kanal
    klasörü olarak da kullanır (assets/music/<kanal-slug>/). Allowlist olmasa
    kurgucu bir bilim videosuna kanal marşı seçebilirdi.
    """
    return sorted(m for m in (library_index or {}).get("music", {})
                  if m in MUSIC_MOOD_VOCAB)


class EditPlan(BaseModel):
    """Kurgucunun ÖNERİSİ. Boş alan = "karar verme", çağıran seed-hash'e düşer.

    Aşağıdaki mod-çöküşü alanları şema gereği durur (LLM yine de doldurabilir) ama
    ``validate_plan`` onları HER ZAMAN boşaltır — bkz. modül başlığındaki iş bölümü.
    """
    mood: str = ""             # tense|curious|epic|calm|dark|upbeat
    cut_effect: str = ""       # flash|glitch|rgbsplit|lightleak
    music_mood: str = ""       # kütüphanedeki müzik ruh hallerinden biri
    sfx_plan: list[str] = []   # kesim başına KATEGORİ (dosya adı DEĞİL)
    reason: str = ""           # kısa Türkçe gerekçe (logda görünür)
    # Kurgucuya SORULMAYAN, seed-hash'e bırakılan alanlar (mod çöküşü ölçüldü):
    cut_pacing: str = ""
    marker_kit: list[str] = []
    layout: str = ""


def _prompt(narration, topic: str, n_cuts: int, sfx_cats: list[str],
            music_moods: list[str]) -> str:
    beats = "\n".join(f"  - {getattr(b, 'text', '')}" for b in narration.beats)
    return f"""Sen bir YouTube Shorts VİDEO KURGUCUSUSUN. Aşağıdaki videonun
kurgusunu belirle. Kararların İÇERİKLE UYUMLU olsun — hüzünlü bir konuya neşeli
ses, sakin bir konuya hızlı kesim koyma.

KONU: {topic}
HOOK: {narration.hook}
BEAT'LER:
{beats}
KAPANIŞ: {narration.close}

Bu videoda {n_cuts} kesim var. Her kesim için bir SFX KATEGORİSİ seç (çeşitli olsun,
hepsi aynı olmasın; vurucu anlarda "impact", geçişlerde "whoosh" gibi).

KULLANILABİLİR SFX KATEGORİLERİ: {", ".join(sfx_cats)}
KULLANILABİLİR MÜZİK RUH HALLERİ: {", ".join(music_moods)}
KESME EFEKTİ: {", ".join(CUT_EFFECTS)}

SADECE JSON:
{{"mood": "<{'|'.join(MOODS)}>",
 "cut_effect": "<efekt>",
 "music_mood": "<müzik ruh hali>",
 "sfx_plan": ["<kategori>", ... tam {n_cuts} adet],
 "reason": "<kurgu seçimini 1 cümleyle açıkla>"}}"""


def validate_plan(plan: EditPlan, *, library_index: dict, n_cuts: int) -> EditPlan:
    """Her alanı mevcut havuza karşı denetle; geçersizi BOŞALT (→ seed-hash fallback)."""
    sfx_cats = set((library_index or {}).get("sfx", {}))
    music_moods = set(_music_moods(library_index))

    mood = plan.mood if plan.mood in MOODS else ""
    effect = plan.cut_effect if plan.cut_effect in CUT_EFFECTS else ""
    mmood = plan.music_mood if plan.music_mood in music_moods else ""

    # sfx_plan: geçersiz kategorileri ele, sonra n_cuts'a normalize et
    cats = [c for c in (plan.sfx_plan or []) if c in sfx_cats]
    if cats and n_cuts > 0:
        cats = [cats[i % len(cats)] for i in range(n_cuts)]
    else:
        cats = []

    # cut_pacing/layout/marker_kit KASTEN boş → seed-hash çeşitliliği korunur.
    return EditPlan(mood=mood, cut_effect=effect, music_mood=mmood,
                    sfx_plan=cats, reason=plan.reason)


def plan_edit(narration, *, topic: str, n_cuts: int, library_index: dict,
              llm_call) -> "EditPlan | None":
    """Anlatımı okuyup kurgu planı üret. Kütüphane boş / LLM hatası → None.

    None dönünce çağıran TAMAMEN eski seed-hash varyasyonuna düşer (fail-open).
    """
    sfx_cats = sorted((library_index or {}).get("sfx", {}))
    music_moods = _music_moods(library_index)
    if not sfx_cats or not music_moods:
        log.info("kurgucu: kütüphane boş → seed-hash varyasyonu")
        return None
    try:
        raw = run_json(_prompt(narration, topic, n_cuts, sfx_cats, music_moods),
                       EditPlan, claude_path=llm_call.claude_path,
                       model=llm_call.model, backend=llm_call.backend,
                       api_key=llm_call.api_key, retries=1, timeout_s=60)
    except Exception as e:
        log.warning(f"kurgucu başarısız ({e}) → seed-hash varyasyonu")
        return None
    plan = validate_plan(raw, library_index=library_index, n_cuts=n_cuts)
    log.info(f"  kurgucu: mood={plan.mood or '-'} efekt={plan.cut_effect or '-'} "
             f"müzik={plan.music_mood or '-'} | {plan.reason[:70]}")
    return plan
