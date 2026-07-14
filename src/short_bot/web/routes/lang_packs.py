"""Dil paketleri paneli: listele / göster / düzenle / üret.

NEDEN GÖRÜNÜR OLMALI: Almanca kanal açan biri ekranda ne yazacağını GÖREBİLMELİ.
Paket bir LLM çıktısıdır (Sonnet 5); gözden geçirilmeden üretime girmemeli. Ve paket
YOKSA kanal KURULMAMALI — Türkçe pakete düşmek, düzeltmeye çalıştığımız sessiz
bozulmanın ta kendisi.
"""
from __future__ import annotations

import json
import logging
import threading

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)

from short_bot.lang_pack import (LangPack, load_pack, pack_path, validate_pack)
from short_bot.locale import LANGUAGE_NAMES, SUPPORTED_LANGUAGES

bp = Blueprint("lang_packs", __name__)
_LOG = logging.getLogger(__name__)

# Üretimi süren diller (panel "üretiliyor…" gösterebilsin).
_uretiliyor: set[str] = set()


def _durum(lang: str) -> dict:
    d = {"lang": lang, "name": LANGUAGE_NAMES.get(lang, lang),
         "uretiliyor": lang in _uretiliyor}
    try:
        pack = load_pack(lang)
    except RuntimeError as e:
        return {**d, "var": False, "pack": None, "json": "", "hata": str(e)}
    return {**d, "var": True, "pack": pack, "hata": "",
            "json": pack.model_dump_json(indent=2),
            # Kodla gelen mi, kullanıcı dizininde üretilmiş mi?
            "uretilmis": pack_path(lang, user=True).exists()}


@bp.get("/lang-packs")
def page():
    return render_template("lang_packs.html.j2",
                           diller=[_durum(x) for x in SUPPORTED_LANGUAGES])


@bp.post("/lang-packs/<lang>/generate")
def generate(lang):
    from short_bot.lang_pack_gen import generate_pack
    if lang not in SUPPORTED_LANGUAGES:
        flash(f"Desteklenmeyen dil: {lang}", "error")
        return redirect(url_for("lang_packs.page"))

    settings = current_app.config["SHORTBOT_SETTINGS"]
    secrets = _secrets()
    hedef = pack_path(lang, user=True)
    ad = LANGUAGE_NAMES.get(lang, lang)

    def _job():
        _uretiliyor.add(lang)
        try:
            pack = generate_pack(
                lang,
                claude_path=settings.claude_cli_path,
                openrouter_model=settings.openrouter_models.get(
                    "script", "anthropic/claude-sonnet-5"),
                openrouter_key=secrets.get("openrouter_api_key"))
            hedef.parent.mkdir(parents=True, exist_ok=True)
            hedef.write_text(pack.model_dump_json(indent=2) + "\n", encoding="utf-8")
            load_pack.cache_clear()
            _LOG.info(f"[langpack] {lang} üretildi → {hedef}")
        except Exception as e:   # noqa: BLE001 — thread paneli düşürmesin
            _LOG.warning(f"[langpack] {lang} üretilemedi: {e}")
        finally:
            _uretiliyor.discard(lang)

    threading.Thread(target=_job, daemon=True).start()
    flash(f"{ad} dil paketi üretiliyor (Sonnet 5, birkaç dakika). Bittiğinde sayfayı "
          f"yenileyin; hata olursa günlüklere düşer.", "info")
    return redirect(url_for("lang_packs.page"))


@bp.post("/lang-packs/<lang>")
def save(lang):
    """Elle düzenlenen paketi kaydet — DOĞRULAMADAN GEÇMEDEN kaydedilmez.

    Bozuk bir paket sessizce kabul edilirse Almanca kanal bozuk çalışır (kırpılmış
    çip, eşleşmeyen denetçi, üretim ortasında KeyError).
    """
    if lang not in SUPPORTED_LANGUAGES:
        flash(f"Desteklenmeyen dil: {lang}", "error")
        return redirect(url_for("lang_packs.page"))
    try:
        pack = LangPack.model_validate(json.loads(request.form.get("json", "")))
    except Exception as e:   # noqa: BLE001 — kullanıcı girdisi
        flash(f"Geçersiz JSON / şema: {e}", "error")
        return redirect(url_for("lang_packs.page"))

    hatalar = validate_pack(pack)
    if hatalar:
        flash("Paket REDDEDİLDİ:  • " + "  • ".join(hatalar), "error")
        return redirect(url_for("lang_packs.page"))

    hedef = pack_path(lang, user=True)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(pack.model_dump_json(indent=2) + "\n", encoding="utf-8")
    load_pack.cache_clear()
    flash(f"{LANGUAGE_NAMES.get(lang, lang)} paketi kaydedildi.", "success")
    return redirect(url_for("lang_packs.page"))


def _secrets() -> dict:
    import yaml
    try:
        sp = current_app.config["SHORTBOT_SECRETS_PATH"]
        return (yaml.safe_load(sp.read_text(encoding="utf-8")) if sp.exists() else {}) or {}
    except Exception:   # noqa: BLE001
        return {}
