"""Reel abone mekanikleri: seri çerçevesi + yorum-sorusu + CTA son kartı.

Deterministik (seed → sabit), havuzdan rotasyon (şablon parmak izi vermez).

METİNLERİN TAMAMI DİL PAKETİNDEN gelir (lang_pack). Türkçe sabit oldukları sürece
Almanca kanalın ekranına Türkçe "ABONE OL" çipi basılıyordu ve LLM'e Türkçe yorum-soru
yönergesi gidiyordu.

YORUM YEMİ — YÖNERGE, kalıp cümle DEĞİL.
  Açık uçlu sorular ("Ne düşünüyorsun?") YÜKSEK EFORLUDUR ve cevapsız kalır. Yanıt ALAN
  türler: İKİLİ/hangisi (tek harf yeter), kişisel hatırlama, doğrulama, eksiği-bul. Ama
  iyi bir soru VİDEODAKİ SPESİFİK BİR ANA bağlı olmalı — jenerik kalıp bunu yapamaz. O
  yüzden LLM'e cümleyi yazdırıyoruz, biz yalnız TÜRÜ dayatıyoruz. ("Yanlışı bul" türü
  KASTEN YOK: kısa vadeli yorum için uzun vadeli OTORİTEYİ takas eder.)

ABONE İSTEĞİ — "Daha fazlası için abone ol" araştırmanın adıyla andığı ölü ifadedir:
  izleyici bunu on bin kez duydu, beyni filtreliyor ("YouTube beyaz gürültüsü").
  İşleyen çerçeveler: DEĞER-SPESİFİK (ne alacağını söyle) ve SERİ (dönüşü alışkanlık
  yapar). ÇİP TEK SATIR: 1080px genişliğe sığmalı — bu yüzden CTA_MAX_CHARS kod sabiti
  ve dil paketleri ona uymak ZORUNDA (üretim anında doğrulanır).
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from short_bot.lang_pack import CTA_MAX_CHARS, load_pack

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubscribeBits:
    series_directive: str
    comment_line: str
    cta_text: str
    badge: str = ""          # feed kimliği rozeti ("BİLİNMEYEN TARİH #47")


def _idx(seed: int, salt: str, n: int) -> int:
    h = hashlib.sha1(f"{seed}:{salt}".encode("utf-8")).hexdigest()
    return int(h, 16) % n


def build_subscribe_bits(channel, seed: int, episode=None) -> SubscribeBits:
    """Abone mekanikleri. ``episode`` (EpisodePlan) verilirse SERİ modu devreye girer.

    Seri modunda üç şey değişir:
      • yönerge: LLM'e bölüm numarası + ödenecek söz + açılacak kapı bildirilir
      • CTA: jenerik rotasyon yerine TAKAS ("#48 yarın — ABONE OL")
      • rozet: kare sıfırda feed kimliği

    Ayrıca YORUM SORUSU KAPATILIR. Çalışma belgesi (§3.1) "son 5 saniyede CTA
    yığılması: üç istek = sıfır istek" diyor. Seride izleyiciden istediğimiz TEK şey
    net: bir sonraki bölüm için abone olmak. Yorum sorusu onunla dikkat için yarışır
    ve ikisi de kaybeder.
    """
    reel = channel.reel
    pack = load_pack(channel.language)
    seri = episode is not None and getattr(episode, "enabled", True)

    series_directive = ""
    badge = ""
    if seri:
        from short_bot.reel_series import episode_badge
        from short_bot.reel_series import series_directive as _sd
        title = (getattr(reel, "series_title", "")
                 or pack.default_series_title).strip()
        series_directive = _sd(episode, title, pack=pack)
        badge = episode_badge(title, episode.episode_no, pack=pack)
    elif getattr(reel, "series_enabled", False):
        # Seri açık ama bölüm planı gelmedi (eski çağıranlar / plan kurulamadı) →
        # eski davranış: yalnız bir teaser yönergesi, numara ve takas yok.
        title = (getattr(reel, "series_title", "")
                 or pack.default_series_title).strip()
        series_directive = pack.series.teaser_fallback.format(title=title)

    comment_line = ""
    if getattr(reel, "comment_question", False) and not seri:
        comment_line = pack.comment_styles[
            _idx(seed, "comment", len(pack.comment_styles))]

    cta_text = ""
    if getattr(reel, "cta_enabled", False):
        custom = (getattr(reel, "cta_text_custom", "") or "").strip()
        if seri and not custom:
            # TAKAS: numarası olan istek somut bir şey vaat eder ve ne zaman
            # geleceğini söyler. "Daha fazlası için abone ol" beyaz gürültüdür.
            from short_bot.reel_series import trade_cta
            cta_text = trade_cta(episode.next_no, pack=pack)
        else:
            cta_text = custom or pack.cta_texts[
                _idx(seed, "cta", len(pack.cta_texts))]
        if len(cta_text) > CTA_MAX_CHARS:
            # Paket metinleri ÜRETİM ANINDA doğrulandığı için buraya normalde yalnız
            # cta_text_custom düşebilir (kullanıcının elle girdiği metin). Kesilmiş
            # bir çip ("...ABONE O") her şeyden kötü — kırp ve uyar.
            log.warning(f"  abone çipi çok uzun ({len(cta_text)} > {CTA_MAX_CHARS} "
                        f"karakter), kırpılıyor: {cta_text!r}")
            cta_text = cta_text[:CTA_MAX_CHARS].rstrip()

    return SubscribeBits(series_directive=series_directive,
                         comment_line=comment_line, cta_text=cta_text, badge=badge)
