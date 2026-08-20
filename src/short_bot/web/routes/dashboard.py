"""Kokpit — panelin açılış ekranı.

Ekranın sorusu "kaç video var?" değil, **"şu an benden ne bekleniyor?"**.
Sıralama bilinçli: önce elle yapılması gereken iş, sonra kanalların durumu,
en sonda karşılığı (izlenme/abone).

Eski ekranın ölçüm hatası için bkz. ``short_bot.dashboard_stats``: sayaçlar
``deleted_at IS NULL`` üzerinden kuruluydu, yani üretimi değil gelen kutusunu
sayıyordu ve operatör listeyi boşalttığında hepsi sıfıra düşüyordu.
"""
from __future__ import annotations

from datetime import datetime

from flask import (Blueprint, current_app, flash, make_response,
                   redirect, render_template, request, url_for)

from short_bot.config import list_channels
from short_bot.formats import FORMAT_LABELS as _FORMAT_LABELS
from short_bot.formats import channel_format as _channel_format
from short_bot.dashboard_stats import (STALE_RUN_MINUTES, ViewRate,
                                       channel_growth, channel_view_rate,
                                       daily_production, empty_runs,
                                       failed_runs, hourly_production,
                                       minutes_since, production_summary,
                                       last_production, relative_time,
                                       stalled_runs, to_local, top_videos)
from short_bot.db import (cleanup_zombie_runs, clear_recent_failed_runs,
                          init_db)

bp = Blueprint("dashboard", __name__)

# Kayan pencere; takvim günü DEĞİL. Takvim sayacı gece yarısı sıfırlanıp
# sabahın erken saatlerinde ekranı boş gösteriyordu.
WINDOW_HOURS = 24
SPARK_DAYS = 7

# Bir kanalın kabul oranı bunun altındaysa üretimin çoğu çöpe gidiyor demektir.
# Payda küçükken oran gürültüdür (1/2 = %50), o yüzden en az bu kadar karar
# verilmiş olması aranır.
LOW_ACCEPT_RATE = 0.35
LOW_ACCEPT_MIN_DECIDED = 5

# Format simgeleri. Tür RENKLE değil YAZIYLA gösterilir: bu ekranda renk
# zaten durum anlatıyor (yeşil yayında, kehribar bekliyor, kırmızı acil);
# formatı da renge bindirmek ikisini de belirsizleştirirdi. Simge yalnız
# taramayı hızlandıran bir işaret.
_FORMAT_GLYPHS = {
    "card": "▭", "voiced": "♪", "yorum": "❝", "reel": "▶", "curated": "✂",
}

_SOURCE_LABELS = {
    "rss": "RSS",
    "feed": "Havuz",
    "generator": "Üretici",
    "curated": "Kürate",
}


def _pencere_adi(hours: int) -> str:
    """Metin içinde geçen pencere adı: "Son {…} 3 video üretildi"."""
    if hours % 24 == 0 and hours > 24:
        return f"{hours // 24} günde"
    return f"{hours} saatte"


def _source_label(cfg) -> str:
    """Kaynak adı — bölge/dil BURADA GEÇMEZ, ayrı alanda gösterilir.

    Bölgeyi buraya katmak "Trends TR · TR" gibi tekrarlar üretiyordu.
    """
    src = getattr(cfg, "content_source", "rss") or "rss"
    if src == "trends":
        return "Trends"
    return _SOURCE_LABELS.get(src, src)


def _locale_label(cfg) -> str:
    """Kaynağın bölgesi ve çıktının dili.

    İkisi AYNI ayar değil: ``trends_region`` neyin çekildiğini, ``language``
    hangi dilde yazıldığını belirler. Aynıysa tek kod yazılır (DE); farklıysa
    ikisi de gösterilir (US→TR), çünkü o durumda kanalın ne yaptığı ancak
    ikisiyle anlaşılır.
    """
    dil = (cfg.language or "").upper()
    if (getattr(cfg, "content_source", "rss") or "rss") != "trends":
        return dil
    bolge = (getattr(cfg, "trends_region", "") or "").upper()
    if not bolge or bolge == dil:
        return dil or bolge
    return f"{bolge}→{dil}"


def _cron_next(expr: str):
    """Cron ifadesinin sıradaki tetiklenmesi (yerel, tz-aware) ya da None."""
    if not expr:
        return None
    try:
        from apscheduler.triggers.cron import CronTrigger
        return CronTrigger.from_crontab(expr).get_next_fire_time(
            None, datetime.now().astimezone())
    except Exception:  # noqa: BLE001 — bozuk cron ekranı düşürmesin
        return None


def _next_fires(channels) -> dict[str, datetime | None]:
    """slug → sıradaki tetiklenme (yerel).

    Çalışan scheduler varsa GERÇEK job zamanı okunur; kapalı kanalın job'ı
    yoktur, onun için ifade hesaplanır. Kapalıyken de göstermek bilinçli:
    "açarsam ne zaman çalışır" sorusu kanalı açma kararının kendisi.
    """
    canli: dict[str, datetime] = {}
    sched = getattr(current_app, "scheduler", None)
    if sched is not None:
        try:
            for j in sched.get_jobs():
                if j.next_run_time:
                    canli[j.id] = j.next_run_time
        except Exception:  # noqa: BLE001 — scheduler arızası ekranı düşürmesin
            canli = {}

    out: dict[str, datetime | None] = {}
    for c in channels:
        t = canli.get(c.slug) or _cron_next(getattr(c, "schedule_cron", ""))
        out[c.slug] = t.astimezone() if t is not None else None
    return out


def _creds_slugs(channels) -> dict[str, str]:
    """slug → kimlik slug'ı. ``credentials_from`` doluysa o kanalınki.

    Avatar, kota ve istatistik hep bu anahtarla aranır: iki format tek
    YouTube kanalını paylaşabiliyor (Klartext → Kompakt).
    """
    from short_bot.youtube import auth as yt_auth
    out = {}
    for c in channels:
        try:
            out[c.slug] = yt_auth.creds_slug(c)
        except Exception:  # noqa: BLE001
            out[c.slug] = c.slug
    return out


def _avatars(channels, creds) -> dict[str, bool]:
    """slug → önbellekte kanal logosu var mı (/youtube-avatars/<kimlik>)."""
    from short_bot.youtube.avatar import has_avatar
    root = current_app.config.get("SHORTBOT_YT_CREDS_DIR")
    out = {}
    for c in channels:
        if not root:
            out[c.slug] = False
            continue
        try:
            out[c.slug] = bool(has_avatar(root, creds.get(c.slug, c.slug)))
        except Exception:  # noqa: BLE001
            out[c.slug] = False
    return out


def _yt_connected(channels) -> dict[str, bool]:
    """slug → YouTube bağlantısı var mı.

    Bağlantı kanalın KENDİ slug'ında olmayabilir: ``credentials_from`` ile
    başka bir kanalınkini paylaşıyor olabilir (Klartext, Kompakt'ınkini
    kullanıyor).
    """
    from short_bot.youtube import auth as yt_auth
    root = current_app.config.get("SHORTBOT_YT_CREDS_DIR")
    out: dict[str, bool] = {}
    for c in channels:
        if not root:
            out[c.slug] = False
            continue
        try:
            out[c.slug] = bool(yt_auth.has_credentials(root, yt_auth.creds_slug(c)))
        except Exception:  # noqa: BLE001
            out[c.slug] = False
    return out


def _palette_color(cfg) -> str:
    """Satırın sol şeridi — kanalı bir bakışta tanıtan renk.

    Eski kartlardaki dört renk kutusu süstü; tek şerit aynı işi tabloda
    yer kaplamadan yapıyor.
    """
    dna = getattr(cfg, "dna", None)
    if dna is not None and getattr(dna, "palette", None) is not None:
        renk = getattr(dna.palette, "primary", "")
        if renk:
            return renk
    colors = getattr(cfg, "colors", None)
    if colors is not None:
        return getattr(colors, "primary", "") or "#94918a"
    return "#94918a"


def _spark(values: list[int], *, w: int = 84, h: int = 22, pad: float = 3.0) -> dict:
    """Günlük üretim serisini SVG'ye çevirir.

    Jinja'da yapılabilirdi ama şablonda aritmetik okunmuyor ve test edilemiyor.
    Tepe değeri sıfırsa (hiç üretim yok) çizgi tabana yapıştırılır — bölme
    hatası yerine dümdüz bir taban çizgisi.
    """
    n = len(values)
    if n < 2:
        return {"points": "", "last_x": w, "last_y": h - pad, "flat": True}
    tepe = max(values)
    adim = w / (n - 1)
    ic = h - 2 * pad
    noktalar = []
    for i, v in enumerate(values):
        x = i * adim
        y = (h - pad) if tepe == 0 else (h - pad) - (v / tepe) * ic
        noktalar.append(f"{x:.1f},{y:.1f}")
    son_x, son_y = noktalar[-1].split(",")
    return {"points": " ".join(noktalar),
            "last_x": float(son_x), "last_y": float(son_y),
            "flat": tepe == 0}


def _build_tasks(*, prod, stalled, empties, failures, channels_by_slug,
                 yt_conn, window_hours: int = WINDOW_HOURS) -> list[dict]:
    """"Seni bekleyen" kuyruğu — yalnızca GERÇEKTEN geçerli maddeler.

    Kalıcı olarak doğru olan hiçbir şey buraya girmez (örn. "6 kanal kapalı").
    Her gün aynı satırı gösteren bir yapılacaklar listesi, okunmayan bir
    yapılacaklar listesidir; kalıcı durum tabloda yaşar.
    """
    tasks: list[dict] = []

    # 1) İncelenmeyi bekleyen video — operatörün asıl işi.
    if prod.pending > 0:
        kirilim = [(c.slug, c.pending) for c in prod.channels if c.pending]
        tasks.append({
            "kind": "pending",
            "severity": "wait",
            "count": prod.pending,
            "title": "video incelenmeyi bekliyor",
            "why": ("Üretildi, henüz yayına alınmadı ya da elenmedi. "
                    "Karar verdikçe liste boşalır."),
            "chips": [{"label": s, "value": n,
                       "color": _palette_color(channels_by_slug[s])
                                if s in channels_by_slug else "#94918a"}
                      for s, n in kirilim],
            "action": {"label": "Listeyi aç", "href": "/shorts", "primary": True},
        })

    # 2) Üretiyor ama yayınlanamıyor: bağlantısı olmayan kanal.
    bagsiz = [c for c in prod.channels
              if c.produced > 0 and not yt_conn.get(c.slug, False)]
    if bagsiz:
        tasks.append({
            "kind": "unconnected",
            "severity": "stall",
            "count": len(bagsiz),
            "title": "kanal YouTube'a bağlı değil",
            "why": (f"Son {_pencere_adi(window_hours)} "
                    f"{sum(c.produced for c in bagsiz)} video üretildi ama "
                    "hiçbiri yayınlanamaz — kanal bağlanana kadar üretim "
                    "kasada birikiyor."),
            "chips": [{"label": c.slug, "value": c.produced,
                       "color": _palette_color(channels_by_slug[c.slug])
                                if c.slug in channels_by_slug else "#94918a"}
                      for c in bagsiz],
            "action": {"label": "YouTube'a bağla", "href": "/youtube",
                       "primary": True},
        })

    # 3) Ölmüş ama "running" görünen koşular.
    if stalled:
        tasks.append({
            "kind": "stalled",
            "severity": "stall",
            "count": len(stalled),
            "title": "koşu takılı kalmış",
            "why": (f"{STALE_RUN_MINUTES} dakikadan uzun süredir «çalışıyor» "
                    "görünüyorlar. Üretim thread'i öldüğünde bitiş damgası hiç "
                    "yazılmaz; üstteki «çalışıyor» rozeti de bunları sayar. "
                    "Kapatmak satırı hata olarak işaretler ve kanalın üretim "
                    "kilidini serbest bırakır."),
            "chips": [{"label": r.channel,
                       "value": to_local(r.started_at).strftime("%H:%M")
                                if r.started_at else "—",
                       "color": _palette_color(channels_by_slug[r.channel])
                                if r.channel in channels_by_slug else "#94918a"}
                      for r in stalled],
            "action": {"label": "Takılanları kapat",
                       "post": "/dashboard/close-stalled", "primary": True},
        })

    # 4) Gerçekten çöken koşular.
    if failures:
        tasks.append({
            "kind": "failed",
            "severity": "stall",
            "count": len(failures),
            "title": "koşu hatayla bitti",
            "why": (failures[0]["error"] or "bilinmeyen hata")[:180],
            "chips": [{"label": f["channel"],
                       "value": to_local(f["started_at"]).strftime("%H:%M")
                                if f["started_at"] else "—",
                       "color": _palette_color(channels_by_slug[f["channel"]])
                                if f["channel"] in channels_by_slug else "#94918a"}
                      for f in failures],
            "action": {"label": "Logları aç", "href": "/logs?level=ERROR"},
            "clearable": True,
        })

    # 5) Üretimin çoğu çöpe gidiyor — para ve zaman yakan sessiz sorun.
    dusuk = [c for c in prod.channels
             if c.decided >= LOW_ACCEPT_MIN_DECIDED
             and (c.accept_rate or 0) < LOW_ACCEPT_RATE]
    if dusuk:
        tasks.append({
            "kind": "low_accept",
            "severity": "idle",
            "count": len(dusuk),
            "title": "kanalda üretimin çoğu eleniyor",
            "why": ("Üretilen video yayına gitmeden siliniyor. Her eleme bir "
                    "koşunun API ve render maliyeti demek — kaynak ya da "
                    "eşik gözden geçirilmeli."),
            "chips": [{"label": c.slug,
                       "value": f"{c.uploaded}/{c.decided}",
                       "color": _palette_color(channels_by_slug[c.slug])
                                if c.slug in channels_by_slug else "#94918a"}
                      for c in dusuk],
            "action": {"label": "Shorts'u incele", "href": "/shorts"},
        })

    # 6) Çökmeden, aday bulamadan biten koşular — hata sayacına düşmezler.
    if empties:
        tasks.append({
            "kind": "empty",
            "severity": "idle",
            "count": sum(n for _, n in empties),
            "title": "koşu aday bulamadan bitti",
            "why": (f"Son {SPARK_DAYS} günde çökmeden, hiç video üretmeden "
                    "sonlandılar. Hata sayacına düşmezler; eşik ya da kaynak "
                    "kuruduğunda böyle görünür."),
            "chips": [{"label": s, "value": f"{n}×",
                       "color": _palette_color(channels_by_slug[s])
                                if s in channels_by_slug else "#94918a"}
                      for s, n in empties],
            "action": {"label": "Kanalları gör", "href": "/channels"},
        })

    # 7) Kapalı olduğu hâlde elle çalıştırılan kanal — cron'u açmak unutulmuş olabilir.
    elle = [c for c in prod.channels
            if c.produced > 0
            and c.slug in channels_by_slug
            and not channels_by_slug[c.slug].enabled]
    if elle:
        tasks.append({
            "kind": "manual_only",
            "severity": "idle",
            "count": len(elle),
            "title": "kapalı kanal elle çalıştırılmış",
            "why": ("Üretim yaptılar ama cron'ları kapalı — kendi başlarına "
                    "bir daha çalışmayacaklar."),
            "chips": [{"label": c.slug, "value": c.produced,
                       "color": _palette_color(channels_by_slug[c.slug])}
                      for c in elle],
            "action": {"label": "Kanalları aç", "href": "/channels"},
        })

    onem = {"stall": 0, "wait": 1, "idle": 2}
    tasks.sort(key=lambda t: onem.get(t["severity"], 9))
    return tasks


# Pencere seçicinin sunduğu aralıklar: (anahtar, etiket, saat).
WINDOWS = (("24s", "Son 24 saat", 24),
           ("7g", "7 gün", 24 * 7),
           ("30g", "30 gün", 24 * 30))


def _window() -> tuple[str, int]:
    """Seçili pencere. Tanınmayan değer varsayılana düşer — elle yazılmış
    querystring ekranı bozmasın."""
    istenen = (request.args.get("w") or "").strip()
    for anahtar, _etiket, saat in WINDOWS:
        if anahtar == istenen:
            return anahtar, saat
    return WINDOWS[0][0], WINDOWS[0][2]


@bp.route("/")
def index():
    config_dir = current_app.config["SHORTBOT_CONFIG_DIR"]
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])

    win_key, win_hours = _window()
    channels = list_channels(config_dir / "channels", enabled_only=False)
    by_slug = {c.slug: c for c in channels}

    prod = production_summary(eng, hours=win_hours)
    prod_by_slug = {c.slug: c for c in prod.channels}
    spark = daily_production(eng, days=SPARK_DAYS)
    stalled = stalled_runs(eng)
    empties = empty_runs(eng, days=SPARK_DAYS)
    failures = failed_runs(eng, hours=win_hours)
    yt_conn = _yt_connected(channels)
    fires = _next_fires(channels)
    creds = _creds_slugs(channels)
    avatars = _avatars(channels, creds)
    view_rates = channel_view_rate(eng)
    son_uretim = last_production(eng)
    YOK = ViewRate(None, "istatistik hiç toplanmamış")
    KAPALI = ViewRate(None, "kanal bağlı değil")

    tasks = _build_tasks(prod=prod, stalled=stalled, empties=empties,
                         failures=failures, channels_by_slug=by_slug,
                         yt_conn=yt_conn, window_hours=win_hours)

    rows = []
    for c in channels:
        p = prod_by_slug.get(c.slug)
        seri = spark.get(c.slug, [0] * SPARK_DAYS)
        _son = son_uretim.get(c.slug)
        rows.append({
            "spark_svg": _spark(seri),
            "cfg": c,
            "slug": c.slug,
            "name": c.name,
            "enabled": c.enabled,
            "color": _palette_color(c),
            "source": _source_label(c),
            "format": _FORMAT_LABELS.get(_channel_format(c), ""),
            "glyph": _FORMAT_GLYPHS.get(_channel_format(c), ""),
            "language": _locale_label(c),
            "produced": p.produced if p else 0,
            "uploaded": p.uploaded if p else 0,
            "pending": p.pending if p else 0,
            "dropped": p.dropped if p else 0,
            "accept_rate": p.accept_rate if p else None,
            "last_at": to_local(_son) if _son else None,
            "last_rel": relative_time(_son) if _son else "hiç üretmedi",
            "last_min": minutes_since(_son) if _son else None,
            "creds": creds.get(c.slug, c.slug),
            "avatar": avatars.get(c.slug, False),
            "views": (view_rates.get(creds.get(c.slug, c.slug), YOK)
                      if yt_conn.get(c.slug, False) else KAPALI),
            "next_at": fires.get(c.slug),
            "spark": seri,
            "yt": yt_conn.get(c.slug, False),
        })
    # AÇIK kanallar üstte, sonra üretim çokluğuna göre. Üretimi öne almak
    # denendi ve bırakıldı: elle çalıştırılan kapalı bir kanal (gundem-yorum,
    # 9 video) gerçekten cron'la çalışan bir kanalın üstüne çıkıyordu.
    rows.sort(key=lambda r: (not r["enabled"], -r["produced"], r["slug"]))

    return render_template(
        "dashboard.html.j2",
        prod=prod,
        tasks=tasks,
        rows=rows,
        hours=hourly_production(eng, hours=WINDOW_HOURS),
        growth=channel_growth(eng, days=SPARK_DAYS),
        top=top_videos(eng, days=SPARK_DAYS, limit=5),
        windows=WINDOWS,
        win_key=win_key,
        window_hours=win_hours,
        spark_days=SPARK_DAYS,
        enabled_count=sum(1 for c in channels if c.enabled),
        channel_count=len(channels),
        now_local=datetime.now().astimezone(),
    )


@bp.route("/dashboard/clear-errors", methods=["POST"])
def clear_errors():
    """"Hataları temizle" düğmesi: son 24 saatin failed satırlarını siler.
    Disk üzerindeki koşu logları KORUNUR (/logs'tan hâlâ okunabilir)."""
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    deleted = clear_recent_failed_runs(eng, hours=WINDOW_HOURS)
    if deleted:
        flash(f"{deleted} hata kaydı silindi.", "success")
    else:
        flash("Silinecek hata yok.", "info")
    return _back()


@bp.route("/dashboard/close-stalled", methods=["POST"])
def close_stalled():
    """Ölmüş ama 'running' görünen koşuları kapatır.

    Temizliği KENDİ yapmaz, ``db.cleanup_zombie_runs``a devreder. Ayrı bir
    uygulama yazmak cazipti ama yanlış olurdu: oradaki ölçüt yaş değil
    CANLILIK — üretim kilidi sahipsizse koşu kaç dakikalık olursa olsun
    ölmüştür. Kilidi de o fonksiyon siliyor; ikinci bir uygulama kilidi
    ortada bırakıp kanalı kilitli hâlde donduracaktı.

    Aynı temizlik panel her açıldığında da koşuyor; bu düğme, panel açık
    kalmışken ölen bir üretim için elle tetikleme yolu.
    """
    eng = init_db(current_app.config["SHORTBOT_DB_PATH"])
    kapanan = cleanup_zombie_runs(eng, current_app.config["SHORTBOT_LOCK_DIR"],
                                  age_minutes=STALE_RUN_MINUTES)
    if kapanan:
        flash(f"{kapanan} takılı koşu kapatıldı.", "success")
    else:
        flash("Takılı koşu yok.", "info")
    return _back()


def _back():
    if request.headers.get("HX-Request"):
        resp = make_response("", 200)
        resp.headers["HX-Redirect"] = url_for("dashboard.index")
        return resp
    return redirect(url_for("dashboard.index"))
