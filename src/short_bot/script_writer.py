"""LLM script writer: news item + body → Script (header / overlay / paragraph / highlights)."""
from short_bot.claude_cli import run_json
from short_bot.models import NewsItem, Script


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
- header_top + header_bottom toplam 4-6 kelimeyi geçmesin
- header_top + header_bottom toplam ≤6 kelime VE her satır ≤14 harf (uzun tek kelime taşar)
- Yazım Türkçe, diakritikler tam (ç, ğ, ı, ö, ş, ü)
"""


def write_script(item: NewsItem, body: str, *, claude_path: str = "claude") -> Script:
    prompt = build_script_prompt(item, body)
    return run_json(prompt, Script, claude_path=claude_path, retries=3)
