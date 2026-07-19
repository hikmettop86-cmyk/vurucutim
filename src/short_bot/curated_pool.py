"""KÜRATE HAVUZU: cron sürekli Reddit'i tarar, her kürate kanala uygun (tona-duyarlı skor)
cevherleri ``pooled_gems`` tablosuna biriktirir; kullanıcı panelden bakıp 'Üret'/'Ele' der.

Bu, autopilot'un (auto_produce_curated) OTOMATİK-üret kısmını çıkarıp yerine İNSAN ONAYI
koyan versiyon: pahalı otonom LLM ajanı DEĞİL — mevcut find_gems + tona-duyarlı
score_curiosity + dedup'ın zamanlanmış (cron) hâli. Maliyet ~$0 (skor Google ücretsiz
havuz, thumbnail üzerinden; klip İNMEZ — indirme/watermark üretim anında).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import func, select

from short_bot.db import init_db, pooled_gems, shorts

log = logging.getLogger(__name__)

POOL_MAX = 40              # kanal başına en fazla bu kadar BEKLEYEN cevher (havuz taşmasın)
MIZAH_POOL_MIN_SCORE = 7   # mizah havuz eşiği 6→7 (short 957 dersi: 6 sıradan klibi geçiriyor)
QUALITY_MIN = 6            # storyboard izlenme-değerliliği eşiği (engaging + score>=bu)
MAX_JUDGE = 15             # tarama başına en fazla bu kadar aday İNDİR+yargıla (maliyet sınırı)


def clip_key(video_url: str) -> str:
    """Dedup anahtarı — v.redd.it id'si ya da (query'siz) url. _produced_clip_keys ile
    TUTARLI olmalı (aynı klip havuzda + üretilmişte aynı anahtarı üretsin)."""
    vu = (video_url or "").split("?")[0]
    m = re.search(r"v\.redd\.it/([a-z0-9]+)", vu)
    return "vreddit:" + m.group(1) if m else vu


def _gem_key(gem: dict) -> str:
    return clip_key(gem.get("video_url", ""))


def count_pending(eng, channel: str) -> int:
    with eng.connect() as c:
        return c.execute(
            select(func.count()).select_from(pooled_gems).where(
                (pooled_gems.c.channel == channel)
                & (pooled_gems.c.status == "pending"))).scalar() or 0


def pool_keys(eng, channel: str) -> set:
    """Bu kanal için havuzda OLAN tüm clip_key'ler (durumdan bağımsız) — üretilmiş/elenmiş
    olanı yeniden eklememek için."""
    with eng.connect() as c:
        return {r[0] for r in c.execute(
            select(pooled_gems.c.clip_key).where(pooled_gems.c.channel == channel))}


# ── ELENEN-HAFIZASI: aynı klibi her koşuda yeniden indirip yargılamayı önle ──────────────
def mark_seen(eng, channel: str, clip_key: str, verdict: str) -> None:
    """Bir klibi KALICI yargısıyla (produced/watermark/heavy-text/off-tone) hatırla → aynı klip
    bir daha indirilip vision'la kontrol edilmesin. Geçici indirme/vision hatasında ÇAĞRILMAZ.
    INSERT OR IGNORE (yarış-güvenli); hafıza best-effort, üretimi asla düşürmez."""
    if not (clip_key or "").strip():
        return
    from short_bot.db import seen_clips
    try:
        with eng.begin() as c:
            c.execute(seen_clips.insert().prefix_with("OR IGNORE").values(
                channel=channel, clip_key=clip_key, verdict=verdict))
    except Exception as e:  # noqa: BLE001 — hafıza yazımı üretimi bloklamaz
        log.info(f"  kürate[hafıza]: seen yazılamadı ({e})")


def seen_keys(eng, channel: str) -> set:
    """Bu kanal için KALICI yargılanmış (elenmiş/üretilmiş) clip_key'ler — auto_produce fresh
    bunlara karşı da dedup'lar → önceden elenen klip yeniden indirilip kontrol edilmez."""
    from short_bot.db import seen_clips
    with eng.connect() as c:
        return {r[0] for r in c.execute(
            select(seen_clips.c.clip_key).where(seen_clips.c.channel == channel))}


def _produced_keys(db_path) -> set:
    """Üretilmiş kliplerin clip_key'leri (shorts.script_json'dan)."""
    import json
    keys: set = set()
    try:
        eng = init_db(db_path)
        with eng.connect() as c:
            for r in c.execute(select(shorts.c.script_json)):
                try:
                    d = json.loads(r[0] or "{}")
                except Exception:  # noqa: BLE001
                    continue
                vu = d.get("source_video_url") or ""
                if vu:
                    keys.add(clip_key(vu))
                if d.get("source_permalink"):
                    keys.add(d["source_permalink"])
    except Exception:  # noqa: BLE001
        pass
    return keys


def collect_pool(channel, *, settings, secrets, db_path, log=log) -> int:
    """Bir kürate kanal için havuzu doldur: find_gems → dedup → tona-duyarlı skor →
    güçlüyü ekle. Eklenen sayısını döndürür. Havuz doluysa (>=POOL_MAX bekleyen) atlar."""
    from short_bot.curated_pipeline import (CURATED_DUYGU_MIN_S,
                                            CURATED_MIZAH_MIN_S, DUYGU_MIN_SCORE)
    from short_bot.curated_rank import score_curiosity
    from short_bot.pipeline import resolve_ai_call
    from short_bot.reddit_gems import (DEFAULT_DUYGU_SUBS, DEFAULT_SUBS,
                                       find_gems)

    reel = getattr(channel, "reel", None)
    if reel is None or not reel.enabled or getattr(channel, "content_source", "") != "curated":
        return 0
    cid, csec = secrets.get("reddit_client_id"), secrets.get("reddit_client_secret")
    if not (cid and csec):
        log.info(f"  havuz[{channel.slug}]: Reddit kimliği yok → atlandı")
        return 0
    eng = init_db(db_path)
    pending = count_pending(eng, channel.slug)
    if pending >= POOL_MAX:
        log.info(f"  havuz[{channel.slug}]: {pending} bekleyen (>= {POOL_MAX}) → tarama atlandı")
        return 0

    tone = getattr(reel, "curated_tone", "mizah")
    min_ups = getattr(reel, "curated_min_ups", 500)
    max_dur = getattr(reel, "curated_max_duration", 90)
    subs = list(getattr(reel, "subreddits", []) or []) or (
        DEFAULT_DUYGU_SUBS if tone == "duygu" else DEFAULT_SUBS)
    gems = find_gems(cid, csec, subreddits=subs,
                     t=getattr(reel, "curated_time", "month"),
                     min_ups=min_ups, max_duration=max_dur)
    # EK KAYNAK: r/popular (tüm Reddit'te anlık trending) — listede olmayan sub'lardan da
    # taze klip; tona-skor + temizlik filtresi uygunluğu süzer.
    if getattr(reel, "curated_include_popular", True):
        from short_bot.reddit_gems import fetch_popular
        try:
            pop = fetch_popular(cid, csec, min_ups=min_ups, max_duration=max_dur)
            gems += pop
            log.info(f"  havuz[{channel.slug}]: r/popular +{len(pop)} trending video eklendi")
        except Exception as e:  # noqa: BLE001 — popular düşerse subs ile devam
            log.info(f"  havuz[{channel.slug}]: r/popular çekilemedi ({e})")
    # BATCH-İÇİ DEDUP (find_gems + popular çakışabilir) — clip_key başına tek gem
    _uniq: dict = {}
    for g in gems:
        _uniq.setdefault(_gem_key(g), g)
    gems = list(_uniq.values())
    # DEDUP: üretilmiş + havuzda olan
    skip = _produced_keys(db_path) | pool_keys(eng, channel.slug)
    fresh = [g for g in gems if _gem_key(g) not in skip
             and g.get("permalink") not in skip]
    # SÜRE filtresi (tona göre)
    min_s = CURATED_DUYGU_MIN_S if tone == "duygu" else CURATED_MIZAH_MIN_S
    fresh = [g for g in fresh if not (0 < (g.get("duration") or 0) < min_s)]
    if not fresh:
        log.info(f"  havuz[{channel.slug}]: taze cevher yok")
        return 0

    room = POOL_MAX - pending
    # TONA-DUYARLI SKOR (thumbnail, ücretsiz vision) — boş yere hepsini skorlama, room kadar+pay
    fresh.sort(key=lambda g: -(g.get("ups") or 0))
    vision = None
    try:
        vision = resolve_ai_call(settings, secrets, "vision")
    except Exception:  # noqa: BLE001 — vision yoksa engagement sırası
        vision = None
    scored = score_curiosity(fresh, vision_call=vision, tone=tone,
                             top_n=min(30, room + 6), log=log)
    thr = DUYGU_MIN_SCORE if tone == "duygu" else MIZAH_POOL_MIN_SCORE
    strong = [g for g in scored if (g.get("curiosity") or 0) >= thr]
    strong.sort(key=lambda g: -(g.get("curiosity") or 0))
    # FAIL-OPEN: vision HİÇ skorlayamadıysa (yok/çöktü → tüm curiosity=None) sert eşik havuzu
    # SESSİZCE boşaltır (kullanıcı geçmişi: 'no_candidates' / boş havuz). Skor yoksa engagement
    # sırasına düş — boş havuzdansa skorsuz aday iyidir (üretimde ayrıca storyboard kalite kapısı
    # var). Vision GERÇEKTEN skorlayıp hepsini düşük bulduysa TETİKLENMEZ (o zaman eşik doğru).
    if not strong and scored and not any(g.get("curiosity") is not None for g in scored):
        strong = sorted(scored, key=lambda g: -(g.get("ups") or 0))[:room + 6]
        log.info(f"  havuz[{channel.slug}]: vision skorlanamadı → engagement sırasıyla "
                 f"{len(strong)} aday (skorsuz fallback — sessiz-boş önlendi)")

    # STORYBOARD KALİTE KAPISI (kullanıcı: 'kaliteli video motomuz'): thumbnail-skor SIRADAN
    # klibi geçirebiliyor (short 957: kadın-futbolu pile-up skor 8 ama izlenmez — 'maybe maybe
    # maybe' başlığı bilgisiz + kapak aksiyon gibi görünüyor). Güçlü adayları İNDİR + GERÇEK
    # 6 kareyle (storyboard) yargıla → sıradan/rutin olanı ELE. Yalnız MAX_JUDGE kadar indir
    # (maliyet). Storyboard skoru thumbnail skorunun YERİNE geçer (daha doğru).
    if vision is not None and strong:
        import tempfile

        from short_bot.curated_clean import judge_clip_quality
        from short_bot.reddit_gems import download_clip
        verified: list = []
        judged = 0
        with tempfile.TemporaryDirectory() as td:
            for g in strong:
                if len(verified) >= room or judged >= MAX_JUDGE:
                    break
                try:
                    clip = download_clip(g["video_url"], Path(td) / f"q{judged}.mp4")
                except Exception:  # noqa: BLE001 — inmezse (403 vs) atla
                    continue
                judged += 1
                q = judge_clip_quality(clip, vision_call=vision,
                                       ffmpeg_path=settings.ffmpeg_path, tone=tone)
                try:
                    Path(clip).unlink()          # yer aç (tarama başına 15 klip inebilir)
                except Exception:  # noqa: BLE001
                    pass
                if q is None:
                    verified.append(g)           # yargı hatası → fail-open (thumbnail skoruyla)
                elif q.engaging and q.score >= QUALITY_MIN:
                    g["curiosity"] = q.score      # storyboard skoru (daha doğru) YERİNE geçer
                    verified.append(g)
                else:
                    log.info(f"  havuz[kalite][{channel.slug}]: "
                             f"'{(g.get('title') or '')[:34]}' sıradan "
                             f"(q={getattr(q, 'score', '?')}) → elendi")
        strong = sorted(verified, key=lambda x: -(x.get("curiosity") or 0))
        log.info(f"  havuz[kalite][{channel.slug}]: {judged} yargılandı → {len(strong)} izlenesi")

    added = 0
    with eng.begin() as c:
        for g in strong[:room]:
            try:
                c.execute(pooled_gems.insert().values(
                    channel=channel.slug, clip_key=_gem_key(g),
                    permalink=g.get("permalink", ""), video_url=g.get("video_url", ""),
                    title=(g.get("title") or "")[:500], sub=g.get("sub", ""),
                    ups=g.get("ups", 0), comments=g.get("comments", 0),
                    duration=g.get("duration") or 0, width=g.get("width") or 0,
                    height=g.get("height") or 0, orient=g.get("orient", ""),
                    thumb=g.get("thumb", ""), score=float(g.get("curiosity") or 0),
                    tone=tone, status="pending"))
                added += 1
            except Exception as e:  # noqa: BLE001 — UniqueConstraint yarışı vb. → atla
                log.info(f"  havuz[{channel.slug}]: satır eklenemedi ({e})")
    log.info(f"  havuz[{channel.slug}]: +{added} cevher ({len(fresh)} taze, "
             f"{len(strong)} güçlü, {pending}→{pending + added}/{POOL_MAX})")
    return added


def collect_all(channels, *, settings, secrets, db_path, log=log) -> int:
    """Tüm kürate kanallar için havuz toplar. Toplam eklenen döndürür."""
    total = 0
    for ch in channels:
        if getattr(ch, "content_source", "") == "curated" and getattr(ch, "reel", None) \
                and ch.reel.enabled:
            try:
                total += collect_pool(ch, settings=settings, secrets=secrets,
                                      db_path=db_path, log=log)
            except Exception as e:  # noqa: BLE001 — bir kanal düşerse diğerleri sürsün
                log.info(f"  havuz[{ch.slug}]: toplama hatası ({e})")
    return total


def clean_pool(channels, *, settings, secrets, db_path, log=log) -> int:
    """Mevcut BEKLEYEN havuz cevherlerini YENİDEN tara; kapağında gömülü yazı/altyazı/logo
    olanı 'skipped' yap (temiz-only filtresi bu klipler toplandıktan SONRA eklendi). Elenen
    toplam sayısını döndürür. Skorlamayı DÜŞÜRMEZ (drop_text=False) — yalnız has_text bakar."""
    from short_bot.curated_rank import score_curiosity
    from short_bot.pipeline import resolve_ai_call
    eng = init_db(db_path)
    try:
        vision = resolve_ai_call(settings, secrets, "vision")
    except Exception:  # noqa: BLE001
        vision = None
    if vision is None:
        log.info("  havuz[temizlik]: vision yok → atlandı")
        return 0
    import tempfile

    from short_bot.curated_clean import judge_clip_quality
    from short_bot.reddit_gems import download_clip
    total = 0
    for ch in channels:
        if getattr(ch, "content_source", "") != "curated" or not getattr(ch, "reel", None):
            continue
        rows = list_pool(eng, ch.slug, status="pending", limit=200)
        if not rows:
            continue
        tone = getattr(ch.reel, "curated_tone", "mizah")
        gems = [dict(row_to_gem(r), _pool_id=r["id"]) for r in rows]
        # 1) YAZI (thumbnail): top_n=hepsi; drop_text=False → elemeyi BİZ yaparız
        score_curiosity(gems, vision_call=vision, tone=tone, top_n=len(gems),
                        drop_text=False, log=log)
        dirty = [g for g in gems if g.get("has_text")]
        for g in dirty:
            mark_pool(eng, g["_pool_id"], "skipped")
        clean = [g for g in gems if not g.get("has_text")]
        # 2) STORYBOARD KALİTE (indir + gerçek 6 kare): sıradan/rutin olanı ele
        mundane = 0
        dl_fail = none_ct = 0
        with tempfile.TemporaryDirectory() as td:
            for i, g in enumerate(clean):
                try:
                    clip = download_clip(g["video_url"], Path(td) / f"c{i}.mp4")
                except Exception as e:  # noqa: BLE001 — inmezse dokunma (bırak dursun)
                    dl_fail += 1
                    log.info(f"  havuz[temizlik][{ch.slug}]: indirilemedi "
                             f"({str(e)[:40]}) → {(g.get('title') or '')[:24]}")
                    continue
                q = judge_clip_quality(clip, vision_call=vision,
                                       ffmpeg_path=settings.ffmpeg_path, tone=tone)
                try:
                    Path(clip).unlink()
                except Exception:  # noqa: BLE001
                    pass
                if q is None:
                    none_ct += 1
                    continue
                if not q.engaging or q.score < QUALITY_MIN:
                    mark_pool(eng, g["_pool_id"], "skipped")
                    mundane += 1
                    log.info(f"  havuz[temizlik][{ch.slug}]: '{(g.get('title') or '')[:30]}' "
                             f"sıradan (q={q.score}) → elendi")
        if dl_fail or none_ct:
            log.info(f"  havuz[temizlik][{ch.slug}]: {dl_fail} indirilemedi, "
                     f"{none_ct} vision-hatası (bunlar bırakıldı)")
        total += len(dirty) + mundane
        log.info(f"  havuz[temizlik][{ch.slug}]: {len(dirty)} yazılı + {mundane} sıradan "
                 f"elendi / {len(gems)} tarandı → {len(gems) - len(dirty) - mundane} kaldı")
    return total


def list_pool(eng, channel: str, *, status: str = "pending", limit: int = 100) -> list[dict]:
    """Panelde göstermek için havuz satırları (skor sıralı)."""
    with eng.connect() as c:
        rows = c.execute(
            select(pooled_gems).where(
                (pooled_gems.c.channel == channel) & (pooled_gems.c.status == status))
            .order_by(pooled_gems.c.score.desc(), pooled_gems.c.ups.desc())
            .limit(limit)).mappings().all()
    return [dict(r) for r in rows]


def pool_counts(eng, channel: str) -> dict:
    """Kanal için durum sayıları (pending/produced/skipped)."""
    with eng.connect() as c:
        rows = c.execute(
            select(pooled_gems.c.status, func.count()).where(
                pooled_gems.c.channel == channel).group_by(pooled_gems.c.status)).all()
    return {s: n for s, n in rows}


def get_pool_row(eng, pool_id: int):
    with eng.connect() as c:
        r = c.execute(select(pooled_gems).where(pooled_gems.c.id == pool_id)).mappings().first()
    return dict(r) if r else None


def row_to_gem(row: dict) -> dict:
    """Havuz satırı → produce_curated'ın beklediği gem dict."""
    return {
        "video_url": row["video_url"], "title": row.get("title") or "",
        "permalink": row.get("permalink") or "", "sub": row.get("sub") or "",
        "ups": row.get("ups") or 0, "comments": row.get("comments") or 0,
        "duration": row.get("duration") or 0, "width": row.get("width") or 0,
        "height": row.get("height") or 0, "orient": row.get("orient") or "",
        "thumb": row.get("thumb") or "",
    }


def mark_pool(eng, pool_id: int, status: str, *, short_id: int | None = None) -> None:
    vals = {"status": status}
    if short_id is not None:
        vals["short_id"] = short_id
    with eng.begin() as c:
        c.execute(pooled_gems.update().where(pooled_gems.c.id == pool_id).values(**vals))
