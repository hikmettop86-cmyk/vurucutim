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


def _sema_talimati(schema: type[T]) -> str:
    """Modelin ÜRETECEĞİ şekli prompt'a yazar.

    ÖLÇÜLDÜ (2026-08-21, canlı panel): burası şemayı yalnız DOĞRULAMA için
    kullanıyor, modele HİÇ söylemiyordu. Kanal sohbeti bu yüzden gerçek modelle
    hiç çalışmadı: `SohbetCevabi.mesaj` zorunluydu ama prompt'ta adı bile
    geçmiyordu. Model `mesaj`sız JSON üretti, iki deneme de aynı hatayla düştü,
    kullanıcı 111 saniye bekleyip hata mesajı gördü.

    Şema JSON'u küçük (ölçüldü: SohbetCevabi 1.078, LangPack 1.880 karakter),
    prompt'u şişirmiyor.
    """
    zorunlu = [ad for ad, f in schema.model_fields.items() if f.is_required()]
    parca = ["", "",
             "ÇIKTI: yalnızca aşağıdaki şemaya uyan TEK bir JSON nesnesi "
             "döndür — önsöz, açıklama, markdown çiti yazma.",
             json.dumps(schema.model_json_schema(), ensure_ascii=False)]
    if zorunlu:
        # Şema JSON'unun içindeki "required" gözden kaçıyor; ayrıca yazıyoruz.
        parca.append("ZORUNLU ALANLAR (biri eksikse cevap reddedilir): "
                     + ", ".join(zorunlu))
    return "\n".join(parca)


def _dusme_modeli(istenen: str) -> str:
    """Düşme yolu SONNET KALMALI.

    ÖLÇÜLDÜ (2026-08-21): çağıranların hepsi
    ``settings.openrouter_models["script"]`` geçiriyor ve o anahtar canlıda
    ``google/gemini-3.1-flash-lite`` — sistemin EN UCUZ modeli. Sonnet'i tutan
    anahtar ``dna``. Yani modülün başındaki "düşme yolu AYNI MODELİ kullanır,
    yalnız fatura değişir" sözü pratikte tutmuyordu: CLI'nin patladığı her
    koşuda kalite sessizce düşüyordu.

    Bunun bedeli ölçülü: ``topic_bank`` aynı modelle koşarken konu bankasının
    %85'i çöp çıktı. Sohbetin kanal kararlarını da o model verirdi.
    """
    if istenen and "sonnet" in istenen.lower():
        return istenen
    if istenen and istenen != SONNET_OR:
        log.warning(f"[sonnet] düşme modeli '{istenen}' Sonnet değil → {SONNET_OR}")
    return SONNET_OR


def sonnet_json(prompt: str, schema: type[T], *, claude_path: str = "claude",
                openrouter_model: str = "", openrouter_key: str | None = None,
                timeout_s: int = TIMEOUT_S, retries: int = 2, invoke=None) -> T:
    """Sonnet 5'e prompt gönder, çıktıyı JSON olarak parse edip ``schema`` ile doğrula.

    invoke: test enjeksiyonu. Üretimde ``claude_cli._invoke_raw`` kullanılır.
    """
    inv = invoke or _invoke_raw
    sema = _sema_talimati(schema)
    or_model = _dusme_modeli(openrouter_model)
    son: Exception | None = None

    for deneme in range(1, retries + 1):
        tam = prompt + sema
        if son is not None:
            # HATA GERİ BESLENMELİ. Beslenmezse ikinci deneme aynı prompt'la
            # aynı yanlışı üretir ve yalnız süreyi ikiye katlar — canlıda tam
            # bu oldu (2 × 55 sn, iki cevap da `mesaj` alanını atladı).
            tam += (f"\n\nÖNCEKİ DENEMEN REDDEDİLDİ: {str(son)[:500]}\n"
                    f"Aynı hatayı tekrarlama; eksik alanları doldur.")
        try:
            raw = inv(tam, backend="claude_cli", model=SONNET_CLI,
                      claude_path=claude_path, api_key=None, timeout_s=timeout_s)
        except (ClaudeCliError, FileNotFoundError, OSError,
                subprocess.TimeoutExpired) as e:
            # CLI yok / patladı / yanıt vermedi → OpenRouter'daki AYNI modele düş.
            #
            # TimeoutExpired'i yakalamak ŞART: OSError DEĞİL, ve yakalanmazsa üretim
            # düşme yolunu HİÇ DENEMEDEN ölür. Gerçek koşuda tam bu yaşandı.
            log.info(f"[sonnet] Claude CLI kullanılamadı ({e}) → OpenRouter")
            raw = inv(tam, backend="openrouter", model=or_model,
                      claude_path=claude_path, api_key=openrouter_key,
                      timeout_s=timeout_s)

        try:
            return schema.model_validate(json.loads(_extract_json(raw)))
        except Exception as e:   # noqa: BLE001 — JSON/şema hatası: yeniden dene
            son = e
            log.warning(f"[sonnet] deneme {deneme} şemaya uymadı: {e}")

    raise RuntimeError(f"Sonnet {retries} denemede geçerli JSON üretemedi: {son}")
