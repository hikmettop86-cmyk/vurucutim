"""Reel abone mekanikleri: seri çerçevesi + yorum-sorusu + CTA son kartı.

Deterministik (seed → sabit), havuzdan rotasyon (şablon parmak izi vermez).
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# YORUM YEMİ — YÖNERGE, kalıp cümle DEĞİL.
#
# Açık uçlu sorular ("Ne düşünüyorsun?", "Hangisi seni en çok şaşırttı?") YÜKSEK
# EFORLUDUR ve cevapsız kalır. Yanıt ALAN türler: İKİLİ/hangisi (tek harf yeter),
# kişisel hatırlama, doğrulama, eksiği-bul. Ama iyi bir soru VİDEODAKİ SPESİFİK BİR
# ANA bağlı olmalı — jenerik kalıp bunu yapamaz. O yüzden LLM'e cümleyi yazdırıyoruz,
# biz yalnız TÜRÜ dayatıyoruz.
#
# "Yanlışı bul" türü KASTEN YOK: bilim/tarih kanalında kısa vadeli yorum için uzun
# vadeli OTORİTEYİ takas eder — otorite bizim ürünümüz. Yerine "eksiği bul".
COMMENT_STYLES = (
    "İKİLİ SORU: videodaki iki şıkkı karşılaştıran, tek harfle (A/B) "
    "cevaplanabilecek bir soru sor. Örnek kalıp: 'Sence hangisi daha çılgın: "
    "A mı, B mi? Tek harf yaz.'",
    "KİŞİSEL HATIRLAMA: 'Bunu kaç yaşında öğrendin?' gibi, izleyicinin kendi "
    "deneyimini tek kelimeyle yazabileceği bir soru sor.",
    "DOĞRULAMA: 'Bunu duyunca tüylerin diken diken olan bir ben miyim?' gibi, "
    "onay ya da itiraz — ikisi de yorum getiren bir cümle kur.",
    "EKSİĞİ BUL: 'Kasten bir detay atladım, bulabilir misin?' tarzı, izleyiciyi "
    "videoya geri döndüren bir soru sor. (Kasten YANLIŞ bilgi verme — otoriteyi "
    "asla takas etme.)",
)

# ABONE İSTEĞİ — "Daha fazlası için abone ol" ARAŞTIRMANIN ADIYLA ANDIĞI ölü ifade:
# izleyici bunu on bin kez duydu, beyni filtreliyor ("YouTube beyaz gürültüsü").
# İşleyen çerçeveler: DEĞER-SPESİFİK (ne alacağını söyle) ve SERİ (dönüşü alışkanlık
# yapar; seri izleyicisi ilk-kez izleyiciden çok daha yüksek oranda abone olur).
#
# ÇİP TEK SATIR: 1080px genişliğe sığmalı. "Bu seri devam ediyor — ABONE OL" (30
# karakter) sağdan KESİLİYORDU. Sarmaya izin vermek çözüm değil — iki satırlık çip
# altyazının üstüne biner ve payoff'u kapatır (araştırma: CTA payoff'u KAPATMAMALI).
CTA_MAX_CHARS = 24
CTA_TEXTS = (
    "Her gün yeni — ABONE OL",
    "Yarın devamı — ABONE OL",
    "Seri sürüyor — ABONE OL",
    "Devamı yarın — ABONE OL",
)


@dataclass(frozen=True)
class SubscribeBits:
    series_directive: str
    comment_line: str
    cta_text: str


def _idx(seed: int, salt: str, n: int) -> int:
    h = hashlib.sha1(f"{seed}:{salt}".encode("utf-8")).hexdigest()
    return int(h, 16) % n


def build_subscribe_bits(channel, seed: int) -> SubscribeBits:
    reel = channel.reel

    series_directive = ""
    if getattr(reel, "series_enabled", False):
        title = (getattr(reel, "series_title", "") or "İlginç Bilgiler").strip()
        series_directive = (
            f"Bu bir '{title}' serisinin bir bölümü. Kapanışı, izleyiciyi bir "
            f"sonraki bölüm için meraklandıracak bir AÇIK DÖNGÜ / teaser ile bitir "
            f"('bir sonrakinde daha da tuhafı var' tarzı)."
        )

    comment_line = ""
    if getattr(reel, "comment_question", False):
        comment_line = COMMENT_STYLES[_idx(seed, "comment", len(COMMENT_STYLES))]

    cta_text = ""
    if getattr(reel, "cta_enabled", False):
        custom = (getattr(reel, "cta_text_custom", "") or "").strip()
        cta_text = custom or CTA_TEXTS[_idx(seed, "cta", len(CTA_TEXTS))]
        if len(cta_text) > CTA_MAX_CHARS:
            # Kesilmiş çip ("...ABONE O") her şeyden kötü — kırp ve uyar.
            log.warning(f"  abone çipi çok uzun ({len(cta_text)} > {CTA_MAX_CHARS} "
                        f"karakter), kırpılıyor: {cta_text!r}")
            cta_text = cta_text[:CTA_MAX_CHARS].rstrip()

    return SubscribeBits(series_directive=series_directive,
                         comment_line=comment_line, cta_text=cta_text)
