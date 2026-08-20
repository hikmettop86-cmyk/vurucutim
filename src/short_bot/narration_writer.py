"""LLM anlatım yazıcı: haber → Narration (hook + beat'ler + loop kapanışı)."""
from __future__ import annotations

from short_bot.claude_cli import run_json
import logging

from short_bot.fact_gate import unverified_claims
from short_bot.narration_lint import dangling_fragments, fragment_feedback
from short_bot.locale import LANGUAGE_NAMES
from short_bot.narration import Narration

log = logging.getLogger(__name__)

# Ölçülmüş anlatım hızı: ai33/ElevenLabs Türkçe sesi, speed=1.0 → 70 kelime
# 31.4 sn (2.23 kelime/sn). 2.5 varsayımı bütçeyi şişirip videoyu 67 sn'ye
# taşıyordu; 2.2 hedef 45-60 sn bandını tutturuyor.
WORDS_PER_SECOND = 2.2

# HIZ DİLE BAĞLI — Türkçe sabiti başka dilde SESSİZCE yanlış süre üretir; hata da
# vermez, video sadece hedefin dışına düşer.
#
# ÖLÇÜLDÜ (2026-08-09, gerçek koşular):
#   es, ses 'Juanka Dominguez':  90/29.2 = 3.08 | 110/39.5 = 2.78 | 102/38.7 = 2.64
#   tr, ses 'Mustafa Energetic': 103/52.1 = 1.98
# Hız hem içerikle (~%17) hem SESLE değişiyor: yukarıdaki 2.2 sabiti başka bir
# Türkçe sesle ölçülmüştü, Mustafa belirgin daha yavaş okuyor ve 35-50sn hedefi
# 52.1sn'ye taşıyordu. reel_narration'daki kanıtlanmış kural: bütçeyi EN YAVAŞ
# ölçüme göre kur — üst sınırın hedefi AŞMAMASI, kısa kalmaktan önemlidir
# (aşınca loop zorlaşır). Bu yüzden es'te ortalama (2.8) değil 2.64 yazılı.
WORDS_PER_SECOND_BY_LANG: dict[str, float] = {"es": 2.64, "tr": 1.98}


def words_per_second(language: str | None = None) -> float:
    """Bu dilin ölçülmüş anlatım hızı; ölçülmemişse Türkçe sabiti."""
    return WORDS_PER_SECOND_BY_LANG.get(language or "", WORDS_PER_SECOND)


def word_budget(target_duration_s: tuple[int, int],
                language: str | None = None) -> tuple[int, int]:
    """Hedef süre aralığından kelime bütçesi (min, max).

    `language` verilmezse Türkçe hızı kullanılır (mevcut çağıranların davranışı
    değişmesin diye).
    """
    wps = words_per_second(language)
    lo, hi = target_duration_s
    return int(lo * wps), int(hi * wps)


def build_narration_prompt(item, body: str, channel) -> str:
    voice = channel.voice
    lo_w, hi_w = word_budget(voice.target_duration_s, channel.language)
    lo_s, hi_s = voice.target_duration_s
    lang_name = LANGUAGE_NAMES.get(channel.language, "Turkish")

    return f"""You are writing a spoken-narration script for a {lo_s}-{hi_s} second
vertical short video. The narration will be read aloud by a text-to-speech voice
and every word will appear as karaoke subtitles.

WRITE IN: {lang_name}
NARRATOR PERSONA: {voice.persona}

NEWS HEADLINE: {item.title}
SOURCE: {getattr(item, "source", None) or "unknown"}
ARTICLE BODY:
{body[:3000]}

OUTPUT a JSON object with exactly these fields:
- "hook": the FIRST spoken sentence. It must create curiosity in under 2 seconds
  — a question or a shocking claim. Never start with "Bugün" / "Today" / a date.
- "beats": 3-5 narrative beats. Each beat is an object with:
    - "text": the spoken sentence(s) for that beat (10-400 chars)
    - "on_screen": a SHORT ALL-CAPS card shown while that beat is spoken
      (max 60 chars, 2-5 words, a fact/number/action — NOT a description of a photo)
- "loop_close": the LAST spoken sentence. CRITICAL: when the video loops back to
  the start, this sentence must read as a natural set-up for the hook. Do not say
  "abone ol", "subscribe", "in this video" or any meta phrase.
- "mood": one of "breaking" | "neutral" | "upbeat"

HARD RULES:
- TOTAL spoken words across hook + all beats + loop_close: between {lo_w} and {hi_w}.
- Plain spoken language. No markdown, no emoji, no stage directions, no brackets.
- Every claim must come from the article body. Invent nothing.
- Numbers should be written as they are spoken.

Return ONLY the JSON object."""


def _budget_feedback(actual: int, lo_w: int, hi_w: int) -> str:
    if actual > hi_w:
        return (f"\n\nKISALT: previous attempt had {actual} spoken words, "
                f"the limit is {hi_w}. Rewrite shorter, keep the same structure.\n")
    return (f"\n\nUZAT: previous attempt had only {actual} spoken words, "
            f"the minimum is {lo_w}. Add detail from the article body.\n")


def _fact_feedback(eksik: list[str]) -> str:
    return (
        "\n\nFACT ERROR — these names/numbers are in your narration but NOT in the "
        f"ARTICLE BODY: {', '.join(eksik)}.\n"
        "Rewrite. Use ONLY names, clubs and numbers that literally appear in the "
        "article body above. Your verdict/opinion is still REQUIRED, but an opinion "
        "must be about what the article says — it may not introduce a new person, "
        "club or figure. Do not replace them with other outside names either.\n"
    )


def write_narration(
    item,
    body: str,
    *,
    channel,
    claude_path: str = "claude",
    model: str = "default",
    backend: str = "claude_cli",
    api_key: str | None = None,
) -> Narration:
    """Anlatım senaryosu üretir; kelime bütçesi ve OLGU kapısından geçirir.

    Olgu kapısı (fact_gate): anlatımdaki her isim/sayı haberde geçmeli. Bir kez
    düzelttirilir; ikinci kez de uydurma varsa RuntimeError — video ÜRETİLMEZ.
    Prompt'taki "Invent nothing" kuralı tek başına yetmedi (bkz. fact_gate).
    """
    voice = getattr(channel, "voice", None)
    if voice is None:
        raise ValueError("write_narration: channel.voice tanımlı değil")

    lo_w, hi_w = word_budget(voice.target_duration_s, channel.language)
    prompt = build_narration_prompt(item, body, channel)

    def _uret(p: str) -> Narration:
        return run_json(p, Narration, claude_path=claude_path, model=model,
                        backend=backend, api_key=api_key, retries=3)

    narration = _uret(prompt)
    actual = narration.word_count()
    if not (lo_w <= actual <= hi_w):
        # Tek düzeltme turu. İkincisi de bütçe dışıysa kabul edilir —
        # süre zaten sesten okunur, bütçe sadece bir hedeftir.
        narration = _uret(prompt + _budget_feedback(actual, lo_w, hi_w))

    eksik = unverified_claims(narration.full_text(), body,
                              language=channel.language)
    if not eksik:
        return narration

    log.warning(f"[olgu] haberde geçmeyen isim/sayı: {eksik} → yeniden yazdırılıyor")
    narration = _uret(prompt + _fact_feedback(eksik))
    eksik = unverified_claims(narration.full_text(), body,
                              language=channel.language)
    if eksik:
        raise RuntimeError(
            f"anlatım haberde geçmeyen isim/sayı içeriyor: {', '.join(eksik)}. "
            f"İki denemede de düzelmedi — video üretilmedi (uydurma bilgi "
            f"yayınlamaktansa video çıkmasın).")
    log.info("[olgu] düzeltme turu temiz ✓")
    return narration


# ─── Gündem Yorum: tarafsız-ama-görüşlü yorumcu ──────────────────────────────
# Politika gerekçesi (2026-08-20 değerlendirmesi): tam otomatik "manşet + özet"
# YouTube'un inauthentic-content tanımına yakın. Bu anlatım üç şeyle ayrışır —
# birden çok KAYNAK adıyla olgu, kaynaklardan kurulan BAĞLANTI ve birinci tekil
# HÜKÜM + izleyiciye soru. "Çaktırmadan sevilecek" = propaganda değil, güven.

YORUM_PERSONA_TR = (
    "Sen Türkiye'nin gündemini yorumlayan, kimsenin adamı olmayan bir sokak bilgesisin. "
    "Taraf tutmazsın ama görüşsüz de değilsin: olayı sade anlatır, herkesin aklındaki soruyu "
    "sen sorar, kimsenin bağlamadığı bir noktayı bağlar, sonunda adil ama net bir hüküm "
    "verirsin. Vatandaşın tarafındasın — kurumların değil, partilerin değil. Hafif mizah "
    "olur, alay olmaz. Acı haberde saygılısın. Konuşma dili: kısa cümleler, 'bakın', 'şimdi', "
    "'bence'; spiker kalıpları yok ('açıklandı', 'bildirildi', 'kaydedildi')."
)


BANNED_PHRASES: tuple[str, ...] = (
    # ARAMA VERİSİ: konuyu seçer, KONUŞULMAZ. "yirmi bin kişi aradı" cümlesi
    # kimsenin umurunda değil ve videoyu otomasyon gibi gösteriyor (kullanıcı
    # bildirimi 2026-08-20, Batrakov videosu).
    "Google Trends", "arama hacmi", "kişi aradı", "aramalar yüzde", "aratıldı",
    "trend oldu", "gündeme oturdu", "sosyal medyada gündem",
    # AI-slop kalıpları: her videoda aynı yerde çıkan bağlaçlar/kapanışlar
    "Bakın,", "Şimdi,", "Öte yandan", "Yani,", "Peki sizce", "Sizce de",
    "Bence risk var ama", "Kısacası", "Sonuç olarak", "Özetle",
    "abone ol", "kanalımıza", "yorumlarda buluşalım",
)


def build_yorum_prompt(item, body: str, channel, *, extra_sources: list[tuple[str, str]],
                       variation=None) -> str:
    """Yorum anlatımı promptu. Çıktı şeması ``Narration`` ile aynı (hook/beats/
    loop_close/mood) — TTS/hizalama/render zinciri değişmeden kullanılır.

    ``variation`` (yorum_variation.YorumVariation): bu videonun açılış/yaklaşım/
    kapanış biçimi. Pipeline her videoda farklı bir biçim seçer; sabit iskelet
    "her video aynı" hissini veriyordu (kullanıcı bildirimi 2026-08-20).
    """
    voice = channel.voice
    lo_w, hi_w = word_budget(voice.target_duration_s, channel.language)
    lo_s, hi_s = voice.target_duration_s
    lang_name = LANGUAGE_NAMES.get(channel.language, "Turkish")
    primary_src = getattr(item, "source", None) or "unknown"

    extra_block = ""
    if extra_sources:
        parts = []
        for url, text in extra_sources:
            host = url.split("//")[-1].split("/")[0].removeprefix("www.")
            parts.append(f"--- {host} ---\n{text[:1500]}")
        extra_block = "\nADDITIONAL SOURCES (same story, other publishers):\n" + "\n".join(parts) + "\n"
        source_rule = ("- SOURCING: name an outlet ONLY when it earns it — a contested claim, an "
                       "exclusive, or an official statement. At most TWO such attributions in the "
                       "whole narration; everything else is plain narration. Never recite sources "
                       "one after another like a bibliography.")
    else:
        source_rule = ("- SOURCING: name the source at most once, only if the claim needs it; "
                       "do not invent other outlets.")

    shape = ""
    if variation is not None:
        shape = (
            "\nSHAPE OF THIS VIDEO (follow it; the next video gets a different one):\n"
            f"- OPENING: {variation.opening}\n"
            f"- SPINE: {variation.angle}\n"
            f"- CLOSING: {variation.closing}\n"
        )

    from short_bot.followup import followup_block as _followup_block
    followup = _followup_block(item)

    banned = ", ".join(f'"{p}"' for p in BANNED_PHRASES)

    return f"""You are writing a spoken commentary script for a {lo_s}-{hi_s} second vertical
short video. A text-to-speech voice reads it; the news card stays on screen while a
short caption per beat changes.

WRITE IN: {lang_name}
COMMENTATOR PERSONA: {voice.persona}

HEADLINE: {item.title}
PRIMARY SOURCE ({primary_src}):
{body[:3000]}
{extra_block}{followup}{shape}
OUTPUT a JSON object with exactly these fields:
- "hook": the FIRST spoken sentence, written in the OPENING style above.
- "beats": 3-5 beats. Each beat: {{"text": spoken sentence(s) (10-400 chars),
  "on_screen": SHORT ALL-CAPS caption (max 60 chars, 2-5 words: a fact, number or claim)}}
- "loop_close": the LAST spoken sentence, written in the CLOSING style above. It must also
  read as a natural set-up for the hook when the video loops.
- "mood": "breaking" | "neutral" | "upbeat"

HARD RULES:
- TOTAL spoken words across hook + beats + loop_close: between {lo_w} and {hi_w}.
{source_rule}
- HAVE A VIEW: somewhere in the narration take a clear, fair position on what this means —
  but do not stamp it with the same phrase every time, and do not moralise.
- BE FAIR: if there is a serious other reading, give it one honest sentence. Never take a
  party's or a leader's side; no insults; state uncertain claims as uncertain
  ('iddiaya göre'). In tragedies: respectful, no jokes.
- NEVER MENTION how many people searched this, search engines, trends, or that the topic is
  "trending" — that is our internal selection signal, not content. The viewer must not be
  able to tell how the topic was chosen.
- BANNED PHRASES (do not use, in any inflection): {banned}
- Every fact must come from the sources above. Invent nothing — no names, numbers, dates.
- Plain spoken language, no markdown, no emoji, no brackets, numbers written as spoken.
- Vary sentence length, but EVERY sentence must stand on its own: never write a short
  abstract headline sentence whose referent arrives later ('Asıl mesele hız.'). If you
  name an abstraction, the concrete fact goes in the SAME sentence
  ('Asıl mesele hız: saldırgan bir ay önce partiye geçmişti.'). A metaphor is allowed
  only next to the literal fact it stands for.
- Do not start two consecutive sentences with the same word.

Return ONLY the JSON object."""


def write_yorum_narration(
    item,
    body: str,
    *,
    channel,
    extra_sources: list[tuple[str, str]] | None = None,
    variation=None,
    claude_path: str = "claude",
    model: str = "default",
    backend: str = "claude_cli",
    api_key: str | None = None,
) -> Narration:
    """Yorum anlatımı: ``write_narration`` ile aynı bütçe + olgu kapısı makinesi;
    fark prompt ve olgu referansı (ana gövde + ek kaynaklar + Trends bağlamı —
    aksi hâlde 'yüz bin kişi aradı' uydurma sayılırdı)."""
    voice = getattr(channel, "voice", None)
    if voice is None:
        raise ValueError("write_yorum_narration: channel.voice tanımlı değil")
    extra_sources = list(extra_sources or [])
    lo_w, hi_w = word_budget(voice.target_duration_s, channel.language)
    prompt = build_yorum_prompt(item, body, channel, extra_sources=extra_sources,
                                variation=variation)
    reference = "\n".join([body] + [t for _, t in extra_sources]
                          + [getattr(item, "description", None) or ""])

    def _uret(p: str) -> Narration:
        return run_json(p, Narration, claude_path=claude_path, model=model,
                        backend=backend, api_key=api_key, retries=3)

    narration = _uret(prompt)
    actual = narration.word_count()
    if not (lo_w <= actual <= hi_w):
        narration = _uret(prompt + _budget_feedback(actual, lo_w, hi_w))

    eksik = unverified_claims(narration.full_text(), reference, language=channel.language)
    if eksik:
        log.warning(f"[olgu] kaynaklarda geçmeyen isim/sayı: {eksik} → yeniden yazdırılıyor")
        narration = _uret(prompt + _fact_feedback(eksik))
        eksik = unverified_claims(narration.full_text(), reference, language=channel.language)
        if eksik:
            raise RuntimeError(
                f"yorum anlatımı kaynaklarda geçmeyen isim/sayı içeriyor: {', '.join(eksik)}. "
                f"İki denemede de düzelmedi — video üretilmedi.")
        log.info("[olgu] düzeltme turu temiz ✓")

    # ÜSLUP KAPISI: dayanaksız kısa cümle ("Asıl mesele hız.") bir kez düzelttirilir.
    # Uydurma bilgiden farkı: ısrar ederse video YİNE üretilir — kötü bir cümle,
    # yanlış bilgi kadar ağır değil; ama sessizce geçmesin diye log'a düşer.
    parcali = dangling_fragments(narration.full_text())
    if parcali:
        log.warning(f"[üslup] dayanaksız kısa cümle: {parcali} → yeniden yazdırılıyor")
        aday = _uret(prompt + fragment_feedback(parcali))
        kalan = dangling_fragments(aday.full_text())
        if unverified_claims(aday.full_text(), reference, language=channel.language):
            log.warning("[üslup] düzeltme turu olgu kapısını bozdu — ilk metin korunuyor")
        elif kalan:
            log.warning(f"[üslup] düzeltmede de kaldı: {kalan} — yine de üretiliyor")
            narration = aday
        else:
            log.info("[üslup] düzeltme turu temiz ✓")
            narration = aday
    return narration
