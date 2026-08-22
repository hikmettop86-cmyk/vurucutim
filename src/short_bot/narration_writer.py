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
    """Hedef süre aralığından uzunluk bütçesi (min, max), DİLİN BİRİMİNDE.

    CJK'DE BİRİM KARAKTERDİR. Japoncada boşluk yok: 65 karakterlik bir cümle
    `.split()` ile 1 parça sayılıyordu, yani "66-110 kelime" bütçesi kurulup
    sayım 1 dönüyor, kontrol hep başarısız oluyor ve metin bütçeden BAĞIMSIZ
    kabul ediliyordu — bütçe Japoncada hiç çalışmıyordu (2026-08-22).

    Mekanizma kürate yolu için zaten çözülmüştü (`reel_narration`); burada
    yeniden yazmak yerine ORASI kullanılıyor, iki yerde ayrışmasın.

    `language` verilmezse Türkçe hızı kullanılır (mevcut çağıranların davranışı
    değişmesin diye).
    """
    from short_bot.reel_narration import CJK_LANGUAGES, reel_word_budget
    if (language or "") in CJK_LANGUAGES:
        return reel_word_budget(target_duration_s, language)
    wps = words_per_second(language)
    lo, hi = target_duration_s
    return int(lo * wps), int(hi * wps)


def narration_length(text: str, language: str | None = None) -> int:
    """Anlatım uzunluğu, DİLİN BİRİMİNDE (CJK'de karakter, ötekinde kelime).

    `Narration.word_count()` her dilde `.split()` sayar; CJK'de bu 1 döner.
    Bütçe kontrolü bu fonksiyondan geçmeli.
    """
    from short_bot.reel_narration import budget_unit
    t = text or ""
    if budget_unit(language or "") == "characters":
        return len("".join(t.split()))      # boşluk saymadan karakter
    return len(t.split())


def build_narration_prompt(item, body: str, channel) -> str:
    voice = channel.voice
    lo_w, hi_w = word_budget(voice.target_duration_s, channel.language)
    # Bütçenin BİRİMİ dile göre: CJK'de karakter (boşluk yok, kelime
    # sayısı anlamsız), ötekinde kelime.
    from short_bot.reel_narration import budget_unit as _bu
    birim = "characters" if _bu(channel.language) == "characters" else "words"
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
- TOTAL spoken {birim} across hook + all beats + loop_close: between {lo_w} and {hi_w}.
- Plain spoken language. No markdown, no emoji, no stage directions, no brackets.
- Every claim must come from the article body. Invent nothing.
- Numbers should be written as they are spoken.

Return ONLY the JSON object."""


def _budget_feedback(actual: int, lo_w: int, hi_w: int,
                     language: str | None = None) -> str:
    """Bütçe dışı denemeye geri bildirim. BİRİM DİLE GÖRE — Japoncaya
    "had 1 spoken words" demek anlamsız bir talimattır."""
    from short_bot.reel_narration import budget_unit
    birim = "characters" if budget_unit(language or "") == "characters" else "words"
    if actual > hi_w:
        return (f"\n\nKISALT: previous attempt had {actual} spoken {birim}, "
                f"budget is {lo_w}-{hi_w}. Cut to fit.")
    return (f"\n\nUZAT: previous attempt had only {actual} spoken {birim}, "
            f"budget is {lo_w}-{hi_w}. Add detail to fit.")


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
    # Bütçenin BİRİMİ dile göre: CJK'de karakter (boşluk yok, kelime
    # sayısı anlamsız), ötekinde kelime.
    from short_bot.reel_narration import budget_unit as _bu
    birim = "characters" if _bu(channel.language) == "characters" else "words"
    prompt = build_narration_prompt(item, body, channel)

    def _uret(p: str) -> Narration:
        return run_json(p, Narration, claude_path=claude_path, model=model,
                        backend=backend, api_key=api_key, retries=3)

    narration = _uret(prompt)
    actual = narration_length(narration.full_text(), channel.language)
    if not (lo_w <= actual <= hi_w):
        # Tek düzeltme turu. İkincisi de bütçe dışıysa kabul edilir —
        # süre zaten sesten okunur, bütçe sadece bir hedeftir.
        narration = _uret(prompt + _budget_feedback(actual, lo_w, hi_w,
                                            channel.language))

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


# ALMANCA YORUMCU. Türkçe personanın ÇEVİRİSİ DEĞİL — Alman medya kültürünün
# kendi kalıbı: Tagesthemen sonundaki "Kommentar" geleneği. Orada yorumcu adıyla
# konuşur, önce SACHLICH anlatır, sonra EINORDNUNG yapar (bu kelime Alman haber
# dilinin merkezinde: olayı bağlama oturtmak), tartar ve net bir hükümle biter.
# Türk "sokak bilgesi" tonu ("bakın", "şimdi") Almancaya çevrilse kabalaşır.
YORUM_PERSONA_DE = (
    "Du kommentierst die Nachrichtenlage in Deutschland: parteilos, aber nicht "
    "meinungslos. Zuerst sagst du sachlich, was passiert ist. Dann ordnest du ein — "
    "was daran neu ist, was es konkret für die Menschen bedeutet, was offen bleibt. "
    "Du wägst ab, drückst dich aber nicht: am Ende steht ein klares, faires Urteil. "
    "Du stehst auf der Seite der Bürgerinnen und Bürger, nicht auf der einer Partei, "
    "einer Behörde oder eines Konzerns. Trockener Humor ja, Häme nein; bei Opfern und "
    "Trauer bist du respektvoll. Sprache: kurze Hauptsätze, Aktiv statt Passiv, "
    "'Der Reihe nach', 'Fakt ist', 'Bleibt die Frage'. Keine Behördenfloskeln "
    "('teilte mit', 'wurde bekannt gegeben'), keine Anglizismen-Show. "
    "Pressekodex: Verdächtige NIE mit vollem Namen — 'mutmaßlich', 'Max M.'."
)

# JAPONCA YORUMCU. Türkçe/Almanca personanın çevirisi DEĞİL — Japon 芸能ニュース
# grameri başka: kaynak göstermek zorunlu ("事務所によると"), kesinlik dereceleri
# dilin içine gömülü ("〜と報じられています" / "〜とみられます"), ve özel hayat
# üzerine yorum 名誉毀損 riski taşır (Japonya'da doğru beyan bile suç olabilir).
# Bu yüzden görüş, RİSKSİZ alana park edilir: eser, sahne, kariyer kararı.
YORUM_PERSONA_JA = (
    "あなたは芸能ニュースを落ち着いて読み解くコメンテーターです。"
    "役割は一つ——何が発表され、何がまだ分かっていないかを切り分けること。"
    "出どころを必ず示します（事務所の発表、本人のコメント、報じた媒体の名前）。"
    "確認されていないことは言い切らず、「〜と報じられています」「〜とみられます」と伝えます。"
    "私生活の憶測はしません——交際、破局、離婚、病気の「可能性」を勝手に語らない。"
    "誰かを笑いものにせず、追い詰めません。訃報では言葉を選び、遺族に配慮します。"
    "作品・舞台・キャリアの判断については率直に良し悪しを言ってよい——そこがあなたの意見の場所です。"
    "話し方：短い文、です・ます、テンポよく。「まず」「ここが大事です」「正直なところ」。"
    "ワイドショーの決まり文句は使いません。"
)

YORUM_PERSONAS: dict[str, str] = {"tr": YORUM_PERSONA_TR, "de": YORUM_PERSONA_DE,
                                  "ja": YORUM_PERSONA_JA}


def default_yorum_persona(language: str = "tr") -> str:
    """Kanalın dili için varsayılan yorumcu personası.

    Bilinmeyen dilde Türkçe personayı DÖNDÜRMEZ — çok dilli tuzakların en
    sinsisi tam buydu (bkz. reel_narration._language_name: bilinmeyen dilde
    'Turkish' dönüp Japonca sese Türkçe metin okutuyordu). Karşılığı olmayan
    dilde boş döner: panel operatörden persona ister, sessizce yanlış dilde
    yazmaz."""
    return YORUM_PERSONAS.get((language or "").split("-")[0].lower(), "")


# YASAK KALIPLAR DİLE ÖZGÜDÜR. Almanca kanala "Peki sizce" yasağı koymak boşa
# kürek: model o kalıbı zaten üretmez, ürettiği Alman gazetecilik klişesidir
# ("Es bleibt abzuwarten" — Almanca haber metinlerinin en yıpranmış kapanışı).
BANNED_PHRASES_DE: tuple[str, ...] = (
    # Arama verisi: konuyu seçer, KONUŞULMAZ.
    "Google Trends", "Suchanfragen", "haben danach gesucht", "im Trend",
    "trendet", "viral gegangen", "Suchvolumen",
    # AI-slop / klişe kapanışlar
    "Es bleibt abzuwarten", "Zusammenfassend", "Abschließend lässt sich sagen",
    "Letztendlich", "Am Ende des Tages", "Schauen wir mal", "Nicht zuletzt",
    "Was meint ihr", "Schreibt es in die Kommentare", "abonniert", "unseren Kanal",
)

# JAPONCA YASAK KALIPLAR. Almanca notundaki aynı gerekçe: Japon web haberinin
# yıpranmış kalıpları Türkçeninkinden bambaşka. "〜が話題に" ve "今後の展開に
# 注目したい" Japonca haber metninin en bitkin açılış/kapanışları.
BANNED_PHRASES_JA: tuple[str, ...] = (
    # Arama verisi: konuyu seçer, KONUŞULMAZ.
    "検索", "トレンド入り", "急上昇", "検索数", "バズって",
    # AI-slop / klişe açılış-kapanış
    "が話題になっています", "話題を呼んでいます", "注目が集まっています",
    "今後の展開に注目", "衝撃", "まさかの", "騒然", "物議を醸し",
    "ネットの声", "チャンネル登録", "コメント欄",
)

_BANNED: dict[str, tuple[str, ...]] = {"tr": BANNED_PHRASES, "de": BANNED_PHRASES_DE,
                                       "ja": BANNED_PHRASES_JA}


def banned_phrases(language: str = "tr") -> tuple[str, ...]:
    """Bu dilde yasak kalıplar. Listesi olmayan dilde boş — uydurma yasak
    koymaktansa hiç koymamak yeğdir."""
    return _BANNED.get((language or "").split("-")[0].lower(), ())


def card_mismatch(narration_text: str, card) -> bool:
    """Anlatım KARTIN anlattığı olaydan sapmış mı?

    CANLI VAKA (short 1772): kaynak makale "görünür sutyen modası" hakkındaydı
    ve yan cümlede bir film devamından söz ediyordu. Kart ana haberi özetledi,
    anlatım EK KAYNAĞA kayıp 40 saniyeyi film devamına ayırdı — ekran bir şey,
    ses başka şey söyledi.

    Ölçüt DAR tutuldu (yanlış pozitif üretimi durdurur, Burhan dersi): yalnız
    kartın ÖZNESİ (header_top) anlatımda hiç geçmiyorsa sapma sayılır. Çok
    kısa özneler denetime girmez — "AB" gibi bir dizi her metinde bulunur.
    """
    if not card:
        return False
    ozne = (card.get("header_top") or "").strip() if hasattr(card, "get") else ""
    if len(ozne) < 3:
        return False
    from short_bot.text_normalize import locale_fold
    return locale_fold(ozne) not in locale_fold(narration_text or "")


def build_yorum_prompt(item, body: str, channel, *, extra_sources: list[tuple[str, str]],
                       variation=None, card=None) -> str:
    """Yorum anlatımı promptu. Çıktı şeması ``Narration`` ile aynı (hook/beats/
    loop_close/mood) — TTS/hizalama/render zinciri değişmeden kullanılır.

    ``variation`` (yorum_variation.YorumVariation): bu videonun açılış/yaklaşım/
    kapanış biçimi. Pipeline her videoda farklı bir biçim seçer; sabit iskelet
    "her video aynı" hissini veriyordu (kullanıcı bildirimi 2026-08-20).
    """
    voice = channel.voice
    lo_w, hi_w = word_budget(voice.target_duration_s, channel.language)
    # Bütçenin BİRİMİ dile göre: CJK'de karakter (boşluk yok, kelime
    # sayısı anlamsız), ötekinde kelime.
    from short_bot.reel_narration import budget_unit as _bu
    birim = "characters" if _bu(channel.language) == "characters" else "words"
    lo_s, hi_s = voice.target_duration_s
    lang_name = LANGUAGE_NAMES.get(channel.language, "Turkish")
    primary_src = getattr(item, "source", None) or "unknown"

    extra_block = ""
    # KART ÇAPASI. Kart ve anlatım aynı makaleden BAĞIMSIZ yazılıyor ve
    # hiçbir şey ikisini bağlamıyordu: canlı vakada (short 1772) kart ana
    # haberi, anlatım ek kaynaktaki BAŞKA bir haberi anlattı — ekran bir
    # şey, ses başka şey söyledi. Kart artık anlatımın konusunu sabitler.
    card_block = ""
    if card:
        _ust = (card.get('header_top') or '').strip()
        _alt = (card.get('header_bottom') or '').strip()
        if _ust or _alt:
            card_block = (
                f"{chr(10)}MAIN STORY — the on-screen card says this, and your "
                f"narration MUST be about THIS event:{chr(10)}"
                f"  {_ust} / {_alt}{chr(10)}"
                "If a source below covers a different story, IGNORE it." + chr(10))
    if extra_sources:
        parts = []
        for url, text in extra_sources:
            host = url.split("//")[-1].split("/")[0].removeprefix("www.")
            parts.append(f"--- {host} ---\n{text[:1500]}")
        # "same story" VARSAYIMI KALDIRILDI: Google Trends bir trende 3 makale
        # verir ve bunlar farklı olaylar olabilir. Canlı vakada (short 1772)
        # anlatım ek kaynağa kayıp bambaşka bir haberi anlattı.
        extra_block = ("\nADDITIONAL SOURCES (may cover a DIFFERENT angle or even a\n"
                       "different story — use ONLY to corroborate the MAIN STORY below,\n"
                       "never as the subject of the narration):\n" + "\n".join(parts) + "\n")
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

    _bans = banned_phrases(channel.language)
    # Listesi olmayan dilde satır HİÇ yazılmaz: "BANNED PHRASES:" deyip boş
    # bırakmak modele anlamsız bir kural verir ve prompt'a gürültü katar.
    banned_line = ("\n- BANNED PHRASES (do not use, in any inflection): "
                   + ", ".join(f'"{p}"' for p in _bans)) if _bans else ""

    return f"""You are writing a spoken commentary script for a {lo_s}-{hi_s} second vertical
short video. A text-to-speech voice reads it; the news card stays on screen while a
short caption per beat changes.

WRITE IN: {lang_name}
COMMENTATOR PERSONA: {voice.persona}

HEADLINE: {item.title}{card_block}
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
- TOTAL spoken {birim} across hook + beats + loop_close: between {lo_w} and {hi_w}.
{source_rule}
- HAVE A VIEW: somewhere in the narration take a clear, fair position on what this means —
  but do not stamp it with the same phrase every time, and do not moralise.
- BE FAIR: if there is a serious other reading, give it one honest sentence. Never take a
  party's or a leader's side; no insults; state uncertain claims as uncertain
  ('iddiaya göre'). In tragedies: respectful, no jokes.
- NEVER MENTION how many people searched this, search engines, trends, or that the topic is
  "trending" — that is our internal selection signal, not content. The viewer must not be
  able to tell how the topic was chosen.
{banned_line}
- Every fact must come from the sources above. Invent nothing — no names, numbers, dates.
- Plain spoken language, no markdown, no emoji, no brackets, numbers written as spoken.
- Vary sentence length, but EVERY sentence must stand on its own: never write a short
  abstract headline sentence whose referent arrives later ('Asıl mesele hız.'). If you
  name an abstraction, the concrete fact goes in the SAME sentence
  ('Asıl mesele hız: saldırgan bir ay önce partiye geçmişti.'). A metaphor is allowed
  only next to the literal fact it stands for.
- Do not start two consecutive sentences with the same word.

Return ONLY the JSON object."""


def fact_reference(item, body: str, extra_sources) -> str:
    """Olgu kapısının referans metni.

    BAŞLIK VE KAYNAK ADI DA REFERANSTIR. Persona kaynağı ADIYLA söylemeyi
    ZORUNLU kılıyor ("報じた媒体の名前" / "kaynak adıyla olgu"), ama yayın adı
    haberin BAŞLIĞINDA ve `item.source` alanında durur — gövde metninde
    geçmeyebilir. Referansa alınmayınca kapı onu uydurma sayıyor ve iki kural
    birbiriyle ÇELİŞİYORDU: canlı vakada 週刊女性PRIME kaynaklı haberde anlatım
    kaynağı söyledi, kapı "PRIME" dedi ve ÜRETİM DURDU (2026-08-22).
    """
    parcalar = [body]
    parcalar += [t for _, t in (extra_sources or ())]
    for alan in ("description", "title", "source"):
        deger = getattr(item, alan, None)
        if deger:
            parcalar.append(str(deger))
    for _, baslik in (getattr(item, "trend_articles", None) or ()):
        if baslik:
            parcalar.append(str(baslik))
    return "\n".join(x for x in parcalar if x)


def write_yorum_narration(
    item,
    body: str,
    *,
    channel,
    extra_sources: list[tuple[str, str]] | None = None,
    variation=None,
    card=None,
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
    # Bütçenin BİRİMİ dile göre: CJK'de karakter (boşluk yok, kelime
    # sayısı anlamsız), ötekinde kelime.
    from short_bot.reel_narration import budget_unit as _bu
    birim = "characters" if _bu(channel.language) == "characters" else "words"
    prompt = build_yorum_prompt(item, body, channel, extra_sources=extra_sources,
                                variation=variation, card=card)
    reference = fact_reference(item, body, extra_sources)

    def _uret(p: str) -> Narration:
        return run_json(p, Narration, claude_path=claude_path, model=model,
                        backend=backend, api_key=api_key, retries=3)

    narration = _uret(prompt)
    actual = narration_length(narration.full_text(), channel.language)
    if not (lo_w <= actual <= hi_w):
        narration = _uret(prompt + _budget_feedback(actual, lo_w, hi_w,
                                            channel.language))

    # KART UYUMU: anlatım kartın anlattığı olaydan saptıysa BİR düzeltme turu.
    # Sert reddetmiyoruz — yanlış pozitif üretimi tamamen durdurur (Burhan
    # dersi) ve yükleme zaten elle yapılıyor. Israr ederse gürültülü uyarı.
    if card_mismatch(narration.full_text(), card):
        _ozne = (card or {}).get('header_top', '')
        narration = _uret(
            prompt + f"{chr(10)}{chr(10)}DÜZELT: the narration drifted to a different "
            f"story. It MUST be about '{_ozne}' — the subject on the card. "
            "Rewrite it about that event only.")
        if card_mismatch(narration.full_text(), card):
            log.warning(
                f"  [kart uyumu] anlatım '{_ozne}' öznesinden sapmış; iki denemede "
                f"de düzelmedi. Video üretiliyor ama YÜKLEMEDEN ÖNCE OKUNMALI.")

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
