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
    "tabloid": """ARCHETYPE: tabloid — provocative, sensational
- header_top: provocative question or exclamation
- header_bottom: short follow-up phrase
- photo_overlay: gossip-style claim ("EXPOSED!" / "SHOCK!")
- body_paragraph: 2-3 punchy sentences, sensational tone
- highlights: red=scandal, yellow=name/place
- mood: usually breaking
""",
    "magazine": """ARCHETYPE: magazine — elegant, longform
- header_top: poetic 2-4 word title
- header_bottom: subtitle phrase or attribution
- photo_overlay: thoughtful sub-tagline
- body_paragraph: 5-7 sentences, elegant, descriptive
- highlights: yellow=key idea, red sparingly
- mood: usually neutral or upbeat
""",
    "kinetic": """ARCHETYPE: kinetic — typography-led, single-focus
- header_top: 1-2 PUNCHY words OR a number
- header_bottom: 1 short phrase OR empty
- photo_overlay: brief context (≤5 words)
- body_paragraph: 1-2 short sentences (max 80 chars total)
- highlights: 0-1, neon style
- mood: any, often upbeat for stat/insight
""",
    "dark-tech": """ARCHETYPE: dark-tech — terminal, codified
- header_top: codified-style "> NEWS_DROP" or "[ALERT]"
- header_bottom: tech topic descriptor
- photo_overlay: 3-6 words technical claim
- body_paragraph: 3-4 sentences, factual, can include code-flavored terms
- highlights: green/cyan=key tech, red=vulnerability/risk
- mood: usually breaking for vulnerabilities, upbeat for releases
""",
    "stadium": """ARCHETYPE: stadium — sports broadcast energy
- header_top: SCORE format ("TEAM 2-1 TEAM") OR action word
- header_bottom: event/stage ("90+3", "FINAL")
- photo_overlay: 2-5 words, action/stat caption like "PENALTI KAÇTI", "SON DAKİKA GOLÜ", "İLK 11'DE YOK". DO NOT describe the photo content (no "the player's face", "üzgün taraftar" etc.) — write a short caption tag.
- body_paragraph: 3-4 sentences, energetic sports-broadcast tone
- highlights: red=goal/critical event, yellow=player name/stat
- mood: breaking for last-minute, upbeat for victory
""",
    "meme": """ARCHETYPE: meme — Impact-style top/bottom text
- header_top: TOP TEXT (Impact-meme, ALL CAPS, ≤5 words)
- header_bottom: BOTTOM TEXT (≤5 words, punchline)
- photo_overlay: empty OR a short tag
- body_paragraph: 1 short caption (≤60 chars)
- highlights: 0-1, edgy
- mood: usually upbeat
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
) -> Script:
    prompt = (build_script_prompt_for_channel(item, body, channel)
              if channel is not None else build_script_prompt(item, body))
    return run_json(prompt, Script, claude_path=claude_path, model=model, retries=3)
