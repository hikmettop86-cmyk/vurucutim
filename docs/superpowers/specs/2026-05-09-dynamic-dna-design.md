# Dynamic DNA — Per-Video Style Selection (Design)

**Date:** 2026-05-09
**Status:** Design (pending implementation plan)
**Author:** Brainstormed with Claude Opus

## Summary

Add an opt-in per-channel feature where every published video gets its own
LLM-generated DNA (archetype + palette + fonts + tone + custom CSS + animation
style) tailored to the article's topic. Similar topics within a channel reuse
cached DNAs via embedding similarity, capping cost. Non-opted channels keep
their existing fixed-DNA behavior unchanged.

## Motivation

Today every video from a given channel renders with the same archetype and
palette baked in at channel-creation time. A successful list-format channel
in another niche (German psychology shorts: 12k–219k views, list of 5–7
items, dark+red palette) suggests that visual variety per topic could lift
engagement, but rebuilding DNA per-video by hand is intractable. Letting
Claude pick archetype + palette + animation per article — with a cache so
recurring topics are free — captures the variety with bounded cost.

The user explicitly chose:
- Full DNA regeneration per video (not just archetype switch)
- Opus quality with aggressive cache (not Sonnet/Haiku)
- Per-channel cache scope (not global pool)
- Embedding-based similarity (not keyword/category)
- OpenAI text-embedding-3-small as embedding provider
- 90-day cache TTL
- Animation style as a DNA field
- Opt-in via per-channel flag (not default-on)

## Non-Goals

- Cross-channel DNA pool sharing (rejected during brainstorming)
- Local embedding model (sentence-transformers — rejected for OpenAI API)
- Per-video DNA editing UI (cache is read-only from user perspective in v1)
- Animation style preview in UI (visual variation surfaces only in rendered
  video for v1; preview affordances are a v2 nice-to-have)
- Cost/budget UI guard rails — relies on cache hit rate being high enough in
  practice; can be added later if needed
- Migration of existing channels (they keep static DNA; opting in is per-
  channel)

## Architecture

### High-level flow

```
[RSS fetch / generator] → [extract + script_writer]
                              ↓
              ┌───────────────┴───────────────┐
              │  channel.dynamic_dna == True  │
              └───────────────┬───────────────┘
                              ↓ no → use channel.dna (static, current)
                              ↓ yes
              [embed(headline + body[:200])]   ← OpenAI text-embedding-3-small
                              ↓
              [DNA cache lookup (per-channel)]
                  ├─ cosine ≥ 0.85 ? → use cached DnaSpec + cached CSS file
                  └─ else → Opus generate_dna_for_video() → save to cache
                              ↓
              [build_css_override → templates/css/dynamic-<slug>-<rand>.css]
                              ↓
              [render_frames with archetype = effective_dna.archetype]
                              ↓
              [composer + auto_upload]
```

If any step in the dynamic path fails (OpenAI down, key missing, Opus
timeout, JSON parse error), the pipeline silently falls back to
`channel.dna` (or `channel.template + colors` if channel has no DNA). The
pipeline never aborts due to dynamic-DNA failure.

### New modules

| Module | Purpose |
|---|---|
| `src/short_bot/embeddings.py` | OpenAI embedding client wrapper. `embed_text(text, api_key) -> list[float]`. Caller resolves key via `os.environ.get("OPENAI_API_KEY") or secrets.get("openai_api_key")` (mirror of `resolve_pexels_api_key` pattern). Raises `EmbeddingError` if key missing or on API errors after retry. 1536-dim float32 output. |
| `src/short_bot/dna_cache.py` | SQLite-backed cache. `lookup_cached_dna(channel_slug, embedding, threshold) -> CacheHit \| None`, `save_cached_dna(...)`, `cleanup_expired_dna_cache(days)`, `increment_hit_count(id)`. |

### New function in existing module

`src/short_bot/dna.py`:
- `generate_dna_for_video(channel: ChannelConfig, headline: str, body: str, claude_path: str, model: str = "opus") -> DnaSpec`
- Wraps `run_json` with a per-article prompt (see "Prompt design" below).
- Same `DnaSpec` return type — no new schema, just article-aware inputs.

### Modified modules

| Module | Change |
|---|---|
| `config.py` | `ChannelConfig.dynamic_dna: bool = False`; YAML round-trip writes only when True |
| `dna.py` | `DnaSpec.animation_style: Literal[...] = "none"` field; `build_css_override` emits `_animations.css` import + stage class hint |
| `pipeline.py` | New `_resolve_dna_for_video()` helper; called in `_run_rss` and `_run_generator` after `script_writer`, before `render_frames`; returns `(dna, css_path)` or `None` for fallback |
| `renderer.py` | `build_html` accepts `animation_style` Jinja var; `dna_css` parameter already exists, now points to per-video CSS |
| `db.py` (or new `migrations/`) | `dna_cache` table schema |
| `secrets_io.py` | New `update_openai_api_key(secrets_path, key)` helper that writes `openai_api_key` to top-level of `data/secrets.yaml` (mirror of `update_channel_proxy` atomic-write pattern) |
| 15 archetype templates | Stage root gets `class="stage dna-anim-{{ animation_style }}"`; `gundem.html.j2` list items get `style="--i: {{ loop.index0 }}"` |
| `web/routes/channel_edit.py` | Form posts `dynamic_dna` checkbox |
| `web/templates/channels/edit.html.j2` | New checkbox UI + helper text |

## Data Model

### `ChannelConfig` extension

```python
@dataclass(frozen=True)
class ChannelConfig:
    ...
    dynamic_dna: bool = False  # NEW
    dna: DnaSpec | None = None  # existing — used when dynamic_dna=False, also as
                                # fallback if per-video generation fails
```

YAML serialization:
```yaml
dynamic_dna: true   # written only when True (keeps existing YAMLs clean)
dna: { ... }        # always preserved; in dynamic mode used as fallback +
                    # persona ipucu source for the per-video prompt
```

### `DnaSpec` extension

```python
class DnaSpec(BaseModel):
    ...
    animation_style: Literal[
        "none", "fade-up", "slide-in", "stagger-reveal", "typewriter", "zoom-in"
    ] = "none"
```

`"none"` is the default → existing channels with stored DnaSpec round-trip
without behavior change. The DNA generation prompt for new channels (legacy
`generate_dna()` path) keeps emitting `"none"` unless explicitly extended.

### `dna_cache` SQLite table

```sql
CREATE TABLE dna_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_slug TEXT NOT NULL,
    topic_text TEXT NOT NULL,         -- embedded source: headline + "\n" + body[:200]
    embedding BLOB NOT NULL,          -- 1536 float32 packed (~6KB) — see encoding note
    dna_json TEXT NOT NULL,           -- DnaSpec.model_dump_json()
    css_filename TEXT NOT NULL,       -- "dynamic-<slug>-<rand>.css" relative to templates/css/
    archetype TEXT NOT NULL,          -- denormalized from dna_json for filtering
    created_at TIMESTAMP NOT NULL,
    last_used_at TIMESTAMP,
    hit_count INTEGER DEFAULT 0
);
CREATE INDEX idx_dna_cache_channel_created ON dna_cache(channel_slug, created_at);
```

**Embedding storage:** `numpy.array(emb, dtype=np.float32).tobytes()` →
6144-byte BLOB. Read back with `np.frombuffer(blob, dtype=np.float32)`.
This avoids JSON serialization overhead for the hot lookup path.

**Lookup query:** SELECT all rows for `channel_slug`, compute cosine in
Python (per-channel row count expected ≤ 1000 over 90 days at typical
cadence — ~10 videos/day × 90 days = 900 rows; cosine on 1536-dim float32
×1000 takes <50ms). Return row with max cosine if ≥ 0.85.

**Note on scaling:** if a channel produces > ~10k cache rows the linear
scan grows past 500ms; revisit with a vector index (sqlite-vss, hnsw, or
prune by recent N) when that happens. Not a v1 concern.

### Per-video CSS files

Stored as `templates/css/dynamic-<slug>-<6-char-hex>.css`. Filename is
recorded in `dna_cache.css_filename`. On TTL cleanup, the file is deleted
along with the row. Filename uses `secrets.token_hex(3)` for collision
avoidance; channel slug prefix keeps directory listings grep-able and
makes manual cleanup of a single channel's cache trivial (`rm
templates/css/dynamic-galatasaray-*.css`).

## Pipeline Integration

### `_resolve_dna_for_video()` (new helper in `pipeline.py`)

```python
def _resolve_dna_for_video(
    *,
    channel: ChannelConfig,
    headline: str,
    body: str,
    log: logging.Logger,
    claude_path: str,
    secrets_path: Path,
    templates_dir: Path,
    eng,                              # SQLAlchemy engine for dna_cache
) -> tuple[DnaSpec, Path] | None:
    """For dynamic_dna channels: lookup cache or generate per-video DNA.
    Returns (dna, css_path) or None on failure (caller falls back to channel.dna)."""
    if not channel.dynamic_dna:
        return None

    topic_text = f"{headline}\n{body[:200]}"

    # 1. Resolve key + embed (with retry; on hard failure return None → fallback)
    api_key = os.environ.get("OPENAI_API_KEY") or _load_secrets(secrets_path).get("openai_api_key", "")
    if not api_key:
        log.warning("  [dna] no openai_api_key configured → fallback to static")
        return None
    try:
        emb = embed_text(topic_text, api_key=api_key)
    except EmbeddingError as e:
        log.warning(f"  [dna] embedding failed: {e} → fallback to static")
        return None

    # 2. Cache lookup
    hit = lookup_cached_dna(eng, channel.slug, emb, threshold=0.85)
    if hit is not None:
        log.info(f"  [dna] cache HIT id={hit.id} archetype={hit.archetype} "
                 f"(cos={hit.score:.3f})")
        increment_hit_count(eng, hit.id)
        return hit.dna, templates_dir / "css" / hit.css_filename

    # 3. Cache miss → generate
    log.info(f"  [dna] cache MISS → generating (Opus)…")
    try:
        dna = generate_dna_for_video(
            channel=channel, headline=headline, body=body,
            claude_path=claude_path,
        )
    except Exception as e:
        log.warning(f"  [dna] generation failed: {e} → fallback to static")
        return None

    # 4. Save (DNA + CSS file + cache row)
    css_text = build_css_override(dna)
    css_filename = f"dynamic-{channel.slug}-{secrets.token_hex(3)}.css"
    (templates_dir / "css" / css_filename).write_text(css_text, encoding="utf-8")
    save_cached_dna(eng, channel.slug, topic_text, emb, dna, css_filename)
    log.info(f"  [dna] saved: archetype={dna.archetype} css={css_filename}")
    return dna, templates_dir / "css" / css_filename
```

### Call site (in `_run_rss` and `_run_generator`)

After `write_script(...)` returns, **before** `render_frames`:

```python
script = write_script(...)

# Resolve effective DNA + CSS path (handles static, dynamic, and fallback)
effective_dna = channel.dna
effective_css_path = templates_dir / "css" / f"{channel.slug}.css"

resolved = _resolve_dna_for_video(
    channel=channel, headline=script.headline_top + " " + script.headline_bot,
    body=script.body_paragraph,
    log=log, claude_path=settings.claude_cli_path,
    secrets_path=secrets_path, templates_dir=templates_dir, eng=eng,
)
if resolved is not None:
    effective_dna, effective_css_path = resolved

# Template path now derived from effective archetype
archetype = effective_dna.archetype if effective_dna else channel.template
template_path = templates_dir / f"{archetype}.html.j2"
```

### Renderer changes

`build_html()` already accepts `dna_css: str` — pipeline passes
`effective_css_path.read_text(encoding="utf-8")` to it.

New Jinja parameter `animation_style=effective_dna.animation_style if
effective_dna else "none"`. Each archetype template's stage root gets:
```jinja
<div class="stage dna-anim-{{ animation_style }}">
```

### Overflow check

`check_overflow(html, archetype=archetype)` — pass the **effective
archetype** (not `channel.template`), so the per-video archetype's
`ARCHETYPE_OVERFLOW_FIELDS` selectors are used. Without this fix, a
dynamic-DNA video that picked `tabloid` would be checked against the
channel's static `newscast` rules and either pass invalid layouts or
trigger false retries.

### Image picker

`pick_query_for_archetype(effective_archetype)` — DDG image search query
template comes from the effective archetype, so spor-haber's
`"{header_top} {category} football match"` query template is used when
the per-video DNA picks spor-haber, regardless of the channel's static
template.

### Failure modes (always non-fatal)

| Failure | Behavior | Log |
|---|---|---|
| `openai_api_key` missing | Skip embed → `EmbeddingError` → fallback | `[dna] embedding failed: missing openai_api_key → fallback to static` |
| OpenAI 429/5xx after retry | `EmbeddingError` → fallback | `[dna] embedding failed: <api error> → fallback to static` |
| Opus timeout / non-JSON | Exception caught → fallback | `[dna] generation failed: <error> → fallback to static` |
| Pydantic validation fail | Exception caught → fallback | `[dna] generation failed: validation → fallback to static` |
| CSS file write fail | Exception caught → fallback | `[dna] save failed: <io error> → fallback to static` |

In every fallback case the pipeline continues with the channel's static
DNA (or template+colors) and produces a video. Dynamic mode is best-effort
augmentation, never a hard requirement.

## Animation Feature

### Shared animation CSS (`templates/css/_animations.css`)

```css
@keyframes anim-fade-up {
  from { opacity: 0; transform: translateY(40px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes anim-slide-in {
  from { opacity: 0; transform: translateX(60px); }
  to   { opacity: 1; transform: translateX(0); }
}
@keyframes anim-zoom-in {
  from { opacity: 0; transform: scale(0.85); }
  to   { opacity: 1; transform: scale(1); }
}
@keyframes anim-typewriter {
  from { clip-path: inset(0 100% 0 0); }
  to   { clip-path: inset(0 0 0 0); }
}

/* Single-element animations — apply to body-text & first headline line */
.dna-anim-fade-up    .body-text,
.dna-anim-fade-up    .header .top  { animation: anim-fade-up 0.8s ease-out forwards; }
.dna-anim-slide-in   .body-text,
.dna-anim-slide-in   .header .top  { animation: anim-slide-in 0.7s ease-out forwards; }
.dna-anim-zoom-in    .body-text,
.dna-anim-zoom-in    .header .top  { animation: anim-zoom-in 0.7s ease-out forwards; }
.dna-anim-typewriter .body-text    { display: inline-block;
                                      animation: anim-typewriter 1.2s steps(40) forwards; }

/* List-mode stagger (gundem) — uses --i index var */
.dna-anim-stagger-reveal .list-item {
  opacity: 0;
  animation: anim-fade-up 0.6s ease-out forwards;
  animation-delay: calc(var(--i, 0) * var(--stagger-delay, 1s));
}
```

This file is imported once in the base CSS chain. `dna-anim-none` matches
nothing → no animations → existing channels with `animation_style="none"`
render exactly as today.

### Template wiring

Each of the 15 archetypes gets a one-line change to its stage root:
```jinja
<div class="stage dna-anim-{{ animation_style|default('none') }}">
```

`gundem.html.j2` list items additionally get an index var:
```jinja
{% for item in items %}
  <div class="list-item" style="--i: {{ loop.index0 }};">…</div>
{% endfor %}
```

### Determinism with Playwright frame stepping

The existing renderer (`renderer.py:128`):
```python
page.add_init_script("document.getAnimations().forEach(a => a.pause());")
```
already pauses all CSS animations after `set_content`. The frame loop
steps animations via `a.currentTime = t_ms`. New `@keyframes` introduced
here use the same mechanism — no renderer change needed beyond passing
`animation_style` to Jinja.

## UI Changes

### Channel edit page (`web/templates/channels/edit.html.j2`)

```html
<label class="block">
  <input type="checkbox" name="dynamic_dna" value="1"
         {% if c.dynamic_dna %}checked{% endif %}>
  <span class="text-sm font-semibold">Dinamik DNA (her video için stil yenilensin)</span>
  <span class="text-[11px] text-claude-subtle block mt-1">
    Açıkken her video için Claude (Opus) konuya göre archetype + palette + animation seçer.
    Benzer konular cache'ten gelir (90 gün saklanır). OpenAI API key gerekir.
  </span>
</label>
```

`channel_edit.py` route:
```python
dynamic_dna=_form_get_bool("dynamic_dna", cfg.dynamic_dna)
```

### Settings/secrets UI

Existing secrets edit screen gains an `OpenAI API Key` field (mirror of
existing Pexels key pattern). Stored in `data/secrets.yaml` under
top-level key `openai_api_key`. `OPENAI_API_KEY` env var takes precedence
when set (matches Pexels resolution order).

### Dashboard rozeti (low-cost addition)

Channel cards show a small badge when `dynamic_dna=True`:
```
🧬 dyn (12 cache, 89% hit)
```
Computed from `SELECT COUNT(*), SUM(hit_count) FROM dna_cache WHERE
channel_slug = ?`. Hit rate = `hit_count_sum / (hit_count_sum + row_count)`.

### Cache management UI (deferred to v2)

Per-channel "DNA cache temizle" button + last-10-cache-entries listing.
Not required for v1.

## Tests

### New test files

| File | Coverage |
|---|---|
| `tests/test_embeddings.py` | OpenAI client wrapper — mocked HTTP via `responses` lib, key-missing raises EmbeddingError, retry on 5xx (3 attempts), 1536-dim output validation |
| `tests/test_dna_cache.py` | Save → lookup roundtrip; threshold below/above (cos 0.84 vs 0.86); TTL cleanup deletes both row and CSS file; per-channel isolation (channel A's row not visible to channel B); `increment_hit_count` race-safe |
| `tests/test_dna_animation.py` | `DnaSpec.animation_style` Literal validation (invalid value raises); `build_css_override` output contains expected stage class wiring; `_animations.css` keyframes count |
| `tests/test_pipeline_dynamic_dna.py` | E2E with `dynamic_dna=True`: cache miss path creates DB row + CSS file, cache hit path skips both LLM calls, embedding failure falls back to static, Opus failure falls back to static, overflow check uses effective archetype not channel.template |

### Existing tests — minor updates

| File | Change |
|---|---|
| `test_config.py` | `dynamic_dna` default False round-trip; explicit True round-trip |
| `test_dna.py` | `animation_style="none"` default; round-trip with all 6 enum values |
| `test_pipeline.py` | Fixtures gain `dynamic_dna=False` (explicit, not relying on default) |
| `test_pipeline_age_filter.py` | No change |

### Snapshot tests

The 14 snapshot baselines (one per archetype, except meme has its own
specific test) are recorded with `animation_style="none"` explicitly set,
so they don't drift when this feature lands. Frame-0 of an animated
template would differ from a static one (opacity/transform offset);
forcing `"none"` keeps existing baselines stable.

## Implementation Phases

| Phase | Scope | Acceptance |
|---|---|---|
| **F1: Cache infra** | `embeddings.py`, `dna_cache.py`, secrets `openai_api_key`, migration, tests | All new tests pass; existing pipeline behavior unchanged; no UI yet |
| **F2: Per-video DNA + opt-in** | `generate_dna_for_video()` (without animation_style guidance — that arrives in F3), `_resolve_dna_for_video()`, pipeline integration, `ChannelConfig.dynamic_dna`, channel-edit UI checkbox, OpenAI key in secrets UI | Dynamic-DNA channel produces a video using a per-video DNA; cache populates; fallback paths exercised; `animation_style="none"` for all generated DNAs in this phase |
| **F3: Animation** | `DnaSpec.animation_style` field added to schema, `_animations.css`, stage-class wiring on 15 templates, gundem list `--i`, **prompt extended** in `generate_dna_for_video` to instruct Opus to choose `animation_style` per article tempo | A dynamic channel with `animation_style != "none"` produces visibly animated frames; snapshot tests still pass (defaults to `"none"`) |
| **F4: Observability + maintenance** | Dashboard cache hit/miss rozeti, daily TTL cleanup cron triggers `cleanup_expired_dna_cache(days=90)` (runs once per day, deletes expired rows + their CSS files) | Rozeti shows correct count; cron logs show daily cleanup; expired CSS files removed; total `templates/css/dynamic-*.css` count stays bounded over time |

F1+F2 ships the feature minimally. F3 ships the animation. F4 ships
maintenance. Each phase is independently testable and shippable to
production.

## Prompt Design (`generate_dna_for_video`)

The per-video prompt extends the existing `build_dna_prompt()` with
article context. Key differences from the channel-level prompt:

```
KANAL PERSONA (kanalın genel kimliği):
- {channel.dna.persona_summary if channel.dna else channel.name + " (no persona set)"}
- Mevcut tone: {channel.dna.tone.voice if channel.dna else "default"}

BU VİDEO İÇİN MAKALE:
- Başlık: {headline}
- Body: {body[:500]}

GÖREV: Bu KAYDA özgü bir DNA üret. Kanalın temel kimliğine sadık kal
(persona_summary'deki ton/stil), ama:
- archetype seçimini bu makaleye göre yap (transfer haberi → spor-haber,
  ekonomik tartışma → ekonomi, magazin → tabloid, vb.)
- palette'i makalenin duygusuna göre ayarla (kriz haberi → koyu/kırmızı,
  başarı haberi → parlak/altın)
- animation_style'ı makalenin tempo'suna göre seç:
  * none: sakin, kurumsal haber
  * fade-up: standart info shot
  * slide-in: hızlı transferler, son dakika
  * stagger-reveal: liste/sayı haberi (top-5, fixtures)
  * typewriter: alıntı, açıklama
  * zoom-in: heyecan/skor/zafer
- custom_css: makaleye uygun ek dekorasyon (varsa kanalın signature
  motifini koru, ama bu video'ya özgü vurgu ekle)

[+ existing DNA prompt rules unchanged]
```

The model receives a stable channel-persona anchor + per-article
specifics, so cached entries cluster by topic but stay within the channel
brand envelope.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Cost runaway if cache hit rate is low | 90-day TTL means high temporal locality (sports transfers cluster in window); embedding threshold tunable; Opus call has 180s timeout; fallback always available |
| OpenAI API outage | EmbeddingError fallback to static DNA; pipeline never blocked |
| Per-video CSS files accumulate | F4 cleanup cron removes expired rows + files; manual purge button planned for v2 |
| DNA quality drift between videos | Channel-persona anchor in prompt + custom_css preserves brand; embedding cache means topic-recurring content reuses good results |
| Embedding cost | text-embedding-3-small at $0.02/1M tokens × ~50 tokens/topic = ~$0.000001/lookup; negligible |
| Snapshot tests breaking | Default `animation_style="none"` keeps baselines stable; explicit set in tests |
| Brand inconsistency | Channel.dna persists as "anchor" — used in per-video prompt as channel persona; LLM instructed to stay within envelope |

## Open Questions

None at design time. Implementation may surface:
- Optimal embedding `topic_text` length (currently `headline + body[:200]`)
- Whether to embed `script.headline_top + " " + script.headline_bot` vs the
  raw RSS headline (script-rewritten headlines might cluster differently)
- Cosine threshold tuning (0.85 default; might need per-channel tuning if a
  channel has narrow topic range)

These are tuning decisions, not architectural — adjust empirically after
shipping F1+F2.

## Definition of Done

- F1: `embed_text()` returns a 1536-dim vector when key configured;
  `dna_cache` table exists; `lookup_cached_dna()` finds rows above
  threshold; tests green.
- F2: A channel with `dynamic_dna: true` produces a video where the
  rendered HTML uses a different archetype than `channel.template`; cache
  row created; second video on similar topic reuses cached DNA without an
  Opus call; OpenAI key removed → pipeline still produces video using
  static DNA.
- F3: A channel with `dynamic_dna: true` and Opus picking
  `animation_style="stagger-reveal"` for a list video produces a video
  where list items visibly appear at staggered intervals (verifiable in
  output mp4).
- F4: Dashboard shows cache stats; expired entries (created_at < now - 90d)
  are removed by cron along with their CSS files; cron runs daily and is
  idempotent (re-running same day produces no further deletions).
