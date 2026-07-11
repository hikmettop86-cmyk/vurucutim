"""NexLev-destekli niş bulucu.

Panelin zaten kullandığı ``claude`` CLI'yi headless (``-p``) çağırır; CLI'ye
NexLev MCP bağlıysa Claude, canlı NexLev verisiyle (kârlı/büyüyen nişler, outlier
skoru, rakip kanallar) veri-destekli niş önerileri üretir. Çağrı ~60-120 sn
sürdüğü için çağıran taraf bunu arka planda (daemon thread) çalıştırmalı.

Saf ve enjekte-edilebilir: ``run`` parametresi test için ``subprocess.run``
yerine sahte bir fonksiyonla değiştirilebilir.
"""
import json
import logging
import subprocess

_log = logging.getLogger("short_bot.web.niche_finder")

# Yalnızca shorts niş arama aracına izin ver — dar tutmak turleri/maliyeti azaltır.
_ALLOWED_TOOLS = "mcp__claude_ai_NexLev__search_shorts_niche_finder_channels"

_PROMPT_TMPL = (
    "NexLev araçlarını kullanarak '{query}' temalı, footage-sürüklü (stok görüntü + "
    "AI seslendirme) faceless YouTube Shorts için {n} kârlı niş bul. Türkçe'de "
    "rekabeti az olanları tercih et. SADECE şu biçimde bir JSON dizisi döndür; "
    "başka hiçbir şey yazma, markdown kod bloğu KULLANMA:\n"
    '[{{"nis":"kısa niş adı","neden":"veriye dayalı 1-2 cümlelik gerekçe '
    '(kanal/outlier/gelir sinyali)","konu_tohumu":"kanal üretiminde kullanılacak '
    'Türkçe konu tohumu cümlesi"}}]'
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


def find_niches(query, *, claude_path="claude", model=None,
                count=6, timeout=240, run=subprocess.run) -> list:
    """Claude CLI + NexLev MCP ile veri-destekli niş önerileri döndür.

    Dönüş: ``[{"nis":.., "neden":.., "konu_tohumu":..}, ...]``.
    Hata durumunda ``RuntimeError`` (CLI yok/başarısız/zaman aşımı) ya da
    ``ValueError`` (çıktı ayrıştırılamadı) yükseltir.
    """
    query = (query or "").strip() or "ilginç bilgiler, bilim ve doğa"
    prompt = _PROMPT_TMPL.format(query=query, n=int(count))
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

    # Envelope: {"result": "<model metni>", ...}. Bozuksa ham stdout'a düş.
    try:
        envelope = json.loads(proc.stdout)
        result_text = envelope.get("result", "") if isinstance(envelope, dict) else proc.stdout
    except (ValueError, TypeError):
        result_text = proc.stdout or ""

    niches = _normalize(_extract_json_array(result_text))
    if not niches:
        raise ValueError("geçerli niş önerisi çıkarılamadı")
    return niches
