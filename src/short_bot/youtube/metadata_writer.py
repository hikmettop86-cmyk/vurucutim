"""Sonnet-driven YouTube metadata generation — title + description + tags.

Output is calibrated for short-form videos (≤60s):
- Title: 80-100 chars, language-native, keyword-front-loaded
- Description: hook + summary + source credit + fair-use disclaimer + hashtags
- Tags: 8-15 relevant, channel-tuned

Generator-mode shorts (no rss source) get an "AI-generated original" notice
instead of source attribution.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from short_bot.claude_cli import run_json
from short_bot.locale import LANGUAGE_NAMES


class YoutubeMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=10, max_length=4900)
    tags: list[str] = Field(default_factory=list, min_length=0, max_length=20)


def build_metadata_prompt(*, channel, script: dict,
                          rss_source: str | None,
                          rss_link: str | None,
                          hook_patterns=None, base_title: str = "") -> str:
    """Compose the prompt for Sonnet. Returns a string."""
    lang_name = LANGUAGE_NAMES.get(channel.language, channel.language)

    # MİZAH PERSONA override'ı: prompt varsayılan olarak HABER-tonlu (fair-use
    # disclaimer, #sondakika, kuru dil). Kanalın bir reel personası varsa (mizah)
    # bu ton YANLIŞ. Aşağıdaki blok en sona konur ve varsayılanları EZER; ayrıca
    # reel zaten iyi bir SEO başlığı (base_title) ürettiyse onu temel al.
    _reel = getattr(channel, "reel", None)
    _persona_raw = getattr(_reel, "persona", "") if _reel is not None else ""
    _persona = _persona_raw.strip() if isinstance(_persona_raw, str) else ""
    override = ""
    if base_title:
        override += (f"ZATEN İYİ BİR VİDEO BAŞLIĞI VAR: {base_title!r}\n"
                     f"Bunu KORU ya da hafif iyileştir; anahtar kelime EN BAŞTA kalsın.\n")
    if _persona:
        override += (
            "KANAL TONU (EN ÖNEMLİ — yukarıdaki haber kurallarını EZER): Bu bir MİZAH/"
            "EĞLENCE Shorts kanalı, HABER DEĞİL. Başlık + açıklama EĞLENCELİ, sokak-ağzı, "
            "merak açan olsun; kuru/resmi haber dili KULLANMA. Fair-use/haber-özeti "
            "disclaimer'ını EKLEME (bu ÖZGÜN mizah içeriği, haber alıntısı değil). "
            "Hashtag'ler mizah/hayvan/eğlence odaklı olsun (ör. #shorts #komik #hayvanlar "
            "#mizah), #sondakika/#haber KULLANMA.\n")
    override_block = ("\n" + override + "\n") if override else ""

    hook_block = ""
    if hook_patterns:
        pats = "\n".join(f"- {p}" for p in hook_patterns)
        hook_block = (f"KANITLANMIŞ BAŞLIK ÖRÜNTÜLERİ (nişte patlamış videolardan):\n"
                      f"{pats}\n"
                      f"CTR kuralları: İlk 3 kelime vurucu olsun; merak boşluğu "
                      f"bırak; mümkünse somut sayı kullan. Kanal tonunun "
                      f"yasaklarına uy.\n\n")

    if rss_source and rss_link:
        source_block = (
            f"KAYNAK BİLGİSİ:\n"
            f"- Outlet: {rss_source}\n"
            f"- Orijinal link: {rss_link}\n"
            f"- Bu içerik bir haber özetidir. Açıklamada kaynak mutlaka belirt.\n"
        )
    else:
        source_block = (
            "KAYNAK BİLGİSİ:\n"
            "- Bu kanal AI ile özgün kısa içerik üretiyor (haber özeti DEĞİL).\n"
            "- Açıklamada 'Bu içerik yapay zeka ile özgün olarak üretilmiştir' notu olsun.\n"
        )

    body = script.get("body_paragraph", "")
    keywords = ", ".join((channel.keywords or [])[:8])

    return f"""Sen bir YouTube Shorts kanalı için SEO-uyumlu metadata üreticisisin.

KANAL:
- Adı: {channel.name}
- Handle: {channel.handle}
- Dil: {lang_name}
- Anahtar kelimeler: {keywords}

İÇERİK:
- Başlık üst: {script.get("header_top", "")}
- Başlık alt: {script.get("header_bottom", "")}
- Gövde: {body}
- Kategori: {script.get("category", "")}
- Mood: {script.get("mood", "")}

{source_block}
{hook_block}
GÖREV: Aşağıdaki kurallara göre title + description + tags üret.

TITLE KURALLARI:
- 60-100 karakter (max 100 ZORUNLU)
- {lang_name} dilinde
- Anahtar kelime başta (SEO)
- Clickbait DEĞİL — dürüst, içeriği yansıtan
- "Shocking", "You won't believe" gibi yapay heyecan KULLANMA
- Sayı/tarih varsa başa al ("3 dakika", "2026 öncesi" gibi)

DESCRIPTION KURALLARI ({lang_name} dilinde):
1. İlk satır (mobile preview ~150 char): vurucu, içeriği özetleyen tek cümle
2. Boş satır
3. 2-4 cümlelik tam özet (haberin/içeriğin ne anlattığını detaylı açıklayan)
4. Boş satır
5. Kaynak bloğu (varsa "Kaynak: {{outlet}} — {{link}}", yoksa AI özgün notu)
6. Boş satır
7. Telif/Fair Use disclaimer ({lang_name} dilinde, 2-3 cümle):
   "Bu video haber içeriklerinin kısa özetidir. Görsel ve metin alıntıları
   bilgilendirme amaçlı, fair use kapsamında kullanılmıştır. Telif hakları
   ilgili kaynaklara aittir. İçeriğinin kaldırılmasını talep eden hak
   sahipleri kanal sahibiyle iletişime geçebilir."
8. Boş satır
9. Hashtag bloğu: 5-10 tag, son satırda. #shorts MUTLAKA dahil. Konuyla
   alakalı + handle. Örn: "#shorts #sondakika #haber #{channel.handle.replace('@', '')}"

TAGS KURALLARI:
- 8-15 tag (kesinlikle ≤20)
- {lang_name} ve İngilizce karışık olabilir
- 1-3 kelimeli, virgülsüz
- Genel ("haber") + spesifik (konu kelimeleri)
- "shorts" tag'i MUTLAKA dahil
{override_block}
ÇIKTI: SADECE aşağıdaki JSON formatında, başka metin yazma:
{{
  "title": "<60-100 char>",
  "description": "<full description with sections>",
  "tags": ["...", "..."]
}}
"""


def generate_youtube_metadata(*, channel, script: dict,
                              rss_source: str | None, rss_link: str | None,
                              claude_path: str = "claude",
                              model: str = "sonnet",
                              backend: str = "claude_cli",
                              api_key: str | None = None,
                              hook_patterns=None, base_title: str = "") -> YoutubeMetadata:
    """Call Sonnet to produce metadata. Raises ClaudeCliError on failure —
    callers should fall back to non-LLM build_snippet."""
    prompt = build_metadata_prompt(
        channel=channel, script=script,
        rss_source=rss_source, rss_link=rss_link,
        hook_patterns=hook_patterns, base_title=base_title,
    )
    return run_json(
        prompt, YoutubeMetadata,
        claude_path=claude_path, model=model,
        backend=backend, api_key=api_key,
        retries=2, timeout_s=120,
    )
