"""Cartesia panel uçları: ses listesi, sağlık, model sınama, klon.

Hepsi JSON döner ve HATA UI'YI KIRMAZ: anahtar yoksa 200 + ``error`` alanı, böylece
arayüz kullanıcıya anlaşılır uyarı gösterir. Kredi harcayan tek uçlar ``health``
(model sınaması 2 kredi) ve ``models/probe`` (aday başına 2 kredi) — ikisi de
yalnız düğmeyle çağrılır.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from short_bot.pexels import load_secrets
from short_bot.tts.cartesia_client import (
    HEALTH_MESSAGES_TR,
    KNOWN_MODELS,
    CartesiaError,
    clone_voice,
    health_check,
    list_voices,
    probe_models,
    resolve_cartesia_api_key,
)

bp = Blueprint("cartesia_api", __name__)

_NO_KEY = "Cartesia API anahtarı tanımlı değil (Ayarlar → API anahtarları)."


def _key() -> str:
    secrets_path = Path(current_app.config.get("SHORTBOT_SECRETS_PATH") or "data/secrets.yaml")
    return resolve_cartesia_api_key(load_secrets(secrets_path))


@bp.route("/api/cartesia/voices", methods=["GET"])
def voices():
    """``?language=tr`` ŞART sayılır: süzgeçsiz ilk 100 seste Türkçe hiç yok.
    ``language=*`` tüm dillerin ilk 100'ünü getirir (bilerek)."""
    key = _key()
    if not key:
        return jsonify({"voices": [], "error": _NO_KEY})
    language = (request.args.get("language") or "tr").strip().lower()
    q = (request.args.get("q") or "").strip() or None
    out = list_voices(api_key=key, language=language, q=q)
    if not out:
        return jsonify({"voices": [], "error": f"'{language}' için ses bulunamadı ya da liste alınamadı."})
    return jsonify({"voices": out})


@bp.route("/api/cartesia/health", methods=["POST"])
def health():
    key = _key()
    if not key:
        return jsonify({"ok": False, "state": "no-key", "message": HEALTH_MESSAGES_TR["no-key"]})
    voice_id = (request.form.get("voice_id") or "").strip()
    model = (request.form.get("model") or "").strip() or KNOWN_MODELS[0]
    state = health_check(voice_id=voice_id, api_key=key, model=model)
    return jsonify({"ok": state == "healthy", "state": state,
                    "message": HEALTH_MESSAGES_TR.get(state, state)})


@bp.route("/api/cartesia/models/probe", methods=["POST"])
def models_probe():
    key = _key()
    if not key:
        return jsonify({"models": [], "error": _NO_KEY})
    out = probe_models(api_key=key)
    return jsonify({"models": out, "credits": 2 * len(KNOWN_MODELS)})


@bp.route("/api/cartesia/clone", methods=["POST"])
def clone():
    key = _key()
    if not key:
        return jsonify({"error": _NO_KEY}), 400
    f = request.files.get("clip")
    name = (request.form.get("name") or "").strip()
    language = (request.form.get("language") or "en").strip().lower()
    if f is None or not f.filename or not name:
        return jsonify({"error": "Ses dosyası ve ad gerekli."}), 400
    suffix = Path(f.filename).suffix.lower() or ".wav"
    settings = current_app.config.get("SHORTBOT_SETTINGS")
    ffmpeg = getattr(settings, "ffmpeg_path", "ffmpeg") or "ffmpeg"
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe") if "ffmpeg" in ffmpeg else "ffprobe"
    with tempfile.TemporaryDirectory() as td:
        clip_path = Path(td) / f"clip{suffix}"
        f.save(str(clip_path))
        try:
            vid, trimmed = clone_voice(api_key=key, name=name, clip_path=clip_path,
                                       language=language, ffmpeg=ffmpeg, ffprobe=ffprobe)
        except CartesiaError as e:
            return jsonify({"error": str(e)}), 400
    return jsonify({"voice_id": vid, "trimmed": trimmed})
