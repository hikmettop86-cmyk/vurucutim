"""LLM reel senaryo yazıcı: konu → ReelNarration (beat başına görsel sorgu).

Seslendirme metni kanal dilinde, her beat için SOMUT İngilizce görsel sorgu
(Pexels EN'de zengin). Kelime bütçesi ~1.95 kelime/sn (gerçek koşularda ölçüldü).
"""
from __future__ import annotations

import logging

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
