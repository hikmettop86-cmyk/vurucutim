"""SQLite via SQLAlchemy Core. Plain functions, no ORM session ceremony."""
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Index, Integer, MetaData, String,
    Table, Text, UniqueConstraint, create_engine, select,
)
from sqlalchemy.engine import Engine


def _utcnow() -> datetime:
    """UTC now, timezone-aware. Replaces deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)


metadata = MetaData()

processed_items = Table(
    "processed_items", metadata,
    Column("guid", String, primary_key=True),
    Column("title", Text, nullable=False),
    Column("channel", String, nullable=False),
    Column("processed_at", DateTime, default=_utcnow),
    # OpenAI text-embedding-3-small vector (1536 dims) serialized as JSON
    # array. NULL on legacy rows or when no API key is configured. Used by
    # dedup.filter_new for topic-level similarity check beyond fuzzy title.
    Column("embedding_json", Text),
    # Embedding of the Claude-PRODUCED headline ("SON DAKIKA KADIR INANIR
    # YOGUN BAKIMDA") rather than the RSS-side input title. Catches the case
    # where 3 publishers' headlines all converge on the same Claude output —
    # the RSS-side embedding may miss this when individual titles diverge,
    # but the produced-side embedding is by construction consistent.
    Column("produced_title_embedding_json", Text),
)
Index("idx_processed_channel_ts",
      processed_items.c.channel, processed_items.c.processed_at)

rss_items = Table(
    "rss_items", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("guid", String, nullable=False),
    Column("channel", String, nullable=False),
    Column("title", Text, nullable=False),
    Column("link", Text, nullable=False),
    Column("source", String),
    Column("pub_date", DateTime),
    Column("thumb_url", Text),
    Column("score", Float),
    Column("status", String),
    Column("fetched_at", DateTime, default=_utcnow),
    Column("short_id", Integer, ForeignKey("shorts.id")),
)

shorts = Table(
    "shorts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False),
    Column("rss_item_guid", String),
    Column("title", Text, nullable=False),
    Column("file_path", Text, nullable=False),
    Column("duration_s", Integer),
    Column("script_json", Text),
    Column("render_ms", Integer),
    Column("created_at", DateTime, default=_utcnow),
    Column("deleted_at", DateTime),
)
Index("idx_shorts_channel_created",
      shorts.c.channel, shorts.c.created_at.desc())

runs = Table(
    "runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False),
    Column("trigger", String, nullable=False),
    Column("started_at", DateTime, default=_utcnow),
    Column("ended_at", DateTime),
    Column("status", String),
    Column("short_id", Integer, ForeignKey("shorts.id")),
    Column("error", Text),
    Column("log_path", Text),
)

youtube_uploads = Table(
    "youtube_uploads", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("short_id", Integer, ForeignKey("shorts.id"), nullable=False),
    Column("video_id", String),
    Column("video_url", String),
    Column("status", String, nullable=False),
    Column("error", Text),
    Column("uploaded_at", DateTime, default=_utcnow),
)
Index("idx_yt_uploads_short", youtube_uploads.c.short_id, youtube_uploads.c.uploaded_at)

# KÜRATE HAVUZU: cron sürekli Reddit'i tarar, kanala uygun (tona-duyarlı skor) cevherleri
# buraya biriktirir; kullanıcı panelden bakıp 'Üret'/'Ele' der. status: pending|produced|skipped.
pooled_gems = Table(
    "pooled_gems", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False),
    Column("clip_key", String, nullable=False),   # dedup: v.redd.it id ya da url
    Column("permalink", Text),
    Column("video_url", Text, nullable=False),
    Column("title", Text),
    Column("sub", String),
    Column("ups", Integer),
    Column("comments", Integer),
    Column("duration", Integer),
    Column("width", Integer),
    Column("height", Integer),
    Column("orient", String),
    Column("thumb", Text),
    Column("score", Float),                        # tona-duyarlı merak/duygu skoru
    Column("tone", String),
    Column("status", String, default="pending"),   # pending | produced | skipped
    Column("added_at", DateTime, default=_utcnow),
    Column("short_id", Integer, ForeignKey("shorts.id")),  # üretilince bağlanır
    UniqueConstraint("channel", "clip_key", name="uq_pool_channel_clip"),
)

# ELENEN-HAFIZASI (2026-07-19): indirilip YARGILANMIŞ her klip (üretildi/watermark/gömülü-yazı/
# yanlış-ton). Aynı klibi HER koşuda yeniden indirip vision'la kontrol etmemek için (funnel
# israfı — kullanıcı: 'önceden elenenler yine geliyor'). Yalnız KALICI yargılar yazılır; geçici
# indirme/vision hatası KAYDEDİLMEZ (tekrar denenir). auto_produce fresh'i buna karşı da dedup'lar.
seen_clips = Table(
    "seen_clips", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False),
    Column("clip_key", String, nullable=False),
    Column("verdict", String, nullable=False),   # produced | watermark | heavy-text | off-tone
    Column("ts", DateTime, default=_utcnow),
    UniqueConstraint("channel", "clip_key", name="uq_seen_channel_clip"),
)
Index("idx_pool_channel_status", pooled_gems.c.channel, pooled_gems.c.status,
      pooled_gems.c.score.desc())

youtube_video_stats = Table(
    "youtube_video_stats", metadata,
    Column("video_id", String, nullable=False),
    Column("snapshot_date", String, nullable=False),
    Column("views", Integer, default=0),
    Column("likes", Integer, default=0),
    Column("comments", Integer, default=0),
    Column("watch_time_min", Float, default=0.0),
    Column("avg_view_duration_s", Float, default=0.0),
    # Dönüşüm görünürlüğü (2026-07-16): abone kazanımı video başına 7x oynuyor —
    # hangi video dönüştürüyor görmeden içerik kararı alınamaz. Pencere metriği
    # (7 gün), kümülatif değil. avg_view_percentage Shorts loop'larıyla %100'ü aşar.
    Column("subscribers_gained", Integer, default=0),
    Column("avg_view_percentage", Float, default=0.0),
    Column("updated_at", DateTime, default=_utcnow),
)
Index("idx_yt_video_stats_video_date",
      youtube_video_stats.c.video_id, youtube_video_stats.c.snapshot_date,
      unique=True)

youtube_channel_stats = Table(
    "youtube_channel_stats", metadata,
    Column("channel", String, nullable=False),
    Column("snapshot_date", String, nullable=False),
    Column("subscribers", Integer, default=0),
    Column("total_views", Integer, default=0),
    Column("updated_at", DateTime, default=_utcnow),
)
Index("idx_yt_channel_stats_chan_date",
      youtube_channel_stats.c.channel, youtube_channel_stats.c.snapshot_date,
      unique=True)

youtube_quota = Table(
    "youtube_quota", metadata,
    Column("channel", String, nullable=False),
    Column("date", String, nullable=False),
    Column("units_used", Integer, default=0),
    Column("updated_at", DateTime, default=_utcnow),
)
Index("idx_yt_quota_chan_date",
      youtube_quota.c.channel, youtube_quota.c.date, unique=True)

dna_cache = Table(
    "dna_cache", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel_slug", String, nullable=False),
    Column("topic_text", Text, nullable=False),
    Column("embedding", Text, nullable=False),  # JSON array of floats; small enough
    Column("dna_json", Text, nullable=False),
    Column("css_filename", String, nullable=False),
    Column("archetype", String, nullable=False),
    Column("created_at", DateTime, default=_utcnow, nullable=False),
    Column("last_used_at", DateTime),
    Column("hit_count", Integer, default=0, nullable=False),
)
Index("idx_dna_cache_channel_created",
      dna_cache.c.channel_slug, dna_cache.c.created_at)

# Per-channel performance insights computed nightly (and on-demand from the
# /insights/<slug> web view). data_json is the structured aggregation dict
# documented in short_bot.learning.aggregator.compute_channel_insights().
# Used both for UI display AND for scorer prompt injection (so future runs
# inherit "what's actually worked for this channel").
channel_insights = Table(
    "channel_insights", metadata,
    Column("channel", String, primary_key=True),
    Column("computed_at", DateTime, default=_utcnow, nullable=False),
    Column("sample_size", Integer, default=0, nullable=False),
    Column("data_json", Text, nullable=False),
)

# Kanıtlanmış-konu bankası: YouTube outlier madenciliğinden damıtılmış konu
# fikirleri. Üretim anında API'ye GİDİLMEZ — bu tablo okunur (spec:
# docs/superpowers/specs/2026-07-12-topic-bank-design.md).
topic_bank = Table(
    "topic_bank", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False, index=True),
    Column("topic", Text, nullable=False),
    Column("source_title", Text, default="", nullable=False),
    Column("views", Integer, default=0, nullable=False),
    Column("subs", Integer, default=0, nullable=False),
    Column("hook_pattern", String, default="", nullable=False),
    # KONUNUN KAYNAĞI: kanıtlı mı, üretilmiş mi?
    #   reference — referans kanalın kendi outlier'ı (format+kitle kanıtlı, en güçlü)
    #   search    — arama outlier'ı (izlenme/abone oranıyla kanıtlı)
    #   llm       — modelin üretimi, YouTube kanıtı YOK
    # Kanıtsız bir konuyu kanıtlı sanmak sessiz bir yanılgıdır; kullanıcı hangisine
    # baktığını bilmeli.
    Column("source", String, default="search", nullable=False),
    Column("status", String, default="active", nullable=False),  # active|used|rejected
    Column("created_at", DateTime, default=_utcnow, nullable=False),
    Column("used_at", DateTime),
)

# Küçük anahtar-değer defteri. Şimdilik tek müşterisi: konu bankasının son DOLDURMA
# DENEMESİ. Neden ayrı bir defter gerekti — topic_bank.created_at son EKLENEN konunun
# tarihidir, son denemenin değil. Niş tükenip madencilik 0 konu eklediğinde o tarih
# donar; kota koruması bir daha asla tetiklenmez ve 4 saatlik iş her seferinde ~400
# birim yakar. Deneme kaydı, sonuç ne olursa olsun düşer.
kv = Table(
    "kv", metadata,
    Column("k", String, primary_key=True),
    Column("v", Text, default="", nullable=False),
    Column("updated_at", DateTime, default=_utcnow, onupdate=_utcnow, nullable=False),
)


# SERİ BÖLÜMLERİ (bkz. reel_series). Konu planlamasını video düzeyinden ARK düzeyine
# çıkaran kayıt: her bölüm bir KAPI açar (open_loop) ve o kapı, BİR SONRAKİ bölümün
# konu tohumu olur. Bu tablo olmadan zincir kurulamaz — bölüm numarası da, ödenecek
# söz de kalıcı olmalı (üretim süreçleri arasında yaşamalı).
series_episodes = Table(
    "series_episodes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False, index=True),
    Column("episode_no", Integer, nullable=False),   # kanal ömrü boyunca artan
    Column("arc_pos", Integer, default=1, nullable=False),   # arkın kaçıncı bölümü
    Column("topic", Text, default="", nullable=False),
    Column("open_loop", Text, default="", nullable=False),   # sonrakine bırakılan söz
    Column("short_id", Integer, ForeignKey("shorts.id")),
    Column("created_at", DateTime, default=_utcnow, nullable=False),
)


# PLANLI ARK (bkz. reel_arc). Zincirden farkı: bölümler ÖNCEDEN planlanır ve kullanıcı
# ONAYLAR. Plan JSON olarak durur — ayrı bir kalem tablosuna bölmenin faydası yok:
# plan bir BÜTÜN olarak onaylanıyor, tek tek düzenlenmiyor. Hangi kalemin üretildiğini
# 'produced' sayacı taşır (series_episodes zaten bölüm bölüm kayıt tutuyor).
#
# status: draft   → LLM plan yazdı, kullanıcı henüz onaylamadı (ÜRETİME GİRMEZ)
#         active  → onaylandı, bölümleri sırayla üretiliyor
#         done    → tüm bölümleri üretildi
#         discarded → kullanıcı attı
series_arcs = Table(
    "series_arcs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False, index=True),
    Column("title", Text, default="", nullable=False),
    Column("seed_topic", Text, default="", nullable=False),   # arkı doğuran banka konusu
    Column("plan_json", Text, nullable=False),                # [{topic, promise}, ...]
    Column("status", String, default="draft", nullable=False),
    Column("produced", Integer, default=0, nullable=False),   # kaç bölümü üretildi
    Column("created_at", DateTime, default=_utcnow, nullable=False),
    Column("approved_at", DateTime),
)


# AUTOPILOT SLOTLARI (bkz. autopilot.py). Sistemin TEK doğruluk kaynağı: "bugün ne
# üretilecek, ne zaman yayınlanacak, hangisi patladı" sorularının cevabı burada.
#
# UNIQUE (channel, slot_local_date, slot_index) HAYATİ: planlayıcı hem gece cron'unda
# HEM UYGULAMA AÇILIŞINDA koşuyor. Kısıt olmasa aynı gün iki kez planlanır → KOPYA SLOT
# → aynı slot için iki video üretilir ve ikisi de yüklenir. Hiçbir hata vermez.
publish_slots = Table(
    "publish_slots", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String, nullable=False, index=True),
    Column("slot_local_date", String, nullable=False),   # kanalın YEREL günü
    Column("slot_index", Integer, nullable=False),
    Column("slot_at_utc", DateTime, nullable=False),
    Column("jitter_min", Integer, default=0, nullable=False),   # HAM sapma
    # SLOT TÜRÜ: series | standalone
    #
    # Seri bölümü izleyiciye "#2 YARIN" diye söz veriyor. Günde 3 bölüm üretilirse
    # 3 bölümlük ark BİR GÜNDE biter ve #2 aynı gün yayınlanır — söz YALAN olur.
    # Bu yüzden günde EN FAZLA series_per_day (varsayılan 1) slot seri bölümüdür;
    # kalanlar bankadan bağımsız konu üretir ve ARK TÜKETMEZ.
    Column("kind", String, default="standalone", nullable=False),
    # planned → producing → produced → scheduled → published
    #                    ↘ failed        ↘ skipped
    Column("status", String, default="planned", nullable=False),
    Column("short_id", Integer, ForeignKey("shorts.id")),
    Column("run_id", Integer, ForeignKey("runs.id")),
    Column("attempts", Integer, default=0, nullable=False),
    Column("produced_at", DateTime),
    Column("uploaded_at", DateTime),
    Column("error", Text),
    Column("created_at", DateTime, default=_utcnow, nullable=False),
    UniqueConstraint("channel", "slot_local_date", "slot_index",
                     name="uq_publish_slot"),
)


feeds = Table(
    "feeds", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("url", Text, nullable=False, unique=True),
    Column("title", Text),
    Column("enabled", Integer, default=1, nullable=False),
    Column("added_at", DateTime, default=_utcnow, nullable=False),
    Column("last_fetched_at", DateTime),
    Column("last_error", Text),
)


def init_db(db_path: Path | str) -> Engine:
    """Create engine, enable WAL + FK + busy_timeout, create schema if absent."""
    db_path = Path(db_path).resolve()    # absolute, avoids cwd surprises
    db_path.parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    with eng.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.exec_driver_sql("PRAGMA busy_timeout=5000")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    metadata.create_all(eng)
    # Also create generator-mode tables (separate MetaData object)
    from short_bot.generated_db import metadata as generator_metadata
    generator_metadata.create_all(eng)
    # Idempotent column-level migrations for tables that pre-date a feature.
    # create_all only creates missing tables, not missing columns.
    _migrate_add_columns(eng)
    return eng


def _migrate_add_columns(eng: Engine) -> None:
    """Add columns introduced in later versions to pre-existing production DBs.

    SQLite ALTER TABLE ADD COLUMN is non-locking and idempotent when guarded
    by a PRAGMA table_info check, so re-running init_db is safe.
    """
    migrations: list[tuple[str, str, str]] = [
        # (table, column, type)
        ("processed_items", "embedding_json", "TEXT"),
        ("processed_items", "produced_title_embedding_json", "TEXT"),
        # SLOT TÜRÜ (bkz. publish_slots): önce planlanmış slotlar 'standalone'
        # sayılır — seriyi ilerletmezler. Güvenli varsayılan: yanlışlıkla seri
        # bölümü üretip arkı tüketmektense hiç üretmemek yeğdir.
        ("publish_slots", "kind", "TEXT DEFAULT 'standalone' NOT NULL"),
        # KONUNUN KAYNAĞI. Mevcut kayıtların hepsi arama/referans outlier'larından
        # geldi → 'search'. Yeni: 'llm' (modelin üretimi, YouTube kanıtı yok).
        ("topic_bank", "source", "TEXT DEFAULT 'search' NOT NULL"),
        # Dönüşüm metrikleri (bkz. youtube_video_stats tablo tanımı).
        ("youtube_video_stats", "subscribers_gained", "INTEGER DEFAULT 0"),
        ("youtube_video_stats", "avg_view_percentage", "REAL DEFAULT 0.0"),
    ]
    with eng.begin() as conn:
        for table, col, coltype in migrations:
            existing = conn.exec_driver_sql(
                f"PRAGMA table_info({table})"
            ).fetchall()
            names = {row[1] for row in existing}
            if col not in names:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"
                )


def mark_processed(
    eng: Engine, guid: str, title: str, channel: str,
    *, embedding: list[float] | None = None,
    produced_title_embedding: list[float] | None = None,
) -> None:
    """Mark item as processed. embedding (RSS-side) and produced_title_embedding
    (Claude-side, after script generation) are optional; both feed downstream
    dedup checks against future candidates."""
    import json as _json
    with eng.begin() as conn:
        conn.execute(
            processed_items.insert().prefix_with("OR IGNORE"),
            {"guid": guid, "title": title, "channel": channel,
             "processed_at": _utcnow(),
             "embedding_json": _json.dumps(embedding) if embedding else None,
             "produced_title_embedding_json":
                 _json.dumps(produced_title_embedding)
                 if produced_title_embedding else None},
        )


def fetch_recent_embeddings(
    eng: Engine, channel: str, *, lookback_days: int = 14,
) -> list[list[float]]:
    """Return all non-null RSS-title embeddings for `channel` in the last
    `lookback_days`. Rows with NULL embedding_json (pre-feature legacy or
    no API key at the time) are silently skipped."""
    return _fetch_recent_embedding_column(
        eng, channel, lookback_days, "embedding_json",
    )


def fetch_recent_produced_title_embeddings(
    eng: Engine, channel: str, *, lookback_days: int = 14,
) -> list[list[float]]:
    """Return all non-null Claude-PRODUCED-title embeddings for `channel` in
    the last `lookback_days`. Drives the second dedup layer that catches the
    case where multiple publishers' RSS titles diverge but Claude normalizes
    them all to the same headline."""
    return _fetch_recent_embedding_column(
        eng, channel, lookback_days, "produced_title_embedding_json",
    )


def _fetch_recent_embedding_column(
    eng: Engine, channel: str, lookback_days: int, column: str,
) -> list[list[float]]:
    import json as _json
    cutoff = _utcnow() - timedelta(days=lookback_days)
    col = getattr(processed_items.c, column)
    with eng.connect() as conn:
        rows = conn.execute(
            select(col)
            .where(processed_items.c.channel == channel)
            .where(processed_items.c.processed_at >= cutoff)
            .where(col.is_not(None))
        ).fetchall()
    out: list[list[float]] = []
    for (raw,) in rows:
        if not raw:
            continue
        try:
            vec = _json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(vec, list) and vec:
            out.append(vec)
    return out


def is_processed(eng: Engine, guid: str, channel: str) -> bool:
    with eng.connect() as conn:
        row = conn.execute(
            select(processed_items.c.guid)
            .where(processed_items.c.guid == guid)
            .where(processed_items.c.channel == channel)
        ).fetchone()
    return row is not None


def similar_title_exists(
    eng: Engine,
    title: str,
    channel: str,
    threshold: float,
    *,
    lookback_days: int = 30,
) -> bool:
    """Fuzzy match against titles processed within lookback window (default 30 days)."""
    cutoff = _utcnow() - timedelta(days=lookback_days)
    with eng.connect() as conn:
        rows = conn.execute(
            select(processed_items.c.title)
            .where(processed_items.c.channel == channel)
            .where(processed_items.c.processed_at >= cutoff)
        ).fetchall()
    title_low = title.lower()
    for (existing,) in rows:
        if SequenceMatcher(None, title_low, existing.lower()).ratio() >= threshold:
            return True
    return False


def record_rss_item(
    eng: Engine, *, guid, channel, title, link, source,
    pub_date, thumb_url, score, status,
) -> int:
    with eng.begin() as conn:
        result = conn.execute(rss_items.insert().values(
            guid=guid, channel=channel, title=title, link=link,
            source=source, pub_date=pub_date, thumb_url=thumb_url,
            score=score, status=status, fetched_at=_utcnow(),
        ))
        return result.inserted_primary_key[0]


def record_short(
    eng: Engine, *, channel, rss_item_guid, title, file_path,
    duration_s, script_json, render_ms,
) -> int:
    with eng.begin() as conn:
        result = conn.execute(shorts.insert().values(
            channel=channel, rss_item_guid=rss_item_guid, title=title,
            file_path=file_path, duration_s=duration_s, script_json=script_json,
            render_ms=render_ms, created_at=_utcnow(),
        ))
        return result.inserted_primary_key[0]


def count_recent_categories(
    eng: Engine, channel: str, *, hours: int = 24,
) -> dict[str, int]:
    """Son `hours` saatte bu kanalda hangi konudan kaç video üretildi.

    Kategori kotasının girdisi. Etiketler normalize edilerek sayılır —
    yazım farkı ("Transfer" / "transfer") kotayı iki ayrı kovaya bölüp
    hiç dolmamasına yol açardı.
    """
    import json as _json
    from short_bot.topic_taxonomy import normalize_category

    cutoff = _utcnow() - timedelta(hours=hours)
    counts: dict[str, int] = {}
    with eng.connect() as conn:
        rows = conn.execute(
            select(shorts.c.script_json)
            .select_from(
                shorts.outerjoin(youtube_uploads,
                                 youtube_uploads.c.short_id == shorts.c.id)
            )
            .where(shorts.c.channel == channel)
            .where(shorts.c.created_at >= cutoff)
            # "Silinmiş" ile "reddedilmiş" AYNI ŞEY DEĞİL. Operatörün akışı
            # ölçüldü: üret → incele → beğenirse YÜKLE ve listeden sil,
            # beğenmezse doğrudan sil. Son 24 saatteki 13 videonun 12'si
            # deleted_at taşıyordu ama 7'si YouTube'da yayındaydı — yalnız
            # deleted_at'e bakan bir filtre kotayı fiilen öldürürdü.
            # Kota ölçüsü: yayınlanan (izleyici gördü) + henüz karar
            # verilmemiş videolar sayılır; yalnızca YÜKLENMEDEN silinmiş
            # olanlar sayılmaz.
            .where(~(shorts.c.deleted_at.is_not(None)
                     & youtube_uploads.c.id.is_(None)))
        ).all()
    for (script_json,) in rows:
        try:
            raw = (_json.loads(script_json or "{}") or {}).get("category")
        except (TypeError, ValueError):
            raw = None
        if not raw:
            continue
        key = normalize_category(raw)
        counts[key] = counts.get(key, 0) + 1
    return counts


def count_recent_subjects(
    eng: Engine, channel: str, *, days: int = 14,
) -> dict[str, int]:
    """Son `days` günde bu kanalda hangi özneden kaç video üretildi.

    Saga cezasının girdisi. `count_recent_categories` ile AYNI join'i kullanır
    ve bu bilinçlidir: "silinmiş" ile "reddedilmiş" aynı şey değil. Operatör
    beğendiği videoyu YÜKLEYİP listeden siliyor; yalnız `deleted_at`'e bakan
    bir filtre, yayınlanmış videoları saymayıp sayacı fiilen öldürürdü.
    Sayılan: yayınlanan + henüz karar verilmemiş. Sayılmayan: yüklenmeden
    silinmiş (operatörün reddettiği).
    """
    import json as _json
    from short_bot.topic_taxonomy import normalize_subject

    cutoff = _utcnow() - timedelta(days=days)
    counts: dict[str, int] = {}
    with eng.connect() as conn:
        rows = conn.execute(
            select(shorts.c.script_json)
            .select_from(
                shorts.outerjoin(youtube_uploads,
                                 youtube_uploads.c.short_id == shorts.c.id)
            )
            .where(shorts.c.channel == channel)
            .where(shorts.c.created_at >= cutoff)
            .where(~(shorts.c.deleted_at.is_not(None)
                     & youtube_uploads.c.id.is_(None)))
        ).all()
    for (script_json,) in rows:
        try:
            raw = (_json.loads(script_json or "{}") or {}).get("subject")
        except (TypeError, ValueError):
            raw = None
        if not raw:
            continue
        key = normalize_subject(raw)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def start_run(eng: Engine, channel: str, trigger: str, log_path: str) -> int:
    with eng.begin() as conn:
        result = conn.execute(runs.insert().values(
            channel=channel, trigger=trigger, status="running",
            started_at=_utcnow(), log_path=log_path,
        ))
        return result.inserted_primary_key[0]


def is_run_cancelled(eng: Engine, run_id: int) -> bool:
    """Kullanıcı bu koşuyu panelden iptal etti mi?

    İptal düğmesi DB'de statüyü 'cancelled' yapar. Boru hattı bunu FAZ SINIRLARINDA
    yoklar ve durur — yoksa düğme yalan söylerdi: arayüzde iptal görünürken arka
    planda iş sürer, LLM/TTS/vision kredisi yanmaya devam ederdi.
    """
    with eng.connect() as conn:
        row = conn.execute(
            select(runs.c.status).where(runs.c.id == run_id)
        ).fetchone()
    return bool(row) and row[0] == "cancelled"


def finish_run(
    eng: Engine, run_id: int, *,
    status: str, short_id: int | None = None, error: str | None = None,
) -> None:
    with eng.begin() as conn:
        conn.execute(runs.update().where(runs.c.id == run_id).values(
            ended_at=_utcnow(), status=status,
            short_id=short_id, error=error,
        ))


def _kilit_serbest(lock_dir: Path, channel: str) -> bool:
    """Kanalın üretim kilidi SAHİPSİZ mi? (True = onu tutan canlı süreç yok)"""
    from filelock import FileLock, Timeout
    try:
        with FileLock(str(Path(lock_dir) / f"{channel}.lock"), timeout=0):
            return True
    except Timeout:
        return False
    except OSError:
        # Kilit dosyası açılamadı — canlılık hakkında bir şey söyleyemeyiz.
        return False


def cleanup_zombie_runs(
    eng: Engine, lock_dir: Path | None = None, *, age_minutes: int = 60,
) -> int:
    """Ölmüş 'running' satırlarını 'failed' işaretle ve sahipsiz kilitlerini sil.

    GERÇEK OLAY (2026-07-14): panel, bir üretim koşarken yeniden başlatıldı. Üretim
    thread'i panelle birlikte öldü; runs satırı 'running' kaldı ve panel "Aşama 4/8"
    gösterip durdu. Kullanıcı "takılmış olabilir" dedi — haklıydı.

    ESKİ ÖLÇÜT YANLIŞTI: yalnız YAŞA bakıyordu (>60 dk). Ölen koşu, panel yeniden
    başladığında 9 DAKİKALIKTI → temizleyici ona dokunmadı → satır sonsuza dek
    'running' kaldı (periyodik süpürücü de yok).

    DOĞRU ÖLÇÜT CANLILIK:
      • KİLİT SERBEST → sahibi ölü. Yaş fark etmez; bu fonksiyon açılışta koşuyor ve
        önceki sürecin thread'i hayatta olamaz. Canlı bir üretim kilidini TUTAR.
      • KİLİT TUTULUYOR ama koşu ``age_minutes``tan eski → süreç canlı ama üretim
        asılı kalmış olabilir; yine temizle (eski davranış, ikincil güvenlik ağı).

    lock_dir verilmezse canlılık ölçülemez → yalnız yaş kuralı işler (eski davranış).
    """
    from sqlalchemy import text
    with eng.begin() as conn:
        acik = list(conn.execute(text(
            "SELECT id, channel, datetime(started_at) < datetime('now', :delta) "
            "AS eski FROM runs WHERE status = 'running'"
        ), {"delta": f"-{age_minutes} minutes"}))

        stale = []
        for r in acik:
            if lock_dir is not None and _kilit_serbest(Path(lock_dir), r.channel):
                stale.append((r, "panel yeniden başlatıldı / süreç öldü "
                                 "(üretim kilidi sahipsiz)"))
            elif r.eski:
                stale.append((r, f"zombi temizliği (>{age_minutes} dk asılı kaldı)"))

        if not stale:
            return 0
        for r, sebep in stale:
            conn.execute(text(
                "UPDATE runs SET ended_at = datetime('now'), status = 'failed', "
                "error = :err WHERE id = :id"
            ), {"err": sebep, "id": r.id})

    if lock_dir is not None:
        for r, _ in stale:
            try:
                (Path(lock_dir) / f"{r.channel}.lock").unlink(missing_ok=True)
            except OSError:
                pass
    return len(stale)


def reclaim_producing_slots(eng: Engine) -> int:
    """'producing'de asılı kalan otomasyon slotlarını 'planned'a geri al.

    ⚠ YALNIZ AÇILIŞTA ÇAĞIR. Panel koşarken çağırmak ÇİFTE ÜRETİM yapar: o an gerçekten
    üretilen bir slot 'planned'a döner ve bir sonraki tick onu ikinci kez üretime verir.
    Açılışta ise 'producing' olan her slot TANIMI GEREĞİ öksüzdür — onu üreten thread
    bir önceki süreçteydi ve o süreç artık yok.

    SESSİZ KAYIP (2026-07-14'te yaşandı): üretim thread'i panelle birlikte ölünce slot
    'producing'de dondu ve otomasyon onu BİR DAHA ELE ALMADI (tick yalnız 'planned'
    slotları üretime verir). Günün videosu yok oldu ve bunu hiçbir şey söylemedi.

    ``attempts`` sayacına DOKUNULMAZ: sıfırlansaydı max_attempts sınırı çöker ve
    sürekli patlayan bir slot sonsuza dek yeniden denenirdi.
    """
    with eng.begin() as conn:
        return conn.execute(
            publish_slots.update()
            .where(publish_slots.c.status == "producing")
            .values(status="planned")).rowcount


def record_youtube_upload(
    eng: Engine, *, short_id: int, video_id: str | None,
    status: str, error: str | None, video_url: str | None,
) -> int:
    with eng.begin() as conn:
        result = conn.execute(youtube_uploads.insert().values(
            short_id=short_id, video_id=video_id, video_url=video_url,
            status=status, error=error, uploaded_at=_utcnow(),
        ))
        return result.inserted_primary_key[0]


def get_youtube_upload_for_short(eng: Engine, *, short_id: int):
    """Most recent upload row for a short, or None."""
    with eng.connect() as conn:
        return conn.execute(
            select(youtube_uploads)
            .where(youtube_uploads.c.short_id == short_id)
            .order_by(youtube_uploads.c.uploaded_at.desc())
            .limit(1)
        ).first()


def list_youtube_uploads_for_channel(eng: Engine, channel: str, *, limit: int = 20):
    """Recent uploads for a channel (joined via shorts.channel)."""
    with eng.connect() as conn:
        return list(conn.execute(
            select(youtube_uploads)
            .join(shorts, youtube_uploads.c.short_id == shorts.c.id)
            .where(shorts.c.channel == channel)
            .order_by(youtube_uploads.c.uploaded_at.desc())
            .limit(limit)
        ))


def get_rss_item_for_short(eng: Engine, *, short_id: int):
    """Return the rss_items row matching this short's rss_item_guid, or None.

    Generator-mode shorts have rss_item_guid=None and naturally return None.
    Used to surface source/link for YouTube descriptions.
    """
    with eng.connect() as conn:
        s = conn.execute(
            select(shorts.c.rss_item_guid, shorts.c.channel)
            .where(shorts.c.id == short_id)
        ).first()
        if s is None or s.rss_item_guid is None:
            return None
        return conn.execute(
            select(rss_items)
            .where(rss_items.c.guid == s.rss_item_guid)
            .where(rss_items.c.channel == s.channel)
            .limit(1)
        ).first()


def get_last_youtube_upload_at(eng: Engine):
    """Return the uploaded_at timestamp of the most recent successful upload
    across all channels, or None when no successes exist. Used for global
    cooldown / stagger between auto-uploads."""
    with eng.connect() as conn:
        row = conn.execute(
            select(youtube_uploads.c.uploaded_at)
            .where(youtube_uploads.c.status == "success")
            .order_by(youtube_uploads.c.uploaded_at.desc())
            .limit(1)
        ).first()
        return row[0] if row else None


def upsert_video_stats(eng: Engine, *, video_id: str, snapshot_date,
                       views: int, likes: int, comments: int,
                       watch_time_min: float, avg_view_duration_s: float,
                       subscribers_gained: int = 0,
                       avg_view_percentage: float = 0.0) -> None:
    """UPSERT a video stats row keyed on (video_id, snapshot_date)."""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    iso = snapshot_date.isoformat()
    with eng.begin() as conn:
        stmt = sqlite_insert(youtube_video_stats).values(
            video_id=video_id, snapshot_date=iso,
            views=views, likes=likes, comments=comments,
            watch_time_min=watch_time_min,
            avg_view_duration_s=avg_view_duration_s,
            subscribers_gained=subscribers_gained,
            avg_view_percentage=avg_view_percentage,
            updated_at=_utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["video_id", "snapshot_date"],
            set_=dict(
                views=views, likes=likes, comments=comments,
                watch_time_min=watch_time_min,
                avg_view_duration_s=avg_view_duration_s,
                subscribers_gained=subscribers_gained,
                avg_view_percentage=avg_view_percentage,
                updated_at=_utcnow(),
            ),
        )
        conn.execute(stmt)


def get_video_stats_for_short(eng: Engine, *, short_id: int, days: int = 30):
    """Recent stats rows for the short's YouTube video, newest first."""
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    with eng.connect() as conn:
        upload = conn.execute(
            select(youtube_uploads.c.video_id)
            .where(youtube_uploads.c.short_id == short_id)
            .where(youtube_uploads.c.status == "success")
            .order_by(youtube_uploads.c.uploaded_at.desc())
            .limit(1)
        ).first()
        if upload is None or upload.video_id is None:
            return []
        return list(conn.execute(
            select(youtube_video_stats)
            .where(youtube_video_stats.c.video_id == upload.video_id)
            .where(youtube_video_stats.c.snapshot_date >= cutoff)
            .order_by(youtube_video_stats.c.snapshot_date.desc())
        ))


def upsert_channel_stats(eng: Engine, *, channel: str, snapshot_date,
                          subscribers: int, total_views: int) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    iso = snapshot_date.isoformat()
    with eng.begin() as conn:
        stmt = sqlite_insert(youtube_channel_stats).values(
            channel=channel, snapshot_date=iso,
            subscribers=subscribers, total_views=total_views,
            updated_at=_utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["channel", "snapshot_date"],
            set_=dict(subscribers=subscribers, total_views=total_views,
                      updated_at=_utcnow()),
        )
        conn.execute(stmt)


def get_channel_stats_history(eng: Engine, *, channel: str, days: int = 7):
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    with eng.connect() as conn:
        return list(conn.execute(
            select(youtube_channel_stats)
            .where(youtube_channel_stats.c.channel == channel)
            .where(youtube_channel_stats.c.snapshot_date >= cutoff)
            .order_by(youtube_channel_stats.c.snapshot_date.desc())
        ))


def incr_quota(eng: Engine, *, channel: str, units: int) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    today_iso = datetime.now(timezone.utc).date().isoformat()
    with eng.begin() as conn:
        stmt = sqlite_insert(youtube_quota).values(
            channel=channel, date=today_iso, units_used=units,
            updated_at=_utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["channel", "date"],
            set_=dict(
                units_used=youtube_quota.c.units_used + units,
                updated_at=_utcnow(),
            ),
        )
        conn.execute(stmt)


def get_quota_used_today(eng: Engine, *, channel: str) -> int:
    today_iso = datetime.now(timezone.utc).date().isoformat()
    with eng.connect() as conn:
        row = conn.execute(
            select(youtube_quota.c.units_used)
            .where(youtube_quota.c.channel == channel)
            .where(youtube_quota.c.date == today_iso)
        ).first()
        return int(row[0]) if row else 0


def count_uploads_for_channel(eng: Engine, channel: str) -> int:
    """Total successful YT uploads for a channel (joined via shorts.channel)."""
    from sqlalchemy import func
    with eng.connect() as conn:
        row = conn.execute(
            select(func.count())
            .select_from(youtube_uploads.join(shorts, youtube_uploads.c.short_id == shorts.c.id))
            .where(shorts.c.channel == channel)
            .where(youtube_uploads.c.status == "success")
        ).first()
        return int(row[0]) if row else 0


def last_upload_at_for_channel(eng: Engine, channel: str):
    """Most recent successful upload timestamp for a channel, or None."""
    with eng.connect() as conn:
        row = conn.execute(
            select(youtube_uploads.c.uploaded_at)
            .select_from(youtube_uploads.join(shorts, youtube_uploads.c.short_id == shorts.c.id))
            .where(shorts.c.channel == channel)
            .where(youtube_uploads.c.status == "success")
            .order_by(youtube_uploads.c.uploaded_at.desc())
            .limit(1)
        ).first()
        return row[0] if row else None


def upsert_channel_insights(eng: Engine, *, channel: str, sample_size: int,
                              data_json: str) -> None:
    """Persist computed insights for `channel`. Overwrites any prior row."""
    import json as _json
    with eng.begin() as conn:
        # SQLite-friendly upsert: try update first, insert if no row touched
        result = conn.execute(
            channel_insights.update()
            .where(channel_insights.c.channel == channel)
            .values(computed_at=_utcnow(), sample_size=sample_size,
                    data_json=data_json)
        )
        if result.rowcount == 0:
            conn.execute(channel_insights.insert().values(
                channel=channel, computed_at=_utcnow(),
                sample_size=sample_size, data_json=data_json,
            ))


def load_channel_insights(eng: Engine, channel: str) -> dict | None:
    """Return the cached insights dict for `channel`, or None when missing.

    Returned dict shape mirrors short_bot.learning.aggregator output plus a
    `_meta` wrapper with `computed_at` (ISO timestamp) and `sample_size`.
    """
    import json as _json
    with eng.connect() as conn:
        row = conn.execute(
            select(channel_insights).where(channel_insights.c.channel == channel)
        ).first()
    if row is None:
        return None
    try:
        data = _json.loads(row.data_json)
    except (ValueError, TypeError):
        return None
    data["_meta"] = {
        "computed_at": (row.computed_at.isoformat()
                         if row.computed_at else None),
        "sample_size": int(row.sample_size or 0),
    }
    return data


def load_channels_with_uploads(eng: Engine) -> list[str]:
    """Distinct channel slugs that have at least one successful YT upload.
    Used by the nightly insights aggregation cron to decide which channels
    need a refresh."""
    with eng.connect() as conn:
        rows = conn.execute(
            select(shorts.c.channel).distinct()
            .select_from(youtube_uploads.join(shorts, youtube_uploads.c.short_id == shorts.c.id))
            .where(youtube_uploads.c.status == "success")
        ).all()
    return [r[0] for r in rows]


def backfill_produced_embeddings(
    eng: Engine, openai_api_key: str, *, days: int = 14,
) -> dict[str, int]:
    """Retroactively populate produced_title_embedding_json for processed_items
    whose row exists but lacks the new column (records created before the
    feature shipped). Embeds the Claude-produced header from shorts.script_json
    joined by RSS GUID. Returns {'updated': N, 'skipped': M, 'errors': K}.

    Idempotent: rows that already have a non-null embedding are skipped.
    """
    import json as _json
    from datetime import timedelta
    from short_bot.embeddings import embed_text, EmbeddingError

    if not openai_api_key:
        return {"updated": 0, "skipped": 0, "errors": 0, "no_key": 1}

    cutoff = _utcnow() - timedelta(days=days)
    # Pull processed_items rows missing the embedding, joined with shorts via
    # rss_item_guid so we can read the Claude-produced header text.
    from sqlalchemy import text
    sql = text(
        "SELECT p.guid, p.channel, s.script_json "
        "FROM processed_items p "
        "JOIN shorts s ON s.rss_item_guid = p.guid AND s.channel = p.channel "
        "WHERE p.processed_at >= :cutoff "
        "AND p.produced_title_embedding_json IS NULL "
        "AND s.script_json IS NOT NULL"
    )
    with eng.connect() as conn:
        rows = conn.execute(sql, {"cutoff": cutoff}).fetchall()

    updated = skipped = errors = 0
    for r in rows:
        try:
            sc = _json.loads(r.script_json)
        except (ValueError, TypeError):
            skipped += 1
            continue
        header = (f"{sc.get('header_top', '')} "
                  f"{sc.get('header_bottom', '')}").strip()
        if not header:
            skipped += 1
            continue
        try:
            vec = embed_text(header, api_key=openai_api_key)
        except EmbeddingError:
            errors += 1
            continue
        try:
            with eng.begin() as conn:
                conn.execute(
                    processed_items.update()
                    .where(processed_items.c.guid == r.guid)
                    .where(processed_items.c.channel == r.channel)
                    .values(produced_title_embedding_json=_json.dumps(vec))
                )
            updated += 1
        except Exception:
            errors += 1
    return {"updated": updated, "skipped": skipped, "errors": errors}


def clear_recent_failed_runs(eng: Engine, *, hours: int = 24) -> int:
    """Delete 'failed' runs that started within the last `hours` hours.

    The dashboard surfaces these in its "Son 24 saat — N hata" panel; this
    helper backs the "Hataları temizle" button. Filesystem run logs are NOT
    touched — only the DB row that drives the panel. Returns deleted count.
    """
    from sqlalchemy import text
    with eng.begin() as conn:
        result = conn.execute(
            text("DELETE FROM runs WHERE status='failed' "
                 "AND datetime(started_at) > datetime('now', :delta)"),
            {"delta": f"-{hours} hours"}
        )
        return int(result.rowcount or 0)


def add_feed(eng: Engine, *, url: str, title: str | None) -> int:
    """Insert a feed into the pool. Raises on duplicate url (UNIQUE)."""
    with eng.begin() as conn:
        result = conn.execute(feeds.insert().values(
            url=url, title=title, enabled=1, added_at=_utcnow(),
        ))
        return result.inserted_primary_key[0]


def list_feeds(eng: Engine, enabled_only: bool = False) -> list:
    """All feeds, newest first. enabled_only filters disabled rows out."""
    with eng.connect() as conn:
        stmt = select(feeds)
        if enabled_only:
            stmt = stmt.where(feeds.c.enabled == 1)
        return list(conn.execute(stmt.order_by(feeds.c.added_at.desc())))


def get_feed(eng: Engine, feed_id: int):
    """Single feed row by id, or None."""
    with eng.connect() as conn:
        return conn.execute(
            select(feeds).where(feeds.c.id == feed_id)
        ).first()


def delete_feed(eng: Engine, feed_id: int) -> None:
    """Delete a feed by id. No-op (silent) if the id does not exist."""
    with eng.begin() as conn:
        conn.execute(feeds.delete().where(feeds.c.id == feed_id))


def set_feed_meta(
    eng: Engine, feed_id: int, *,
    last_fetched_at: datetime | None = None,
    last_error: str | None = None,
    title: str | None = None,
    enabled: int | None = None,
) -> None:
    """Patch fetch-state / enabled / title. Only non-None args are written.
    To CLEAR a prior error, pass last_error="" (empty string is written;
    None means 'leave unchanged')."""
    values: dict = {}
    if last_fetched_at is not None:
        values["last_fetched_at"] = last_fetched_at
    if last_error is not None:
        values["last_error"] = last_error
    if title is not None:
        values["title"] = title
    if enabled is not None:
        values["enabled"] = enabled
    if not values:
        return
    with eng.begin() as conn:
        conn.execute(feeds.update().where(feeds.c.id == feed_id).values(**values))


# ── Kanıtlanmış-konu bankası yardımcıları ────────────────────────────────

def insert_bank_topics(eng: Engine, channel: str, rows: list[dict]) -> int:
    """Damıtılmış konu kayıtlarını ekler (dedup ÇAĞIRANDA). Eklenen sayısı döner."""
    if not rows:
        return 0
    with eng.begin() as conn:
        for r in rows:
            conn.execute(topic_bank.insert().values(
                channel=channel, topic=str(r.get("topic", ""))[:500],
                source_title=str(r.get("source_title", ""))[:500],
                views=int(r.get("views", 0) or 0), subs=int(r.get("subs", 0) or 0),
                hook_pattern=str(r.get("hook_pattern", ""))[:200],
                source=str(r.get("source") or "search")[:20],
            ))
    return len(rows)


def _bank_row_dict(row) -> dict:
    return {"id": row.id, "topic": row.topic, "source_title": row.source_title,
            "views": row.views, "subs": row.subs,
            "hook_pattern": row.hook_pattern, "status": row.status,
            # reference | search | llm — kanıtlı mı, üretilmiş mi?
            "source": getattr(row, "source", "search") or "search",
            "created_at": row.created_at, "used_at": row.used_at}


def active_bank_topics(eng: Engine, channel: str, limit: int = 10) -> list[dict]:
    """status=active kayıtlar, en yeni önce (üretim prompt'u için)."""
    with eng.connect() as conn:
        rows = conn.execute(
            select(topic_bank).where(topic_bank.c.channel == channel)
            .where(topic_bank.c.status == "active")
            .order_by(topic_bank.c.created_at.desc()).limit(limit)).all()
    return [_bank_row_dict(r) for r in rows]


def kv_touch(eng: Engine, k: str, v: str = "", *, at: datetime | None = None) -> None:
    """Anahtarı damgala (varsa güncelle, yoksa oluştur).

    ``at`` ŞART OLABİLİR: çağıran enjekte edilmiş bir saatle çalışıyorsa (autofill'in
    ``now`` parametresi gibi), burada gerçek saati damgalamak İKİ SAATİ KARIŞTIRIR ve
    sonuç günün saatine göre değişir — testler sabahleyin geçip akşam düşer. Ölçüldü.
    """
    ts = (at or _utcnow())
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)   # SQLite naive tutar
    with eng.begin() as conn:
        n = conn.execute(kv.update().where(kv.c.k == k)
                         .values(v=v, updated_at=ts)).rowcount
        if not n:
            conn.execute(kv.insert().values(k=k, v=v, updated_at=ts))


def kv_updated_at(eng: Engine, k: str):
    """Anahtarın son damga zamanı ya da None (hiç yazılmadıysa)."""
    with eng.connect() as conn:
        row = conn.execute(
            select(kv.c.updated_at).where(kv.c.k == k)).first()
    return row[0] if row else None


def active_bank_count(eng: Engine, channel: str) -> int:
    """Kaç AKTİF konu kaldı? Bankanın su seviyesi.

    Otomasyon günde ~2-3 konu tüketiyor (bağımsız videolar + arkın tohumu). Haftalık
    tazeleme ~6 konu ekliyor. Yani banka HAFTADA ~11-15 KONU KURUYOR — ve kuruduğunda
    seri durur, bağımsız videolar kanıtlanmış konu olmadan üretilir. Bu seviye
    izlenmezse bozulma SESSİZ olur.
    """
    from sqlalchemy import func
    with eng.connect() as conn:
        return int(conn.execute(
            select(func.count()).select_from(topic_bank)
            .where(topic_bank.c.channel == channel)
            .where(topic_bank.c.status == "active")).scalar() or 0)


def all_bank_topics(eng: Engine, channel: str) -> list[dict]:
    """Panel listesi: her status, en yeni önce."""
    with eng.connect() as conn:
        rows = conn.execute(
            select(topic_bank).where(topic_bank.c.channel == channel)
            .order_by(topic_bank.c.created_at.desc())).all()
    return [_bank_row_dict(r) for r in rows]


def mark_bank_topic_used(eng: Engine, topic_id: int) -> None:
    """Kaydı used işaretle. Bilinmeyen/uydurma id → sessiz no-op."""
    with eng.begin() as conn:
        conn.execute(topic_bank.update().where(topic_bank.c.id == int(topic_id))
                     .values(status="used", used_at=_utcnow()))


def reject_bank_topic(eng: Engine, topic_id: int) -> None:
    with eng.begin() as conn:
        conn.execute(topic_bank.update().where(topic_bank.c.id == int(topic_id))
                     .values(status="rejected"))


def last_episode(eng: Engine, channel: str) -> dict | None:
    """Kanalın EN SON bölümü (ark zincirini kuran kayıt) ya da None.

    Sıralama episode_no'ya göre — created_at'e DEĞİL: iki üretim aynı saniyede
    biterse (paralel koşu) created_at eşitlenip zincir yanlış halkadan devam edebilir.
    """
    with eng.connect() as conn:
        row = conn.execute(
            select(series_episodes).where(series_episodes.c.channel == channel)
            .order_by(series_episodes.c.episode_no.desc()).limit(1)).first()
    if row is None:
        return None
    return {"episode_no": row.episode_no, "arc_pos": row.arc_pos,
            "topic": row.topic, "open_loop": row.open_loop,
            "short_id": row.short_id}


def record_episode(eng: Engine, channel: str, *, episode_no: int, arc_pos: int,
                   topic: str, open_loop: str, short_id: int | None = None) -> None:
    """Üretilen bölümü kaydet. ``open_loop`` bir sonraki bölümün KONU TOHUMUDUR."""
    with eng.begin() as conn:
        conn.execute(series_episodes.insert().values(
            channel=channel, episode_no=int(episode_no), arc_pos=int(arc_pos),
            topic=str(topic or "")[:500], open_loop=str(open_loop or "")[:500],
            short_id=short_id))


def episode_history(eng: Engine, channel: str, limit: int = 20) -> list[dict]:
    """Panel için: son bölümler, en yeni önce."""
    with eng.connect() as conn:
        rows = conn.execute(
            select(series_episodes).where(series_episodes.c.channel == channel)
            .order_by(series_episodes.c.episode_no.desc()).limit(limit)).all()
    return [{"episode_no": r.episode_no, "arc_pos": r.arc_pos, "topic": r.topic,
             "open_loop": r.open_loop, "short_id": r.short_id,
             "created_at": r.created_at} for r in rows]


# --- AUTOPILOT SLOTLARI ----------------------------------------------------

def _slot_dict(row) -> dict:
    return {"id": row.id, "channel": row.channel,
            "slot_local_date": row.slot_local_date, "slot_index": row.slot_index,
            "slot_at_utc": row.slot_at_utc, "jitter_min": row.jitter_min,
            "kind": row.kind, "status": row.status,
            "short_id": row.short_id, "run_id": row.run_id,
            "attempts": row.attempts, "produced_at": row.produced_at,
            "uploaded_at": row.uploaded_at, "error": row.error}


def plan_slots(eng: Engine, channel: str, slot_local_date: str,
               slots: list[dict]) -> int:
    """Slotları yaz. VAR OLANI ASLA EZMEZ — eklenen slot sayısını döndürür.

    Planlayıcı gece cron'unda VE uygulama açılışında koşuyor. Var olan bir slotu ezmek,
    üretilmiş/yüklenmiş bir slotu 'planned'a döndürür → aynı video ikinci kez üretilir
    ve ikinci kez yüklenir. Sessiz ve geri dönüşü olmayan bir bozulma.
    """
    eklenen = 0
    with eng.begin() as conn:
        mevcut = {r[0] for r in conn.execute(
            select(publish_slots.c.slot_index)
            .where(publish_slots.c.channel == channel)
            .where(publish_slots.c.slot_local_date == slot_local_date)).all()}
        for s in slots:
            i = int(s["slot_index"])
            if i in mevcut:
                continue
            conn.execute(publish_slots.insert().values(
                channel=channel, slot_local_date=slot_local_date, slot_index=i,
                slot_at_utc=s["slot_at_utc"],
                jitter_min=int(s.get("jitter_min", 0)),
                kind=str(s.get("kind", "standalone")),
                status="planned", attempts=0))
            eklenen += 1
    return eklenen


def slots_for_date(eng: Engine, channel: str, slot_local_date: str) -> list[dict]:
    with eng.connect() as conn:
        rows = conn.execute(
            select(publish_slots).where(publish_slots.c.channel == channel)
            .where(publish_slots.c.slot_local_date == slot_local_date)
            .order_by(publish_slots.c.slot_index)).all()
    return [_slot_dict(r) for r in rows]


def slots_in_range(eng: Engine, channel: str, d1: str, d2: str) -> list[dict]:
    with eng.connect() as conn:
        rows = conn.execute(
            select(publish_slots).where(publish_slots.c.channel == channel)
            .where(publish_slots.c.slot_local_date >= d1)
            .where(publish_slots.c.slot_local_date <= d2)
            .order_by(publish_slots.c.slot_local_date,
                      publish_slots.c.slot_index)).all()
    return [_slot_dict(r) for r in rows]


def open_slots(eng: Engine, channel: str) -> list[dict]:
    """Henüz SONUÇLANMAMIŞ slotlar — tick yalnız bunlarla ilgilenir."""
    with eng.connect() as conn:
        rows = conn.execute(
            select(publish_slots).where(publish_slots.c.channel == channel)
            .where(publish_slots.c.status.in_(
                ("planned", "producing", "produced", "scheduled")))
            .order_by(publish_slots.c.slot_at_utc)).all()
    return [_slot_dict(r) for r in rows]


def slot_set_status(eng: Engine, slot_id: int, status: str, *,
                    short_id: int | None = None, run_id: int | None = None,
                    error: str | None = None) -> None:
    vals: dict = {"status": status}
    if short_id is not None:
        vals["short_id"] = int(short_id)
    if run_id is not None:
        vals["run_id"] = int(run_id)
    if error is not None:
        vals["error"] = str(error)[:1000]
    if status == "produced":
        vals["produced_at"] = _utcnow()
    if status in ("scheduled", "published"):
        vals["uploaded_at"] = _utcnow()
    with eng.begin() as conn:
        conn.execute(publish_slots.update()
                     .where(publish_slots.c.id == int(slot_id)).values(**vals))


def slot_bump_attempt(eng: Engine, slot_id: int) -> int:
    """Deneme sayacını artır, YENİ değeri döndür."""
    with eng.begin() as conn:
        row = conn.execute(select(publish_slots.c.attempts)
                           .where(publish_slots.c.id == int(slot_id))).first()
        yeni = (int(row[0] or 0) + 1) if row else 1
        conn.execute(publish_slots.update()
                     .where(publish_slots.c.id == int(slot_id))
                     .values(attempts=yeni))
    return yeni


def delete_planned_slots(eng: Engine, channel: str) -> int:
    """Henüz ÜRETİLMEMİŞ slotları sil (ayar değişince yeniden planlansınlar).

    YALNIZ 'planned'. Üretilmiş/yüklenmiş/yayınlanmış slotlara DOKUNULMAZ — onlar
    gerçekleşmiş olayların kaydı; silmek geçmişi yeniden yazmak olurdu (ve
    series_episodes'taki bölüm kaydı öksüz kalırdı).
    """
    with eng.begin() as conn:
        r = conn.execute(publish_slots.delete()
                         .where(publish_slots.c.channel == channel)
                         .where(publish_slots.c.status == "planned"))
        return int(r.rowcount or 0)


def prev_day_jitters(eng: Engine, channel: str, date_local) -> dict[int, int]:
    """Dünkü HAM sapmalar — rastgele yürüyüş buradan devam eder.

    Okunamazsa yürüyüş her gün 0'dan başlar ve slotlar tabana yapışır: her gün aynı
    dakika, yani tam da kaçınmaya çalıştığımız otomasyon parmak izi.
    """
    dun = (date_local - timedelta(days=1)).isoformat()
    with eng.connect() as conn:
        rows = conn.execute(
            select(publish_slots.c.slot_index, publish_slots.c.jitter_min)
            .where(publish_slots.c.channel == channel)
            .where(publish_slots.c.slot_local_date == dun)).all()
    return {int(r[0]): int(r[1]) for r in rows}


# --- PLANLI ARK ------------------------------------------------------------

def _arc_dict(row) -> dict:
    import json as _json
    try:
        plan = _json.loads(row.plan_json)
    except Exception:
        plan = []
    return {"id": row.id, "title": row.title, "seed_topic": row.seed_topic,
            "plan": plan, "status": row.status, "produced": row.produced,
            "created_at": row.created_at, "approved_at": row.approved_at,
            "total": len(plan),
            "remaining": max(0, len(plan) - int(row.produced or 0))}


def create_arc(eng: Engine, channel: str, *, title: str, seed_topic: str,
               plan: list[dict]) -> int:
    """Taslak ark kaydet (status=draft → ÜRETİME GİRMEZ, önce onay)."""
    import json as _json
    with eng.begin() as conn:
        r = conn.execute(series_arcs.insert().values(
            channel=channel, title=str(title or "")[:120],
            seed_topic=str(seed_topic or "")[:500],
            plan_json=_json.dumps(plan, ensure_ascii=False),
            status="draft", produced=0))
        return int(r.inserted_primary_key[0])


def _arc_by_status(eng: Engine, channel: str, status: str) -> dict | None:
    with eng.connect() as conn:
        row = conn.execute(
            select(series_arcs).where(series_arcs.c.channel == channel)
            .where(series_arcs.c.status == status)
            .order_by(series_arcs.c.id.desc()).limit(1)).first()
    return _arc_dict(row) if row is not None else None


def draft_arc(eng: Engine, channel: str) -> dict | None:
    """Onay bekleyen taslak (varsa)."""
    return _arc_by_status(eng, channel, "draft")


def active_arc(eng: Engine, channel: str) -> dict | None:
    """Üretimde olan onaylı ark. Bölümleri BİTMİŞSE None döner (done'a çekilir)."""
    a = _arc_by_status(eng, channel, "active")
    if a and a["remaining"] <= 0:
        finish_arc(eng, a["id"])
        return None
    return a


def approve_arc(eng: Engine, arc_id: int) -> None:
    """Taslağı ÜRETİME AL. Aynı kanalda başka bir aktif ark varsa o done'a çekilir —
    iki aktif ark olursa hangisinin üretileceği belirsizleşir."""
    with eng.begin() as conn:
        row = conn.execute(select(series_arcs.c.channel)
                           .where(series_arcs.c.id == int(arc_id))).first()
        if row is None:
            return
        conn.execute(series_arcs.update()
                     .where(series_arcs.c.channel == row[0])
                     .where(series_arcs.c.status == "active")
                     .values(status="done"))
        conn.execute(series_arcs.update().where(series_arcs.c.id == int(arc_id))
                     .values(status="active", approved_at=_utcnow()))


def discard_arc(eng: Engine, arc_id: int) -> None:
    with eng.begin() as conn:
        conn.execute(series_arcs.update().where(series_arcs.c.id == int(arc_id))
                     .values(status="discarded"))


def finish_arc(eng: Engine, arc_id: int) -> None:
    with eng.begin() as conn:
        conn.execute(series_arcs.update().where(series_arcs.c.id == int(arc_id))
                     .values(status="done"))


def advance_arc(eng: Engine, arc_id: int) -> None:
    """Bir bölüm ÜRETİLDİ → sayacı ilerlet. Üretim BAŞARILIYSA çağrılır: başarısız
    bir koşu planı tüketirse o bölüm hiç üretilmemiş olur ve planda delik kalır."""
    with eng.begin() as conn:
        row = conn.execute(select(series_arcs.c.produced, series_arcs.c.plan_json)
                           .where(series_arcs.c.id == int(arc_id))).first()
        if row is None:
            return
        import json as _json
        try:
            toplam = len(_json.loads(row[1]))
        except Exception:
            toplam = 0
        yeni = int(row[0] or 0) + 1
        conn.execute(series_arcs.update().where(series_arcs.c.id == int(arc_id))
                     .values(produced=yeni,
                             status=("done" if toplam and yeni >= toplam else "active")))


def arc_history(eng: Engine, channel: str, limit: int = 10) -> list[dict]:
    with eng.connect() as conn:
        rows = conn.execute(
            select(series_arcs).where(series_arcs.c.channel == channel)
            .where(series_arcs.c.status.in_(("active", "done")))
            .order_by(series_arcs.c.id.desc()).limit(limit)).all()
    return [_arc_dict(r) for r in rows]


def bank_last_refresh(eng: Engine, channel: str):
    """En yeni created_at (haftalık tazeleme kararı) ya da None."""
    with eng.connect() as conn:
        row = conn.execute(
            select(topic_bank.c.created_at).where(topic_bank.c.channel == channel)
            .order_by(topic_bank.c.created_at.desc()).limit(1)).first()
    return row[0] if row else None


def bank_hook_patterns(eng: Engine, channel: str, limit: int = 5) -> list[str]:
    """Distinct, boş-olmayan hook_pattern'ler (başlık/hook few-shot için)."""
    with eng.connect() as conn:
        rows = conn.execute(
            select(topic_bank.c.hook_pattern).distinct()
            .where(topic_bank.c.channel == channel)
            .where(topic_bank.c.hook_pattern != "").limit(limit)).all()
    return [r[0] for r in rows]
