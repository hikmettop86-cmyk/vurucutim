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


# --- ŞEMA MODELE SÖYLENMELİ ------------------------------------------------
#
# ÖLÇÜLDÜ (2026-08-21, canlı panel): `sonnet_json` şemayı yalnız DOĞRULAMA için
# kullanıyor, modele HİÇ söylemiyordu. Kanal sohbeti bu yüzden gerçek modelle
# HİÇ çalışmadı — `SohbetCevabi.mesaj` zorunluydu ama prompt'ta adı bile
# geçmiyordu; model onsuz JSON üretti, iki deneme de aynı hatayla düştü ve
# kullanıcı 111 saniye sonra hata mesajı gördü.
#
# Testler sahte LLM enjekte ettiği için boşluk görünmüyordu: sahte cevap zaten
# geçerliydi. Kapıyı buraya koyuyoruz — şemayı prompt'a KİM koyuyorsa test onu
# sınamalı, çağıran değil.

class _Zorunlu(BaseModel):
    mesaj: str
    sayi: int = 0


def _yakala(cevaplar):
    """invoke sahtesi: gördüğü prompt'ları biriktirir, sıradaki cevabı döner."""
    promptlar = []

    def _invoke(prompt, **kw):
        promptlar.append(prompt)
        return cevaplar[min(len(promptlar) - 1, len(cevaplar) - 1)]
    return _invoke, promptlar


def test_prompt_SEMAYI_tasir():
    inv, promptlar = _yakala(['{"mesaj": "ok"}'])
    sonnet_json("merhaba", _Zorunlu, invoke=inv)
    p = promptlar[0]
    assert "merhaba" in p, "asıl prompt korunmalı"
    for alan in _Zorunlu.model_fields:
        assert alan in p, f"'{alan}' alanı modele hiç söylenmiyor"


def test_ZORUNLU_alanlar_ayrica_isaretlenir():
    """Şema JSON'u uzun; zorunlu alan listesi ayrıca yazılmalı ki gözden kaçmasın."""
    inv, promptlar = _yakala(['{"mesaj": "ok"}'])
    sonnet_json("merhaba", _Zorunlu, invoke=inv)
    p = promptlar[0]
    i = p.find("ZORUNLU")
    assert i > 0, "zorunlu alan vurgusu yok"
    assert "mesaj" in p[i:i + 200]


def test_retry_HATAYI_geri_besler():
    """İkinci deneme birincinin hatasını görmeli.

    Görmezse aynı prompt aynı yanlışı üretir: canlıda tam bu oldu, iki deneme
    de `mesaj` alanını atladı ve 111 saniye boşa gitti.
    """
    inv, promptlar = _yakala(['{"sayi": 1}', '{"mesaj": "ok"}'])
    assert sonnet_json("merhaba", _Zorunlu, invoke=inv).mesaj == "ok"
    assert len(promptlar) == 2
    assert "mesaj" in promptlar[1]
    assert promptlar[1] != promptlar[0], "ikinci deneme aynı prompt'u yollamış"
    assert "REDDEDİLDİ" in promptlar[1] or "hata" in promptlar[1].lower()


# --- DÜŞME YOLU SONNET KALMALI ---------------------------------------------
#
# ÖLÇÜLDÜ (2026-08-21): modülün sözü "düşme yolu AYNI MODELİ kullanır" ama
# çağıranların HEPSİ `settings.openrouter_models["script"]` geçiriyor ve o
# anahtar canlıda `google/gemini-3.1-flash-lite` — sistemin EN UCUZ modeli.
# Sonnet'i tutan anahtar `dna`. topic_bank'in kendi notu bu modelin konu
# bankasının %85'ini çöpe çevirdiğini yazıyor; sohbetin kanal kararlarını da
# aynı model verirdi. Canlı ölçüm: flash-lite cevabı 1,8 sn'de KESİLDİ
# (Unterminated string) — güvenlik ağı hem ucuz hem bozuktu.

def test_OPENROUTER_dusme_yolu_SONNET_kalir():
    from short_bot.claude_cli import ClaudeCliError
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw)
        if kw["backend"] == "claude_cli":
            raise ClaudeCliError("yok")
        return '{"mesaj": "ok"}'

    sonnet_json("m", _Zorunlu, invoke=_invoke, openrouter_key="k",
                openrouter_model="google/gemini-3.1-flash-lite")
    assert "sonnet" in cagri[1]["model"], "düşme yolu ucuz modele indi"


def test_SONNET_varyanti_gecirilebilir():
    """Sonnet ailesinden bir model açıkça verilirse ona saygı duyulur."""
    from short_bot.claude_cli import ClaudeCliError
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw)
        if kw["backend"] == "claude_cli":
            raise ClaudeCliError("yok")
        return '{"mesaj": "ok"}'

    sonnet_json("m", _Zorunlu, invoke=_invoke, openrouter_key="k",
                openrouter_model="anthropic/claude-sonnet-5-20260101")
    assert cagri[1]["model"] == "anthropic/claude-sonnet-5-20260101"


# --- SAĞLAYICI SEÇİLEBİLİR OLMALI ------------------------------------------
#
# `sonnet_json` birincil yolu KODA SABİTLİYORDU (claude_cli/sonnet). Sohbet ve
# konu bankası buradan geçiyor; kullanıcı ayarlardan ücretsiz Google havuzunu
# seçse bile çağrı yine CLI'ye gidiyordu. Ölçüldü (2026-08-21): CLI çağrısı
# 52-112 sn, aynı iş google_studio/gemini-3.5-flash-lite ile 6-7 sn.

def test_VARSAYILAN_hala_claude_cli():
    """Geriye uyum: parametre verilmezse davranış birebir."""
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw)
        return '{"x": 1}'
    sonnet_json("m", _Sema, invoke=_invoke)
    assert cagri[0]["backend"] == "claude_cli" and cagri[0]["model"] == SONNET_CLI


def test_backend_ve_model_GECIRILEBILIR():
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw)
        return '{"x": 2}'
    sonnet_json("m", _Sema, invoke=_invoke, backend="google_studio",
                model="gemini-3.5-flash-lite", api_key=None)
    assert cagri[0]["backend"] == "google_studio"
    assert cagri[0]["model"] == "gemini-3.5-flash-lite"


def test_secilen_saglayici_patlarsa_YINE_OPENROUTERA_duser():
    """Düşme yolu birincil neyse ona göre değil, hep Sonnet'e — kalite garantisi."""
    from short_bot.claude_cli import ClaudeCliError
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw["backend"])
        if kw["backend"] != "openrouter":
            raise ClaudeCliError("havuz tükendi")
        return '{"x": 3}'
    assert sonnet_json("m", _Sema, invoke=_invoke, backend="google_studio",
                       model="g", openrouter_key="k").x == 3
    assert cagri == ["google_studio", "openrouter"]


def test_backend_verilip_MODEL_verilmezse_saglayicinin_ilki():
    """`model=""` ile çağrılırsa boş model adı gider ve sağlayıcı 400 döner."""
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw)
        return '{"x": 9}'
    sonnet_json("m", _Sema, invoke=_invoke, backend="deepseek")
    assert cagri[0]["model"] == "deepseek-chat"


def test_GOOGLE_HAVUZU_TUKENIRSE_de_dusulur():
    """`GoogleStudioExhausted` `AIBackendError` DEĞİL — yakalanmazsa üretim
    düşme yolunu hiç denemeden ölür (aynı tuzağa TimeoutExpired'de düşülmüştü)."""
    from short_bot.google_studio import GoogleStudioExhausted
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw["backend"])
        if kw["backend"] == "google_studio":
            raise GoogleStudioExhausted("havuz bitti")
        return '{"x": 4}'
    assert sonnet_json("m", _Sema, invoke=_invoke, backend="google_studio",
                       model="g", openrouter_key="k").x == 4
    assert cagri == ["google_studio", "openrouter"]
