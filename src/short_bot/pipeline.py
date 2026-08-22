"""Pipeline orchestrator: runs all 8 stages, persists to DB, writes per-run log."""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
import threading
import time
import hashlib
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock, Timeout

from short_bot.config import ChannelConfig, Settings, resolve_ai_call
from short_bot.reel import RunCancelled
from short_bot.db import (
    is_run_cancelled,
    init_db, mark_processed, record_short, record_rss_item,
    start_run, finish_run, get_last_youtube_upload_at,
    get_feed,
    recent_narration_variations,
)
from short_bot.youtube import auth as _yt_auth
from short_bot.youtube.auto_upload import (
    should_auto_upload, run_auto_upload,
)
from short_bot.models import RenderJob
from short_bot.fetcher import fetch_rss, fetch_feed_url
from short_bot.trends.trending_now import fetch_trending_items
from short_bot.formats import channel_format
from short_bot.dedup import filter_new
from short_bot.scorer import score_items, select_top, select_newest_above, select_by_volume
from short_bot.extractor import (
    extract_article,
    extract_og_image_url,
    _is_google_news_url,
)
from short_bot.script_writer import write_script
from short_bot import run_context
from short_bot.assets import download_and_blur_thumb, pick_music
from short_bot.renderer import render_frames, build_html
from short_bot.overflow import (
    OverflowReport,
    check_overflow,
    format_feedback,
    truncate_to_fit,
)
from short_bot.templates_config import ARCHETYPE_OVERFLOW_FIELDS
from short_bot.composer import compose_video
from short_bot.locale import ui_labels_for, trend_region_for
from short_bot.generator import (
    GeneratorRetryExhausted, check_duplicate, generate_quote,
)
from short_bot.generated_db import (
    generated_id_for_text, insert_generated, recent_generated_texts,
    topic_distribution, update_generated_short_id,
)
from short_bot.image_picker import pick_image_for_generator
import os
import secrets as _secrets_mod  # avoid shadowing the local `secrets_path` var
from dataclasses import replace as _dc_replace

from short_bot.text_normalize import locale_fold
import short_bot.pexels as _pexels_mod
from short_bot.pexels import (
    load_secrets as _load_secrets,
    pick_query_for_archetype,
    resolve_pexels_api_key,
    resolve_openai_api_key,
)
from short_bot.dna import DnaSpec, build_css_override, generate_dna_for_video
from short_bot.dna_cache import (
    increment_hit_count, lookup_cached_dna, save_cached_dna,
)
from short_bot.embeddings import EmbeddingError, embed_text
from short_bot.locale import trend_region_for
from short_bot.models import ScoredItem

_GENERATOR_TOPIC_DIST_DAYS = 7   # window for topic_distribution Sonnet hint
_IMAGE_RETRY_MAX = 3   # try this many top candidates before giving up on image


def _is_recent(pub_date: datetime | None, cutoff: datetime) -> bool:
    """True if pub_date is at or after cutoff. Items without pub_date are rejected
    (Google News normally provides one — missing date most often means a re-syndicated
    aggregator entry with no fresh signal)."""
    if pub_date is None:
        return False
    aware = pub_date if pub_date.tzinfo else pub_date.replace(tzinfo=timezone.utc)
    return aware >= cutoff


def _filter_negative_keywords(items: list, negative_keywords: list[str],
                              language: str) -> list:
    """Başlığında negatif anahtar kelime geçen haberleri eler.

    KÜÇÜLTME DİLE DUYARLI olmalı: Python'un `.lower()`'ı "CANLI" → "canli"
    (noktalı i) verir, anahtar kelime ise "canlı"dır (noktasız ı) — eşleşmez ve
    filtre SESSİZCE hiçbir şey elemez. Aslan Gündem+'a 'canlı' eklendiği hâlde
    "CANLI | Galatasaray alıyor" başlıklı canlı blog geçip gitti (ölçüldü).
    locale_fold Türkçede I/İ eşlemesini yapar, başka dillerde casefold'a düşer
    (Almancada 'I'nin küçüğü 'ı' değildir).

    `language` ZORUNLU, varsayılanı yok: Türkçe eşlemesini İspanyolca başlığa
    uygulamak "EN DIRECTO"yu "en dırecto" yapar ve 'en directo' HİÇ eşleşmez —
    yani yanlış bir varsayılan, filtrenin çalıştığını sanırken sıfır şey elemesi
    demektir.
    """
    if not negative_keywords:
        return items
    needles = [locale_fold(k.strip(), language)
               for k in negative_keywords if k.strip()]
    if not needles:
        return items
    return [
        i for i in items
        if not any(n in locale_fold(i.title, language) for n in needles)
    ]


def _apply_category_quota(
    scored: list[ScoredItem],
    *,
    channel: ChannelConfig,
    eng,
    log: logging.Logger,
) -> list[ScoredItem]:
    """Günlük kotasını doldurmuş konuların aday puanını düşür.

    Puanlayıcı havuzun konu dağılımını olduğu gibi yayına geçiriyordu: 442
    videoluk analizde üretimin %50'si gelen-transferdi ve o en zayıf
    performanslı kategoriydi. Kota, aynı konunun art arda seçilmesini kırar.
    Kotası olmayan kanallarda hiçbir etkisi yok.
    """
    if not channel.category_quota_per_day:
        return scored
    from short_bot.db import count_recent_categories
    from short_bot.scorer import apply_category_quota

    produced = count_recent_categories(eng, channel.slug, hours=24)
    out = apply_category_quota(scored, produced=produced,
                               quota=channel.category_quota_per_day,
                               floor=channel.min_score)
    doymus = [c for c, limit in channel.category_quota_per_day.items()
              if produced.get(c, 0) >= limit]
    if doymus:
        log.info(f"  [kota] doymuş konu(lar) geri çekildi: {', '.join(doymus)} "
                 f"(son 24s üretim: {produced})")
    return out


def _apply_saga_penalty(
    scored: list[ScoredItem],
    *,
    channel: ChannelConfig,
    eng,
    log: logging.Logger,
) -> list[ScoredItem]:
    """Aynı öznenin tekrarında aday puanını kademeli düşür.

    Kategori kotasından SONRA çalışır ve bu sıra bilinçlidir: kota puanı
    min_score'a sabitler, saga cezası onu tabanın ALTINA indirebilir. Kota
    konu çeşitliliği aracıdır, saga sınırı tekrar vetosudur; çatışırlarsa
    veto kazanmalıdır.

    Gerekçe (29 günlük ölçüm): "Batrakov" 15 günde 4 videoya çıktı. Mevcut
    dedup neredeyse aynı HABERİ yakalıyor, günlere yayılan aynı HİKÂYEYİ
    değil.

    Cezası 0.0 olan kanallarda (varsayılan) hiçbir etkisi yok.
    """
    if not channel.saga_penalty_per_repeat:
        return scored
    from short_bot.db import count_recent_subjects
    from short_bot.scorer import apply_saga_penalty, saga_repeat_count

    produced = count_recent_subjects(eng, channel.slug,
                                     days=channel.saga_window_days)
    out = apply_saga_penalty(scored, produced=produced,
                             step=channel.saga_penalty_per_repeat)
    for before, after in zip(scored, out):
        if after.score < before.score:
            n = saga_repeat_count(before.subject, produced)
            log.info(f"  [saga] '{before.subject}' son "
                     f"{channel.saga_window_days}g'de {n} kez geçti → "
                     f"puan {before.score:.1f}→{after.score:.1f}")
    return out


def _apply_trend_boost(
    scored: list[ScoredItem],
    *,
    channel: ChannelConfig,
    settings: Settings,
    cache_dir: Path,
    secrets_path: Path,
    log: logging.Logger,
) -> list[ScoredItem]:
    """Augment each ScoredItem.score by +trend_boost when its headline
    matches a currently trending term in the channel's region.

    Graceful: any failure (no cache, no api key, network error) returns
    the input list unchanged. Boost amount + matched term shown in log.
    """
    if channel.trend_boost is None or not channel.trend_boost.enabled:
        return scored
    if not settings.trends.enabled:
        log.info("  [trends] settings.trends.enabled=false -- skipping boost")
        return scored
    if not scored:
        return scored

    from short_bot.trends.aggregator import get_or_refresh
    from short_bot.trends.matcher import compute_trend_boost

    tb = channel.trend_boost
    region = tb.region_override or trend_region_for(channel.language)
    sources = list(tb.sources) if tb.sources else list(settings.trends.default_sources)
    secrets = _load_secrets(secrets_path)
    yt_key = secrets.get("youtube_api_key", "") or ""

    try:
        cache = get_or_refresh(
            region, sources=sources, youtube_api_key=yt_key,
            cache_dir=cache_dir / "trends",
            max_age_minutes=settings.trends.cache_max_age_minutes,
        )
    except Exception as e:  # noqa: BLE001 -- never let trend fetch break pipeline
        log.warning(f"  [trends] fetch failed: {e} -- skipping boost")
        return scored

    if cache is None or not cache.items:
        log.info(f"  [trends] no trends loaded for region={region} -- skipping boost")
        return scored

    log.info(f"  [trends] {len(cache.items)} terms (region={region}, "
             f"age={cache.age_minutes():.0f}m, sources={','.join(cache.sources)})")

    boosted: list[ScoredItem] = []
    boost_count = 0
    for s in scored:
        boost, matches = compute_trend_boost(
            s.item.title, cache.items,
            max_boost=tb.max_boost,
            min_term_length=tb.min_term_length,
            exclude_terms=tb.exclude_terms,
            fuzzy_threshold=tb.fuzzy_threshold,
        )
        if boost <= 0:
            boosted.append(s)
            continue
        new_score = min(10.0, s.score + boost)
        boost_count += 1
        top = matches[0]
        log.info(
            f"  trend boost +{boost:.2f} "
            f"[{top.match_type} rank#{top.item.rank} '{top.item.term[:60]}'] "
            f"{s.score:.1f}->{new_score:.1f} | {s.item.title[:70]}"
        )
        # `replace` ŞART — burada `ScoredItem(...)` YENİDEN KURULUYORDU ve
        # sayılmayan her alan sessizce varsayılanına düşüyordu: `category` ve
        # `subject` boşalıyordu. Sonucu, tam olarak engellenmek istenen durumdu:
        # boost'lanan aday hem kategori kotasını hem saga vetosunu ATLIYOR
        # (`_apply_trend_boost` ikisinden de ÖNCE koşar), üstüne +2.0'a kadar
        # fazladan puan taşıdığı için seçilme ihtimali de artıyordu. Seçilirse
        # `script_json`'a `subject=""` yazılıyor ve o video da sayaca hiç
        # girmiyordu. Ölçüm: üretim günlüklerinde boost'lanan terimler saga
        # adlarının kendisi ("zaniolo" tek koşuda iki kez, "bensebaini" iki
        # kez) — bir hikâye zaten TEKRAR işlendiği için trend oluyor.
        # Yeniden kurmak yerine kopyalamak, ileride eklenecek alanların da
        # aynı şekilde düşmesini engeller.
        boosted.append(replace(
            s,
            score=new_score,
            reasoning=f"{s.reasoning} [trend+{boost:.2f}]",
        ))

    if boost_count == 0:
        log.info("  [trends] no candidate headlines matched any trending term")
    else:
        log.info(f"  [trends] {boost_count}/{len(scored)} item(s) boosted")
    return boosted


def _resolve_dna_for_video(
    *,
    channel: ChannelConfig,
    headline: str,
    body: str,
    log: logging.Logger,
    claude_path: str,
    secrets_path: Path,
    templates_dir: Path,
    eng,
    model: str = "opus",
    backend: str = "claude_cli",
    api_key: str | None = None,
) -> tuple[DnaSpec, Path] | None:
    """For dynamic_dna channels: lookup cache or generate per-video DNA.

    Returns (dna, css_path) on success or None on any failure
    (caller falls back to channel.dna or channel.template).
    """
    if not channel.dynamic_dna:
        return None

    topic_text = f"{headline}\n{body[:200]}"

    # 1. Resolve key + embed
    api_key = resolve_openai_api_key(_load_secrets(secrets_path))
    if not api_key:
        log.warning("  [dna] no openai_api_key configured → fallback to static")
        return None
    try:
        emb = embed_text(topic_text, api_key=api_key)
    except EmbeddingError as e:
        log.warning(f"  [dna] embedding failed: {e} → fallback to static")
        return None

    css_dir = templates_dir / "css"

    # 2. Cache lookup
    hit = lookup_cached_dna(eng, channel.slug, emb, threshold=0.85)
    if hit is not None:
        css_path = css_dir / hit.css_filename
        if css_path.exists():
            log.info(
                f"  [dna] cache HIT id={hit.id} archetype={hit.archetype} "
                f"(cos={hit.score:.3f})"
            )
            increment_hit_count(eng, hit.id)
            return hit.dna, css_path
        # CSS missing on disk (manual cleanup, etc.) — treat as miss, fall through
        log.warning(
            f"  [dna] cache HIT id={hit.id} but {css_path.name} missing → regenerating"
        )

    # 3. Cache miss → generate
    log.info("  [dna] cache MISS → generating (Opus)…")
    try:
        dna = generate_dna_for_video(
            channel=channel, headline=headline, body=body,
            claude_path=claude_path, model=model,
            backend=backend, api_key=api_key,
        )
    except Exception as e:  # broad: timeout, JSON parse, validation, etc.
        log.warning(f"  [dna] generation failed: {e} → fallback to static")
        return None

    # 4. Save (DNA + CSS file + cache row)
    try:
        css_text = build_css_override(dna)
        css_filename = f"dynamic-{channel.slug}-{_secrets_mod.token_hex(3)}.css"
        css_path = css_dir / css_filename
        css_dir.mkdir(parents=True, exist_ok=True)
        css_path.write_text(css_text, encoding="utf-8")
        save_cached_dna(eng, channel.slug, topic_text, emb, dna, css_filename)
        log.info(f"  [dna] saved: archetype={dna.archetype} css={css_filename}")
        return dna, css_path
    except OSError as e:
        log.warning(f"  [dna] save failed: {e} → fallback to static")
        return None


def _resolve_ui_labels(channel: ChannelConfig) -> dict[str, str]:
    labels = dict(ui_labels_for(channel.language))
    if channel.dna and channel.dna.ui_badge.strip():
        labels["breaking"] = channel.dna.ui_badge.strip()
    return labels


def _maybe_auto_upload(*, eng, short_id: int, channel, picked_score: float | None,
                       log, yt_creds_root: Path, claude_path: str,
                       model: str, cooldown_minutes: int = 5,
                       secrets_path: Path | None = None,
                       backend: str = "claude_cli",
                       api_key: str | None = None,
                       defer: bool = False) -> None:
    """Post-render hook: if channel opts in, evaluate gates + run upload.

    ``defer=True`` (AUTOPILOT): YÜKLEME BURADA YAPILMAZ.

    Autopilot videoyu KENDİ yükleyecek — gizli + publishAt ile, planlanmış slot
    saatine. Burada da yüklersek kanalda İKİ video olur: biri anında (public), biri
    zamanlı. Hiçbir hata vermez; yalnız kanal bozulur ve bütün zamanlama çöker.
    """
    if defer:
        log.info("[YT] auto-upload ERTELENDİ — autopilot slot saatine yükleyecek")
        return
    if channel.youtube is None or not channel.youtube.auto_upload:
        return
    # Token refresh için proxy session hazır olsun (varsa)
    proxy_session = None
    if secrets_path:
        from short_bot.youtube.proxy import (
            load_channel_proxy_url, build_proxied_requests_session,
        )
        proxy_url = load_channel_proxy_url(channel.slug, secrets_path)
        if proxy_url:
            proxy_session = build_proxied_requests_session(proxy_url)
    _cslug = _yt_auth.creds_slug(channel)
    creds = _yt_auth.load_credentials(
        yt_creds_root, _cslug, proxy_session=proxy_session,
    )
    if creds is None:
        log.info(f"[YT] auto-upload atlandı — '{_cslug}' bağlanmamış (token.json yok)")
        return
    if _cslug != channel.slug:
        log.info(f"[YT] '{_cslug}' kanalının bağlantısı kullanılıyor")
    last_at = get_last_youtube_upload_at(eng)
    decision = should_auto_upload(
        channel=channel, picked_score=picked_score,
        last_upload_at=last_at, cooldown_minutes=cooldown_minutes,
    )
    if not decision.eligible:
        log.info(f"[YT] auto-upload atlandı — {decision.reason}")
        return
    log.info(f"[YT] auto-upload başlıyor (short {short_id})")
    try:
        result = run_auto_upload(
            eng=eng, short_id=short_id, channel=channel,
            credentials=creds, claude_path=claude_path, model=model,
            secrets_path=secrets_path, backend=backend, api_key=api_key,
        )
        log.info(f"[YT] auto-upload başarılı: {result.video_url}")
    except Exception as e:
        log.warning(f"[YT] auto-upload hatası: {e}")


@dataclass
class RunResult:
    run_id: int
    status: str           # 'success' | 'failed' | 'no_candidates' | 'cancelled'
    short_path: Path | None
    error: str | None
    # AUTOPILOT: slot hangi videoya bağlanacak? Yükleme üretimden AYRI koştuğu için
    # yolu değil KİMLİĞİ taşımak zorundayız (upload short_id ile çalışıyor).
    short_id: int | None = None


def _slugify(text: str, max_len: int = 60) -> str:
    ham = text or ""
    t = unicodedata.normalize("NFKD", ham)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    # ANLAMLI mı? Japonca "藤井風 12月のタイ公演中止を発表" başlığından geriye
    # yalnız "12" kalıyordu — teknik olarak boş değil ama dosya adı olarak
    # işe yaramaz (ölçüldü: 2026-08-22_12.mp4). Harf taşımayan ya da çok kısa
    # kalan slug da yedeğe düşer.
    if t and len(t.replace("-", "")) >= 3 and any(c.isalpha() for c in t):
        return t[:max_len]
    # ASCII'YE İNDİRGENEMEYEN BAŞLIK (CJK, Kiril…): eskiden HEPSİ "haber"e
    # düşüyordu ve klasör haber.mp4 / haber-2.mp4 diye doluyordu — hangi
    # videonun hangisi olduğu okunamaz, üstelik "haber" Japonca kanalda
    # Türkçe bir kelime (2026-08-22, ilk gerçek Japonca koşuda ölçüldü).
    # Başlıktan türeyen özet AYIRT EDİCİ ve denemeler arasında KARARLI —
    # yol üretim başında bir kez seçilip yeniden denemelerce paylaşılıyor.
    if ham.strip():
        return "video-" + hashlib.sha1(ham.encode("utf-8")).hexdigest()[:10]
    return "haber"


# Aynı gün + aynı başlık = AYNI DOSYA ADI. İkinci üretim birincinin üzerine YAZAR.
# GERÇEK KAYIP: short 801 ve 802 aynı konuyu (Löwenzahn) aynı gün ürettiği için
# ikisi de 2026-07-14_jeder-teil-des-lowenzahns-....mp4 yolunu aldı. 802 yazınca
# 801'in videosu SESSİZCE yok oldu; veritabanında iki kayıt AYNI dosyayı gösteriyordu.
# Sessiz veri kaybı — kullanıcı ancak eski videoyu açmaya çalışınca fark eder.
MAX_OUTPUT_SUFFIX = 99


def unique_output_path(out_dir: Path, stem: str, suffix: str = ".mp4") -> Path:
    """Var olan bir dosyanın ÜZERİNE YAZMAYAN yol: ``stem.mp4`` dolu ise ``stem-2.mp4``…

    Yol ÜRETİM BAŞINDA bir kez seçilir; koşum içindeki yeniden denemeler (senaryo
    3 deneme vb.) aynı yolu paylaşır — istenen davranış bu.
    """
    aday = out_dir / f"{stem}{suffix}"
    if not aday.exists():
        return aday
    for n in range(2, MAX_OUTPUT_SUFFIX + 1):
        aday = out_dir / f"{stem}-{n}{suffix}"
        if not aday.exists():
            return aday
    # 99 sürüm — burada bir şey ters gitmiş demektir; üzerine yazmaktansa PATLA.
    raise RuntimeError(
        f"çıktı adı üretilemedi: {out_dir / stem}{suffix} ve -2..-{MAX_OUTPUT_SUFFIX} dolu")


# _build_cta_sfx KALDIRILDI (2026-07-16): CTA kapanış kartı silindi.


_RUN_SUB_LOGGERS = (
    "short_bot.assets",
    "short_bot.claude_cli",
    "short_bot.composer",
    "short_bot.dedup",
    "short_bot.dna",
    "short_bot.dna_smoke",
    "short_bot.extractor",
    "short_bot.fetcher",
    "short_bot.generator",
    "short_bot.image_picker",
    "short_bot.image_search",
    "short_bot.pexels",
    "short_bot.renderer",
    "short_bot.scorer",
    "short_bot.script_writer",
    "short_bot.wikimedia_search",
    "short_bot.youtube.auth",
    "short_bot.youtube.uploader",
    # Reel (footage-sürüklü) boru hattı — bunlar eksikken reel koşusunun logu
    # "reel modu: footage-sürüklü üretim" satırında donuyor, asıl teşhis bilgisi
    # (kurgucunun kararı, footage red gerekçeleri, faz süreleri) yalnız stdout'a
    # gidiyordu; panelden bakan kullanıcı hiçbirini göremiyordu.
    "short_bot.assets_library",
    "short_bot.footage_matcher",
    "short_bot.footage_sources",
    "short_bot.reel",
    "short_bot.reel_narration",
    "short_bot.reel_director",
    "short_bot.reel_render",
    "short_bot.tts.align",
    "short_bot.voiced",
)


# Thread-local active run path so concurrent pipeline runs (different
# channels firing in parallel) keep their sub-logger output (image_picker,
# scorer, etc.) inside their own log files. Without this, every run's
# FileHandler is attached to the same shared sub-logger and they all
# receive every log record — galatasaray's run log was getting NFL/Putin
# query lines from other channels' concurrent runs.
# Thread-local artık short_bot.run_context'te: paralel vision çağrıları (worker
# thread'ler) ebeveynin koşusunu DEVRALABİLSİN diye. İki ayrı depo olsaydı devralma
# çalışmaz ve worker logları run dosyasına hiç düşmezdi (gerçek ölçüm yanılsaması:
# "12 klip için 1 vision yargısı" — oysa 24 yargı yapılmıştı, görünmüyorlardı).
def _set_active_run_log_path(log_path: str) -> None:
    run_context.set_log_path(log_path)


def _clear_active_run_log_path() -> None:
    run_context.clear_log_path()


class _RunFileFilter(logging.Filter):
    """Only let a record through if the calling thread's active run log
    path matches the handler's log path."""

    def __init__(self, log_path: str) -> None:
        super().__init__()
        self._log_path = log_path

    def filter(self, record: logging.LogRecord) -> bool:
        return run_context.get_log_path() == self._log_path


def _setup_logger(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"shortbot.run.{log_path.stem}")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(sh)
    # Forward asset-fase module logs to this run's file so failure reasons
    # (DDG empty, Claude vision reject, etc.) show up in the run log.
    sub_fmt = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
    log_path_str = str(log_path)
    for name in _RUN_SUB_LOGGERS:
        sub = logging.getLogger(name)
        sub.setLevel(logging.INFO)
        sub_fh = logging.FileHandler(log_path, encoding="utf-8")
        sub_fh.setFormatter(sub_fmt)
        sub_fh.addFilter(_RunFileFilter(log_path_str))
        sub_fh._shortbot_run = True
        sub.addHandler(sub_fh)
    return logger


def _teardown_logger(log: logging.Logger) -> None:
    for h in list(log.handlers):
        try:
            h.close()
        except Exception:
            pass
        log.removeHandler(h)
    for name in _RUN_SUB_LOGGERS:
        sub = logging.getLogger(name)
        for h in list(sub.handlers):
            if getattr(h, "_shortbot_run", False):
                try:
                    h.close()
                except Exception:
                    pass
                sub.removeHandler(h)


def _resolve_pexels_bg(*, channel, cache_dir, secrets_path, log) -> Path | None:
    """Search/download a Pexels bg video for `channel`. None on opt-out / failure."""
    if channel.bg_video is None or not channel.bg_video.enabled:
        return None
    api_key = resolve_pexels_api_key(_load_secrets(secrets_path))
    if not api_key:
        log.warning("  bg_video enabled but PEXELS_API_KEY not set → fallback")
        return None
    archetype = (channel.dna.archetype if channel.dna is not None
                 else channel.template)
    query = pick_query_for_archetype(archetype)
    log.info(f"  pexels search: query={query!r}")
    candidates = _pexels_mod.search_videos(query, api_key, max_results=8)
    if not candidates:
        log.warning("  pexels: no candidates returned → fallback")
        return None
    # Shuffle candidates so successive runs don't always pick the FIRST
    # (most popular) result. Combined with random page in search_videos this
    # gives reasonable variety across renders for the same channel.
    import random as _rand
    _rand.shuffle(candidates)
    bg_cache = Path(cache_dir) / "pexels_videos"
    for cand in candidates:
        path = _pexels_mod.download_video(cand.url, bg_cache)
        if path is not None:
            log.info(f"  pexels accepted: {path.name} (id={cand.id})")
            return path
    log.warning("  pexels: all candidate downloads failed → fallback")
    return None


def current_app_secrets_path() -> Path:
    """Resolve the secrets path (data/secrets.yaml relative to cwd).

    Pipeline runs both inside Flask (web 'Run now') and standalone (CLI/cron).
    Keep simple: data/secrets.yaml next to the cwd's data directory. If a project-level
    DATA_DIR helper exists in the future, swap to that — but don't refactor for it now."""
    return Path("data") / "secrets.yaml"


def run_pipeline(**kw) -> RunResult:
    """Üretim hattı — kanalın DİLİ kurulmuş hâlde koşar.

    Bu ince sarmalayıcının tek işi ``language(channel.language)`` bağlamını açmak.
    Gerekli, çünkü aksan temizleyicisi (text_normalize.strip_foreign_diacritics) bir
    pydantic ``field_validator``'dan çağrılıyor ve validator'ın kanalın dilini görmesinin
    başka yolu yok. Kurulmazsa Almanca "Täglich" → "Taglich" olur; TTS yanlış okur,
    altyazı yanlış görünür ve BUNU HİÇBİR HATA BİLDİRMEZ.

    Gövde ``_run_pipeline_inner``'da; imza ve tüm yorumlar orada. (Parametrelerin hepsi
    anahtar-kelimeli olduğu için ``**kw`` ile aktarmak güvenli ve gövdeyi yeniden
    girintilemekten doğacak riski sıfırlıyor.)
    """
    from short_bot.text_normalize import language
    with language(kw["channel"].language):
        return _run_pipeline_inner(**kw)


def _run_pipeline_inner(
    *,
    channel: ChannelConfig,
    settings: Settings,
    db_path: Path,
    music_root: Path,
    templates_dir: Path,
    cache_dir: Path,
    logs_dir: Path,
    lock_dir: Path | None = None,
    trigger: str = "cli",
    preselected_item=None,   # NewsItem | None — manuel feed seciminde dolu
    curated_gem=None,        # dict | None — kürate klip onayında dolu (SP3, bkz. curated_pipeline)
    forced_topic: str | None = None,   # panelden secilen baslik (yeniden uret / konu bankasi)
    # AUTOPILOT: yüklemeyi autopilot yapacak (gizli + publishAt, slot saatine).
    # True iken pipeline HİÇBİR koşulda yüklemez — yoksa ÇİFTE YÜKLEME olur.
    defer_upload: bool = False,
    # BAĞIMSIZ VİDEO: seri kapalıymış gibi üret. Seri açık olsa bile bölüm
    # planlanmaz, ark tüketilmez, bölüm kaydedilmez.
    #
    # NEDEN: seri bölümü izleyiciye "#2 YARIN" diye söz veriyor. Günde 3 bölüm
    # üretilirse 3 bölümlük ark BİR GÜNDE biter ve #2 aynı gün yayınlanır — söz
    # YALAN olur ve abone takası çöker. Günde EN FAZLA 1 bölüm; kalan slotlar
    # bankadan bağımsız konu üretir (bkz. autopilot.KIND_STANDALONE).
    standalone: bool = False,
) -> RunResult:
    eng = init_db(db_path)
    log_path = logs_dir / f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{channel.slug}.log"
    log_rel = str(log_path)
    log = _setup_logger(log_path)
    _set_active_run_log_path(str(log_path))
    run_id = start_run(eng, channel.slug, trigger=trigger, log_path=log_rel)

    lock_dir = Path(lock_dir) if lock_dir else Path("data/locks")
    lock_path = lock_dir / f"{channel.slug}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_path), timeout=0)

    try:
        try:
            with lock:
                log.info(f"=== run {run_id} channel={channel.slug} "
                         f"trigger={trigger} source={channel.content_source} ===")
                if preselected_item is not None:
                    log.info(f"  preselected item: {preselected_item.title[:80]}")
                    res = _produce_from_item(
                        item=preselected_item, channel=channel, eng=eng,
                        settings=settings, log=log, music_root=music_root,
                        templates_dir=templates_dir, cache_dir=cache_dir,
                        run_id=run_id, score=None, defer_upload=defer_upload,
                    )
                    if res.status != "success":
                        finish_run(eng, run_id, status="no_candidates",
                                   short_id=None, error=res.error)
                    return res
                if curated_gem is not None:
                    # KÜRATE: seçilen Reddit klibini üret (indir→temizle→vision→senaryo→
                    # montaj→Short). Run/log/Akış makinesi burada; üretim mantığı ayrı.
                    log.info(f"  kürate cevher: {(curated_gem.get('title') or '')[:80]}")
                    from short_bot.curated_pipeline import produce_curated
                    secrets_path = (Path(eng.url.database).parent / "secrets.yaml"
                                    if eng.url.database else Path("data/secrets.yaml"))
                    short_id, out_path = produce_curated(
                        curated_gem, channel, settings=settings,
                        secrets=_load_secrets(secrets_path), db_path=db_path,
                        output_root=Path(channel.output_dir).parent,
                        music_root=music_root, templates_dir=templates_dir, log=log)
                    finish_run(eng, run_id, status="success", short_id=short_id,
                               error=None)
                    return RunResult(run_id=run_id, status="success",
                                     short_path=out_path, short_id=short_id, error=None)
                if channel.content_source == "curated":
                    # Kürate kanalı CEVHERSİZ çalıştı (cron/autopilot/'Şimdi üret') →
                    # en iyi ÜRETİLMEMİŞ cevheri otomatik seç + üret. (Eskiden buraya
                    # düşünce _run_rss'e gidip 'keywords boş olamaz' veriyordu.)
                    log.info("  kürate kanalı: cevher otomatik seçiliyor")
                    from short_bot.curated_pipeline import auto_produce_curated
                    secrets_path = (Path(eng.url.database).parent / "secrets.yaml"
                                    if eng.url.database else Path("data/secrets.yaml"))
                    short_id, out_path = auto_produce_curated(
                        channel, settings=settings, secrets=_load_secrets(secrets_path),
                        db_path=db_path, output_root=Path(channel.output_dir).parent,
                        music_root=music_root, templates_dir=templates_dir, log=log)
                    if short_id is None:
                        finish_run(eng, run_id, status="no_candidates", short_id=None,
                                   error="Taze kürate cevheri yok (hepsi üretilmiş).")
                        return RunResult(run_id=run_id, status="no_candidates",
                                         short_path=None, error="taze cevher yok")
                    finish_run(eng, run_id, status="success", short_id=short_id,
                               error=None)
                    return RunResult(run_id=run_id, status="success",
                                     short_path=out_path, short_id=short_id, error=None)
                if channel.content_source == "generator":
                    return _run_generator(
                        channel=channel, run_id=run_id, log=log, eng=eng,
                        settings=settings, music_root=music_root,
                        templates_dir=templates_dir, cache_dir=cache_dir,
                        forced_topic=forced_topic, defer_upload=defer_upload,
                        standalone=standalone,
                    )
                if channel.content_source == "feed":
                    return _run_feed(
                        channel=channel, run_id=run_id, log=log, eng=eng,
                        settings=settings, music_root=music_root,
                        templates_dir=templates_dir, cache_dir=cache_dir,
                        defer_upload=defer_upload,
                    )
                return _run_rss(
                    channel=channel, run_id=run_id, log=log, eng=eng,
                    settings=settings, music_root=music_root,
                    templates_dir=templates_dir, cache_dir=cache_dir,
                    defer_upload=defer_upload,
                )
        except Timeout:
            finish_run(eng, run_id, status="failed", short_id=None,
                       error="lock busy: pipeline already running for this channel")
            return RunResult(run_id=run_id, status="failed", short_path=None,
                             error="lock busy")
        except RunCancelled:
            # Kullanıcı panelden durdurdu — HATA DEĞİL. 'failed' yazmak yanıltır ve
            # kullanıcının bilerek verdiği kararı arıza gibi gösterir.
            log.info("koşu panelden iptal edildi")
            finish_run(eng, run_id, status="cancelled", short_id=None, error=None)
            return RunResult(run_id=run_id, status="cancelled", short_path=None, error=None)
        except Exception as e:
            log.exception("pipeline failed")
            finish_run(eng, run_id, status="failed", short_id=None, error=str(e))
            return RunResult(run_id=run_id, status="failed", short_path=None, error=str(e))
    finally:
        _teardown_logger(log)
        _clear_active_run_log_path()
        # Dispose engine to release the SQLite connection pool (CLI use case)
        eng.dispose()


def _produce_from_item(
    *, item, channel, eng, settings, log,
    music_root, templates_dir, cache_dir, run_id: int,
    score: float | None = None,
    subject: str = "",
    defer_upload: bool = False,
) -> RunResult:
    """Tek bir NewsItem'dan video üretir. Manuel ve otomatik yol paylaşır.

    Görsel bulunamazsa RunResult(status='image_rejected') döner (run'ı
    finish ETMEZ — çağıran karar verir: manuel'de hata, _run_rss'te sonraki
    aday). Başarıda run'ı finish EDER ve auto-upload tetikler.

    Caller, 'image_rejected' (veya 'success' dışı) dönüşte
    `finish_run(eng, run_id, status='no_candidates', ...)` çağırMAKLA
    yükümlüdür; aksi halde run satırı açık kalır.

    NOT: mark_processed burada RSS + üretilmiş-manşet embedding'iyle çağrılır —
    yani bu yoldan üretilen videolar da sonraki koşuların çok-kaynak dedup'ına
    katkı verir. (Eskiden yalnız guid+title yazılıyordu ve bu, panelden üretilen
    her video için dedup geçmişinde kör bir satır bırakıyordu.)

    `subject`: saga sayacının anahtarı — senaryo yazarı ÜRETMEZ, seçilen adayın
    (`ScoredItem.subject`) değeri kaydetmeden hemen önce script'e taşınır. YENİ
    ÇAĞIRAN EKLERKEN GEÇMEYİ UNUTMA: boş kalırsa video sayaca kör bir satır
    olarak girer ve saga sınırı sessizce eksik ateşler (bkz. yukarıdaki dedup
    hatası — aynı sınıf). Elle seçilen (preselected) item'da aday yoktur; ""
    kalması BİLİNÇLİDİR, tek seferlik video bir sagayı temsil etmez.
    """
    secrets_path = current_app_secrets_path()
    secrets = _load_secrets(secrets_path)
    script_call = resolve_ai_call(settings, secrets, "script")
    if script_call.backend == "claude_cli":
        script_model = (channel.script_model
                        or settings.claude_models.get("script")
                        or settings.claude_models.get("default", "haiku"))
    else:
        script_model = script_call.model
    # Kanal modeli ANLATIMA da geçsin. script_call aşağıda _render_and_compose'a,
    # oradan write_narration'a veriliyordu ve kanal ayarını GÖRMÜYORDU: aynı
    # kanalın haber kartı channel.script_model ile, seslendirme anlatımı ise
    # settings'teki modelle yazılıyordu.
    script_call = _dc_replace(script_call, model=script_model)

    article_url = item.link
    if _is_google_news_url(article_url):
        from short_bot.google_news_resolver import resolve as _resolve_gnews
        resolved = _resolve_gnews(article_url)
        if resolved:
            article_url = resolved

    log.info("  extract_article")
    body = extract_article(article_url)
    if body is None:
        body = item.description or item.title
        log.warning("  trafilatura empty → fallback description")

    log.info(f"  write_script (model={script_model})")
    if channel.template in ARCHETYPE_OVERFLOW_FIELDS:
        template_path = templates_dir / f"{channel.template}.html.j2"
        script, _retries = write_script_with_overflow_check(
            item=item, body_html=body, channel=channel,
            template_path=template_path,
            job_template_args={"music_path": Path("dummy.mp3"),
                               "ui_language": channel.language},
            max_retries=2, log=log,
            claude_path=script_call.claude_path, model=script_model,
            backend=script_call.backend, api_key=script_call.api_key,
        )
    else:
        script = write_script(
            item, body, claude_path=script_call.claude_path,
            channel=channel, model=script_model,
            backend=script_call.backend, api_key=script_call.api_key,
        )

    log.info("  assets/image")
    bg = None
    original_was_gnews = _is_google_news_url(item.link)
    og_url = extract_og_image_url(article_url)
    if og_url:
        bg = download_and_blur_thumb(og_url, cache_dir,
                                     blur_radius=channel.bg_image_blur)
    if bg is None and not original_was_gnews and item.thumb_url:
        bg = download_and_blur_thumb(item.thumb_url, cache_dir,
                                     blur_radius=channel.bg_image_blur)
    if bg is None:
        from short_bot.image_picker import pick_image_for_script
        vision_call = resolve_ai_call(settings, secrets, "vision")
        bg = pick_image_for_script(
            script, cache_dir / "images",
            claude_path=vision_call.claude_path, channel=channel,
            backend=vision_call.backend, api_key=vision_call.api_key,
            model=vision_call.model)
    if bg is None:
        log.warning("  no image → image_rejected")
        record_rss_item(eng, guid=item.guid, channel=channel.slug,
                        title=item.title, link=item.link, source=item.source,
                        pub_date=item.pub_date, thumb_url=item.thumb_url,
                        score=score, status="image_rejected")
        return RunResult(run_id=run_id, status="image_rejected",
                         short_path=None, error="no usable image")

    record_rss_item(eng, guid=item.guid, channel=channel.slug,
                    title=item.title, link=item.link, source=item.source,
                    pub_date=item.pub_date, thumb_url=item.thumb_url,
                    score=score, status="selected")

    music = pick_music(music_root, mood=script.mood, channel_slug=channel.slug)
    job = RenderJob(
        script=script, bg_image_path=bg, music_path=music,
        channel_colors=channel.colors, handle=channel.handle,
        duration_s=channel.duration_s, language=channel.language,
        rss_source=item.source,
    )

    with tempfile.TemporaryDirectory() as tmpd:
        frames_dir = Path(tmpd) / "frames"
        t0 = time.perf_counter()
        ui_labels = _resolve_ui_labels(channel)
        from short_bot.dna import build_css_override
        dna_call = resolve_ai_call(settings, secrets, "dna")
        resolved = _resolve_dna_for_video(
            channel=channel,
            headline=f"{script.header_top} {script.header_bottom}",
            body=script.body_paragraph, log=log,
            claude_path=dna_call.claude_path, secrets_path=secrets_path,
            templates_dir=templates_dir, eng=eng, model=dna_call.model,
            backend=dna_call.backend, api_key=dna_call.api_key)
        if resolved is not None:
            effective_dna, css_path = resolved
            dna_css = css_path.read_text(encoding="utf-8")
        else:
            effective_dna = channel.dna
            dna_css = build_css_override(channel.dna) if channel.dna else ""
        archetype = (effective_dna.archetype if effective_dna is not None
                     else channel.template)

        out_dir = Path(channel.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(item.title)
        out_path = unique_output_path(
            out_dir, f"{datetime.now(timezone.utc):%Y-%m-%d}_{slug}")
        sfx_overlays = []
        bg_video_path = _resolve_pexels_bg(
            channel=channel, cache_dir=cache_dir,
            secrets_path=secrets_path, log=log)
        # Voiced/yorum kanalı panelden (Canlı Gündem, RSS havuzu) seçilen haberle
        # de seslendirmeli üretsin: eskiden bu yol yalnız sessiz kart çiziyordu.
        _render_and_compose(
            job=job, archetype=archetype, templates_dir=templates_dir,
            frames_dir=frames_dir, music=music, out_path=out_path,
            channel=channel, settings=settings, secrets=secrets,
            ui_labels=ui_labels, dna_css=dna_css,
            animation_style=(effective_dna.animation_style
                             if effective_dna is not None else "none"),
            sfx_overlays=sfx_overlays, bg_video_path=bg_video_path,
            item=item, body=body, script=script, bg_image_path=bg,
            log=log, llm_call=script_call, cache_dir=cache_dir,
            recent_variations=tuple(recent_narration_variations(eng, channel.slug)),
        )
        render_ms = int((time.perf_counter() - t0) * 1000)
        log.info(f"  → {out_path.name} ({render_ms}ms)")

    # ÇOK-KAYNAK DEDUP PARİTESİ: bu kol (feed/manuel) eskiden embedding'siz
    # kaydediyordu, yani panelden "şimdi üret" ile çıkan her video dedup
    # geçmişine KÖR bir satır bırakıyordu: aynı haber ertesi gün başka bir
    # gazeteden geldiğinde 3. ve 4. katman karşılaştıracak bir şey bulamıyor,
    # yalnız GUID + başlık kalıyordu (farklı kaynak = farklı GUID = geçer).
    # Fail-open: embedding alınamazsa üretim yine kaydedilir.
    rss_embedding = None
    produced_embedding = None
    try:
        okey = resolve_openai_api_key(secrets)
        if okey:
            from short_bot.embeddings import embed_text as _embed
            rss_embedding = _embed(item.title, api_key=okey)
            produced_text = f"{script.header_top} {script.header_bottom}".strip()
            if produced_text:
                produced_embedding = _embed(produced_text, api_key=okey)
    except Exception as e:  # noqa: BLE001 — üretimi asla engellemez
        log.warning(f"  dedup embedding alınamadı: {e}")

    mark_processed(eng, item.guid, item.title, channel.slug,
                   embedding=rss_embedding,
                   produced_title_embedding=produced_embedding)
    # Saga sayacının anahtarı: senaryo yazarı üretmez, seçilen adaydan taşınır.
    short_id = record_short(
        eng, channel=channel.slug, rss_item_guid=item.guid,
        title=script.header_top + " " + script.header_bottom,
        file_path=str(out_path), duration_s=channel.duration_s,
        script_json=script.model_copy(update={
            "subject": subject,
            "search_queries": list(getattr(item, "trend_related", ()) or ())[:10],
        }).model_dump_json(),
        render_ms=render_ms)
    finish_run(eng, run_id, status="success", short_id=short_id, error=None)

    score_call = resolve_ai_call(settings, secrets, "default")
    yt_creds_root = (Path(eng.url.database).parent / "youtube_credentials").resolve() \
        if eng.url.database else Path("data/youtube_credentials").resolve()
    _maybe_auto_upload(
        eng=eng, short_id=short_id, channel=channel, picked_score=score,
        log=log, yt_creds_root=yt_creds_root,
        claude_path=score_call.claude_path, model=score_call.model,
        secrets_path=secrets_path, backend=score_call.backend,
        api_key=score_call.api_key, defer=defer_upload)
    log.info(f"=== success short_id={short_id} ===")
    return RunResult(run_id=run_id, status="success",
                     short_path=out_path, error=None, short_id=short_id)


_EXTRA_SOURCE_MAX_CHARS = 1500


def _extra_source_bodies(item, *, log) -> list[tuple[str, str]]:
    """Yorum formatı: trendin diğer makalelerinin gövdeleri ``[(url, gövde), …]``.
    Çekilemeyen atlanır; hiçbir hata üretimi durdurmaz (ana makale yeter)."""
    out: list[tuple[str, str]] = []
    for url in getattr(item, "extra_links", ()) or ():
        try:
            u = url
            if _is_google_news_url(u):
                from short_bot.google_news_resolver import resolve as _resolve_gnews
                u = _resolve_gnews(u) or u
            body = extract_article(u)
        except Exception as e:  # noqa: BLE001 — ek kaynak isteğe bağlı
            if log:
                log.info(f"  ek kaynak atlandı ({e}): {url[:80]}")
            continue
        if body and body.strip():
            out.append((url, body.strip()[:_EXTRA_SOURCE_MAX_CHARS]))
    if log and out:
        log.info(f"  ek kaynak: {len(out)} makale")
    return out


_SIBLING_WINDOW_H = 24


def _drop_sibling_coverage(items, *, channel, eng, log):
    """Aynı YouTube kanalına üreten KARDEŞ formatın son 24 saatte anlattığı
    olayları listeden düşür.

    NEDEN (ölçüldü 2026-08-20): ``trends_intent`` havuzu ayırmak için var ama
    bir FİLTRE değil TERCİH — havuzda tercih edilen tür yoksa iki format da en
    yüksek hacimli olaya düşüyor. Alman trendlerinde soru sorgusu oranı **%0**
    ölçüldü (Türkçede %8), yani orada tercih neredeyse hiç bağlamıyor ve
    Deutschland Kompakt ile Klartext aynı haberi iki kez anlatıyordu — TEK bir
    YouTube kanalında aynı olayın iki videosu demek.

    Dedup kanal bazlıdır ve öyle kalmalı (ayrı kanallar aynı olayı işleyebilir);
    burada kısıt yalnız KİMLİĞİ PAYLAŞANLAR için geçerli: ``credentials_from``
    dolu olan kanal, ödünç aldığı kanalın işlediği olaya girmez.
    """
    yt = getattr(channel, "youtube", None)
    sibling = (getattr(yt, "credentials_from", None) or "").strip()
    if not sibling or sibling == channel.slug or not items:
        return items
    from datetime import timedelta as _td
    from short_bot.db import _utcnow, produced_guids_since
    # shorts.created_at NAİF UTC saklanıyor (db._utcnow) — karşılaştırma aynı
    # kaynaktan gelmeli, yoksa saat farkı pencereyi kaydırır.
    since = (_utcnow() - _td(hours=_SIBLING_WINDOW_H)).replace(tzinfo=None)
    try:
        gorulen = produced_guids_since(eng, sibling, since)
    except Exception as e:  # noqa: BLE001 — kısıt üretimi asla durdurmaz
        log.warning(f"  kardeş kanal kontrolü atlandı: {e}")
        return items
    if not gorulen:
        return items
    kalan = [i for i in items if i.guid not in gorulen]
    if len(kalan) != len(items):
        log.info(f"  kardeş kanal '{sibling}' son {_SIBLING_WINDOW_H} saatte "
                 f"{len(items) - len(kalan)} olayı zaten anlattı → düşürüldü")
    return kalan or items      # hepsi düşerse boş dönme: kanal susmasın


def _ticker_items_for_trends(
    scored: list[ScoredItem], picked: ScoredItem, *, min_score: float, limit: int = 4,
) -> tuple[str, ...]:
    """flas şablonunun 'SIRADA' ticker'ı: koşuda kapıyı geçen (≥ min_score) ama
    seçilmeyen diğer olaylar, hacme göre. Kapının altında kalanlar (hava durumu,
    hisse…) ticker'a da girmez — yoksa elenen şey arka kapıdan ekrana döner."""
    others = [s for s in scored
              if s.item.guid != picked.item.guid and s.score >= min_score]
    others.sort(key=lambda s: (s.item.trend_volume, s.score), reverse=True)
    return tuple(s.item.title.strip() for s in others[:limit] if s.item.title.strip())


def _vertical_starved(items, channel) -> bool:
    """Dikey süzgecinden yeterli aday çıkmadı mı?

    Yalnız dikeyi OLAN kanalda anlamlıdır: dikeysiz kanalda eski davranış bit
    bit korunur. True dönerse koşu boş biter — havuz GENİŞLETİLMEZ.
    """
    if not getattr(channel, "trends_vertical", None):
        return False
    return len(items) < channel.trends_min_candidates


def _run_rss(*, channel, run_id, log, eng, settings,
             music_root, templates_dir, cache_dir,
             defer_upload: bool = False) -> RunResult:
    """Existing 8-stage RSS pipeline body, extracted verbatim. Returns RunResult.

    content_source="trends" de bu gövdeyi kullanır: yalnız [1/8] kaynağı ve
    seçim kuralı farklıdır (hacim sıralı + AI kapısı), kalan 7 adım ortak."""
    is_trends = channel.content_source == "trends"
    if is_trends:
        region = (channel.trends_region or trend_region_for(channel.language)).upper()
        dikey = channel.trends_vertical
        log.info(f"[1/8] fetch_trending_now region={region}"
                 f"{f' dikey={dikey}' if dikey else ''}")
        items = fetch_trending_items(
            region, language=channel.language,
            cache_dir=Path(cache_dir) / "trends",
            min_volume=channel.trends_min_volume,
            vertical=channel.trends_vertical, log=log)
        if _vertical_starved(items, channel):
            # HAVUZ GENİŞLETİLMEZ. Dikeyi düşürüp yeniden çekmek, düzeltilen
            # sorunu geri getirir ve üstelik görünmez yapar: kanal "bugün de
            # üretti" der ama kimliği dışında bir video yayınlamış olur.
            log.warning(
                f"  [dikey] '{dikey}' aç kaldı: {len(items)} aday < "
                f"{channel.trends_min_candidates} → koşu boş bitiyor")
            finish_run(eng, run_id, status="no_candidates", short_id=None, error=None)
            return RunResult(run_id=run_id, status="no_candidates",
                             short_path=None, error=None)
    else:
        log.info("[1/8] fetch_rss")
        items = fetch_rss(channel.keywords, channel.rss_locale)
    log.info(f"  → {len(items)} items")

    if channel.max_age_hours > 0:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=channel.max_age_hours)
        before = len(items)
        items = [i for i in items if _is_recent(i.pub_date, cutoff)]
        if before != len(items):
            log.info(f"  → {len(items)} after age filter "
                      f"(<= {channel.max_age_hours}h, dropped {before - len(items)})")
    # MARKA GÜVENLİĞİ: dikey kapısı "bizim işimiz mi", AI kapısı "olay mı" diye
    # sorar; ikisi de "bu videoya reklam verilir mi" diye SORMAZ. Magazin
    # dikeyinde canlı havuzdan cinsel içerikli bir moda haberi çıkıp AI kapısını
    # 7,0 ile geçti (2026-08-22). Arz bol olduğu için elemek ucuz.
    if getattr(channel, "brand_safety", "off") != "off":
        from short_bot.brand_safety import risk_of
        kalan, elenen = [], []
        for it in items:
            # YALNIZ BAŞLIK. Trends haberinin `description` alanı BAĞLAM
            # satırıdır — ilişkili aramalar ve BAŞKA makalelerin başlıkları.
            # Kardeş makalede 性的関係 geçtiği için yaşlı BAKIM haberi elendi
            # (canlı yanlış pozitif, 2026-08-22). Gövde bu aşamada henüz
            # çıkarılmamış (extract_article seçimden SONRA koşar), yani
            # description'ı taramak hiçbir zaman gövdeyi taramıyordu.
            k = risk_of(it.title or "", "",
                        language=channel.language, level=channel.brand_safety)
            (elenen if k else kalan).append((k, it) if k else it)
        if elenen:
            log.info(f"  [marka güvenliği] {len(elenen)} haber elendi "
                     f"(seviye={channel.brand_safety})")
            for k, it in elenen:
                log.info(f"      [{k}] {(it.title or '')[:70]}")
            items = kalan

    # NEW: negative keyword filter
    if channel.negative_keywords:
        before = len(items)
        items = _filter_negative_keywords(items, channel.negative_keywords,
                                          channel.language)
        if before != len(items):
            log.info(f"  → {len(items)} after negative keyword filter (dropped {before - len(items)})")

    log.info("[2/8] dedup")
    # Topic-level dedup via OpenAI embeddings (in addition to GUID + fuzzy
    # title) — catches the multi-publisher-same-story case where two
    # videos for the same Icardi/Osimhen news pass through because GUIDs
    # and headlines differ. Graceful degradation if no API key configured.
    secrets_path_for_dedup = (
        (Path(eng.url.database).parent / "secrets.yaml").resolve()
        if eng.url.database else Path("data/secrets.yaml").resolve()
    )
    try:
        dedup_openai_key = resolve_openai_api_key(_load_secrets(secrets_path_for_dedup))
    except Exception:
        dedup_openai_key = ""
    dedup_embeddings: dict[str, list[float]] = {}
    new_items = filter_new(
        eng, items, channel.slug,
        fuzzy_threshold=settings.fuzzy_dedup_threshold,
        openai_api_key=dedup_openai_key or None,
        embeddings_out=dedup_embeddings,
    )
    log.info(f"  → {len(new_items)} new"
             f"{' (embedding-dedup active)' if dedup_openai_key else ''}")
    new_items = _drop_sibling_coverage(new_items, channel=channel, eng=eng, log=log)
    # Record only fuzzy-similar dropped items (not GUID-exact duplicates,
    # which would bloat rss_items on every poll for the same headline)
    from short_bot.db import is_processed
    new_guids = {n.guid for n in new_items}
    for old in items:
        if old.guid in new_guids:
            continue
        if is_processed(eng, old.guid, channel.slug):
            continue  # GUID-exact, already in processed_items, skip
        # Fuzzy-similar: log it for the panel
        record_rss_item(eng, guid=old.guid, channel=channel.slug,
                        title=old.title, link=old.link, source=old.source,
                        pub_date=old.pub_date, thumb_url=old.thumb_url,
                        score=None, status="duplicate")

    if not new_items:
        log.info("no candidates → finish")
        finish_run(eng, run_id, status="no_candidates", short_id=None, error=None)
        return RunResult(run_id=run_id, status="no_candidates", short_path=None, error=None)

    log.info("[3/8] score_items")
    candidates = new_items[:channel.max_candidates_per_run]
    # Load cached insights (computed nightly + on-demand from /insights page).
    # When sparse or absent the formatter returns "" so the scorer prompt
    # stays unchanged — strictly additive feature.
    perf_insights = None
    try:
        from short_bot.db import load_channel_insights
        perf_insights = load_channel_insights(eng, channel.slug)
        if perf_insights:
            log.info(
                f"  [insights] loaded (sample_size="
                f"{perf_insights.get('sample_size', 0)})"
            )
    except Exception as e:  # noqa: BLE001 -- never let insights crash pipeline
        log.warning(f"  [insights] load failed: {e} -- skipping injection")
    # Resolve the active AI backend (claude_cli default; openrouter when configured).
    # Load secrets once and reuse for every role below.
    secrets = _load_secrets(secrets_path_for_dedup)
    score_call = resolve_ai_call(settings, secrets, "default")
    scored = score_items(
        candidates,
        claude_path=score_call.claude_path,
        model=score_call.model,
        channel=channel,
        performance_insights=perf_insights,
        backend=score_call.backend,
        api_key=score_call.api_key,
    )
    # Trend boost: augment scores when a candidate headline matches a
    # currently trending term in the channel's region. Best-effort -- any
    # failure leaves scores untouched.
    secrets_path_for_trends = (
        (Path(eng.url.database).parent / "secrets.yaml").resolve()
        if eng.url.database else Path("data/secrets.yaml").resolve()
    )
    scored = _apply_trend_boost(
        scored, channel=channel, settings=settings,
        cache_dir=Path(cache_dir),
        secrets_path=secrets_path_for_trends, log=log,
    )
    scored = _apply_category_quota(scored, channel=channel, eng=eng, log=log)
    scored = _apply_saga_penalty(scored, channel=channel, eng=eng, log=log)
    if is_trends:
        # Puan kapı, hacim sıra: ülkenin en çok aradığı OLAY önce.
        top_n_candidates = select_by_volume(
            scored, min_score=channel.min_score, n=_IMAGE_RETRY_MAX,
            intent=getattr(channel, "trends_intent", "any"),
            language=channel.language)
    else:
        top_n_candidates = select_top(scored, min_score=channel.min_score,
                                      n=_IMAGE_RETRY_MAX)
    if not top_n_candidates:
        log.info(f"no item ≥ {channel.min_score} → finish")
        for s in scored:
            record_rss_item(eng, guid=s.item.guid, channel=channel.slug,
                            title=s.item.title, link=s.item.link, source=s.item.source,
                            pub_date=s.item.pub_date, thumb_url=s.item.thumb_url,
                            score=s.score, status="below_threshold")
        # Show top 3 for calibration / debug
        top_seen = sorted(scored, key=lambda s: s.score, reverse=True)[:3]
        for i, s in enumerate(top_seen, 1):
            log.info(f"  top#{i} score={s.score:.1f} | {s.item.title[:80]}")
        finish_run(eng, run_id, status="no_candidates", short_id=None, error=None)
        return RunResult(run_id=run_id, status="no_candidates", short_path=None, error=None)

    log.info(f"  → {len(top_n_candidates)} candidate(s) ≥ {channel.min_score} "
             f"(retry-on-no-image up to {_IMAGE_RETRY_MAX})")
    top_guids = {c.item.guid for c in top_n_candidates}

    # Resolve the script-role AI backend. In claude_cli mode keep the existing
    # channel-aware model precedence (channel.script_model wins); in openrouter
    # mode use the resolved openrouter model.
    script_call = resolve_ai_call(settings, secrets, "script")
    if script_call.backend == "claude_cli":
        script_model = (channel.script_model
                        or settings.claude_models.get("script")
                        or settings.claude_models.get("default", "haiku"))
    else:
        script_model = script_call.model
    # Kanal modeli ANLATIMA da geçsin. script_call aşağıda _render_and_compose'a,
    # oradan write_narration'a veriliyordu ve kanal ayarını GÖRMÜYORDU: aynı
    # kanalın haber kartı channel.script_model ile, seslendirme anlatımı ise
    # settings'teki modelle yazılıyordu.
    script_call = _dc_replace(script_call, model=script_model)

    picked = None
    body = None
    script = None
    bg = None
    for attempt, candidate in enumerate(top_n_candidates, 1):
        vol = (f" volume={candidate.item.trend_volume}" if is_trends else "")
        log.info(f"[4-6/8] candidate {attempt}/{len(top_n_candidates)} "
                 f"score={candidate.score:.1f}{vol} | {candidate.item.title[:80]}")

        # Resolve google-news redirect URLs to the publisher URL so BOTH the
        # body extractor AND the og:image fetch see the real article page
        # (mynet.com.tr / sozcu.com.tr etc.) instead of Google's JS-redirect
        # interstitial. Costs ~3-5s per resolve via Playwright; this is
        # cheaper than falling through to DDG search + Claude vision verify
        # AND it eliminates the "burned-in news graphic" failure mode (the
        # publisher's own og:image is by construction the right photo).
        article_url = candidate.item.link
        if _is_google_news_url(article_url):
            from short_bot.google_news_resolver import resolve as _resolve_gnews
            resolved = _resolve_gnews(article_url)
            if resolved:
                log.info(f"  resolved gnews → {resolved[:90]}")
                article_url = resolved
            else:
                log.info("  gnews resolve failed — using raw URL (body/og may be empty)")

        log.info("  extract_article")
        body_try = extract_article(article_url)
        if body_try is None:
            body_try = candidate.item.description or candidate.item.title
            log.warning("  trafilatura empty → fallback description")
        log.info(f"  → body {len(body_try)} chars")

        log.info(f"  write_script (model={script_model})")
        if channel.template in ARCHETYPE_OVERFLOW_FIELDS:
            template_path = templates_dir / f"{channel.template}.html.j2"
            script_try, _overflow_retries = write_script_with_overflow_check(
                item=candidate.item,
                body_html=body_try,
                channel=channel,
                template_path=template_path,
                job_template_args={
                    "music_path": Path("dummy.mp3"),
                    "ui_language": channel.language,
                },
                max_retries=2,
                log=log,
                claude_path=script_call.claude_path,
                model=script_model,
                backend=script_call.backend,
                api_key=script_call.api_key,
            )
        else:
            log.info(f"  template '{channel.template}' not in overflow config "
                     f"— skipping overflow check")
            script_try = write_script(
                candidate.item, body_try,
                claude_path=script_call.claude_path,
                channel=channel, model=script_model,
                backend=script_call.backend,
                api_key=script_call.api_key,
            )
        log.info(f"  → {script_try.header_top} | {script_try.header_bottom}")

        log.info("  assets/image")
        bg_try = None
        original_was_gnews = _is_google_news_url(candidate.item.link)
        # 1. og:image — publisher's actual hero photo. When the original RSS
        # URL was a google-news redirect, `article_url` was resolved above
        # to the publisher's real page, so og:image now reads the real hero
        # photo (mynet/sozcu/etc.) instead of Google's generic CDN preview.
        og_url = extract_og_image_url(article_url)
        if og_url:
            log.info(f"  og:image: {og_url[:100]}")
            bg_try = download_and_blur_thumb(og_url, cache_dir,
                                             blur_radius=channel.bg_image_blur)
            if bg_try:
                log.info(f"  og:image accepted: {bg_try.name} "
                         f"(blur={channel.bg_image_blur})")
            else:
                log.info(f"  og:image rejected (too small or fetch failed)")
        # 2. RSS thumb fallback (publisher media:thumbnail). Still skipped
        # when the original was google-news -- the thumb on those feeds is
        # always Google's generic publisher logo, identical across articles.
        if bg_try is None and not original_was_gnews and candidate.item.thumb_url:
            bg_try = download_and_blur_thumb(candidate.item.thumb_url, cache_dir,
                                             blur_radius=channel.bg_image_blur)
        # 3. DDG/Wikimedia/Pexels search fallback.
        if bg_try is None:
            from short_bot.image_picker import pick_image_for_script
            images_cache = cache_dir / "images"
            vision_call = resolve_ai_call(settings, secrets, "vision")
            bg_try = pick_image_for_script(script_try, images_cache,
                                           claude_path=vision_call.claude_path,
                                           channel=channel,
                                           backend=vision_call.backend,
                                           api_key=vision_call.api_key,
                                           model=vision_call.model)
            if bg_try:
                log.info(f"  ddg image accepted: {bg_try.name}")

        if bg_try is None:
            log.warning(f"  candidate {attempt} no image → image_rejected, trying next")
            record_rss_item(eng, guid=candidate.item.guid, channel=channel.slug,
                            title=candidate.item.title, link=candidate.item.link,
                            source=candidate.item.source, pub_date=candidate.item.pub_date,
                            thumb_url=candidate.item.thumb_url, score=candidate.score,
                            status="image_rejected")
            continue

        picked = candidate
        body = body_try
        script = script_try
        bg = bg_try
        log.info(f"  → picked {picked.item.guid} (attempt {attempt})")
        break

    # Record below_threshold items (those not in top_n)
    for s in scored:
        if s.item.guid not in top_guids:
            record_rss_item(eng, guid=s.item.guid, channel=channel.slug,
                            title=s.item.title, link=s.item.link, source=s.item.source,
                            pub_date=s.item.pub_date, thumb_url=s.item.thumb_url,
                            score=s.score, status="below_threshold")

    if picked is None:
        msg = f"no usable image after {len(top_n_candidates)} candidates"
        log.warning(f"{msg} → finish")
        finish_run(eng, run_id, status="no_candidates", short_id=None, error=msg)
        return RunResult(run_id=run_id, status="no_candidates",
                         short_path=None, error=msg)

    record_rss_item(eng, guid=picked.item.guid, channel=channel.slug,
                    title=picked.item.title, link=picked.item.link,
                    source=picked.item.source, pub_date=picked.item.pub_date,
                    thumb_url=picked.item.thumb_url, score=picked.score,
                    status="selected")

    music = pick_music(music_root, mood=script.mood, channel_slug=channel.slug)
    log.info(f"  → bg={'cached' if bg else 'none'} music={music.name}")

    log.info("[7/8] render_frames")
    ticker_items: tuple[str, ...] = ()
    if is_trends and picked is not None:
        ticker_items = _ticker_items_for_trends(scored, picked, min_score=channel.min_score)
        if ticker_items:
            log.info(f"  ticker: {len(ticker_items)} başlık")
    job = RenderJob(
        script=script,
        bg_image_path=bg,
        music_path=music,
        channel_colors=channel.colors,
        handle=channel.handle,
        duration_s=channel.duration_s,
        language=channel.language,
        rss_source=picked.item.source if picked else None,
        ticker_items=ticker_items,
    )

    with tempfile.TemporaryDirectory() as tmpd:
        frames_dir = Path(tmpd) / "frames"
        t0 = time.perf_counter()
        ui_labels = _resolve_ui_labels(channel)
        # Resolve effective DNA (per-video for dynamic_dna channels; else channel-level).
        # Note: overflow check ran earlier against channel.template; if the dynamic DNA
        # picks a different archetype the rendered video uses it but overflow was not
        # re-checked. Acceptable risk — fallback is always channel.dna or template.
        from short_bot.dna import build_css_override
        effective_dna = channel.dna
        secrets_path = current_app_secrets_path()
        dna_call = resolve_ai_call(settings, secrets, "dna")
        resolved = _resolve_dna_for_video(
            channel=channel,
            headline=f"{script.header_top} {script.header_bottom}",
            body=script.body_paragraph,
            log=log, claude_path=dna_call.claude_path,
            secrets_path=secrets_path, templates_dir=templates_dir, eng=eng,
            model=dna_call.model, backend=dna_call.backend,
            api_key=dna_call.api_key,
        )
        if resolved is not None:
            effective_dna, css_path = resolved
            dna_css = css_path.read_text(encoding="utf-8")
        else:
            dna_css = build_css_override(channel.dna) if channel.dna else ""
        archetype = effective_dna.archetype if effective_dna is not None else channel.template

        log.info("[8/8] compose_video")
        out_dir = Path(channel.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(picked.item.title)
        out_path = unique_output_path(
            out_dir, f"{datetime.now(timezone.utc):%Y-%m-%d}_{slug}")

        sfx_overlays = []
        bg_video_path = _resolve_pexels_bg(
            channel=channel, cache_dir=cache_dir,
            secrets_path=secrets_path, log=log,
        )

        # bg_video (bv) ve script_call artık _render_and_compose içinde
        # hesaplanıyor; script_call'ı yukarıda (write_script bloğunda) çözdüğümüz
        # değeri yeniden kullanıyoruz — tekrar resolve_ai_call çağırmıyoruz.
        _render_and_compose(
            job=job, archetype=archetype, templates_dir=templates_dir,
            frames_dir=frames_dir, music=music, out_path=out_path,
            channel=channel, settings=settings, secrets=secrets,
            ui_labels=ui_labels, dna_css=dna_css,
            animation_style=(effective_dna.animation_style
                             if effective_dna is not None else "none"),
            sfx_overlays=sfx_overlays, bg_video_path=bg_video_path,
            item=picked.item, body=body, script=script, bg_image_path=bg,
            log=log, llm_call=script_call, cache_dir=cache_dir,
            recent_variations=tuple(recent_narration_variations(eng, channel.slug)),
        )
        render_ms = int((time.perf_counter() - t0) * 1000)
        log.info(f"  → {out_path.name} ({render_ms}ms)")

    # Compute embedding of the Claude-PRODUCED headline too — drives the new
    # "produced-headline dedup" layer in dedup.filter_new on future runs.
    # Best-effort: any failure leaves it NULL and we still benefit from the
    # RSS-side dedup. Reuses the same OpenAI key as RSS-side embedding.
    produced_embedding = None
    try:
        if dedup_openai_key:
            produced_text = (
                f"{script.header_top} {script.header_bottom}".strip()
            )
            if produced_text:
                from short_bot.embeddings import embed_text as _embed
                produced_embedding = _embed(produced_text, api_key=dedup_openai_key)
    except Exception as e:  # noqa: BLE001 — never block render success
        log.warning(f"  produced-title embedding failed: {e}")

    mark_processed(
        eng, picked.item.guid, picked.item.title, channel.slug,
        embedding=dedup_embeddings.get(picked.item.guid),
        produced_title_embedding=produced_embedding,
    )
    # Saga sayacının anahtarı: senaryo yazarı üretmez, seçilen adaydan taşınır.
    short_id = record_short(eng,
        channel=channel.slug, rss_item_guid=picked.item.guid,
        title=script.header_top + " " + script.header_bottom,
        file_path=str(out_path), duration_s=channel.duration_s,
        script_json=script.model_copy(update={
            "subject": picked.subject,
            "search_queries": list(getattr(picked.item, "trend_related", ()) or ())[:10],
        }).model_dump_json(),
        render_ms=render_ms,
    )
    finish_run(eng, run_id, status="success", short_id=short_id, error=None)
    yt_creds_root = (Path(eng.url.database).parent / "youtube_credentials").resolve() \
        if eng.url.database else Path("data/youtube_credentials").resolve()
    secrets_path = (Path(eng.url.database).parent / "secrets.yaml").resolve() \
        if eng.url.database else Path("data/secrets.yaml").resolve()
    _maybe_auto_upload(
        eng=eng, short_id=short_id, channel=channel,
        picked_score=picked.score, log=log,
        yt_creds_root=yt_creds_root,
        claude_path=score_call.claude_path,
        model=score_call.model,
        secrets_path=secrets_path,
        backend=score_call.backend,
        api_key=score_call.api_key,
        defer=defer_upload,
    )
    log.info(f"=== success short_id={short_id} ===")
    return RunResult(run_id=run_id, status="success", short_path=out_path,
                     error=None, short_id=short_id)


def _safe_generate(gen_fn, *, log, attempt: int):
    """Senaryo üret; LLM yanıtı GEÇERSİZSE fırlatma, None dön.

    GERÇEK HATA (run 830): 3 deneme hakkı varken 2. denemede LLM'in ürettiği vurgu
    paragrafta birebir geçmedi → pydantic ValidationError → generate_quote fırlattı
    → TÜM KOŞU DÜŞTÜ, 3. denemeye hiç sıra gelmedi. Doğrulama hatası bir LLM
    kaprisidir; tekrar (duplicate) nasıl bir deneme tüketip devam ediyorsa, geçersiz
    yanıt da öyle davranmalı.
    """
    try:
        return gen_fn()
    except KeyboardInterrupt:
        raise            # kullanıcı durdurduysa YUTMA
    except Exception as e:  # noqa: BLE001 — LLM kaprisi koşuyu düşürmesin
        log.warning(f"  geçersiz LLM yanıtı (deneme {attempt}): {e} → sonraki deneme")
        return None


def _run_generator(*, channel, run_id, log, eng, settings,
                   music_root, templates_dir, cache_dir,
                   forced_topic: str | None = None,
                   defer_upload: bool = False,
                   standalone: bool = False) -> RunResult:
    """6-phase generator pipeline."""
    log.info("[1/6] prepare (forbidden + topic distribution)")
    forbidden = recent_generated_texts(
        eng, channel.slug, limit=channel.generator.forbidden_lookback,
    )
    topic_dist = topic_distribution(eng, channel.slug, days=_GENERATOR_TOPIC_DIST_DAYS)
    log.info(f"  → forbidden={len(forbidden)} topic_dist={topic_dist}")
    # Kanıtlanmış-konu bankası (ilham + rotasyon; boşsa prompt değişmez)
    proven = []
    try:
        from short_bot.db import active_bank_topics
        proven = active_bank_topics(eng, channel.slug, limit=10)
        if proven:
            log.info(f"  → konu bankası: {len(proven)} aktif kayıt")
    except Exception as e:
        log.warning(f"  konu bankası okunamadı: {e}")

    fuzzy_threshold = (channel.generator.fuzzy_threshold
                       if channel.generator.fuzzy_threshold is not None
                       else settings.fuzzy_dedup_threshold)

    # Resolve the active AI backend (claude_cli default; openrouter when configured).
    # Load secrets once and reuse for every role in this path.
    gen_secrets_path = (
        (Path(eng.url.database).parent / "secrets.yaml").resolve()
        if eng.url.database else Path("data/secrets.yaml").resolve()
    )
    secrets = _load_secrets(gen_secrets_path)
    gen_call = resolve_ai_call(settings, secrets, "default")
    if gen_call.backend == "claude_cli":
        gen_model = (channel.script_model
                     or settings.claude_models.get("default", "sonnet"))
    else:
        gen_model = gen_call.model

    # SERİ / ARK PLANI (bkz. reel_series). Konu planlaması burada video düzeyinden
    # ARK düzeyine çıkıyor: önceki bölüm bir kapı açtıysa (open_loop), O KAPI bu
    # bölümün konusudur. Kullanıcı elle konu seçtiyse (forced_topic) zincir ezilir —
    # kullanıcı sözü son sözdür.
    episode = None
    arc_id = None
    reel_cfg = getattr(channel, "reel", None)
    if standalone and reel_cfg is not None and reel_cfg.series_enabled:
        # BAĞIMSIZ SLOT: seri açık ama bu video seriyi İLERLETMEZ. Bölüm planlanmaz,
        # ark tüketilmez, bölüm kaydedilmez. Konu bankadan gelir.
        # (Günde en fazla 1 bölüm — yoksa "#2 yarın" sözü aynı gün bozulur.)
        log.info("  seri: BAĞIMSIZ slot → bölüm üretilmiyor, ark tüketilmiyor")
    elif reel_cfg is not None and reel_cfg.enabled and reel_cfg.series_enabled:
        from short_bot.db import active_arc, last_episode
        from short_bot.lang_pack import load_pack
        from short_bot.reel_series import clean_open_loop, plan_episode
        try:
            episode = plan_episode(last_episode(eng, channel.slug),
                                   arc_max=reel_cfg.series_arc_length)
            # PLANLI ARK ÖNCE. Onaylı bir ark varsa hem KONU hem SIRADAKİ KONU plandan
            # gelir — LLM cliffhanger'ı UYDURMAZ, SÖYLER. Sapma yapısal olarak imkânsız.
            ark = (active_arc(eng, channel.slug)
                   if getattr(reel_cfg, "arc_mode", "chain") == "planned" else None)
            if ark:
                kalemler = ark["plan"]
                i = int(ark["produced"])
                if 0 <= i < len(kalemler):
                    arc_id = ark["id"]
                    sirasi = (kalemler[i + 1]["topic"] if i + 1 < len(kalemler) else "")
                    episode = replace(
                        episode, arc_pos=i + 1, continue_from="",
                        next_topic=sirasi, arc_title=ark["title"],
                        arc_total=len(kalemler))
                    if not forced_topic:
                        forced_topic = kalemler[i]["topic"]
                        log.info(f"  seri: PLANLI ARK '{ark['title']}' "
                                 f"({i + 1}/{len(kalemler)}) → konu plandan: "
                                 f"{forced_topic[:80]!r}")
            elif episode.continue_from and not forced_topic:
                # ZİNCİR MODU. META DİLİ AYIKLA: LLM kapıya "…2. bölümde açıklıyoruz"
                # gibi bir kuyruk ekliyor (ölçüldü). O metin burada ÜRETİM KONUSU
                # oluyor — bölüm numarası geçen bir konu tohumu senaryo yazıcısını
                # yanıltır. Kayıtta HAM hâli duruyor (teşhis).
                forced_topic = clean_open_loop(
                    episode.continue_from, pack=load_pack(channel.language))
                log.info(f"  seri: ark sürüyor → konu ÖNCEKİ BÖLÜMÜN KAPISINDAN "
                         f"geliyor: {forced_topic[:80]!r}")
            elif episode.continue_from:
                log.info("  seri: kullanıcı konu seçti → ark zinciri bu bölümde "
                         "ezildi (sözü ödeme yönergesi yine de veriliyor)")
            elif getattr(reel_cfg, "arc_mode", "chain") == "planned":
                # Planlı mod ama ONAYLI ARK YOK → üretim DURMAZ: bankadan tek konu
                # üretilir ve zincir davranışına düşülür. Duran bir otomasyon,
                # sapmış bir otomasyondan kötüdür; panel bunu görünür kılar.
                log.warning("  seri: planlı mod ama ONAYLI ARK YOK → bankadan tek konu "
                            "(panelden ark planlayıp onaylayın)")
        except Exception as e:   # seri KOZMETİK değil ama üretimi düşürmemeli
            log.warning(f"  seri: bölüm planlanamadı ({e}) → serisiz üretim")
            episode = None
            arc_id = None

    if forced_topic:
        log.info(f"  konu KULLANICI tarafından seçildi: {forced_topic[:80]!r}")

    last_text = ""
    chosen_result = None
    for attempt in range(1, channel.generator.max_retries + 1):
        log.info(f"[2/6] generate attempt {attempt}/{channel.generator.max_retries}")
        result = _safe_generate(
            lambda: generate_quote(
                channel=channel, dna=channel.dna,
                forbidden_texts=forbidden, topic_distribution=topic_dist,
                claude_path=gen_call.claude_path,
                model=gen_model,
                backend=gen_call.backend,
                api_key=gen_call.api_key,
                proven_topics=proven,
                forced_topic=forced_topic,
            ),
            log=log, attempt=attempt)
        if result is None:
            continue          # geçersiz yanıt → tekrar gibi bir deneme tüketir

        # Konuyu KULLANICI seçtiyse tekrar-denetimi ATLANIR: "yeniden üret" ve
        # "bu başlıktan üret" zaten var olan bir başlığı bilerek tekrarlar —
        # dedup burada çalışırsa istek her seferinde çöpe gider.
        if forced_topic:
            chosen_result = result
            break

        log.info(f"[3/6] dedup-check (text={result.text[:60]!r})")
        verdict = check_duplicate(eng, channel.slug, result, forbidden,
                                  fuzzy_threshold)
        if verdict.is_duplicate:
            log.warning(f"  duplicate ({verdict.reason}) → discard")
            try:
                insert_generated(
                    eng, channel=channel.slug, text=result.text,
                    topic_tag=result.topic_tag, language=channel.language,
                    status="discarded", short_id=None,
                )
            except Exception as e:
                log.warning(f"  discarded insert failed (probably hash race): {e}")
            last_text = result.text
            continue

        chosen_result = result
        break

    if chosen_result is None:
        msg = (f"{channel.slug}: {channel.generator.max_retries} attempts all "
               f"duplicate or invalid. Last attempt: {last_text[:80]!r}")
        finish_run(eng, run_id, status="failed",
                   short_id=None, error=msg)
        raise GeneratorRetryExhausted(msg)

    # Record as 'used' WITHOUT short_id yet (filled after render)
    # Zorlanan konuda başlık ZATEN kayıtlı olabilir — (channel, text_hash) benzersiz
    # olduğu için yeni satır açılamaz. Var olanı yeniden kullan; yoksa "yeniden üret"
    # her seferinde benzersizlik kısıtına çarpıp düşerdi.
    existing = (generated_id_for_text(eng, channel.slug, chosen_result.text)
                if forced_topic else None)
    if existing is not None:
        generated_id = existing
        log.info(f"  → mevcut kayıt yeniden kullanıldı: generated_id={generated_id}")
    else:
        generated_id = insert_generated(
            eng, channel=channel.slug, text=chosen_result.text,
            topic_tag=chosen_result.topic_tag, language=channel.language,
            status="used", short_id=None,
        )

    # Banka rotasyonu: LLM kanıtlanmış konu seçtiyse kaydı 'used' işaretle
    # (uydurma id → mark no-op; hata üretimi asla durdurmaz).
    if getattr(chosen_result, "bank_id", None):
        try:
            from short_bot.db import mark_bank_topic_used
            mark_bank_topic_used(eng, chosen_result.bank_id)
            log.info(f"  → banka kaydı used: id={chosen_result.bank_id}")
        except Exception as e:
            log.warning(f"  banka used işaretlenemedi: {e}")

    # Reel formatı: footage-sürüklü üretim (etkinse render/compose'u atla)
    reel_call = resolve_ai_call(settings, secrets, "vision")
    if getattr(channel, "reel", None) is not None and channel.reel.enabled:
        out_dir = Path(channel.output_dir); out_dir.mkdir(parents=True, exist_ok=True)
        reel_out = unique_output_path(
            out_dir,
            f"{datetime.now(timezone.utc):%Y-%m-%d}_{_slugify(chosen_result.text)}")
        hook_pats = []
        try:
            from short_bot.db import bank_hook_patterns
            hook_pats = bank_hook_patterns(eng, channel.slug, limit=5)
        except Exception:
            pass
        # Açık kapıyı senaryo yazılır yazılmaz yakala; ama DB'ye ancak üretim
        # BAŞARILI olunca yaz. Yarım kalan bir üretim bölüm numarasını tüketirse
        # feed'de #47'den #49'a atlarız — seri sayacının delik olması, serinin
        # gerçekliğine dair tek somut kanıtı çürütür.
        narr: dict = {}
        with tempfile.TemporaryDirectory() as reel_tmp:
            t0 = time.perf_counter()
            _reel_produce_or_none(
                channel=channel, topic=chosen_result.text, out_path=reel_out,
                settings=settings, secrets=secrets, music_root=music_root,
                templates_dir=templates_dir, cache_dir=cache_dir,
                work_dir=Path(reel_tmp), log=log, llm_call=gen_call,
                vision_call=reel_call, seed=generated_id,
                hook_patterns=hook_pats,
                cancel_check=lambda: is_run_cancelled(eng, run_id),
                episode=episode,
                on_narration=lambda n: narr.update(open_loop=getattr(n, 'open_loop', ''),
                                   title=getattr(n, 'title', '')),
            )
            render_ms = int((time.perf_counter() - t0) * 1000)
        # SEO BAŞLIĞI: anlatımın 'title'ı (özne anahtar-kelimesi ÖNDE + kısa mahalle
        # vuruşu). Boşsa uzun konu metnine düş (geriye uyum). Dosya adını da bu kısa
        # başlığın slug'ıyla yeniden adlandır — eski davranış konu-cümlesinin çirkin,
        # kesik slug'ını basıyordu.
        seo_title = (narr.get("title") or "").strip()
        if seo_title:
            yeni_out = unique_output_path(
                out_dir, f"{datetime.now(timezone.utc):%Y-%m-%d}_{_slugify(seo_title)}")
            try:
                reel_out.rename(yeni_out)
                reel_out = yeni_out
            except OSError as e:
                log.warning(f"  reel: dosya yeniden adlandırılamadı ({e}) → eski ad")
        video_title = (seo_title or chosen_result.text)[:100]
        log.info(f"  → {reel_out.name} ({render_ms}ms)")
        short_id = record_short(
            eng, channel=channel.slug, rss_item_guid=None,
            title=video_title, file_path=str(reel_out),
            duration_s=channel.duration_s,
            script_json=chosen_result.script.model_dump_json(), render_ms=render_ms,
        )
        update_generated_short_id(eng, generated_id, short_id)
        if episode is not None:
            try:
                from short_bot.db import advance_arc, record_episode
                record_episode(
                    eng, channel.slug, episode_no=episode.episode_no,
                    arc_pos=episode.arc_pos, topic=chosen_result.text,
                    open_loop=narr.get("open_loop", ""), short_id=short_id)
                log.info(f"  seri: bölüm #{episode.episode_no} kaydedildi"
                         + (" (kapı açık → sonraki bölümün konusu hazır)"
                            if narr.get("open_loop") else " (kapı yok → ark biter)"))
                # PLANLI ARK SAYACI — yalnız üretim BAŞARILIYSA ilerler. Başarısız bir
                # koşu planı tüketirse o bölüm hiç üretilmemiş olur ve planda delik kalır.
                if arc_id is not None:
                    advance_arc(eng, arc_id)
                    log.info(f"  seri: ark {arc_id} → "
                             f"{episode.arc_pos}/{episode.arc_total} bölüm üretildi")
            except Exception as e:
                log.warning(f"  seri: bölüm kaydedilemedi ({e}) → zincir kopabilir")
        finish_run(eng, run_id, status="success", short_id=short_id, error=None)
        yt_creds_root = (Path(eng.url.database).parent / "youtube_credentials").resolve() \
            if eng.url.database else Path("data/youtube_credentials").resolve()
        secrets_path2 = (Path(eng.url.database).parent / "secrets.yaml").resolve() \
            if eng.url.database else Path("data/secrets.yaml").resolve()
        _maybe_auto_upload(
            eng=eng, short_id=short_id, channel=channel, picked_score=None, log=log,
            yt_creds_root=yt_creds_root, claude_path=gen_call.claude_path,
            model=gen_call.model, secrets_path=secrets_path2,
            backend=gen_call.backend, api_key=gen_call.api_key,
            defer=defer_upload,
        )
        log.info(f"=== success short_id={short_id} (reel) ===")
        return RunResult(run_id=run_id, status="success", short_path=reel_out,
                         error=None, short_id=short_id)

    # Phase 4: image
    log.info("[4/6] image search (Sonnet keywords)")
    images_cache = Path(cache_dir) / "images"
    vision_call = resolve_ai_call(settings, secrets, "vision")
    bg = pick_image_for_generator(
        keywords=chosen_result.image_keywords,
        script=chosen_result.script,
        cache_dir=images_cache,
        claude_path=vision_call.claude_path,
        backend=vision_call.backend,
        api_key=vision_call.api_key,
        model=vision_call.model,
    )
    music = pick_music(music_root, mood=chosen_result.script.mood, channel_slug=channel.slug)
    log.info(f"  → bg={'cached' if bg else 'none'} music={music.name}")

    # Phase 5+6: render + compose (same RenderJob shape as RSS path)
    log.info("[5/6] render_frames")
    job = RenderJob(
        script=chosen_result.script, bg_image_path=bg, music_path=music,
        channel_colors=channel.colors, handle=channel.handle,
        duration_s=channel.duration_s, language=channel.language,
        rss_source=None,  # generator path — no RSS source
    )

    with tempfile.TemporaryDirectory() as tmpd:
        frames_dir = Path(tmpd) / "frames"
        t0 = time.perf_counter()
        ui_labels = _resolve_ui_labels(channel)
        # Resolve effective DNA (per-video for dynamic_dna channels; else channel-level).
        # Note: overflow check ran earlier against channel.template; if the dynamic DNA
        # picks a different archetype the rendered video uses it but overflow was not
        # re-checked. Acceptable risk — fallback is always channel.dna or template.
        from short_bot.dna import build_css_override
        effective_dna = channel.dna
        secrets_path = current_app_secrets_path()
        dna_call = resolve_ai_call(settings, secrets, "dna")
        resolved = _resolve_dna_for_video(
            channel=channel,
            headline=f"{chosen_result.script.header_top} {chosen_result.script.header_bottom}",
            body=chosen_result.script.body_paragraph,
            log=log, claude_path=dna_call.claude_path,
            secrets_path=secrets_path, templates_dir=templates_dir, eng=eng,
            model=dna_call.model, backend=dna_call.backend,
            api_key=dna_call.api_key,
        )
        if resolved is not None:
            effective_dna, css_path = resolved
            dna_css = css_path.read_text(encoding="utf-8")
        else:
            dna_css = build_css_override(channel.dna) if channel.dna else ""
        archetype = effective_dna.archetype if effective_dna is not None else channel.template
        template_path = templates_dir / f"{archetype}.html.j2"
        render_frames(job, template_path, frames_dir,
                      fps=30, browser=settings.playwright_browser,
                      ui_labels=ui_labels, dna_css=dna_css,
                      animation_style=(effective_dna.animation_style
                                        if effective_dna is not None else "none"))

        log.info("[6/6] compose_video")
        out_dir = Path(channel.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(chosen_result.text)
        out_path = unique_output_path(
            out_dir, f"{datetime.now(timezone.utc):%Y-%m-%d}_{slug}")
        sfx_overlays = []

        bg_video_path = _resolve_pexels_bg(
            channel=channel, cache_dir=cache_dir,
            secrets_path=secrets_path, log=log,
        )

        bv = channel.bg_video
        compose_video(
            frames_dir, music, out_path,
            fps=30, ffmpeg_path=settings.ffmpeg_path,
            sfx_overlays=sfx_overlays,
            bg_video_path=bg_video_path,
            bg_blur_px=bv.blur_px if bv else 30,
            bg_dim=bv.dim if bv else 0.4,
            fg_scale=bv.scale if (bv and bg_video_path) else 1.0,
            duration_s=channel.duration_s,
        )
        render_ms = int((time.perf_counter() - t0) * 1000)
        log.info(f"  → {out_path.name} ({render_ms}ms)")

    short_id = record_short(
        eng, channel=channel.slug, rss_item_guid=None,
        title=chosen_result.script.header_top + " " + chosen_result.script.header_bottom,
        file_path=str(out_path), duration_s=channel.duration_s,
        script_json=chosen_result.script.model_dump_json(),
        render_ms=render_ms,
    )
    update_generated_short_id(eng, generated_id, short_id)
    finish_run(eng, run_id, status="success", short_id=short_id, error=None)
    yt_creds_root = (Path(eng.url.database).parent / "youtube_credentials").resolve() \
        if eng.url.database else Path("data/youtube_credentials").resolve()
    secrets_path = (Path(eng.url.database).parent / "secrets.yaml").resolve() \
        if eng.url.database else Path("data/secrets.yaml").resolve()
    _maybe_auto_upload(
        eng=eng, short_id=short_id, channel=channel,
        picked_score=None, log=log,
        yt_creds_root=yt_creds_root,
        claude_path=gen_call.claude_path,
        model=gen_call.model,
        secrets_path=secrets_path,
        backend=gen_call.backend,
        api_key=gen_call.api_key,
        defer=defer_upload,
    )
    log.info(f"=== success short_id={short_id} ===")
    return RunResult(run_id=run_id, status="success",
                     short_path=out_path, error=None, short_id=short_id)


def _run_feed(*, channel, run_id, log, eng, settings,
              music_root, templates_dir, cache_dir,
              defer_upload: bool = False) -> RunResult:
    """Otomatik feed pipeline: auto_feed_ids'ten çek → dedup → score →
    hibrit seçim (eşik üstü en yeni) → _produce_from_item."""
    log.info(f"[1/3] fetch feeds {channel.auto_feed_ids}")
    items = []
    for fid in channel.auto_feed_ids:
        feed = get_feed(eng, fid)
        if feed is None:
            log.warning(f"  feed id={fid} bulunamadı — atlanıyor")
            continue
        try:
            items.extend(fetch_feed_url(feed.url))
        except Exception as e:
            log.warning(f"  feed {feed.url} çekilemedi: {e}")
    log.info(f"  → {len(items)} items")

    if channel.max_age_hours > 0:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=channel.max_age_hours)
        items = [i for i in items if _is_recent(i.pub_date, cutoff)]
    if channel.negative_keywords:
        items = _filter_negative_keywords(items, channel.negative_keywords,
                                          channel.language)

    log.info("[2/3] dedup")
    # ÇOK-KAYNAK DEDUP bu yolda da açık. Eskiden yalnız GUID + fuzzy-title
    # çalışıyordu: aynı haber başka bir gazeteden geldiğinde GUID farklı,
    # başlık yeterince farklı → aynı hikâye tekrar tekrar video oluyordu
    # (kullanıcının bildirdiği asıl sorun). Anahtar yoksa filter_new zaten
    # embedding katmanlarını atlar, davranış eskisi gibi kalır.
    _dedup_secrets = _load_secrets(current_app_secrets_path())
    _dedup_key = resolve_openai_api_key(_dedup_secrets)
    _dedup_emb: dict[str, list[float]] = {}
    new_items = filter_new(eng, items, channel.slug,
                           fuzzy_threshold=settings.fuzzy_dedup_threshold,
                           openai_api_key=_dedup_key,
                           embeddings_out=_dedup_emb)
    if not new_items:
        log.info("no candidates → finish")
        finish_run(eng, run_id, status="no_candidates", short_id=None, error=None)
        return RunResult(run_id=run_id, status="no_candidates",
                         short_path=None, error=None)

    log.info("[3/3] score_items")
    secrets_path = current_app_secrets_path()
    secrets = _load_secrets(secrets_path)
    score_call = resolve_ai_call(settings, secrets, "default")
    candidates = new_items[:channel.max_candidates_per_run]
    perf_insights = None
    try:
        from short_bot.db import load_channel_insights
        perf_insights = load_channel_insights(eng, channel.slug)
    except Exception as e:
        log.warning(f"  [insights] load failed: {e} -- skipping injection")
    scored = score_items(candidates, claude_path=score_call.claude_path,
                         model=score_call.model, channel=channel,
                         performance_insights=perf_insights,
                         backend=score_call.backend, api_key=score_call.api_key)
    scored = _apply_trend_boost(
        scored, channel=channel, settings=settings,
        cache_dir=Path(cache_dir), secrets_path=secrets_path, log=log)
    scored = _apply_category_quota(scored, channel=channel, eng=eng, log=log)
    scored = _apply_saga_penalty(scored, channel=channel, eng=eng, log=log)
    picked = select_newest_above(scored, min_score=channel.min_score, n=1)
    if not picked:
        log.info(f"no item ≥ {channel.min_score} → finish")
        for s in scored:
            record_rss_item(eng, guid=s.item.guid, channel=channel.slug,
                            title=s.item.title, link=s.item.link,
                            source=s.item.source, pub_date=s.item.pub_date,
                            thumb_url=s.item.thumb_url, score=s.score,
                            status="below_threshold")
        finish_run(eng, run_id, status="no_candidates", short_id=None, error=None)
        return RunResult(run_id=run_id, status="no_candidates",
                         short_path=None, error=None)

    chosen = picked[0]
    log.info(f"  → picked {chosen.item.guid} score={chosen.score:.1f} "
             f"(newest above threshold)")
    res = _produce_from_item(
        item=chosen.item, channel=channel, eng=eng, settings=settings,
        log=log, music_root=music_root, templates_dir=templates_dir,
        cache_dir=cache_dir, run_id=run_id, score=chosen.score,
        subject=chosen.subject,
        defer_upload=defer_upload)
    if res.status != "success":
        finish_run(eng, run_id, status="no_candidates", short_id=None,
                   error=res.error)
    return res


def _render_and_compose(
    *, job, archetype, templates_dir, frames_dir, music, out_path,
    channel, settings, secrets, ui_labels, dna_css, animation_style,
    sfx_overlays, bg_video_path, item, body, script, bg_image_path, log,
    llm_call, cache_dir=None, recent_variations=(),
) -> Path:
    """Kanal voiced ise seslendirmeli üretime devreder, değilse sessiz akış.

    Sessiz yol bugünkü davranışla bit-bit aynıdır.
    """
    bv = channel.bg_video
    voice = getattr(channel, "voice", None)

    if voice is not None and voice.enabled:
        from short_bot.tts.providers import resolve_tts
        from short_bot.voiced import produce_voiced_video
        tts = resolve_tts(getattr(voice, "provider", "ai33"))
        log.info(f"  voiced mod: {tts.label} seslendirme")
        return produce_voiced_video(
            item=item, body=body, script=script,
            bg_image_path=bg_image_path, music_path=music,
            channel=channel, templates_dir=templates_dir,
            work_dir=Path(frames_dir).parent, out_path=out_path,
            api_key=tts.resolve_api_key(secrets),
            ticker_items=tuple(getattr(job, "ticker_items", ()) or ()),
            usage_dir=Path(cache_dir) if cache_dir else None,
            extra_sources=(_extra_source_bodies(item, log=log)
                           if channel_format(channel) == "yorum" else None),
            recent_variations=tuple(recent_variations or ()),
            ffmpeg_path=settings.ffmpeg_path,
            fps=30, browser=settings.playwright_browser,
            ui_labels=ui_labels, dna_css=dna_css,
            animation_style=animation_style,
            sfx_overlays=[], bg_video_path=bg_video_path,
            bg_blur_px=bv.blur_px if bv else 30,
            bg_dim=bv.dim if bv else 0.4,
            fg_scale=bv.scale if (bv and bg_video_path) else 1.0,
            llm_claude_path=llm_call.claude_path, llm_model=llm_call.model,
            llm_backend=llm_call.backend, llm_api_key=llm_call.api_key,
        )

    template_path = templates_dir / f"{archetype}.html.j2"
    render_frames(job, template_path, frames_dir,
                  fps=30, browser=settings.playwright_browser,
                  ui_labels=ui_labels, dna_css=dna_css,
                  animation_style=animation_style)
    compose_video(
        frames_dir, music, out_path,
        fps=30, ffmpeg_path=settings.ffmpeg_path,
        sfx_overlays=sfx_overlays,
        bg_video_path=bg_video_path,
        bg_blur_px=bv.blur_px if bv else 30,
        bg_dim=bv.dim if bv else 0.4,
        fg_scale=bv.scale if (bv and bg_video_path) else 1.0,
        duration_s=channel.duration_s,
    )
    return out_path


def _reel_produce_or_none(
    *, channel, topic, out_path, settings, secrets, music_root, templates_dir,
    cache_dir, work_dir, log, llm_call, vision_call, seed: int = 0,
    hook_patterns=None, cancel_check=None,
    episode=None, on_narration=None,
) -> "Path | None":
    """Kanal reel ise reel videoyu üretip out_path döndürür; değilse None."""
    reel = getattr(channel, "reel", None)
    if reel is None or not reel.enabled:
        return None
    from short_bot.assets import pick_music
    from short_bot.reel import produce_reel_video
    from short_bot.tts.ai33_client import resolve_ai33_api_key
    from short_bot.pexels import resolve_pexels_api_key, resolve_pixabay_api_key
    log.info("  reel modu: footage-sürüklü üretim")
    try:
        music = pick_music(music_root, mood=reel.music_mood, channel_slug=channel.slug)
    except FileNotFoundError:
        log.warning("  reel: mood müziği bulunamadı, müziksiz devam")
        music = None
    return produce_reel_video(
        topic=topic, channel=channel, templates_dir=templates_dir,
        work_dir=Path(work_dir), out_path=out_path, music_path=music,
        ai33_api_key=resolve_ai33_api_key(secrets),
        pexels_api_key=resolve_pexels_api_key(secrets),
        pixabay_api_key=resolve_pixabay_api_key(secrets),
        footage_priority=getattr(settings, "footage_priority", ["pexels"]),
        ffmpeg_path=settings.ffmpeg_path, browser=settings.playwright_browser,
        llm_claude_path=llm_call.claude_path, llm_model=llm_call.model,
        llm_backend=llm_call.backend, llm_api_key=llm_call.api_key,
        whisper_quality=getattr(settings, "whisper_quality", "auto"),
        whisper_device=getattr(settings, "whisper_device", "auto"),
        vision_call=vision_call, seed=seed,
        cancel_check=cancel_check,
        hook_patterns=hook_patterns,
        # SFX + AI-kurgucu kütüphanesinin kökü: music_root'un üst klasörü
        # (music_root paketlenmiş uygulamada taşınır; assets/ ona bitişiktir).
        assets_root=Path(music_root).parent,
        episode=episode, on_narration=on_narration,
    )


def _build_check_job(script, channel, *, music_path, ui_language):
    """Lightweight RenderJob for in-memory overflow check.

    No bg image (Pexels download may not have happened yet at this point —
    template falls back to gradient when bg_image_path is None).
    Music path is required by RenderJob dataclass but unused by build_html.
    """
    from short_bot.models import RenderJob   # local import to avoid cycles
    return RenderJob(
        script=script,
        bg_image_path=None,
        music_path=music_path,
        channel_colors=channel.colors,
        handle=channel.handle,
        duration_s=channel.duration_s,
        language=ui_language,
    )


def write_script_with_overflow_check(
    *,
    item,
    body_html: str,
    channel,
    template_path,
    job_template_args: dict,
    max_retries: int = 2,
    log,
    claude_path: str = "claude",
    model: str = "default",
    backend: str = "claude_cli",
    api_key: str | None = None,
) -> tuple:
    """Returns (final_script, retry_count).

    retry_count: 0 = clean on first attempt
                 1-2 = clean after N retries
                 max_retries+1 (=3) = truncate fallback used (or attempted)
    """
    feedback = ""
    last_script = None
    last_report: OverflowReport | None = None

    for attempt in range(max_retries + 1):  # 0, 1, 2 → 3 attempts
        script = write_script(item, body_html, channel=channel,
                              overflow_feedback=feedback,
                              claude_path=claude_path, model=model,
                              backend=backend, api_key=api_key)
        last_script = script

        check_job = _build_check_job(script, channel, **job_template_args)
        html = build_html(check_job, template_path)

        try:
            report = check_overflow(html, archetype=channel.template)
        except Exception as e:  # noqa: BLE001 — Playwright/timeout are runtime
            log.warning(f"[overflow] check failed (attempt {attempt + 1}): "
                        f"{e} — using script as-is")
            return script, attempt

        if not report.has_any_overflow():
            log.info(f"[overflow] check #{attempt + 1}: clean")
            return script, attempt

        last_report = report
        log.info(f"[overflow] check #{attempt + 1}: {report.summary()}")

        if attempt < max_retries:
            feedback = format_feedback(report)
            log.info("[overflow] retry write_script with feedback")

    # All attempts overflowed — truncate fallback.
    log.warning("[overflow] all retries failed -> truncate_to_fit fallback")
    try:
        return truncate_to_fit(last_script, last_report), max_retries + 1
    except Exception as e:  # noqa: BLE001 — Pydantic ValidationError or ValueError
        log.warning(f"[overflow] truncate failed ({e}) "
                    f"- using last script as-is")
        return last_script, max_retries + 1
