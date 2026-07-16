"""Hibrit AI backend: merkezî fallback (claude_cli) + resolve_ai_call hybrid dalı.

Metin → Claude CLI, vision → Google Studio; birincil çökerse kayıtlı OpenRouter
fallback'ine tek deneme düşülür. Kayıt yoksa davranış birebir (eski modlar korunur).
"""
import pytest

import short_bot.claude_cli as CC


# ── claude_cli merkezî fallback registry ─────────────────────────────────────
def test_fallback_cli_yoksa_openrouter(monkeypatch):
    CC.clear_fallbacks()
    CC.register_fallback("claude_cli", "sonnet", "openrouter",
                         "anthropic/claude-sonnet-5", "or-key")
    seen = {}

    def fake_primary(prompt, *, backend, model, claude_path, api_key, timeout_s, image_path=None):
        if backend == "claude_cli":
            raise FileNotFoundError("claude yok")
        seen.update(backend=backend, model=model, api_key=api_key)
        return "OR CEVAP"

    monkeypatch.setattr(CC, "_invoke_primary", fake_primary)
    out = CC._invoke_raw("selam", backend="claude_cli", model="sonnet",
                         claude_path="claude", api_key=None, timeout_s=10)
    assert out == "OR CEVAP"
    assert seen == {"backend": "openrouter", "model": "anthropic/claude-sonnet-5",
                    "api_key": "or-key"}


def test_fallback_kayitsizken_hata_gecer(monkeypatch):
    CC.clear_fallbacks()

    def fake_primary(prompt, **k):
        raise FileNotFoundError("claude yok")

    monkeypatch.setattr(CC, "_invoke_primary", fake_primary)
    with pytest.raises(FileNotFoundError):   # kayıt yok → davranış birebir
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


def test_google_studio_dispatch_generate_cagirir(monkeypatch):
    CC.clear_fallbacks()
    import short_bot.google_studio as GS
    got = {}

    def gs_gen(prompt, *, model, image_path=None, timeout_s=90):
        got.update(prompt=prompt, model=model, image_path=image_path)
        return "TARIF"

    monkeypatch.setattr(GS, "generate", gs_gen)
    out = CC._invoke_primary("betimle", backend="google_studio", model="gemini-3.1-flash-lite",
                             claude_path="claude", api_key=None, timeout_s=45, image_path="f.jpg")
    assert out == "TARIF"
    assert got == {"prompt": "betimle", "model": "gemini-3.1-flash-lite", "image_path": "f.jpg"}


# ── resolve_ai_call hybrid dalı ──────────────────────────────────────────────
def _settings(**over):
    from short_bot.config import Settings
    base = dict(
        ffmpeg_path="ffmpeg", claude_cli_path="claude", playwright_browser="chromium",
        web_host="127.0.0.1", web_port=5005, fuzzy_dedup_threshold=0.85, log_level="INFO",
        claude_models={"dna": "opus", "default": "sonnet", "script": "sonnet", "vision": "default"},
        ai_backend="hybrid",
        openrouter_models={"dna": "anthropic/claude-opus-4.8",
                           "default": "anthropic/claude-sonnet-5",
                           "script": "anthropic/claude-sonnet-5",
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


def test_resolve_hybrid_metin_cli():
    from short_bot.config import resolve_ai_call
    CC.clear_fallbacks()
    s = _settings()
    txt = resolve_ai_call(s, {"openrouter_api_key": "or"}, "script")
    assert txt.backend == "claude_cli" and txt.model == "sonnet" and txt.api_key is None
    assert CC._FALLBACKS[("claude_cli", "sonnet")] == (
        "openrouter", "anthropic/claude-sonnet-5", "or")
    dna = resolve_ai_call(s, {"openrouter_api_key": "or"}, "dna")
    assert dna.backend == "claude_cli" and dna.model == "opus"
    assert CC._FALLBACKS[("claude_cli", "opus")] == (
        "openrouter", "anthropic/claude-opus-4.8", "or")


def test_resolve_openrouter_mode_bozulmadi():
    # Eski openrouter modu birebir korunmalı (regresyon).
    from short_bot.config import resolve_ai_call
    s = _settings(ai_backend="openrouter")
    c = resolve_ai_call(s, {"openrouter_api_key": "or"}, "script")
    assert c.backend == "openrouter" and c.model == "anthropic/claude-sonnet-5"
