"""Kürate gem SIRALAMA: 'sıradan değil, MERAK/GÜLME uyandıran' klipleri öne çıkar.

İki kademe:
  1. engagement_score — upvote + YORUM ETKİLEŞİMİ (yorum/upvote oranı = 'tepki vermek
     zorunda kaldılar' = tartışma/merak) + yumuşak yön-bias. Eski salt-upvote×2.5-dikey
     sıralaması sevimli-sıradan dikey klipleri tepeye taşıyıp sarsıcı/tartışılan yatay
     klipleri gömüyordu (kullanıcı: 'hep sıradan videolar geliyor').
  2. score_curiosity — etkileşimle en iyi N adayın BAŞLIK + KAPAK KARESİ'ni vision ile
     'merak/gülme/şaşkınlık 1-10' skorla (google_studio ücretsiz havuz). Popülerlik
     değil İZLETME potansiyeli. final = engagement × (merak/5).
"""
from __future__ import annotations

import logging
import math
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from pydantic import BaseModel

log = logging.getLogger(__name__)

_UA = "vurucutim/1.0 (curated-rank)"


def engagement_score(gem: dict) -> float:
    """Upvote + yorum-etkileşimi + yön + süre → 'bize uygun' taban skoru (vision'sız)."""
    ups = float(gem.get("ups", 0) or 0)
    com = float(gem.get("comments", 0) or 0)
    # ETKİLEŞİM: yorum/upvote oranı 'tepki vermek zorunda kaldılar' sinyali. Tipik
    # ~0.01-0.02; yüksek-tartışma/merak ~0.03-0.06. 0.06'da tavan, +%36'ya kadar ödül.
    ratio = (com / ups) if ups > 0 else 0.0
    s = ups * (1.0 + 6.0 * min(ratio, 0.06))
    orient = gem.get("orient")
    if orient == "DİKEY":
        s *= 1.4      # dikey hâlâ hafif tercih (9:16'ya oturur) AMA yatayı gömmez
    elif orient == "yatay":
        s *= 0.9      # yatay: özne-farkında 9:16 kırpıyoruz → ceza küçük
    d = gem.get("duration") or 0
    if d and not (8 <= d <= 45):
        s *= 0.7      # çok kısa (loop) / çok uzun (sıkışma) → ideal 8-45s
    return s


class CuriosityScore(BaseModel):
    """Vision yargısı — klip merak/gülme/şaşkınlık uyandırır mı + TEMİZ görüntü mü."""
    score: int = 5           # 1 (sıradan/sıkıcı) .. 10 (kesin viral/çok merak uyandırıcı)
    has_text: bool = False   # kapakta gömülü yazı/altyazı/logo/watermark VAR mı (temiz değil)
    reason: str = ""


# Her iki skorlama promptuna eklenen TEMİZLİK sorusu — kullanıcı: 'altyazılı/yazılı/logolu
# olanları eleyelim, sadece temiz görüntü'. Kapak karesinde gömülü metin/logo tespiti (ucuz,
# thumbnail üzerinden); collect_pool has_text=True olanı havuza ALMAZ.
_CLEAN_LINE = (
    "AYRICA: kapak karesinde görüntüye SONRADAN BİNDİRİLMİŞ yazı / altyazı bandı / logo / "
    "watermark (TikTok, Instagram, @kullanıcı, gömülü başlık ya da altyazı) VAR mı? "
    "(Doğal sahne yazısı, tabela, forma numarası DEĞİL — editör/platform katmanı. "
    "Emin değilsen ve belirgin bir metin bloğu görüyorsan true.) → has_text.\n"
)


def _curiosity_prompt(title: str) -> str:
    return (
        "Bu bir kısa video klibinin BAŞLIĞI ve KAPAK KARESİ (thumbnail).\n"
        f"BAŞLIK: {title or '(başlık yok)'}\n\n"
        "Bu klip bir izleyicide MERAK ('bunu izlemeliyim'), KAHKAHA ya da ŞAŞKINLIK "
        "('vay be!') uyandırır mı? Yoksa SIRADAN / tahmin edilebilir / sıkıcı mı?\n"
        "Sevimli ama sıradan bir hayvan = DÜŞÜK. Beklenmedik, komik, akıl almaz, "
        "'nasıl yani?' dedirten an = YÜKSEK.\n"
        "1-10 puanla (10 = kesin viral/çok merak uyandırıcı, 1 = sıradan/sıkıcı).\n"
        + _CLEAN_LINE +
        'SADECE JSON: {"score": <1-10>, "has_text": <bool>, "reason": "<çok kısa>"}'
    )


def _emotion_prompt(title: str) -> str:
    """DUYGU kanalı skorlaması — duygusal DERİNLİK (@NedenHayvan: kurtarma AMA wholesome/
    minnet/kavuşma da). Yalnız kurtarmaya kilitlemek kanalı aç bırakıyordu (çoğu wholesome
    klip 3 puan alıp eleniyordu); sadece SEVİMLİ/KOMİK olan yine düşük (derp-koruması)."""
    return (
        "Bu bir kısa video klibinin BAŞLIĞI ve KAPAK KARESİ (thumbnail).\n"
        f"BAŞLIK: {title or '(başlık yok)'}\n\n"
        "Bu klip GÜÇLÜ bir DUYGUSAL/DOKUNAKLI ana dönüşebilir mi — izleyicinin içini "
        "ısıtan, gözünü dolduran, 'aaa' dedirten bir an? YÜKSEK sayılanlar:\n"
        "- Kurtarma / kahramanlık / fedakârlık / canını riske atma\n"
        "- Kavuşma / vefa / sadakat / birini bekleme, koruma\n"
        "- Şükran / minnet / nezaket (yardım edene teşekkür, karşılıksız iyilik anı)\n"
        "- Dokunaklı insan anı (kavuşma, mutluluk gözyaşı, sürpriz sevgi, wholesome an)\n"
        "DÜŞÜK sayılanlar: sadece SEVİMLİ ya da KOMİK ama duygusal derinliği/hikâyesi "
        "OLMAYAN (bir hayvanın komik düşmesi/zıplaması gibi), ya da duygusuz-teknik.\n"
        "1-10 puanla (10 = güçlü duygusal/dokunaklı, izleyiciyi duygulandırır; "
        "1 = duygusuz/sıradan/sadece komik).\n"
        + _CLEAN_LINE +
        'SADECE JSON: {"score": <1-10>, "has_text": <bool>, "reason": "<çok kısa>"}'
    )


def _karma_prompt(title: str) -> str:
    """KARMA ('oh olsun') kanalı skorlaması — kaba/haksız/pervasız birinin ANINDA hak ettiği
    TATMİN EDİCİ karşılığı. YÜKSEK = net 'buldu belasını' anı; DÜŞÜK = karma yok ya da CİDDİ
    zarar (o tatmin değil, rahatsız edici + platform-riskli)."""
    return (
        "Bu bir kısa video klibinin BAŞLIĞI ve KAPAK KARESİ (thumbnail).\n"
        f"BAŞLIK: {title or '(başlık yok)'}\n\n"
        "Bu klip TATMİN EDİCİ bir KARMA ('oh olsun / müstahak / buldu belasını') anına dönüşebilir "
        "mi — biri KABA / HAKSIZ / KURALSIZ / KİBİRLİ / kurnaz davranıp ANINDA hak ettiği karşılığı "
        "buluyor mu? YÜKSEK sayılanlar:\n"
        "- Fazla ukala/pervasız biri kendi hatasıyla rezil olur (kaykılır, tökezler, planı ters teper)\n"
        "- Kural tanımaz sürücü/kişi pervasızlığının SONUCUNU (hafif, kansız) yaşar\n"
        "- Dolandırıcı/hilekâr/zorba kendi kurduğu tuzağa düşer, yakalanır, utanır\n"
        "- Kurulan kibir/racon bir anda bozulur — izleyici 'oh be, müstahak' der\n"
        "DÜŞÜK sayılanlar (score 1-3): karma/hak ediş YOK (sadece kaza/şanssızlık, masum biri); "
        "ya da CİDDİ yaralanma/kan/şiddet/dövüş/çok tehlikeli sonuç (bu tatmin DEĞİL, rahatsız edici "
        "+ platform-riskli); ya da olayın kim-haklı-kim-haksız'ı belirsiz.\n"
        "1-10 puanla (10 = net kurulum[kaba davranış] + tatmin edici hafif comeuppance, kansız; "
        "1 = karma yok ya da ciddi zarar/masum kurban).\n"
        + _CLEAN_LINE +
        'SADECE JSON: {"score": <1-10>, "has_text": <bool>, "reason": "<çok kısa>"}'
    )


def _download_thumb(url: str, dest: Path) -> Path | None:
    if not url or not url.startswith("http"):
        return None
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=15)
        if r.status_code == 200 and r.content:
            dest.write_bytes(r.content)
            return dest
    except Exception:  # noqa: BLE001 — thumb inmezse başlıkla skorla
        return None
    return None


def score_curiosity(gems: list[dict], *, vision_call, top_n: int = 24,
                    workers: int = 6, tone: str = "mizah", drop_text: bool = True,
                    log=log) -> list[dict]:
    """Etkileşimle en iyi ``top_n`` adayı vision ile skorla → final sıra.

    ``tone``: 'mizah' → merak/gülme/şaşkınlık skoru; 'duygu' → kahramanlık/kurtarma/sadakat
    (duygusal potansiyel) skoru. Kanalın tonuna uygun klip seçilir (@NedenHayvan formülü).
    Her gem'e ``curiosity`` (1-10 ya da None) ve ``final_score`` yazar. Kuyruk yalnız
    engagement ile; vision yoksa/hata → engagement sırası (fail-open).

    ``drop_text=True`` (kullanıcı: 'yazılı/altyazılı/logolu olanları eleyelim, sadece temiz
    görüntü'): skorlanan kapaklarda gömülü metin/logo görülen (has_text) gem'ler SONUÇTAN
    ATILIR — havuz/autopilot/manuel arama hepsi temiz görüntü alır. Kuyruk (skorlanmamış)
    thumbnail'dan geçmediği için dokunulmaz."""
    from short_bot.claude_cli import run_json
    _prompt_fn = (_emotion_prompt if tone == "duygu"
                  else _karma_prompt if tone == "karma"
                  else _curiosity_prompt)

    ranked = sorted(gems, key=lambda g: -engagement_score(g))
    head = ranked[:top_n]
    tail = ranked[top_n:]

    if vision_call is None or not head:
        for g in ranked:
            g["curiosity"] = None
            g["final_score"] = engagement_score(g)
        return ranked

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        def _score(item):
            idx, gem = item
            try:
                img = _download_thumb(gem.get("thumb", ""), td / f"t{idx}.jpg")
                res = run_json(
                    _prompt_fn(gem.get("title", "")), CuriosityScore,
                    claude_path=vision_call.claude_path, model=vision_call.model,
                    backend=vision_call.backend, api_key=vision_call.api_key,
                    image_path=img, retries=1, timeout_s=30)
                return (max(1, min(10, int(res.score))), bool(res.has_text))
            except Exception as e:  # noqa: BLE001 — tek skor düşerse nötr, üretim sürsün
                log.info(f"  cevher[merak]: skor hatası ({e}) → nötr 5")
                return (5, False)     # hata → temiz varsay (fail-open, eleme yapma)

        try:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                scores = list(ex.map(_score, enumerate(head)))
        except Exception as e:  # noqa: BLE001
            log.info(f"  cevher[merak]: skorlama çöktü ({e}) → engagement sırası")
            scores = [(None, False)] * len(head)

    for g, (sc, has_text) in zip(head, scores):
        g["curiosity"] = sc
        g["has_text"] = has_text     # kapakta gömülü yazı/logo → collect_pool eler
        # MERAK BİRİNCİL (denetim bulgusu H2): eski 'engagement × merak/5' ÇARPIMINDA upvote
        # (~500-100k, 200× yayılım) merak'ı (10× yayılım) EZİYORDU → sıradan-viral güçlüyü
        # geçiyordu ('hep sıradan geliyor'). YENİ: merak (1-10, KALİTE) tam sayı-baskın terim;
        # log1p(engagement)/8 ∈ [0,~1.5] yalnız AYNI merak seviyesinde tiebreak. Böylece bir
        # merak farkını (1.0) hiçbir upvote uçurumu ezemez → kalite gerçekten yönetir.
        g["final_score"] = (sc if sc else 0) + math.log1p(engagement_score(g)) / 8.0
    for g in tail:                     # skorlanmayan kuyruk (rank 61+): merak yok → alt bant
        g["curiosity"] = None
        g["has_text"] = False
        g["final_score"] = math.log1p(engagement_score(g)) / 8.0

    out = sorted(ranked, key=lambda g: -g["final_score"])
    if drop_text:
        before = len(out)
        out = [g for g in out if not g.get("has_text")]
        dropped = before - len(out)
        if dropped:
            log.info(f"  cevher[temiz]: {dropped} yazılı/altyazılı/logolu kapak elendi")
    if any(g.get("curiosity") for g in head):
        top = out[0] if out else None
        if top:
            log.info(f"  cevher[merak]: {len(head)} aday skorlandı → en iyi "
                     f"'{top.get('title','')[:40]}' (merak={top.get('curiosity')})")
    return out
