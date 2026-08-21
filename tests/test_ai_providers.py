"""Sağlayıcı kaydı ve OpenAI-uyumlu istemci.

NEDEN TEK KAYIT: sağlayıcı bilgisi eskiden `resolve_ai_call`, `_invoke_primary`
ve ayarlar şablonuna dağılmıştı; yeni sağlayıcı eklemek üç yeri birden
düzenlemek demekti ve biri unutulunca SESSİZCE eski sağlayıcıya düşülüyordu.
"""
from __future__ import annotations

import pytest

from short_bot.ai_providers import (ROLLER, SAGLAYICILAR, gerekli_anahtar,
                                    gorsel_saglayicilar, openai_uyumlu,
                                    saglayici)


def test_ozel_yollu_saglayicilarin_base_url_u_YOK():
    """claude_cli/google_studio/openrouter kendi istemcilerini kullanıyor;
    base_url dolarsa OpenAI-uyumlu sanılıp yanlış istemciye gider."""
    for ad in ("claude_cli", "google_studio", "openrouter"):
        assert not SAGLAYICILAR[ad].base_url, ad
        assert not openai_uyumlu(ad), ad


@pytest.mark.parametrize("ad", ["deepseek", "qwen", "openai", "modelscope",
                                "groq", "nvidia"])
def test_openai_uyumlular_TAM_tanimli(ad):
    s = SAGLAYICILAR[ad]
    assert openai_uyumlu(ad)
    assert s.base_url.startswith("https://") and s.base_url.endswith("/chat/completions")
    assert s.gizli_anahtar, f"{ad} için secrets alan adı yok"
    assert s.ornek_modeller, f"{ad} için örnek model yok"


def test_anahtar_gerektirmeyenler():
    """Ücretsiz yollar anahtar İSTEMEZ: CLI abonelikte, havuz kendi dosyasında."""
    assert gerekli_anahtar("claude_cli") == ""
    assert gerekli_anahtar("google_studio") == ""
    assert SAGLAYICILAR["claude_cli"].ucretsiz
    assert SAGLAYICILAR["google_studio"].ucretsiz


def test_gorsel_destekleyenler():
    g = set(gorsel_saglayicilar())
    assert {"claude_cli", "google_studio", "openrouter"} <= g
    assert "deepseek" not in g, "DeepSeek görsel almıyor; vision rolünde önerilmemeli"


def test_roller_resolve_ai_call_ile_AYNI():
    """Rol adı burada ve `resolve_ai_call`da ayrışırsa ayar sessizce yok sayılır."""
    assert {r for r, _ in ROLLER} == {"dna", "script", "default", "vision"}


def test_bilinmeyen_saglayici_None():
    assert saglayici("yok-boyle-bir-sey") is None


def test_her_saglayicinin_etiketi_var():
    """Etiket ayarlar ekranında görünüyor; boşsa kullanıcı slug görür."""
    for ad, s in SAGLAYICILAR.items():
        assert s.etiket.strip(), ad
        assert s.ad == ad


# --- _invoke_primary YÖNLENDİRMESİ -----------------------------------------
#
# Kayıtta duran sağlayıcı `_invoke_primary`de karşılık bulmazsa çağrı SESSİZCE
# Claude CLI'ye düşüyordu (son dal): ayarda "DeepSeek" yazıyor, gerçekte Opus
# koşuyor. Yönlendirme testle bağlanır.

def _yakala(monkeypatch, modul, fonksiyon="complete"):
    gorulen = {}

    def _f(prompt, **kw):
        gorulen.update(kw, prompt=prompt)
        return "cikti"
    monkeypatch.setattr(modul + "." + fonksiyon, _f)
    return gorulen


@pytest.mark.parametrize("ad,url", [
    ("deepseek", "https://api.deepseek.com/chat/completions"),
    ("qwen", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"),
    ("groq", "https://api.groq.com/openai/v1/chat/completions"),
])
def test_openai_uyumlu_saglayici_DOGRU_URLE_gider(monkeypatch, ad, url):
    from short_bot.claude_cli import _invoke_primary
    g = _yakala(monkeypatch, "short_bot.openai_compat")
    out = _invoke_primary("selam", backend=ad, model="m", claude_path="claude",
                          api_key="k", timeout_s=30)
    assert out == "cikti"
    assert g["base_url"] == url and g["model"] == "m" and g["api_key"] == "k"


def test_gemini_direct_TEK_ANAHTARLA_google_uctan_noktasina_gider(monkeypatch):
    from short_bot.claude_cli import _invoke_primary
    gorulen = {}

    def _f(api_key, model, prompt, **kw):
        gorulen.update(api_key=api_key, model=model)
        return "cikti"
    monkeypatch.setattr("short_bot.google_studio._http_generate", _f)
    assert _invoke_primary("x", backend="gemini_direct", model="gemini-3.5-flash-lite",
                           claude_path="claude", api_key="AIza", timeout_s=30) == "cikti"
    assert gorulen == {"api_key": "AIza", "model": "gemini-3.5-flash-lite"}


def test_BILINMEYEN_backend_claude_cli_ye_duser(monkeypatch):
    """Geriye uyum: eski yapılandırmalarda backend adı 'claude_cli' değil boş
    da olabiliyordu; davranış değişmemeli."""
    from short_bot import claude_cli
    monkeypatch.setattr(claude_cli, "_run_cli",
                        lambda yol, model, t, p: "cli-cikti")
    monkeypatch.setattr(claude_cli, "_resolve_claude_binary", lambda p: "claude")
    assert claude_cli._invoke_primary("x", backend="claude_cli", model="opus",
                                      claude_path="claude", api_key=None,
                                      timeout_s=5) == "cli-cikti"


def test_google_studio_METIN_cagrisinda_CIKTI_TAVANI_genis(monkeypatch):
    """`google_studio.generate` varsayılanı 1024 token — vision için yeter ama
    arketip şablonu ~6 KB (≈2000+ token) ve SESSİZCE KESİLİR. Ölçüldü: aynı
    prompt elle 16000 tavanla çağrıldığında 6231 karakter döndü."""
    from short_bot.claude_cli import _invoke_primary
    g = {}
    monkeypatch.setattr("short_bot.google_studio.generate",
                        lambda prompt, **kw: (g.update(kw), "x")[1])
    _invoke_primary("uzun bir sablon yaz", backend="google_studio",
                    model="gemini-3.5-flash-lite", claude_path="c",
                    api_key=None, timeout_s=60)
    assert g.get("max_tokens", 0) >= 8000, "metin çıktısı 1024 tokende kesilir"


def test_google_studio_GORSEL_cagrisinda_tavan_daha_dar(monkeypatch):
    """Vision yanıtı tek cümlelik JSON; 16000 istemek gereksiz."""
    from short_bot.claude_cli import _invoke_primary
    from pathlib import Path
    g = {}
    monkeypatch.setattr("short_bot.google_studio.generate",
                        lambda prompt, **kw: (g.update(kw), "x")[1])
    _invoke_primary("bak", backend="google_studio", model="m", claude_path="c",
                    api_key=None, timeout_s=60, image_path=Path("k.png"))
    assert g.get("max_tokens", 99999) <= 4096


def test_openai_uyumlu_da_GENIS_tavan(monkeypatch):
    from short_bot.claude_cli import _invoke_primary
    g = _yakala(monkeypatch, "short_bot.openai_compat")
    _invoke_primary("x", backend="deepseek", model="m", claude_path="c",
                    api_key="k", timeout_s=30)
    assert g.get("max_tokens", 0) >= 8000
