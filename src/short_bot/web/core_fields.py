"""Ortak çekirdek alanları — TEK okuyucu.

Kimlik, zamanlama, YouTube ve otomasyon her formatta AYNI alanlardır. Bugüne kadar
dört düzenleme rotası bunları ayrı ayrı okuyordu ve dördü de eksikti: kürate
kanalda gizlilik/kategori/yükleme eşiği hiç yoktu, kart kanalında
`credentials_from` yoktu (oysa gundem ile gundem-yorum aynı YouTube kanalına
üretiyor). Tek okuyucu bu hata sınıfını kapatır.

TASARIM: `core_updates` **yazmaz**, `dataclasses.replace` kwargs'ı döndürür.
Çağıran kendi formatına özgü alanlarını ekleyip tek `replace` yapar — böylece
ortak alanlar ile formata özgü alanlar arasında yazma sırası tartışması olmaz.

FORM'DA OLMAYAN ALANA DOKUNULMAZ. Kısmi form (örn. Gündem Yorum'da
`schedule_cron` yok, `runs_per_day`'den türetiliyor) mevcut ayarı silmemeli.
"""
from __future__ import annotations

from typing import Callable, Iterable

from short_bot.config import YoutubeChannelConfig

# Formda bunlardan biri varsa YouTube bloğu güncellenir; hiçbiri yoksa mevcut
# blok olduğu gibi korunur.
_YT_ALANLARI = ("yt_auto_upload", "yt_ai_content", "yt_category_id",
                "yt_privacy_status", "yt_min_score_for_upload",
                "yt_cron_preset", "yt_credentials_from")


def _float(form, ad: str, varsayilan: float) -> float:
    try:
        return float(form.get(ad, varsayilan))
    except (TypeError, ValueError):
        return varsayilan


def core_updates(form, cfg) -> dict:
    """Ortak alanların `dataclasses.replace` kwargs'ı.

    `form`: `request.form` ya da düz sözlük (test kolaylığı).
    """
    upd: dict = {}

    if "name" in form:
        upd["name"] = (form.get("name") or cfg.name).strip()
    if "handle" in form:
        upd["handle"] = (form.get("handle") or cfg.handle).strip()
    if "schedule_cron" in form:
        upd["schedule_cron"] = (form.get("schedule_cron") or cfg.schedule_cron).strip()

    # enabled ve archived AYRI EKSENLER (bkz. ChannelConfig.archived notu):
    # enabled = cron çalışsın mı, archived = Kokpit'te görünsün mü. Cron'u kapalı
    # ama elle çalıştırılan kanallar var; ikisini tek bayrağa bağlamak onları
    # listeden düşürürdü.
    #
    # Onay kutusu İŞARETSİZ gönderilmez. Bu yüzden "kutu formda var mıydı" bilgisi
    # gizli bir eşlik alanıyla taşınır (`enabled_present`), yoksa her kısmi kaydet
    # kanalı kapatırdı.
    if form.get("enabled_present") == "1" or "enabled" in form:
        upd["enabled"] = form.get("enabled") == "1"
    if form.get("archived_present") == "1" or "archived" in form:
        upd["archived"] = form.get("archived") == "1"

    if any(k in form for k in _YT_ALANLARI):
        yt = cfg.youtube or YoutubeChannelConfig()
        degis: dict = {}
        if "yt_auto_upload" in form:
            degis["auto_upload"] = form.get("yt_auto_upload") == "1"
        if "yt_ai_content" in form:
            degis["ai_content"] = form.get("yt_ai_content") == "1"
        if "yt_category_id" in form:
            degis["category_id"] = form.get("yt_category_id") or "24"
        if "yt_privacy_status" in form:
            degis["privacy_status"] = form.get("yt_privacy_status") or "public"
        if "yt_min_score_for_upload" in form:
            degis["min_score_for_upload"] = _float(
                form, "yt_min_score_for_upload", yt.min_score_for_upload)
        if "yt_cron_preset" in form:
            degis["cron_preset"] = (form.get("yt_cron_preset") or "").strip() or None
        if "yt_credentials_from" in form:
            # Boş = kendi bağlantım; kendi slug'ı da "kendi" demektir.
            cf = (form.get("yt_credentials_from") or "").strip()
            degis["credentials_from"] = None if (not cf or cf == cfg.slug) else cf
        upd["youtube"] = yt.model_copy(update=degis)

    return upd


def linkable_channels(cfg, *, others: Iterable,
                      has_credentials: Callable[[str], bool],
                      channel_info: Callable[[str], dict | None]) -> list[dict]:
    """`credentials_from` açılırının seçenekleri.

    SEÇİLİ DEĞER HER ZAMAN LİSTEDE OLMALI — henüz bağlanmamış olsa bile.
    CANLI VAKA (2026-08-20): deutschland-klartext'in `credentials_from`'u
    'deutschland-kompakt' idi ama o kanal henüz OAuth'lanmamıştı; açılırda hiç
    seçenek yoktu, tarayıcı boş değeri gönderdi ve ayar SESSİZCE silindi.
    (Aynı aile: dil açılırının ilk seçeneğe düşüp kanalı Türkçeye çevirmesi.)
    """
    liste: list[dict] = []
    for o in others:
        if o.slug == cfg.slug or not has_credentials(o.slug):
            continue
        info = channel_info(o.slug) or {}
        liste.append({"slug": o.slug, "name": o.name,
                      "yt": (info.get("snippet") or {}).get("title", ""),
                      "connected": True})

    mevcut = (cfg.youtube.credentials_from if cfg.youtube else None)
    if mevcut and mevcut not in {l["slug"] for l in liste}:
        baslik = next((o.name for o in others if o.slug == mevcut), mevcut)
        liste.insert(0, {"slug": mevcut, "name": baslik, "yt": "",
                         "connected": False})
    return liste
