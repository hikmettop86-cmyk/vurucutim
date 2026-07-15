"""Reel anlatım personası: few-shot örneği + ton kuralları.

Persona metni DİL PAKETİNDEN gelir (Türk dizisi referansları yalnız tr'de). Bilinmeyen
slug ya da yanlış dil RuntimeError verir — sessizce kişiliksiz'e / yanlış dile düşmek
YASAK: kullanıcı mizah seçtiyse mizah almalı, seçmediyse bugünkü davranışı almalı.
"""
from __future__ import annotations

from pydantic import BaseModel

from short_bot.lang_pack import load_pack


class Persona(BaseModel):
    slug: str
    few_shot: str
    rules: list[str]
    humor_check: bool = True


def load_persona(slug: str, *, language: str) -> Persona | None:
    if not (slug or "").strip():
        return None                      # kişiliksiz: bugünkü prompt, sıfır regresyon
    pack = load_pack(language)
    data = (pack.personas or {}).get(slug)
    if not data:
        raise RuntimeError(
            f"persona '{slug}' {language} dil paketinde yok — "
            f"bu persona bu dilde tanımlı değil (sessiz düşme yok)")
    return Persona(slug=slug, few_shot=data.get("few_shot", ""),
                   rules=list(data.get("rules", [])),
                   humor_check=bool(data.get("humor_check", True)))


def mascot_block(name: str, animal: str, trait: str) -> str:
    """Senaryo prompt'una eklenecek MASKOT (tekrar eden ana karakter) bloğu.

    Üçü de doluysa maskot aktif; biri boşsa "" (maskot yok, her video bağımsız).
    Maskot persona'dan AYRI: persona TON (mahalle ağzı), maskot KARAKTER (Deli Kâzım).
    """
    if not all((name or "").strip() and (x or "").strip() for x in (name, animal, trait)):
        return ""
    return (
        f"=== ANA KARAKTER (MASKOT — KANALIN YÜZÜ) ===\n"
        f"Bu kanalın SABİT baş karakteri: {name} ({animal}). Kişilik: {trait}.\n"
        f"Her videoda AYNI isim, AYNI kişilik — izleyici {name}'ı tanısın ve ona "
        f"bağlansın (bir videoya değil, KARAKTERE abone olsun).\n"
        f"KONU {animal.upper()} İLE İLGİLİYSE: {name}'ı doğrudan merkeze al, onun bir "
        f"macerası/özelliği gibi anlat.\n"
        f"KONU BAŞKA BİR HAYVANSA: {name} onu kendi mahalle-abisi gözünden YORUMLAR/"
        f"KIYASLAR — o hayvanın yanına gitmez (coğrafi tutarlılık). Örnek: 'bu penguen "
        f"çakıl çalıyormuş; bizim {name} görse taşı da alırdı sahibini de'.\n"
        f"Manşet ve ozan imzası {name}'ın ismini taşıyabilir ('Aşık {name} der ki...').\n")


def topic_guidance(persona: Persona | None) -> str:
    """Konu üretimine verilecek niş-üstü yönerge (propose_topics.extra_guidance).

    Mizah kanalı için konu SEÇİMİ mizahı hedeflemeli: DiscoverNow'un en çok tutan
    videoları hep KARAKTERLİ/KABADAYI hayvanlar (bal porsuğu, kangal, leopar). Konu
    üretimi persona-agnostik olduğu için hüzünlü/nötr davranışlar da geliyordu
    (fil hafızası, göç). Bu yönerge üretimi karakterli davranışlara çeker.
    """
    if persona is None or persona.slug != "vahsi_mizah":
        return ""
    return (
        "MİZAH KANALI — KONU SEÇİMİ ÖNEMLİ: Bu kanal hayvanları bir MAHALLE "
        "KARAKTERİNE büründürüp komik anlatıyor. O yüzden KARAKTERLİ, KABADAYI, "
        "TUHAF, KURNAZ ya da KOMİK davranışlı hayvan/olayları TERCİH ET — korkusuzluk, "
        "kavga, blöf, kıskançlık, kurnazlık, hiyerarşi, tuhaf çiftleşme/yavru bakımı "
        "gibi 'mahalle tipi' davranışlar. Örnek uygun: bal porsuğunun cesareti, "
        "ahtapotun komşusuna çamur fırlatması, capuchin'in adalet duygusu, sincabın "
        "sahte çukur kazması, kanganın boks yapması. KAÇIN: hüzünlü/nötr/duygusal "
        "olgular (fil hafızası, göç mesafeleri, nesli tükenme) — bunlar komik "
        "anlatıma DİRENÇLİDİR. Her konu, hayvanın bir 'karakterini' ortaya koymalı.")


def director_guidance(persona: Persona | None) -> str:
    """Kurgucuya (reel_director) verilecek yönerge. Mizah videosu EĞLENCELİ
    kurgulanmalı — kurgucu persona-agnostik olduğu için mizah anlatımına 'dark/tense'
    mood + gerilim müziği seçebiliyordu (ölçüldü: short 813, mood=dark/glitch/tense).
    """
    if persona is None or persona.slug != "vahsi_mizah":
        return ""
    return (
        "BU BİR MİZAH VİDEOSU (hayvan mahalle karakterine bürünmüş, komik anlatım). "
        "Kurgu EĞLENCELİ ve TEMPOLU olmalı: mood 'upbeat' seç (mizahta 'dark'/'tense' "
        "YANLIŞTIR — ciddi/gerilim tonu komediyi öldürür). Müzik neşeli/enerjik olsun. "
        "SFX'ler canlı ve vurucu — komik anları (blöf, kavga, twist) 'impact'/canlı "
        "kategoriyle noktala. Amaç: izleyici gülümserken izlesin, gerilmesin.")


def channel_director_guidance(persona_slug: str, language: str) -> str:
    """Kanal persona slug'ından kurgu rehberi (güvenli sarmalayıcı, bkz. topic sürümü)."""
    if not (persona_slug or "").strip():
        return ""
    try:
        p = load_persona(persona_slug, language=language)
    except RuntimeError:
        return ""
    return director_guidance(p)


def channel_topic_guidance(persona_slug: str, language: str) -> str:
    """Kanal persona slug'ından konu üretim rehberi. Güvenli sarmalayıcı:
    boş slug ya da yanlış dil → "" (konu üretimi bozulmaz, sadece mizah-agnostik olur).
    refresh_topic_bank'in tüm çağıranları bunu ``extra_guidance`` olarak geçirir."""
    if not (persona_slug or "").strip():
        return ""
    try:
        p = load_persona(persona_slug, language=language)
    except RuntimeError:
        return ""
    return topic_guidance(p)


def persona_block(persona: Persona) -> str:
    kurallar = "\n".join(f"{i+1}. {r}" for i, r in enumerate(persona.rules))
    return (
        "=== ANLATIM PERSONASI (TON — EN ÖNEMLİ KATMAN) ===\n"
        "Bu videoyu aşağıdaki KOMİK personada yaz. İçerik yapısı (hook→tırmanış→tepe→"
        "callback) AYNI kalır; DEĞİŞEN şey TONDUR. Sıkıcı belgesel anlatıcısı DEĞİL —\n"
        "izleyiciyle mahallede çay içer gibi, racon keserek, kahkaha attırarak konuş.\n"
        "Bilgi GERÇEK, anlatım MAHALLE AĞZI.\n\n"
        f"TARZIN TAM ÖRNEĞİ (aynen bunun tadında yaz):\n---\n{persona.few_shot}\n---\n\n"
        f"KURALLAR (hepsi ZORUNLU):\n{kurallar}\n\n"
        "MİZAH SIKIŞTIRILAMAZ: kelimeleri kısıp esprisiz özet çıkarma. Nefes alanı "
        "olan, kurulup boşalan şakalar yaz. Her beat bir sahne/espri taşısın.\n\n"
        "ÇIKTI DİSİPLİNİ (JSON BOZULMASIN): Senaryo metinlerinde (hook, beat, close, "
        "comment) ASLA çift tırnak (\") kullanma — diyalog/alıntı için TEK tırnak (') "
        "kullan. Örnek: karga 'kırmızı tişörtlü cimrinin teki geçti' der. Yanıt "
        "SADECE geçerli JSON olsun, markdown kod bloğu ekleme.\n\n"
        "KAPANIŞ (close) EN FAZLA 120 KARAKTER: ozan imzasını buna göre KISA yaz "
        "(2 mısra). Uzarsa üretim düşer. Yorum sorusunu close'a KOYMA — 'comment' "
        "alanına yaz.\n")
