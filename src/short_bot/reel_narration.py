"""LLM reel senaryo yazıcı: konu → ReelNarration (beat başına görsel sorgu).

Seslendirme metni kanal dilinde, her beat için SOMUT İngilizce görsel sorgu
(Pexels EN'de zengin). Kelime bütçesi ~1.95 kelime/sn (gerçek koşularda ölçüldü).
"""
from __future__ import annotations

import logging
import re

from short_bot.claude_cli import run_json
from short_bot.reel_models import ReelNarration
from short_bot.lang_pack import load_pack
from short_bot.reel_factcheck import (check_narration, fact_feedback,
                                      rewrite_cover_title)
from short_bot.reel_humor_check import check_humor, humor_feedback
from short_bot.persona import load_persona, persona_block
from short_bot.reel_phrases import find_overused, pick_styles

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


def build_reel_prompt(topic: str, channel, hook_patterns=None, seed: int = 0) -> str:
    lo_w, hi_w = reel_word_budget(channel.reel.target_duration_s)
    lo_s, hi_s = channel.reel.target_duration_s
    lang = _language_name(channel.language)
    # Yönergeler ve yasaklı kalıplar DİL PAKETİNDEN gelir: Almanca kanalın anlatım
    # LLM'ine Türkçe yönerge ve Türkçe örnek cümle vermek dil sızıntısı davetiyesidir.
    pack = load_pack(channel.language)
    # Bağlaçlar CÜMLE olarak verilince LLM birebir kopyalıyordu (ölçüldü: üç
    # anlatımın ikisinde aynı iki cümle). Artık YÖNERGE veriyoruz ve yönergeler
    # seed'e göre dönüyor — her video farklı bir alt küme görür.
    connective_block = "\n".join(f"    • {s}" for s in pick_styles(seed, 4, pack=pack))
    banned_block = "\n".join(f"    ✗ \"{p}\"" for p in pack.overused)
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

KONU SADAKATİ (ZORUNLU): Senaryodaki HAYVAN/ÖZNE, konu tohumundaki hayvanla AYNI
olmalı. Konu "şebek" diyorsa senaryo çakal/babun'a KAYMAZ; konu "Adélie pengueni"
diyorsa başka penguene geçmez. Benzer bir hayvana savrulmak uydurma bilgiye yol
açar (ölçüldü: şebek konusu → çakal senaryosu → biyoloji denetiminden kaldı).

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
  kapanmamalı. Bu borç anları retention'ı ayakta tutan şeydir.
  Aşağıdakiler CÜMLE DEĞİL, YÖNERGEDİR — cümleyi SEN yazacaksın, videonun kendi
  içeriğinden. Her beat'in sonuna bunlardan birinin İŞLEVİNİ gören bir geçiş koy:
{connective_block}
  HAZIR KALIP KOPYALAMA: aşağıdaki ifadeler AŞINMIŞTIR, birebir ya da benzerini
  kullanman YASAK (kullanılırsa metin reddedilir):
{banned_block}

=== OLGUSAL SADAKAT (TEPE KURALINDAN DAHA ÖNCELİKLİ) ===
Yukarıda "TEPE = EN ŞOK EDİCİ bilgi" dedik. Bu, olguyu ŞİŞİRMEK demek DEĞİLDİR.
Şok, KONUNUN KENDİSİNDE zaten var — senin işin onu doğru sırayla ortaya çıkarmak.

- GENİŞLETMEK SENİN İŞİN, ama YANLIŞ SÖYLEMEK DEĞİL. Konu tek cümlelik bir TOHUMDUR;
  onu doğru bilgilerle açman BEKLENİR. Yasak olan, YANLIŞ olan şeyi söylemektir.

- YÜKSELTME YASAK — olguyu, onu YANLIŞ yapacak kadar şişirme:
    "engelliyor" → "zehirliyor"        ✗
    "yavaşlatır" → "öldürür"           ✗
    "bağlantılı" → "sebep oluyor"      ✗
    "nadiren"    → "asla"              ✗
    "bazı"       → "bütün"             ✗
  GERÇEK HATA (bu sistemde yaşandı): konu "kafein bitkinin büyümesini ENGELLER"
  diyordu; senaryo "bitkilerini yavaş yavaş ZEHİRLİYOR" yazdı ve ekrana
  "ZEHİRLENME TEHLİKESİ" bastı. Kafein bitkiyi zehirlemez. Video YANLIŞ oldu.

- UYDURMA SAYI/OLAY/MEKANİZMA YOK. Emin olmadığın bir rakamı, tarihi ya da süreci
  YAZMA — bir ders kitabında ya da yerleşik bilgide karşılığı olmalı.

- Merak ve gerilim ANLATIM BİÇİMİNDEN gelir (sıralama, bekletme, mikro-döngü) —
  olguyu abartmaktan DEĞİL. Kanalın OTORİTESİ ürünüdür; bir tek yanlış iddia onu yakar.

OUTPUT a JSON object:
- "hook": FIRST spoken sentence in {lang}. A curiosity question or surprising claim,
  under 2 seconds. Never start with a date.
  YASAK AÇILIŞLAR: "Bunu biliyor muydunuz?" (200 milisaniyede içinden cevaplanır →
  gerilim çöker → kaydırır), "Merhaba arkadaşlar", "Bugün sizlere ... anlatacağım".
  Cevaplanabilir bir evet/hayır sorusu HOOK DEĞİLDİR.
- "cover_title": KARE SIFIR MANŞETİ — {lang}, 3-6 KELİME, BÜYÜK yazılacak.
  Feed'de izleyicinin gördüğü İLK KARE budur ve video orada avuç içi kadar görünür.
  Hook CÜMLESİ o boyutta okunmaz; 3-6 kelimelik bir manşet okunur. Manşet
  KONUŞULMAZ — yalnız ekranda durur, hook cümlesi altyazı olarak akar.
  Manşet videonun VAADİNİ taşımalı, konusunu ÖZETLEMEMELİ:
    KÖTÜ: "Kanguru yavruları hakkında bilgiler"   ← başlık değil, etiket
    İYİ:  "Bebek kanguru bir embriyo"             ← merak açar
  Cevabı VERME (merak kapanır), soruyu KUR. Nokta/emoji yok.
  MANŞET VİDEONUN SONUCUNU YALANLAYAMAZ.
    GERÇEK HATA: video "taze kahve telvesi genç bitkilere ZARAR VERİR" diyordu, ama
    manşet "DOĞAL GÜBRE OLARAK KAHVE TELVESİ" yazıyordu. Feed'de kaydıran biri onu
    bir ONAY sanar; içeri girince tam tersini duyar ve kandırıldığını hisseder.
  Manşet merak açabilir, soru sorabilir, cevabı saklayabilir — ama videonun
  söylediğinin TERSİNİ İDDİA EDEMEZ.
  BİR EFSANEYİ YIKIYORSAN manşet o efsaneyi DOĞRUYMUŞ GİBİ İLAN EDEMEZ. Onu EFSANE
  olarak adlandır ya da SORGULA:
    GERÇEK HATA: konu "yapraklardaki su damlaları güneşte yakar EFSANESİ YANLIŞ" idi;
    manşet "SU DAMLASI TEHLİKE BAHÇE" yazıldı — efsaneyi ONAYLADI, video tersini
    söylüyordu.
      ✗ "SU DAMLASI TEHLİKE BAHÇE"       ← efsaneyi doğru sayıyor
      ✓ "MERCEK EFSANESİ"                ← efsaneyi efsane olarak adlandırıyor
      ✓ "DAMLALAR GERÇEKTEN YAKAR MI?"   ← soruyor, cevabı saklıyor
  Merak, efsaneyi ONAYLAMAKTAN değil SORGULAMAKTAN doğar.
- "title": VİDEO BAŞLIĞI ({lang}) — YouTube ve dosya adı için, cover_title'dan AYRI.
  KISA (≤60 karakter) + SEO-DOSTU: ÖZNENİN ADI (hayvan/konu anahtar-kelimesi) EN BAŞTA
  olsun — izleyici aramada onu yazar, aramada BULUNMASI için baştaki kelime kritik.
  Ardından kısa bir merak/vuruş gelir. KONUŞMA CÜMLESİ DEĞİL, gerçek bir başlık.
    KÖTÜ: 'Bizim bukalemunlar renk değiştirip mahalle kavgasını başlatıyor'  ← uzun cümle
    İYİ:  'Bukalemun Mahalle Kavgası: Renk Değiştiren Kabadayı'              ← özne önde, kısa
  Nokta yok. Clickbait/'inanamayacaksın' YASAK — dürüst ama merak açan.
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
- "open_loop": YALNIZCA aşağıda bir SERİ yönergesi verildiyse doldur; yoksa boş bırak.
  Tepe ödendikten SONRA açılan yeni, SPESİFİK soru/vaat.
  BU ALAN BİR KONU BAŞLIĞIDIR, konuşulacak cümle DEĞİL. Bir sonraki bölümün ÜRETİM
  KONUSU olarak aynen kullanılacak — o yüzden:
    ✗ "Bunun bilimsel sırrını 2. bölümde açıklıyoruz."   ← bölüm numarası, meta dil
    ✗ "Daha fazlası var."                                 ← içi boş
    ✓ "Paslı benekli kedinin avlanma başarısının ardındaki refleks hızı"
    ✓ "Fener balığının ışığını üreten simbiyotik bakteri"
  Bölüm numarası, "sonraki bölümde", "anlatacağım" GİBİ İFADELER BU ALANA GİRMEZ —
  onlar BEAT'İN METNİNE girer (aşağıdaki seri yönergesine bak). Bu alan yalnız
  KONUNUN KENDİSİDİR: bir sonraki videonun neyi anlatacağı.
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


def _phrase_feedback(bad: list[str]) -> str:
    """Yakalanan aşınmış kalıpları LLM'e GÖSTER. Soyut 'kalıp kullanma' uyarısı
    işe yaramıyor; ne yaptığını birebir söylemek işe yarıyor."""
    lines = "\n".join(f'  ✗ "{p}"' for p in bad)
    return (f"\n\nHATA — HAZIR KALIP: Metninde şu aşınmış ifadeler geçiyor:\n{lines}\n"
            f"Bunlar her videoda tekrarlandığı için içerik OTOMASYON ÜRÜNÜ gibi "
            f"okunuyor. Aynı İŞLEVİ gören (izleyiciyi bir sonraki beat'e borçlandıran) "
            f"ama BU VİDEONUN İÇERİĞİNDEN doğan cümleler kur. Yeniden yaz.\n")


MIN_BEATS = 3


def fit_word_budget(n: ReelNarration, *, lo_w: int, hi_w: int) -> ReelNarration:
    """Bütçeyi aşan senaryoyu KESİN olarak sığdır (LLM ikna edilemezse son çare).

    GERÇEK HATA: LLM 112 kelime üretti (sınır 99) → video 53.3 SANİYE oldu. Retry
    vardı ama sonucu KONTROL EDİLMİYORDU. 45sn'yi aşan video hem düşüşü sertleştirir
    hem loop'u zorlaştırır hem de TEPE'yi geciktirir (%64'e kaydı, olması gereken ~%50).

    Kısaltma sırası: SONDAN başlayarak beat at — ama TEPE beat'i, hook'u ve close'u
    ASLA atma (tepe duygusal boşalma anı; hook en kritik saniye; close LOOP callback'i).

    SERİDE TEPE-SONRASI BEAT DE DOKUNULMAZ: açık kapı cümlesi (bir sonraki bölümün
    vaadi) tam orada konuşuluyor. Atılırsa abone çipi, izleyicinin HİÇ DUYMADIĞI bir
    sözün üstüne ateşlenir ve takas çöker — yani serinin bütün mekanizması ölür.
    """
    if n.word_count() <= hi_w:
        return n

    def _rebuild(beats, peak):
        # comment/cover_title de TAŞINMALI: eski hâli bunları düşürüyordu — bütçe
        # taşan her senaryoda yorum sorusu sessizce kayboluyordu (ve manşet de
        # kaybolurdu). Kısaltma BEAT atar, alan silmez.
        return ReelNarration(hook=n.hook, beats=beats, close=n.close, mood=n.mood,
                             hook_visual=n.hook_visual, close_visual=n.close_visual,
                             cover_title=n.cover_title, title=n.title, comment=n.comment,
                             open_loop=n.open_loop, peak_beat=peak)

    beats = list(n.beats)
    peak = n.peak_beat
    cur = n
    # SONDAN başlayarak beat at — TEPE'ye (ve seride tepe-sonrasına) dokunma,
    # MIN_BEATS'in altına inme.
    while cur.word_count() > hi_w and len(beats) > MIN_BEATS:
        korunan = {peak} | ({peak + 1} if n.open_loop else set())
        drop = next((i for i in range(len(beats) - 1, -1, -1)
                     if i not in korunan), None)
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
                         hook_patterns=None, seed: int = 0) -> ReelNarration:
    reel = getattr(channel, "reel", None)
    if reel is None:
        raise ValueError("write_reel_narration: channel.reel tanımlı değil")
    lo_w, hi_w = reel_word_budget(reel.target_duration_s)
    prompt = build_reel_prompt(topic, channel, hook_patterns=hook_patterns, seed=seed)
    # PERSONA: reel motoru normalde tona duyarsız ("ilginç bilgiler"). Kanalın bir
    # personası varsa (örn. "vahsi_mizah") prompt'a ton bloğu (few-shot + kurallar)
    # eklenir. Persona None ise prompt bugünkü gibi kalır → sıfır regresyon.
    persona = load_persona(getattr(reel, "persona", ""), language=channel.language)
    if persona:
        prompt = prompt + "\n\n" + persona_block(persona, seed=seed)
        # MASKOT: tekrar eden ana karakter (persona TON verir, maskot KARAKTER).
        from short_bot.persona import mascot_block
        mblok = mascot_block(getattr(reel, "mascot_name", ""),
                             getattr(reel, "mascot_animal", ""),
                             getattr(reel, "mascot_trait", ""))
        if mblok:
            prompt = prompt + "\n\n" + mblok
    if hook_angle:
        prompt = prompt + f"\n\nAÇILIŞ AÇISI: {hook_angle}\n"
    if series_directive:
        prompt = prompt + f"\n\nSERİ: {series_directive}\n"
    if comment_line:
        # comment_line KALIP CÜMLE değil, YÖNERGE: soruyu LLM videonun kendi
        # içeriğinden yazar. Jenerik ("Ne düşünüyorsun?") sorular cevapsız kalır;
        # iyi bir yorum sorusu videodaki SPESİFİK bir ana bağlı olmalıdır.
        #
        # GERÇEK HATA (short 801 ve 802, Almanca): bu metin "soruyu 'close' alanının
        # SONUNA ekle" diyordu — ama 'comment' AYRI bir alan olarak çıkarıldığında
        # burası güncellenmemişti. Prompt KENDİSİYLE ÇELİŞİYORDU (yukarıda "yorum
        # sorusunu close'a KOYMA" yazıyor). Model ikisini de doldurdu:
        #   close   = "So wurde Löwenzahn zum Kaffeeersatz. Was schmeckt besser:
        #              Wurzel A oder Blüte B? Nur A oder B."
        #   comment = "Was schmeckt wohl besser: Wurzel A oder Blüte B?"
        # Sonuç: soru İKİ KEZ soruldu, ve dev kapanış KARTI (yalnız close'u basar)
        # 7 satırlık bir metin duvarına dönüştü — videonun üçte biri boyunca ekranda.
        #
        # İKİNCİ HATA: yönergenin içindeki ÖRNEK KALIP'ın meta-talimatı senaryoya
        # sızdı. Almanca kalıp "...Schreib nur den Buchstaben." diyor; model bunu
        # "Nur A oder B." diye kırpıp KONUŞULAN metne yazdı — izleyici için anlamsız
        # bir parça. Kalıp TÜR göstermek içindir, KOPYALANMAK için değil.
        prompt = prompt + (
            f"\n\nYORUM SORUSU — yalnızca 'comment' ALANINA yaz. 'close' alanına "
            f"ASLA soru koyma: close LOOP CALLBACK'tir ve dev kapanış kartına basılır; "
            f"soru oraya girerse ekranı metin duvarı kaplar ve soru İKİ KEZ sorulur.\n"
            f"Soru videonun İÇERİĞİNE bağlı ve KISA olmalı. Türü şu olmalı:\n"
            f"{comment_line}\n"
            f"Yukarıdaki yönergedeki ÖRNEK KALIP yalnız TÜRÜ gösterir — onu KOPYALAMA. "
            f"Kalıbın içindeki 'tek harf yaz' gibi TALİMAT parçaları izleyiciye "
            f"söylenecek cümle DEĞİLDİR; senaryoya girerlerse anlamsız kalırlar.\n"
            f"Soru DÜŞÜK EFORLU olmalı (tek harf/tek kelimeyle cevaplanabilsin). "
            f"'Ne düşünüyorsun?' / 'Yorumlara yaz' gibi açık uçlu, jenerik "
            f"sorular YASAK — cevapsız kalırlar.\n")
    def _budgeted(p: str) -> ReelNarration:
        n = run_json(p, ReelNarration, claude_path=claude_path, model=model,
                     backend=backend, api_key=api_key, retries=3)
        if lo_w <= n.word_count() <= hi_w:
            return n
        # LLM'i bir kez daha ikna etmeyi dene — SONUCU KONTROL ET (eskiden edilmiyordu:
        # ikinci deneme de taşınca 112 kelime olduğu gibi gidiyor, video 53sn oluyordu).
        n2 = run_json(p + _budget_feedback(n.word_count(), lo_w, hi_w), ReelNarration,
                      claude_path=claude_path, model=model, backend=backend,
                      api_key=api_key, retries=3)
        if lo_w <= n2.word_count() <= hi_w:
            return n2
        # İkna olmadı → KESİN olarak sığdır (kısa kalan da fazla uzun olandan iyidir).
        best = n2 if abs(n2.word_count() - hi_w) < abs(n.word_count() - hi_w) else n
        log.warning(f"  senaryo bütçeye uymadı ({n.word_count()} → {n2.word_count()} "
                    f"kelime, sınır {lo_w}-{hi_w}) → kısaltılıyor")
        return fit_word_budget(best, lo_w=lo_w, hi_w=hi_w)

    n = _budgeted(prompt)

    # AŞINMIŞ KALIP DENETİMİ. Prompt'a "kullanma" demek YETMİYOR: ölçüldü, model
    # yasak dediğimiz cümleleri yine kuruyor. Yakalayıp yeniden yazdırıyoruz —
    # LLM çağrısı ucuz, tekrar eden kalıp ise videoyu "otomasyon" diye ele veriyor.
    pack = load_pack(channel.language)
    bad = find_overused(n.full_text(), pack=pack)
    if bad:
        log.warning(f"  senaryo aşınmış kalıp kullandı ({', '.join(bad)}) → yeniden yazılıyor")
        n = _budgeted(prompt + _phrase_feedback(bad))
        still = find_overused(n.full_text(), pack=pack)
        if still:
            log.warning(f"  kalıp ikinci denemede de geçti ({', '.join(still)}) → "
                        f"mevcut metin kullanılıyor")

    # OLGU DENETİMİ. Konu bankasında doğrulama kapısı VAR (topic_propose.verify_topics)
    # ve konuları doğru buluyor — ama ANLATIM doğru bir konuyu yanlış bir videoya
    # çevirebiliyor.
    #
    # GERÇEK HATA (Almanca kanal, short 795): konu "kafein büyümeyi ENGELLER" diyordu,
    # senaryo "bitkilerini ZEHİRLİYOR" yazdı ve ekrana "ZEHİRLENME TEHLİKESİ" bastı.
    # Kafein bitkiyi zehirlemez. Prompt'ta olgusal sadakat kuralı YOKTU — üstelik
    # "TEPE = EN ŞOK EDİCİ bilgi" diyerek abartmayı fiilen teşvik ediyordu.
    #
    # Kuralı prompt'a ekledik, ama prompt'a güvenmenin YETMEDİĞİNİ ölçtük. Kapı şart.
    #
    # MİZAH İSTİSNASI (ölçüldü: bal porsuğu üretimi, run 907): mizah personası abartıyı
    # DOĞAL kullanır ("Afrika'nın vergi memuru", "özgüven kıtaya sığmıyor", "kobra
    # zehri ona ayran aşısı"). Olgu kapısı bu mizahi hiperbolü "yanlış bilgi" sanıp
    # gereksiz yeniden yazım tetikliyor ve close kayboluyordu. Mizahta biyoloji
    # doğruluğunu MİZAH KAPISI denetler ("biyoloji DOĞRU mu"). O yüzden persona varsa
    # olgu kapısı ATLANIR — iki kapı çatışmasın, mizah kapısı yeter.
    sorunlar = [] if persona else check_narration(
        topic, cover_title=n.cover_title, text=n.full_text(),
        language=channel.language, claude_path=claude_path, model=model,
        backend=backend, api_key=api_key)
    if sorunlar:
        log.warning(f"  senaryo konuyu abarttı/çarpıttı "
                    f"({'; '.join(i.problem for i in sorunlar)}) → yeniden yazılıyor")
        n = _budgeted(prompt + fact_feedback(sorunlar))
        hala = check_narration(
            topic, cover_title=n.cover_title, text=n.full_text(),
            language=channel.language, claude_path=claude_path, model=model,
            backend=backend, api_key=api_key)

        # OLGU ile MANŞET ayrı ele alınır — tepki ORANTILI olmalı.
        olgu = [i for i in hala if i.kind != "cover"]
        manset = [i for i in hala if i.kind == "cover"]

        if olgu:
            # ANLATIMDA olgusal hata ısrar ediyor. Yanlış bir video yayınlamak, hiç
            # video yayınlamamaktan KÖTÜDÜR — kanalın otoritesi ürünüdür.
            raise ValueError(
                "senaryo olgu denetiminden geçemedi (2 deneme): "
                + "; ".join(f'"{i.claim}" → {i.problem}' for i in olgu))

        if manset:
            # MANŞET TEK BİR ALAN. Anlatım sağlamken videoyu öldürmek ORANTISIZ.
            # GERÇEK KOŞU: konu "su damlaları güneşte yakar EFSANESİ YANLIŞ" idi; model
            # manşeti "SU DAMLASI TEHLİKE BAHÇE" yazdı (efsaneyi doğruymuş gibi ilan
            # etti) ve 7 dakikalık üretim çöpe gitti. Manşeti HEDEFLİ yeniden üretiyoruz.
            i = manset[0]
            yeni = rewrite_cover_title(
                topic, text=n.full_text(), bad_title=n.cover_title,
                problem=i.problem, language=channel.language,
                claude_path=claude_path, model=model, backend=backend,
                api_key=api_key)
            if yeni:
                log.warning(f"  manşet videoyla çelişti ({i.problem}) → yenilendi: "
                            f"{n.cover_title!r} → {yeni!r}")
                n = n.model_copy(update={"cover_title": yeni})
            else:
                # Üretilemedi → manşeti BOŞALT. Kare sıfırda hook cümlesi görünür
                # (reel_render'ın mevcut davranışı). Çelişen bir manşetten iyidir.
                log.warning(f"  manşet çelişti ve yenilenemedi → BOŞALTILDI "
                            f"({n.cover_title!r})")
                n = n.model_copy(update={"cover_title": ""})

    # MİZAH KAPISI — yalnız persona'lı (mizah) üretimlerde. Olgu kapısı gibi:
    # üretilen senaryo GERÇEKTEN komik mi, referanslar GERÇEK mi, biyoloji DOĞRU mu.
    # Bu oturumun kanıtlanmış dersi: güçlü prompt yetmez, kapı şart. Olgu kapısı da
    # açık kaldı — mizah, yanlış bilgiye izin vermez (iki kapı da geçilir).
    if persona and persona.humor_check:
        mizah = check_humor(topic, text=n.full_text(), language=channel.language,
                            claude_path=claude_path, model=model, backend=backend,
                            api_key=api_key)
        if mizah:
            # MİZAH KAPISI DÜŞÜRMEZ, İYİLEŞTİRİR. Mizah abartıdır; "yeterince komik
            # değil" ya da bir referans için 7 dakikalık üretimi çöpe atmak yanlış
            # (kullanıcı için video çıkmaması en kötüsü). Bir kez iyileştir, hâlâ
            # sorun varsa videoyu KABUL ET + uyar. Biyoloji artık kapıda YOK — mizahi
            # abartı serbest (kullanıcı: "mizah abartıda böyle kural olmamalı").
            log.info(f"  mizah gözlemi ({'; '.join(i.problem for i in mizah)}) "
                     f"→ bir kez iyileştiriliyor")
            n = _budgeted(prompt + humor_feedback(mizah))
            hala = check_humor(topic, text=n.full_text(), language=channel.language,
                               claude_path=claude_path, model=model, backend=backend,
                               api_key=api_key)
            if hala:
                log.warning(f"  mizah gözlemi sürüyor → video YİNE DE kabul "
                            f"({'; '.join(i.problem for i in hala)})")

    # AÇIK KAPI DENETİMİ (yalnız seride). Abone çipi tepeden ~1.3sn sonra ekrana
    # geliyor; vaat o ana kadar SÖYLENMEMİŞSE istek, izleyicinin hiç duymadığı bir
    # sözün üstüne düşer ve takas çöker. Prompt bunu istiyor — ama ölçüyoruz.
    if series_directive:
        n = _ensure_open_loop(n, prompt, claude_path=claude_path, model=model,
                              backend=backend, api_key=api_key,
                              budgeted=_budgeted)
    return n


def _open_loop_feedback(n: ReelNarration) -> str:
    if not n.open_loop:
        return ("\n\nHATA — AÇIK KAPI YOK: 'open_loop' alanını boş bıraktın. Seri "
                "yönergesi verildi; bu bölüm kendi tepesini ödedikten sonra bir "
                "sonraki bölüme SPESİFİK bir kapı AÇMALI. Abone isteği o vaadin "
                "karşılığıdır; vaat yoksa istek de yok.\n")
    return (f"\n\nHATA — VAAT SÖYLENMİYOR: 'open_loop' alanına şunu yazdın:\n"
            f'  "{n.open_loop}"\n'
            f"Ama bu vaat TEPEDEN SONRAKİ beat'lerin METNİNDE geçmiyor — yani "
            f"izleyici onu HİÇ DUYMUYOR. Abone çipi tam o anda ekrana geliyor ve "
            f"boşluğa düşüyor.\n"
            f"Tepeden sonraki beat'in metnini, bu vaadi AÇIKÇA söyleyecek şekilde "
            f"yeniden yaz (aynı sözcükleri kullan).\n")


def _ensure_open_loop(n: ReelNarration, prompt: str, *, claude_path, model, backend,
                      api_key, budgeted) -> ReelNarration:
    """Açık kapı konuşulmuyorsa LLM'e NE YAPTIĞINI birebir gösterip yeniden yazdır."""
    if n.open_loop and n.open_loop_spoken():
        return n
    neden = ("open_loop boş" if not n.open_loop
             else f"vaat tepe-sonrası beat'te geçmiyor ('{n.open_loop[:50]}')")
    log.warning(f"  seri: açık kapı denetimi başarısız ({neden}) → yeniden yazılıyor")
    n2 = budgeted(prompt + _open_loop_feedback(n))
    if n2.open_loop and n2.open_loop_spoken():
        return n2
    # İkinci deneme de tutmadı: video yine üretilir ama TAKAS ÇALIŞMAZ — bunu
    # görünür kıl, sessizce geçiştirme (abone gelmiyorsa sebebi burada aranmalı).
    log.warning("  seri: açık kapı İKİNCİ denemede de kurulamadı → bu bölümün abone "
                "takası çalışmayacak (çip, söylenmemiş bir vaadin üstüne düşecek)")
    return n2 if n2.open_loop else n


# ===========================================================================
# KÜRATE-KLİP MODU (pivot 2026-07-17, SP3): kitlenin ZATEN onayladığı GERÇEK bir
# klibi persona ile YENİDEN ANLAT — uydurma değil. Girdi: klibin başlığı (gerçek
# bağlam) + vision'ın gördüğü GERÇEK aksiyon. Senaryo o gerçeğe sadık kalır.
# ===========================================================================
from pydantic import BaseModel as _BaseModel  # noqa: E402
from pydantic import Field as _Field  # noqa: E402

# Kürate video süresi KLİP UZUNLUĞUNDAN türer → LOOP YOK (kullanıcı: "loopa girince
# kötü oluyor" → çözüm: kısa klip loop yerine YAVAŞLATILIR, bkz. reel._slow_clip_to).
# Klip yeterince uzunsa (>= CURATED_MIN_S) video ~klip boyu (tek oynatım); kısa klip
# ~klip×CURATED_MAX_LOOP'a UZATILIR (yavaşlatma bunu tek oynatımda doldurur, loop yok)
# → senaryo nefes alır (persona sıkışmaz). Kanal üst süresini AŞMAZ.
CURATED_MAX_LOOP = 2.6
CURATED_MIN_S = 8
# SÜRE TAVANI (Faz 2): başarılı Türk Shorts kanalları 33-49sn (tatlı nokta ~40); 54sn'lik
# uzun/dağınık senaryolar retention'ı düşürüyordu. Uzun klip bu süreye kırpılır (payoff
# genelde erken; tempolu kısa senaryo > dağınık uzun). Kanal hedefi daha düşükse o geçerli.
CURATED_MAX_S = 45
# Bütçe kısaltma döngüsü: taşan senaryo klibi gerip loop'latır → hedefin altına
# inene kadar (en çok bu kadar tur) gemini ile kısaltılır (eski _fd_enforce_budget dersi).
_CURATED_BUDGET_ROUNDS = 3
_CURATED_BUDGET_TOL = 1.12


def curated_target(clip_dur_s: float, channel_target) -> tuple:
    """Kürate video süre penceresi (lo, hi) — KLİP uzunluğundan türer (loop önleme).

    clip >= CURATED_MIN_S → video ~klip boyu (loop YOK); kısa klip → en çok 2x.
    Kanal üst süresini aşmaz, CURATED_MIN_S'nin altına inmez."""
    lo_ch, hi_ch = channel_target
    if clip_dur_s <= 0:
        return channel_target
    if clip_dur_s >= CURATED_MIN_S:
        hi = min(int(hi_ch), int(round(clip_dur_s)), CURATED_MAX_S)   # uzun klip → ≤45sn
    else:
        hi = min(int(hi_ch), int(round(clip_dur_s * CURATED_MAX_LOOP)))  # kısa → ≤2x
    hi = max(CURATED_MIN_S, hi)
    return (max(6, hi - 4), hi)


def _curated_wc(d) -> int:
    return len((d.hook + " " + " ".join(d.beats) + " " + d.close).split())


class _CuratedDraft(_BaseModel):
    """Kürate senaryo GEVŞEK şeması: visual_query yok (tek hazır klip). ReelBeat'in
    katı doğrulaması yerine sade metin — beat'ler sonradan resmileşir."""
    hook: str = _Field(min_length=3, max_length=140)
    beats: list[str] = _Field(min_length=3, max_length=5)
    close: str = _Field(min_length=3, max_length=120)
    mood: str = "upbeat"
    title: str = ""
    title_en: str = ""      # İngilizce başlık (YouTube çok-dilli → küresel Shorts akışı)
    cover_title: str = ""


def build_curated_prompt(title: str, clip_description: str, *, channel,
                         target_duration_s=None, scene_split: float | None = None,
                         comments=None, tone: str = "mizah") -> str:
    """Tek GERÇEK klip için persona senaryosu prompt'u (uydurma yasağı).

    ``scene_split``: klip 2 sahneliyse İLK sahnenin bittiği oran (0-1, vision tespiti).
    ``comments``: üst Reddit yorumları — vision'a ALTERNATİF gerçek sinyal.
    ``tone``: 'mizah' (mahalle mizahı) | 'duygu' (duygusal mikro-dram — kahramanlık/kurtarma)."""
    td = tuple(target_duration_s) if target_duration_s else channel.reel.target_duration_s
    lo_s, hi_s = td
    lo_w, hi_w = reel_word_budget(td)
    lang = _language_name(channel.language)
    _duygu = (tone == "duygu")
    # TON KURALI: mizah → güldür; duygu → gerilim + sıcak çözüm (antropomorfik, @NedenHayvan).
    if _duygu:
        tone_rule = (
            "- 💗 DUYGU VER — bu bir DUYGUSAL MİKRO-DRAM (@NedenHayvan formülü). GÜLDÜRME; "
            "içten, sinematik anlat. HOOK'ta saniye-1 TEHLİKE/duygusal risk kur ('Bu [özne] "
            "… üzereydi, ama…'). Hayvana NİYET/kahramanlık/sadakat/şefkat ata (antropomorfik: "
            "'sanki koruyordu', 'pes etmedi', 'onu asla bırakmadı'). Mahalle-argosu, şaka, "
            "ironi YASAK. Ton: sıcak + gerilimli; final DUYGUSAL çözüm (kurtuluş/kavuşma/sadakat).")
        cta_hint = "izleyiciye içten çağrı ('Bu dokunduysa yorumlara bir kalp bırak.')"
    else:
        tone_rule = (
            "- GÜLDÜR — ama GERÇEK, ANLAMLI mizahla (aşağıdaki EN ÖNCELİKLİ MİZAH KURALI'na uy). "
            "Ekrandaki GERÇEK özneyi/aksiyonu KORU; yapay/resmi/belgesel dil YASAK.")
        cta_hint = "izleyiciye doğal bir soru/kışkırtma ('Sen olsan ne yapardın?' gibi, persona sesiyle)"
    # KALABALIK BAĞLAMI: başlık + üst yorumlar olayın NE olduğunu anlatır (vision tek
    # storyboard'dan aleti/olayı kaçırabilir — short 923: pipeti görmeyip 'parmak' dedi).
    crowd = ""
    _cl = [str(c).strip() for c in (comments or []) if str(c).strip()][:4]
    if _cl:
        _joined = "\n".join(f"  • {c}" for c in _cl)
        crowd = (f"\nARKA-PLAN BAĞLAMI (üst yorumlar — SADECE olayı/aleti ANLAMAN için; "
                 f"anahtar nesneyi ve ne olduğunu açıklarlar):\n{_joined}\n"
                 f"UYARI: Bu yorumlar yalnız SENİN anlaman için. Anlatıma 'yorumlar', "
                 f"'millet', 'izleyici', 'Reddit' DİYE SOKMA — sanki olayı sen görmüşsün "
                 f"gibi anlat.\n")
    scene_rule = ""
    if scene_split is not None and 0.0 < scene_split < 1.0:
        s1 = round(scene_split * 100)
        s2 = 100 - s1
        s1_words = max(2, round(scene_split * hi_w))
        scene_rule = (
            f"\n- ⏱ SAHNE-SENKRON (ÇOK ÖNEMLİ — ses görüntüyle uyumlu olmalı): Bu klip "
            f"~%{s1} noktasında YENİ bir sahneye/mekâna geçiyor (İLK sahne klibin ~%{s1}'i, "
            f"İKİNCİ sahne son ~%{s2}'si). Anlatımı buna göre TEMPOLA: sözlerinin ilk ~%{s1}'i "
            f"(~{s1_words} kelime) SADECE ilk sahneyi anlatsın; ikinci sahneye ('sonra', "
            f"'ardından', yeni mekân adı) ANCAK sözlerinin son ~%{s2}'sinde GEÇ. İkinci "
            f"sahneyi ERKEN anlatırsan izleyici onu HENÜZ görmüyor — ses görüntünün önüne "
            f"geçer, senkron bozulur. İlk sahneyi doyur, geçişi tam yerinde yap.")
    # ZAMAN-SIRALI BEAT SHEET (kürate: clip_description = 'BAŞ/ORTA/SON (Xsn): …'): anlatımı
    # AYNI zaman-sırasına oturt ki cümleler ekrandaki ana denk gelsin (short 990). scene_rule
    # yalnız 2-sahnede tetikleniyordu; beat sheet TEK-sahne çok-olay için de sırayı zorlar.
    beat_rule = ""
    if "BAŞ (" in clip_description or "ORTA (" in clip_description:
        beat_rule = (
            "\n- ⏱ ZAMAN-SIRALI BEAT SHEET: Yukarıdaki tarif klibin ZAMAN dilimleridir "
            "(BAŞ→ORTA→SON, saniyelerle). Anlatımını TAM bu sırayla kur: 1. beat BAŞ'takini, "
            "2. beat ORTA'dakini, kapanış SON'dakini anlatsın. SON'daki ödülü/kavuşmayı/çözümü/"
            "punchline'ı ERKEN AÇMA — izleyici onu HENÜZ görmüyor, ses görüntünün önüne geçer, "
            "cümleler sahneyle oturmaz. Sıralamayı ASLA bozma; her beati kendi zaman dilimine yaz.")
    return f"""You are writing narration for a REAL short video clip we are RE-TELLING.

REAL CONTEXT (the clip's own caption/title): {title}
WHAT IS ACTUALLY ON SCREEN (vision of the real clip): {clip_description}
{crowd}{beat_rule}
This is a KÜRATE clip — the audience already loved this REAL moment. Narrate the REAL
story with the channel's persona. Do NOT invent a new story.

RULES:
- NE OLDUĞUNU önce BAŞLIK + YORUMLARdan anla: Başlık (poster'ın kendi tarifi) ve yorumlar
  olayın GERÇEĞİDİR — anahtar nesne/aleti, EYLEMİ ve AMACINI onlar söyler. Vision tek kareden
  aleti/yönü KAÇIRABİLİR ya da TERS okuyabilir; başlık/yorum bir şeyi ('using a straw' =
  aleti KULLANIYOR, 'inserted/resuscitating' = SOKUP hava veriyor) söylüyorsa, vision
  'removes/çıkarıyor' dese BİLE başlık+yoruma GÜVEN — eylemi/yönü TERS çevirme, 'parmakla'
  gibi yanlış ikame UYDURMA. Örn. 'saves a turtle using a straw' = balıkçı pipeti KURTARMAK
  için kullanır (pipeti burundan çıkarmak DEĞİL). Vision görsel detay (renk, poz, ortam)
  için; olayın ÖZÜ + AMACI başlık+yorumdan gelir.
- ⛔ UYDURMA VARLIK KESİN YASAK (EN SIK HATA): Ekranda GÖRÜNMEYEN ikinci bir CANLI / NESNE / KİŞİ
  ya da onunla ilgili bir alt-olay EKLEME. Sahneyi 'zenginleştirmek' ya da kelime doldurmak için
  olmayan bir şey İCAT ETME. GERÇEK örnek-hata (short 999, YAPMA): kaplumbağa taşıyan adama dair
  anlatım araya 'yolda kaybolmuş bir YENGEÇ bulunca onu da taşıdı' diye UYDURULMUŞ bir yengeç
  soktu — karelerde yengeç YOKTU. Tek özneye/olaya SADIK KAL. Yalnız başlık+yorum+vision'ın
  BİLDİRDİĞİ varlıklar vardır; başkası YOK. (Duygu/abartı/lakap serbest — o YORUM; yeni fiziksel
  varlık değil.){scene_rule}
- ⛔ UYDURMA GEÇMİŞ/SEBEP DE YASAK (short 1000, YAPMA): Öznenin ekranda GÖRÜNMEYEN geçmişini,
  günlük rutinini ya da bir olayın SEBEBİNİ UYDURMA. Örnek-hata: kalabalıkta arabaya yürüyüp bir
  kadına sarılan adam için 'her maçtan sonra en son çıkardı', 'gece yarısı hep yalnız yürürdü',
  'öğrenciler ona araba almıştı' diye UYDURMA sebep-sonuç zinciri kuruldu → 'geç çıkmak' ile
  'araba' arasında bağ yok, izleyici 'ne alaka' dedi. YALNIZ ŞU ANI (vision + başlık/yorumun net
  söylediği) anlat; 'neden', 'geçmişte', 'çünkü şöyleydi' gibi UYDURMA arka plan/gerekçe EKLEME.
  Duygu, GÖRÜNEN andan çıkar (adam duygulanmış, sarılıyor, kalabalık onu alkışlıyor) — uydurma
  hikâyeden değil.
- KENDİ İÇİNDE HİKÂYE — META YOK: Anlatım, olayı GÖREN birinin ağzından akan tek bir
  hikâyedir. 'Yorumlarda millet', 'izleyici', 'Reddit', 'video' gibi DIŞ referans SOKMA;
  dördüncü duvarı KIRMA. (Yorumlar sana bağlam; metne değil.)
- ZORLAMA METAFOR YASAK: Sahneyle ALAKASIZ, rastgele benzetme kullanma ('sanki davulla
  köye gönderiyor' gibi — deniz/kaplumbağayla ilgisiz). Benzetme kullanacaksan sahneden
  ÇIKMALI ve ANLAMLI olmalı; olmuyorsa düz ve komik anlat, zorlama.
- ANLAŞILIRLIK ŞART — İZLEYİCİ NE OLDUĞUNU ANLAMALI (short 980: 'Nereye baksan orada;
  fizikçiler elektron ararken bu kadar çaresiz kalmaz' → anlamsız/kopuk laf, izleyici videodan
  hiçbir şey anlamadı): HER cümle anlaşılır ve sahneyle NET bağlantılı olmalı. İzleyici
  anlatımı dinleyince videoda GERÇEKTE ne olduğunu — KURULUM (kim, nerede, ne yapıyor) + ASIL
  OLAY/ÖDÜL (sürpriz/komik an) — net kavramalı. Bağlamsız, kendinden menkul, 'akıllı laf' gibi
  duran ama bir şey ANLATMAYAN cümle YASAK. Zekâ, sahneyi NET ve komik anlatmaktan gelir —
  laf kalabalığından değil.
- TEK KELİME/İMGE ÇEKİÇLEME YASAK (short 957 dersi: 'çığ' 5 cümlede 5 kez tekrarlandı,
  ezber gibi durdu): aynı kelimeyi/imgeyi/benzetmeyi art arda cümlelerde TEKRARLAMA. Bir
  espriyi ya da imgeyi bir kez kur, GEÇ; sahneyi FARKLI açılardan besle (tepki, iç ses,
  görünür bir detay, absürt abartı, karşı-karakter). Bir merkez fikrin olabilir ama onu
  döve döve tekrar etme — çeşitlilik komiği, tekrar yapaylığı doğurur.
- 🎣 KANCA & MERAK YAPISI (RETENTION — tutan Türk Shorts kanallarının ORTAK formülü):
  * HOOK (ilk cümle) bir MERAK BOŞLUĞU açar: şaşırtan bir iddia/soru — ama SONUCU/açıklamayı
    ELE VERMEZ. Kalıp: "Şu [özneye] bak, [şaşırtan/absürt iddia]…" ya da "Bu [özne] …
    ama [terslik/soru]". İzleyici 'ne olacak / neden?' diye MERAKTA kalmalı, cevabı beklemeli.
  * BEAT'lerde gerilimi/merakı TIRMANDIR, açıklamayı ERTELE. Orta beat'e bir merak-RESET
    koy ('ama işin asıl kısmı burada' / 'ama olay burada bitmiyor') — sayaç sıfırlanır.
  * ÖDÜL — asıl 'aa!' anı ya da en komik vuruş — SON beat + close'ta gelir; BAŞTAN ele verme.
    Payoff sona saklanır ki izleyici sonuna kadar kalsın (loop mantığı).
{tone_rule}
- HARD WORD BUDGET: the whole spoken script (hook + 3 beats + close) must be {lo_w}-{hi_w}
  words TOTAL and MUST NOT exceed {hi_w}. TTS reads ~1.95 words/s, so this is what keeps
  the clip from LOOPING (video lands in {lo_s}-{hi_s}s). Count your words.
- Write EXACTLY 3 beats, each a FULL natural sentence (not clipped telegram-style). Aim
  for the MIDDLE of the {lo_w}-{hi_w} word range — rich persona voice, not terse. In {lang}.
- "title" (YouTube başlığı): MERAK BOŞLUĞU başlığı — sonucu SPOILER YAPMA, merak uyandır +
  SONUNA 1 emoji (😳/😱/🤯/🥹/😲). Kalıp: "[Özne] [şaşırtan eylem]… 😳". Eski düz SEO-spoiler
  başlık ('Kaplumbağa Boğuluyor Balıkçı Kurtarıyor') YASAK — cevabı verme, sordur.
- "title_en": AYNI başlığın İngilizcesi (aynı merak, aynı emoji) — küresel Shorts akışı için
  (YouTube çok-dilli başlık; 240 ülkeye açar). Örn: "Watch what this fisherman does… 😳".
- "cover_title" (3-6 kelime ekran manşeti).
- KAPANIŞ ('close'): SON vuruş (payoff — komik ya da duygusal, tona göre) + ARDINDAN kısa
  bir YORUM-YEMİ: {cta_hint}. SAKIN 'Ozan der ki', beyit/şair kalıbı YAZMA — ozan YASAK.
- mood: one of upbeat / neutral / calm.
Output JSON ONLY: {{"hook": "...", "beats": ["...", "...", "..."], "close": "...",
  "mood": "upbeat", "title": "...", "title_en": "...", "cover_title": "..."}}
"""


def _curated_humor_override(humor_style: str = "") -> str:
    """EN ÖNCELİKLİ mizah katmanı (persona formülünü bile ezer). GERÇEK, klibe özgü,
    ANLAMLI mizah — kalıp/atasözü/saçma espri YASAK. Kanalın humor_style'ı varsa o ses."""
    voice = (humor_style or "").strip()
    voice_line = (f"BU KANALIN KENDİ MİZAH SESİ: {voice}\nBu sesle, bu tonla güldür.\n"
                  if voice else "")
    return (
        "=== EN ÖNCELİKLİ MİZAH KURALI (YUKARIDAKİ HER ŞEYİ, PERSONA FORMÜLÜNÜ DE EZER) ===\n"
        + voice_line +
        "Mizah GERÇEK ve ANLAMLI olacak. Ekrandaki BU ANA dair KESKİN, ÖZGÜN bir gözlemden "
        "güldür — zeki bir arkadaşın o anı görüp attığı laf gibi. Komik olan, bu klibe ÖZGÜ "
        "gerçek detaydır (uyumsuzluk, insani paralel, beklenmedik köşe); HAZIR KALIP DEĞİL.\n"
        "KESİN YASAK: anlamsız atasözü/özlü söz, zorlama kafiye, uydurma-saçma espri, hazır "
        "kalıp ('resmen ... gibi', '... der ki', 'valla ...'), formül uygulamak. Bir satır "
        "GERÇEKTEN komik VE anlamlı değilse onu SADE ama gerçek yaz — saçmalamaktansa "
        "düz-ama-doğru yeğdir.\n"
        "KAPANIŞ (close): bu klibe oturan DOĞAL, komik bir son cümle — atasözü/ozan/kalıp "
        "DEĞİL; yoksa klibin en komik gerçek detayını tekrar vuran sade bir cümle."
    )


def _curated_emotion_override() -> str:
    """EN ÖNCELİKLİ DUYGU katmanı (persona formülünü de ezer). Gerilim-kurgulu duygusal
    mikro-dram — @NedenHayvan (437M) formülü: mizah/argo YOK, antropomorfik + sinematik."""
    return (
        "=== EN ÖNCELİKLİ TON KURALI (YUKARIDAKİ HER ŞEYİ, PERSONA FORMÜLÜNÜ DE EZER) ===\n"
        "Bu bir DUYGUSAL mikro-dram. GÜLDÜRME; ironi, şaka, mahalle-argosu YOK. Olayı bir "
        "tanık gibi GERİLİMLİ ve İÇTEN anlat. Hayvanı KAHRAMAN/insan gibi çerçevele — niyet, "
        "cesaret, sadakat, şefkat ata ('sanki koruyordu', 'bir an bile bırakmadı', 'pes "
        "etmeyi reddetti'). HOOK'ta saniye-1 ölüm-kalım/duygusal risk; ORTADA 'ama tehlike "
        "henüz geçmemişti' ile gerilimi sürdür AMA gerilimi UYDURMA bir engelle/varlıkla değil, "
        "sahnedeki GERÇEK zorlukla besle (ekranda olmayan ikinci bir hayvan/nesne/engel EKLEME — "
        "short 999: 'yolda bir yengeç buldu' diye olmayan yengeç uydurdu, YAPMA). FİNALDE sıcak "
        "bir çözüm (kurtuluş/kavuşma/fedakârlık). Klişe/melodram DEĞİL — bu ANIN GERÇEK "
        "duygusundan çık, abartma. Bir satır gerçekten duygu vermiyorsa sade ama içten yaz."
    )


def write_curated_narration(title: str, clip_description: str, *, channel,
                            subject: str = "scene",
                            claude_path: str = "claude", model: str = "default",
                            backend: str = "claude_cli", api_key: str | None = None,
                            seed: int = 0, target_duration_s=None,
                            scene_split: float | None = None,
                            comments=None, feedback: str = "") -> ReelNarration:
    """GERÇEK klibin başlığı + vision aksiyonundan persona senaryosu. visual_query'ler
    tek hazır klibe bağlı olduğu için ``subject``e sabitlenir (footage aranmaz).

    ``scene_split``: klip 2 sahneliyse geçiş oranı → anlatım temposu sahneye uydurulur.
    ``comments``: üst Reddit yorumları — olayı anlamak için vision'a ALTERNATİF gerçek
    sinyal (vision aleti/olayı kaçırırsa başlık+yorum yakalar; bkz. build_curated_prompt)."""
    reel = getattr(channel, "reel", None)
    if reel is None:
        raise ValueError("write_curated_narration: channel.reel yok")
    tone = getattr(reel, "curated_tone", "mizah")
    prompt = build_curated_prompt(title, clip_description, channel=channel,
                                  target_duration_s=target_duration_s,
                                  scene_split=scene_split, comments=comments, tone=tone)
    if (feedback or "").strip():
        # SADAKAT ya da NETLİK kapısı yeniden-yazımı: önceki deneme reddedildi → sorunu düzelt.
        # Framing İKİSİNİ de karşılar: uydurma olay (sadakat) + kopuk/anlamsız anlatım (netlik).
        prompt += (f"\n\n⚠️ ÖNEMLİ — ÖNCEKİ DENEMEN REDDEDİLDİ, ŞU SORUN VARDI:\n{feedback.strip()}\n"
                   "Bu sorunu DÜZELT. Yalnız ekranda GERÇEKTEN olanı, NET ve ANLAŞILIR anlat: "
                   "olmayan olay/sıra/dram (bırakılma, geri dönüş, kurtarma, olmayan karakter) "
                   "UYDURMA; kopuk/bağlamsız/anlamsız 'akıllı laf' KULLANMA. İzleyici klibi "
                   "görüyor ve videoda NE OLDUĞUNU anlamalı.")
    persona = load_persona(getattr(reel, "persona", ""), language=channel.language)
    if persona and tone != "duygu":
        # DUYGU modunda mahalle-mizahı personası ton'la çelişir → persona bloğu eklenmez
        # (duygu override tek başına yönetir). Mizahta persona ağzı/karakteri korunur.
        # curated=True: subject-agnostik (kaosdayi hayvan-DIŞI kaos/fail) + footage-sadakat
        # bloğu atlanır (klip sabit). Bkz. persona.persona_block.
        prompt += "\n\n" + persona_block(persona, seed=seed, curated=True)
        from short_bot.persona import mascot_block
        mblok = mascot_block(getattr(reel, "mascot_name", ""),
                             getattr(reel, "mascot_animal", ""),
                             getattr(reel, "mascot_trait", ""))
        if mblok:
            prompt += "\n\n" + mblok
    # EN SON KATMAN → EN ÖNCELİKLİ: tona göre humor ya da duygu override (persona formülünü EZER).
    prompt += "\n\n" + (_curated_emotion_override() if tone == "duygu"
                        else _curated_humor_override(getattr(reel, "humor_style", "")))

    # TEK LLM ÇAĞRISI: kürate anlatımı Claude CLI Sonnet 5 ile yazılır (Max aboneliği →
    # ÜCRETSİZ, OpenRouter parası yok). Ama CLI Sonnet ~50sn/çağrı: eski çok-turlu LLM
    # bütçe kısaltması (draft + N kısaltma turu) toplam >2dk sürüp timeout'a giriyordu.
    # Çözüm: TEK çağrı (retries=2 sadece JSON parse hatasına karşı) + taşarsa LLM yerine
    # DETERMİNİSTİK kısaltma (fit_word_budget beat atar, ekstra çağrı YOK). Sonnet zaten
    # kelime sınırına iyi uyduğu için fit_word_budget nadiren tetiklenir.
    draft = run_json(prompt, _CuratedDraft, claude_path=claude_path, model=model,
                     backend=backend, api_key=api_key, retries=2)

    from short_bot.reel_models import ReelBeat
    subj = (subject or "scene").strip() or "scene"
    # Ozan kalıbını ('Aşık X der ki' + zorlama kafiye) hook+beat İÇİNDEN de temizle (denetim:
    # few-shot düzeltildi ama savunma şart). _strip_bard_inline noktalama/büyük-harf DOKUNMAZ →
    # ozan yoksa hook/beat DEĞİŞMEZ (close için tam _strip_bard: tam cümle olsun).
    beats = [ReelBeat(text=_strip_bard_inline(t), visual_query=subj, keyword="")
             for t in draft.beats]
    narration = ReelNarration(
        hook=_strip_bard_inline(draft.hook), beats=beats, close=_strip_bard(draft.close),
        mood=draft.mood, title=draft.title, title_en=getattr(draft, "title_en", ""),
        cover_title=draft.cover_title, hook_visual=subj, close_visual=subj)
    # BÜTÇE: taşarsa deterministik sığdır (SONDAN beat at, hook/tepe/close korunur).
    td2 = tuple(target_duration_s) if target_duration_s else channel.reel.target_duration_s
    lo_w, hi_w = reel_word_budget(td2)
    if narration.word_count() > hi_w:
        log.info(f"  kürate[bütçe]: {narration.word_count()} kelime > {hi_w} → "
                 f"deterministik kısaltma")
        narration = fit_word_budget(narration, lo_w=lo_w, hi_w=hi_w)
    return narration


# ── TON-KLİP UYUM KAPISI (DUYGU kanalı KOMİK klip seçince zorla 'yas' draması çıkıyordu) ──
# Emotion/curiosity thumbnail-skoru aldatılabiliyor (stadyumda Viking-kask klibi merak=8 aldı
# ama duygusuz). Vision TARİFİNDEN (indirilmiş klip) METİN yargısı: klip kanalın TONUNA gerçekten
# uyuyor mu (DUYGU=dokunaklı, mizah=komik). Uymuyorsa klip YANLIŞ kanalda → atla.
class ToneFit(_BaseModel):
    """Klip kanalın tonuna (duygu/mizah) uyuyor mu — vision tarifinden metin yargısı."""
    fits: bool = True
    reason: str = ""


_TONE_FIT_DUYGU = (
    "Bu video DUYGUSAL/DOKUNAKLI bir kanala UYAR mı? UYANLAR: kurtarma, kavuşma, vefa/sadakat, "
    "şükran/nezaket/iyilik, kahramanlık/fedakârlık, içini ısıtan ya da gözünü dolduran insan/"
    "hayvan anı. UYMAYANLAR (fits=false): SADECE komik/absürt/şakacı, random/anlamsız, gerilim/"
    "aksiyon/fail, duygusal derinliği OLMAYAN (örn. stadyumda kostümle takılan biri, komik düşme, "
    "oyun oynama). Klip dokunaklı DEĞİL sadece eğlenceli/ilginçse fits=false."
)
_TONE_FIT_MIZAH = (
    "Bu video KOMİK/ŞAŞIRTICI bir kanala UYAR mı? UYANLAR: komik, absürt, beklenmedik, çarpıcı, "
    "'nasıl yani?!' dedirten, gülümseten ya da kahkaha attıran, fail/kaos anı. UYMAYANLAR "
    "(fits=false): SADECE hüzünlü/ağır/ciddi ya da dokunaklı-dram; komik/şaşırtıcı yanı OLMAYAN "
    "sıradan/durgun an."
)
_TONE_FIT_PROMPT = (
    "Bir kısa video şunu gösteriyor:\nVİDEO: {desc}\n\n{rule}\n"
    "- fits: video bu tona GERÇEKTEN uyuyor mu?\n"
    "- reason: uymuyorsa kısa neden (tek cümle Türkçe).\n"
    'SADECE JSON: {{"fits": <bool>, "reason": "<...>"}}'
)


def judge_tone_fit(clip_description: str, tone: str, *, backend: str = "claude_cli",
                   model: str = "default", api_key: str | None = None,
                   claude_path: str = "claude"):
    """Klip kanalın TONUNA (duygu/mizah) uyuyor mu — vision tarifinden METİN yargısı (ucuz,
    vision/storyboard GEREKMEZ). Döner ToneFit ya da None (hata → fail-open, çağıran uyuyor
    sayar). Retry'lı (None yalnız gerçekten doğrulanamayınca)."""
    if not (clip_description or "").strip():
        return None
    rule = _TONE_FIT_DUYGU if tone == "duygu" else _TONE_FIT_MIZAH
    prompt = _TONE_FIT_PROMPT.format(desc=clip_description[:600], rule=rule)
    last: Exception | None = None
    for _ in range(2):
        try:
            return run_json(prompt, ToneFit, claude_path=claude_path, model=model,
                            backend=backend, api_key=api_key, retries=2, timeout_s=60)
        except Exception as e:  # noqa: BLE001 — geçici → tekrar dene
            last = e
    log.info(f"  kürate[ton-uyum]: yargı doğrulanamadı ({last})")
    return None


# ── ANLATIM TUTARLILIK / NETLİK KAPISI (kullanıcı: 'videodan hiçbir şey anlamadım', short 980) ──
# Sadakat kapısı (verify_curated_narration) anlatım gerçek videoyu mu anlatıyor diye VISION'la
# bakar; bu kapı METİN-tabanlı: anlatım TUTARLI + ANLAŞILIR mı, izleyici olayı takip eder mi.
# İkinci-LLM (yazan Sonnet değil, ucuz metin backend) → varyansla üretilen 'akıllı ama anlamsız'
# / kopuk anlatımı yakalar; produce_curated değilse geri bildirimle yeniden yazdırır.
class NarrationClarity(_BaseModel):
    """Metin yargısı — anlatım NET + TUTARLI mı (izleyici videoda ne olduğunu anlıyor mu)."""
    clear: bool = True    # izleyici olayı net + tutarlı anlıyor mu
    reason: str = ""      # clear=False ise en büyük anlaşılırlık sorunu (tek cümle, TR)


_CLARITY_PROMPT = (
    "Aşağıda bir kısa video için yazılmış Türkçe bir mahalle-mizahı ANLATIMI var. Video şunu "
    "gösteriyor:\nVİDEO: {desc}\n\nANLATIM:\n---\n{narr}\n---\n"
    "Bu anlatım NET, TUTARLI ve GERÇEKTEN İŞLEYEN bir mizah mı? İKİ şeye bak:\n"
    "1) İzleyici NE OLDUĞUNU net anlıyor mu (kim / ne yapıyor / asıl sürpriz-komik AN)?\n"
    "2) Benzetmeler/laflar sahneye OTURUYOR mu, yoksa ZORLAMA / kopuk / üst üste yığılmış mı? "
    "Net bir KOMİK NOKTA var mı, yoksa kulağa akıllı gelen ama bir şey ANLATMAYAN/güldürmeyen "
    "laf yığını mı?\n"
    "clear=false DE eğer: bağlamsız/anlamsız cümle var; VEYA benzetmeler sahneyle ZAYIF bağlı/"
    "zorlama ve ÜST ÜSTE yığılmış (ör. basit bir düşüşe alakasız 'kaleci pozu / kanat gibi / "
    "cesaret kaydı gitti' benzetmeleri arka arkaya — short 1004, izleyici 'neresi komik, ne demek "
    "istedi' der); VEYA net bir komik nokta YOK; VEYA asıl olayı hiç anlatmıyor.\n"
    "SERBEST (clear=true): mahalle ağzı, abartı, lakap ve YERİNİ BULAN tek-iki keskin benzetme + "
    "NET olay. Amaç: zorlama-laf yığınını elemek, İYİ mahalle mizahını DEĞİL. Şüphede clear=TRUE.\n"
    "- clear: hem NET hem İŞLEYEN-mizah mı (olay anlaşılıyor + benzetmeler oturuyor + komik nokta var)?\n"
    "- reason: clear=false ise EN büyük sorun (tek cümle Türkçe).\n"
    'SADECE JSON: {{"clear": <bool>, "reason": "<...>"}}'
)


def judge_narration_clarity(narration_text: str, clip_description: str, *,
                            backend: str = "claude_cli", model: str = "default",
                            api_key: str | None = None, claude_path: str = "claude"):
    """Anlatım NET + TUTARLI mı (izleyici olayı anlar mı)? METİN-tabanlı ikinci-LLM yargısı
    (vision/storyboard GEREKMEZ → ucuz). Döner NarrationClarity ya da None (hata → fail-open,
    çağıran net sayar). Geçici hataya karşı retry'lı (None yalnız gerçekten doğrulanamayınca)."""
    if not (narration_text or "").strip():
        return None
    prompt = _CLARITY_PROMPT.format(desc=(clip_description or "")[:600], narr=narration_text[:900])
    last: Exception | None = None
    for _ in range(2):
        try:
            return run_json(prompt, NarrationClarity, claude_path=claude_path, model=model,
                            backend=backend, api_key=api_key, retries=2, timeout_s=60)
        except Exception as e:  # noqa: BLE001 — geçici → tekrar dene
            last = e
    log.info(f"  kürate[netlik]: yargı doğrulanamadı ({last})")
    return None


# Ozan/âşık imzası — kullanıcı ozanı İSTEMİYOR ama model arada prompt'u delip yazıyor.
# Deterministik SÖK: hem BAŞTAKİ 'Ozan der ki:' / 'Aşık Kedi der ki:' öneki, hem SONDAKİ
# ', Ozan yazdı' / '— Aşık Kedi' bylline'ı gider; arkasındaki ANLAMLI espri kalır.
_BARD_RE = re.compile(
    r"^\s*(?:a[şs][iıİ]k[^.;:!?]{0,25}|ozan)\s*der\s*ki\s*[:;,\-–—]?\s*",
    re.IGNORECASE)
_BARD_TAIL_RE = re.compile(
    r"[.,;:—–-]\s*(?:a[şs][iıİ]k|ozan)\b.*$", re.IGNORECASE | re.DOTALL)


def _strip_bard_inline(s: str) -> str:
    """Ozan kalıbını ('Aşık X der ki' öneki + zorlama kafiye kuyruğu) hook/beat İÇİNDEN temizle,
    AMA _strip_bard'ın aksine noktalama/büyük-harf normalizasyonu YAPMA (hook/beat'i değiştirme —
    ozan yoksa aynen kalsın). Yalnız kalıp sızarsa keser."""
    if not isinstance(s, str):
        return s
    return _BARD_TAIL_RE.sub("", _BARD_RE.sub("", s)).strip()


def _strip_bard(close: str) -> str:
    if not isinstance(close, str):
        return close
    s = _BARD_TAIL_RE.sub("", _BARD_RE.sub("", close)).strip().rstrip(",;:—–- ")
    if not s:
        return close
    if s[-1] not in ".!?":
        s += "."
    return s[0].upper() + s[1:]
