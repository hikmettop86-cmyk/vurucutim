"""NexLev kanıtlanmış-konu madencisi: nişte patlamış shorts → konu bankası.

TIMEOUT NOTU: NexLev MCP köprüsü niş karmaşıklığına göre 4-9 dk sürebilir
(gerçek ölçüm: balinalar ~4dk OK, bilim-tarihi 300s'te timeout). Varsayılan
600s; daha kısası gerçek nişlerde zaman aşımı üretir.

``web/niche_finder.py`` deseninin aynası: headless ``claude`` CLI, allowed-tools
NexLev outlier araçlarıyla kısıtlı, ``run=subprocess.run`` testlerde enjekte
edilir. Üretim anında ÇAĞRILMAZ — panel düğmesi + haftalık cron doldurur,
üretim ``db.active_bank_topics`` okur.
"""
from __future__ import annotations

import json
import subprocess

from rapidfuzz import fuzz

_ALLOWED_TOOLS = ",".join([
    "mcp__claude_ai_NexLev__search_viral_videos_small_channels",
    "mcp__claude_ai_NexLev__youtube_channel_outliers",
    "mcp__claude_ai_NexLev__search_shorts_niche_finder_channels",
])

_DUP_THRESHOLD = 80   # aynı kanaldaki mevcut konuya fuzzy oran eşiği

_LANG_NAMES = {"tr": "Türkçe", "en": "İngilizce", "de": "Almanca",
               "es": "İspanyolca", "fr": "Fransızca"}


def _prompt(niche_query: str, count: int, lang: str) -> str:
    return f"""NexLev araçlarıyla şu nişte KÜÇÜK kanallarda PATLAMIŞ (outlier)
YouTube Shorts videolarını bul: "{niche_query}"

Küçük kanal + çok izlenme = kanıtlanmış konu. En güçlü {count} videoyu seç.
Her biri için SADECE şu JSON dizisini döndür (başka metin YOK):
[{{"topic": "<{lang} tek cümlelik konu fikri — bu konuda video üretilecek>",
  "source_title": "<orijinal video başlığı>",
  "views": <videonun izlenmesi, int>,
  "subs": <kanalın abone sayısı, int>,
  "hook_pattern": "<başlığın örüntüsü, {lang} 2-4 kelime, ör. 'sayı + beklenmedik iddia'>"}}]"""


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


def _parse_topics(text: str) -> list[dict]:
    """Ham çıktı → normalize kayıt listesi (eksik alan coercion, boş topic elenir)."""
    out = []
    for item in _extract_json_array(text):
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()
        if not topic:
            continue

        def _i(v):
            try:
                return int(str(v).replace(",", "").replace(".", "") or 0)
            except (ValueError, TypeError):
                return 0
        out.append({"topic": topic,
                    "source_title": str(item.get("source_title") or "").strip(),
                    "views": _i(item.get("views")), "subs": _i(item.get("subs")),
                    "hook_pattern": str(item.get("hook_pattern") or "").strip()})
    if not out:
        raise ValueError("geçerli konu kaydı çıkarılamadı")
    return out


def mine_topics(niche_query: str, *, language: str = "tr",
                claude_path: str = "claude", model: str | None = None,
                count: int = 12, timeout: int = 600,
                run=subprocess.run) -> list[dict]:
    """NexLev'den outlier shorts madenciliği. Hata → RuntimeError/ValueError."""
    niche_query = (niche_query or "").strip() or "ilginç bilgiler"
    lang = _LANG_NAMES.get(language, "Türkçe")
    cmd = [claude_path, "-p", _prompt(niche_query, int(count), lang),
           "--allowedTools", _ALLOWED_TOOLS,
           "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    try:
        proc = run(cmd, capture_output=True, text=True,
                   timeout=timeout, encoding="utf-8")
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"konu madenciliği zaman aşımına uğradı ({timeout}s)") from e
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
    return _parse_topics(result_text)


def refresh_topic_bank(eng, channel_slug: str, niche_query: str, *,
                       language: str = "tr", claude_path: str = "claude",
                       model: str | None = None, run=subprocess.run) -> dict:
    """mine → mevcut bankaya fuzzy-dedup → insert. {"added": N, "skipped_dup": M}."""
    from short_bot.db import all_bank_topics, insert_bank_topics
    mined = mine_topics(niche_query, language=language, claude_path=claude_path,
                        model=model, run=run)
    existing = [r["topic"] for r in all_bank_topics(eng, channel_slug)]
    fresh, dup = [], 0
    for r in mined:
        if any(fuzz.ratio(r["topic"].lower(), e.lower()) > _DUP_THRESHOLD
               for e in existing):
            dup += 1
            continue
        existing.append(r["topic"])   # aynı partide de tekrar önle
        fresh.append(r)
    insert_bank_topics(eng, channel_slug, fresh)
    return {"added": len(fresh), "skipped_dup": dup}
