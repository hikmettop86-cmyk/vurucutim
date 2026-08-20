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


# Hashtag ÖRNEĞİ dile özgü olmalı. Örnek Türkçe sabit kalınca Almanca kanalın
# metadata'sına "#sondakika" sızıyordu: model örneği kopyalar, kural metnini
# değil. (Aynı aile: çok dilli sessiz tuzaklar — persona/yasak listesi.)
_HASHTAG_ORNEK: dict[str, str] = {
    "tr": "#shorts #sondakika #haber",
    "de": "#shorts #eilmeldung #nachrichten #deutschland",
    "en": "#shorts #breakingnews #news",
    "es": "#shorts #ultimahora #noticias",
    "fr": "#shorts #actualites #info",
    "ja": "#shorts #速報 #ニュース",
}


def search_terms_for(eng, channel, limit: int = 12) -> list[str]:
    """Bu kanalın metadata'da kullanılacak KANITLI arama sözlüğü.

    Kimliğini başka kanaldan ödünç alan formatlarda (youtube.credentials_from —
    ör. gundem-yorum → gundem) sorgular YouTube KANALINA aittir, short-bot
    slug'ına değil; bu yüzden önce ödünç veren slug denenir. Ölçüm henüz yoksa
    boş liste döner ve metadata yalnız konunun Trends sorgularıyla yazılır.

    Hiçbir hata yükseltmez: sözlük bir iyileştirmedir, yükleme şartı değildir.
    """
    try:
        from short_bot.db import top_search_terms
        from short_bot.youtube import auth as _auth
        primary = _auth.creds_slug(channel)
        terms = top_search_terms(eng, primary, limit=limit)
        if not terms and primary != channel.slug:
            terms = top_search_terms(eng, channel.slug, limit=limit)
        return terms
    except Exception:  # noqa: BLE001
        return []


def _search_block(script: dict, search_terms, language: str) -> str:
    """ARAMA SÖZLÜĞÜ bloğu: izleyicinin gerçekten YAZDIĞI dizeler.

    İki kaynak birleşir:
      * ``script["search_queries"]`` — bu KONUNUN canlı sorguları (Google Trends
        ilişkili aramaları, hacim sırasında). Konuşulan metne asla girmez
        (bkz. narration_writer.BANNED_PHRASES) ama metadata YouTube'un metni
        sorguyla eşleştirdiği tek yer.
      * ``search_terms`` — bu KANALIN kanıtlı sorguları (YouTube Analytics,
        youtube_search_terms tablosu): izleyiciler bizi fiilen bu kelimelerle
        buldu.

    Ölçüm (2026-08-20, Aslan Gündem 28 gün): aramadan gelen 245K izlenmenin
    tamamı VARLIK+NİYET kalıbındaydı ("galatasaray transfer son dakika"), soru
    değil; ve "gs" kısaltması ayda 25K+ izlenme getirdiği hâlde hiçbir
    başlığımızda geçmiyordu. Blok bu iki gerçeği doğrudan hedefler.
    """
    from short_bot.search_intent import ranked_queries

    trend_q = ranked_queries(script.get("search_queries") or (), language=language)
    proven = [t for t in (search_terms or []) if str(t).strip()][:12]
    if not trend_q and not proven:
        return ""
    parts = ["\nARAMA SÖZLÜĞÜ (İZLEYİCİ TAM OLARAK BUNLARI YAZIYOR):"]
    if trend_q:
        parts.append("- Bu konunun canlı sorguları: " + " | ".join(trend_q))
    if proven:
        parts.append("- Kanalın kanıtlı sorguları (bizi bu kelimelerle buldular): "
                     + " | ".join(str(t) for t in proven))
    parts.append(
        "\nARAMA KURALLARI (title/description/tags bunlara göre kurulur):\n"
        "1. BAŞLIK: yukarıdaki sorgulardan HABERLE ÖRTÜŞEN en üsttekinin "
        "kelimelerini BİREBİR ve BAŞTA taşı. Örtüşmeyeni ZORLAMA.\n"
        "2. Konuyla ilgisiz sorguyu EKLEME — yanlış eşleşme izlenmeyi düşürür, "
        "tıklayan kişi hemen çıkar.\n"
        "3. KISALTMAYI da yaz (gs, fb, ŞL gibi): başlığa sığmıyorsa açıklamanın "
        "ilk iki satırına ve etiketlere koy.\n"
        "4. Etiketleri sorgudaki gibi YAZ — 'son dakika' boşlukluysa boşluklu "
        "yaz, 'sondakika' diye birleştirme.\n"
        "5. Açıklamanın İLK SATIRI sorgunun karşılığını doğrudan versin "
        "(arayan kişi cevabı ilk satırda görsün).")
    return "\n".join(parts) + "\n"


def build_metadata_prompt(*, channel, script: dict,
                          rss_source: str | None,
                          rss_link: str | None,
                          hook_patterns=None, base_title: str = "",
                          search_terms=None) -> str:
    """Compose the prompt for Sonnet. Returns a string.

    ``search_terms``: kanalın kanıtlı arama sözlüğü (db.top_search_terms).
    Boş geçilebilir — o zaman yalnız konunun Trends sorguları kullanılır."""
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
    search_block = _search_block(script, search_terms, channel.language)
    hashtag_ornek = _HASHTAG_ORNEK.get(channel.language, _HASHTAG_ORNEK["en"])

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
{search_block}
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
   alakalı + handle. Örn: "{hashtag_ornek} #{channel.handle.replace('@', '')}"

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
                              hook_patterns=None, base_title: str = "",
                              search_terms=None) -> YoutubeMetadata:
    """Call Sonnet to produce metadata. Raises ClaudeCliError on failure —
    callers should fall back to non-LLM build_snippet."""
    prompt = build_metadata_prompt(
        channel=channel, script=script,
        rss_source=rss_source, rss_link=rss_link,
        hook_patterns=hook_patterns, base_title=base_title,
        search_terms=search_terms,
    )
    return run_json(
        prompt, YoutubeMetadata,
        claude_path=claude_path, model=model,
        backend=backend, api_key=api_key,
        retries=2, timeout_s=120,
    )
