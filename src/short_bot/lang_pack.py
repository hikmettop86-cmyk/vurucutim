"""Dile özgü metinlerin tamamı: ekran metni, LLM yönergeleri, klişe denetçisi.

NEDEN VAR: sistem beş dili destekliyor (locale.SUPPORTED_LANGUAGES) ama reel katmanının
metinleri TÜRKÇE SABİTTİ. Almanca kanalda ekrana Türkçe "ABONE OL" çipi basılıyor,
rozet "BİER GARTEN" yazıyor (Türkçe noktalı İ) ve klişe denetçisi hiçbir şey
yakalayamıyordu. İlk ikisi görünür; üçüncüsü SESSİZ — denetçi çalışıyor görünüp sıfır
şey buluyordu.

Paket dosyadan gelir (langpacks/<dil>.json). tr/en elle yazıldı; de/es/fr Sonnet 5
üretiyor (lang_pack_gen). Türkçe paket bugünkü sabitlerin BİREBİR kopyasıdır — altın
test (test_lang_pack_tr_golden.py) çıktının zerre değişmediğini kanıtlıyor.
"""
from __future__ import annotations

import json
import re
import string
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from short_bot.locale import SUPPORTED_LANGUAGES

# EKRAN KISITLARI KODDAN gelir, paketten değil — paket bunlara UYMAK zorunda.
CTA_MAX_CHARS = 24      # 1080px'e sığan tek satır abone çipi
BADGE_MAX_CHARS = 28    # kare-sıfır feed rozeti
TITLE_MAX_CHARS = BADGE_MAX_CHARS - len(" #47")   # rozette numaraya yer kalmalı

# Seed rotasyonu bu sayılara dayanıyor (reel_phrases.pick_styles, reel_subscribe._idx).
N_COMMENT_STYLES = 4
N_CONNECTIVE_STYLES = 8
MIN_OVERUSED = 5
MIN_OVERUSED_PATTERNS = 4

# Seri yönergesi şablonlarının yer tutucuları: alan → (zorunlu, izin verilen).
# Eksik yer tutucu = LLM'e o bilgi hiç söylenmez. Fazlası = çalışma anında KeyError.
SERIES_PLACEHOLDERS: dict[str, tuple[set[str], set[str]]] = {
    "header":          ({"title", "no", "next_no"}, {"title", "no", "next_no"}),
    "paying_promise":  ({"promise"}, {"promise", "no"}),
    "announce_arc":    ({"arc_title", "arc_total"}, {"arc_title", "arc_total", "no"}),
    "finale":          ({"arc_title", "next_no"}, {"arc_title", "next_no", "no"}),
    "planned_loop":    ({"next_no", "next_topic"}, {"next_no", "next_topic"}),
    "chain_loop":      ({"next_no"}, {"next_no"}),
    "teaser_fallback": ({"title"}, {"title"}),
}


class OverusedPattern(BaseModel):
    label: str = Field(min_length=3)     # LLM'e geri bildirimde gösterilir
    pattern: str = Field(min_length=2)   # hedef dilde regex


class SeriesDirectives(BaseModel):
    """Senaryo LLM'ine geçen seri yönergeleri. Pedagoji: ödenmiş tepe + açık kapı."""
    header: str
    paying_promise: str
    announce_arc: str
    finale: str
    planned_loop: str
    chain_loop: str
    teaser_fallback: str


class LangPack(BaseModel):
    lang: str
    # EKRANA BASILAN
    cta_texts: list[str]
    trade_cta: str
    default_series_title: str
    # LLM YÖNERGELERİ
    comment_styles: list[str]
    connective_styles: list[str]
    series: SeriesDirectives
    # DENETÇİ
    overused: list[str]
    overused_patterns: list[OverusedPattern]
    meta_tail_pattern: str


def _placeholders(tmpl: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(tmpl) if f}


def validate_pack(pack: LangPack) -> list[str]:
    """Hataların listesi (boş = geçerli). ÜRETİM ANINDA koşar, çalışma anında DEĞİL.

    Çalışma anında "düzeltmek" kabul edilemez: kırpılmış bir abone çipi ekranda
    "ABONNIE" yazar, eksik yer tutucu üretimin tam ortasında KeyError fırlatır.
    """
    h: list[str] = []

    if pack.lang not in SUPPORTED_LANGUAGES:
        h.append(f"desteklenmeyen dil: {pack.lang!r}")

    # --- ekrana basılan
    if len(pack.cta_texts) != 4:
        h.append(f"cta_texts tam 4 olmalı, {len(pack.cta_texts)} geldi")
    if len(set(pack.cta_texts)) != len(pack.cta_texts):
        h.append("cta_texts tekrarlı metin içeriyor")
    for c in pack.cta_texts:
        if not c.strip():
            h.append("cta_texts boş metin içeriyor")
        elif len(c) > CTA_MAX_CHARS:
            h.append(f"CTA {len(c)} karakter, en fazla {CTA_MAX_CHARS}: {c!r}")

    if "{no}" not in pack.trade_cta:
        h.append("trade_cta '{no}' yer tutucusu içermeli")
    else:
        # HAM uzunluk değil, RENDER edilmiş uzunluk ölçülür.
        render = pack.trade_cta.replace("{no}", "48")
        if len(render) > CTA_MAX_CHARS:
            h.append(f"trade_cta render edilince {len(render)} karakter, en fazla "
                     f"{CTA_MAX_CHARS}: {render!r}")

    if not pack.default_series_title.strip():
        h.append("default_series_title boş")
    elif len(pack.default_series_title) > TITLE_MAX_CHARS:
        h.append(f"default_series_title {len(pack.default_series_title)} karakter; "
                 f"rozete sığması için en fazla {TITLE_MAX_CHARS}")

    # --- sayılar
    if len(pack.comment_styles) != N_COMMENT_STYLES:
        h.append(f"comment_styles tam {N_COMMENT_STYLES} olmalı, "
                 f"{len(pack.comment_styles)} geldi")
    if len(pack.connective_styles) != N_CONNECTIVE_STYLES:
        h.append(f"connective_styles tam {N_CONNECTIVE_STYLES} olmalı, "
                 f"{len(pack.connective_styles)} geldi")

    # --- denetçi (boş liste = denetçi yok = sessiz bozulma)
    if len(pack.overused) < MIN_OVERUSED:
        h.append(f"overused en az {MIN_OVERUSED} olmalı, {len(pack.overused)} geldi")
    if len(pack.overused_patterns) < MIN_OVERUSED_PATTERNS:
        h.append(f"overused_patterns en az {MIN_OVERUSED_PATTERNS} olmalı, "
                 f"{len(pack.overused_patterns)} geldi")
    for op in pack.overused_patterns:
        try:
            re.compile(op.pattern)
        except re.error as e:
            h.append(f"geçersiz regex {op.pattern!r}: {e}")
    try:
        re.compile(pack.meta_tail_pattern)
    except re.error as e:
        h.append(f"geçersiz meta_tail_pattern regex: {e}")

    # --- seri şablonları
    for alan, (zorunlu, izinli) in SERIES_PLACEHOLDERS.items():
        var = _placeholders(getattr(pack.series, alan))
        for eksik in sorted(zorunlu - var):
            h.append(f"series.{alan}: zorunlu yer tutucu eksik: {{{eksik}}}")
        for fazla in sorted(var - izinli):
            h.append(f"series.{alan}: bilinmeyen yer tutucu: {{{fazla}}}")

    return h


# --- YÜKLEME ---------------------------------------------------------------

# Kodla gelen varsayılan paketler (tr, en — elle yazıldı).
_BUILTIN_DIR = Path(__file__).parent / "langpacks"

# Üretilen paketlerin yazıldığı kullanıcı dizini. ÖNCELİKLİ: paketlenmiş Electron
# uygulamasında kurulum dizini salt-okunur olabilir ve üretilen paketlerin bir yere
# yazılması gerekir.
_user_dir: Path | None = None


def set_user_dir(path: Path | None) -> None:
    """Üretilen paketlerin okunacağı/yazılacağı dizin (SHORTBOT_CONFIG_DIR/langpacks)."""
    global _user_dir
    _user_dir = Path(path) if path else None
    load_pack.cache_clear()


def pack_path(lang: str, *, user: bool = False) -> Path:
    if user:
        if _user_dir is None:
            raise RuntimeError("kullanıcı dil paketi dizini kurulmadı (set_user_dir)")
        return _user_dir / f"{lang}.json"
    return _BUILTIN_DIR / f"{lang}.json"


@lru_cache(maxsize=8)
def load_pack(lang: str) -> LangPack:
    """Dil paketini yükle. Bulunamazsa RuntimeError.

    SESSİZ DÜŞME YASAK: Türkçe pakete DÜŞMEZ. Almanca kanalın Türkçe abone çipi
    basması — düzeltmeye çalıştığımız hatanın ta kendisi. Paket yoksa üretilmeli
    (lang_pack_gen.generate_pack); üretilemiyorsa kanal kurulmamalı.
    """
    adaylar = ([pack_path(lang, user=True)] if _user_dir else []) + [pack_path(lang)]
    for p in adaylar:
        if not p.exists():
            continue
        pack = LangPack.model_validate(json.loads(p.read_text(encoding="utf-8")))
        hatalar = validate_pack(pack)
        if hatalar:
            raise RuntimeError(f"{p}: geçersiz dil paketi\n  • "
                               + "\n  • ".join(hatalar))
        return pack
    raise RuntimeError(
        f"'{lang}' dil paketi yok. Panelden Ayarlar → Dil paketleri'nden üretin "
        f"(Sonnet 5, ~1 dakika). Türkçe pakete DÜŞÜLMEZ — Almanca kanalın Türkçe "
        f"abone çipi basması sessiz bir bozulmadır.")
