"""Günün derlemesi — "Türkiye bugün ne aradı?" uzun-form videosu.

NEDEN: Shorts geliri havuzdan bölüşülür ve Türkiye RPM'i düşük (ölçüm: 0,709 TL/1k).
Aynı üretimden günlük bir UZUN-FORM video hem 4.000 saat yolunu açar hem uzun-form
RPM'ini getirir. YouTube 3 dakikanın altındaki dikey videoyu Shorts sayar; bu yüzden
derleme yalnız toplam ≥ ``MIN_TOTAL_S`` (190 sn, pay bırakır) olunca üretilir.

Akış: günün yorum klipleri (dosyası diskte olan) → her biri aynı kodek/çözünürlüğe
normalize edilir → intro (4 sn, günün manşetleri) + klipler (arada 0,4 sn siyah)
+ outro (3 sn) concat demuxer ile birleşir → ``shorts`` tablosuna
``compilation:<slug>:<gün>`` kimliğiyle yazılır (metadata ``script_json`` içinde;
yükleyici onu kullanır, #shorts etiketi YOK).

Süreler DB'den DEĞİL ffprobe'dan: voiced kanallarda ``shorts.duration_s`` kanalın
``duration_s``'i (6) olarak kaydediliyor, gerçek süre değil.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import select

from short_bot.db import record_short, shorts
from short_bot.text_normalize import locale_fold

log = logging.getLogger(__name__)

MIN_TOTAL_S = 190.0
GAP_S = 0.4
INTRO_S = 4.0
OUTRO_S = 3.0
WIDTH, HEIGHT, FPS = 1080, 1920, 30
COMPILATION_PREFIX = "compilation:"

_MONTHS_TR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
              "Eylül", "Ekim", "Kasım", "Aralık"]


def format_day_tr(day: date) -> str:
    return f"{day.day} {_MONTHS_TR[day.month - 1]} {day.year}"


@dataclass(frozen=True)
class Clip:
    short_id: int
    title: str
    path: Path
    duration_s: float
    created_at: datetime
    # queries: o klibin konusunun canlı arama dizeleri (Script.search_queries).
    # Derleme EVERGREEN varlıktır ve ölçüm (2026-08-20) 60+ günlük videolarda
    # izlenmenin %17,3'ünün aramadan geldiğini gösterdi — akış bıraktıktan sonra
    # kalan tek kapı arama. Etiketler bu yüzden gerçek sorgu metnini taşır.
    queries: tuple[str, ...] = ()


# --- seçim --------------------------------------------------------------------------

def probe_duration_s(path: Path, *, ffprobe: str = "ffprobe") -> float:
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True,
                         timeout=30, check=False).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def day_bounds_utc(day: date, tz: str = "Europe/Istanbul") -> tuple[datetime, datetime]:
    """Yerel günün UTC sınırları (``shorts.created_at`` naif UTC saklanıyor)."""
    z = ZoneInfo(tz)
    start = datetime.combine(day, time.min, tzinfo=z).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=z).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


def pick_day_clips(eng, channel_slug: str, day: date, *, tz: str = "Europe/Istanbul",
                   probe: Callable[[Path], float] = probe_duration_s) -> list[Clip]:
    """O gün üretilen, dosyası diskte olan klipler — kronolojik. Derleme satırları
    ve dosyası silinmiş olanlar atlanır. ``deleted_at`` ELENMEZ: operatör yükledikten
    sonra listeden siliyor, dosya çoğunlukla duruyor."""
    start, end = day_bounds_utc(day, tz)
    with eng.connect() as conn:
        rows = conn.execute(
            select(shorts.c.id, shorts.c.title, shorts.c.file_path, shorts.c.created_at,
                   shorts.c.rss_item_guid, shorts.c.script_json)
            .where(shorts.c.channel == channel_slug)
            .where(shorts.c.created_at >= start)
            .where(shorts.c.created_at < end)
            .order_by(shorts.c.created_at.asc())
        ).fetchall()
    clips: list[Clip] = []
    for r in rows:
        if (r.rss_item_guid or "").startswith(COMPILATION_PREFIX):
            continue
        p = Path(r.file_path)
        if not p.exists():
            continue
        d = probe(p)
        if d <= 0:
            continue
        try:
            qs = tuple((json.loads(r.script_json or "{}") or {}).get("search_queries") or ())
        except (ValueError, TypeError):
            qs = ()
        clips.append(Clip(short_id=r.id, title=r.title, path=p, duration_s=d,
                          created_at=r.created_at, queries=qs))
    return clips


def total_seconds(clips: list[Clip]) -> float:
    if not clips:
        return 0.0
    return INTRO_S + sum(c.duration_s for c in clips) + GAP_S * (len(clips) - 1) + OUTRO_S


def chapters(clips: list[Clip]) -> list[tuple[int, str]]:
    """YouTube bölümleri: (başlangıç saniyesi, başlık). İlk bölüm 0'dan başlamalı."""
    out = [(0, "Giriş")]
    t = INTRO_S
    for i, c in enumerate(clips):
        out.append((int(t), c.title))
        t += c.duration_s + (GAP_S if i < len(clips) - 1 else 0)
    return out


# --- metadata -----------------------------------------------------------------------

def build_compilation_metadata(day: date, clips: list[Clip], *, channel_name: str, handle: str,
                               language: str = "tr") -> dict:
    """Uzun-form metadata. #shorts YOK (Shorts değil), bölüm zaman damgaları var."""
    n = len(clips)
    title = f"Türkiye bugün ne aradı? — {format_day_tr(day)} | {n} gündem"
    lines = [f"{format_day_tr(day)} · Google Trends'te en çok aranan {n} konu, tarafsız yorumla.", ""]
    for sec, name in chapters(clips):
        lines.append(f"{sec // 60:02d}:{sec % 60:02d} {name}")
    lines += ["", f"{channel_name} · {handle}", "#gündem #haber #türkiye #sondakika"]
    tags = ["gündem", "haber", "türkiye", "son dakika", "google trends", "günün özeti"]
    # O günün GERÇEK arama dizeleri etiketlere eklenir (varsa). Uydurma anahtar
    # kelime değil: her biri o derlemede gerçekten anlatılan konunun sorgusudur.
    seen = {locale_fold(t) for t in tags}
    for clip in clips:
        for q in clip.queries:
            q = (q or "").strip()
            if not q or len(tags) >= 20:
                continue
            key = locale_fold(q)
            if key not in seen:
                seen.add(key)
                tags.append(q)
    return {"title": title[:100], "description": "\n".join(lines)[:5000], "tags": tags}


# --- üretim -------------------------------------------------------------------------

def _run(cmd: list[str], *, timeout: int = 600) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg başarısız ({r.returncode}): {r.stderr[-400:]}")


def normalize_clip(src: Path, dst: Path, *, ffmpeg: str = "ffmpeg", run=_run) -> Path:
    """Her parçayı aynı kodek/çözünürlük/ses biçimine getir (concat -c copy için şart)."""
    run([ffmpeg, "-y", "-v", "error", "-i", str(src),
         "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,fps={FPS},format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "160k",
         "-movflags", "+faststart", str(dst)])
    return dst


def still_to_clip(png: Path, dst: Path, seconds: float, *, ffmpeg: str = "ffmpeg", run=_run) -> Path:
    """Tek kareyi sessiz videoya çevir (intro/outro/siyah boşluk)."""
    run([ffmpeg, "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-t", f"{seconds:.2f}",
         "-i", str(png), "-f", "lavfi", "-t", f"{seconds:.2f}", "-i", "anullsrc=r=44100:cl=stereo",
         "-vf", f"scale={WIDTH}:{HEIGHT},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "160k", "-shortest",
         str(dst)])
    return dst


def concat_clips(parts: list[Path], out_path: Path, *, ffmpeg: str = "ffmpeg", run=_run) -> Path:
    lst = out_path.with_suffix(".txt")
    # concat demuxer göreli yolları LİSTE DOSYASININ dizinine göre çözer → mutlak yaz.
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    run([ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", "-movflags", "+faststart", str(out_path)])
    return out_path


def render_card_png(template_path: Path, context: dict, out_png: Path, *, browser: str = "chromium") -> Path:
    """Intro/outro kartını tek PNG'ye çiz (Playwright)."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from playwright.sync_api import sync_playwright
    env = Environment(loader=FileSystemLoader(str(template_path.parent)),
                      autoescape=select_autoescape(["html"]))
    html = env.get_template(template_path.name).render(**context)
    with sync_playwright() as p:
        b = getattr(p, browser).launch()
        page = b.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        page.set_content(html, wait_until="networkidle")
        page.screenshot(path=str(out_png), omit_background=False)
        b.close()
    return out_png


def build_compilation(clips: list[Clip], *, day: date, channel, templates_dir: Path, work_dir: Path,
                      out_path: Path, ffmpeg: str = "ffmpeg", browser: str = "chromium",
                      run=_run, render_png: Callable = render_card_png) -> Path:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    ctx = {"channel": channel, "day_label": format_day_tr(day), "headlines": [c.title for c in clips][:6],
           "count": len(clips), "handle": channel.handle, "language": channel.language}
    intro_png = render_png(Path(templates_dir) / "compilation_intro.html.j2", ctx, work_dir / "intro.png",
                           browser=browser)
    outro_png = render_png(Path(templates_dir) / "compilation_outro.html.j2", ctx, work_dir / "outro.png",
                           browser=browser)
    black_png = work_dir / "black.png"
    _write_black_png(black_png)

    parts: list[Path] = [still_to_clip(intro_png, work_dir / "p_intro.mp4", INTRO_S, ffmpeg=ffmpeg, run=run)]
    gap = still_to_clip(black_png, work_dir / "p_gap.mp4", GAP_S, ffmpeg=ffmpeg, run=run)
    for i, c in enumerate(clips):
        parts.append(normalize_clip(c.path, work_dir / f"p_{i:02d}.mp4", ffmpeg=ffmpeg, run=run))
        if i < len(clips) - 1:
            parts.append(gap)
    parts.append(still_to_clip(outro_png, work_dir / "p_outro.mp4", OUTRO_S, ffmpeg=ffmpeg, run=run))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return concat_clips(parts, out_path, ffmpeg=ffmpeg, run=run)


def _write_black_png(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0)).save(path)


def produce_daily_compilation(channel, *, eng, day: date, templates_dir: Path, output_root: Path,
                              ffmpeg: str = "ffmpeg", browser: str = "chromium",
                              tz: str = "Europe/Istanbul", log=log, force: bool = False,
                              probe: Callable[[Path], float] | None = None,
                              run=_run, render_png: Callable = render_card_png) -> int | None:
    """Günün derlemesini üret, DB'ye yaz, ``short_id`` döndür. Süre yetmezse None.
    ``force`` yalnız panel düğmesinde: uyarıya rağmen kısa derleme istenirse."""
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe") if "ffmpeg" in ffmpeg else "ffprobe"
    probe = probe or (lambda p: probe_duration_s(p, ffprobe=ffprobe))
    clips = pick_day_clips(eng, channel.slug, day, tz=tz, probe=probe)
    total = total_seconds(clips)
    log.info(f"[derleme] {channel.slug} {day}: {len(clips)} klip, toplam {total:.0f}s "
             f"(eşik {MIN_TOTAL_S:.0f}s)")
    if not clips:
        return None
    if total < MIN_TOTAL_S and not force:
        log.info("[derleme] süre eşiğin altında — Shorts sayılır, atlandı")
        return None

    out_dir = Path(output_root) / channel.slug / "derleme"
    out_path = out_dir / f"{day.isoformat()}.mp4"
    work_dir = out_dir / f".work-{day.isoformat()}"
    build_compilation(clips, day=day, channel=channel, templates_dir=templates_dir, work_dir=work_dir,
                      out_path=out_path, ffmpeg=ffmpeg, browser=browser, run=run, render_png=render_png)
    try:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
    except OSError:
        pass

    guid = f"{COMPILATION_PREFIX}{channel.slug}:{day.isoformat()}"
    meta = build_compilation_metadata(day, clips, channel_name=channel.name, handle=channel.handle,
                                      language=channel.language)
    # Aynı gün yeniden üretildiyse eski satır silinmiş sayılır (dosya üzerine yazıldı).
    with eng.begin() as conn:
        conn.execute(shorts.update().where(shorts.c.rss_item_guid == guid)
                     .where(shorts.c.deleted_at.is_(None))
                     .values(deleted_at=datetime.now(timezone.utc).replace(tzinfo=None)))
    script_json = json.dumps({
        "kind": "compilation", "day": day.isoformat(),
        "clip_ids": [c.short_id for c in clips],
        "headlines": [c.title for c in clips],
        "chapters": chapters(clips),
        "compilation_meta": meta,
        # Panel /shorts/<id> bu alanları bekliyor
        "header_top": "GÜNÜN DERLEMESİ", "header_bottom": format_day_tr(day),
        "body_paragraph": meta["description"][:800],
    }, ensure_ascii=False)
    short_id = record_short(eng, channel=channel.slug, rss_item_guid=guid, title=meta["title"],
                            file_path=str(out_path), duration_s=int(round(total)),
                            script_json=script_json, render_ms=0)
    log.info(f"[derleme] → {out_path} ({total:.0f}s) short_id={short_id}")
    return short_id
