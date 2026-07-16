"""Paket üretimi — Sonnet 5, Claude CLI üzerinden.

Aktif backend openrouter olduğu için resolve_ai_call baypas edilir. Bu, kod tabanında
kanıtlanmış bir desen (niche_finder aynısını yapıyor): önce Claude CLI, patlarsa
OpenRouter. Düşme yolu AYNI modeli kullanır — anthropic/claude-sonnet-5.

Gerçek LLM ÇAĞRILMAZ: sahte `invoke` enjekte edilir. Gerçek üretimin kalite kapısı
ayrı bir testte (test_lang_pack_de_real.py).
"""
import json

import pytest

from short_bot.lang_pack import LangPack, validate_pack
from short_bot.lang_pack_gen import generate_pack

GECERLI = {
    "lang": "de",
    "default_series_title": "Kuriose Fakten",
    "comment_styles": [f"Y{i}" for i in range(4)],
    "connective_styles": [f"S{i}" for i in range(8)],
    "series": {
        "header": "Folge {no} von '{title}'. Nächste: {next_no}.",
        "paying_promise": 'Löse ein: "{promise}"',
        "announce_arc": "Serie '{arc_title}', {arc_total} Folgen.",
        "finale": "Letzte Folge von '{arc_title}'. Folge {next_no} neu.",
        "planned_loop": 'Thema von Folge {next_no}: "{next_topic}"',
        "chain_loop": "Antwort in Folge {next_no}.",
        "teaser_fallback": "Eine Folge der Serie '{title}'.",
    },
    "overused": ["wusstest du schon", "hallo leute", "heute zeige ich euch",
                 "bleibt dran", "vergesst nicht"],
    "overused_patterns": [
        {"label": "Wusstest du schon?", "pattern": r"\bwusstest du\b"},
        {"label": "Hallo Leute", "pattern": r"\bhallo leute\b"},
        {"label": "Heute zeige ich", "pattern": r"\bheute zeige ich\b"},
        {"label": "Seid ihr bereit?", "pattern": r"\bseid ihr bereit\b"},
    ],
    "meta_tail_pattern": r"\b(erkl[äa]r|zeig)\w*\s+ich[^.]*?folge\s+\d+[^.]*?[.!?]?\s*$",
}


def test_gecerli_paket_URETILIR():
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw)
        return json.dumps(GECERLI, ensure_ascii=False)

    pack = generate_pack("de", invoke=_invoke)
    assert isinstance(pack, LangPack)
    assert validate_pack(pack) == []
    assert pack.lang == "de"


def test_SONNET_claude_CLI_uzerinden():
    """Kullanıcının seçimi: Opus değil Sonnet 5, ve CLI'dan (abonelik, ek maliyet yok)."""
    cagri = []

    def _invoke(prompt, **kw):
        cagri.append(kw)
        return json.dumps(GECERLI, ensure_ascii=False)

    generate_pack("de", invoke=_invoke)
    assert cagri[0]["backend"] == "claude_cli"
    assert cagri[0]["model"] == "sonnet"


def test_TURKCE_paket_PROMPTA_referans_verilir():
    """'Çevir' demiyoruz, 'bu dilin kendi muadilini yaz' diyoruz — ama modelin NEYİN
    muadilini yazacağını görmesi lazım."""
    gorulen = {}

    def _invoke(prompt, **kw):
        gorulen["prompt"] = prompt
        return json.dumps(GECERLI, ensure_ascii=False)

    generate_pack("de", invoke=_invoke)
    p = gorulen["prompt"]
    assert "Bilinmeyen" in p or "İLGİNÇ" in p or '"tr"' in p or "yarın" in p,         "Türkçe paket referans olarak verilmedi"
    assert "24" in p, "rozet başlığı karakter sınırı prompt'ta söylenmedi"
    assert "Deutsch" in p


def test_prompt_KELIME_SIRASI_tuzagini_soyler():
    """Türkçe regex'in yapısını çevirmek SESSİZCE eşleşmiyor — bunu bizzat yaşadık
    (Almanca ve İngilizce fixture'ları ilk yazışımızda bu hatayla yazıldı)."""
    gorulen = {}

    def _invoke(prompt, **kw):
        gorulen["p"] = prompt
        return json.dumps(GECERLI, ensure_ascii=False)

    generate_pack("de", invoke=_invoke)
    p = gorulen["p"].lower()
    assert "kelime sırası" in p or "sözdizim" in p


def test_GECERSIZ_paket_HATALARLA_yeniden_denenir():
    """Doğrulama hataları prompt'a GERİ VERİLİR ve bir kez daha denenir."""
    uzun = dict(GECERLI, default_series_title="A" * 30)   # rozet sınırı 24'ü aşar
    promptlar = []

    def _invoke(prompt, **kw):
        promptlar.append(prompt)
        return json.dumps(uzun if len(promptlar) == 1 else GECERLI, ensure_ascii=False)

    pack = generate_pack("de", invoke=_invoke)
    assert validate_pack(pack) == []
    assert len(promptlar) == 2
    assert "REDDEDİLDİ" in promptlar[1], "hata geri bildirilmedi"
    assert "30 karakter" in promptlar[1]


def test_IKI_deneme_de_duserse_RUNTIME_ERROR():
    """SESSİZ KABUL YOK. Geçersiz paket kaydedilirse Almanca kanal bozuk çalışır."""
    uzun = dict(GECERLI, default_series_title="A" * 30)   # rozet sınırı 24'ü aşar

    def _invoke(prompt, **kw):
        return json.dumps(uzun, ensure_ascii=False)

    with pytest.raises(RuntimeError, match="dil paketi üretilemedi"):
        generate_pack("de", invoke=_invoke)


def test_BOZUK_JSON_de_yeniden_denenir():
    cevaplar = ["bu json degil", json.dumps(GECERLI, ensure_ascii=False)]

    def _invoke(prompt, **kw):
        return cevaplar.pop(0)

    assert validate_pack(generate_pack("de", invoke=_invoke)) == []


def test_CLAUDE_CLI_patlarsa_OPENROUTERA_duser():
    from short_bot.claude_cli import ClaudeCliError
    cagrilar = []

    def _invoke(prompt, **kw):
        cagrilar.append(kw)
        if kw["backend"] == "claude_cli":
            raise ClaudeCliError("claude binary not found")
        return json.dumps(GECERLI, ensure_ascii=False)

    pack = generate_pack("de", invoke=_invoke, openrouter_key="k")
    assert validate_pack(pack) == []
    assert cagrilar[0]["backend"] == "claude_cli"
    assert cagrilar[1]["backend"] == "openrouter"
    # AYNI MODEL, farklı yol — kalite değişmez, yalnız fatura değişir.
    assert "sonnet" in cagrilar[1]["model"]
    assert cagrilar[1]["api_key"] == "k"


def test_CLI_ZAMAN_ASIMINDA_da_dusulur():
    """GERÇEK HATA (ilk canlı koşu): Claude CLI 240 sn'de yanıt vermedi ve
    subprocess.TimeoutExpired — OSError DEĞİL — except bloğunda yakalanmıyordu.
    Üretim, düşme yolunu HİÇ DENEMEDEN öldü."""
    import subprocess
    cagrilar = []

    def _invoke(prompt, **kw):
        cagrilar.append(kw["backend"])
        if kw["backend"] == "claude_cli":
            raise subprocess.TimeoutExpired(cmd=["claude"], timeout=600)
        return json.dumps(GECERLI, ensure_ascii=False)

    assert validate_pack(generate_pack("de", invoke=_invoke)) == []
    assert cagrilar == ["claude_cli", "openrouter"]


def test_zaman_asimi_PAKETE_gore_cömert():
    """Referans olarak tüm Türkçe paket gidiyor (~10 KB), çıktı da uzun.
    Ölçüldü: 240 sn YETMEDİ."""
    from short_bot.lang_pack_gen import _TIMEOUT_S
    assert _TIMEOUT_S >= 480


def test_CLI_YOKSA_da_dusulur():
    """claude binary kurulu değilse FileNotFoundError gelir."""
    cagrilar = []

    def _invoke(prompt, **kw):
        cagrilar.append(kw["backend"])
        if kw["backend"] == "claude_cli":
            raise FileNotFoundError("claude")
        return json.dumps(GECERLI, ensure_ascii=False)

    assert validate_pack(generate_pack("de", invoke=_invoke)) == []
    assert cagrilar == ["claude_cli", "openrouter"]


def test_desteklenmeyen_dil_RED():
    with pytest.raises(ValueError):
        generate_pack("zz", invoke=lambda *a, **k: "{}")
