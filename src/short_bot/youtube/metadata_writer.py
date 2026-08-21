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


# DİKEYE ÖZGÜ BAŞLIK KURALLARI. Prompt TALİMATLARI Türkçe (çıktı dili ayrıca
# söyleniyor), bu yüzden dil başına çoğaltmaya gerek yok.
#
# NEDEN VAR: personalara koyulan güvenlik kuralları yalnız ANLATIMI koruyordu.
# Başlık en görünür metin ve YouTube'un indekslediği şey; anlatımı "iddia
# ediliyor" diyen bir videonun başlığı suçu kesinleyebiliyordu.
_VERTICAL_META_RULES: dict[str, str] = {
    "para": (
        "- YATIRIM TAVSİYESİ YASAK: başlık ya da açıklama 'şunu al', 'şuraya "
        "yatır', 'şu banka daha iyi' DEMEZ. Ne olduğunu söyle, kararı izleyiciye "
        "bırak.\n"
        "- Rakam varsa başlığa koy ama SONUCU uydurma ('7.052 TL' evet, "
        "'10 bine gidiyor' hayır)."),
    "adalet": (
        "- MASUMİYET KARİNESİ BAŞLIKTA DA GEÇERLİ: şüpheyi suç gibi KESİNLEŞTİRME. "
        "'öldürdü' değil 'öldürmekle suçlanıyor'; dava hangi safhadaysa onu yaz "
        "(şüphe / soruşturma / iddianame / karar).\n"
        "- Şüpheli ve mağdur TAM ADLA anılmaz."),
    "magazin": (
        "- ÖZEL HAYAT SPEKÜLASYONU YASAK: doğrulanmamış ilişki, ayrılık, boşanma "
        "ya da hastalık iddiasını başlıkta KESİN gibi yazma. Kaynak varsa "
        "'... açıkladı' de; yoksa o iddiayı başlığa hiç alma.\n"
        "- Kimseyi aşağılayan ya da alay eden başlık kurma."),
    "spor": (
        "- Skor, transfer ve sakatlık bilgisi KESİN olmalı; söylentiyi "
        "gerçekleşmiş gibi yazma ('imzaladı' ile 'görüşüyor' aynı şey değil)."),
    "olay": (
        "- Can kaybı ve yaralı sayısını yalnız RESMİ kaynak verdiyse yaz.\n"
        "- Mağdurları teşhir eden ya da felaketi şova çeviren başlık kurma."),
    "teknoloji": (
        "- Duyuru ile çıkış tarihini karıştırma; sızıntıyı doğrulanmış gibi "
        "yazma ('sızdı' ile 'açıklandı' ayrı şeyler)."),
}

# CJK dilleri Latin'den ÇOK daha yoğun: '藤井風 タイ公演中止を発表 事務所が理由を説明'
# zaten 25 karakter ve tam bir cümle. 60-100 karakter dayatmak modeli DOLGU
# yapmaya iter — tam da kaçındığımız AI-slop.
_CJK_DILLER = frozenset({"ja", "zh", "ko"})


def _baslik_butcesi(language: str) -> str:
    """Başlık karakter bütçesi. CJK'de Latin bütçesi dolgu ürettirir."""
    return "20-40" if (language or "").split("-")[0].lower() in _CJK_DILLER else "60-100"


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

    # Dikey kuralları + kanalın kendi yasak listesi. İkisi de yalnız VARSA girer;
    # dikeysiz kanalın prompt'u bit bit eskisi gibi kalır.
    _dikey = getattr(channel, "trends_vertical", None)
    dikey_block = ""
    if _dikey:
        from short_bot.trends.verticals import VERTICAL_LABELS
        kural = _VERTICAL_META_RULES.get(_dikey, "")
        etiket = VERTICAL_LABELS.get(_dikey, _dikey)
        dikey_block = (f"\nKANALIN DİKEYİ: {etiket}\n"
                       f"Başlık ve açıklama bu dikeyin kurallarına UYMAK ZORUNDA:\n"
                       f"{kural}\n")
    _dna = getattr(channel, "dna", None)
    _yasak = list(getattr(getattr(_dna, "tone", None), "forbidden", []) or [])
    if _yasak:
        dikey_block += ("\nBU KANALDA YASAK (kart kuralları başlık için de geçerli):\n"
                        + "\n".join(f"- {y}" for y in _yasak) + "\n")
    baslik_butcesi = _baslik_butcesi(channel.language)

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
    # HASHTAG ÖRNEĞİ ÖNCE KANALIN KENDİ KELİMELERİNDEN. Sabit dil örneği
    # ("#shorts #速報 #ニュース") HABER tonlu; magazin kanalına sızıyordu.
    # Kodun kendi dersi: model ÖRNEĞİ kopyalar, kural metnini değil. Kanalın
    # anahtar kelimeleri hem dile hem dikeye tanım gereği doğru.
    _kw = [k.strip() for k in (channel.keywords or []) if k and k.strip()][:3]
    if _kw:
        hashtag_ornek = "#shorts " + " ".join(
            "#" + k.replace(" ", "") for k in _kw)
    else:
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
{hook_block}{dikey_block}
GÖREV: Aşağıdaki kurallara göre title + description + tags üret.

TITLE KURALLARI:
- {baslik_butcesi} karakter (max 100 ZORUNLU)
- {lang_name} dilinde
- VARLIK + NİYET kalıbı: başlığa önce ÖZNEYİ yaz (kişi, kurum, kulüp,
  ürün, eser adı), hemen ardından NE OLDUĞUNU. Ölçüldü (28 gün, YouTube
  Analytics arama terimleri): kanalı bulan ilk 25 sorgunun hiçbiri soru
  değildi, hepsi varlık+niyet kalıbıydı ('galatasaray transfer', 'gs
  transfer son dakika'). Genel kategori kelimesiyle ('son dakika haber')
  BAŞLAMA.
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
  "title": "<{baslik_butcesi} char>",
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
