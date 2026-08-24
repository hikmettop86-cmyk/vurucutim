"""Sonnet-driven YouTube metadata generation — title + description + tags.

Output is calibrated for short-form videos (≤60s):
- Title: 80-100 chars, language-native, keyword-front-loaded
- Description: hook + summary + source credit + fair-use disclaimer + hashtags
- Tags: 8-15 relevant, channel-tuned

Generator-mode shorts (no rss source) get an "AI-generated original" notice
instead of source attribution.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from short_bot.claude_cli import run_json
from short_bot.locale import LANGUAGE_NAMES
from short_bot.text_normalize import turkce_gorunuyor_mu

log = logging.getLogger(__name__)


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

# YAPAY ZEKÂ NOTU dile özgü olmalı. Örnek Türkçe SABİT kalınca model onu OLDUĞU
# GİBİ kopyalıyordu: ölçüldü (short #1892, latidoblanco-flash) — İspanyolca bir
# açıklamanın ortasına "Bu içerik yapay zeka ile özgün olarak üretilmiştir."
# düştü. Hashtag örneği ve kaynak etiketi aynı dersle zaten dile bağlanmıştı;
# bu üçüncü sabit gözden kaçmıştı. Kuralın kendisi Türkçe kalabilir — model
# KURALI değil ÖRNEĞİ kopyalar.
_AI_NOTU: dict[str, str] = {
    "tr": "Bu içerik yapay zeka ile özgün olarak üretilmiştir.",
    "de": "Dieser Inhalt wurde mithilfe künstlicher Intelligenz erstellt.",
    "en": "This content was originally created with artificial intelligence.",
    "es": "Este contenido ha sido creado de forma original con inteligencia artificial.",
    "fr": "Ce contenu a été créé de manière originale avec l'intelligence artificielle.",
    "ja": "このコンテンツはAIによってオリジナル制作されています。",
}


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
        "kelimelerini başlıkta GEÇİR — ama DOĞAL BİR MANŞETİN İÇİNDE, "
        "cümlenin parçası olarak. Sorguyu başlığın önüne etiket gibi "
        "YAPIŞTIRMA: '<sorgu>: <manşet>' kalıbı YASAK. Sorgunun kendi "
        "yazımını (küçük harf) TAŞIMA — başlık dilin normal büyük harf "
        "kurallarına uyar. Örtüşmeyeni ZORLAMA.\n"
        "2. Konuyla ilgisiz sorguyu EKLEME — yanlış eşleşme izlenmeyi düşürür, "
        "tıklayan kişi hemen çıkar.\n"
        "3. KISALTMAYI da yaz (gs, fb, ŞL gibi): başlığa sığmıyorsa açıklamanın "
        "ilk iki satırına ve etiketlere koy.\n"
        "4. Etiketleri sorgudaki gibi YAZ — 'son dakika' boşlukluysa boşluklu "
        "yaz, 'sondakika' diye birleştirme.\n"
        "5. Açıklamanın İLK SATIRI sorgunun karşılığını doğrudan versin "
        "(arayan kişi cevabı ilk satırda görsün).")
    return "\n".join(parts) + "\n"


def ilk_harfi_buyut(title: str, language: str) -> str:
    """Başlık küçük harfle başlıyorsa ilk harfi büyüt — DİLE GÖRE.

    NEDEN KODDA: prompt kuralı YETMEDİ. Arama bloğu sorguyu "BİREBİR ve BAŞTA"
    taşımayı emrediyordu; sorgular izleyicinin yazdığı gibi küçük harfli gelir
    ve üç video "akaryakıt fiyatları zam: ..." / "altın fiyatları uçuşta: ..."
    diye YAYINLANDI (Gündem TR, 2026-08-22). Prompt düzeltildi ama tek savunma
    bırakmıyoruz — bu kusur yayına çıkınca geri alınamıyor.

    TÜRKÇE TUZAĞI: 'i'nin büyüğü 'İ'dir; str.upper() 'I' üretir ve kelimeyi
    bozar (bkz. text_normalize.turkish_upper).

    MARKA İSTİSNASI: ilk kelimede büyük harf VARSA dokunulmaz — 'iPhone',
    'eBay' gibi adlar kasıtlı küçük harfle başlar ve düzeltmek onları bozar.
    """
    t = (title or "").lstrip()
    if not t or not t[0].isalpha() or not t[0].islower():
        return title
    ilk_kelime = t.split(maxsplit=1)[0]
    if any(c.isupper() for c in ilk_kelime):
        return title
    if (language or "").split("-")[0].lower() == "tr":
        from short_bot.text_normalize import turkish_upper
        bas = turkish_upper(t[0])
    else:
        bas = t[0].upper()
    return bas + t[1:]


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
    # KAYNAK ETİKETİ KANALIN DİLİNDE. Örnek Türkçe sabit kalınca Japonca
    # açıklamaya "Kaynak: Yahoo!ニュース" diye sızdı (canlı ölçüm 2026-08-22) —
    # model KURAL metnini değil ÖRNEĞİ kopyalar, hashtag örneğiyle aynı sınıf.
    from short_bot.locale import UI_LABELS as _UI
    kaynak_etiketi = (_UI.get(channel.language) or _UI.get("en") or {}).get(
        "source", "Source")

    hook_block = ""
    if hook_patterns:
        pats = "\n".join(f"- {p}" for p in hook_patterns)
        hook_block = (f"KANITLANMIŞ BAŞLIK ÖRÜNTÜLERİ (nişte patlamış videolardan):\n"
                      f"{pats}\n"
                      f"CTR kuralları: İlk 3 kelime vurucu olsun; merak boşluğu "
                      f"bırak; mümkünse somut sayı kullan. Kanal tonunun "
                      f"yasaklarına uy.\n\n")

    # KAYNAK KARARI LİNKE BAKAR, OUTLET ADINA DEĞİL.
    #
    # Eskiden koşul `rss_source and rss_link` idi ve outlet adı boş olan her
    # haber "AI ile üretilmiş özgün içerik" ilan ediliyordu. Outlet adı Google
    # News DIŞINDAKİ feed'lerde tanım gereği boştu (bkz. fetcher._yayinci_adi),
    # yani RSS Havuzu'na elle eklenen HER kaynak bu dala düşüyordu: haber özeti
    # olan video kaynak atfı olmadan, yanlış bir özgünlük beyanıyla yayına
    # hazırlanıyordu (ölçüldü: short #1892, bernabeudigital.com). Link varsa bu
    # bir haber özetidir — outlet adının eksikliği bunu değiştirmez.
    if rss_link:
        outlet_satiri = (f"- Outlet: {rss_source}\n" if rss_source else
                         "- The feed carries no outlet name: use the link's domain "
                         "as the source.\n")
        source_block = (
            f"SOURCE:\n"
            f"{outlet_satiri}"
            f"- Original link: {rss_link}\n"
            f"- This is a news summary. The description MUST credit the source.\n"
        )
    else:
        ai_notu = _AI_NOTU.get(channel.language) or _AI_NOTU["en"]
        source_block = (
            "SOURCE:\n"
            "- This channel produces original short-form content with AI "
            "(NOT a news summary).\n"
            f"- Put this note in the description, in {lang_name}: \"{ai_notu}\"\n"
        )

    body = script.get("body_paragraph", "")
    keywords = ", ".join((channel.keywords or [])[:8])
    search_block = _search_block(script, search_terms, channel.language)
    # HASHTAG ÖRNEĞİ ÖNCE KANALIN KENDİ KELİMELERİNDEN. Sabit dil örneği
    # ("#shorts #速報 #ニュース") HABER tonlu; magazin kanalına sızıyordu.
    # Kodun kendi dersi: model ÖRNEĞİ kopyalar, kural metnini değil. Kanalın
    # anahtar kelimeleri hem dile hem dikeye tanım gereği doğru.
    _kw = [k.strip() for k in (channel.keywords or []) if k and k.strip()][:3]
    _dil_ornek = _HASHTAG_ORNEK.get(channel.language, _HASHTAG_ORNEK["en"])
    if _kw:
        _etiketler = ["#shorts"] + ["#" + k.replace(" ", "") for k in _kw]
        # DİL VARSAYILANI HABER TONLU (#eilmeldung, #速報). Dikeysiz kanal zaten
        # haber kanalı — varsayılan onu zenginleştirir, eski davranış korunur.
        # Dikey VARSA eklenmez: magazin kanalına "#速報" tam da kaçındığımız sızıntı.
        if not getattr(channel, "trends_vertical", None):
            for t in _dil_ornek.split():
                if t.lower() not in {x.lower() for x in _etiketler}:
                    _etiketler.append(t)
        hashtag_ornek = " ".join(_etiketler)
    else:
        hashtag_ornek = _dil_ornek

    # BAŞLIK ÖRNEĞİ KANALIN DİLİNDEN. Kalıbı Türkçe örneklerle ('galatasaray
    # transfer') anlatmak modele Türkçe KELİME enjekte ediyordu.
    _ornek_kw = [k.strip() for k in (channel.keywords or []) if k and k.strip()][:2]
    if _ornek_kw and channel.language != "tr":
        varlik_ornek = ", ".join(f"'{k.lower()}'" for k in _ornek_kw)
    else:
        varlik_ornek = "'galatasaray transfer', 'gs transfer son dakika'"

    # İSTEMİN GÖVDESİ İNGİLİZCE — ÖLÇÜLDÜ, TALİMAT YETMEDİ.
    #
    # Kurallar önceden baştan sona Türkçeydi ve çıktı dili tek satırla
    # ("- {lang_name} dilinde") söyleniyordu. Model bunu tutmuyordu: İspanyolca
    # latidoblanco-flash kanalında 6 üretimin 6'sı Türkçe başlıkla döndü
    # ("Real Madrid gündeminde Enzo Fernández ve Álvaro Carreras gelişmeleri").
    # Denenip ELENEN çareler — her biri 5-6 üretimle ölçüldü:
    #   • istemin başına + sonuna büyük harfli "DİL KİLİDİ" bloğu → 0/6
    #   • kilidi hedef dilde yazmak ("ESCRIBE TODO EN ESPAÑOL") → 1/6
    #   • kaynak haber başlığını "dil demiri" örneği olarak vermek → 0/6
    #   • Türkçe çıktıyı yakalayıp yeniden istemek → 2. deneme de Türkçe
    # Kural gövdesi İngilizceye çevrilince 5/5 hedef dilde geldi: talimat dili
    # nötr olunca modelin varsayılanı "istemin dilini taklit et" olmaktan çıkıp
    # açıkça istenen dile dönüyor. Kod yorumları ve kanaldan gelen veri
    # (persona, yasak listesi, arama sözlüğü) Türkçe kalır — onlar operatörün
    # ve kanalın malı, modele örnek olarak DEĞİL veri olarak gidiyor.
    return f"""You write SEO metadata for a YouTube Shorts channel.

OUTPUT LANGUAGE: {lang_name}. Write title, description and tags ONLY in
{lang_name}. Some blocks below carry channel-specific data in other languages —
that is data, not a language example.

CHANNEL:
- Name: {channel.name}
- Handle: {channel.handle}
- Language: {lang_name}
- Keywords: {keywords}

CONTENT:
- Headline top: {script.get("header_top", "")}
- Headline bottom: {script.get("header_bottom", "")}
- Body: {body}
- Category: {script.get("category", "")}
- Mood: {script.get("mood", "")}

{source_block}
{search_block}
{hook_block}{dikey_block}
TASK: produce title + description + tags following the rules below.

TITLE RULES:
- {baslik_butcesi} characters ({baslik_butcesi.split('-')[-1]} max, hard limit)
- Written in {lang_name}
- ENTITY + INTENT pattern: lead with the SUBJECT (person, organisation, club,
  product, title of a work), then what happened to it. Measured over 28 days of
  YouTube Analytics search terms: none of the top 25 queries that found the
  channel were questions — all were entity+intent, e.g. {varlik_ornek} for this
  channel. Do not open with a generic category word (the equivalent of
  "breaking news").
- The title must stand alone as a correct headline: do not drop the subject,
  and do not glue two separate fragments together with a colon. Do not start
  with a lowercase letter.
- Not clickbait — honest, reflecting the actual content.
- No manufactured excitement ("Shocking", "You won't believe").
- If there is a number or date, put it near the front.

DESCRIPTION RULES (in {lang_name}):
1. First line (~150 chars, the mobile preview): one punchy sentence that
   summarises the content
2. blank line
3. A full summary in 2-4 sentences, explaining what the story actually says
4. blank line
5. Source block — the LABEL in {lang_name}: "{kaynak_etiketi}: {{outlet}} — {{link}}"
   when a source exists, otherwise the AI-original note given above
6. blank line
7. Copyright / fair-use disclaimer in {lang_name}, 2-3 sentences, covering:
   this video is a short summary of news content; image and text quotations are
   used for information purposes under fair use; the copyright belongs to the
   respective sources; rights holders who want the content removed can contact
   the channel owner
8. blank line
9. Hashtag block: 5-10 tags on the last line, #shorts mandatory, topic-relevant
   plus the handle. Example: "{hashtag_ornek} #{channel.handle.replace('@', '')}"

TAGS RULES:
- 8-15 tags (20 max)
- may mix {lang_name} and English
- 1-3 words each, no commas inside a tag
- a generic one (the equivalent of "news") plus specific topic words
- "shorts" mandatory
{override_block}
OUTPUT: only the JSON below, no other text:
{{
  "title": "<{baslik_butcesi} char>",
  "description": "<full description with sections>",
  "tags": ["...", "..."]
}}
"""


def lang_adi(dil: str) -> str:
    return LANGUAGE_NAMES.get(dil, dil)


def _turkce_sizdi_mi(meta: "YoutubeMetadata", dil: str) -> bool:
    """Türkçe DIŞI bir kanalın metadata'sına Türkçe karışmış mı.

    Türkçe kanalda kapalı (kontrol edilecek bir şey yok). Başlık ve açıklama
    BİRLİKTE bakılır: sızıntı çoğu kez ikisinden yalnız birinde oluyor —
    ölçüldüğünde başlık tümüyle Türkçeydi ama açıklamanın gövdesi İspanyolcaydı,
    yalnız araya "Bu içerik yapay zeka ile özgün olarak üretilmiştir." düşmüştü.
    """
    if (dil or "").split("-")[0].lower() == "tr":
        return False
    return (turkce_gorunuyor_mu(meta.title)
            or turkce_gorunuyor_mu(meta.description))


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
    dil = getattr(channel, "language", "tr")
    meta = None
    for deneme in (1, 2):
        meta = run_json(
            prompt, YoutubeMetadata,
            claude_path=claude_path, model=model,
            backend=backend, api_key=api_key,
            retries=2, timeout_s=120,
        )
        if not _turkce_sizdi_mi(meta, dil):
            break
        # DİL KİLİDİ TALİMATI TEK BAŞINA YETMİYOR. İstem baştan sona Türkçe
        # (operatör Türkçe okuyor) ve model dili ara sıra karıştırıyor: aynı
        # short için arka arkaya iki üretimde biri İspanyolca, öteki "Real
        # Madrid transfer planları ve Bernabéu'da yaşanan son gelişmeler"
        # çıktı. Talimatı tekrarlamak yerine ÇIKTIYI DENETLİYORUZ.
        #
        # İkinci deneme de sızdırırsa elde olan döndürülür: bu bir KAPI değil
        # — metadata üretimini büsbütün patlatmak, kusurlu bir başlıktan daha
        # kötü (çağıran o zaman LLM'siz `build_snippet` yedeğine düşer).
        log.warning("youtube metadata: çıktıya Türkçe sızdı (%s kanalı %s dilinde) "
                    "— %d. deneme", getattr(channel, "handle", "?"), dil, deneme + 1)
        prompt += (
            f"\n\nÖNCEKİ DENEMEN REDDEDİLDİ: çıktıda Türkçe kelimeler vardı "
            f"(başlık: {meta.title!r}). İstemin kuralları Türkçe yazılmıştır ama "
            f"ÇIKTI {lang_adi(dil)} olmak zorundadır. Yeniden yaz; tek bir Türkçe "
            f"kelime bırakma.")
    duzeltilmis = ilk_harfi_buyut(meta.title, dil)
    if duzeltilmis != meta.title:
        return meta.model_copy(update={"title": duzeltilmis})
    return meta
