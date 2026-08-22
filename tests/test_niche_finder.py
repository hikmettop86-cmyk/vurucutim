import json

import pytest

from short_bot.web.niche_finder import (find_niches_ai, find_niches_data,
                                        _extract_json_array)

_SAMPLE = [
    {"nis": "Uzay Gizemleri", "neden": "Yeni kanallar patlıyor.",
     "konu_tohumu": "Kara deliğe düşersen ne olur?"},
    {"nis": "İnsan Vücudu", "neden": "Talep yüksek.",
     "konu_tohumu": "Nefesini 60 saniye tutunca ne olur?"},
]


def test_extract_json_array_direct_and_embedded():
    assert _extract_json_array('[{"a":1}]') == [{"a": 1}]
    assert _extract_json_array('önek [1, 2] sonek') == [1, 2]
    with pytest.raises(ValueError):
        _extract_json_array("hiç dizi yok")


# ── AI modu (Claude CLI Opus → OpenRouter fallback) ──────────────────────────

def test_find_niches_ai_uses_claude_first():
    calls = []

    def fake_invoke(prompt, *, backend, model, **kw):
        calls.append(backend)
        return json.dumps(_SAMPLE, ensure_ascii=False)

    out = find_niches_ai("bilim", invoke=fake_invoke)
    assert len(out) == 2
    assert calls == ["claude_cli"]  # OpenRouter'a düşmedi


def test_find_niches_ai_opus_model_passed():
    seen = {}

    def fake_invoke(prompt, *, backend, model, **kw):
        seen["model"] = model
        return json.dumps(_SAMPLE, ensure_ascii=False)

    find_niches_ai("bilim", claude_model="opus", invoke=fake_invoke)
    assert seen["model"] == "opus"


def test_find_niches_ai_falls_back_to_openrouter():
    calls = []

    def fake_invoke(prompt, *, backend, model, **kw):
        calls.append(backend)
        if backend == "claude_cli":
            raise RuntimeError("no claude subscription")
        return json.dumps(_SAMPLE, ensure_ascii=False)

    out = find_niches_ai("bilim", openrouter_model="x/y", openrouter_key="sk-or",
                         invoke=fake_invoke)
    assert len(out) == 2
    assert calls == ["claude_cli", "openrouter"]


def test_find_niches_ai_both_fail_raises():
    def fake_invoke(prompt, *, backend, model, **kw):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        find_niches_ai("x", openrouter_model="x/y", openrouter_key="sk",
                       invoke=fake_invoke)


def test_find_niches_ai_no_openrouter_key_raises():
    def fake_invoke(prompt, *, backend, model, **kw):
        raise RuntimeError("no claude")

    with pytest.raises(RuntimeError):
        find_niches_ai("x", invoke=fake_invoke)  # openrouter anahtarı yok


def test_find_niches_ai_language_in_prompt():
    seen = {}

    def fake_invoke(prompt, *, backend, model, **kw):
        seen["prompt"] = prompt
        return json.dumps(_SAMPLE, ensure_ascii=False)

    find_niches_ai("x", language="es", invoke=fake_invoke)
    assert "İspanyolca" in seen["prompt"]


# ── Veri-destekli mod (LLM adaylar + YouTube outlier kanıtı) ─────────────────

def _fake_invoke(prompt, *, backend, model, **kw):
    return json.dumps(_SAMPLE, ensure_ascii=False)


def _fake_http_get(strong_for="Uzay Gizemleri"):
    """search/videos/channels uçları: yalnız `strong_for` sorgusunda dev outlier."""
    class _R:
        status_code = 200
        def __init__(self, p): self._p = p
        def json(self): return self._p

    def http_get(url, params=None, timeout=None):
        p = params or {}
        if "/search" in url:
            if p.get("q") == strong_for:
                return _R({"items": [{"id": {"videoId": "v1"},
                                      "snippet": {"title": "Viral", "channelId": "c1"}}]})
            return _R({"items": []})
        if "/videos" in url:
            return _R({"items": [{"id": "v1", "statistics": {"viewCount": "3000000"}}]})
        if "/channels" in url:
            return _R({"items": [{"id": "c1", "statistics": {"subscriberCount": "4000"}}]})
        return _R({})
    return http_get


def test_find_niches_data_scores_and_sorts():
    out = find_niches_data("bilim", api_keys=["K"], invoke=_fake_invoke,
                           http_get=_fake_http_get(strong_for="Uzay Gizemleri"))
    assert out[0]["nis"] == "Uzay Gizemleri"           # kanıtlı niş öne geçti
    assert out[0]["kanit_puani"] > 0
    assert "Kanıt:" in out[0]["neden"] and "3,000,000" in out[0]["neden"]
    assert out[1]["kanit_puani"] == 0                  # kanıtsız aday sonda
    assert "outlier bulunamadı" in out[1]["neden"]


def test_find_niches_data_no_keys_raises():
    with pytest.raises(RuntimeError, match="anahtar"):
        find_niches_data("bilim", api_keys=[], invoke=_fake_invoke)


def test_find_niches_data_quota_propagates(monkeypatch):
    from short_bot.yt_outliers import QuotaExhausted
    import short_bot.web.niche_finder as nf

    def boom(*a, **kw):
        raise QuotaExhausted("kota dolu")
    monkeypatch.setattr("short_bot.yt_outliers.search_outlier_shorts", boom)
    with pytest.raises(QuotaExhausted):
        find_niches_data("bilim", api_keys=["K"], invoke=_fake_invoke)
