"""Canlı Gündem masası — Google Trends'in güncel listesi + tek tıkla üretim.

Kullanıcı isteği (2026-08-20): "Trends'in sürekli güncel hâlini görüp en iyi
haberleri bir tıkla video yapacağım bir ekran." Tablo 5 dakikada bir kendiliğinden
tazelenir (HTMX), satır başına hedef kanallar listelenir (o bölgenin trends
kanalları — 6 sn kart / Yorum), tıklanınca seçilen haber ``preselected_item``
olarak kanalın hattına girer (dedup/puanlama atlanır, operatör zaten seçti).

Veri ``trends.trending_now.fetch_trending_items`` ile aynı önbellekten gelir
(kanal koşularıyla aynı dosya) — ekran 'Yenile' derse API'ye gider.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from short_bot.config import list_channels, load_channel
from short_bot.db import init_db, is_processed
from short_bot.formats import FORMAT_LABELS, channel_format
from short_bot.locale import trend_region_for
from short_bot.trends.trending_now import fetch_trending_items
from short_bot.web.runs import launch_pipeline

bp = Blueprint("gundem", __name__)

REGIONS = [("TR", "Türkiye"), ("DE", "Almanya"), ("ES", "İspanya"), ("US", "ABD"),
           ("FR", "Fransa"), ("JP", "Japonya"), ("GB", "Birleşik Krallık"), ("AT", "Avusturya")]
REGION_LANG = {"TR": "tr", "DE": "de", "ES": "es", "US": "en", "FR": "fr", "JP": "ja", "GB": "en", "AT": "de"}
DESK_MIN_VOLUME = 1000       # masa her şeyi göstersin; kanal eşiği ayrı
DESK_MAX_ENTRIES = 60
REFRESH_SECONDS = 300


def _cache_dir() -> Path:
    return Path(current_app.config["SHORTBOT_CACHE_DIR"]) / "trends"


def _region() -> str:
    r = (request.args.get("region") or request.form.get("region") or "TR").strip().upper()
    return r if len(r) == 2 and r.isalpha() else "TR"


def _trend_channels(region: str) -> list:
    """Bu bölgeyi üreten trends kanalları (6 sn kart + yorum), etkin olmayanlar dahil
    (operatör kapalı kanala da elle üretebilir)."""
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    out = []
    for c in list_channels(cfg_dir / "channels", enabled_only=False):
        if c.content_source != "trends":
            continue
        r = (c.trends_region or trend_region_for(c.language)).upper()
        if r != region:
            continue
        out.append({"slug": c.slug, "name": c.name, "format": channel_format(c),
                    "label": FORMAT_LABELS.get(channel_format(c), channel_format(c))})
    return out


def _cache_age_minutes(region: str) -> float | None:
    p = _cache_dir() / f"trending_now_{region.lower()}.json"
    if not p.exists():
        return None
    return (datetime.now(timezone.utc).timestamp() - p.stat().st_mtime) / 60.0


def _rows(region: str, *, force: bool):
    items = fetch_trending_items(region, language=REGION_LANG.get(region, "en"),
                                 cache_dir=_cache_dir(),
                                 max_age_minutes=0 if force else 30,
                                 min_volume=DESK_MIN_VOLUME, max_entries=DESK_MAX_ENTRIES)
    channels = _trend_channels(region)
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    now = datetime.now(timezone.utc)
    rows = []
    for it in items:
        produced = [c["slug"] for c in channels if is_processed(eng, it.guid, c["slug"])]
        age_h = None
        if it.pub_date:
            pd = it.pub_date if it.pub_date.tzinfo else it.pub_date.replace(tzinfo=timezone.utc)
            age_h = max(0.0, (now - pd).total_seconds() / 3600)
        # description biçimi (trending_now._describe): "Google Trends · N arama[ · +%P] · ilişkili · diğer"
        parts = [p.strip() for p in (it.description or "").split("·")][1:]   # baş etiketi at
        growth = next((p for p in parts if p.startswith("+%")), "")
        rest = [p for p in parts if p and not p.startswith("+%") and not p.endswith("arama")]
        related = rest[0] if rest else ""
        others = rest[1] if len(rest) > 1 else ""
        rows.append({
            "guid": it.guid, "title": it.title, "link": it.link, "source": it.source or "",
            "volume": it.trend_volume, "growth": growth, "age_h": age_h,
            "related": related, "others": others, "thumb": it.thumb_url or "",
            "extra": len(it.extra_links), "produced": produced,
        })
    return rows, channels


@bp.route("/gundem")
def desk():
    region = _region()
    rows, channels = _rows(region, force=False)
    return render_template("gundem/desk.html.j2", region=region, regions=REGIONS, rows=rows,
                           channels=channels, cache_age=_cache_age_minutes(region),
                           refresh_seconds=REFRESH_SECONDS)


@bp.route("/gundem/table")
def table():
    """HTMX parçası: her 5 dk ve 'Yenile' ile."""
    region = _region()
    force = request.args.get("force") == "1"
    rows, channels = _rows(region, force=force)
    return render_template("gundem/_table.html.j2", region=region, rows=rows, channels=channels,
                           cache_age=_cache_age_minutes(region))


@bp.route("/gundem/produce", methods=["POST"])
def produce():
    """Seçilen trendi seçilen kanala tek tıkla üret. Haber önbellekten guid ile bulunur
    (form alanlarına güvenmek yerine) → description/trend_volume/extra_links tam gelir."""
    region = _region()
    slug = (request.form.get("channel_slug") or "").strip()
    guid = (request.form.get("guid") or "").strip()
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    channel_path = cfg_dir / "channels" / f"{slug}.yaml"
    if not slug or not channel_path.exists() or not guid:
        abort(404)
    channel = load_channel(channel_path)
    items = fetch_trending_items(region, language=REGION_LANG.get(region, "en"), cache_dir=_cache_dir(),
                                 max_age_minutes=30, min_volume=DESK_MIN_VOLUME, max_entries=DESK_MAX_ENTRIES)
    item = next((i for i in items if i.guid == guid), None)
    if item is None:
        flash("Bu haber artık listede değil — listeyi yenileyip tekrar dene.", "error")
        return redirect(url_for("gundem.desk", region=region))
    launch_pipeline(
        channel=channel,
        settings=current_app.config["SHORTBOT_SETTINGS"],
        db_path=current_app.config["SHORTBOT_DB_PATH"],
        music_root=current_app.config["SHORTBOT_MUSIC_ROOT"],
        templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
        cache_dir=current_app.config["SHORTBOT_CACHE_DIR"],
        lock_dir=current_app.config["SHORTBOT_LOCK_DIR"],
        logs_dir=current_app.config["SHORTBOT_LOGS_DIR"],
        trigger="manual_gundem",
        preselected_item=item,
    )
    flash(f"Üretim başladı: {item.title[:60]} → {channel.name}. İlerleme Akış/Loglar'da.", "success")
    return redirect(url_for("gundem.desk", region=region))
