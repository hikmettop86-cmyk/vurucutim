"""Kanal sohbeti — karar veren, soru sormayan.

ÜSLUP KURALI (tasarımın çekirdeği):
    "Tonu ne olsun? Sesi ne olsun? YouTube ne olsun?" diye soran bir sohbet,
    94 alanlık formu 94 soruya çevirmekten başka bir şey değildir — ve
    kullanıcıyı ne diyeceğini bilmek zorunda bırakır.

    Bunun yerine Claude KARARI VERİR, NEDEN öyle yaptığını yazar, kullanıcı
    yalnız beğenmediği satıra dokunur. Kullanıcı hiçbir şey yazmadan
    "Kanalı kur"a basabilmelidir; ilk cümlesi zaten yeterli bilgiyi taşıyordu.

GEÇMİŞ PROMPT'A GÖMÜLÜR, CLI oturumuna bağlanılmaz. Claude CLI `-p` ile tek
atış çağrılıyor (`--tools ""`, oturumsuz) ve patlarsa OpenRouter'daki aynı
modele düşüyor; orada oturum diye bir şey yok. Oturuma bağlanmak düşme yolunda
sohbeti bozardı.

HİÇBİR ŞEY YAZILMAZ: `uygula` yeni bir ChannelConfig DÖNDÜRÜR, diske yazmaz.
Kaydetme kararı çağıranın (ve kullanıcının onayının) işidir. Bu, mevcut kanal
kurma ajanının `build_plan`/`apply_plan` ayrımıyla aynı desendir.

YAZILABİLİR ALANLAR BEYAZ LİSTE. `slug` dosya yollarını, `language` dil
paketini/DNA'yı/konu bankasını, `output_dir` üretim çıktısını belirliyor;
LLM'in bunlara dokunması kanalı sessizce bozar.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any, Callable, Sequence

from pydantic import BaseModel

# LLM'in değiştirebileceği alanlar. Nokta içerenler iç içe blok alanıdır.
# Buraya alan eklemek bilinçli bir karardır — varsayılan YASAK.
YAZILABILIR: frozenset[str] = frozenset({
    # kimlik ve tempo
    "name", "handle", "schedule_cron", "enabled", "archived",
    "min_score", "max_age_hours", "max_candidates_per_run", "keywords",
    "negative_keywords", "duration_s",
    # trends
    "trends_region", "trends_min_volume", "trends_intent",
    # saga / kategori
    "saga_penalty_per_repeat", "saga_window_days", "category_quota_per_day",
    # yayın
    "youtube.auto_upload", "youtube.privacy_status", "youtube.category_id",
    "youtube.min_score_for_upload", "youtube.ai_content",
    "youtube.credentials_from",
    # ses
    "voice.enabled", "voice.speed", "voice.persona", "voice.music_volume",
    "voice.target_duration_s", "voice.voice_id",
    # görsel kimlik
    "dna.sentence_max_words", "dna.body_max_chars",
    "dna.size_headline_top", "dna.size_headline_bot",
    # kürate montaj
    "reel.cut_pacing", "reel.layout", "reel.font", "reel.music_volume",
    "reel.speed", "reel.target_duration_s", "reel.series_enabled",
    "reel.series_title", "reel.highlight_color", "reel.verify_footage",
})


class YasakAlan(ValueError):
    """LLM beyaz listede olmayan bir alanı yazmaya çalıştı."""


class Karar(BaseModel):
    """Claude'un verdiği tek bir karar — ve NEDEN verdiği.

    `dikkat=True` olanlar panelde sarı satır olur: karar yine verilmiştir ama
    kullanıcının bilmesi şarttır (fatura etkisi, ayrı YouTube kanalı gibi).
    """
    alan: str
    deger: Any
    ozet: str
    gerekce: str
    dikkat: bool = False
    alternatif_etiket: str = ""


class SohbetCevabi(BaseModel):
    """Bir sohbet turunun çıktısı.

    HER ALAN PANELDE KULLANILIR. `kurmaya_hazir: bool` alanı spec'te vardı ama
    hiçbir yerde okunmuyordu: "Kanalı kur" düğmesi kurma sohbetinde zaten hep
    görünür, kapı yok. Okunmayan alan bedava değildir — her prompt'ta şemayla
    birlikte modele gider ve her cevapta doldurulur.
    """
    mesaj: str
    kararlar: list[Karar] = []
    # Composer'ın üstündeki tıklanabilir öneriler — boş kutuya bakıp donmayı
    # önler ("ne diyeceğimi bilemem").
    oneriler: list[str] = []


# --- alan okuma / yazma ----------------------------------------------------

def _dogrula(alan: str) -> None:
    if alan not in YAZILABILIR:
        raise YasakAlan(
            f"'{alan}' değiştirilemez. Yazılabilir alanlar sabit bir listede "
            f"(channel_chat.YAZILABILIR); slug/dil/çıktı dizini gibi alanlar "
            f"kanalı bozacağı için dışarıda.")


def oku(cfg, alan: str):
    """Nokta yollu alan okuma. Blok yoksa None."""
    if "." not in alan:
        return getattr(cfg, alan, None)
    blok_adi, ic = alan.split(".", 1)
    blok = getattr(cfg, blok_adi, None)
    return None if blok is None else getattr(blok, ic, None)


def uygula(kararlar: Sequence[Karar], cfg):
    """Kararları uygulanmış YENİ bir ChannelConfig döndürür — diske YAZMAZ.

    Fark gösterilip onaylanmadan hiçbir şey kalıcı olmamalı.
    """
    duz: dict[str, Any] = {}
    bloklar: dict[str, dict[str, Any]] = {}

    for k in kararlar:
        _dogrula(k.alan)
        if "." in k.alan:
            blok_adi, ic = k.alan.split(".", 1)
            bloklar.setdefault(blok_adi, {})[ic] = k.deger
        else:
            duz[k.alan] = k.deger

    for blok_adi, degisiklik in bloklar.items():
        mevcut = getattr(cfg, blok_adi, None)
        if mevcut is None:
            raise YasakAlan(
                f"'{blok_adi}' bloğu bu kanalda yok; sohbet var olmayan bir "
                f"bloğa yazamaz (format değiştirmek ayrı bir iş).")
        duz[blok_adi] = mevcut.model_copy(update=degisiklik)

    return dataclasses.replace(cfg, **duz)


def fark(kararlar: Sequence[Karar], cfg) -> list[tuple[str, Any, Any]]:
    """Panelde gösterilecek (alan, eski, yeni) listesi.

    Değişmeyen alan LİSTELENMEZ: "22 → 22" satırı kullanıcıya bir şey
    söylemez, sadece onay ekranını gürültüyle doldurur.
    """
    out: list[tuple[str, Any, Any]] = []
    for k in kararlar:
        _dogrula(k.alan)
        eski = oku(cfg, k.alan)
        if eski != k.deger:
            out.append((k.alan, eski, k.deger))
    return out


# --- prompt ----------------------------------------------------------------

_USLUP = """Sen bir YouTube Shorts otomasyon panelinin kanal asistanısın.

EN ÖNEMLİ KURAL — SORU SORMA, KARAR VER:
Kullanıcıya "ne olsun?" diye sorma. Elindeki bilgiyle en iyi kararı ver, her
karar için GEREKÇE yaz, kullanıcı beğenmezse değiştirsin. Kullanıcı hiçbir şey
yazmadan devam edebilmeli. Bilgi eksikse en makul varsayımı yap ve varsayım
olduğunu gerekçede söyle.

Bilinmesi ŞART olan bir sonuç varsa (fatura artışı, ayrı YouTube kanalı,
otomatik yüklemenin açılması gibi) o kararda dikkat=true koy — kararı yine
sen ver, ama gözden kaçmasın.

TEK İSTİSNA — YENİ KANAL KURULUMUNDA `enabled` ve `youtube.auto_upload`
KAPALI KALIR. Kullanıcı önce birkaç video üretip sonucu görsün; ayarları
oturmamış bir kanalı doğrudan zamanlanmış üretime ya da yayına sokmak
geri alınması pahalı tek karardır. Bunları açmayı ÖNER (`oneriler`), açma.

`mesaj`: kullanıcıya söylediğin bir-iki cümle — ne yaptığını ve sırada ne
olduğunu anlat ("Beşiktaş kart kanalını kurdum, günde 3 video çıkar. İstersen
tonu sertleştiririz."). ASLA BOŞ BIRAKMA: karar üretmediğin turda bile yaz,
yoksa panelde sohbet sessiz kalır.

`kararlar`: verdiğin ayar değişiklikleri. Her karar için:
- alan   : aşağıdaki YAZILABİLİR listesinden bir ad (başkasını YAZMA)
- deger  : yeni değer
- ozet   : tek satır, kullanıcının diliyle ("Bölge Avusturya (AT)")
- gerekce: NEDEN böyle seçtiğin, ölçü ya da sonuçla ("Bölge ve dil bağımsız
           alanlar; Avusturya gündemini Almanca anlatır")

`oneriler`: 3-4 tane, kullanıcının bir sonraki adımda söyleyebileceği kısa
cümleler ("günde 3 olsun", "daha sert bir ton"). Bunlar tıklanabilir çip
olacak; "ne diyeceğimi bilemem" durumunun çaresi.

Türkçe yaz."""


def yazilabilir_alanlar(cfg) -> list[str]:
    """Bu kanalda GERÇEKTEN yazılabilecek alanlar.

    Olmayan bloğun alanını listelemek modele imkânsız karar verdiriyor ve
    bedeli ağır: `uygula` ilk imkânsız kararda patlıyor ve BÜTÜN PARTİYİ
    reddediyor. Canlı koşuda (2026-08-21) kart kanalı için model 15 karar
    verdi, biri `voice.enabled`di, hiçbiri uygulanmadı — kullanıcı
    "İşaretlileri uygula"ya bastı, hiçbir şey olmadı, sonra "Kanalı kur"
    "adı yok" dedi.

    Kart formatında ses/montaj bloğu YOK (format tanımı gereği), DNA da
    kurulumda henüz üretilmedi.
    """
    return [alan for alan in sorted(YAZILABILIR)
            if "." not in alan
            or getattr(cfg, alan.split(".", 1)[0], None) is not None]


def prompt_kur(*, cfg, gecmis: Sequence[tuple[str, str]], girdi: str,
               bulgular: Sequence[Any] = (), fmt: str | None = None) -> str:
    """Sohbet prompt'u. Geçmiş buraya GÖMÜLÜR (CLI oturumu kullanılmaz).

    `fmt`: KURULUM sırasında şart. Taslakta ses/montaj bloğu kapalı olduğu
    için `channel_format(cfg)` "card" der; kullanıcının seçtiği format
    çağırandan gelir.
    """
    from short_bot.formats import FORMATS, channel_format

    fmt = fmt or channel_format(cfg)
    ad = FORMATS[fmt].label if fmt in FORMATS else fmt
    alanlar = yazilabilir_alanlar(cfg)
    satirlar = [_USLUP, "", f"KANAL: {cfg.slug} ({ad} formatı)",
                "MEVCUT AYARLAR:"]
    for alan in alanlar:
        deger = oku(cfg, alan)
        if deger is not None:
            satirlar.append(f"  {alan} = {json.dumps(deger, ensure_ascii=False, default=str)}")

    if bulgular:
        satirlar += ["", "ÖLÇÜLEN SORUNLAR (panel bunları zaten hesapladı):"]
        satirlar += [f"  - {b.ozet}: {b.gerekce}" for b in bulgular]

    satirlar += ["", "YAZILABİLİR ALANLAR (başkasını yazma):",
                 "  " + ", ".join(alanlar)]

    if gecmis:
        satirlar += ["", "KONUŞMA:"]
        for kim, metin in gecmis:
            satirlar.append(f"  {'Kullanıcı' if kim == 'kullanici' else 'Sen'}: {metin}")

    satirlar += ["", f"Kullanıcı: {girdi}", "", "Cevabını JSON olarak ver."]
    return "\n".join(satirlar)


def taslak(fmt: str, *, language: str = "tr", slug: str = "yeni-kanal"):
    """Kurma sohbetinin üzerinde çalışacağı BOŞ kanal.

    Kurma ve düzenleme aynı motoru kullansın diye kurulum da bir
    ChannelConfig üstünde yürür: sohbet kararları `uygula` ile bu taslağa
    işlenir, kullanıcı farkı görür, "Kur"a basınca YAML yazılır.

    SLUG BURADA GEÇİCİDİR ve `YAZILABILIR` listesinde değildir: kaydederken
    kanalın adından türetilir. LLM'in slug yazmasına izin vermek dosya
    yollarını (output_dir, css, kimlik klasörü) tutarsız bırakırdı.
    """
    from short_bot.config import (ChannelConfig, ReelConfig, VoiceConfig,
                                  YoutubeChannelConfig)
    from short_bot.locale import RSS_LOCALES

    ortak = dict(
        slug=slug, name="", keywords=[], rss_locale=RSS_LOCALES.get(language, ""),
        schedule_cron="0 9,15,20 * * *", duration_s=6, min_score=6.0,
        max_candidates_per_run=10, template="flas",
        colors={"primary": "#d0021b", "accent": "#ffe600",
                "bg_gradient": ["#3a3a3a", "#141414"]},
        handle=f"@{slug}", output_dir=f"output/{slug}",
        # YENİ KANAL CRON'U KAPALI KURULUR. Kullanıcı önce birkaç video
        # üretip sonucu görsün; açık kurmak, ayarları oturmamış bir kanalı
        # doğrudan üretime sokmak demek.
        enabled=False, language=language,
        # YOUTUBE BLOĞU BAŞTAN VAR. Yoksa modelin verdiği her `youtube.*`
        # kararı `uygula`da patlıyor ve bütün partiyi düşürüyor; oysa
        # kurulumda kategori/gizlilik belirlemek meşru (Beşiktaş → Spor 17).
        # Varsayılanlar etkisiz: auto_upload False.
        youtube=YoutubeChannelConfig(),
    )
    # SES/MONTAJ BLOĞU KAPALI KURULUR. `VoiceConfig(enabled=True)` ve
    # `ReelConfig(enabled=True)` `voice_id` zorunlu kılıyor ve taslakta henüz
    # ses seçilmedi. Yer tutucu bir voice_id koymak daha kötü olurdu: kurulum
    # yarıda kalırsa diskte çalışmayan bir kanal kalırdı.
    #
    # Bu yüzden taslağın FORMATI `channel_format(cfg)`den okunamaz — formatı
    # çağıran taşır (rota parametresi) ve `prompt_kur(fmt=...)` ile verilir.
    if fmt == "voiced":
        return ChannelConfig(**ortak, voice=VoiceConfig(enabled=False))
    if fmt == "yorum":
        return ChannelConfig(**ortak, content_source="trends",
                             trends_intent="question", trends_min_volume=5000,
                             voice=VoiceConfig(enabled=False, provider="cartesia",
                                               target_duration_s=(35, 50)))
    if fmt == "curated":
        return ChannelConfig(**ortak, content_source="curated",
                             reel=ReelConfig(enabled=False))
    return ChannelConfig(**ortak)          # card


def konus(*, cfg, gecmis: Sequence[tuple[str, str]], girdi: str,
          llm: Callable[..., SohbetCevabi],
          bulgular: Sequence[Any] = (), fmt: str | None = None) -> SohbetCevabi:
    """Tek sohbet turu. `llm` imzası `sonnet_json(prompt, schema, **kw)`.

    Şema doğrulaması çağrı katmanında yapılır (sonnet_json Pydantic ile
    doğrular ve uymazsa modele tekrar sorar) — burada ayrıca ayrıştırma yok.
    """
    return llm(prompt_kur(cfg=cfg, gecmis=gecmis, girdi=girdi,
                          bulgular=bulgular, fmt=fmt), SohbetCevabi)
