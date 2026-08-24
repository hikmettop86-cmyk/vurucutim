"""Domain models. Frozen dataclasses for in-pipeline data, Pydantic for LLM output."""
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from short_bot.narration import NarrationTimeline
from short_bot.text_normalize import strip_non_turkish_diacritics


@dataclass(frozen=True)
class NewsItem:
    guid: str
    title: str
    link: str
    source: str | None
    pub_date: datetime | None
    thumb_url: str | None
    description: str | None
    # trend_volume: Google Trends kaynağında arama hacmi (50000 gibi). Seçim
    # sırası bu alana dayanır (hacim sıralı + AI kapısı). RSS/feed kaynaklarında
    # 0 kalır; varsayılanlı olduğu için mevcut kurucular kırılmaz.
    trend_volume: int = 0
    # extra_links: aynı haberin başka yayıncılardaki makaleleri (Google Trends her
    # trende 3 haber verir). Yorum formatı bunları ek kaynak olarak okur — 'en az
    # iki kaynak adı' kuralı buradan beslenir. 6 sn kart yolu kullanmaz.
    extra_links: tuple[str, ...] = ()
    # Aşağıdakiler yalnız Google Trends kaynağında dolar; panelin Gündem masası
    # bunları GÖSTERİR (açıklama metnini geri ayrıştırmak yerine). Puanlayıcı ve
    # senaryo yazarı description'ı kullanmaya devam eder.
    trend_growth_pct: int = 0                          # 1000 = %1.000 artış
    trend_related: tuple[str, ...] = ()                # ilişkili aramalar
    trend_articles: tuple[tuple[str, str], ...] = ()   # diğer kaynaklar: (yayıncı, başlık)
    # trend_categories: Google Trends'in KENDİ sınıflandırması (17=Spor,
    # 3=İş&Finans, 4=Eğlence…). Dikey kapısı buna dayanır, ek AI maliyeti yok
    # (bkz. trends/verticals.py). RSS/feed/curated kaynaklarında boş kalır.
    trend_categories: tuple[int, ...] = ()
    # followup_of: bu haberi DAHA ÖNCE anlatan videonun özeti (bkz. followup.py).
    # Doluysa yazarlar "güncelleme" modunda çalışır: yalnız YENİ olanı anlatır.
    # Yalnız Gündem masasındaki "takip üret" düğmesi doldurur — otomatik üretim
    # asla doldurmaz, yoksa aynı haberi iki kez anlatan bot oluruz.
    followup_of: str = ""


@dataclass(frozen=True)
class ScoredItem:
    item: NewsItem
    score: float            # 0-10
    reasoning: str          # LLM's short rationale (debug/UI)
    # category: kanal canonical liste tanımladıysa puanlayıcının atadığı konu.
    # Seçim anında konuyu bilmek gerekiyor — kategori eskiden yalnız script
    # yazılırken (seçimden SONRA) belirleniyordu, bu yüzden "aynı konudan
    # günde en fazla N" kotası uygulanamıyordu. Liste yoksa boş kalır.
    category: str = ""
    # subject: haberin merkezindeki kişi/kulüp (saga anahtarı). Kategoriyle aynı
    # sebeple SEÇİM ANINDA gerekiyor: aynı hikâyenin kaçıncı videosu olduğunu
    # bilmeden puanı düşürülemez. Kanal saga cezasını açmadıysa boş kalır.
    subject: str = ""


# VURGU ÖLÇÜSÜ. generator.py promptu vurguyu "1-3 kelime" diye tarif ediyor.
# CJK'DA BOŞLUK YOKTUR, dolayısıyla "kelime" ölçüsü orada hiçbir şey demek
# değil: model 「村上宗隆の四球をきっかけに3者連続アーチで一気に同点」yı (24 karakter)
# TEK vurgu diye üretti ve gövdenin %60'ı kırmızıya boyandı — okunmaz oldu
# (2026-08-22, short 1787). Aynı sınıf tuzak anlatım bütçesinde de çıkmıştı.
#
# Vurgu bir OLGUYU işaretler: isim, sayı, sonuç. Cümleyi değil.
_CJK_KARAKTER = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_VURGU_MAX_CJK = 12       # 「7回途中2失点」= 7, 「3者連続アーチ」= 7
_VURGU_MAX_LATIN = 40     # ~3-5 kelime
# Kapsam tavanı: tek tek kısa vurgular da toplamda gövdeyi boyayabilir.
_VURGU_KAPSAM_ORANI = 0.35


def _vurgu_siniri(metin: str) -> int:
    return _VURGU_MAX_CJK if _CJK_KARAKTER.search(metin) else _VURGU_MAX_LATIN


class Highlight(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    color: Literal["red", "yellow"]

    @field_validator("text", mode="before")
    @classmethod
    def _normalize_text(cls, v):
        return strip_non_turkish_diacritics(v) if isinstance(v, str) else v


# Başlık/etiket alanlarının üst sınırları. Bir karakterlik taşma ÜRETİMİ DÜŞÜRMEMELİ:
# gerçek hata — LLM "VÜCUDUN GİZEMLİ MEKANİZMASI" (26 karakter) yazdı, header_top 25
# sınırlıydı, 3/3 deneme ValidationError'la düştü ve koca bir üretim (LLM + TTS +
# footage + montaj) iptal oldu. Üstelik bu alan reel kanalında hiç kullanılmıyor.
# Kırpmak güvenli: görsel taşma riski zaten kalkıyor.
_TRIM_LIMITS = {"header_top": 25, "header_bottom": 35, "photo_overlay": 60,
                "category": 30}


class Script(BaseModel):
    header_top: str = Field(min_length=1, max_length=25)
    header_bottom: str = Field(min_length=1, max_length=35)
    photo_overlay: str = Field(min_length=1, max_length=60)
    body_paragraph: str = Field(min_length=20, max_length=800)
    highlights: list[Highlight] = Field(default_factory=list, max_length=8)
    category: str = Field(min_length=1, max_length=30)
    mood: Literal["breaking", "neutral", "upbeat"]
    # --- Yalnız seslendirmeli üretimde dolar; sessiz kanallarda boş kalır. ---
    # Ekrandaki `body_paragraph` haber kartı metnidir; ANLATILAN metin ondan
    # farklıdır ve hiçbir yerde saklanmıyordu.
    narration_text: str = ""
    # Anlatımın Türkçesi. Operatör hedef dili bilmiyorsa videoyu YAYINLAMADAN
    # ÖNCE "bu ne diyor" sorusunu ancak böyle yanıtlayabilir; panel bunu
    # /shorts/<id> sayfasında gösterir (web/routes/shorts.py). Türkçe kanalda boş.
    # NOT: aksan temizleyici validator'ı bu iki alana UYGULANMAZ — hedef dilin
    # aksanları (é, ñ, ü) korunmalı.
    body_paragraph_tr: str = ""
    # subject: saga sayacının anahtarı. Senaryo yazarı LLM'i bunu ÜRETMEZ —
    # seçilen adayın (ScoredItem.subject) değeri kaydetmeden hemen önce
    # taşınır. Aksan temizleyici validator'a BAĞLANMAZ: anahtar eşleşme için
    # kullanılıyor, görsel metin değil.
    subject: str = Field(default="", max_length=40)
    # narration_variation: yorum videosunun biçimi ("acilis/yaklasim/kapanis").
    # Bir sonraki video bunu OKUYUP aynısını seçmez — art arda videolar aynı
    # iskelette çıkmasın diye (kullanıcı bildirimi 2026-08-20).
    narration_variation: str = Field(default="", max_length=60)
    # search_queries: bu KONUNUN canlı arama dizeleri (Trends ilişkili aramaları).
    # Senaryo yazarı ÜRETMEZ — seçilen adaydan kaydetmeden önce taşınır, tıpkı
    # subject gibi. Tek tüketicisi YouTube metadata yazarı: başlık/açıklama/etiket
    # YouTube'un metni sorguyla eşleştirdiği TEK yer. Konuşulan metne ASLA girmez
    # (bkz. narration_writer.BANNED_PHRASES — kullanıcı kuralı 2026-08-20).
    search_queries: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("header_top", "header_bottom", "photo_overlay",
                      "body_paragraph", "category", mode="before")
    @classmethod
    def _normalize_text(cls, v):
        return strip_non_turkish_diacritics(v) if isinstance(v, str) else v

    @field_validator("header_top", "header_bottom", "photo_overlay", "category",
                     mode="before")
    @classmethod
    def _trim_overflow(cls, v, info):
        """Taşan BAŞLIK/ETİKET alanını kırp (gövde metni HARİÇ — orayı kırpmak
        cümleyi yarım bırakır, LLM yeniden yazsın diye hata verilir)."""
        limit = _TRIM_LIMITS.get(info.field_name)
        if isinstance(v, str) and limit and len(v) > limit:
            return v[:limit].rstrip()
        return v

    @field_validator("highlights", mode="before")
    @classmethod
    def _flatten_highlights(cls, v):
        """İÇ İÇE listeyi düzle, çöpü at — üretimi DÜŞÜRME.

        CANLI VAKA (2026-08-23, fenerbahce koşu #2112 ve galatasaray #2105):
        model `highlights`'ı [[{...}, {...}]] diye SARMALAYARAK döndürdü.
        Pydantic "Input should be a valid dictionary" der, `run_json` 3 denemeyi
        de aynı şekilde kaybeder ve koca bir üretim iptal olur — oysa vurgular
        tamamen KOZMETİK: vurgusuz gövde gayet okunur. Aynı gerekçeyle başlık
        alanları kırpılıyor (bkz. _TRIM_LIMITS) ve cümle boyu vurgular hata
        yerine düşürülüyor (bkz. highlights_mark_facts_not_sentences).

        Düz dize de kabul edilir: model bazen ["Fenerbahçe"] yazıyor. Rengi
        varsayılana çekmek, vurgunun tamamen kaybolmasından iyidir.
        """
        if not isinstance(v, list):
            return v
        duz = []

        def _ekle(x, derinlik=0):
            if isinstance(x, list) and derinlik < 4:   # 4 = makul bir taban
                for y in x:
                    _ekle(y, derinlik + 1)
            elif isinstance(x, str):
                if x.strip():
                    duz.append({"text": x.strip(), "color": "yellow"})
            elif x is not None:
                duz.append(x)                          # dict / Highlight

        _ekle(v)
        return duz

    @model_validator(mode="after")
    def highlights_must_be_substrings(self) -> "Script":
        for h in self.highlights:
            if h.text not in self.body_paragraph:
                raise ValueError(
                    f"Highlight '{h.text}' paragrafta birebir geçmiyor"
                )
        return self

    @model_validator(mode="after")
    def highlights_mark_facts_not_sentences(self) -> "Script":
        """Cümle boyu ve gövdeyi kaplayan vurguları DÜŞÜR (hata FIRLATMA).

        Fırlatmak koca bir üretimi (LLM + TTS + render) çöpe atardı; oysa
        kusur yalnız kozmetik — vurgusuz gövde gayet okunur. Aynı gerekçe
        header alanlarının kırpılmasında da geçerli (bkz. yukarıdaki not).
        """
        if not self.highlights:
            return self
        uygun = [h for h in self.highlights
                 if len(h.text) <= _vurgu_siniri(h.text)]
        govde = self.body_paragraph or ""
        if govde and uygun:
            tavan = len(govde) * _VURGU_KAPSAM_ORANI
            # Kısa vurgu daha kesin bir işarettir: tavana önce onlar girsin.
            tutulan, toplam = set(), 0
            for h in sorted(uygun, key=lambda x: len(x.text)):
                if toplam + len(h.text) > tavan:
                    continue
                tutulan.add(id(h))
                toplam += len(h.text)
            # Modelin verdiği SIRA korunur: renderer ilk eşleşmeyi sarıyor.
            uygun = [h for h in uygun if id(h) in tutulan]
        self.highlights = uygun
        return self


@dataclass
class RenderJob:
    script: Script
    bg_image_path: Path | None
    music_path: Path
    channel_colors: dict
    handle: str
    duration_s: int
    language: str = "tr"
    # Beğeni/abone CTA alanları KALDIRILDI (2026-07-16, kullanıcı kararı).
    rss_source: str | None = None   # shown as "Kaynak: <source>" overlay
    # Doluysa video "voiced" modda render edilir: süre sesten gelir,
    # her karede window.__seek(t_ms) çağrılır.
    narration: NarrationTimeline | None = None
    # ticker_items: şablonun alt akan şeridinde gösterilecek diğer başlıklar
    # (flas arketipi 'SIRADA' ticker'ı). Trend kanalında koşudaki diğer
    # yüksek hacimli olaylarla dolar; başka kaynaklarda boş kalır.
    ticker_items: tuple[str, ...] = ()
