"""Niş bulucu — iki mod (NexLev bağımlılığı KALDIRILDI, 2026-07-12).

**Veri-destekli mod** (``find_niches_data``): LLM aday nişleri üretir
(``find_niches_ai`` ile), her aday YouTube Data API outlier KANITIYLA ölçülür
(``yt_outliers`` — küçük kanalda patlamış shorts sayısı/oranı) ve kanıta göre
sıralanır. LLM fikri üretir, YouTube verisi hakemlik eder. NexLev'in RPM/gelir
tahmini yoktur; aksiyon sinyali izlenme kanıtıdır.

**AI modu** (``find_niches_ai``): saf LLM beyin fırtınası. Önce Claude CLI'yi
Opus modeliyle dener (Claude aboneliği varsa); başarısızsa OpenRouter'a düşer.

Her iki mod da ~30-120 sn sürebildiği için çağıran taraf bunları arka planda
(daemon thread) çalıştırmalı. Saf/enjekte-edilebilir: ``invoke`` (LLM) ve
``http_get`` (YouTube API) test için değiştirilebilir.
"""
import json
import logging

_log = logging.getLogger("short_bot.web.niche_finder")

# Dil kodu → prompt'ta kullanılacak dil adı (öneriler bu dilde üretilsin).
_LANG_NAMES = {
    "tr": "Türkçe", "en": "İngilizce", "de": "Almanca",
    "es": "İspanyolca", "fr": "Fransızca",
}


def _lang_name(language: str) -> str:
    return _LANG_NAMES.get((language or "tr").lower(), "Türkçe")


def _ai_prompt(query: str, count: int, lang: str) -> str:
    return (
        f"Sen bir YouTube niş stratejistisin. '{query}' temasında, footage-sürüklü "
        f"(stok görüntü + AI seslendirme + karaoke altyazı) faceless YouTube Shorts "
        f"için {count} umut vaat eden niş fikri üret. {lang} dilinde içerik "
        f"üretilecek; o dil/pazar için uygun, izlenme potansiyeli yüksek ve çok "
        f"doymamış nişler seç. Niş adı, gerekçe ve konu tohumunu {lang} dilinde yaz. "
        f"SADECE şu biçimde bir JSON dizisi döndür; başka hiçbir şey yazma, markdown "
        f"kod bloğu KULLANMA:\n"
        '[{"nis":"kısa niş adı","neden":"neden umut vaat ettiğine dair 1-2 cümle",'
        '"konu_tohumu":"kanal üretiminde kullanılacak konu tohumu cümlesi"}]'
    )


def _extract_json_array(text: str) -> list:
    """Model çıktısından JSON diziyi çıkar (kod bloğu/önek metne dayanıklı)."""
    text = (text or "").strip()
    try:
        val = json.loads(text)
        if isinstance(val, list):
            return val
    except (ValueError, TypeError):
        pass
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            val = json.loads(text[start:end + 1])
            if isinstance(val, list):
                return val
        except (ValueError, TypeError):
            pass
    raise ValueError("model çıktısında JSON dizi bulunamadı")


def _normalize(raw: list) -> list:
    """Ham dict listesini {nis, neden, konu_tohumu} biçimine indirger."""
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        nis = str(item.get("nis") or item.get("name") or "").strip()
        neden = str(item.get("neden") or item.get("why") or "").strip()
        tohum = str(item.get("konu_tohumu") or item.get("topic") or "").strip()
        if nis and tohum:
            out.append({"nis": nis, "neden": neden, "konu_tohumu": tohum})
    return out


def _parse_niches(text: str) -> list:
    niches = _normalize(_extract_json_array(text))
    if not niches:
        raise ValueError("geçerli niş önerisi çıkarılamadı")
    return niches


def find_niches_data(query, *, language="tr", count=6, api_keys,
                     claude_path="claude", claude_model="opus",
                     openrouter_model=None, openrouter_key=None,
                     timeout=180, invoke=None, http_get=None) -> list:
    """Veri-destekli mod: LLM aday nişleri üretir, YouTube outlier kanıtı sıralar.

    Her aday nişin adıyla YouTube'da arama yapılır; küçük kanalda patlamış shorts
    sayısı + en iyi oran KANIT olarak "neden" alanına eklenir, nişler kanıt
    puanına (ilk 3 outlier oranının toplamı) göre sıralanır.

    Dönüş: ``[{"nis", "neden", "konu_tohumu", "kanit_puani"}, ...]``.
    Hata: ``RuntimeError`` (anahtar yok / LLM başarısız) — YouTube kotası dolarsa
    ``yt_outliers.QuotaExhausted`` yüzeye çıkar (net Türkçe mesajlı).
    """
    if not api_keys:
        raise RuntimeError("YouTube API anahtarı yok — Ayarlar → YouTube Data "
                           "API bölümünden anahtar ekleyin.")
    from short_bot.yt_outliers import QuotaExhausted, search_outlier_shorts
    cands = find_niches_ai(query, language=language, count=max(int(count), 6),
                           claude_path=claude_path, claude_model=claude_model,
                           openrouter_model=openrouter_model,
                           openrouter_key=openrouter_key, timeout=timeout,
                           invoke=invoke)
    scored = []
    for n in cands:
        try:
            rows = search_outlier_shorts(
                n["nis"], api_keys=api_keys, language=language, limit=10,
                min_views=10_000, max_subs=2_000_000, min_ratio=1.0,
                http_get=http_get)
        except QuotaExhausted:
            raise   # net kota mesajı kullanıcıya çıksın
        except Exception as e:  # noqa: BLE001 — tek nişin ölçümü listeyi bozmasın
            _log.info("niş kanıt ölçümü atlandı (%s): %s", n["nis"], e)
            rows = []
        score = round(sum(r["ratio"] for r in rows[:3]), 1)
        if rows:
            best = rows[0]
            kanit = (f"Kanıt: {len(rows)} outlier; en iyi {best['views']:,} izl / "
                     f"{best['subs']:,} abone ({best['ratio']:.0f}x).")
        else:
            kanit = "Kanıt: bu aramada outlier bulunamadı."
        scored.append({**n, "neden": f"{n['neden']} — {kanit}",
                       "kanit_puani": score})
    scored.sort(key=lambda x: x["kanit_puani"], reverse=True)
    return scored[:int(count)]


def _default_invoke(prompt, *, backend, model, claude_path, api_key, timeout_s):
    """LLM çağrısı için varsayılan: claude_cli._invoke_raw (backend'e göre yönlendirir)."""
    from short_bot import claude_cli
    return claude_cli._invoke_raw(
        prompt, backend=backend, model=model, claude_path=claude_path,
        api_key=api_key, timeout_s=timeout_s,
    )


def find_niches_ai(query, *, language="tr", count=6, claude_path="claude",
                   claude_model="opus", openrouter_model=None,
                   openrouter_key=None, timeout=180, invoke=None) -> list:
    """AI modu: saf LLM. Önce Claude CLI (Opus), başarısızsa OpenRouter fallback.

    En az bir backend başarılı olmalı; ikisi de olmazsa ``RuntimeError``.
    ``invoke`` test için enjekte edilebilir (bkz. ``_default_invoke`` imzası).
    """
    query = (query or "").strip() or "ilginç bilgiler, bilim ve doğa"
    prompt = _ai_prompt(query, int(count), _lang_name(language))
    invoke = invoke or _default_invoke

    errors = []
    # 1) Claude CLI (Opus) — Claude aboneliği varsa
    try:
        raw = invoke(prompt, backend="claude_cli", model=claude_model,
                     claude_path=claude_path, api_key=None, timeout_s=timeout)
        return _parse_niches(raw)
    except Exception as e:  # noqa: BLE001 — fallback'e düş
        errors.append(f"claude: {e}")
        _log.info("AI niş bulucu: claude CLI başarısız, OpenRouter deneniyor (%s)", e)

    # 2) OpenRouter fallback — anahtar + model varsa
    if openrouter_key and openrouter_model:
        try:
            raw = invoke(prompt, backend="openrouter", model=openrouter_model,
                         claude_path=claude_path, api_key=openrouter_key,
                         timeout_s=timeout)
            return _parse_niches(raw)
        except Exception as e:  # noqa: BLE001
            errors.append(f"openrouter: {e}")
    else:
        errors.append("openrouter: anahtar/model yok")

    raise RuntimeError("AI niş bulucu başarısız — " + " | ".join(errors))
