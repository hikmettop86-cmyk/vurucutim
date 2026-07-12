"""ai33.pro TTS istemcisi (ElevenLabs altyapılı aggregator).

Protokol (faceless-2'deki doğrulanmış akıştan):
  POST {base}/v3/text-to-speech   multipart: text, voice_id, speed  -> {task_id}
  GET  {base}/v1/task/{task_id}                                     -> {status, metadata:{audio_url}}
  GET  audio_url                                                    -> mp3 bytes
Auth: HTTP header  ``xi-api-key: <key>``  (Bearer değil).

Not: v3 endpoint ``model_id`` ve ``voice_settings`` KABUL ETMEZ; modeli
voice_id'nin prefix'i belirler. Timestamp de döndürmez — kelime senkronu
için ``short_bot.tts.align`` kullanılır.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

BASE_URL = "https://api.ai33.pro"

_VOICE_PREFIXES = ("elevenlabs_", "minimax_", "edge_", "kokoro_", "clone_")


def resolve_ai33_api_key(secrets: dict) -> str:
    """ai33 API anahtarını çöz. Env var AI33_API_KEY, secrets dict'i ezer."""
    return os.environ.get("AI33_API_KEY") or secrets.get("ai33_api_key") or ""


def normalize_voice_id(voice_id: str) -> str:
    """v3 provider-prefix'i zorunlu; ham id'ye 'elevenlabs_' eklenir."""
    v = (voice_id or "").strip()
    if not v:
        raise ValueError("voice_id boş olamaz")
    return v if v.startswith(_VOICE_PREFIXES) else f"elevenlabs_{v}"


POLL_INTERVAL_S = 4.0
POLL_TIMEOUT_S = 600.0     # 10 dk
POST_TIMEOUT_S = 60.0
TASK_TIMEOUT_S = 30.0
DOWNLOAD_TIMEOUT_S = 180.0
DOWNLOAD_RETRIES = 3       # ses hazır ama indirme kopabilir (10054) — kredi yanmasın


class Ai33Error(RuntimeError):
    """ai33 istemcisinin taban hatası."""


class Ai33AuthError(Ai33Error):
    """401 — geçersiz API anahtarı veya yetersiz kredi."""


class Ai33RateLimitError(Ai33Error):
    """429 — hız sınırı veya kuyruk dolu."""


class Ai33TimeoutError(Ai33Error):
    """poll zaman aşımı — kuyruk takılı (task 'done'/'error' vermeden süre doldu)."""


_STATUS_MESSAGES = {
    400: "geçersiz istek (voice_id veya text hatalı)",
    401: "geçersiz AI33_API_KEY veya yetersiz kredi",
    413: "istek çok büyük (>10MB)",
    422: "geçersiz parametre",
    429: "hız sınırı aşıldı veya kuyruk dolu",
}


def _check_status(resp, context: str) -> None:
    code = resp.status_code
    if 200 <= code < 300:
        return
    detail = _STATUS_MESSAGES.get(code) or f"HTTP {code}"
    msg = f"ai33 {context}: {detail}"
    if code == 401:
        raise Ai33AuthError(msg)
    if code == 429:
        raise Ai33RateLimitError(msg)
    raise Ai33Error(msg)


def _new_session():
    import requests
    return requests.Session()


def synthesize(
    text: str,
    *,
    voice_id: str,
    api_key: str,
    out_path: "Path",
    speed: float = 1.0,
    base_url: str = BASE_URL,
    session=None,
    sleep=time.sleep,
    now=time.monotonic,
    poll_interval_s: float = POLL_INTERVAL_S,
    poll_timeout_s: float = POLL_TIMEOUT_S,
) -> "Path":
    """Metni seslendirip mp3'ü ``out_path``'e yazar ve yolu döndürür.

    session/sleep/now testler için enjekte edilebilir.
    """
    if not (text or "").strip():
        raise ValueError("text boş olamaz")
    if not api_key:
        raise Ai33AuthError("AI33_API_KEY tanımlı değil")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Kendi açtığımız Session'ı kapatmak bizim sorumluluğumuz; enjekte edilene dokunma.
    owns_session = session is None
    sess = session or _new_session()
    headers = {"xi-api-key": api_key}

    try:
        resp = sess.post(
            f"{base_url}/v3/text-to-speech",
            headers=headers,
            files={
                "text": (None, text),
                "voice_id": (None, normalize_voice_id(voice_id)),
                "speed": (None, f"{speed:g}"),
            },
            timeout=POST_TIMEOUT_S,
        )
        _check_status(resp, "text-to-speech POST")
        task_id = (resp.json() or {}).get("task_id")
        if not task_id:
            raise Ai33Error("ai33 yanıtında task_id yok")

        start = now()
        while True:
            if now() - start > poll_timeout_s:
                raise Ai33TimeoutError(
                    f"ai33 poll timeout (~{poll_timeout_s / 60:.0f}dk), task={task_id}"
                )
            sleep(poll_interval_s)
            try:
                r = sess.get(f"{base_url}/v1/task/{task_id}", headers=headers,
                             timeout=TASK_TIMEOUT_S)
            except Exception:
                # Geçici ağ kopması (timeout/reset) poll'u DÜŞÜRMESİN — task sunucuda
                # işlemeye devam ediyor; üstteki poll_timeout_s guard'ı süreyi sınırlar.
                continue
            _check_status(r, "task poll")
            task = r.json() or {}
            status = task.get("status")
            if status == "done":
                meta = task.get("metadata") or {}
                url = (meta.get("audio_url") or meta.get("output_uri")
                       or task.get("output_uri") or task.get("audio_url"))
                if not url:
                    raise Ai33Error(f"ai33 task bitti ama ses URL'i yok (task={task_id})")
                # Ses SUNUCUDA hazır (kredi harcandı) — indirme sırasındaki tek bir
                # bağlantı kopması (10054/ChunkedEncoding) tüm üretimi düşürmesin.
                audio = None
                last_err: Exception | None = None
                for attempt in range(1, DOWNLOAD_RETRIES + 1):
                    try:
                        audio = sess.get(url, timeout=DOWNLOAD_TIMEOUT_S)
                        break
                    except Exception as e:
                        last_err = e
                        if attempt < DOWNLOAD_RETRIES:
                            sleep(2.0 * attempt)
                if audio is None:
                    raise Ai33Error(
                        f"ai33 ses indirme {DOWNLOAD_RETRIES} denemede de koptu "
                        f"(task={task_id}): {last_err}")
                _check_status(audio, "ses indirme")
                out_path.write_bytes(audio.content)
                return out_path
            if status == "error":
                raise Ai33Error(
                    f"ai33 task hatası: {task.get('error_message') or 'bilinmeyen hata'}"
                )
            # 'doing' | 'processing' | 'pending' → poll'a devam
    finally:
        if owns_session:
            sess.close()


HEALTH_TIMEOUT_S = 25.0
HEALTH_TEXT = "test bir iki"


def health_check(
    *,
    voice_id: str,
    api_key: str,
    tmp_dir: "Path",
    timeout_s: float = HEALTH_TIMEOUT_S,
    base_url: str = BASE_URL,
    session=None,
    sleep=time.sleep,
    now=time.monotonic,
) -> str:
    """Küçük bir TTS isteğiyle servisi yoklar. ASLA exception atmaz.

    Dönüş: 'healthy' | 'stalled' | 'auth' | 'no-key' | 'no-voice' | 'error'
    """
    if not api_key:
        return "no-key"
    if not (voice_id or "").strip():
        return "no-voice"
    probe = Path(tmp_dir) / "_ai33_health.mp3"
    try:
        synthesize(HEALTH_TEXT, voice_id=voice_id, api_key=api_key,
                   out_path=probe, base_url=base_url, session=session,
                   sleep=sleep, now=now,
                   poll_interval_s=1.0, poll_timeout_s=timeout_s)
    except Ai33AuthError:
        return "auth"
    except Ai33TimeoutError:
        return "stalled"
    except Ai33Error:
        return "error"
    except Exception:
        return "error"
    finally:
        probe.unlink(missing_ok=True)
    return "healthy"


def list_voices(
    *,
    api_key: str,
    provider: str = "elevenlabs",
    search: str = "",
    page: int = 1,
    page_size: int = 100,
    base_url: str = BASE_URL,
    session=None,
) -> list[dict]:
    """Ses kütüphanesini listeler. Hata durumunda boş liste döner (UI dostu)."""
    if not api_key:
        return []
    # Kendi açtığımız Session'ı kapatmak bizim sorumluluğumuz; enjekte edilene dokunma.
    owns_session = session is None
    sess = session or _new_session()
    try:
        r = sess.get(
            f"{base_url}/v3/voices",
            headers={"xi-api-key": api_key},
            params={"provider": provider, "search": search,
                    "page": page, "page_size": page_size},
            timeout=TASK_TIMEOUT_S,
        )
        _check_status(r, "voices")
        body = r.json() or {}
    except Exception:
        return []
    finally:
        if owns_session:
            sess.close()
    items = body.get("data") if isinstance(body, dict) else body
    return list(items or [])
