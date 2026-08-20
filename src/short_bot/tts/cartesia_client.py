"""Cartesia (Sonic) TTS istemcisi — ai33 ile aynı sözleşme, artı kelime zaman damgası.

Doğrulanmış API gerçekleri (2026-08-20, canlı; ayrıntı spec'te):
- Başlık ``Cartesia-Version: 2026-08-14`` + ``Authorization: Bearer``.
- ``POST /tts/sse`` + ``add_timestamps`` yalnız ``raw`` container verir → ham PCM
  (pcm_s16le 44100) WAV'a yazılır. Olaylar: ``chunk`` (base64), ``timestamps``
  (``word_timestamps: {words, start, end}``), ``done``. Böylece whisper hizalaması
  gereksiz: kelimeler sentezle birlikte gelir.
- Model kimliği duyuru adıyla AYNI DEĞİL: ``sonic-3.5`` kararlı; ``sonic-3.6`` → 404,
  ``sonic-2`` emekli (faceless-2 ölçtü). Model listesi ucu yok; adaylar 2 karakterle
  sınanır (yalnız düğmeyle — kredi harcar).
- ``generation_config.speed`` ∈ [0.6, 1.5], ``volume`` ∈ [0.5, 2.0]; aralık dışı 400.
- Kredi: 1 karakter = 1 kredi (Pro ses 1.5×). Her sentez loglanır ve aylık sayaç tutulur.
- Sağlık yoklaması ``GET /voices/<id>`` (kredi harcamaz) + isteğe bağlı 2 karakterlik
  model sınaması (``model_not_found`` yoklamada yakalansın diye).

Sert-dur: Cartesia başarısızsa başka sağlayıcıya DÜŞÜLMEZ — ses evreni farklı, kanalın
sesi sessizce değişmemeli. Çağıran (voiced.py) hatayı görür.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from short_bot.narration import TimedWord

log = logging.getLogger(__name__)

BASE_URL = os.environ.get("CARTESIA_BASE_URL", "https://api.cartesia.ai")
VERSION = os.environ.get("CARTESIA_VERSION", "2026-08-14")
DEFAULT_MODEL = "sonic-3.5"
KNOWN_MODELS: tuple[str, ...] = ("sonic-3.5", "sonic-3", "sonic-preview")
SPEED_RANGE = (0.6, 1.5)
VOLUME_RANGE = (0.5, 2.0)
SAMPLE_RATE = 44100
CHUNK_CHARS = 3000          # tek istek tavanı; aşarsa cümle sınırından bölünür
MIN_AUDIO_BYTES = 512       # bunun altı "istek reddedilmiş" sayılır
RETRY_DELAYS_S = (2.0, 4.0, 8.0)
MONTHLY_BUDGET_DEFAULT = 100_000   # $5 plan; panel yüzdeyi buna göre gösterir


class CartesiaError(RuntimeError):
    """Cartesia çağrısı başarısız (ayrıntı mesajda)."""


class CartesiaAuthError(CartesiaError):
    """Anahtar yok/geçersiz (401/403)."""


class CartesiaRateLimitError(CartesiaError):
    """429 — denemeler tükendi."""


class CartesiaTimeoutError(CartesiaError):
    """Ağ zaman aşımı."""


@dataclass(frozen=True)
class SynthesisResult:
    path: Path
    words: list[TimedWord] = field(default_factory=list)
    duration_s: float = 0.0
    chars_spent: int = 0


def resolve_cartesia_api_key(secrets: dict | None) -> str:
    """secrets.yaml ``cartesia_api_key`` → ortam ``CARTESIA_API_KEY`` → ``""``."""
    key = str((secrets or {}).get("cartesia_api_key") or "").strip()
    return key or os.environ.get("CARTESIA_API_KEY", "").strip()


def _headers(api_key: str) -> dict:
    return {"Cartesia-Version": VERSION, "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"}


def clamp_speed(v: float) -> tuple[float, bool]:
    """Hızı API aralığına kırp; ``(değer, kırpıldı_mı)``."""
    lo, hi = SPEED_RANGE
    k = min(hi, max(lo, float(v)))
    return k, k != float(v)


def clamp_volume(v: float) -> tuple[float, bool]:
    lo, hi = VOLUME_RANGE
    k = min(hi, max(lo, float(v)))
    return k, k != float(v)


# --- SSE ayrıştırma ---------------------------------------------------------------

def parse_sse(text: str) -> tuple[bytes, list[TimedWord]]:
    """``/tts/sse`` gövdesini (ham PCM, kelimeler) olarak ver. Saf; bozuk satırlar atlanır."""
    pcm = bytearray()
    words: list[TimedWord] = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        t = ev.get("type")
        if t == "chunk" and ev.get("data"):
            try:
                pcm.extend(base64.b64decode(ev["data"]))
            except (ValueError, TypeError):
                continue
        elif t == "timestamps":
            wt = ev.get("word_timestamps") or {}
            ws, ss, es = wt.get("words") or [], wt.get("start") or [], wt.get("end") or []
            for w, s, e in zip(ws, ss, es):
                try:
                    words.append(TimedWord(word=str(w), start_s=float(s), end_s=float(e), seg=0))
                except (TypeError, ValueError):
                    continue
        elif t == "error":
            raise CartesiaError(f"sse error: {str(ev)[:200]}")
    return bytes(pcm), words


def _split_text(text: str, limit: int | None = None) -> list[str]:
    """Cümle sınırından parçala (paragraf > cümle > boşluk > sert kesme)."""
    limit = limit or CHUNK_CHARS
    text = text.strip()
    if len(text) <= limit:
        return [text]
    out: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = -1
        for pat in (r"\n\n", r"[.!?…]['\")\]]?\s", r"\s"):
            ms = list(re.finditer(pat, window))
            if ms and ms[-1].end() >= limit * 0.5:
                cut = ms[-1].end()
                break
        if cut <= 0:
            cut = limit
        out.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        out.append(rest)
    return [p for p in out if p]


# --- sentez -----------------------------------------------------------------------

def _post_sse(body: dict, *, api_key: str, timeout_s: float, session=None, sleep=time.sleep) -> str:
    sess = session or requests
    last: Exception | None = None
    for attempt in range(len(RETRY_DELAYS_S) + 1):
        try:
            r = sess.post(f"{BASE_URL}/tts/sse", json=body, headers=_headers(api_key),
                          timeout=timeout_s, stream=True)
        except requests.Timeout as e:
            raise CartesiaTimeoutError(f"tts/sse zaman aşımı ({timeout_s:.0f}s)") from e
        except requests.RequestException as e:
            last = e
            if attempt < len(RETRY_DELAYS_S):
                sleep(RETRY_DELAYS_S[attempt])
                continue
            raise CartesiaError(f"tts/sse ağ hatası: {e}") from e
        status = getattr(r, "status_code", 200)
        if status in (401, 403):
            raise CartesiaAuthError(f"Cartesia reddetti (HTTP {status}): anahtar geçersiz ya da kredi bitmiş")
        if status == 429 or status >= 500:
            last = CartesiaError(f"HTTP {status}: {_body_text(r)[:200]}")
            if attempt < len(RETRY_DELAYS_S):
                sleep(RETRY_DELAYS_S[attempt])
                continue
            if status == 429:
                raise CartesiaRateLimitError("Cartesia 429 — denemeler tükendi")
            raise last
        if status >= 400:
            raise CartesiaError(f"tts/sse HTTP {status}: {_body_text(r)[:200]}")
        return _body_text(r)
    raise CartesiaError(f"tts/sse başarısız: {last}")


def _body_text(r) -> str:
    content = getattr(r, "content", None)
    if isinstance(content, bytes):
        return content.decode("utf-8", "replace")
    return str(getattr(r, "text", "") or "")


def synthesize(
    text: str,
    *,
    voice_id: str,
    api_key: str,
    out_path: Path,
    speed: float = 1.0,
    volume: float = 1.0,
    language: str = "tr",
    model: str = DEFAULT_MODEL,
    emotion: str = "",
    session=None,
    sleep=time.sleep,
    timeout_s: float = 180.0,
    usage_dir: Path | None = None,
) -> SynthesisResult:
    """Metni seslendirip WAV yazar; kelime zaman damgalarıyla döner.

    ``out_path`` uzantısı ne olursa olsun ``.wav`` yazılır ve DÖNEN yol kullanılmalı
    (voiced.py buna göre). ``emotion`` boş değilse transcript önüne yönerge olarak
    eklenir — model desteklemiyorsa yok sayılır, sese zarar vermez.
    """
    if not (text or "").strip():
        raise ValueError("text boş olamaz")
    if not api_key:
        raise CartesiaAuthError("CARTESIA_API_KEY tanımlı değil")
    if not (voice_id or "").strip():
        raise CartesiaError("voice_id boş")
    model = (model or DEFAULT_MODEL).strip()
    spd, spd_clipped = clamp_speed(speed)
    vol, vol_clipped = clamp_volume(volume)
    if spd_clipped:
        log.warning(f"  [cartesia] hız {speed} → {spd} (API aralığı {SPEED_RANGE})")
    if vol_clipped:
        log.warning(f"  [cartesia] ses seviyesi {volume} → {vol} (API aralığı {VOLUME_RANGE})")

    parts = _split_text(text)
    total_chars = sum(len(p) for p in parts)
    log.info(f"  [cartesia] {model} · {len(parts)} parça · {total_chars} karakter "
             f"≈ {total_chars} kredi (aylık {MONTHLY_BUDGET_DEFAULT // 1000}K'nın "
             f"%{100 * total_chars / MONTHLY_BUDGET_DEFAULT:.1f}'i)")

    pcm_all = bytearray()
    words_all: list[TimedWord] = []
    offset_s = 0.0
    for idx, part in enumerate(parts):
        transcript = f"{emotion.strip()} {part}" if emotion.strip() else part
        body = {
            "model_id": model,
            "transcript": transcript,
            "voice": {"mode": "id", "id": str(voice_id).strip()},
            "language": (language or "tr")[:2].lower(),
            "output_format": {"container": "raw", "encoding": "pcm_s16le",
                              "sample_rate": SAMPLE_RATE},
            "add_timestamps": True,
            "generation_config": {"speed": spd, "volume": vol},
        }
        raw = _post_sse(body, api_key=api_key, timeout_s=timeout_s, session=session, sleep=sleep)
        pcm, words = parse_sse(raw)
        if len(pcm) < MIN_AUDIO_BYTES:
            raise CartesiaError(
                f"ses gövdesi çok küçük ({len(pcm)} bayt) — istek reddedilmiş olabilir "
                f"(parça {idx + 1}/{len(parts)})")
        for w in words:
            words_all.append(TimedWord(word=w.word, start_s=w.start_s + offset_s,
                                       end_s=w.end_s + offset_s, seg=0))
        part_s = len(pcm) / 2 / SAMPLE_RATE
        offset_s += part_s
        pcm_all.extend(pcm)
        log.info(f"     {idx + 1}/{len(parts)} ✓ {len(part)} karakter · {part_s:.1f}s · {len(words)} kelime")

    out_path = Path(out_path).with_suffix(".wav")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(pcm_all))
    duration_s = len(pcm_all) / 2 / SAMPLE_RATE
    if not words_all:
        log.warning("  [cartesia] zaman damgası gelmedi — hizalama orantılı dağıtıma düşecek")
    if usage_dir is not None:
        record_usage(total_chars, cache_dir=usage_dir)
    log.info(f"  [cartesia] → {out_path.name} {duration_s:.1f}s, {len(words_all)} kelime, "
             f"{total_chars} kredi harcandı")
    return SynthesisResult(path=out_path, words=words_all, duration_s=duration_s,
                           chars_spent=total_chars)


# --- sağlık / modeller / sesler / klon -------------------------------------------

def health_check(*, voice_id: str, api_key: str, model: str = DEFAULT_MODEL,
                 probe_model: bool = True, session=None, timeout_s: float = 20.0,
                 tmp_dir: Path | None = None) -> str:
    """'healthy' | 'no-key' | 'no-voice' | 'auth' | 'voice-missing' | 'model' | 'error'.

    Ses GET'i kredi harcamaz. ``probe_model`` açıkken 2 karakterlik sentez (2 kredi)
    modelin gerçekten var olduğunu doğrular — faceless-2'de ses geçip sentez
    ``model_not_found`` verince yoklama yalan söylemişti.
    """
    if not api_key:
        return "no-key"
    if not (voice_id or "").strip():
        return "no-voice"
    sess = session or requests
    try:
        r = sess.get(f"{BASE_URL}/voices/{voice_id.strip()}", headers=_headers(api_key),
                     timeout=timeout_s)
    except requests.RequestException:
        return "error"
    st = getattr(r, "status_code", 200)
    if st in (401, 403):
        return "auth"
    if st == 404:
        return "voice-missing"
    if st >= 400:
        return "error"
    if probe_model:
        try:
            with tempfile.TemporaryDirectory(dir=str(tmp_dir) if tmp_dir else None) as td:
                synthesize("ok", voice_id=voice_id, api_key=api_key,
                           out_path=Path(td) / "probe.wav", model=model, session=sess,
                           timeout_s=timeout_s)
        except CartesiaAuthError:
            return "auth"
        except CartesiaError as e:
            if re.search(r"model_not_found|model_sunsetted", str(e)):
                return "model"
            return "error"
        except Exception:  # noqa: BLE001
            return "error"
    return "healthy"


HEALTH_MESSAGES_TR = {
    "healthy": "Cartesia hazır: anahtar, ses ve model doğrulandı.",
    "no-key": "Cartesia API anahtarı tanımlı değil (Ayarlar → API anahtarları).",
    "no-voice": "Ses seçilmemiş (voice_id boş).",
    "auth": "Cartesia reddetti: anahtar geçersiz ya da kredi bitmiş.",
    "voice-missing": "Bu voice_id Cartesia'da bulunamadı.",
    "model": f"Model geçersiz — ölçülmüş geçerli kimlikler: {', '.join(KNOWN_MODELS)}.",
    "error": "Cartesia şu an yanıt vermiyor.",
}


def probe_models(*, api_key: str, candidates: tuple[str, ...] = KNOWN_MODELS,
                 session=None) -> list[dict]:
    """Her adayı 2 karakterle sınar (kredi harcar → yalnız düğmeyle).
    Geçersiz bir ses kullanılır: ses reddi gelirse MODEL geçerlidir."""
    out: list[dict] = []
    for m in candidates:
        try:
            with tempfile.TemporaryDirectory() as td:
                synthesize("ok", voice_id="PROBE", api_key=api_key,
                           out_path=Path(td) / "p.wav", model=m, session=session, timeout_s=20)
            out.append({"id": m, "ok": True, "reason": ""})
        except CartesiaError as e:
            s = str(e)
            if re.search(r"model_not_found", s):
                out.append({"id": m, "ok": False, "reason": "yok"})
            elif re.search(r"model_sunsetted", s):
                out.append({"id": m, "ok": False, "reason": "emekli"})
            elif re.search(r"voice", s, re.I):
                out.append({"id": m, "ok": True, "reason": ""})
            else:
                out.append({"id": m, "ok": False, "reason": s[:60]})
    return out


def list_voices(*, api_key: str, language: str | None = "tr", q: str | None = None,
                limit: int = 100, session=None, timeout_s: float = 30.0) -> list[dict]:
    """``GET /voices`` — kredi harcamaz. Dil süzgeci ŞART: süzgeçsiz ilk 100 seste
    Türkçe HİÇ yok (ölçüldü). Hata → boş liste + log (UI kırılmaz)."""
    if not api_key:
        return []
    params: list[tuple[str, str]] = [("limit", str(max(1, min(100, int(limit)))))]
    if language and language != "*":
        params.append(("language", language[:2].lower()))
    if q:
        params.append(("q", q))
    params.append(("expand[]", "preview_file_url"))
    sess = session or requests
    try:
        r = sess.get(f"{BASE_URL}/voices", params=params, headers=_headers(api_key),
                     timeout=timeout_s)
        if getattr(r, "status_code", 200) >= 400:
            log.warning(f"[cartesia] voices HTTP {r.status_code}: {_body_text(r)[:120]}")
            return []
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        log.warning(f"[cartesia] voices başarısız: {e}")
        return []
    out = []
    for v in (data.get("data") or []):
        out.append({
            "voice_id": v.get("id", ""),
            "name": v.get("name") or v.get("id", ""),
            "description": v.get("description") or "",
            "language": v.get("language") or "",
            "gender": v.get("gender") or "",
            "is_owner": bool(v.get("is_owner")),
            "is_pro": bool(v.get("is_pro")),
            "preview_url": v.get("preview_file_url") or "",
        })
    return out


CLONE_EXTENSIONS = {".flac", ".mp3", ".mpeg", ".mpga", ".oga", ".ogg", ".wav", ".webm"}
CLONE_MAX_S = 10.0
CLONE_TARGET_S = 9.0
CLONE_SKIP_HEAD_S = 0.5


def _probe_seconds(path: Path, ffprobe: str) -> float | None:
    try:
        out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(path)], capture_output=True, text=True,
                             timeout=15, check=False).stdout.strip()
        return float(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def clone_voice(*, api_key: str, name: str, clip_path: Path, language: str,
                description: str = "", session=None, ffmpeg: str = "ffmpeg",
                ffprobe: str = "ffprobe", timeout_s: float = 180.0) -> tuple[str, bool]:
    """Instant clone → ``(voice_id, kırpıldı_mı)``. 10 sn tavanı: uzun klip 0.5-9.5 sn'ye
    yeniden kodlanarak kırpılır (mp3'te ``-c copy`` kare sınırına yuvarlıyor)."""
    if not api_key:
        raise CartesiaAuthError("CARTESIA_API_KEY tanımlı değil")
    clip_path = Path(clip_path)
    if not clip_path.exists():
        raise CartesiaError("ses dosyası bulunamadı")
    if clip_path.suffix.lower() not in CLONE_EXTENSIONS:
        raise CartesiaError(f"desteklenmeyen uzantı {clip_path.suffix}; "
                            f"izinli: {', '.join(sorted(CLONE_EXTENSIONS))}")
    trimmed = False
    send_path = clip_path
    secs = _probe_seconds(clip_path, ffprobe)
    tmp: Path | None = None
    if secs is not None and secs > CLONE_MAX_S:
        tmp = clip_path.with_name(f".cartesia-klip-{int(time.time())}{clip_path.suffix}")
        subprocess.run([ffmpeg, "-y", "-v", "error", "-ss", str(CLONE_SKIP_HEAD_S),
                        "-t", str(CLONE_TARGET_S), "-i", str(clip_path), str(tmp)],
                       check=True, timeout=60)
        send_path, trimmed = tmp, True
        log.info(f"[cartesia] klon klibi {secs:.1f}s → {CLONE_TARGET_S:.0f}s kırpıldı")
    sess = session or requests
    try:
        with open(send_path, "rb") as fh:
            r = sess.post(f"{BASE_URL}/voices/clone",
                          headers={"Cartesia-Version": VERSION, "Authorization": f"Bearer {api_key}"},
                          data={"name": name, "language": (language or "en")[:2].lower(),
                                "description": description, "access": "private"},
                          files={"clip": (send_path.name, fh)}, timeout=timeout_s)
    except requests.RequestException as e:
        raise CartesiaError(f"voices/clone ağ hatası: {e}") from e
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
    st = getattr(r, "status_code", 200)
    if st in (401, 403):
        raise CartesiaAuthError(f"Cartesia reddetti (HTTP {st})")
    if st >= 400:
        raise CartesiaError(f"voices/clone HTTP {st}: {_body_text(r)[:200]}")
    try:
        vid = str(r.json().get("id") or "")
    except ValueError:
        vid = ""
    if not vid:
        raise CartesiaError("voices/clone kimlik döndürmedi")
    return vid, trimmed


# --- kredi sayacı -----------------------------------------------------------------

def _usage_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / "cartesia_usage.json"


def _month_key(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def record_usage(chars: int, *, cache_dir: Path, now: datetime | None = None) -> int:
    """Aylık karakter sayacına ekle; yeni toplamı döndür. Dosya bozuksa sıfırdan başlar."""
    p = _usage_path(cache_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    key = _month_key(now)
    data[key] = int(data.get(key, 0)) + int(chars)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data[key]


def month_usage(cache_dir: Path, now: datetime | None = None) -> int:
    p = _usage_path(cache_dir)
    if not p.exists():
        return 0
    try:
        return int(json.loads(p.read_text(encoding="utf-8")).get(_month_key(now), 0))
    except (OSError, ValueError):
        return 0
