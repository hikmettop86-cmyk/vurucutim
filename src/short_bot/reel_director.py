"""AI video kurgucusu: anlatımı okuyup TUTARLI kurgu kararları verir.

SORUN: kurgu kararları (tempo/efekt/SFX/müzik/marker/renk/layout) seed'in SHA-1
hash'iyle küçük havuzlardan RASTGELE seçiliyordu — içerikten habersiz. Hüzünlü bir
konuya neşeli "ding" gelebiliyordu; her video aynı kalıba oturuyordu.

MİMARİ İLKE: **Kurgucu ÖNERİR, kod DOĞRULAR.** LLM uydurma değer/kategori üretse
bile çökertmez — ``validate_plan`` her alanı mevcut havuza karşı denetler, geçersizi
BOŞALTIR ve çağıran o alan için eski seed-hash davranışına düşer (fail-open).
LLM'e dosya adı VERİLMEZ, yalnız kategoriler verilir → dosya uyduramaz.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

from short_bot.claude_cli import run_json
from short_bot.reel_markers import MARKER_TYPES
from short_bot.reel_variation import CUT_EFFECTS, LAYOUTS

log = logging.getLogger(__name__)

PACINGS = ("fast", "medium", "slow")
MOODS = ("tense", "curious", "epic", "calm", "dark", "upbeat")


class EditPlan(BaseModel):
    mood: str = ""             # tense|curious|epic|calm|dark|upbeat
    cut_pacing: str = ""       # fast|medium|slow
    cut_effect: str = ""       # flash|glitch|rgbsplit|lightleak
    marker_kit: list[str] = []  # MARKER_TYPES alt kümesi
    layout: str = ""           # classic|lower_left|top_heavy
    music_mood: str = ""       # kütüphanedeki müzik klasörlerinden biri
    sfx_plan: list[str] = []   # kesim başına KATEGORİ (dosya adı DEĞİL)
    reason: str = ""           # kısa Türkçe gerekçe (logda görünür)


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
KESİM TEMPOSU: {", ".join(PACINGS)}
KESME EFEKTİ: {", ".join(CUT_EFFECTS)}
MARKER TÜRLERİ: {", ".join(MARKER_TYPES)}
LAYOUT: {", ".join(LAYOUTS)}

SADECE JSON:
{{"mood": "<{'|'.join(MOODS)}>",
 "cut_pacing": "<tempo>",
 "cut_effect": "<efekt>",
 "marker_kit": ["<1-2 marker türü>"],
 "layout": "<layout>",
 "music_mood": "<müzik ruh hali>",
 "sfx_plan": ["<kategori>", ... tam {n_cuts} adet],
 "reason": "<kurgu seçimini 1 cümleyle açıkla>"}}"""


def validate_plan(plan: EditPlan, *, library_index: dict, n_cuts: int) -> EditPlan:
    """Her alanı mevcut havuza karşı denetle; geçersizi BOŞALT (→ seed-hash fallback)."""
    sfx_cats = set((library_index or {}).get("sfx", {}))
    music_moods = set((library_index or {}).get("music", {}))

    mood = plan.mood if plan.mood in MOODS else ""
    pacing = plan.cut_pacing if plan.cut_pacing in PACINGS else ""
    effect = plan.cut_effect if plan.cut_effect in CUT_EFFECTS else ""
    layout = plan.layout if plan.layout in LAYOUTS else ""
    kit = [m for m in (plan.marker_kit or []) if m in MARKER_TYPES]
    mmood = plan.music_mood if plan.music_mood in music_moods else ""

    # sfx_plan: geçersiz kategorileri ele, sonra n_cuts'a normalize et
    cats = [c for c in (plan.sfx_plan or []) if c in sfx_cats]
    if cats and n_cuts > 0:
        cats = [cats[i % len(cats)] for i in range(n_cuts)]
    else:
        cats = []

    return EditPlan(mood=mood, cut_pacing=pacing, cut_effect=effect,
                    marker_kit=kit, layout=layout, music_mood=mmood,
                    sfx_plan=cats, reason=plan.reason)


def plan_edit(narration, *, topic: str, n_cuts: int, library_index: dict,
              llm_call) -> "EditPlan | None":
    """Anlatımı okuyup kurgu planı üret. Kütüphane boş / LLM hatası → None.

    None dönünce çağıran TAMAMEN eski seed-hash varyasyonuna düşer (fail-open).
    """
    sfx_cats = sorted((library_index or {}).get("sfx", {}))
    music_moods = sorted((library_index or {}).get("music", {}))
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
    log.info(f"  kurgucu: mood={plan.mood or '-'} tempo={plan.cut_pacing or '-'} "
             f"efekt={plan.cut_effect or '-'} müzik={plan.music_mood or '-'} "
             f"| {plan.reason[:70]}")
    return plan
