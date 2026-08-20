"""LLM script writer: news item + body → Script (header / overlay / paragraph / highlights)."""
from __future__ import annotations

from short_bot.claude_cli import run_json
from short_bot.config import ChannelConfig
from short_bot.dna import _DESIGNED_ARCHETYPES
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
    # ─── Designed archetypes — auto-generated from config/archetypes.json
    # Same content schema as newscast (header_top + header_bottom + photo_overlay
    # + body_paragraph), different visual styling. Generic newscast prompt +
    # JSON's label+subtitle as style hint.
    **{
        a["slug"]: f"""ARCHETYPE: {a["slug"]} — visual style: {a["label"]}, {a["subtitle"]}
- header_top + header_bottom: 4-6 words total, news headline (ALLCAPS dostu)
- photo_overlay: 2-5 words, key fact (stat/decision/action), max 60 chars
- body_paragraph: 3-4 sentences, neutral journalistic tone, max 300 chars
- highlights: red=warning/risk, yellow=stat/decision/key actor
- mood: breaking for crisis, neutral default, upbeat for positive resolution
"""
        for a in _DESIGNED_ARCHETYPES
    },
    # ─── NFL gameday — özel spor prompt'u. Aynı anahtar comprehension'da generic
    # üretildiği için bu explicit tanım (dict literal'de sonra geldiğinden) onu ezer.
    "nfl-gameday": """ARCHETYPE: nfl-gameday — American football (NFL) gameday broadcast energy
- header_top (max 25 chars): SCORE or big action. Prefer "TEAM ## - ## TEAM" score format when the news is a result; else a punchy ALLCAPS action line (e.g. "TOUCHDOWN CHIEFS", "OT THRILLER"). NFL team names/abbreviations OK.
- header_bottom (max 35 chars): game context / stakes (quarter, week, playoff round, record) — e.g. "4th quarter, 0:12 left", "Week 12, AFC clash".
- photo_overlay (max 60 chars): on-field action tag, ALLCAPS punchy (e.g. "TOUCHDOWN!", "4TH & GOAL", "PICK SIX", "GAME-WINNING FG").
- body_paragraph: 2-4 sentences, gameday hype tone. Use NFL terminology naturally (touchdown, QB, yards, sack, interception/INT, drive, red zone, field goal, end zone). Lead with the decisive play/result.
- highlights: wrap the key player name(s) and the decisive number/score — color "red" for scores/results, "yellow" for player names.
- category: "NFL" or the specific matchup/round.
- mood: "breaking" for finals/upsets, "upbeat" for highlights/wins.
- KEEP NFL terms in English even when the output language is not English.""",
}


# Şablonun GERÇEK manşet kapasitesi (ölçülmüş), Pydantic'in 25 karakterlik
# kırpma sınırı değil. stadium'un 200px Oswald başlığı satır başına ~5 karakter
# alıyor; iki kanalda 463 kırpılmamış manşet ölçüldü — galatasaray medyan 10 /
# p90 16, fenerbahce medyan 9 / p90 11. Prompt 25 dediği için LLM 16 karakter
# yazıyor, render reddediyor, 3 retry LLM çağrısı yanıyor ve sonunda kelime
# ortadan kesiliyordu: galatasaray manşetlerinin %59'unda "…" var.
# Ölçüm yapılmamış şablonlar eski 25 değerinde kalır.
_HEADER_TOP_BUDGET = {"stadium": 14}
_DEFAULT_HEADER_TOP_BUDGET = 25


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

    # Canonical kategori listesi: serbest etiket learning/aggregator'ın konu
    # kovalarını böldüğü için (aynı konuya "Transfer"/"transfer"/"Futbol
    # Transfer") kanal bir liste tanımlayabilir. Tanımlamayanlar eski
    # serbest davranışta kalır.
    category_spec = "..."
    category_rule = ""
    if channel.categories:
        allowed = " | ".join(channel.categories)
        category_spec = f"<{allowed}>"
        category_rule = (
            f"\n- category: pick EXACTLY ONE from this list, verbatim: {allowed}. "
            f"Do not invent a new label, do not translate it, do not change its case."
        )

    header_top_budget = _HEADER_TOP_BUDGET.get(
        channel.template, _DEFAULT_HEADER_TOP_BUDGET)

    source = item.source or "—"
    trend_block, trend_rules = _trend_context(item, channel)
    return f"""You are writing a {lang_name} YouTube Shorts script.

ORIGINAL HEADLINE: {item.title}
SOURCE: {source}

ARTICLE BODY:
{body}
{trend_block}
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
  "category":        "{category_spec}",
  "mood":            "breaking" | "neutral" | "upbeat"
}}

Rules:{category_rule}
- FACTUAL ACCURACY (critical): Use ONLY facts present in the ARTICLE BODY above. Do NOT invent or guess names, numbers, dates, ages, fees, scores, titles, records, or events. If a specific figure is not in the source, do not state one. Never attribute quotes or actions to people not named in the source. If the article is thin, write a shorter factual script instead of padding with fabricated details.
- All text in {lang_name}, with proper diacritics
- highlights[i].text must appear verbatim in body_paragraph
- Stay within tone constraints if specified above
- header_top: MAX {header_top_budget} characters (hard limit, will be rejected otherwise).
  Shorter is better — one strong word beats a truncated phrase.
- header_bottom: MAX 35 characters (hard limit, will be rejected otherwise){trend_rules}
"""


def _trend_context(item: NewsItem, channel: ChannelConfig) -> tuple[str, str]:
    """Trend kanalında (content_source=trends) kartın 'kendi değer katmanı':
    arama hacmi + ilişkili aramalar. Yayıncının haberini özetleyen bin kanaldan
    ayıran tek veri bu; gövdenin son cümlesi 'neden gündemde' olur ve KJ satırı
    hacmi taşıyabilir. Ayrıca tek bir BAĞLAM cümlesine izin verilir (kıyas/sıra/
    büyüklük — gövdedeki bilgiden, yorum değil). Politika gerekçesi: toplu
    üretilmiş 'haber özeti' yerine dönüştürülmüş içerik (2026-08-20 notu).
    Trend verisi yoksa ikisi de boş döner, prompt bit bit aynı kalır."""
    if getattr(channel, "content_source", "") != "trends":
        return "", ""
    if not item.trend_volume or not (item.description or "").strip():
        return "", ""
    block = (
        "\nWHAT PEOPLE ARE SEARCHING FOR (internal signal — tells you which questions "
        "the body should answer; NEVER mention it on screen):\n"
        f"{item.description.strip()}\n"
    )
    rules = (
        "\n- CONTEXT SENTENCE: include exactly ONE sentence that places the event in "
        "context (a comparison, a sequence, a magnitude: 'the 36th tremor in 8 hours', "
        "'the first since 2019') — built ONLY from facts in the article body or the "
        "related searches above. No opinion, no adjectives of judgement."
        "\n- The related searches tell you what people actually want to know — answer the "
        "biggest of those questions inside the body."
        "\n- NEVER write that the topic is trending, how many people searched it, or mention "
        "search engines / Google Trends. That is our internal selection signal, not content; "
        "on screen it reads as automation."
    )
    return block, rules


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
- OLGUSAL DOĞRULUK (kritik): SADECE yukarıdaki MAKALE GÖVDESİ'nde geçen bilgileri kullan. İsim, sayı, tarih, yaş, ücret, skor, unvan, rekor veya olay UYDURMA. Kaynakta olmayan spesifik bir rakam verme; kaynakta geçmeyen kişilere söz/eylem atfetme. Haber zayıfsa uydurma detayla şişirme — daha kısa ama doğru bir script yaz.
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
    backend: str = "claude_cli",
    api_key: str | None = None,
) -> Script:
    prompt = (build_script_prompt_for_channel(item, body, channel)
              if channel is not None else build_script_prompt(item, body))
    if overflow_feedback:
        prompt = prompt + "\n\n" + overflow_feedback + "\n"
    return run_json(prompt, Script, claude_path=claude_path, model=model,
                    backend=backend, api_key=api_key, retries=3)
