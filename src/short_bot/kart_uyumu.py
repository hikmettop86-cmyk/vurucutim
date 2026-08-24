"""EKRAN ile SESİN aynı olayı anlattığını doğrulayan senaryo-sonrası yargı.

NEDEN VAR — mevcut mekanik kapı yalnız ÖZNEYE bakıyor
─────────────────────────────────────────────────────────────────────────────
`narration_writer.card_mismatch` kartın öznesinin (header_top) anlatımda geçip
geçmediğine bakar. Bu, anlatımın bambaşka bir habere kaymasını yakalar ama
AYNI ÖZNE / FARKLI OLAY halini göremez. Canlı vakalar:

    #1848  kart: BLEACH — ilkokul Koshien özeli (McDonald's turnuvası)
           ses : BLEACH seiyuu röportajı (Umehara'nın 20 yılı)
           → "BLEACH" iki yanda da geçiyor, mekanik kapı temiz dedi.

    #1810  kart: ソフトバンク — 近藤・栗原・柳田'nın home run'ları
           ses : ソフトバンク'ın 大津亮介'i, sezonun 10. galibiyeti
           → aynı takım, başka maç. Kapı görmedi.

NEDEN MEKANİK ÖLÇÜT ÇÖZMÜYOR — ölçüldü (73 anlatımlı video, 2026-08-23)
─────────────────────────────────────────────────────────────────────────────
Kart gövdesi ↔ anlatım arasında dilden bağımsız birim örtüşmesi (CJK 2-gram +
kelime kökü) hesaplandı. Bilinen kırıklar dağılımın dibinde ama SAĞLAM videolar
da orada:

    #1772 KIRIK  0,130      #1797 sağlam 0,167
    #1848 KIRIK  0,136      #1713 sağlam 0,192
    #1810 KIRIK  0,228      #1732 sağlam 0,208

Manşet örtüşmesi de ayırmıyor: #1713 ("İLK MAÇTA 1-0 YENİLDİ" ↔ anlatım "bir
sıfırlık skor") ve #1793 ("ZAM GELDİ" ↔ "gelen zamla") 0,00 örtüşmeyle
kırıkların yanında duruyor. Üç ayrı gürültü kaynağı ölçütü kör ediyor:
seslendirme sayıları YAZIYLA yazıyor, Türkçe ekleri kökü değiştiriyor,
Japoncada bileşik ad kısaltılıyor (鹿島アントラーズ → 鹿島).

İki dağılım iç içe olduğuna göre karar metin benzerliğinde değil, ikisini de
OKUYAN bir yargıçta olmalı — mükerrerlik kapısının (story_dedup) izlediği yol.

PENCERE, KAPI DEĞİL: yargı alınamazsa "uyumlu" döner. Yanlış ELEME yanlış
geçirmeden pahalı — burada bedeli boşuna bir yeniden yazım turu ve kısalan,
bozulan bir anlatımdır (bkz. #1806: iki tur boşa gitti, metin 179 karaktere
düştü).
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from short_bot.claude_cli import run_json

log = logging.getLogger(__name__)

#: Yargıca giden metinlerin üst sınırı. Kart zaten kısa; anlatım 40-50 saniye,
#: yani birkaç yüz karakter. Kırpma yalnız uç kaçaklara karşı.
_KART_KARAKTER = 700
_ANLATIM_KARAKTER = 2000


class KartKarari:
    """``sapma`` boşsa uyumlu. Doğruluk değeri: sapma varsa True."""

    def __init__(self, sapma: str = ""):
        self.sapma = sapma

    def __bool__(self) -> bool:
        return bool(self.sapma)

    def __repr__(self) -> str:  # pragma: no cover — hata ayıklama kolaylığı
        return f"KartKarari({self.sapma!r})"


class _Karar(BaseModel):
    same_event: bool = Field(default=True)
    reason: str = ""


_ISTEM = """You are the editor of a short-form news channel. Every video shows a CARD
on screen while a VOICEOVER plays. Both must be about the SAME news event —
otherwise the viewer reads one story and hears another.

CARD (what the viewer READS):
{kart}

VOICEOVER (what the viewer HEARS):
{anlatim}

Answer ONE question: do these describe the SAME news event?

  SAME EVENT — answer true. All of these are the same event:
    · the voiceover adds detail, background, numbers or a quote the card omits
    · the voiceover takes an angle, opinion or reaction to the card's event
    · the voiceover names people the card only implies (a squad, a company)
    · the wording, the order and the emphasis differ completely
    · numbers are spelled out in words instead of digits
    · a name is shortened or written differently in one of them

  DIFFERENT EVENT — answer false. Only these:
    · a different match, fixture, announcement, release or incident
    · the same subject but another occasion (one game's result vs. another
      game's result; one interview vs. another interview)
    · the card's central claim appears NOWHERE in the voiceover, and the
      voiceover's central claim appears NOWHERE in the card

WHEN IN DOUBT, ANSWER TRUE. A wrongly flagged video is rewritten for nothing and
comes back shorter and worse. Answer false only when you can name the card's
event and the voiceover's event and they are two different occurrences.

Return JSON: {{"same_event": true|false,
"reason": "<one short sentence in English; name BOTH events when false>"}}"""


def kart_ozeti(card) -> str:
    """Yargıca giden kart metni: manşet + gövde.

    Foto şeridi ve vurgular dışarıda — aynı olayı başka kelimelerle tekrar
    ediyorlar ve istemi şişirmekten başka bir şey katmıyorlar (story_dedup'ta
    aynı karar verildi).
    """
    if not card:
        return ""
    al = card.get if hasattr(card, "get") else (lambda k, d="": getattr(card, k, d))
    ust = (al("header_top", "") or "").strip()
    alt = (al("header_bottom", "") or "").strip()
    govde = (al("body_paragraph", "") or "").strip()
    return f"{ust} {alt} — {govde}".strip(" —")[:_KART_KARAKTER]


def ayni_olay_mi(card, narration_text: str, *,
                 backend: str = "claude_cli", model: str = "default",
                 api_key: str | None = None, claude_path: str = "claude",
                 strict: bool = False) -> KartKarari:
    """Kart ile anlatım aynı olayı mı anlatıyor? Sapma varsa sebebi döner.

    Kart ya da anlatım boşsa, yargı alınamazsa ya da model sebep veremiyorsa
    "uyumlu" döner (fail-open, bkz. modül başlığı).

    ``strict``: hatayı yükselt (panelden elle çalıştırma / test için).
    """
    kart = kart_ozeti(card)
    anlatim = (narration_text or "").strip()[:_ANLATIM_KARAKTER]
    if not kart or not anlatim:
        return KartKarari()
    try:
        karar = run_json(_ISTEM.format(kart=kart, anlatim=anlatim), _Karar,
                         claude_path=claude_path, model=model, backend=backend,
                         api_key=api_key, retries=2, timeout_s=90)
    except Exception as e:  # noqa: BLE001 — pencere, kapı değil
        log.info(f"  kart uyumu yargısı alınamadı ({e})")
        if strict:
            raise
        return KartKarari()

    if karar.same_event:
        return KartKarari()
    sebep = (karar.reason or "").strip()
    if not sebep:
        # Sebepsiz "farklı" GÜVENİLMEZ: istem her iki olayı da adlandırmayı
        # şart koşuyor. Adlandıramayan bir yargıyla anlatım yeniden yazdırılmaz.
        log.info("  kart uyumu yargısı sebep vermedi → yok sayıldı")
        return KartKarari()
    return KartKarari(sebep)
