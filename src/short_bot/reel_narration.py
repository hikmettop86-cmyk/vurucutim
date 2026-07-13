"""LLM reel senaryo yazıcı: konu → ReelNarration (beat başına görsel sorgu).

Seslendirme metni kanal dilinde, her beat için SOMUT İngilizce görsel sorgu
(Pexels EN'de zengin). Kelime bütçesi ~2.2 kelime/sn (ai33 Türkçe ölçümü).
"""
from __future__ import annotations

from short_bot.claude_cli import run_json
from short_bot.reel_models import ReelNarration

WORDS_PER_SECOND = 2.2   # ai33/ElevenLabs Türkçe ölçümü

# Prompt İngilizce yazıldığından dil adları da İngilizce verilir. locale.LANGUAGE_NAMES
# yerel adları döndürüyor ("tr" -> "Türkçe") ve İngilizce prompt'a uymadığından burada
# ayrı İngilizce ad tablosu tutuyoruz (LLM'e "write in Turkish" gibi net talimat).
_PROMPT_LANGUAGE_NAMES = {
    "tr": "Turkish",
    "en": "English",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
}


def reel_word_budget(target_duration_s: tuple[int, int]) -> tuple[int, int]:
    lo, hi = target_duration_s
    return int(lo * WORDS_PER_SECOND), int(hi * WORDS_PER_SECOND)


def _language_name(code: str) -> str:
    return _PROMPT_LANGUAGE_NAMES.get(code, "Turkish")


def build_reel_prompt(topic: str, channel, hook_patterns=None) -> str:
    lo_w, hi_w = reel_word_budget(channel.reel.target_duration_s)
    lo_s, hi_s = channel.reel.target_duration_s
    lang = _language_name(channel.language)
    hook_block = ""
    if hook_patterns:
        pats = "\n".join(f"- {p}" for p in hook_patterns)
        hook_block = (f"\nKANITLANMIŞ HOOK ÖRÜNTÜLERİ (nişinde patlamış "
                      f"videolardan):\n{pats}\n"
                      f"Hook cümleni bu örüntülerden birine uydur.\n")
    return f"""You are writing a fast-paced, footage-driven "interesting facts /
how it works" vertical short ({lo_s}-{hi_s} seconds). It will be narrated by a
text-to-speech voice with karaoke subtitles, over stock footage clips that change
every beat.

TOPIC SEED: {topic}

=== YAPI: LİSTE DEĞİL, ARK (EN ÖNEMLİ KURAL) ===
A list of facts LEAKS viewers. Every fact that fully resolves is an EXIT RAMP:
the viewer got the information, curiosity CLOSED, and second 12 has no reason to
lead to second 13. Write an ARC instead:

  hook  → aç: tek bir vaat, cevaplanmamış bir soru
  beat 0 → İLK ÖDEME (gerçek bir bilgi ver — ama vurucu olanı DEĞİL)
  beats  → TIRMANIŞ: her beat bir öncekinin üstüne çıkar
  TEPE   → EN ŞOK EDİCİ bilgi. ORTADA. (peak_beat ile işaretle)
  son beat → TWIST: hook'u YENİDEN BAĞLAMLANDIRIR
  close  → hook'un SÖZCÜKLERİNİ geri çağırır (callback) → video başa döner

- EN İYİ BİLGİYİ BAŞA KOYMA (front-load YASAK). En şok edici olanı ORTAYA koy.
  Baştaki en iyi bilgi = geri kalanı yokuş aşağı = doğrusal düşüş.
- MİKRO-DÖNGÜ: her beat, bir sonrakine BORÇ bırakarak bitmeli — asla temiz
  kapanmamalı. Türkçe bağlaçlar (her beat'in sonuna birini koy):
    "Ama asıl garip olan şu:" / "Ve burada iş çığırından çıkıyor."
    "Sebebi ise sandığın şey değil." / "Bir de bunu duymadın:"
  Bu bağlaçlar izleyicinin kendine borçlandığı ANLARDIR — retention onlarla ayakta durur.

OUTPUT a JSON object:
- "hook": FIRST spoken sentence in {lang}. A curiosity question or surprising claim,
  under 2 seconds. Never start with a date.
  YASAK AÇILIŞLAR: "Bunu biliyor muydunuz?" (200 milisaniyede içinden cevaplanır →
  gerilim çöker → kaydırır), "Merhaba arkadaşlar", "Bugün sizlere ... anlatacağım".
  Cevaplanabilir bir evet/hayır sorusu HOOK DEĞİLDİR.
- "peak_beat": 0-based index of the beat that carries the BIGGEST shock/reveal.
  It must be in the MIDDLE of the beat list, not the first and not the last.
  Bu, beğeni tetiğinin ve abone isteğinin yerleşeceği andır: beğeni bir karar değil,
  DUYGUSAL BOŞALMADIR — boşalacak bir tepe yoksa beğeni de gelmez.
- "hook_visual": a SHORT English stock-footage query (2-4 COMMON words) for the
  OPENING shot. This is the MOST IMPORTANT frame of the video — the viewer decides
  in 1 second whether to keep watching. Pick the most STRIKING, CONCRETE, visually
  arresting subject OF THE TOPIC ITSELF (e.g. topic "ultra marathon destroys your
  body" → "exhausted runner collapsing", NOT "self destruction"). It MUST be
  something a generic stock library actually has.
  HOOK METAFORU GÖRSELE GİRMEZ: your hook SENTENCE may use a metaphor, but
  hook_visual must show the video's REAL subject — never the metaphor's object.
    KÖTÜ: topic "parasitic wasp takes over a caterpillar", hook "Bir geminin
          mürettebatı fırtınada mahsur kalırsa..." → hook_visual "ship in storm"
          → the viewer watches a SHIP for the first 5 seconds of a WASP video.
    İYİ:  hook_visual "caterpillar wasp larvae" (the video's real subject).
  Metaphor lives in the WORDS; the picture shows the SUBJECT. That is what a human
  editor does.
- "close_visual": a SHORT English stock-footage query (2-4 COMMON words) for the
  CLOSING shot. Concrete and findable; it should echo the hook's subject — and it
  is bound by the SAME metaphor ban.
- "beats": 3-6 beats. Each beat:
    - "text": the spoken sentence(s) in {lang} for this beat
    - "visual_query": a SHORT English stock-footage search query (2-4 COMMON words)
      for what to SHOW during this beat. It MUST be a subject a generic stock library
      (Pexels) actually has — e.g. "lightning storm", "storm clouds", "ocean waves",
      "factory machine", "bee flower". Concrete but findable. AVOID rare compound
      descriptions like "storm cloud interior ice crystals turbulence" — those return
      zero results. English only.
    - "keyword": a SHORT ALL-CAPS on-screen tag in {lang} (max 40 chars, 1-3 words)
- "close": LAST spoken sentence in {lang}. LOOP CALLBACK — it must REUSE THE HOOK'S
  OWN WORDS so the video falls back into its own beginning. Shorts loop, and every
  replay counts as a separate view; a faceless video loops INVISIBLY (no face, no
  body language, no cue that it restarted). A close that "wraps things up" throws
  that away.
    Hook:  "Piramitleri köleler yapmadı."
    Close: "...ve işte bu yüzden, piramitleri köleler yapmadı."   ← geri çağırır
    KÖTÜ:  "Doğa her zaman şaşırtıcıdır."   ← hiçbir sözcüğü paylaşmıyor, video BİTER
  Kapanış hook'un en az bir ANLAMLI SÖZCÜĞÜNÜ tekrar etmeli. No "abone ol"/"subscribe".
- "mood": one of "upbeat" | "neutral" | "calm"

HARD RULES:
- TOTAL spoken words across hook + beats + close: between {lo_w} and {hi_w}.
- Every visual_query / hook_visual / close_visual must be a real, findable
  stock-footage subject: a PHYSICAL, VISIBLE thing (person, animal, object, place,
  machine, natural phenomenon). NEVER an abstract concept ("auto-cannibalism",
  "self destruction", "symbolic power") — stock libraries have no footage for those;
  translate the idea into what a CAMERA would actually see.
- METAFOR YASAĞI (ÇOK ÖNEMLİ): The narration may use metaphors, but the visual
  query must describe the LITERAL subject of THIS video — never the metaphor.
  Stock search takes words literally and will return the WRONG thing.
    KÖTÜ: narration "görünmez savaşçılar" (= bakteriyofaj) → query "invisible
          warrior"  → stok kütüphane bir ESKRİMCİ döndürür. FELAKET.
    İYİ:  query "bacteriophage virus microscope" (videonun gerçek öznesi).
  Her sorgu, videonun ANA KONUSUYLA doğrudan ilişkili somut bir nesne olmalı.
- ÖZNEYİ ADIYLA YAZ (ÇOK ÖNEMLİ): HER visual_query, videonun öznesini ADIYLA
  içermeli (tür/nesne adı) — genel bir KATEGORİ adı DEĞİL. Genel kategori, stok
  kütüphaneden BAŞKA BİR CANLI getirir ve izleyici yanlış hayvanı görür.
    KÖTÜ: konu kanguru yavrusu → "tiny newborn animal"       → stok bir KUŞ getirdi
          konu kanguru yavrusu → "climbing struggling animal" → stok KEÇİ getirdi
          konu kanguru yavrusu → "desert wildlife predator"   → stok VAŞAK getirdi
    İYİ:  "newborn kangaroo joey", "kangaroo joey climbing pouch",
          "kangaroo mother pouch", "dingo australia"
  Kural: sorguda konunun ADI (kangaroo / condor / bee / bacteriophage) GEÇMELİ.
  "Bulunabilir olsun" kuralı bunu EZMEZ: yanlış özneyi bulmaktansa hiç bulmamak
  iyidir — kod, bulamayınca konunun dünyasından güvenli b-roll'e düşer.
- Plain spoken language, no markdown/emoji/brackets. Add a genuinely interesting
  angle, not a dry list.
{hook_block}Return ONLY the JSON object."""


def _budget_feedback(actual: int, lo_w: int, hi_w: int) -> str:
    if actual > hi_w:
        return f"\n\nKISALT: {actual} kelime vardı, üst sınır {hi_w}. Kısalt.\n"
    return f"\n\nUZAT: sadece {actual} kelime vardı, alt sınır {lo_w}. Detay ekle.\n"


def write_reel_narration(topic: str, *, channel, claude_path: str = "claude",
                         model: str = "default", backend: str = "claude_cli",
                         api_key: str | None = None,
                         hook_angle: str = "", series_directive: str = "",
                         comment_line: str = "",
                         hook_patterns=None) -> ReelNarration:
    reel = getattr(channel, "reel", None)
    if reel is None:
        raise ValueError("write_reel_narration: channel.reel tanımlı değil")
    lo_w, hi_w = reel_word_budget(reel.target_duration_s)
    prompt = build_reel_prompt(topic, channel, hook_patterns=hook_patterns)
    if hook_angle:
        prompt = prompt + f"\n\nAÇILIŞ AÇISI: {hook_angle}\n"
    if series_directive:
        prompt = prompt + f"\n\nSERİ: {series_directive}\n"
    if comment_line:
        prompt = prompt + (f"\n\nYORUM SORUSU: '{comment_line}' cümlesini kapanışın "
                           f"hemen ardına, izleyiciyi yorum yapmaya teşvik edecek "
                           f"şekilde 'close' alanına dahil et.\n")
    n = run_json(prompt, ReelNarration, claude_path=claude_path, model=model,
                 backend=backend, api_key=api_key, retries=3)
    if lo_w <= n.word_count() <= hi_w:
        return n
    retry = prompt + _budget_feedback(n.word_count(), lo_w, hi_w)
    return run_json(retry, ReelNarration, claude_path=claude_path, model=model,
                    backend=backend, api_key=api_key, retries=3)
