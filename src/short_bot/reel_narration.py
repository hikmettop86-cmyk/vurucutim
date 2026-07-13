"""LLM reel senaryo yazıcı: konu → ReelNarration (beat başına görsel sorgu).

Seslendirme metni kanal dilinde, her beat için SOMUT İngilizce görsel sorgu
(Pexels EN'de zengin). Kelime bütçesi ~1.95 kelime/sn (gerçek koşularda ölçüldü).
"""
from __future__ import annotations

import logging

from short_bot.claude_cli import run_json
from short_bot.reel_models import ReelNarration

log = logging.getLogger(__name__)

# ÖLÇÜM (gerçek koşular, kelime/sn):
#   86/47.8 = 1.80  |  96/48.6 = 1.98  |  92/43.4 = 2.12  |  112/53.3 = 2.10
# Hız içeriğe göre %18 oynuyor. Bütçeyi EN YAVAŞ ölçüme göre kur: 45 saniyeyi
# AŞMAMAK, kısa kalmaktan önemli (aşınca düşüş sertleşiyor, loop zorlaşıyor ve
# TEPE geç kalıyor). 2.2 varsayımı iyimserdi → 48-53 saniyelik videolar üretiyordu.
WORDS_PER_SECOND = 1.80

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
  KISA TUT (en fazla 120 karakter, ~12 kelime). Uzun kapanış close segmentini şişirir
  (bir koşuda videonun %27'siydi) ve ekranı 13 saniye STATİK bir metin bloğu kaplar —
  outro LOOP'U ÖLDÜRÜR: izleyici bittiğini görür ve başa dönmez.
  YORUM SORUSUNU BURAYA KOYMA — onun kendi alanı var ("comment").
- "comment": videonun İÇERİĞİNE bağlı, DÜŞÜK EFORLU yorum sorusu (en fazla 90
  karakter). Ayrı alan çünkü "close" ile birleşince hem sınırı aşıyor hem dev
  kapanış kartını şişiriyordu. Boş bırakılabilir.
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
        return (f"\n\nKISALT: {actual} kelime yazdın, ÜST SINIR {hi_w}. "
                f"En az {actual - hi_w} kelime AT. Beat sayısını azaltabilirsin.\n")
    return f"\n\nUZAT: sadece {actual} kelime vardı, alt sınır {lo_w}. Detay ekle.\n"


MIN_BEATS = 3


def fit_word_budget(n: ReelNarration, *, lo_w: int, hi_w: int) -> ReelNarration:
    """Bütçeyi aşan senaryoyu KESİN olarak sığdır (LLM ikna edilemezse son çare).

    GERÇEK HATA: LLM 112 kelime üretti (sınır 99) → video 53.3 SANİYE oldu. Retry
    vardı ama sonucu KONTROL EDİLMİYORDU. 45sn'yi aşan video hem düşüşü sertleştirir
    hem loop'u zorlaştırır hem de TEPE'yi geciktirir (%64'e kaydı, olması gereken ~%50).

    Kısaltma sırası: SONDAN başlayarak beat at — ama TEPE beat'i, hook'u ve close'u
    ASLA atma (tepe duygusal boşalma anı; hook en kritik saniye; close LOOP callback'i).
    """
    if n.word_count() <= hi_w:
        return n

    def _rebuild(beats, peak):
        return ReelNarration(hook=n.hook, beats=beats, close=n.close, mood=n.mood,
                             hook_visual=n.hook_visual, close_visual=n.close_visual,
                             peak_beat=peak)

    beats = list(n.beats)
    peak = n.peak_beat
    cur = n
    # SONDAN başlayarak beat at — TEPE'ye dokunma, MIN_BEATS'in altına inme.
    while cur.word_count() > hi_w and len(beats) > MIN_BEATS:
        drop = next((i for i in range(len(beats) - 1, -1, -1) if i != peak), None)
        if drop is None:
            break
        log.info(f"  senaryo bütçeyi aşıyor → beat atıldı: "
                 f"'{beats[drop].text[:40]}...'")
        beats = beats[:drop] + beats[drop + 1:]
        if drop < peak:
            peak -= 1
        cur = _rebuild(beats, peak)
        peak = cur.peak_beat
    n = cur
    if n.word_count() > hi_w:
        log.warning(f"  senaryo hâlâ bütçe dışı: {n.word_count()} kelime > {hi_w} "
                    f"(en az {MIN_BEATS} beat korunuyor) → video hedeften uzun olacak")
    return n


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
        # comment_line artık KALIP CÜMLE değil, YÖNERGE: soruyu LLM videonun kendi
        # içeriğinden yazar. Jenerik ("Ne düşünüyorsun?") sorular cevapsız kalır;
        # iyi bir yorum sorusu videodaki SPESİFİK bir ana bağlı olmalıdır.
        prompt = prompt + (
            f"\n\nYORUM SORUSU — 'close' alanının SONUNA, videonun İÇERİĞİNE bağlı "
            f"KISA bir soru ekle. Türü şu olmalı:\n{comment_line}\n"
            f"Soru DÜŞÜK EFORLU olmalı (tek harf/tek kelimeyle cevaplanabilsin). "
            f"'Ne düşünüyorsun?' / 'Yorumlara yaz' gibi açık uçlu, jenerik "
            f"kapanışlar YASAK — cevapsız kalırlar.\n"
            f"Kapanışın LOOP CALLBACK görevi bozulmasın: önce hook'un sözcüklerini "
            f"geri çağır, soruyu EN SONA koy.\n")
    n = run_json(prompt, ReelNarration, claude_path=claude_path, model=model,
                 backend=backend, api_key=api_key, retries=3)
    if lo_w <= n.word_count() <= hi_w:
        return n
    # LLM'i bir kez daha ikna etmeyi dene — SONUCU KONTROL ET (eskiden edilmiyordu:
    # ikinci deneme de taşınca 112 kelime olduğu gibi gidiyor, video 53sn oluyordu).
    retry = prompt + _budget_feedback(n.word_count(), lo_w, hi_w)
    n2 = run_json(retry, ReelNarration, claude_path=claude_path, model=model,
                  backend=backend, api_key=api_key, retries=3)
    if lo_w <= n2.word_count() <= hi_w:
        return n2
    # İkna olmadı → KESİN olarak sığdır (kısa kalan da fazla uzun olandan iyidir).
    best = n2 if abs(n2.word_count() - hi_w) < abs(n.word_count() - hi_w) else n
    log.warning(f"  senaryo bütçeye uymadı ({n.word_count()} → {n2.word_count()} "
                f"kelime, sınır {lo_w}-{hi_w}) → kısaltılıyor")
    return fit_word_budget(best, lo_w=lo_w, hi_w=hi_w)
