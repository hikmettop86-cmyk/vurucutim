"""MERAK MİMARİSİ: 3 aday senaryo -> rubrik yargıcı -> doktor turu.

Kullanıcı teşhisi (2026-07-16): videolar komik ama SÜRÜKLEYİCİ değil — hook
durdurmuyor, beat'ler arası 'sonra ne olacak?' çekişi yok, tepe 'vay be'
dedirtmiyor. Tek taslağı cilalamak sıkıcı taslağı cilalamaya mahkûm; ÇEŞİTLİLİK
+ SEÇİM iterasyonu yener: her adaya farklı merak iskeleti dayatılır, rubrik
tabanlı yargıç kazananı seçer, doktor yalnız somut şikâyetleri düzeltir.

Rubrik kaynağı: DiscoverNow mizah DNA analizi (manuel araştırma tarihçesi,
bkz. discovernow-mizah-dna) + anlatı ilk-ilkeleri (bilgi-boşluğu kuramı:
merak = izleyicinin bildiği ile bilmek istediği arasındaki açık; açık erken
kapanırsa izleme sebebi biter). Transkript tabanlı doğrulama DENENDİ
(2026-07-16, YouTube Data API) — kota dolu olduğu için eklenemedi; kota
açılınca rubrik gerçek transkript analiziyle zenginleştirilebilir.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# Her adaya BİR iskelet dayatılır — üç aday üç farklı merak stratejisi dener.
# (persona/çeşitleme reçetesi korunur; iskelet ÜSTÜNE biner.)
CURIOSITY_SKELETONS: list[tuple[str, str]] = [
    ("GİZEM-ÖNCE",
     "Hook somut ve spesifik bir SORU/GİZEM açar ('Bu balık neden herkesi "
     "korkutuyor?' gibi jenerik değil — 'Şu masum surat var ya, az sonra "
     "yapacağı şeye inanamayacaksın' tadında, SAHNEYE bağlı). Cevabı EN SONA "
     "SAKLA: her beat cevaba bir adım yaklaştırır ama YENİ bir mini-soru da "
     "açar. Cevap reveal beat'inden önce ASLA sızmaz."),
    ("TIRMANAN BAHİS",
     "Her beat bir öncekinden DAHA BÜYÜK bir iddia/tehlike/absürtlük kurar — "
     "'bu daha bir şey değil...' merdiveni. İzleyici her basamakta 'bundan "
     "büyüğü olamaz' der, sen bir üstünü koyarsın. Tepe = en büyük basamak; "
     "erken zirve YASAK (sonrası düşüş hissi verir)."),
    ("SAHTE ÇÖZÜM + TWIST",
     "İzleyiciye cevabı aldığını HİSSETTİR (bir beat sahte-çözüm gibi kapanır), "
     "sonra tepe onu TERS KÖŞE yapar — gerçek asıl o an açığa çıkar. Sahte "
     "çözüm inandırıcı olmalı; twist kliplerde GERÇEKTEN görünen bir şeyden "
     "doğmalı, uydurma olay YASAK."),
]

# Yargıcın puanlama rubriği. Kaynak: DiscoverNow DNA + anlatı ilk-ilkeleri.
RUBRIC = """PUANLAMA RUBRİĞİ (her aday için her maddeye 0-10):
1. AÇIK DÖNGÜ: hook somut/spesifik bir soru-gizem açıyor mu (jenerik 'bakın ne
   olacak' = 2 puan altı)? Cevap reveal beat'inden önce SIZINTI yapıyor mu?
   (sızıntı varsa bu madde en fazla 3)
2. BEAT-SONU KANCASI: her beat'in SON cümlesi sonraki beat'i merak ettiriyor mu
   (yeni mini-soru, tehdit, iddia)? Merakı SIFIRLAYAN (kapanan) beat sayısı
   kadar puan kır.
3. TIRMANIŞ: beat'ler yükseliyor mu — her biri öncekinden daha büyük
   iddia/tehlike/absürtlük? Düz sıralama (beat'ler yer değiştirse fark etmez)
   = 4 altı.
4. ÖDEME: tepe, hook'un açtığı soruyu GERÇEKTEN cevaplıyor mu ve cevap
   beklenenden İYİ mi (ters köşe/abartı)? Vaat ödenmiyorsa aday DİSKALİFİYE.
5. MİZAH YOĞUNLUĞU: benzetme/replik/patlama-cümle sıklığı; boş geçiş cümlesi
   ('bak şimdi', 'işin sırrı') başına puan kır.
6. GÖRÜNTÜ SADAKATİ: her beat kendi klibinin TARİFİNDE olan şeyi mi anlatıyor?
   Tarif dışı somut olay uyduran aday DİSKALİFİYE.
7. KLİŞE: yasak açılışlar ('Ula', 'bak hele', 'biliyor muydunuz') ya da
   birbirinin aynısı kalıplar varsa puan kır."""


# Aday prompt'una eklenen merak yönergesi + iskelet + yeni JSON alanları.
_CANDIDATE_ADDENDUM = """
=== MERAK MİMARİSİ (BU ADAYIN İSKELETİ: {etiket}) ===
{talimat}

EK ÇIKTI ALANLARI (JSON'a ekle — hepsi ZORUNLU):
  "open_question": hook'un açtığı merak sorusu, İZLEYİCİ DİLİYLE, EN FAZLA 45
    karakter (ekranda küçük çip olarak asılı kalacak; kısa + spesifik).
  "reveal_beat": cevabın GERÇEKTEN ödendiği beat'in indeksi (0-tabanlı).
    0 OLAMAZ (cevap hook'ta ödenmez) — genelde son ya da sondan bir önceki beat.
  "clip_order": beat'leri hangi kliplere yazdığın — beat i, KLİP clip_order[i]'yi
    anlatır. Her klip TAM BİR KEZ kullanılır (permütasyon). DRAMATURJİ SENİN
    ELİNDE: en çarpıcı klibi reveal beat'ine koy; clip_order[0] (hook'ta da
    görünecek klip) FRAGMAN olmalı, cevabı GÖSTEREN klip ASLA olmamalı.
NOT: 'Beat i klip i'yi anlatır' kuralı bu modda ŞÖYLE değişir: beat i,
clip_order[i] numaralı KLİBİN tarifini anlatır. Tarifte olmayan olay uydurmak
yine YASAK."""


def write_candidates(topic: str, clip_descriptions: list[str], *, channel,
                     seed: int = 0, invoke, target_duration_s=None) -> list:
    """3 iskeletle 3 paralel aday. Çöken aday düşürülür (fail-open).

    ``invoke``: (prompt, schema) -> FDDraftNarration (test enjeksiyonu / gerçek LLM).
    ``target_duration_s``: görüntü-önce efektif süre (klip sayısından); None → kanal hedefi.
    """
    from short_bot.reel_models import FDDraftNarration
    from short_bot.reel_narration import _fd_prompt
    base = _fd_prompt(topic, clip_descriptions, channel=channel, seed=seed,
                      target_duration_s=target_duration_s)

    def _one(i):
        etiket, talimat = CURIOSITY_SKELETONS[i]
        p = base + _CANDIDATE_ADDENDUM.format(etiket=etiket, talimat=talimat)
        try:
            return invoke(p, FDDraftNarration)
        except Exception as e:  # noqa: BLE001 — tek aday yarışı düşürmesin
            log.warning(f"  merak[aday {etiket}]: üretim çöktü ({e}) → düşürüldü")
            return None

    with ThreadPoolExecutor(max_workers=3) as ex:
        sonuclar = list(ex.map(_one, range(len(CURIOSITY_SKELETONS))))
    return [s for s in sonuclar if s is not None]


class JudgeVerdict(BaseModel):
    winner: int = Field(ge=0)
    scores: list[int] = Field(default_factory=list)   # aday başına toplam merak puanı
    complaints: list[str] = Field(default_factory=list, max_length=8)


def judge_scripts(candidates: list, *, topic: str, invoke):
    """Rubrikle yargıla → (kazanan_aday, verdict|None). Çökerse ilk aday (fail-open)."""
    if len(candidates) == 1:
        return candidates[0], None
    bolumler = []
    for i, c in enumerate(candidates):
        beats = "\n".join(f"    beat {j}: {b.text}" for j, b in enumerate(c.beats))
        bolumler.append(
            f"--- ADAY {i} ---\nhook: {c.hook}\nopen_question: {c.open_question}\n"
            f"reveal_beat: {c.reveal_beat}\n{beats}\nclose: {c.close}")
    prompt = (
        f"Konu: {topic}\n\nAşağıda aynı konu için yazılmış {len(candidates)} kısa "
        f"video senaryosu adayı var:\n\n" + "\n\n".join(bolumler) +
        f"\n\n{RUBRIC}\n\n"
        "GÖREV: Her adayı RUBRİĞE göre puanla, EN SÜRÜKLEYİCİ olanı seç. Kazanan "
        "için EN FAZLA 5 SOMUT şikâyet yaz (hangi beat, ne sorun, nasıl düzelir) — "
        "doktor turu yalnız bunları düzeltecek. Genel laf ('daha iyi olabilir') "
        "yazma; işaret et.\n"
        'SADECE JSON: {"winner": <indeks>, "scores": [aday başına 0-70 toplam], '
        '"complaints": ["...", ...]}')
    try:
        v = invoke(prompt, JudgeVerdict)
    except Exception as e:  # noqa: BLE001 — yargıç çökerse yarışma iptal, ilk aday
        log.warning(f"  merak[yargıç]: çöktü ({e}) → ilk aday kullanılıyor")
        return candidates[0], None
    if not (0 <= v.winner < len(candidates)):
        return candidates[0], v
    log.info(f"  merak[yargıç]: kazanan aday {v.winner} "
             f"(puanlar={v.scores}) şikâyet={len(v.complaints)}")
    return candidates[v.winner], v


def doctor_pass(winner, complaints: list[str], *, topic: str, invoke):
    """Kazananı YALNIZ yargıç şikâyetlerini düzelterek yeniden yazdır.

    Beat sayısı değişirse (klip bağı bozulur) ya da çağrı çökerse kazanan
    olduğu gibi kalır (fail-open)."""
    if not complaints:
        return winner
    from short_bot.reel_models import FDDraftNarration
    mevcut = winner.model_dump_json()
    liste = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(complaints))
    prompt = (
        f"Konu: {topic}\n\nAşağıdaki kısa video senaryosu bir yarışmayı kazandı "
        f"ama yargıcın SOMUT şikâyetleri var. YALNIZ bu şikâyetleri düzelt — "
        f"beat SAYISI, clip_order, konuşulmayan alanlar ve genel yapı AYNEN "
        f"kalsın. İyi olan cümleleri değiştirme.\n\nSENARYO (JSON):\n{mevcut}\n\n"
        f"ŞİKÂYETLER:\n{liste}\n\nDüzeltilmiş senaryoyu AYNI ŞEMADA, SADECE JSON "
        f"olarak döndür.")
    try:
        out = invoke(prompt, FDDraftNarration)
    except Exception as e:  # noqa: BLE001
        log.warning(f"  merak[doktor]: çöktü ({e}) → kazanan olduğu gibi")
        return winner
    if len(out.beats) != len(winner.beats):
        log.warning("  merak[doktor]: beat sayısını değiştirdi → kazanan olduğu gibi")
        return winner
    return out


def _fallback_single(topic, clip_descriptions, clip_queries, **kw):
    """Tüm adaylar çökerse: mevcut tek-çağrı yol (davranış = curiosity kapalı)."""
    from short_bot.reel_narration import write_footage_driven_narration
    return write_footage_driven_narration(topic, clip_descriptions, clip_queries, **kw)


def write_curious_narration(topic: str, clip_descriptions: list[str],
                            clip_queries: list[str], *, channel, seed: int = 0,
                            claude_path: str = "claude", model: str = "default",
                            backend: str = "claude_cli", api_key: str | None = None,
                            invoke=None, target_duration_s=None):
    """Yarışma hattı: 3 aday → yargıç → doktor → pinleme.

    Döner ``(ReelNarration, perm)`` — ``perm`` beat→orijinal-klip permütasyonu
    (çağıran fd_clips/descs/queries'i bununla yeniden dizer; kimlik = değişiklik yok).

    ``target_duration_s``: görüntü-önce efektif süre (teslim klip sayısından); senaryo
    o pencereye yazılır (loop yok). None → kanalın sabit hedefi (eski davranış).
    """
    from short_bot.claude_cli import run_json
    from short_bot.reel_narration import _pin_queries
    # timeout_s=75: CLI hang'i HIZLI yakala → OR'a düşmeden tekrar dene (rate penceresi
    # temizlensin). Varsayılan 180sn her hang'de 180sn yakıyordu; meşru merak çağrısı
    # (~4-60sn) 75'e sığar, gerçek hang (dakikalarca CLI-içi backoff) 75'te kesilip retry olur.
    inv = invoke or (lambda p, s: run_json(
        p, s, claude_path=claude_path, model=model, backend=backend,
        api_key=api_key, retries=2, timeout_s=75))

    adaylar = write_candidates(topic, clip_descriptions, channel=channel,
                               seed=seed, invoke=inv, target_duration_s=target_duration_s)
    if not adaylar:
        log.warning("  merak: TÜM adaylar çöktü → tek-çağrı yola düşülüyor")
        n = _fallback_single(topic, clip_descriptions, clip_queries,
                             channel=channel, seed=seed, claude_path=claude_path,
                             model=model, backend=backend, api_key=api_key,
                             target_duration_s=target_duration_s)
        return n, list(range(len(clip_queries)))

    kazanan, verdict = judge_scripts(adaylar, topic=topic, invoke=inv)
    if verdict is not None and verdict.complaints:
        kazanan = doctor_pass(kazanan, verdict.complaints, topic=topic, invoke=inv)
    # KELİME BÜTÇESİ (aslan dersi: prompt bütçesi yetmiyor, model 143 yazdı)
    from short_bot.reel_narration import _fd_enforce_budget
    kazanan = _fd_enforce_budget(kazanan, channel, topic, invoke=inv,
                                 target_duration_s=target_duration_s)

    n_beats = len(kazanan.beats)
    perm = list(kazanan.clip_order) if len(kazanan.clip_order) == n_beats \
        else list(range(n_beats))
    # Sorgular permütasyona göre pinlenir: beat i ↔ orijinal klip perm[i].
    permuted_queries = ([clip_queries[j] if j < len(clip_queries) else clip_queries[-1]
                         for j in perm] if clip_queries else [])
    narr = _pin_queries(kazanan, permuted_queries, topic)
    return narr, perm
