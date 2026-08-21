"""Rol başına sağlayıcı seçimi — `settings.ai_roles`.

NEDEN: `ai_backend` KABA bir anahtar. "Şablonu ücretsiz Google havuzunda yaz
ama sohbeti Claude CLI'da tut" demenin yolu yoktu. Ölçüldü (2026-08-21,
arketip şablonu yazma): claude_cli/opus 112,7 sn, google_studio/
gemini-3.5-flash-lite 7,0 sn (ücretsiz). Hangi rolün nereye gideceği
KULLANICININ kararı olmalı — kalite de aynı değil.

GERİYE UYUMLU: `ai_roles` boşsa eski `ai_backend` mantığı aynen çalışır.
"""
from __future__ import annotations

import pytest

from short_bot.config import load_settings, resolve_ai_call


def _ayar(tmp_path, ek: str = ""):
    p = tmp_path / "settings.yaml"
    p.write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: sonnet, script: sonnet}\n"
        "ai_backend: claude_cli\n"
        "openrouter_models: {dna: anthropic/claude-sonnet-5, default: google/gemini-3.1-flash-lite}\n"
        + ek, encoding="utf-8")
    return load_settings(p)


def test_ai_roles_YOKSA_eski_davranis(tmp_path):
    a = _ayar(tmp_path)
    assert a.ai_roles == {}
    c = resolve_ai_call(a, {}, "dna")
    assert c.backend == "claude_cli" and c.model == "opus"


def test_rol_bazli_saglayici_EZER(tmp_path):
    a = _ayar(tmp_path, "ai_roles:\n  dna: {provider: google_studio, "
                        "model: gemini-3.5-flash-lite}\n")
    c = resolve_ai_call(a, {}, "dna")
    assert c.backend == "google_studio" and c.model == "gemini-3.5-flash-lite"
    # Diğer roller etkilenmez.
    assert resolve_ai_call(a, {}, "script").backend == "claude_cli"


def test_openai_uyumlu_saglayici_ANAHTARINI_alir(tmp_path):
    a = _ayar(tmp_path, "ai_roles:\n  script: {provider: deepseek, model: deepseek-chat}\n")
    c = resolve_ai_call(a, {"deepseek_api_key": "sk-d"}, "script")
    assert c.backend == "deepseek" and c.model == "deepseek-chat"
    assert c.api_key == "sk-d"


def test_ucretsiz_yollar_anahtarsiz(tmp_path):
    a = _ayar(tmp_path, "ai_roles:\n  vision: {provider: google_studio, model: g}\n")
    assert resolve_ai_call(a, {}, "vision").api_key is None


def test_BILINMEYEN_saglayici_yok_sayilir(tmp_path):
    """Elle düzenlenmiş yaml kanalı kırmasın: bilinmeyen ad eski yola düşer."""
    a = _ayar(tmp_path, "ai_roles:\n  dna: {provider: uydurma, model: x}\n")
    assert resolve_ai_call(a, {}, "dna").backend == "claude_cli"


def test_MODEL_bossa_saglayicinin_ilk_ornegi(tmp_path):
    a = _ayar(tmp_path, "ai_roles:\n  dna: {provider: deepseek}\n")
    c = resolve_ai_call(a, {"deepseek_api_key": "k"}, "dna")
    assert c.model == "deepseek-chat"


def test_ai_roles_TUM_ROLLER_icin_okunur(tmp_path):
    from short_bot.ai_providers import ROLLER
    ek = "ai_roles:" + chr(10) + "".join(
        "  " + r + ": {provider: google_studio, model: gm-" + r + "}" + chr(10)
        for r, _ in ROLLER)
    a = _ayar(tmp_path, ek)
    for r, _ in ROLLER:
        c = resolve_ai_call(a, {}, r)
        assert c.backend == "google_studio" and c.model == "gm-" + r, r
