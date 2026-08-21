"""Kanal formatı — TEK yerde karar.

Panel (liste rozeti, düzenle sayfası), voiced.py (anlatım yazarı seçimi) ve
pipeline aynı soruyu soruyor: "bu kanal hangi formatta üretiyor?" Her biri kendi
if-zincirini kursaydı, bir alan eklenince (örn. content_source=trends + voice)
biri güncellenir diğeri unutulurdu.

Formatlar:
- card    : 6 sn haber kartı (rss/feed/trends, sessiz)
- voiced  : kart + seslendirme (Aslan Gündem+, Latido Blanco)
- yorum   : Google Trends + seslendirme = Gündem Yorum
- curated : Reddit kürate klip

ORTAK ÇEKİRDEK / FORMAT KATMANI AYRIMI (2026-08-21)
---------------------------------------------------
`FormatSpec.core` her formatta AYNI tuple'dır ve bu kasıtlıdır. Ölçüldü: ortak
alanlar dört düzenleme sayfasında ayrı ayrı yazılmıştı ve dördü de eksikti —
kürate kanalda gizlilik/kategori/yükleme eşiği UI'de HİÇ yoktu, kart kanalında
`credentials_from` yoktu (oysa gundem + gundem-yorum aynı YouTube kanalına
üretiyor). Ortak alanlar tek partial kümesinden çizilince bu sınıf hata biter.

`ChannelConfig` BÖLÜNMEZ. Dataclass'ı parçalamak tüm YAML'ları, load/save'i ve
pipeline'ı kırardı; kazancı yok. Ayrım yalnız sunum katmanındadır.

REEL: kanal formatı olarak kaldırıldı (canlıda 0 kanal). Reel PIPELINE'ı duruyor —
kürate üretimi onu kullanıyor ve `dayidiyorki` montaj ayarlarını `cfg.reel`
üzerinden okumaya devam ediyor.
"""
from __future__ import annotations

from dataclasses import dataclass

# Her formatta AYNI çizilen ortak alanlar. Sıra ekrandaki sıradır.
#
# Otomasyon (autopilot) BİLEREK yok: kendi sayfası var (/autopilot) ve hiçbir
# düzenleme sayfasında alanı bulunmuyor. Buraya koymak, olmayan bir şeyi vaat
# etmek olurdu.
CORE_PARTIALS: tuple[str, ...] = (
    "core/identity",    # ad, dil (kilitli), slug, handle
    "core/schedule",    # cron, enabled (cron çalışsın), archived (Kokpit'te görünsün)
    "core/youtube",     # bağlantı, auto_upload, gizlilik, kategori, eşik, credentials_from
)


@dataclass(frozen=True)
class FormatSpec:
    """Bir kanal formatının panel kimliği ve hangi parçalardan çizildiği.

    `core` bilerek her formatta aynıdır; farklılaşan tek şey `body_template`.
    """
    key: str
    label: str
    glyph: str
    subtitle: str
    body_template: str
    core: tuple[str, ...] = CORE_PARTIALS


FORMATS: dict[str, FormatSpec] = {
    "card": FormatSpec(
        key="card", label="Kart", glyph="▭",
        subtitle="6 saniye, sessiz",
        body_template="channels/_body_card.html.j2"),
    "voiced": FormatSpec(
        key="voiced", label="Sesli", glyph="♪",
        subtitle="6 sn kart + anlatım",
        body_template="channels/_body_voiced.html.j2"),
    "yorum": FormatSpec(
        key="yorum", label="Gündem Yorum", glyph="❝",
        subtitle="Trends + yorumcu",
        body_template="channels/_body_yorum.html.j2"),
    "curated": FormatSpec(
        key="curated", label="Kürate", glyph="✂",
        subtitle="Reddit klip + persona",
        body_template="channels/_body_curated.html.j2"),
}

# TÜRETİLMİŞ — elle ikinci bir liste tutmak, biri güncellenip diğerinin
# unutulduğu klasik tuzağı doğurur.
FORMAT_LABELS: dict[str, str] = {k: v.label for k, v in FORMATS.items()}


def channel_format(cfg) -> str:
    if getattr(cfg, "content_source", "rss") == "curated":
        return "curated"
    # `reel.enabled` FORMAT BELİRLEMEZ. Reel bir kanal formatı olmaktan çıktı
    # (canlıda 0 kanal); o blok artık yalnız kürate'nin montaj ayarlarını taşır
    # ve kürate kararı yukarıda content_source ile zaten verildi.
    voice = getattr(cfg, "voice", None)
    if voice is not None and getattr(voice, "enabled", False):
        if getattr(cfg, "content_source", "rss") == "trends":
            return "yorum"
        return "voiced"
    return "card"


def format_spec(cfg) -> FormatSpec:
    """Kanalın FormatSpec'i. Bilinmeyen/eski format kart sayılır — panel çökmez."""
    return FORMATS.get(channel_format(cfg), FORMATS["card"])
