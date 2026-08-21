"""OpenAI-uyumlu tek istemci: DeepSeek, Qwen, ModelScope, Groq, NVIDIA, OpenAI.

Hepsi aynı `/chat/completions` sözleşmesini konuşuyor; altı ayrı istemci yazmak
altı ayrı hata yolu demekti.
"""
from __future__ import annotations

import pytest

from short_bot.openai_compat import OpenAIUyumluError, complete

URL = "https://ornek.test/chat/completions"


class _Yanit:
    def __init__(self, kod=200, govde=None, metin=""):
        self.status_code, self._govde, self.text = kod, govde or {}, metin

    def json(self):
        return self._govde


def _iyi(icerik="merhaba"):
    return _Yanit(200, {"choices": [{"message": {"content": icerik}}]})


def test_ANAHTAR_YOKSA_agla_gidilmez(monkeypatch):
    """Anahtarsız istek 401 alır ve sebebi anlaşılmaz; önce burada dur."""
    def _patla(*a, **kw):
        raise AssertionError("ağ çağrısı yapılmamalıydı")
    monkeypatch.setattr("requests.post", _patla)
    with pytest.raises(OpenAIUyumluError, match="anahtar"):
        complete("x", base_url=URL, model="m", api_key=None)


def test_govde_ve_basliklar(monkeypatch):
    yakalanan = {}

    def _post(url, json=None, headers=None, timeout=None):
        yakalanan.update(url=url, json=json, headers=headers, timeout=timeout)
        return _iyi("tamam")

    monkeypatch.setattr("requests.post", _post)
    assert complete("selam", base_url=URL, model="m1", api_key="k",
                    timeout_s=42, max_tokens=1234) == "tamam"
    assert yakalanan["url"] == URL and yakalanan["timeout"] == 42
    assert yakalanan["headers"]["Authorization"] == "Bearer k"
    g = yakalanan["json"]
    assert g["model"] == "m1" and g["max_tokens"] == 1234
    assert g["messages"] == [{"role": "user", "content": "selam"}]


def test_json_modu_istege_bagli(monkeypatch):
    """Şablon yazarken çıktı HTML — json_mode açık kalırsa model JSON'a zorlanır."""
    yakalanan = {}
    monkeypatch.setattr("requests.post",
                        lambda url, json=None, **kw: (yakalanan.update(json), _iyi())[1])
    complete("x", base_url=URL, model="m", api_key="k")
    assert "response_format" not in yakalanan
    yakalanan.clear()
    complete("x", base_url=URL, model="m", api_key="k", json_mode=True)
    assert yakalanan["response_format"] == {"type": "json_object"}


def test_gorsel_base64_content_block(monkeypatch, tmp_path):
    p = tmp_path / "k.jpg"
    p.write_bytes(b"\xff\xd8\xff")
    yakalanan = {}
    monkeypatch.setattr("requests.post",
                        lambda url, json=None, **kw: (yakalanan.update(json), _iyi())[1])
    complete("bak", base_url=URL, model="m", api_key="k", image_path=p)
    ic = yakalanan["messages"][0]["content"]
    assert isinstance(ic, list) and ic[0]["type"] == "text"
    assert ic[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_HTTP_hatasi_SEBEBI_tasir(monkeypatch):
    monkeypatch.setattr("requests.post",
                        lambda *a, **kw: _Yanit(429, {}, "rate limited abi"))
    with pytest.raises(OpenAIUyumluError, match="429"):
        complete("x", base_url=URL, model="m", api_key="k")


def test_bos_yanit_hata(monkeypatch):
    """Boş içerik sessizce '' dönerse çağıran onu geçerli sanır."""
    monkeypatch.setattr("requests.post", lambda *a, **kw: _iyi(""))
    with pytest.raises(OpenAIUyumluError):
        complete("x", base_url=URL, model="m", api_key="k")


def test_beklenmeyen_govde_hata(monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **kw: _Yanit(200, {"tuhaf": 1}))
    with pytest.raises(OpenAIUyumluError):
        complete("x", base_url=URL, model="m", api_key="k")


def test_ag_hatasi_sarilir(monkeypatch):
    import requests as _r

    def _patla(*a, **kw):
        raise _r.RequestException("kablo koptu")
    monkeypatch.setattr("requests.post", _patla)
    with pytest.raises(OpenAIUyumluError, match="ağ"):
        complete("x", base_url=URL, model="m", api_key="k")
