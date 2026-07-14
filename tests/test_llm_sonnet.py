"""Sonnet 5 çağırıcısı: önce Claude CLI (abonelik), patlarsa OpenRouter (AYNI model).

NEDEN resolve_ai_call DEĞİL: aktif backend `openrouter` ve resolve_ai_call her rol için
OpenRouter döndürüyor — Claude CLI aboneliğini kullanamayız. Baypas etmek kod tabanında
kanıtlanmış desen (niche_finder, lang_pack_gen).
"""
import subprocess

import pytest
from pydantic import BaseModel

from short_bot.llm_sonnet import SONNET_CLI, SONNET_OR, TIMEOUT_S, sonnet_json


class _Sema(BaseModel):
    x: int


def test_CLAUDE_CLI_ve_SONNET_kullanilir():
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw)
        return '{"x": 1}'

    assert sonnet_json("merhaba", _Sema, invoke=_invoke).x == 1
    assert cagri[0]["backend"] == "claude_cli"
    assert cagri[0]["model"] == SONNET_CLI == "sonnet"


def test_CLI_patlarsa_OPENROUTERA_duser():
    from short_bot.claude_cli import ClaudeCliError
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw)
        if kw["backend"] == "claude_cli":
            raise ClaudeCliError("claude yok")
        return '{"x": 2}'

    assert sonnet_json("merhaba", _Sema, invoke=_invoke, openrouter_key="k").x == 2
    assert [c["backend"] for c in cagri] == ["claude_cli", "openrouter"]
    assert "sonnet" in cagri[1]["model"], "düşme yolu AYNI modeli kullanmalı"
    assert cagri[1]["api_key"] == "k"


def test_CLI_ZAMAN_ASIMINDA_da_dusulur():
    """subprocess.TimeoutExpired OSError DEĞİL — ayrıca yakalanmalı. Ölçüldü: gerçek
    koşuda yakalanmayınca üretim düşme yolunu HİÇ DENEMEDEN öldü."""
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw["backend"])
        if kw["backend"] == "claude_cli":
            raise subprocess.TimeoutExpired(cmd=["claude"], timeout=TIMEOUT_S)
        return '{"x": 3}'

    assert sonnet_json("merhaba", _Sema, invoke=_invoke).x == 3
    assert cagri == ["claude_cli", "openrouter"]


def test_CLI_YOKSA_da_dusulur():
    def _invoke(prompt, **kw):
        if kw["backend"] == "claude_cli":
            raise FileNotFoundError("claude")
        return '{"x": 4}'

    assert sonnet_json("merhaba", _Sema, invoke=_invoke).x == 4


def test_BOZUK_JSON_yeniden_denenir():
    cevaplar = ["bu json degil", '{"x": 5}']

    def _invoke(prompt, **kw):
        return cevaplar.pop(0)

    assert sonnet_json("merhaba", _Sema, invoke=_invoke).x == 5


def test_HEP_bozuksa_hata():
    def _invoke(prompt, **kw):
        return "asla json degil"

    with pytest.raises(RuntimeError):
        sonnet_json("merhaba", _Sema, invoke=_invoke)


def test_openrouter_modeli_SONNET():
    assert SONNET_OR == "anthropic/claude-sonnet-5"


def test_zaman_asimi_comert():
    # Uzun prompt (banka + kanıt) + uzun çıktı. Ölçüldü: 240 sn YETMEDİ.
    assert TIMEOUT_S >= 480
