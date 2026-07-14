"""Kanal kurma ajanı: bir cümleden çalışan bir kanala.

Ajan bir ORKESTRATÖRDÜR — niş bulucu, dil paketi, DNA ve konu bankası zaten var.
Tek gerçek yeni parça ses seçimi (voice_picker).

İKİ AŞAMA, ve ayrım KASITLI:
    build_plan  → HİÇBİR ŞEY YAZMAZ. Kullanıcı planı görür.
    apply_plan  → YAML'ı yazar, CSS yazar, konu bankasını tohumlar.

Neden: ajan yanlış ses seçer, ismi tutmaz ya da niş kaymışsa, kullanıcı bunu KANAL
KURULMADAN görmeli. Kurulmuş bir kanalı geri almak (YAML sil, banka temizle, CSS sil)
kullanıcının işi olmamalı.

DİL PAKETİ İSTİSNA: o dile aittir, kanala değil. build_plan onu üretir (yoksa), çünkü
paket olmadan planın "3 örnek konu"su bile hedef dilde doğrulanamaz — ve paket bir kez
üretilip o dildeki HER kanalda kullanılır.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel

from short_bot.dna import DnaSpec, generate_dna
from short_bot.lang_pack import load_pack
from short_bot.locale import LANGUAGE_NAMES, SUPPORTED_LANGUAGES
from short_bot.topic_miner import refresh_topic_bank
from short_bot.topic_propose import propose_topics, verify_topics
from short_bot.voice_picker import VoiceChoice, pick_voice, voices_for

log = logging.getLogger(__name__)

SAMPLE_TOPIC_COUNT = 3
DEFAULT_HIGHLIGHT = "#38bdf8"

# unicodedata tek başına 'ı'yı ve 'ß'yi düşürüyor — elle eşliyoruz.
_SLUG_MAP = str.maketrans({"ı": "i", "İ": "I", "ş": "s", "Ş": "S", "ğ": "g",
                           "Ğ": "G", "ç": "c", "Ç": "C", "ö": "o", "Ö": "O",
                           "ü": "u", "Ü": "U", "ä": "a", "Ä": "A"})


class ChannelPlan(BaseModel):
    language: str
    niche: str                    # TEMİZLENMİŞ niş — generator.topic olacak
    intent: str = ""              # kullanıcının HAM cümlesi (planda gösterilir)
    evidence: str = ""            # YouTube ölçümü YOKSA BOŞ — uydurma kanıt yazmayız
    # DİL ÇELİŞKİSİ: metin başka bir dil istiyor gibi görünüyor ama menü bunu diyor.
    # Menü hüküm verir (açık kullanıcı girdisi); panel çelişkiyi UYARI olarak gösterir.
    lang_conflict: str = ""       # kullanıcının metinde istediği dil kodu (varsa)
    name: str
    slug: str
    voice: VoiceChoice
    dna: DnaSpec
    highlight_color: str = DEFAULT_HIGHLIGHT
    sample_topics: list[str] = []


class _Name(BaseModel):
    name: str


class _Niche(BaseModel):
    niche: str
    wants_language: str = ""     # kullanıcının YAYIN DİLİ olarak istediği dil kodu


def _normalize_niche(intent: str, language: str, llm) -> tuple[str, str]:
    """Kullanıcının İSTEĞİNİ temiz bir NİŞE çevir. ``(niş, istenen_dil_kodu)`` döner.

    NEDEN NİŞ TEMİZLİĞİ (gerçek hata, ilk canlı koşu): kullanıcı "Almanca bahçe ile
    ilgilenen insanların bahçecilik üzerine merak uyandıran niş bir short kanal kurmak
    istiyorum" yazdı ve bu cümle olduğu gibi ``generator.topic``e kaydedilecekti. YouTube
    arama sorgusu bundan türetiliyor (``_short_query`` ilk kelimeleri alıyor) →
    "Almanca bahce ile" → hiçbir şey bulmaz → o kanalda kanıt madenciliği KALICI OLARAK
    ÖLÜ. İnsan doğal olarak İSTEĞİNİ yazar, nişini değil.

    NEDEN DİL TESPİTİ (ölçüldü): metinde "Almanca" yazıp açılır menüyü Türkçe bırakmak
    kolay. O hâlde ses Türkçe seçilir, dil paketi Türkçe olur, konular Türkçe üretilir —
    ama kullanıcı Almanca kanal istemiştir. Ortaya TUTARSIZ bir kanal çıkar.

    AMA OTOMATİK DÜZELTMEK YANLIŞ OLUR: "Alman tarihi hakkında TÜRKÇE kanal" da geçerli
    bir istek; orada "Alman" kelimesi KONUYU anlatıyor, dili değil. Bu yüzden menü hüküm
    verir, biz yalnız ÇELİŞKİYİ BİLDİRİRİZ (çağıran uyarır).

    Niş HEDEF DİLDE yazılır (menüdeki dil): kanal o dilde yayın yapar ve arama sorguları
    nişten türetilir.
    """
    intent = (intent or "").strip()
    if llm is None:
        return intent, ""
    ad = LANGUAGE_NAMES.get(language, language)
    try:
        v = llm(f"""Kullanıcı bir YouTube Shorts kanalı kurmak istiyor. İSTEĞİNİ temiz
bir NİŞ cümlesine çevir.

KULLANICININ YAZDIĞI:
{intent}

KANALIN SEÇİLİ YAYIN DİLİ: {ad} ({language})

1) "niche" — konu cümlesi:
- {ad} DİLİNDE yaz. Metinde BAŞKA bir dil geçse bile ÇIKTI {ad} olacak; yayın dili
  budur ve YouTube arama sorguları bu cümleden türetilecek.
- Bu bir KONU tarifi, bir İSTEK değil. "kanal kurmak istiyorum", "bana bul", "olsun"
  gibi ifadeler ÇIKMALI.
- İçeriğin NE HAKKINDA olduğunu söyle: hangi alan, hangi tür olgular.
- 1 cümle, en fazla 120 karakter. Somut ol.
    ✗ "Almanca bahçe ile ilgilenen insanların bahçecilik üzerine kanal kurmak istiyorum"
    ✓ "Überraschende Fakten über Gartenpflanzen, Anbau, Boden und Pflanzenbiologie"

2) "wants_language" — kullanıcı hangi dilde YAYIN yapmak istiyor?
- Metinden anlaşılıyorsa dil KODUNU yaz: tr, en, de, es, fr.
- DİKKAT — konu ile dili KARIŞTIRMA:
    "Almanca bahçecilik kanalı"        → wants_language = "de"  (yayın dili Almanca)
    "Alman tarihi hakkında kanal"      → wants_language = ""    (KONU Almanya, dil belli değil)
    "İspanyol mutfağını anlatan kanal" → wants_language = ""    (KONU İspanya)
- Metin dil hakkında bir şey söylemiyorsa BOŞ bırak.

SADECE JSON: {{"niche": "<{ad} tek cümle>", "wants_language": "<kod ya da boş>"}}""",
                _Niche)
        temiz = (v.niche or "").strip()[:200]
        istenen = (v.wants_language or "").strip().lower()
        if istenen not in SUPPORTED_LANGUAGES:
            istenen = ""
        if len(temiz) >= 10:
            log.info(f"[ajan] niş temizlendi: {intent[:50]!r} → {temiz!r}"
                     + (f" | istenen dil: {istenen}" if istenen else ""))
            return temiz, istenen
    except Exception as e:   # noqa: BLE001 — temizleme kanalı bozmaz
        log.warning(f"[ajan] niş temizlenemedi ({e}) → ham metin kullanılıyor")
    return intent, ""


def _slugify(name: str) -> str:
    name = name.replace("ß", "ss").translate(_SLUG_MAP)
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return name or "channel"


def _unique_slug(base: str, channels_dir) -> str:
    slug, n = base, 2
    while (Path(channels_dir) / f"{slug}.yaml").exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _pick_name(niche: str, language: str, llm) -> str:
    """Hedef dilde kısa, akılda kalır bir kanal adı. Ad kanalı bozmaz → patlarsa türet."""
    yedek = (niche.split()[0][:24].title() if niche.split() else "Kanal")
    if llm is None:
        return yedek
    ad = LANGUAGE_NAMES.get(language, language)
    try:
        v = llm(f"""Bir YouTube Shorts kanalına AD ver.

NİŞ: {niche}
DİL: {ad}

KURALLAR:
- Ad {ad} dilinde olmalı (izleyici o dili konuşuyor).
- KISA: 1-3 kelime, en fazla 24 karakter.
- Akılda kalır, telaffuz edilebilir, nişi çağrıştırsın.
- "Shorts", "Channel", "Kanal" gibi jenerik kelimeler KULLANMA.

SADECE JSON: {{"name": "<ad>"}}""", _Name)
        return (v.name or "").strip()[:40] or yedek
    except Exception as e:   # noqa: BLE001 — isim kanalı bozmaz
        log.warning(f"[ajan] isim üretilemedi ({e}) → nişten türetiliyor")
        return yedek


def _ensure_lang_pack(language: str, *, settings, secrets) -> None:
    """Dil paketi yoksa ÜRET. Paket olmadan hedef dilde hiçbir şey doğru çalışmaz:
    ekrana Türkçe abone çipi basılır, rozet Türkçe noktalı İ ile yazılır ve klişe
    denetçisi hiçbir şey yakalamaz — üçü de SESSİZCE."""
    try:
        load_pack(language)
        return
    except RuntimeError:
        pass

    from short_bot.lang_pack import pack_path
    from short_bot.lang_pack_gen import generate_pack

    ad = LANGUAGE_NAMES.get(language, language)
    log.info(f"[ajan] {ad} dil paketi yok → üretiliyor (Sonnet 5, birkaç dakika)")
    pack = generate_pack(
        language,
        claude_path=getattr(settings, "claude_cli_path", "claude"),
        openrouter_model=getattr(settings, "openrouter_models", {}).get(
            "script", "anthropic/claude-sonnet-5"),
        openrouter_key=(secrets or {}).get("openrouter_api_key"))
    hedef = pack_path(language, user=True)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(pack.model_dump_json(indent=2) + "\n", encoding="utf-8")
    load_pack.cache_clear()
    log.info(f"[ajan] {ad} dil paketi üretildi → {hedef}")


def _sample_topics(niche: str, language: str, llm) -> list[str]:
    """3 GERÇEK konu: propose + doğrulama kapısı.

    Patlarsa boş liste — plan YİNE kurulur, banka kurulumdan sonra dolar.
    """
    try:
        onerilen = propose_topics(niche, language=language, evidence=[], existing=[],
                                  count=SAMPLE_TOPIC_COUNT, llm=llm)
        yargilar = verify_topics([t.topic for t in onerilen], language=language,
                                 llm=llm)
        return [t.topic for t, y in zip(onerilen, yargilar) if y.solid]
    except Exception as e:   # noqa: BLE001 — örnek konu kanalı bozmaz
        log.warning(f"[ajan] örnek konu üretilemedi ({e}) → plan konusuz sunuluyor")
        return []


# Planın adımları. Panelde ilerleme olarak gösterilir.
#
# NEDEN GEREKLİ (ölçüldü): plan BEŞ ayrı LLM çağrısı yapıyor ve Claude CLI her
# çağrıda yeni bir süreç açıyor. Gerçek koşu ~6-8 DAKİKA sürüyor. Panel "hazırlanıyor…"
# deyip susunca kullanıcı haklı olarak "takıldı mı?" diye soruyor — ve cevabı
# bilmenin tek yolu log'a bakmak oluyordu. Görünmeyen bir iş, takılmış bir iştir.
PLAN_STEPS = ("Dil paketi", "Niş", "Ses", "Kanal adı", "Kimlik", "Örnek konular")


def build_plan(niche: str, *, language: str, channels_dir, ai33_key: str,
               settings, secrets: dict, llm=None, dna_call=None,
               evidence: str = "", on_step=None) -> ChannelPlan:
    """Kanal planı kur. HİÇBİR DOSYA YAZMAZ (dil paketi hariç — modül docstring'i).

    ``niche``: kullanıcının HAM cümlesi olabilir ("… kanal kurmak istiyorum"). Önce
    temiz bir nişe çevrilir (bkz. _normalize_niche) — aksi hâlde YouTube arama sorgusu
    çöp olur ve o kanalda kanıt madenciliği kalıcı olarak ölür.

    ``evidence``: niş bulucunun YouTube ölçümü. YOKSA BOŞ KALIR — uydurma kanıt yazmayız.
    ``on_step``: ``(index, ad) -> None`` — panel ilerlemeyi göstersin diye.
    """
    intent = (niche or "").strip()
    if len(intent) < 10:
        raise ValueError("niş en az 10 karakter olmalı — ne hakkında kanal "
                         "istediğini yaz")

    def _adim(i: int) -> None:
        log.info(f"[ajan] adım {i + 1}/{len(PLAN_STEPS)}: {PLAN_STEPS[i]}")
        if on_step is not None:
            try:
                on_step(i, PLAN_STEPS[i])
            except Exception:   # noqa: BLE001 — ilerleme bildirimi planı bozmasın
                pass

    # 1) DİL PAKETİ — olmadan hedef dilde hiçbir şey doğru çalışmaz.
    _adim(0)
    _ensure_lang_pack(language, settings=settings, secrets=secrets)

    # 2) NİŞ TEMİZLİĞİ — insan İSTEĞİNİ yazar, nişini değil.
    #    Ayrıca: metin başka bir yayın dili istiyor mu? (menü hüküm verir, biz uyarırız)
    _adim(1)
    niche, istenen_dil = _normalize_niche(intent, language, llm)
    cakisma = istenen_dil if (istenen_dil and istenen_dil != language) else ""
    if cakisma:
        log.warning(f"[ajan] DİL ÇELİŞKİSİ: metin '{cakisma}' istiyor ama menü "
                    f"'{language}'. Menü hüküm veriyor — panel uyaracak.")

    # 3) SES — hedef dilde ses YOKSA burada dururuz (İngilizceye DÜŞMEYİZ).
    _adim(2)
    voices = voices_for(language, api_key=ai33_key)
    voice = pick_voice(language, niche, voices=voices, llm=llm)

    # 4) İSİM + SLUG
    _adim(3)
    name = _pick_name(niche, language, llm)
    slug = _unique_slug(_slugify(name), channels_dir)

    # 5) KİMLİK (DNA) — kimlik olmadan kanal kurulmaz.
    _adim(4)
    if dna_call is None:
        from short_bot.config import resolve_ai_call
        dna_call = resolve_ai_call(settings, secrets or {}, "dna")
    dna = generate_dna(name=name, keywords=[], language=language,
                       topic_hint=niche, target_audience="",
                       claude_path=dna_call.claude_path, model=dna_call.model,
                       backend=dna_call.backend, api_key=dna_call.api_key)

    # 6) ÖRNEK KONULAR — gerçekten üretilir ve doğrulama kapısından geçer.
    _adim(5)
    ornek = _sample_topics(niche, language, llm)

    return ChannelPlan(language=language, niche=niche, intent=intent,
                       evidence=evidence, lang_conflict=cakisma,
                       name=name, slug=slug, voice=voice, dna=dna,
                       sample_topics=ornek)


def apply_plan(plan: ChannelPlan, *, channels_dir, templates_dir, db_path,
               settings, secrets: dict, llm=None) -> str:
    """Planı gerçeğe çevir: YAML + CSS + konu bankası tohumu. Slug döner.

    AUTOPILOT AÇILMAZ ve SERİ KAPALI kurulur: YouTube'a otomatik yükleme büyük bir
    taahhüt, kullanıcı bilinçli açar.

    Konu bankası tohumlaması PATLASA DA kanal kurulmuş sayılır — YAML yazıldıysa kanal
    VARDIR ve banka 4 saatte bir kendini doldurur (topic_autofill).
    """
    from short_bot.config import (ChannelConfig, GeneratorConfig, ReelConfig,
                                  save_channel)
    from short_bot.db import init_db
    from short_bot.dna import build_css_override
    from short_bot.locale import RSS_LOCALES

    channels_dir = Path(channels_dir)
    channels_dir.mkdir(parents=True, exist_ok=True)

    reel = ReelConfig(
        enabled=True,
        voice_id=plan.voice.voice_id,
        highlight_color=plan.highlight_color,
        cta_enabled=True,
        comment_question=True,
        series_enabled=False,      # kullanıcı açar
    )

    cfg = ChannelConfig(
        slug=plan.slug, name=plan.name, keywords=[],
        rss_locale=RSS_LOCALES[plan.language],
        schedule_cron="0 10 * * *",
        duration_s=40, min_score=7.0, max_candidates_per_run=3,
        template=plan.dna.archetype,
        colors={"primary": plan.dna.palette.primary,
                "accent": plan.highlight_color,
                "bg_gradient": plan.dna.palette.bg_gradient},
        handle=f"@{plan.slug}", output_dir=f"output/{plan.slug}",
        enabled=True,
        cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language=plan.language, dna=plan.dna, script_model=None,
        content_source="generator",
        generator=GeneratorConfig(topic=plan.niche),
        reel=reel,
        # autopilot AÇILMAZ — kullanıcı bilinçli açar.
    )
    save_channel(channels_dir / f"{plan.slug}.yaml", cfg)

    css = Path(templates_dir) / "css" / f"{plan.slug}.css"
    css.parent.mkdir(parents=True, exist_ok=True)
    css.write_text(build_css_override(plan.dna), encoding="utf-8")

    # KONU BANKASI TOHUMU — patlasa da kanal kurulmuş sayılır.
    try:
        from short_bot.yt_outliers import resolve_youtube_api_keys
        eng = init_db(db_path)
        res = refresh_topic_bank(eng, plan.slug, plan.niche, language=plan.language,
                                 api_keys=resolve_youtube_api_keys(secrets or {}),
                                 llm=llm)
        log.info(f"[ajan] {plan.slug}: banka tohumlandı (+{res['added']} konu)")
    except Exception as e:   # noqa: BLE001 — kanal VAR; banka 4 saatte bir dolar
        log.warning(f"[ajan] {plan.slug}: banka tohumlanamadı ({e}) — kanal yine "
                    f"kuruldu, otomatik doldurma birkaç saat içinde deneyecek")

    log.info(f"[ajan] kanal kuruldu: {plan.slug} ({plan.language})")
    return plan.slug
