"""Niş bulucu — iki mod.

**NexLev modu** (``find_niches``): panelin ``claude`` CLI'sini headless çağırır;
CLI'ye NexLev MCP bağlıysa Claude, canlı NexLev verisiyle (kârlı/büyüyen nişler,
outlier skoru, rakip kanallar) veri-destekli öneriler üretir. NexLev'e yalnızca
MCP/CLI üzerinden erişilebildiği için bu modun OpenRouter karşılığı yoktur.

**AI modu** (``find_niches_ai``): saf LLM beyin fırtınası (NexLev'siz). Önce Claude
CLI'yi Opus modeliyle dener (Claude aboneliği varsa); başarısızsa OpenRouter'a
düşer. Böylece Claude aboneliği olan da olmayan da kullanabilir.

Her iki mod da ~60-120 sn sürebildiği için çağıran taraf bunları arka planda
(daemon thread) çalıştırmalı. Saf/enjekte-edilebilir: NexLev modunda ``run``
(``subprocess.run`` yerine), AI modunda ``invoke`` (LLM çağrısı yerine) test için
değiştirilebilir.
"""
import json
import logging
import subprocess

_log = logging.getLogger("short_bot.web.niche_finder")

# Yalnızca shorts niş arama aracına izin ver — dar tutmak turleri/maliyeti azaltır.
_ALLOWED_TOOLS = "mcp__claude_ai_NexLev__search_shorts_niche_finder_channels"

# Dil kodu → prompt'ta kullanılacak dil adı (öneriler bu dilde üretilsin).
_LANG_NAMES = {
    "tr": "Türkçe", "en": "İngilizce", "de": "Almanca",
    "es": "İspanyolca", "fr": "Fransızca",
}


def _lang_name(language: str) -> str:
    return _LANG_NAMES.get((language or "tr").lower(), "Türkçe")


def _nexlev_prompt(query: str, count: int, lang: str) -> str:
    return (
        f"NexLev araçlarını kullanarak '{query}' temalı, footage-sürüklü (stok "
        f"görüntü + AI seslendirme) faceless YouTube Shorts için {count} kârlı niş "
        f"bul. {lang} dilinde içerik üretilecek; o dil pazarında rekabeti az "
        f"olanları tercih et. Niş adı, gerekçe ve konu tohumunu {lang} dilinde yaz. "
        f"SADECE şu biçimde bir JSON dizisi döndür; başka hiçbir şey yazma, markdown "
        f"kod bloğu KULLANMA:\n"
        '[{"nis":"kısa niş adı","neden":"veriye dayalı 1-2 cümlelik gerekçe '
        '(kanal/outlier/gelir sinyali)","konu_tohumu":"kanal üretiminde kullanılacak '
        'konu tohumu cümlesi"}]'
    )


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


def find_niches(query, *, language="tr", claude_path="claude", model=None,
                count=6, timeout=240, run=subprocess.run) -> list:
    """NexLev modu: Claude CLI + NexLev MCP ile veri-destekli öneriler.

    Dönüş: ``[{"nis":.., "neden":.., "konu_tohumu":..}, ...]``.
    Hata: ``RuntimeError`` (CLI yok/başarısız/zaman aşımı) / ``ValueError``
    (çıktı ayrıştırılamadı).
    """
    query = (query or "").strip() or "ilginç bilgiler, bilim ve doğa"
    prompt = _nexlev_prompt(query, int(count), _lang_name(language))
    cmd = [claude_path, "-p", prompt,
           "--allowedTools", _ALLOWED_TOOLS,
           "--output-format", "json"]
    if model:
        cmd += ["--model", model]

    try:
        proc = run(cmd, capture_output=True, text=True,
                   timeout=timeout, encoding="utf-8")
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"niş araması zaman aşımına uğradı ({timeout}s)") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"claude CLI bulunamadı: {claude_path}") from e

    if getattr(proc, "returncode", 1) != 0:
        stderr = (getattr(proc, "stderr", "") or "")[:300]
        raise RuntimeError(f"claude CLI hata (kod {proc.returncode}): {stderr}")

    try:
        envelope = json.loads(proc.stdout)
        result_text = envelope.get("result", "") if isinstance(envelope, dict) else proc.stdout
    except (ValueError, TypeError):
        result_text = proc.stdout or ""

    return _parse_niches(result_text)


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
