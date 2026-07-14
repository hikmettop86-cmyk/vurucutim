"""Sonnet 5 çağırıcısı — önce Claude CLI, patlarsa OpenRouter (AYNI model).

NEDEN resolve_ai_call DEĞİL: aktif backend `openrouter` (config/settings.yaml) ve
resolve_ai_call her rol için OpenRouter döndürüyor — Claude CLI aboneliğini
kullanamayız. Baypas etmek kod tabanında kanıtlanmış desen: niche_finder da,
lang_pack_gen de aynısını yapıyor.

Düşme yolu AYNI MODELİ kullanır (anthropic/claude-sonnet-5): kalite değişmez,
yalnız fatura değişir.
"""
from __future__ import annotations

import json
import logging
import subprocess
from typing import TypeVar

from pydantic import BaseModel

from short_bot.claude_cli import ClaudeCliError, _extract_json, _invoke_raw

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

SONNET_CLI = "sonnet"                      # Claude CLI alias → Sonnet 5
SONNET_OR = "anthropic/claude-sonnet-5"    # OpenRouter düşme yolu (AYNI model)
# Prompt'lar uzun (banka + kanıt başlıkları) ve çıktı da uzun.
# ÖLÇÜLDÜ: 240 sn YETMEDİ (dil paketi üretiminin ilk canlı koşusu zaman aşımına uğradı).
TIMEOUT_S = 600


def sonnet_json(prompt: str, schema: type[T], *, claude_path: str = "claude",
                openrouter_model: str = "", openrouter_key: str | None = None,
                timeout_s: int = TIMEOUT_S, retries: int = 2, invoke=None) -> T:
    """Sonnet 5'e prompt gönder, çıktıyı JSON olarak parse edip ``schema`` ile doğrula.

    invoke: test enjeksiyonu. Üretimde ``claude_cli._invoke_raw`` kullanılır.
    """
    inv = invoke or _invoke_raw
    son: Exception | None = None

    for deneme in range(1, retries + 1):
        try:
            raw = inv(prompt, backend="claude_cli", model=SONNET_CLI,
                      claude_path=claude_path, api_key=None, timeout_s=timeout_s)
        except (ClaudeCliError, FileNotFoundError, OSError,
                subprocess.TimeoutExpired) as e:
            # CLI yok / patladı / yanıt vermedi → OpenRouter'daki AYNI modele düş.
            #
            # TimeoutExpired'i yakalamak ŞART: OSError DEĞİL, ve yakalanmazsa üretim
            # düşme yolunu HİÇ DENEMEDEN ölür. Gerçek koşuda tam bu yaşandı.
            log.info(f"[sonnet] Claude CLI kullanılamadı ({e}) → OpenRouter")
            raw = inv(prompt, backend="openrouter",
                      model=openrouter_model or SONNET_OR,
                      claude_path=claude_path, api_key=openrouter_key,
                      timeout_s=timeout_s)

        try:
            return schema.model_validate(json.loads(_extract_json(raw)))
        except Exception as e:   # noqa: BLE001 — JSON/şema hatası: yeniden dene
            son = e
            log.warning(f"[sonnet] deneme {deneme} şemaya uymadı: {e}")

    raise RuntimeError(f"Sonnet {retries} denemede geçerli JSON üretemedi: {son}")
