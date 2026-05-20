"""LLM script writer: news item + body → Script (header / overlay / paragraph / highlights)."""
from __future__ import annotations

from short_bot.claude_cli import run_json
from short_bot.config import ChannelConfig
from short_bot.locale import LANGUAGE_NAMES
from short_bot.models import NewsItem, Script


ARCHETYPE_PROMPTS = {
    "newscast": """ARCHETYPE: newscast — formal news presentation
- header_top + header_bottom: 4-6 words total, formal capital news headline
- photo_overlay: 2-5 words, key fact (number, decision, action)
- body_paragraph: 4-5 sentences, neutral journalistic tone
- highlights: red=warning/risk/casualty, yellow=stat/decision/key actor
- mood: breaking for crisis, neutral default, upbeat for positive resolution
""",
    "stadium": """ARCHETYPE: stadium — sports broadcast energy
- header_top: SCORE format ("TEAM 2-1 TEAM") OR action word
- header_bottom: event/stage ("90+3", "FINAL")
- photo_overlay: 2-5 words, action/stat caption like "PENALTI KAÇTI", "SON DAKİKA GOLÜ", "İLK 11'DE YOK". DO NOT describe the photo content (no "the player's face", "üzgün taraftar" etc.) — write a short caption tag.
- body_paragraph: 3-4 sentences, energetic sports-broadcast tone
- highlights: red=goal/critical event, yellow=player name/stat
- mood: breaking for last-minute, upbeat for victory
""",
    "stat-hero": """ARCHETYPE: stat-hero — single hero number + tight caption
- header_top: 2-4 words context label ("ENFLASYON", "ANKET SONUCU")
- header_bottom: 2-4 words specifier ("MAYIS 2026", "SEÇİME 3 GÜN")
- photo_overlay: 3-7 words context tag — usually a category clue
- body_paragraph: MUST contain ONE prominent number in the first 80
  characters; rest of the paragraph (≤180 chars total) explains what the
  number means. The template extracts the first number it sees and
  renders it as a giant hero stat, with the rest as caption beneath.
  Valid number forms (in priority order):
    "%54", "%54,3", "yüzde 25", "₺250 milyon", "1.500", "25 bin"
  EXAMPLE body: "%54,3 oran açıklandı; bütçe gelirleri rekor seviyede,
  vergi tahsilatı yıllık bazda artış gösterdi."
- highlights: red=düşüş/risk/eksi, yellow=artış/önemli sayı (NOT the
  hero number itself; highlight CONTEXT words around it)
- mood: usually neutral (analytical), breaking only on rekor / sürpriz
""",
    "bigquote": """ARCHETYPE: bigquote — fullscreen attributed quotation
- This template puts ONE quote on the screen huge. The quote IS the
  body_paragraph (max 800 chars but aim for 60-180 char punchy quotes).
- header_top: 2-4 words — WHO said it ("Maliye Bakanı", "Galatasaray Başkanı",
  "Cumhurbaşkanı"). Renders as "— Maliye Bakanı" attribution.
- header_bottom: 2-5 words — WHEN / WHERE / KONU ("Mayıs 2026", "TBMM kürsüsü",
  "Basın toplantısı", "Bütçe görüşmesi")
- photo_overlay: 2-7 words context tag — usually a category/topic clue
  ("BÜTÇE AÇIKLAMASI", "TRANSFER YORUMU", "DEPREM AÇIKLAMASI")
- body_paragraph: THE QUOTE ITSELF as a direct first-person statement.
  Must stand alone. NOT a 3rd-person description of what they said.
  GOOD: "Şampiyonluk hakkımızdır, hiç kimse bizi durduramaz."
  BAD:  "Galatasaray Başkanı şampiyonluğa olan inancını ifade etti."
  Length: 60-180 chars ideal; can go up to 300 for nuanced quotes.
- highlights: leave empty — quote is presented as-is, no inline highlights
- mood: usually neutral, breaking for inflammatory statements
""",
    "polaroid": """ARCHETYPE: polaroid — magazine/feature with tilted photo card
- Lifestyle / nostalji / culture / human-interest feel — NOT breaking news.
  Reads like a magazine spread, not a newsroom alert.
- header_top: 3-5 words feature headline ("ESKİ İSTANBUL'A YOLCULUK",
  "BİR USTANIN HİKAYESİ", "90'LARIN SES KÜLTÜRÜ")
- header_bottom: 4-7 words italic subtitle elaborating the headline
  ("Eski mahallenin son kalan ustası anlatıyor", "Kayıp bir kuşağın izinde")
- photo_overlay: 2-5 words HANDWRITTEN-style caption inside the polaroid frame.
  Short, personal, almost diary-like.
  ("İstanbul, 1987", "Kapalıçarşı sabahı", "Son ustalar")
- body_paragraph: 3-4 sentences, narrative / feature-writing tone (not
  breaking-news terse). Past or continuous tense, scene-setting.
  EXAMPLE: "Halıcıyı 40 yıldır aynı tezgâh ardında buluyorsunuz. Her sabah
  saat altıda dükkanı açar, müşterilerine kendi demlediği çayı ikram eder."
- highlights: red=key person/place name, yellow=year/era/cultural marker
- mood: usually neutral (reflective), upbeat for celebratory stories
""",
    "newscast-magazine": """ARCHETYPE: newscast-magazine — editorial/serif feature
- Reads like a print magazine front page (NYT/Atlantic feel), not breaking TV news.
- header_top: 3-6 words BIG serif headline; declarative, not sensational.
- header_bottom: 5-9 words italic subtitle elaborating the headline.
- photo_overlay: 2-4 words section/topic tag in small caps
  ("ECONOMY", "POLITICS", "INVESTIGATION").
- body_paragraph: 3-5 sentences, longer-form journalism tone. Treat the
  reader as informed; nuance + context > urgency.
- highlights: red=key figure, yellow=key number/date
- mood: usually neutral; breaking only for genuine front-page-worthy events.
""",
    "newscast-ticker": """ARCHETYPE: newscast-ticker — lower-third broadcast banner
- Photo dominates upper 2/3; red ticker stripe holds the headline + lead.
- header_top: 4-7 words punchy, all-caps-friendly news headline.
- header_bottom: 3-5 words follow-up clause (impact / subject / when).
- photo_overlay: 2-5 words key fact stamped over the photo
  ("250 BAZ PUAN", "92. DAKİKA", "AĞUSTOS VERİLERİ").
- body_paragraph: 1-2 SHORT sentences — only 2 lines fit. Lead with the
  impact, not the background.
- highlights: red=key figure, yellow=key number/decision
- mood: breaking by default
""",
    "stadium-scoreboard": """ARCHETYPE: stadium-scoreboard — two-team score callout
- header_top: HOME team name (1-2 words, ALLCAPS). Short league abbreviation
  also works (e.g. "GS", "FB", "RM", "BAR").
- header_bottom: AWAY team name (same format).
- photo_overlay: THE SCORE itself — "3-2", "1-1", "OT", "PEN 5-4". 1-6 chars.
  This is the dominant visual element on screen.
- category: tournament / round / matchday context — "SÜPER LİG", "DERBİ",
  "ÇEYREK FİNAL". 1-3 words, ALLCAPS.
- body_paragraph: 2-4 sentences recapping the match — key moment, scorer(s),
  context. Past tense.
- highlights: red=winning team / scorer name, yellow=minute / decisive moment
- mood: energetic; breaking if upset/last-minute
""",
    "stadium-spotlight": """ARCHETYPE: stadium-spotlight — single hero moment
- ONE player or moment dominates the screen. Use when a single name/figure
  drives the story (a goal, a record, a milestone).
- header_top: team / competition context, 1-3 words ("GALATASARAY", "DEVRE
  ARASI", "SÜPER LİG").
- header_bottom: 2-5 words secondary context ("Süper Lig 12. Hafta",
  "Şampiyonlar Ligi gecesi").
- photo_overlay: THE HERO NUMBER — minute, goal count, record number,
  ranking. SHORT (1-4 chars). Examples: "92'", "3", "100", "1.".
  This becomes a massive screen-dominating display.
- category: PLAYER / EVENT NAME — 1-2 words, ALLCAPS.
  ("ICARDI", "MERIH DEMİRAL", "REKOR").
- body_paragraph: 1-3 sentences explaining the moment. Punchy, not analytical.
- highlights: red=team name, yellow=stat/milestone
- mood: energetic / breaking
""",
}


def build_script_prompt_for_channel(item: NewsItem, body: str, channel: ChannelConfig) -> str:
    """Channel-aware prompt: includes archetype instructions + tone block + language."""
    lang_name = LANGUAGE_NAMES.get(channel.language, channel.language)
    arch_instructions = ARCHETYPE_PROMPTS.get(channel.template, ARCHETYPE_PROMPTS["newscast"])

    tone_text = ""
    if channel.dna is not None:
        t = channel.dna.tone
        tone_text = f"""
TONE OF VOICE:
- Voice: {t.voice}
- Style: {t.style}
- Forbidden: {", ".join(t.forbidden) if t.forbidden else "(none)"}
- Sentence max: {t.sentence_max_words} words
- Paragraph: {t.paragraph_sentences[0]}-{t.paragraph_sentences[1]} sentences
- Body max: {t.body_max_chars} characters
- Headline style: {t.headline_style_hint}
"""

    source = item.source or "—"
    return f"""You are writing a {lang_name} YouTube Shorts script.

ORIGINAL HEADLINE: {item.title}
SOURCE: {source}

ARTICLE BODY:
{body}

{arch_instructions}
{tone_text}
TASK: Convert this news into a 3-layer Short script. Output language: {lang_name}.
Output STRICT JSON only:
{{
  "header_top":      "...",
  "header_bottom":   "...",
  "photo_overlay":   "...",
  "body_paragraph":  "...",
  "highlights":      [{{"text": "<exact substring of body>", "color": "red"|"yellow"}}],
  "category":        "...",
  "mood":            "breaking" | "neutral" | "upbeat"
}}

Rules:
- All text in {lang_name}, with proper diacritics
- highlights[i].text must appear verbatim in body_paragraph
- Stay within tone constraints if specified above
- header_top: MAX 25 characters (hard limit, will be rejected otherwise)
- header_bottom: MAX 35 characters (hard limit, will be rejected otherwise)
"""


def build_script_prompt(item: NewsItem, body: str) -> str:
    source = item.source or "kaynak"
    return f"""Aşağıdaki Türkçe haberi 30 saniyelik dikey YouTube Shorts için hazırla.

ORİJİNAL BAŞLIK: {item.title}
KAYNAK: {source}

MAKALE GÖVDESİ:
{body}

Görev: Bu haberi 3-katmanlı bir Short videoya dönüştür. SADECE aşağıdaki JSON formatında yanıtla, başka metin yazma:

{{
  "header_top":      "<üst satır, 1-3 kelime, BÜYÜK HARF, dikkat çekici>",
  "header_bottom":   "<alt satır, 1-3 kelime, BÜYÜK HARF>",
  "photo_overlay":   "<fotoğraf üzeri sarı bantta görünecek, 2-5 kelime, BÜYÜK HARF, somut sayı/etki>",
  "body_paragraph":  "<haberi 4-5 cümlede özetleyen Türkçe paragraf, 250-320 karakter, akıcı haber dili>",
  "highlights":      [{{"text": "<paragrafta birebir geçen ifade>", "color": "red"|"yellow"}}],
  "category":        "<EKONOMİ | SPOR | DÜNYA | TEKNOLOJİ | SAĞLIK | SİYASET | SON DAKİKA | ...>",
  "mood":            "breaking" | "neutral" | "upbeat"
}}

Kurallar:
- highlights[i].text MUTLAKA body_paragraph içinde birebir (kelimesi kelimesine) geçmelidir
- 1-4 highlight ekle: önemli sayı/oran/karar = yellow; uyarı/tehlike/şok = red
- header_top: MAX 25 karakter (sert sınır, aşılırsa reddedilir)
- header_bottom: MAX 35 karakter (sert sınır, aşılırsa reddedilir)
- header_top + header_bottom toplam 4-6 kelimeyi geçmesin
- Yazım Türkçe, diakritikler tam (ç, ğ, ı, ö, ş, ü)
"""


def write_script(
    item: NewsItem,
    body: str,
    *,
    claude_path: str = "claude",
    channel: ChannelConfig | None = None,
    model: str = "default",
    overflow_feedback: str = "",
) -> Script:
    prompt = (build_script_prompt_for_channel(item, body, channel)
              if channel is not None else build_script_prompt(item, body))
    if overflow_feedback:
        prompt = prompt + "\n\n" + overflow_feedback + "\n"
    return run_json(prompt, Script, claude_path=claude_path, model=model, retries=3)
