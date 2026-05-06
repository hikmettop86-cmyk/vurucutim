# Activity Timeline — Design Spec

**Date:** 2026-05-07
**Status:** Draft, awaiting approval

## Problem

The current panel scatters operational state across multiple pages: `/` (dashboard summary cards), `/rss` (last-24h candidates), `/shorts` (produced videos), `/logs` (raw run logs), `/channels` (per-channel state). To answer "what happened this morning, and is anything broken?" the operator must visit several pages and stitch the picture together. There's no single chronological feed of system activity, and live state (a running pipeline) is invisible until either the dashboard's "today" counter ticks up or the run log is opened by hand.

## Solution

A new `/activity` page with three vertically stacked zones, in this order:

1. **24-hour summary cards** — hap özet metrik karşılaması.
2. **Live runs** — currently running pipelines with elapsed-time counter.
3. **Timeline feed** — chronological event stream, filterable, with htmx auto-refresh and pagination.

```
┌──────────────────────────────────────────────────────────┐
│  Akış (24s özet)                                          │
│  ┌─ Run 12  ✓ 8  ✗ 1  ─┐  ┌─ Short 9 ─┐  ┌─ YT 7 ─┐   │
│  └─────────────────────┘  └───────────┘  └─────────┘   │
│  ┌─ Hata 1 (kırmızı parlar varsa) ─┐                    │
│  └────────────────────────────────────┘                  │
│                                                            │
│  Şu an çalışan                                            │
│  🟢 son-dakika  başladı 14:23 · 01:32 geçti              │
│  🟢 motivasyon  başladı 14:24 · 00:22 geçti              │
│                                                            │
│  Akış                                                      │
│  Filtre: [kanal v] [tip v] [zaman v]                     │
│  14:21  ▶ YT     son-dakika   "Trump Strait..." (id: …)  │
│  14:18  ✓ Short  son-dakika   "Trump Strait..." (6s)     │
│  14:17  🔍 Run   son-dakika   47 scored / 1 picked       │
│  14:15  ⚠ Run   breaking-news failed · trafilatura empty │
│  ...                                                       │
│  [daha eski yükle]                                         │
└──────────────────────────────────────────────────────────┘
```

## Components

### 1. Route (`src/short_bot/web/routes/activity.py`)

New Flask blueprint with two endpoints:

```python
@bp.route("/activity")
def view():
    """Full page. Renders summary cards + live runs + first feed page."""

@bp.route("/activity/feed")
def feed_partial():
    """htmx partial: re-renders the timeline feed when filters change or
    on auto-refresh. Reads filter query params: channel, type, since, status,
    cursor (for pagination)."""
```

Register in `src/short_bot/web/routes/__init__.py` alongside other blueprints.

### 2. Event builder (`src/short_bot/web/activity.py`)

A pure module that turns DB tables into a unified event stream.

```python
@dataclass(frozen=True)
class ActivityEvent:
    timestamp: datetime
    type: Literal["run", "short", "youtube", "error"]
    channel: str
    title: str           # short human-readable
    detail: str          # secondary info ("47 scored / 1 picked", file name, etc.)
    status: Literal["success", "failed", "no_candidates", "running"] | None
    link: str            # internal URL (e.g. /shorts/<id>, /logs?channel=...)
    icon: str            # emoji or short string


def build_activity_events(
    eng,
    *,
    since: datetime,
    channel: str | None = None,
    types: tuple[str, ...] = ("run", "short", "youtube", "error"),
    status: str | None = None,
    limit: int = 200,
    cursor: datetime | None = None,
) -> list[ActivityEvent]:
    """UNION events from runs, shorts, youtube_uploads. Filter, sort by
    timestamp DESC, paginate via cursor (timestamp-based)."""
```

Event-source mapping:

| Source row                                           | Event type | Status                 | Title example                   | Detail                                      |
|------------------------------------------------------|------------|------------------------|---------------------------------|---------------------------------------------|
| `runs` (status in success/failed/no_candidates)      | `run`      | passes through         | "Run · son-dakika"              | "47 scored / 1 picked" (joined from rss_items count, status='selected'/'below_threshold') OR error message snippet for failed |
| `shorts` (any deleted_at IS NULL)                    | `short`    | "success"              | "Video · son-dakika"            | s.title (truncated), `{duration_s}s render {render_ms}ms` |
| `youtube_uploads` (status=success)                   | `youtube`  | "success"              | "YouTube · son-dakika"          | s.title + video_id                          |
| `youtube_uploads` (status=failed)                    | `error`    | "failed"               | "YouTube hata · son-dakika"     | error[:80]                                  |
| `runs` with status=failed AND error not null          | `error`    | "failed"               | "Run hata · son-dakika"         | error[:80] · log link                        |

Note the `runs` table maps to TWO event types:
- success/no_candidates → `run` event (info)
- failed → `error` event (alarm)

Pagination uses cursor = oldest timestamp of last page (not offset, to stay stable as new events arrive at the head).

### 3. Live runs

Live runs are not events; they're a separate query:

```python
def list_running_runs(eng) -> list[Run]:
    """Runs with ended_at IS NULL ordered by started_at DESC, age limited to
    cleanup_zombie_runs threshold (60min) so abandoned never-finished runs
    don't pile up."""
```

Front-end shows each with elapsed time. Alpine.js ticks a counter every 1s without re-fetching server.

### 4. Summary metrics

A small Pydantic-style dataclass:

```python
@dataclass(frozen=True)
class ActivitySummary:
    runs_24h: int
    runs_success_24h: int
    runs_failed_24h: int
    shorts_24h: int
    youtube_success_24h: int
    errors_24h: int   # = runs_failed_24h + youtube_failed_24h
```

Each card on the top row links to a pre-filtered `/activity` URL that scopes the feed. The errors card additionally pulses (Tailwind `animate-pulse`) when `errors_24h > 0`.

### 5. Templates

- `src/short_bot/web/templates/activity.html.j2` — full page, three zones.
- `src/short_bot/web/templates/_partials/activity_feed.html.j2` — feed-only partial (htmx target).
- `src/short_bot/web/templates/_partials/activity_live_runs.html.j2` — live-runs partial (auto-refresh independently every 5s, since it changes faster than the feed).

Tailwind classes match the rest of the panel. Each event row is a flexbox: timestamp (mono, fixed width) + icon + channel chip + title + detail + status badge + optional link affordance. On hover the row deepens — clicking the row navigates to the natural target page (run → /logs?channel=…&since=run_timestamp; short → /shorts/<id>; youtube → opens youtube URL).

### 6. Filtering

Query parameters (all optional):

| Param      | Values                                                    | Default          |
|------------|-----------------------------------------------------------|------------------|
| `channel`  | any channel slug, or empty for all                        | empty            |
| `type`     | `run`, `short`, `youtube`, `error`, or empty for all      | empty            |
| `status`   | `success`, `failed`, `no_candidates`, or empty            | empty            |
| `since`    | `1h`, `24h`, `7d`, `30d`                                 | `24h`            |
| `cursor`   | ISO timestamp (used for "daha eski yükle")                | absent           |

`status` is mostly relevant when `type` is `run` (success vs failed). Combinations work like AND.

The htmx-driven auto-refresh on the feed uses `hx-trigger="load, every 10s"` and `hx-include` to preserve the user's filter selection.

### 7. Navigation

Add "Akış" tab to `base.html.j2` nav between "Dashboard" and "Shorts". Placement is intentional: it's the new operator front door.

## Failure modes

| Condition                              | Behavior                                                                              |
|----------------------------------------|---------------------------------------------------------------------------------------|
| DB unreachable                          | Page renders summary card slot with "—" and feed shows "Veri okunamadı" placeholder. |
| No events at all (fresh install)        | Feed shows "Henüz aktivite yok. İlk run'ı başlatınca burada görünecek."              |
| Live runs section empty                  | Shows "Şu an çalışan run yok"                                                          |
| Filter returns 0 results                 | Shows "Bu filtre için sonuç yok. Filtreyi temizle"                                    |
| `runs.started_at` tz-naive vs tz-aware  | Already-handled `Run.duration_seconds` pattern; reuse for elapsed-time display.        |

## Test plan

- `tests/test_activity_events.py` — pure unit tests on `build_activity_events`: each source produces correct ActivityEvent shape; filters narrow correctly; pagination cursor works; errors and success runs are mapped to the right type.
- `tests/test_web_activity.py` — Flask client tests:
  - GET `/activity` returns 200 with summary cards
  - feed partial responds to filters
  - empty-DB state rendering
  - live runs section reflects in-flight `runs` rows
  - errors card pulses when failed runs > 0 (assert class on element)
- Existing dashboard/shorts tests must remain green (no regressions).

## Out of scope

- Push notifications / WebSockets — feed uses htmx polling; that's enough for a single-operator panel.
- Per-channel activity drill-down beyond filter — channel detail page is `/channels/<slug>/edit` and stays as-is for now.
- Long-term retention dashboards or charts — that's a separate analytics feature.
- Editing/deleting events from the feed — feed is read-only; mutation lives on the existing per-resource pages.
- Real-time streaming of running pipeline progress (which step it's on) — would need a /run/<id>/progress endpoint backed by the log file. Future enhancement.

## Migration

- No DB migration needed. All event data already lives in `runs`, `shorts`, `youtube_uploads`, `rss_items`.
- `processed_items` is consulted only for the run summary count of "scored items" (joined with rss_items).
- Existing pages remain. Dashboard's hap özet section stays — `/activity` is additive, not a replacement. Removing dashboard's stat cards is a future cleanup if `/activity` proves to subsume them.

## Defaults

- Auto-refresh feed: every 10s.
- Auto-refresh live runs: every 5s.
- Default time window: last 24h.
- Page size: 200 events per fetch.
- Errors-card pulse: `animate-pulse` only when count > 0.
