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
    mesaj: str
    kararlar: list[Karar] = []
    # Composer'ın üstündeki tıklanabilir öneriler — boş kutuya bakıp donmayı
    # önler ("ne diyeceğimi bilemem").
    oneriler: list[str] = []
    kurmaya_hazir: bool = False


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

Her karar için:
- alan   : aşağıdaki YAZILABİLİR listesinden bir ad (başkasını YAZMA)
- deger  : yeni değer
- ozet   : tek satır, kullanıcının diliyle ("Bölge Avusturya (AT)")
- gerekce: NEDEN böyle seçtiğin, ölçü ya da sonuçla ("Bölge ve dil bağımsız
           alanlar; Avusturya gündemini Almanca anlatır")

Ayrıca 3-4 tane `oneriler` yaz: kullanıcının bir sonraki adımda söyleyebileceği
kısa cümleler ("günde 3 olsun", "daha sert bir ton"). Bunlar tıklanabilir çip
olacak; "ne diyeceğimi bilemem" durumunun çaresi.

Türkçe yaz."""


def prompt_kur(*, cfg, gecmis: Sequence[tuple[str, str]], girdi: str,
               bulgular: Sequence[Any] = ()) -> str:
    """Sohbet prompt'u. Geçmiş buraya GÖMÜLÜR (CLI oturumu kullanılmaz)."""
    from short_bot.formats import channel_format

    satirlar = [_USLUP, "", f"KANAL: {cfg.slug} ({channel_format(cfg)} formatı)",
                "MEVCUT AYARLAR:"]
    for alan in sorted(YAZILABILIR):
        deger = oku(cfg, alan)
        if deger is not None:
            satirlar.append(f"  {alan} = {json.dumps(deger, ensure_ascii=False, default=str)}")

    if bulgular:
        satirlar += ["", "ÖLÇÜLEN SORUNLAR (panel bunları zaten hesapladı):"]
        satirlar += [f"  - {b.ozet}: {b.gerekce}" for b in bulgular]

    satirlar += ["", "YAZILABİLİR ALANLAR (başkasını yazma):",
                 "  " + ", ".join(sorted(YAZILABILIR))]

    if gecmis:
        satirlar += ["", "KONUŞMA:"]
        for kim, metin in gecmis:
            satirlar.append(f"  {'Kullanıcı' if kim == 'kullanici' else 'Sen'}: {metin}")

    satirlar += ["", f"Kullanıcı: {girdi}", "", "Cevabını JSON olarak ver."]
    return "\n".join(satirlar)


def konus(*, cfg, gecmis: Sequence[tuple[str, str]], girdi: str,
          llm: Callable[..., SohbetCevabi],
          bulgular: Sequence[Any] = ()) -> SohbetCevabi:
    """Tek sohbet turu. `llm` imzası `sonnet_json(prompt, schema, **kw)`.

    Şema doğrulaması çağrı katmanında yapılır (sonnet_json Pydantic ile
    doğrular ve uymazsa modele tekrar sorar) — burada ayrıca ayrıştırma yok.
    """
    return llm(prompt_kur(cfg=cfg, gecmis=gecmis, girdi=girdi, bulgular=bulgular),
               SohbetCevabi)
