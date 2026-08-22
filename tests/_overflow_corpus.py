# tests/_overflow_corpus.py
"""Per-language word pools for synthesizing scripts at controlled lengths.

Real news vocabulary (not lorem ipsum) so character distributions match
production. Word length distribution per language is roughly authentic:
  - TR: agglutinative, longer average word
  - DE: compound nouns, longest average
  - EN, ES, FR: shorter
"""
from __future__ import annotations


WORDS: dict[str, list[str]] = {
    "tr": [
        "hükümet", "ekonomi", "asgari", "ücret", "zam", "enflasyon",
        "karar", "açıklama", "bakanlık", "milyon", "vatandaş", "çalışan",
        "uyarı", "tehlike", "rapor", "borsa", "döviz", "kur", "piyasa",
        "tarih", "süre", "dönem", "haber", "son", "dakika", "kritik",
        "skandal", "kriz", "şok", "bekleyiş", "müzakere", "anlaşma",
    ],
    "en": [
        "government", "economy", "inflation", "wage", "increase", "decision",
        "ministry", "million", "citizen", "worker", "warning", "danger",
        "report", "stock", "currency", "exchange", "market", "deadline",
        "period", "breaking", "news", "critical", "scandal", "crisis",
        "shock", "negotiation", "agreement", "budget", "policy", "reform",
    ],
    "de": [
        "Bundesregierung", "Wirtschaft", "Inflation", "Mindestlohn",
        "Erhöhung", "Entscheidung", "Ministerium", "Millionen",
        "Bürgerinnen", "Arbeitnehmer", "Warnung", "Gefahr", "Bericht",
        "Börse", "Devisenkurs", "Markt", "Frist", "Zeitraum", "Eilmeldung",
        "Nachrichten", "kritisch", "Skandal", "Krise", "Schock",
        "Verhandlung", "Vereinbarung", "Haushalt", "Reform", "Wahlkampf",
    ],
    "fr": [
        "gouvernement", "économie", "inflation", "salaire", "augmentation",
        "décision", "ministère", "millions", "citoyens", "travailleurs",
        "avertissement", "danger", "rapport", "bourse", "devises", "marché",
        "délai", "période", "actualité", "critique", "scandale", "crise",
        "négociation", "accord", "budget", "politique", "réforme", "élection",
    ],
    "es": [
        "gobierno", "economía", "inflación", "salario", "aumento", "decisión",
        "ministerio", "millones", "ciudadanos", "trabajadores", "advertencia",
        "peligro", "informe", "bolsa", "divisa", "mercado", "plazo",
        "período", "noticia", "crítico", "escándalo", "crisis", "negociación",
        "acuerdo", "presupuesto", "política", "reforma", "elección",
    ],
}


def synthesize_text(language: str, target_chars: int, rng) -> str:
    """Pick random words until total length reaches target_chars."""
    pool = WORDS[language]
    out: list[str] = []
    total = 0
    while total < target_chars:
        w = pool[rng.randrange(len(pool))]
        out.append(w)
        total += len(w) + 1   # +1 for the space
    return " ".join(out)[:target_chars].rstrip()
