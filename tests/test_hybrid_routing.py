"""Hibrit AI backend: merkezî fallback (claude_cli) + resolve_ai_call hybrid dalı.

Metin → Claude CLI, vision → Google Studio; birincil çökerse kayıtlı OpenRouter
fallback'ine tek deneme düşülür. Kayıt yoksa davranış birebir (eski modlar korunur).
"""
import pytest

import short_bot.claude_cli as CC


# ── claude_cli merkezî fallback registry ─────────────────────────────────────
def test_cli_yoksa_hemen_openrouter(monkeypatch):
    # CLI KURULU DEĞİL (FileNotFoundError) → tekrar denemek anlamsız → hemen OR.
    CC.clear_fallbacks()
    CC.register_fallback("claude_cli", "sonnet", "openrouter",
                         "anthropic/claude-sonnet-5", "or-key")
    seen = {}
    calls = {"cli": 0}

    def fake_primary(prompt, *, backend, model, claude_path, api_key, timeout_s, image_path=None):
        if backend == "claude_cli":
            calls["cli"] += 1
            raise FileNotFoundError("claude yok")
        seen.update(backend=backend, model=model, api_key=api_key)
        return "OR CEVAP"

    monkeypatch.setattr(CC, "_invoke_primary", fake_primary)
    out = CC._invoke_raw("selam", backend="claude_cli", model="sonnet",
                         claude_path="claude", api_key=None, timeout_s=10)
    assert out == "OR CEVAP"
    assert calls["cli"] == 1     # FileNotFoundError → retry YOK, tek deneme sonra OR
    assert seen == {"backend": "openrouter", "model": "anthropic/claude-sonnet-5",
                    "api_key": "or-key"}


def test_cli_hang_israrla_retry_eder_or_a_dusmez(monkeypatch):
    # MALİYET ÖNCELİĞİ: CLI hang'inde OR'a DÜŞME → CLI'yi tekrar dene (pencere temizlenir,
    # ölçüldü: hang'den sonraki çağrı başarılı). İlk deneme takılır, ikinci başarılı → OR YOK.
    import subprocess
    CC.clear_fallbacks()
    CC.register_fallback("claude_cli", "sonnet", "openrouter",
                         "anthropic/claude-sonnet-5", "or-key")
    monkeypatch.setattr(CC.time, "sleep", lambda s: None)
    n = {"cli": 0, "or": 0}

    def fake_primary(prompt, *, backend, model, claude_path, api_key, timeout_s, image_path=None):
        if backend == "claude_cli":
            n["cli"] += 1
            if n["cli"] == 1:
                raise subprocess.TimeoutExpired("claude", timeout_s)   # ilk deneme takıldı
            return "CLI CEVAP"                                          # ikinci başarılı
        n["or"] += 1
        return "OR CEVAP"

    monkeypatch.setattr(CC, "_invoke_primary", fake_primary)
    out = CC._invoke_raw("x", backend="claude_cli", model="sonnet",
                         claude_path="claude", api_key=None, timeout_s=10)
    assert out == "CLI CEVAP"    # CLI'de kaldı
    assert n["cli"] == 2 and n["or"] == 0   # OR HİÇ tetiklenmedi


def test_cli_tum_denemeler_patlarsa_son_care_or(monkeypatch):
    # CLI 3 denemede de takılırsa (plan uzun süre doygun) → son çare OR (nadir).
    import subprocess
    CC.clear_fallbacks()
    CC.register_fallback("claude_cli", "sonnet", "openrouter",
                         "anthropic/claude-sonnet-5", "or-key")
    monkeypatch.setattr(CC.time, "sleep", lambda s: None)
    n = {"cli": 0}

    def fake_primary(prompt, *, backend, model, claude_path, api_key, timeout_s, image_path=None):
        if backend == "claude_cli":
            n["cli"] += 1
            raise subprocess.TimeoutExpired("claude", timeout_s)
        return "OR CEVAP"

    monkeypatch.setattr(CC, "_invoke_primary", fake_primary)
    out = CC._invoke_raw("x", backend="claude_cli", model="sonnet",
                         claude_path="claude", api_key=None, timeout_s=10)
    assert out == "OR CEVAP"
    assert n["cli"] == CC._CLI_MAX_ATTEMPTS   # tüm denemeler tükendi, sonra OR


def test_cli_hang_kayitsizken_hata_verir(monkeypatch):
    # Fallback yok + CLI hep patlıyor → son hatayı yükseltir (run_json yakalar).
    import subprocess
    CC.clear_fallbacks()
    monkeypatch.setattr(CC.time, "sleep", lambda s: None)

    def fake_primary(prompt, **k):
        raise subprocess.TimeoutExpired("claude", 10)

    monkeypatch.setattr(CC, "_invoke_primary", fake_primary)
    with pytest.raises(subprocess.TimeoutExpired):
        CC._invoke_raw("x", backend="claude_cli", model="sonnet",
                       claude_path="claude", api_key=None, timeout_s=10)


def test_google_studio_exhausted_fallback(monkeypatch):
    CC.clear_fallbacks()
    CC.register_fallback("google_studio", "gemini-3.1-flash-lite", "openrouter",
                         "google/gemma-4-26b-a4b-it", "or-key")
    import short_bot.google_studio as GS

    def gs_gen(prompt, **k):
        raise GS.GoogleStudioExhausted()

    monkeypatch.setattr(GS, "generate", gs_gen)
    monkeypatch.setattr("short_bot.openrouter_client.complete",
                        lambda prompt, **k: f"OR:{k['model']}")
    out = CC._invoke_raw("tarif", backend="google_studio", model="gemini-3.1-flash-lite",
                         claude_path="claude", api_key=None, timeout_s=10)
    assert out == "OR:google/gemma-4-26b-a4b-it"


def test_claude_cli_cagrilari_serilesir(monkeypatch):
    # KÖK NEDEN (canlı ölçüm): 3 eşzamanlı `claude -p` → 1'i 90sn timeout; seri → 4sn.
    # Max planı/CLI eşzamanlı çağrıda takılıyor → subprocess'ler serileşmeli (yalnız CLI).
    import concurrent.futures as cf
    import threading
    import time
    CC.clear_fallbacks()
    state = {"n": 0, "max": 0}
    slock = threading.Lock()

    def fake_run(cmd, **kw):
        with slock:
            state["n"] += 1
            state["max"] = max(state["max"], state["n"])
        time.sleep(0.05)
        with slock:
            state["n"] -= 1

        class R:
            returncode = 0
            stdout = "ok"
            stderr = ""
        return R()

    monkeypatch.setattr(CC, "_resolve_claude_binary", lambda p: "claude")
    monkeypatch.setattr(CC.subprocess, "run", fake_run)
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        outs = list(ex.map(lambda i: CC._invoke_primary(
            "x", backend="claude_cli", model="sonnet", claude_path="claude",
            api_key=None, timeout_s=10), range(4)))
    assert all(o == "ok" for o in outs)
    assert state["max"] == 1   # serileşti — asla 2+ eşzamanlı claude -p


def test_google_studio_dispatch_generate_cagirir(monkeypatch):
    CC.clear_fallbacks()
    import short_bot.google_studio as GS
    got = {}

    def gs_gen(prompt, *, model, image_path=None, timeout_s=90, max_tokens=1024):
        got.update(prompt=prompt, model=model, image_path=image_path,
                   max_tokens=max_tokens)
        return "TARIF"

    monkeypatch.setattr(GS, "generate", gs_gen)
    out = CC._invoke_primary("betimle", backend="google_studio", model="gemini-3.1-flash-lite",
                             claude_path="claude", api_key=None, timeout_s=45, image_path="f.jpg")
    assert out == "TARIF"
    assert got == {"prompt": "betimle", "model": "gemini-3.1-flash-lite",
                   "image_path": "f.jpg", "max_tokens": CC.TAVAN_GORSEL}


# ── resolve_ai_call hybrid dalı ──────────────────────────────────────────────
def _settings(**over):
    from short_bot.config import Settings
    base = dict(
        ffmpeg_path="ffmpeg", claude_cli_path="claude", playwright_browser="chromium",
        web_host="127.0.0.1", web_port=5005, fuzzy_dedup_threshold=0.85, log_level="INFO",
        claude_models={"dna": "opus", "default": "sonnet", "script": "sonnet", "vision": "default"},
        ai_backend="hybrid",
        openrouter_models={"dna": "anthropic/claude-opus-4.8",
                           "default": "google/gemini-3.1-flash-lite",
                           "script": "google/gemini-3.1-flash-lite",
                           "vision": "google/gemma-4-26b-a4b-it"},
        google_studio={"vision_model": "gemini-3.1-flash-lite"})
    base.update(over)
    return Settings(**base)


def test_resolve_hybrid_vision_google_studio():
    from short_bot.config import resolve_ai_call
    CC.clear_fallbacks()
    s = _settings()
    vis = resolve_ai_call(s, {"openrouter_api_key": "or"}, "vision")
    assert vis.backend == "google_studio" and vis.model == "gemini-3.1-flash-lite"
    assert CC._FALLBACKS[("google_studio", "gemini-3.1-flash-lite")] == (
        "openrouter", "google/gemma-4-26b-a4b-it", "or")


def test_resolve_hybrid_metin_openrouter_gemini():
    # ÖLÇÜLDÜ: metin → OR gemini-flash-lite (ucuz/hızlı/persona-sadık); CLI rate-limit thrash.
    from short_bot.config import resolve_ai_call
    CC.clear_fallbacks()
    s = _settings()
    txt = resolve_ai_call(s, {"openrouter_api_key": "or"}, "script")
    assert txt.backend == "openrouter" and txt.model == "google/gemini-3.1-flash-lite"
    assert txt.api_key == "or"                       # OR key doğrudan çağrıda
    default = resolve_ai_call(s, {"openrouter_api_key": "or"}, "default")
    assert default.backend == "openrouter" and default.model == "google/gemini-3.1-flash-lite"
    # DNA (nadir, yüksek bahis) → Sonnet 5
    dna = resolve_ai_call(s, {"openrouter_api_key": "or"}, "dna")
    assert dna.backend == "openrouter" and dna.model == "anthropic/claude-opus-4.8"


def test_resolve_openrouter_mode_bozulmadi():
    # Eski openrouter modu birebir korunmalı (regresyon).
    from short_bot.config import resolve_ai_call
    s = _settings(ai_backend="openrouter")
    c = resolve_ai_call(s, {"openrouter_api_key": "or"}, "script")
    assert c.backend == "openrouter" and c.model == "google/gemini-3.1-flash-lite"
