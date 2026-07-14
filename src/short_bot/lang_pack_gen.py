"""Dil paketi üretimi — Sonnet 5, Claude CLI üzerinden.

MODEL SEÇİMİ: aktif backend `openrouter` (config/settings.yaml) olduğu için
`resolve_ai_call` her rol için OpenRouter döndürür. Sonnet 5'i Claude CLI'dan çekmek
için onu baypas ediyoruz — abonelikten gelir, marjinal maliyeti yoktur. Bu kod
tabanında kanıtlanmış bir desen: niche_finder.py aynısını yapıyor. CLI yoksa
OpenRouter'daki anthropic/claude-sonnet-5'e düşülür: AYNI MODEL, farklı yol.

Paket dil başına BİR KEZ üretilip dosyaya yazılır; maliyet önemsiz.

PROMPT "ÇEVİR" DEMİYOR. Yasaklı kalıplar hedef dilin GERÇEK Shorts klişeleri olmalı,
Türkçe listenin çevirisi değil. Bunun somut sebebi var ve ölçüldü: kelime sırası
dilden dile değişiyor. Türkçe meta dil "…48. bölümde açıklıyorum" (fiil SONDA),
Almanca "…erkläre ich in Folge 48" (fiil ÖNDE), İngilizce "…I'll explain in episode
48" (fiil ÖNDE). Türkçe regex'in yapısını çevirmek SESSİZCE eşleşmez.
"""
from __future__ import annotations

import json
import logging
import subprocess

from short_bot.claude_cli import (AIBackendError, ClaudeCliError, _extract_json,
                                  _invoke_raw)
from short_bot.lang_pack import CTA_MAX_CHARS, LangPack, load_pack, validate_pack
from short_bot.locale import LANGUAGE_NAMES, SUPPORTED_LANGUAGES

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 2
_SONNET_CLI = "sonnet"                         # Claude CLI alias → Sonnet 5
_SONNET_OR = "anthropic/claude-sonnet-5"       # OpenRouter düşme yolu (AYNI model)
# Paket BÜYÜK: referans olarak tüm Türkçe paket gidiyor (~10 KB) ve çıktı da uzun
# (yedi seri yönergesi + kalıplar). Ölçüldü: 240 sn YETMEDİ.
_TIMEOUT_S = 600


def _prompt(lang: str, ref_json: str, hatalar: list[str]) -> str:
    ad = LANGUAGE_NAMES.get(lang, lang)
    p = f"""Bir YouTube Shorts otomasyon sisteminin DİL PAKETİNİ üreteceksin.

HEDEF DİL: {ad} ({lang})

Aşağıda TÜRKÇE paket REFERANS olarak veriliyor. Görevin ÇEVİRMEK DEĞİL — aynı işlevin
{ad} dilindeki KENDİ MUADİLİNİ yazmak.

ÇEVİRİ NEDEN İŞE YARAMAZ (somut): kelime sırası dilden dile değişir. Türkçe meta dil
"…48. bölümde açıklıyorum" (fiil SONDA), İngilizce "…I'll explain in episode 48"
(fiil ÖNDE). Türkçe kalıbın yapısını çevirirsen regex SESSİZCE hiçbir şey yakalamaz.
Her kalıbı {ad} dilinin KENDİ SÖZDİZİMİNE göre yaz.

Özellikle `overused` ve `overused_patterns`: bunlar {ad} YouTube Shorts'unun GERÇEK,
AŞINMIŞ klişeleri olmalı. Tipik olanlar: kanal açılış selamı; cevaplanabilir bir
evet/hayır sorusu şeklindeki sahte hook; "bugün size göstereceğim" tarzı gündem
duyurusu; içi boş bekletme ("hazır mısınız?").

DİKKAT — kalıp eşleşmesi NOKTALAMASIZ metinde yapılır: kesme işaretleri boşluğa
çevrilir ("what's up" → "what s up"). `overused_patterns` regex'lerini buna göre yaz.
`meta_tail_pattern` ise HAM metne uygulanır (noktalama durur).

SERT KISITLAR — uymayan paket REDDEDİLİR:
  • cta_texts: TAM 4 metin, her biri EN FAZLA {CTA_MAX_CHARS} KARAKTER. Bu bir ekran
    çipi ve 1080 piksele sığmak zorunda; taşarsa kırpılır ve ekranda yarım kelime
    yazar. ({ad} dilinin "abone ol" kelimesi uzunsa metni KISALT.)
  • trade_cta: "{{no}}" yer tutucusu ZORUNLU; no=48 ile render edilince EN FAZLA
    {CTA_MAX_CHARS} KARAKTER.
  • default_series_title: EN FAZLA 24 KARAKTER (rozette " #47" için yer kalmalı).
  • comment_styles: TAM 4.   connective_styles: TAM 8.
  • overused: EN AZ 5.       overused_patterns: EN AZ 4 (regex DERLENEBİLİR olmalı).
  • series.* şablonlarının yer tutucuları AYNEN korunmalı, BAŞKA yer tutucu EKLEME:
      header: {{title}} {{no}} {{next_no}}
      paying_promise: {{promise}}
      announce_arc: {{arc_title}} {{arc_total}}
      finale: {{arc_title}} {{next_no}}
      planned_loop: {{next_no}} {{next_topic}}
      chain_loop: {{next_no}}
      teaser_fallback: {{title}}
  • meta_tail_pattern: {ad} dilinde "…{{konu}} 48. bölümde anlatacağım" gibi bir
    HAVALE cümleciğini cümlenin SONUNDA yakalayan regex ($ ile çapalı). Bu alan bir
    sonraki bölümün ÜRETİM KONUSU olarak kullanılıyor; meta dil temizlenmezse senaryo
    yazıcısı yanılır. Masum bir konu cümlesini KIRPMAMALI.

SERİ YÖNERGELERİNİN PEDAGOJİSİ KORUNMALI: video kendi vaadini TUTAR (tepe gelir,
beğeni tetiklenir), tepeden HEMEN SONRA yeni ve SPESİFİK bir kapı açılır ve o kapının
cevabı BİR SONRAKİ BÖLÜMDEDİR. Abone isteği bir RİCA değil TAKAS'tır. Örnek cümleleri
{ad} dilinde YENİDEN YAZ.

"lang" alanı tam olarak "{lang}" olmalı.

Yalnızca JSON döndür.

REFERANS (Türkçe paket):
{ref_json}
"""
    if hatalar:
        p += ("\nÖNCEKİ DENEMEN REDDEDİLDİ. Şu hataları düzelt:\n  • "
              + "\n  • ".join(hatalar) + "\n")
    return p


def generate_pack(lang: str, *, claude_path: str = "claude",
                  openrouter_model: str = "", openrouter_key: str | None = None,
                  invoke=None) -> LangPack:
    """Dil paketini üret. Doğrulamadan geçmezse RuntimeError — SESSİZ KABUL YOK.

    invoke: test enjeksiyonu. Üretimde claude_cli._invoke_raw kullanılır.
    """
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"desteklenmeyen dil: {lang!r}")

    inv = invoke or _invoke_raw
    ref = load_pack("tr").model_dump_json(indent=2)
    hatalar: list[str] = []
    son: list[str] = ["(deneme yapılamadı)"]

    for deneme in range(1, _MAX_ATTEMPTS + 1):
        prompt = _prompt(lang, ref, hatalar)
        try:
            raw = inv(prompt, backend="claude_cli", model=_SONNET_CLI,
                      claude_path=claude_path, api_key=None, timeout_s=_TIMEOUT_S)
        except (ClaudeCliError, FileNotFoundError, OSError,
                subprocess.TimeoutExpired) as e:
            # CLI yok / patladı / yanıt vermedi → OpenRouter'daki AYNI modele düş.
            # TimeoutExpired'i de yakalamak ŞART: OSError değil, yakalanmazsa üretim
            # düşme yolunu hiç denemeden ölür (ölçüldü — ilk gerçek koşuda tam bu oldu).
            log.info(f"[langpack] Claude CLI kullanılamadı ({e}) → OpenRouter")
            raw = inv(prompt, backend="openrouter",
                      model=openrouter_model or _SONNET_OR,
                      claude_path=claude_path, api_key=openrouter_key,
                      timeout_s=_TIMEOUT_S)

        try:
            pack = LangPack.model_validate(json.loads(_extract_json(raw)))
        except (ValueError, TypeError) as e:
            # Şema/JSON hatası da bir doğrulama hatasıdır — modele geri bildir.
            hatalar = [f"JSON/şema hatası: {e}"]
            son = hatalar
            log.warning(f"[langpack] {lang}: deneme {deneme} şemaya uymadı: {e}")
            continue

        hatalar = validate_pack(pack)
        if not hatalar:
            return pack
        son = hatalar
        log.warning(f"[langpack] {lang}: deneme {deneme} doğrulamayı geçmedi: {hatalar}")

    raise RuntimeError(
        f"'{lang}' dil paketi üretilemedi ({_MAX_ATTEMPTS} deneme). Son hatalar:\n  • "
        + "\n  • ".join(son))


__all__ = ["generate_pack", "AIBackendError"]
