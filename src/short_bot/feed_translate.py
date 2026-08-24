"""RSS Havuzu'ndaki YABANCI dilli haberleri panelde Türkçe göstermek.

NEDEN VAR: operatör yabancı dil bilmiyor. Bernabéu Digital gibi İspanyolca
kaynaklar listede "Otra confirmación más: Endrick no se marchará al Liverpool"
diye görünüyordu; hangi haberin videoya değdiğine bakarak karar vermek imkânsızdı.

ÇEVİRİ YALNIZ GÖSTERİM İÇİNDİR. Video üretimine ORİJİNAL metin gider ve bu
bilinçli bir karardır:
  • Kanal İspanyolcaysa (Latido Blanco) Türkçeye çevrilmiş başlık senaryoyu
    ikinci bir çeviriden geçirir — iki kayıp üst üste biner.
  • Senaryo yazan model kaynağı zaten okuyabiliyor; araya çeviri koymak
    ayrıntıyı (rakam, isim, alıntı) inceltmekten başka bir şey yapmaz.
Bu yüzden `feeds.py` formun gizli alanlarına ORİJİNALİ yazar, ekrana Türkçesini.

Bu bir PENCERE, kapı DEĞİL: çeviri patlarsa liste orijinal diliyle görünür,
haber seçimi durmaz (`lang_review.back_translate` ile aynı tutum).
"""
from __future__ import annotations

import html
import json
import logging
import re

from pydantic import BaseModel, Field

from short_bot.claude_cli import run_json
from short_bot.text_normalize import turkce_gorunuyor_mu

log = logging.getLogger(__name__)

# Tek çağrıda kaç haber çevrilecek. 20 haberlik tipik feed tek istekte biter
# (~4-6 sn). Bölme, 100+ haberlik feed'lerde istemin modelin dikkatini dağıtacak
# kadar uzamaması için var — uzun listelerde model satır atlıyor.
PARCA = 25
# Özetin çeviriye giden kısmı. Panelde zaten 160 karakter gösteriliyor; tamamını
# göndermek jetonu haberin gövdesine harcar, oysa karar başlıkla veriliyor.
OZET_SINIRI = 300

_ETIKET_RE = re.compile(r"<[^>]+>")
_BOSLUK_RE = re.compile(r"\s+")

class _Satir(BaseModel):
    """Tek haberin Türkçesi.

    ``i`` ZORUNLU (varsayılan YOK): eşleşme buna dayanıyor. Model alanı atlarsa
    pydantic hata atmalı ki çeviri fail-open'a düşsün — 0'a düşmek, TÜM
    başlıkların ilk habere yazılması demekti.
    """
    i: int
    baslik: str = Field(default="", max_length=400)
    ozet: str = Field(default="", max_length=800)


class _Ceviri(BaseModel):
    satirlar: list[_Satir] = Field(default_factory=list)


_ISTEM = """You are translating RSS news items into TURKISH for a Turkish
operator who does not speak the source language. They read this list to decide
which item is worth turning into a video.

RULES
- Translate the MEANING, in natural Turkish news-headline style. Never
  transliterate word by word.
- Keep proper nouns exactly as written: clubs, people, cities, competitions
  (Real Madrid, Endrick, Bellingham, LaLiga...). Do not "turkify" them.
- "baslik": a headline, not a sentence. Keep it roughly as short as the source.
- "ozet": ONE plain Turkish sentence, max ~160 characters, saying what happened.
  If the source summary is empty or is only boilerplate, return "".
- Return EVERY input row with the SAME "i" value. Never reorder, merge, drop or
  invent rows.

ITEMS (JSON):
{items}

OUTPUT: a single JSON object, nothing else — no prose, no markdown fence:
{{"satirlar":[{{"i":0,"baslik":"...","ozet":"..."}}]}}"""


def temizle(ham: str | None) -> str:
    """RSS açıklamasını okunur düz metne indir: entity çöz → etiket sök → boşluk sadeleştir.

    ÖLÇÜLDÜ (panel ekran görüntüsü, 24.08): Bernabéu Digital'in özetleri listede
    ``Bernab&eacute;u Digital les ofrece las noticias m&aacute;s destacadas``
    diye görünüyordu. Feed metni ÇİFT kodlanmış (``&amp;eacute;``); feedparser
    bir kat çözüyor, geriye kalan kat ekrana düz metin olarak düşüyor. İki kez
    unescape ETMEK ŞART — tek geçiş bu feed'i düzeltmez.

    Etiket sökme entity çözmeden ÖNCE yapılamaz: ``&lt;p&gt;`` çözülmeden etiket
    gibi görünmez, çözüldükten sonra metinde ham ``<p>`` kalırdı.
    """
    if not ham:
        return ""
    metin = html.unescape(html.unescape(ham))
    metin = _ETIKET_RE.sub(" ", metin)
    return _BOSLUK_RE.sub(" ", metin).strip()


def turkce_mi(metin: str) -> bool:
    """Metin zaten Türkçe mi? (Türkçeyse çeviri çağrısı hiç yapılmaz.)

    Şüphede ÇEVİRİ tarafına düşer — yanlışlıkla çevrilen Türkçe feed birkaç
    kuruşa mal olur, çevrilmeyen yabancı feed ise operatörü ilk günkü yerine
    geri koyar. Bu yüzden eşikler düşük tutuldu.
    """
    kucuk = (metin or "").lower()
    if not kucuk.strip():
        return True  # çevrilecek bir şey yok
    if turkce_gorunuyor_mu(kucuk):
        return True
    # Latin harfi HİÇ yoksa çevrilecek bir cümle de yoktur (salt rakam/işaret).
    # Latin DIŞI yazı (Japonca, Rusça…) ise tam tersi: kesinlikle yabancı ve
    # `turkce_gorunuyor_mu` orada zaten False döner, bu yüzden çeviriye gider.
    return not re.search(r"[^\W\d_]", kucuk, flags=re.UNICODE)


def turkcelestir(satirlar: list[tuple[str, str]], *, backend: str = "claude_cli",
                 model: str = "default", api_key: str | None = None,
                 claude_path: str = "claude") -> dict[int, tuple[str, str]]:
    """[(başlık, özet)] → {sıra: (türkçe başlık, türkçe özet)}.

    Yalnız çevrilebilen satırlar döner: eksik sıra numarası "bu haber orijinal
    diliyle gösterilsin" demektir. Hata → ilgili parça sessizce atlanır.
    """
    if not satirlar:
        return {}
    tumu = " ".join(b for b, _ in satirlar)
    if turkce_mi(tumu):
        return {}

    sonuc: dict[int, tuple[str, str]] = {}
    for bas in range(0, len(satirlar), PARCA):
        parca = [{"i": i, "title": b, "summary": (o or "")[:OZET_SINIRI]}
                 for i, (b, o) in enumerate(satirlar[bas:bas + PARCA], start=bas)]
        istem = _ISTEM.format(items=json.dumps(parca, ensure_ascii=False))
        try:
            cevap = run_json(istem, _Ceviri, claude_path=claude_path, model=model,
                             backend=backend, api_key=api_key, retries=2,
                             timeout_s=120)
        except Exception as e:  # noqa: BLE001 — pencere, kapı değil
            log.info(f"  feed[çeviri]: parça {bas} çevrilemedi ({e})")
            continue
        for s in cevap.satirlar:
            # Aralık dışı sıra numarası: model uydurmuş demektir, yok say —
            # yoksa var olmayan bir habere Türkçe başlık yazılırdı.
            if 0 <= s.i < len(satirlar) and (s.baslik or "").strip():
                sonuc[s.i] = (s.baslik.strip(), (s.ozet or "").strip())
    return sonuc
