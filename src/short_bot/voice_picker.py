"""Hedef dilde konuşan ANLATICI sesi seç.

ÖLÇÜLDÜ (ai33 /v3/voices, gerçek çağrı): 605 ses.
    en=365  hi=38  es=34  vi=22  pt=20  de=18  ko=15  fr=15  ja=12  it=10  tr=8

SAYFALAMA ŞART: varsayılan sayfa çoğunlukla İngilizce; Almanca sesler ileriki
sayfalarda. İlk sayfada durursan "Almanca ses yok" dersin — ama var.

SEÇİM ÖNEMSİZ DEĞİL: Almanca seslerden biri "Mark - Sales Executive", biri
"Daniel - Teacher, explainer-in-chief". Faceless ilginç-bilgi kanalına ikincisi uyar;
"ilk erkek sesi al" kuralı bunu bilemez. O yüzden seçimi LLM yapar ve GEREKÇESİNİ
yazar — kullanıcı planda görür.

HEDEF DİLDE SES YOKSA RuntimeError. İngilizce sese sessizce düşmek YASAK: Almanca
kanal İngiliz aksanıyla okur ve bunu hiçbir şey söylemez.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

from short_bot.locale import LANGUAGE_NAMES
from short_bot.tts.ai33_client import list_voices

log = logging.getLogger(__name__)

_MAX_PAGES = 8       # 8 × 100 = 800 ses; kütüphane bugün 605
_PAGE_SIZE = 100


class VoiceChoice(BaseModel):
    voice_id: str
    name: str
    reason: str      # NEDEN bu ses — kullanıcı planda görecek


def voices_for(language: str, *, api_key: str, session=None) -> list[dict]:
    """ai33 kütüphanesinden HEDEF DİLDE konuşan sesler.

    Hedef dilde ses yoksa RuntimeError — İngilizceye DÜŞMEZ.
    """
    if not api_key:
        raise RuntimeError("ai33 API anahtarı yok — Ayarlar'dan ekleyin "
                           "(ses olmadan reel kanalı kurulamaz).")

    hepsi: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        sayfa = list_voices(api_key=api_key, provider="elevenlabs",
                            page=page, page_size=_PAGE_SIZE, session=session)
        if not sayfa:
            break
        hepsi.extend(sayfa)

    out = [v for v in hepsi
           if str(v.get("language") or "").lower() == (language or "").lower()]
    if not out:
        ad = LANGUAGE_NAMES.get(language, language)
        raise RuntimeError(
            f"ai33 kütüphanesinde {ad} konuşan ses bulunamadı ({len(hepsi)} ses "
            f"tarandı). İngilizce bir sese DÜŞMÜYORUZ — {ad} kanal İngiliz aksanıyla "
            f"okur ve bunu hiçbir şey söylemez. Sesi elle seçin.")
    log.info(f"[ses] {len(hepsi)} sesten {len(out)} tanesi {language}")
    return out


class _Pick(BaseModel):
    voice_id: str
    reason: str = ""


def _prompt(language: str, niche: str, voices: list[dict]) -> str:
    ad = LANGUAGE_NAMES.get(language, language)
    liste = "\n".join(
        f'- {v["voice_id"]} | {v.get("name", "")} | {v.get("gender", "")} | '
        f'{v.get("accent", "")} | {(v.get("description") or "")[:160]}'
        for v in voices)
    return f"""Bir YouTube Shorts kanalı için ANLATICI sesi seç.

KANALIN NİŞİ: {niche}
DİL: {ad}
FORMAT: 40 saniyelik faceless "ilginç bilgi" shorts — stok görüntü + seslendirme.
İzleyici yüz görmez; SES kanalın kimliğidir.

NE ARIYORUZ: net, güven veren, MERAK UYANDIRAN bir ANLATICI. Konuyu açıklayan,
hikâye anlatan bir ton. Satış/reklam tonu, aşırı enerjik sunucu tonu ya da
yapay/robotik ses UYMAZ — izleyici 3 saniyede kaydırır.

SESLER (voice_id | ad | cinsiyet | aksan | açıklama):
{liste}

SADECE JSON: {{"voice_id": "<listeden BİREBİR bir voice_id>",
  "reason": "<TÜRKÇE tek cümle: neden bu ses bu nişe uyuyor>"}}"""


def pick_voice(language: str, niche: str, *, voices: list[dict], llm) -> VoiceChoice:
    """Nişe en uygun ANLATICI sesi. LLM yoksa/patlarsa ilk ses + DÜRÜST gerekçe.

    Ses SEÇİMİ kanalı bozmaz, yalnız iyileştirir — burada durmaya gerek yok.
    (Hedef dilde ses OLMAMASI ise bozar; onu ``voices_for`` RuntimeError ile yakalıyor.)
    """
    if not voices:
        raise RuntimeError("ses listesi boş — seçilecek ses yok")

    ilk = voices[0]

    def _fallback(sebep: str) -> VoiceChoice:
        return VoiceChoice(voice_id=ilk["voice_id"],
                           name=str(ilk.get("name") or ilk["voice_id"]),
                           reason=sebep)

    if llm is None:
        return _fallback("model seçemedi (LLM yok) — listedeki ilk uygun ses")

    try:
        p = llm(_prompt(language, niche, voices), _Pick)
    except Exception as e:   # noqa: BLE001 — ses seçimi kanalı bozmaz
        log.warning(f"[ses] seçim başarısız ({e}) → ilk uygun ses")
        return _fallback(f"model seçemedi ({e}) — listedeki ilk uygun ses")

    esles = {v["voice_id"]: v for v in voices}
    v = esles.get((p.voice_id or "").strip())
    if v is None:
        # Model uydurma bir id verdi — kabul etmeyiz.
        log.warning(f"[ses] model listede olmayan id verdi ({p.voice_id!r}) → ilk ses")
        return _fallback("model listede yok bir ses önerdi — listedeki ilk uygun ses")

    return VoiceChoice(voice_id=v["voice_id"],
                       name=str(v.get("name") or v["voice_id"]),
                       reason=(p.reason or "").strip() or "modelin seçimi")
