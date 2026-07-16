"""Reel etkileşim mekanikleri: seri çerçevesi + yorum-sorusu + feed rozeti.

Deterministik (seed → sabit), havuzdan rotasyon (şablon parmak izi vermez).

METİNLERİN TAMAMI DİL PAKETİNDEN gelir (lang_pack). Türkçe sabit oldukları sürece
Almanca kanalın ekranına Türkçe çip basılıyordu ve LLM'e Türkçe yorum-soru
yönergesi gidiyordu.

YORUM YEMİ — YÖNERGE, kalıp cümle DEĞİL.
  Açık uçlu sorular ("Ne düşünüyorsun?") YÜKSEK EFORLUDUR ve cevapsız kalır. Yanıt ALAN
  türler: İKİLİ/hangisi (tek harf yeter), kişisel hatırlama, doğrulama, eksiği-bul. Ama
  iyi bir soru VİDEODAKİ SPESİFİK BİR ANA bağlı olmalı — jenerik kalıp bunu yapamaz. O
  yüzden LLM'e cümleyi yazdırıyoruz, biz yalnız TÜRÜ dayatıyoruz. ("Yanlışı bul" türü
  KASTEN YOK: kısa vadeli yorum için uzun vadeli OTORİTEYİ takas eder.)

BEĞENİ/ABONE İSTEĞİ YOK (2026-07-16, kullanıcı kararı): "kullanıcı gerçekten
  içinden gelirse abone veya beğenme yapar." Eski mekanik (tepe-sonrası beğeni
  nabzı + değer-spesifik/takas abone çipi) tamamen kaldırıldı. Seri mimarisi
  (bölüm rozeti + cliffhanger) İÇERİK yapısı olarak kalır — istem değildir.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from short_bot.lang_pack import load_pack

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubscribeBits:
    series_directive: str
    comment_line: str
    badge: str = ""          # feed kimliği rozeti ("BİLİNMEYEN TARİH #47")


def _idx(seed: int, salt: str, n: int) -> int:
    h = hashlib.sha1(f"{seed}:{salt}".encode("utf-8")).hexdigest()
    return int(h, 16) % n


def build_subscribe_bits(channel, seed: int, episode=None) -> SubscribeBits:
    """Etkileşim mekanikleri. ``episode`` (EpisodePlan) verilirse SERİ modu devreye girer.

    Seri modunda iki şey değişir:
      • yönerge: LLM'e bölüm numarası + ödenecek söz + açılacak kapı bildirilir
      • rozet: kare sıfırda feed kimliği

    Ayrıca YORUM SORUSU KAPATILIR. Çalışma belgesi (§3.1) "son 5 saniyede istek
    yığılması: üç istek = sıfır istek" diyor. Seride izleyicinin dikkati tek şeyde
    kalmalı: bir sonraki bölümün merakı.
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
        # eski davranış: yalnız bir teaser yönergesi, numara yok.
        title = (getattr(reel, "series_title", "")
                 or pack.default_series_title).strip()
        series_directive = pack.series.teaser_fallback.format(title=title)

    comment_line = ""
    if getattr(reel, "comment_question", False) and not seri:
        comment_line = pack.comment_styles[
            _idx(seed, "comment", len(pack.comment_styles))]

    return SubscribeBits(series_directive=series_directive,
                         comment_line=comment_line, badge=badge)
