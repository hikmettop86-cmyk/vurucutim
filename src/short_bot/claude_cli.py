"""Wrapper around `claude` CLI in headless (-p) mode. JSON-only output."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# ── Merkezî fallback kaydı ───────────────────────────────────────────────────
# hybrid modda resolve_ai_call her rol için birincil (backend, model) → OpenRouter
# fallback'i buraya kaydeder; _invoke_raw birincil çökünce TEK deneme fallback yapar.
# Böylece 36+ çağrı noktası DEĞİŞMEDEN düşme-yolu kazanır. Kayıt yoksa davranış
# birebir (eski claude_cli/openrouter modları korunur).
_FALLBACKS: dict = {}
_FALLBACKS_LOCK = threading.Lock()

# `claude -p` subprocess çağrılarını SERİLEŞTİR. ÖLÇÜLDÜ (2026-07-16 canlı): 3 eşzamanlı
# `claude -p` → en az 1'i 90sn timeout'a takılıyor (Max planı/CLI ~2 eşzamanlıyı kaldırıp
# 3.'yü asıyor); 3 seri → her biri ~4sn. Merak pipeline'ı 3 adayı paralel yazıyordu →
# timeout → OpenRouter fallback (senaryo fazı 573sn, %54). Serileştirme yalnız CLI'yi bağlar;
# google_studio vision (8-yollu) ve openrouter paralelliği ETKİLENMEZ.
_CLI_LOCK = threading.Lock()

# MALİYET ÖNCELİĞİ (kullanıcı direktifi 2026-07-16): OpenRouter neredeyse HİÇ tetiklenmemeli
# (API-bazlı, pahalı). CLI hang'i rate-limit kaynaklı ve GEÇİCİ — ÖLÇÜLDÜ: bir çağrı takılınca
# sonraki temizlenmiş pencerede başarılı (5 ardışıkta 1. takıldı, 2-5. hızlı). Bu yüzden CLI
# hang'inde OR'a DÜŞMEK YERİNE CLI tekrar denenir. OR yalnız CLI tüm denemelerde patlarsa
# (plan uzun süre doygun) ya da CLI KURULU DEĞİLSE — son çare, nadir.
_CLI_MAX_ATTEMPTS = 3

# `claude -p` @dosya ile iliştirilen görselin ÜST SINIRI. ÖLÇÜLDÜ (2026-07-24, aynı
# pano farklı sıkıştırmalarla): 239.437 bayt → 2/2 yanıt, 286.262 bayt → 0/2. Sınırın
# ÜSTÜNDE görsel SESSİZCE düşüyor: modele yalnız dosya YOLU gidiyor, o da ya boş/araç-
# çağrısı döndürüyor ya da metinden UYDURUP güvenli bir hüküm veriyor (short 1077:
# final QA "senkron ✓, skor 8" dedi, ekranda ise anlatımla alakasız fuaye vardı).
# Kör yargı sessiz olduğu için en tehlikeli arıza — bütçeyi aşanı küçültüyoruz.
CLI_IMAGE_MAX_BYTES = 262_144


def register_fallback(primary_backend: str, primary_model: str,
                      fb_backend: str, fb_model: str, fb_api_key: str | None) -> None:
    """(birincil backend, model) → (fallback backend, model, key) — idempotent."""
    with _FALLBACKS_LOCK:
        _FALLBACKS[(primary_backend, primary_model)] = (fb_backend, fb_model, fb_api_key)


def clear_fallbacks() -> None:
    """Kayıtları temizle (test yardımı / mod değişimi)."""
    with _FALLBACKS_LOCK:
        _FALLBACKS.clear()


class AIBackendError(RuntimeError):
    """AI motorlarının ortak hata tabanı (Claude CLI + OpenRouter)."""
    pass


class ClaudeCliError(AIBackendError):
    pass


class OpenRouterError(AIBackendError):
    pass


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
_FIRST_OBJ_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def _resolve_claude_binary(claude_path: str) -> str:
    """Resolve a bare 'claude' to an absolute path so subprocess.run on Windows
    can find npm `.cmd` shims (CreateProcess in shell=False mode does NOT honor
    PATHEXT for non-.exe shims unless given the full path).

    Strategy:
      1. If user already gave an absolute or qualified path → trust it as-is.
      2. shutil.which('claude') → respects PATHEXT, finds claude.cmd / .exe.
      3. Probe well-known npm-global / Anthropic install locations.
      4. Give up and return original; subprocess will raise FileNotFoundError
         which the caller turns into a ClaudeCliError with install hint.
    """
    if claude_path != "claude":
        return claude_path

    found = shutil.which("claude")
    if found:
        return found

    candidates = [
        os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd"),
        os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.exe"),
        os.path.join(os.environ.get("USERPROFILE", ""), ".local", "bin", "claude.exe"),
        os.path.join(os.environ.get("USERPROFILE", ""), ".local", "bin", "claude.cmd"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "claude", "claude.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c

    return claude_path


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty output")
    m = _CODE_FENCE_RE.search(raw)
    if m:
        return m.group(1)
    m = _FIRST_OBJ_RE.search(raw)
    if m:
        return m.group(1)
    return raw


def _invoke_raw(prompt: str, *, backend: str, model: str,
                claude_path: str, api_key: str | None, timeout_s: int,
                image_path: "Path | None" = None) -> str:
    """Birincil backend + kayıtlı fallback (TEK deneme). Kayıt yoksa davranış birebir.

    claude_cli için: hang'de OR'a düşmeden CLI tekrar denenir (maliyet önceliği; bkz.
    _CLI_MAX_ATTEMPTS notu). google_studio/openrouter için: birincil + tek fallback denemesi.
    Kayıt yoksa hata yükseltilir (run_json onu yakalar, FileNotFoundError mesajını korur)."""
    fb = _FALLBACKS.get((backend, model))
    if backend == "claude_cli":
        return _invoke_cli_with_retry(prompt, model=model, claude_path=claude_path,
                                      api_key=api_key, timeout_s=timeout_s,
                                      image_path=image_path, fb=fb)
    try:
        return _invoke_primary(prompt, backend=backend, model=model,
                               claude_path=claude_path, api_key=api_key,
                               timeout_s=timeout_s, image_path=image_path)
    except Exception as e:   # noqa: BLE001 — her başarısızlık fallback adayı
        if fb is None:
            raise
        fb_backend, fb_model, fb_key = fb
        _why = f"{type(e).__name__}" + (f": {e}" if str(e) else "")
        log.warning(f"fallback: {backend}/{model} -> {fb_backend}/{fb_model} ({_why})")
        return _invoke_primary(prompt, backend=fb_backend, model=fb_model,
                               claude_path=claude_path, api_key=fb_key,
                               timeout_s=timeout_s, image_path=image_path)


def _invoke_cli_with_retry(prompt: str, *, model: str, claude_path: str,
                           api_key: str | None, timeout_s: int, image_path, fb) -> str:
    """CLI hang'inde OR'a DÜŞME → CLI'yi tekrar dene (rate penceresi temizlenir; ölçüldü).
    OR yalnız CLI tüm denemelerde patlar (plan uzun doygun) ya da CLI kurulu değilse — son çare.

    ``fb``: (fb_backend, fb_model, fb_key) ya da None."""
    last: Exception | None = None
    for attempt in range(1, _CLI_MAX_ATTEMPTS + 1):
        try:
            return _invoke_primary(prompt, backend="claude_cli", model=model,
                                   claude_path=claude_path, api_key=api_key,
                                   timeout_s=timeout_s, image_path=image_path)
        except FileNotFoundError as e:
            last = e
            break   # CLI KURULU DEĞİL → tekrar denemek anlamsız, son çareye (OR) geç
        except (subprocess.TimeoutExpired, ClaudeCliError) as e:
            last = e   # hang / geçici hata (rate-limit) → tekrar dene
            if attempt < _CLI_MAX_ATTEMPTS:
                log.info(f"claude cli deneme {attempt}/{_CLI_MAX_ATTEMPTS} takıldı "
                         f"({type(e).__name__}) → OR'a düşmeden tekrar deneniyor")
                time.sleep(min(2 * attempt, 8))
    # Buraya: CLI tüm denemelerde patladı ya da kurulu değil → son çare OR (nadir).
    if fb is not None:
        fb_backend, fb_model, fb_key = fb
        log.warning(f"son çare fallback: claude_cli/{model} -> {fb_backend}/{fb_model} "
                    f"({type(last).__name__ if last else '?'}) — {_CLI_MAX_ATTEMPTS} CLI denemesi tükendi")
        return _invoke_primary(prompt, backend=fb_backend, model=fb_model,
                               claude_path=claude_path, api_key=fb_key,
                               timeout_s=timeout_s, image_path=image_path)
    if last is not None:
        raise last
    raise ClaudeCliError("claude cli tüm denemelerde başarısız")


@contextmanager
def _attachable_image(image_path: "Path"):
    """Görseli CLI'nin iliştirebileceği boyuta indir (gerekiyorsa) ve yolunu ver.

    Bütçe altındaysa dosyaya DOKUNULMAZ. Üstündeyse kalite düşürülerek, gerekirse
    küçültülerek geçici bir kopya üretilir. İndirilemiyorsa hata: kör yargı
    (bkz. CLI_IMAGE_MAX_BYTES) sessizce yanlış karar ürettiği için gönderilmez.
    """
    import tempfile
    src = Path(image_path)
    if src.stat().st_size <= CLI_IMAGE_MAX_BYTES:
        yield src
        return
    try:
        from PIL import Image
    except Exception as e:  # noqa: BLE001 — PIL yoksa küçültemeyiz
        raise ClaudeCliError(
            f"görsel {src.stat().st_size} bayt > {CLI_IMAGE_MAX_BYTES} sınırı ve "
            f"küçültülemiyor (PIL yok) → CLI onu sessizce düşürürdü") from e
    # MERDİVEN HEDEFE ULAŞANA KADAR İNER. Eski sabit liste (70/1.0 … 35/0.65) büyük ya da
    # GÜRÜLTÜLÜ (JPEG'in sıkıştıramadığı) kapakları sınıra indiremiyordu ve çağıran adayı
    # KÖR skorluyordu — gerçek koşu 1314/1327: 'cevher[merak]: skor hatası (görsel 262144
    # bayt sınırına indirilemedi) → nötr 5'. Yargısız aday sabit 5 puan alınca merak
    # sıralaması o adaylar için anlamsızlaşıyor, zayıf klip güçlünün önüne geçebiliyor.
    # Önce kaliteyi düşür (detay korunur), yetmezse ölçeği kademeli kır; 256KB'a sığmayan
    # bir kapak pratikte yok. Yine de sığmazsa hata TEŞHİS EDİLEBİLİR olsun (boyutlar).
    steps = ((70, 1.0), (55, 1.0), (45, 1.0), (45, 0.8), (35, 0.65), (35, 0.5),
             (30, 0.4), (25, 0.3), (25, 0.2))
    with tempfile.TemporaryDirectory() as td:
        son = 0
        with Image.open(src) as im:
            im = im.convert("RGB")
            for quality, shrink in steps:
                fitted = Path(td) / "fitted.jpg"
                out = (im if shrink == 1.0 else
                       im.resize((max(64, int(im.width * shrink)),
                                  max(64, int(im.height * shrink)))))
                out.save(fitted, "JPEG", quality=quality)
                son = fitted.stat().st_size
                if son <= CLI_IMAGE_MAX_BYTES:
                    log.info(f"görsel {src.stat().st_size}→{son} bayt "
                             f"(q={quality}, ölçek={shrink}) — CLI sınırına indirildi")
                    yield fitted
                    return
        raise ClaudeCliError(
            f"görsel {CLI_IMAGE_MAX_BYTES} bayt sınırına indirilemedi → gönderilmiyor "
            f"(kör yargı yerine hata). kaynak={src.stat().st_size} bayt, "
            f"en küçük deneme={son} bayt (q=25, ölçek=0.2)")


def _invoke_primary(prompt: str, *, backend: str, model: str,
                    claude_path: str, api_key: str | None, timeout_s: int,
                    image_path: "Path | None" = None) -> str:
    """Tek-atış ham çıktı (fallback YOK). google_studio → havuz; claude_cli →
    subprocess; openrouter → HTTP. FileNotFoundError ve TimeoutExpired'i (claude_cli)
    yukarıya bırakır; diğer hatalarda ilgili *Error fırlatır."""
    if backend == "google_studio":
        from short_bot import google_studio   # fonksiyon-içi import → circular önler
        return google_studio.generate(prompt, model=model, image_path=image_path,
                                      timeout_s=timeout_s)
    if backend == "openrouter":
        from short_bot import openrouter_client   # fonksiyon-içi import → circular önler
        return openrouter_client.complete(prompt, model=model,
                                          api_key=api_key, timeout_s=timeout_s,
                                          image_path=image_path)
    resolved_path = _resolve_claude_binary(claude_path)
    if image_path is not None:
        # Bütçeyi aşan görsel CLI'ye ULAŞMAZ (sessizce düşer) → önce sığdır.
        with _attachable_image(image_path) as fitted:
            return _run_cli(resolved_path, model, timeout_s,
                            f"@{fitted.absolute().as_posix()}\n\n{prompt}")
    return _run_cli(resolved_path, model, timeout_s, prompt)


def _run_cli(resolved_path: str, model: str, timeout_s: int, effective_prompt: str) -> str:
    # LEAN çağrı: `claude -p` normalde HER çağrıda tüm Claude Code ortamını bootstrap eder
    # (MCP sunucuları — NexLev 80+ araç, Chrome, Gmail; CLAUDE.md/skills/plugins/hooks; built-in
    # araçlar). Bizim kullanım saf metin→JSON üretimi; HİÇBİRİNE ihtiyaç yok. Bu bootstrap
    # 6-100sn boşa startup + timeout/varyans kaynağıydı (ölçüldü: MCP'siz ~10sn→4sn). Aşağıdaki
    # bayraklar startup'ı keser → çağrı hızlanır, tek-denemede-geçme oranı artar. Auth ayrı
    # saklandığı için etkilenmez (ölçüldü: --setting-sources '' ile de rc=0).
    cmd = [resolved_path, "-p", "--output-format", "text",
           "--strict-mcp-config",       # MCP sunucularını yükleme (--mcp-config yok → sıfır sunucu)
           "--setting-sources", ""]     # user/project/local ayar (CLAUDE.md/skills/hooks) yükleme
    if model != "default":
        cmd += ["--model", model]
    cmd += ["--tools", ""]              # built-in araçları devre dışı (variadic → EN SONA)
    # Serileştir: eşzamanlı `claude -p` takılıyor (bkz. _CLI_LOCK notu). Kilit yalnız
    # subprocess boyunca tutulur; timeout süresi kadar (nadiren) diğer CLI çağrıları bekler.
    with _CLI_LOCK:
        proc = subprocess.run(cmd, input=effective_prompt, capture_output=True, text=True,
                              encoding="utf-8", timeout=timeout_s, check=False)
    if proc.returncode != 0:
        raise ClaudeCliError(f"claude exit {proc.returncode}: {proc.stderr[:500]}")
    return proc.stdout


def run_json(
    prompt: str,
    schema: type[T],
    *,
    claude_path: str = "claude",
    model: str = "default",
    backend: str = "claude_cli",
    api_key: str | None = None,
    retries: int = 2,
    timeout_s: int = 180,
    image_path: "Path | None" = None,
) -> T:
    """Prompt'u backend'e gönder, çıktıyı JSON olarak parse edip schema ile doğrula.

    backend: "claude_cli" (varsayılan, `claude -p`) | "openrouter" (HTTP).
    api_key: yalnızca backend="openrouter" için gerekli.
    image_path: görsel dosya yolu; claude_cli'da @path prepend, openrouter'da forward.
    """
    last_error: Exception | None = None
    retry_feedback: str = ""

    for attempt in range(1, retries + 1):
        current_prompt = prompt + retry_feedback if retry_feedback else prompt
        try:
            raw = _invoke_raw(current_prompt, backend=backend, model=model,
                              claude_path=claude_path, api_key=api_key,
                              timeout_s=timeout_s, image_path=image_path)
        except FileNotFoundError as e:
            raise ClaudeCliError(
                f"claude binary not found at {claude_path!r}. "
                f"Install Claude Code CLI or set claude_cli_path in config/settings.yaml."
            ) from e
        except (subprocess.TimeoutExpired, AIBackendError) as e:
            last_error = e
            retry_feedback = ""
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

        try:
            payload = _extract_json(raw)
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                # LLM bazen JSON'dan SONRA açıklama/ikinci-obje ekliyor ("Extra data:
                # line N" — ölçüldü, mizah senaryosu 3/3 denemede böyle patladı).
                # İlk TAM JSON objesini kurtar; sonrasını yok say.
                data, _ = json.JSONDecoder().raw_decode(payload.lstrip())
            return schema.model_validate(data)
        except (ValueError, json.JSONDecodeError, ValidationError) as e:
            last_error = e
            retry_feedback = (
                "\n\n---\nPREVIOUS ATTEMPT WAS REJECTED WITH ERROR:\n"
                f"{e}\n"
                "Please fix this error and return ONLY valid JSON, no other text."
            )
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

    err_cls = OpenRouterError if backend == "openrouter" else ClaudeCliError
    raise err_cls(f"run_json failed after {retries} attempts: {last_error}")
