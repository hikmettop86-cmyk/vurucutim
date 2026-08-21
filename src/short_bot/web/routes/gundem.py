"""Canlı Gündem masası — solda kuyruk, sağda seçilen haberin dosyası + tek tıkla üretim.

Kullanıcı isteği (2026-08-20): "Trends'in sürekli güncel hâlini görüp en iyi haberleri
bir tıkla video yapacağım bir ekran." Tasarım yönü **Masa** seçildi (mockup tuvali
"Gündem Ekranı Yönleri" → 2 · Masa): kuyrukta gezinip sağda kararı GÖREREK verirsin —
hangi kaynaklardan yorum kurulacak, insanlar ne arıyor, kart nasıl çıkacak, kanal bugün
kaç video üretmiş.

Veri kanal koşularıyla AYNI önbellekten gelir (trends/trending_now); "Şimdi yenile"
API'ye gider. Seçilen haber ``preselected_item`` olarak hatta girer: dedup ve puanlama
kapısı ATLANIR, çünkü seçimi zaten operatör yaptı.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from short_bot.config import list_channels, load_channel
from short_bot.db import init_db, is_processed, rss_items, shorts
from short_bot.formats import FORMAT_LABELS, channel_format
from short_bot.followup import previous_coverage, summarize
from short_bot.locale import trend_region_for
from short_bot.search_intent import intent_label
from short_bot.trends.trending_now import fetch_trending_items
from short_bot.trends.verticals import (CATEGORY_NAMES, VERTICAL_LABELS,
                                        VERTICALS, matches as vertical_matches)
from short_bot.web.runs import launch_pipeline

bp = Blueprint("gundem", __name__)

REGIONS = [("TR", "Türkiye"), ("DE", "Almanya"), ("ES", "İspanya"), ("US", "ABD"),
           ("FR", "Fransa"), ("JP", "Japonya"), ("GB", "Birleşik Krallık"), ("AT", "Avusturya")]
REGION_LANG = {"TR": "tr", "DE": "de", "ES": "es", "US": "en", "FR": "fr", "JP": "ja",
               "GB": "en", "AT": "de"}
DESK_MIN_VOLUME = 1000       # masa her şeyi görsün; kanalın kendi eşiği ayrı
DESK_ROWS = 60               # kuyrukta kaç satır — ÖNBELLEĞİ küçültmez (limit=)
REFRESH_SECONDS = 300
TZ = "Europe/Istanbul"


def _cache_dir() -> Path:
    return Path(current_app.config["SHORTBOT_CACHE_DIR"]) / "trends"


def _region() -> str:
    r = (request.args.get("region") or request.form.get("region") or "TR").strip().upper()
    return r if len(r) == 2 and r.isalpha() else "TR"


def _eng():
    return init_db(current_app.config["SHORTBOT_DB_PATH"])


def _items(region: str, *, force: bool = False):
    return fetch_trending_items(region, language=REGION_LANG.get(region, "en"),
                                cache_dir=_cache_dir(),
                                max_age_minutes=0 if force else 30,
                                min_volume=DESK_MIN_VOLUME, limit=DESK_ROWS)


def _trend_channels(region: str) -> list[dict]:
    """Bu bölgeyi üreten trends kanalları (kapalı olanlar dahil — operatör elle üretebilir)."""
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    out = []
    for c in list_channels(cfg_dir / "channels", enabled_only=False):
        if c.content_source != "trends":
            continue
        if (c.trends_region or trend_region_for(c.language)).upper() != region:
            continue
        fmt = channel_format(c)
        out.append({"slug": c.slug, "name": c.name, "format": fmt, "handle": c.handle,
                    "label": FORMAT_LABELS.get(fmt, fmt), "cfg": c})
    # Sıra sabit: önce 6 sn kart, sonra Yorum — klavye kısayolları (1/2) buna bağlı.
    out.sort(key=lambda c: (0 if c["format"] == "card" else 1, c["name"]))
    return out


def _desk_verticals(channels) -> list[str]:
    """Bu bölgeyi üreten kanalların dikeyleri (tekilleştirilmiş, sıralı).

    Masa VARSAYILAN olarak bunu süzer: para kanalı için futbol listesine bakmak
    operatörü yanıltır — üretebileceği şeyi görmeli. Dikeysiz kurulumda liste
    boş döner ve masa eski davranışını (her şey) korur.
    """
    return sorted({(c.get("cfg") and c["cfg"].trends_vertical) or ""
                   for c in channels} - {""})


def _dikey() -> str:
    """Masanın dikey süzgeci. '' = kanal dikeyleri (varsayılan), 'all' = tümü,
    aksi halde tek bir dikey adı."""
    d = (request.args.get("dikey") or request.form.get("dikey") or "").strip().lower()
    if d == "all":
        return "all"
    return d if d in VERTICALS else ""


def _channel_fit(channels, picked) -> dict[str, bool]:
    """Seçili haber her kanalın dikeyine uyuyor mu? (slug -> uyuyor mu)

    Masa kuyruğu kanal dikeylerinin BİRLEŞİMİNE süzülür; bölgede iki kanal
    varsa kuyrukta ikisinin de haberi olur ve operatör yanlış düğmeye basabilir.
    Üretim ENGELLENMEZ (elle üretim meşru bir geçersiz kılmadır) ama düğme
    bunu söylemelidir — sessiz üretim kanalın kimliğini bozar.
    """
    if picked is None:
        return {c["slug"]: True for c in channels}
    return {c["slug"]: vertical_matches(picked.trend_categories,
                                        (c.get("cfg") and c["cfg"].trends_vertical))
            for c in channels}


def _filter_by_dikey(items, dikey: str, channel_verticals: list[str]):
    """Masa kuyruğunu süz. ÜRETİM yolunu (produce) etkilemez: operatör süzgeç
    dışındaki bir haberi hâlâ elle üretebilmeli."""
    if dikey == "all":
        return list(items)
    hedef = [dikey] if dikey else channel_verticals
    if not hedef:
        return list(items)
    return [i for i in items
            if any(vertical_matches(i.trend_categories, v) for v in hedef)]


def _cache_age_minutes(region: str) -> float | None:
    p = _cache_dir() / f"trending_now_{region.lower()}.json"
    if not p.exists():
        return None
    return (datetime.now(timezone.utc).timestamp() - p.stat().st_mtime) / 60.0


def _age_hours(pub) -> float | None:
    if not pub:
        return None
    pd = pub if pub.tzinfo else pub.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - pd).total_seconds() / 3600)


def _rows(items, channels, eng) -> list[dict]:
    # Soru kalıpları DİLE özgü ("gelecek mi" ≠ "kommt"). Bölgeyi üreten kanalın
    # dilini kullan; kanal yoksa Türkçe (panelin varsayılan bölgesi TR).
    lang = next((c["cfg"].language for c in channels if c.get("cfg")), "tr")
    rows = []
    for it in items:
        produced = [c["slug"] for c in channels if is_processed(eng, it.guid, c["slug"])]
        rows.append({"guid": it.guid, "title": it.title, "source": it.source or "",
                     "volume": it.trend_volume, "growth": it.trend_growth_pct,
                     "age_h": _age_hours(it.pub_date), "produced": produced,
                     "sources": 1 + len(it.trend_articles),
                     # Niyet rozeti: ilişkili aramalarında SORU olan trend, cevap
                     # veren formatın (yorum) işidir; kanal seçimi bunu zaten
                     # sırada tercih eder (ChannelConfig.trends_intent).
                     "intent": intent_label(it, language=lang),
                     # Kategori rozeti: süzgeç görünmez olmasın — operatör bir
                     # haberin neden listede olduğunu/olmadığını okuyabilmeli.
                     "category": CATEGORY_NAMES.get(
                         (it.trend_categories or (0,))[0], ""),
                     "queries": list(it.trend_related)[:6]})
    return rows


def _pick(items, rows, guid: str | None):
    """Seçili haber: URL'deki guid, yoksa üretilmemiş ilk haber, o da yoksa ilk haber."""
    if guid:
        for it in items:
            if it.guid == guid:
                return it
    by_guid = {r["guid"]: r for r in rows}
    for it in items:
        if not by_guid.get(it.guid, {}).get("produced"):
            return it
    return items[0] if items else None


def _known_score(eng, guid: str):
    """Bu haber daha önce puanlandıysa yapay zekâ kapısının verdiği puan."""
    with eng.connect() as conn:
        row = conn.execute(
            select(rss_items.c.score, rss_items.c.status, rss_items.c.channel)
            .where(rss_items.c.guid == guid)
            .where(rss_items.c.score.is_not(None))
            .order_by(rss_items.c.id.desc())
        ).fetchone()
    if row is None:
        return None
    return {"score": row.score, "status": row.status, "channel": row.channel}


def _next_fire(cron: str):
    try:
        from apscheduler.triggers.cron import CronTrigger
        nxt = CronTrigger.from_crontab(cron).get_next_fire_time(None, datetime.now())
        return nxt.strftime("%H:%M") if nxt else None
    except Exception:  # noqa: BLE001 — geçersiz cron paneli düşürmesin
        return None


def _channel_status(eng, channels) -> list[dict]:
    """Kanal başına: bugün kaç video, sonuncusu ne zaman, sıradaki koşu."""
    start = datetime.combine(date.today(), time.min, tzinfo=ZoneInfo(TZ)) \
        .astimezone(timezone.utc).replace(tzinfo=None)
    out = []
    for c in channels:
        with eng.connect() as conn:
            row = conn.execute(
                select(func.count(shorts.c.id), func.max(shorts.c.created_at))
                .where(shorts.c.channel == c["slug"])
                .where(shorts.c.created_at >= start)
            ).fetchone()
        last = row[1]
        if isinstance(last, str):
            try:
                last = datetime.fromisoformat(last)
            except ValueError:
                last = None
        cfg = c["cfg"]
        out.append({
            "slug": c["slug"], "name": c["name"], "label": c["label"], "format": c["format"],
            "today": int(row[0] or 0),
            "last": (last.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(TZ)).strftime("%H:%M")
                     if last else None),
            "next": _next_fire(cfg.schedule_cron) if cfg.enabled else None,
            "enabled": cfg.enabled,
            # Aramanın payı (28 gün). Aşama 1'in etkisi ancak bu oran zaman
            # içinde izlenirse görülür; başlangıç ölçümü %2,2–2,9 idi.
            "search_pct": _search_pct(eng, cfg),
            # Kanalın dikeyi durum satırında görünür: operatör hangi kanalın
            # neyi ürettiğini masadan okuyabilmeli.
            "dikey": cfg.trends_vertical or "",
        })
    return out


# Masadaki "kart böyle çıkacak" maketi. Renkler ve etiketler SABİT olsaydı
# (Türk flaş kimliği: kırmızı+sarı, "SIRADA") Almanca kanalın masasında yanlış
# bir kart gösterilirdi — operatör kanalı yanlış kimlikle değerlendirir.
_MOCK_TICKER = {"tr": "Sırada", "de": "Weiter", "en": "Next", "es": "Sigue",
                "fr": "Ensuite", "ja": "次"}
_MOCK_ROWS = {"tr": ("MANŞET", "ALT SATIR", "KJ SATIRI"),
              "de": ("SCHLAGZEILE", "UNTERZEILE", "BAUCHBINDE"),
              "en": ("HEADLINE", "SUBLINE", "LOWER THIRD")}


def _card_mock(channels) -> dict:
    """Maketin paleti ve etiketleri bölgeyi üreten kanaldan gelir."""
    cfg = next((c["cfg"] for c in channels if c.get("cfg")), None)
    lang = getattr(cfg, "language", "tr") if cfg else "tr"
    colors = getattr(cfg, "colors", None) or {}
    arch = getattr(getattr(cfg, "dna", None), "archetype", "") or getattr(cfg, "template", "")
    from short_bot.dna import ARCHETYPE_LABELS
    top, bottom, kj = _MOCK_ROWS.get(lang, _MOCK_ROWS["en"])
    return {
        "primary": colors.get("primary", "#d0021b"),
        "accent": colors.get("accent", "#ffe600"),
        "ticker": _MOCK_TICKER.get(lang, "Next"),
        "top": top, "bottom": bottom, "kj": kj,
        "archetype": arch,
        "archetype_label": ARCHETYPE_LABELS.get(arch, arch.capitalize()),
    }


def _search_pct(eng, cfg) -> float | None:
    """Bu kanalın izlenmelerinin yüzde kaçı YouTube ARAMASINDAN geliyor.

    İstatistik tazelemesi yazar (youtube/stats_refresh.py). Ölçüm yoksa None —
    panel "—" gösterir, uydurma sayı ÜRETMEZ."""
    import json as _json
    from short_bot.db import kv_value
    from short_bot.youtube import auth as _yt_auth
    for slug in (_yt_auth.creds_slug(cfg), cfg.slug):
        raw = kv_value(eng, f"traffic:{slug}")
        if raw:
            try:
                return float((_json.loads(raw) or {}).get("search_pct"))
            except (ValueError, TypeError):
                return None
    return None


def _cartesia_usage() -> dict:
    from short_bot.tts import cartesia_client as cc
    used = cc.month_usage(Path(current_app.config["SHORTBOT_CACHE_DIR"]))
    budget = cc.MONTHLY_BUDGET_DEFAULT
    return {"used": used, "budget": budget, "pct": (100 * used / budget) if budget else 0}


def _context(region: str, *, guid: str | None, force: bool = False,
             dikey: str = "") -> dict:
    ham = _items(region, force=force)
    channels = _trend_channels(region)
    kanal_dikeyleri = _desk_verticals(channels)
    items = _filter_by_dikey(ham, dikey, kanal_dikeyleri)
    eng = _eng()
    rows = _rows(items, channels, eng)
    picked = _pick(items, rows, guid)
    return {
        "region": region, "regions": REGIONS, "rows": rows, "channels": channels,
        "dikey": dikey,
        "dikey_secenekleri": sorted(VERTICAL_LABELS.items()),
        "kanal_dikeyleri": kanal_dikeyleri,
        "elenen": len(ham) - len(items),
        "item": picked,
        "item_age_h": _age_hours(picked.pub_date) if picked else None,
        "produced": ([r for r in rows if r["guid"] == picked.guid][0]["produced"] if picked else []),
        "score": _known_score(eng, picked.guid) if picked else None,
        "status": _channel_status(eng, channels),
        "kanal_uyum": _channel_fit(channels, picked),
        "cartesia": _cartesia_usage(),
        "mock": _card_mock(channels),
        "cache_age": _cache_age_minutes(region),
        "refresh_seconds": REFRESH_SECONDS,
    }


@bp.route("/gundem")
def desk():
    ctx = _context(_region(), guid=(request.args.get("guid") or "").strip() or None,
                   dikey=_dikey())
    return render_template("gundem/desk.html.j2", **ctx)


@bp.route("/gundem/list")
def list_partial():
    """Sol kuyruk — HTMX ile 5 dakikada bir tazelenir; seçim korunur."""
    region = _region()
    ctx = _context(region, guid=(request.args.get("guid") or "").strip() or None,
                   force=request.args.get("force") == "1", dikey=_dikey())
    return render_template("gundem/_list.html.j2", **ctx)


@bp.route("/gundem/produce", methods=["POST"])
def produce():
    """Seçilen trendi seçilen kanala üret. Haber ÖNBELLEKTEN guid ile bulunur (form
    alanlarına güvenmek yerine) → açıklama, hacim ve ek kaynaklar eksiksiz gider."""
    region = _region()
    slug = (request.form.get("channel_slug") or "").strip()
    guid = (request.form.get("guid") or "").strip()
    cfg_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    channel_path = cfg_dir / "channels" / f"{slug}.yaml"
    if not slug or not channel_path.exists() or not guid:
        abort(404)
    channel = load_channel(channel_path)
    item = next((i for i in _items(region) if i.guid == guid), None)
    if item is None:
        flash("Bu haber artık listede değil — listeyi yenileyip tekrar dene.", "error")
        return redirect(url_for("gundem.desk", region=region))
    followup_note = ""
    if request.form.get("followup") == "1":
        # TAKİP: önceki videonun metni prompta girer → yeni video yalnız YENİ
        # gelişmeyi anlatır. Önce aynı kanalın kaydı aranır (üslup sürekliliği),
        # yoksa herhangi bir kanalınki (kart → yorum takibi meşrudur).
        eng = _eng()
        prev = (previous_coverage(eng, guid, channel=slug)
                or previous_coverage(eng, guid))
        note = summarize(prev)
        if note:
            item = replace(item, followup_of=note)
            followup_note = " (takip)"
        else:
            flash("Önceki video bulunamadı — normal üretim olarak başlatıldı.", "info")
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
    flash(f"Üretim başladı{followup_note}: {item.title[:60]} → {channel.name}. "
          f"İlerleme Akış/Loglar'da.", "success")
    return redirect(url_for("gundem.desk", region=region, guid=guid))
