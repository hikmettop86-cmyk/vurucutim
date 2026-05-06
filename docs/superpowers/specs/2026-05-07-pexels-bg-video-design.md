# Pexels Animated Background Video — Design Spec

**Date:** 2026-05-07
**Status:** Draft, awaiting approval

## Problem

Some phones crop or letterbox the 9:16 short, hiding part of the archetype frame (header, body, persistent chips). Standard solution: scale the archetype frame down so a safe-area margin exists around it, and fill the margin with a visually appealing background that doesn't compete with the foreground.

## Solution

Render the existing archetype frame at reduced scale (0.88x or 0.80x) centered on a 1080×1920 canvas. Fill the margin with a Pexels stock video clip — searched by archetype-pool query, downloaded once, cached, and post-processed (Gaussian blur + dim) so it reads as ambient texture, not as content.

Per-channel opt-in. Channels that don't enable it keep the existing fullscreen layout.

```
┌─────────────────────────────┐ ← 1080×1920 canvas
│  Pexels video (blurred,     │
│  dimmed, looped, scaled to  │
│  cover, no audio)           │
│  ┌───────────────────────┐  │
│  │                       │  │ ← archetype frame
│  │   Archetype render    │  │   (PNG seq, scaled
│  │   (scale 0.88 / 0.80) │  │    0.88x or 0.80x,
│  │                       │  │    centered)
│  └───────────────────────┘  │
│  Pexels video (continues)   │
└─────────────────────────────┘
```

## Components

### 1. `src/short_bot/pexels.py` (new)

Thin client over Pexels Videos API.

```python
class PexelsCandidate(BaseModel):
    id: int
    url: str         # mp4 download URL (medium quality, ~hd 1080p clip)
    duration_s: int

def search_videos(
    query: str,
    api_key: str,
    *,
    max_results: int = 5,
    orientation: Literal["portrait", "landscape", "square"] = "portrait",
    timeout_s: int = 15,
) -> list[PexelsCandidate]:
    """GET https://api.pexels.com/videos/search?query=...&orientation=portrait&per_page=N
    Auth header: Authorization: <api_key>
    Returns up to max_results candidates. Empty list on HTTP error / rate limit / no results.
    """

def download_video(url: str, cache_dir: Path, *, timeout_s: int = 60) -> Path | None:
    """Download to cache_dir/<sha1(url)[:16]>.mp4. Returns cached path on success,
    None on HTTP error or empty response. Idempotent (returns cached file if present)."""

ARCHETYPE_BG_QUERIES: dict[str, list[str]] = {
    "newscast":  ["newsroom blur", "studio lights motion", "news ticker abstract"],
    "tabloid":   ["paparazzi flash", "neon city night", "magazine pages turning"],
    "magazine":  ["soft fabric texture", "ink water swirl", "warm bokeh"],
    "kinetic":   ["geometric motion", "abstract neon lines", "particle wave"],
    "dark-tech": ["circuit board glow", "matrix code rain", "server room cyan"],
    "stadium":   ["stadium lights night", "crowd cheering blur", "grass pitch zoom"],
    "meme":      ["confetti pop", "colorful gradient swirl", "cartoon background"],
}

def pick_query_for_archetype(archetype: str) -> str:
    """Random pick from ARCHETYPE_BG_QUERIES[archetype]; falls back to a generic
    'abstract motion' if archetype is unknown."""
```

**Rate limiting:** Pexels free tier = 200 req/hour, 20k/month. We rely on:
- Cache (most runs reuse a cached download).
- Random query from a small pool (3 entries × 7 archetypes = 21 distinct queries).
- Failure mode = silent fallback (no Pexels bg, original layout).

### 2. Channel config schema

`ChannelConfig` gains an optional nested model:

```python
class BgVideoConfig(BaseModel):
    enabled: bool = False
    scale: Literal[0.88, 0.80] = 0.88   # only two options exposed in UI
    blur_px: int = Field(ge=0, le=80, default=30)
    dim: float = Field(ge=0.0, le=1.0, default=0.4)  # 0=black, 1=untouched
```

YAML form (existing channel files unaffected — `bg_video` absent ⇒ disabled):

```yaml
bg_video:
  enabled: true
  scale: 0.88
  blur_px: 30
  dim: 0.4
```

### 3. Settings (API key) — secret handling

`config/settings.yaml` is git-tracked, so the API key must NOT live there. Resolution order at runtime (first non-empty wins):

1. Environment variable `PEXELS_API_KEY`.
2. New file `data/secrets.yaml` — git-ignored, written by the web Settings page.

`data/secrets.yaml` shape (created on first save by the UI):

```yaml
pexels_api_key: "..."
```

Loader change in `short_bot/config.py`:

```python
def load_secrets(secrets_path: Path) -> dict:
    if not secrets_path.exists():
        return {}
    return yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}

def resolve_pexels_api_key(settings: Settings, secrets: dict) -> str:
    return os.environ.get("PEXELS_API_KEY") or secrets.get("pexels_api_key", "") or ""
```

`Settings` Pydantic model is **not** modified — the key never enters that object's repr/serialization (avoids accidental log leak).

`.gitignore` additions:

```
data/secrets.yaml
```

Web Settings page (`/settings`) gains a password-style input. Saving:
- Writes only `pexels_api_key` to `data/secrets.yaml` (creates the file if absent).
- Other settings fields continue to flow into `config/settings.yaml` as today.
- Page reads from `data/secrets.yaml` at render time; if the key is set it shows masked (`••••••••<last 4 chars>`) with a "değiştir" toggle that reveals an empty input. Saving an empty value clears the key.

### 4. Pipeline integration (`pipeline.py`)

Asset stage — after current `bg = pick_image_for_script(...)` block, before `pick_music`:

```python
bg_video_path: Path | None = None
if channel.bg_video and channel.bg_video.enabled:
    api_key = resolve_pexels_api_key(settings, load_secrets(secrets_path))
    if api_key:
        from short_bot.pexels import search_videos, download_video, pick_query_for_archetype
        query = pick_query_for_archetype(channel.dna.archetype if channel.dna else channel.template)
        candidates = search_videos(query, api_key, max_results=3)
        for cand in candidates:
            bg_video_path = download_video(cand.url, cache_dir / "pexels_videos")
            if bg_video_path:
                log.info(f"  pexels bg accepted: {bg_video_path.name} (q={query!r})")
                break
        if bg_video_path is None:
            log.warning("  pexels bg unavailable → falling back to fullscreen layout")
    else:
        log.warning("  bg_video.enabled but no PEXELS_API_KEY configured → skipping")
```

`bg_video_path`, `bg_video_config` passed to `RenderJob`.

### 5. Composer (`composer.py`) — the substantive change

Current pipeline: PNG sequence + music → mp4 (single FFmpeg invocation).

New pipeline when `bg_video_path is not None`:

```
ffmpeg
  -stream_loop -1 -i pexels_bg.mp4   # input 0: bg, looped
  -framerate 30 -i frames/%05d.png   # input 1: foreground PNG seq
  -i music.mp3                       # input 2: audio
  -filter_complex "
    [0:v] gblur=sigma={blur_px} ,
          scale=1080:1920:force_original_aspect_ratio=increase,
          crop=1080:1920,
          eq=brightness=-{1-dim}:saturation={dim} ,
          trim=duration={duration_s}, setpts=PTS-STARTPTS
          [bg];
    [1:v] scale=iw*{scale}:ih*{scale},
          format=rgba
          [fg];
    [bg][fg] overlay=(W-w)/2:(H-h)/2:format=auto
          [outv]
  "
  -map [outv] -map 2:a
  -c:v libx264 -pix_fmt yuv420p -shortest
  output.mp4
```

When `bg_video_path is None`: existing single-layer command (no change).

Composer signature gains:

```python
def compose_video(
    frames_dir: Path,
    music_path: Path,
    output: Path,
    duration_s: int,
    *,
    bg_video_path: Path | None = None,
    bg_blur_px: int = 30,
    bg_dim: float = 0.4,
    fg_scale: float = 1.0,
) -> int:  # render_ms
```

`fg_scale` defaults to 1.0 (current behavior). Pipeline passes `channel.bg_video.scale` when bg video active.

### 6. Web UI — channel edit page

A new collapsible section "Arka plan videosu (Pexels)":

- **Etkin** toggle (`bg_video.enabled`)
- When enabled, three controls appear:
  - **Çerçeve oranı** — radio: `0.88 (dar şerit)` / `0.80 (geniş şerit)`
  - **Bulanıklık** — slider 0–80 px (default 30)
  - **Karartma** — slider 0–100% (default 60% = `dim=0.4`)
- Above all: a one-line warning if `pexels_api_key` is not set:
  > "⚠ Pexels API key tanımlı değil. Önce Ayarlar sayfasından gir."
  with link to `/settings`.

Channel new wizard: same section, `enabled` defaults to `false`.

### 7. Cache

- Path: `data/cache/pexels_videos/<sha1(url)[:16]>.mp4`
- No automatic eviction in this spec. Manual cleanup via filesystem; future enhancement could add a TTL job.
- One short clip is typically reused for many renders → real network calls are rare.

## Failure modes

| Condition | Behavior |
|---|---|
| `bg_video.enabled=true`, key missing | Log warning, fallback to fullscreen layout. Pipeline still succeeds. |
| Pexels search returns 0 | Log warning, fallback. |
| Pexels search HTTP error / rate limited | Log warning with status, fallback. |
| Download fails (network / corrupt mp4) | Try next candidate; if all fail, fallback. |
| FFmpeg overlay fails | Bubble up — render fails as before (this is a real bug, not graceful degradation). |

Pipeline never aborts solely because Pexels is unavailable. Channel's render quality may degrade temporarily but content still ships.

## Test plan

- `tests/test_pexels.py` — `search_videos` (httpx mocked), `download_video` (requests mocked + idempotency), `pick_query_for_archetype` returns from pool.
- `tests/test_config.py` extension — `bg_video` parses from YAML, defaults when absent, scale validator rejects values other than 0.88/0.80.
- `tests/test_pipeline.py` extension — when `bg_video.enabled` and key present, pipeline calls Pexels and passes `bg_video_path` to composer; when key missing, falls back gracefully.
- `tests/test_composer.py` — new test asserting the 2-input ffmpeg command shape when `bg_video_path` provided (mock subprocess); existing 1-input path unchanged.
- `tests/test_web_settings.py` extension — Settings page renders `pexels_api_key` field, saving persists.
- `tests/test_web_channel_edit.py` extension — bg_video section renders, toggle + scale radio bind correctly, warning shown when key absent.

Pixel-level snapshot test for the composited output is **out of scope** — too brittle (Pexels content changes). Manual visual verification on first run.

## Out of scope (deliberate)

- Automatic cache eviction / TTL.
- Multiple Pexels candidates with quality scoring (we take first that downloads).
- AI-driven query generation (always archetype pool).
- Audio mixing from Pexels clip (always silent — short already has music).
- Re-rendering existing shorts with bg video applied.

## Migration

- Existing channel YAML files: untouched. `bg_video` is optional; absent ⇒ feature off.
- Existing rendered shorts: untouched.
- Settings: existing `settings.yaml` is **untouched**. API key lives in `data/secrets.yaml` (new, git-ignored). Loading without it works (resolver returns empty string, feature behaves as if `enabled=false`).

## Open questions

None — all major decisions resolved during brainstorming:
- Search strategy: archetype pool (option C).
- Scale options: 0.88 / 0.80 (binary radio).
- API key location: env var with settings.yaml fallback, configured from web Settings page.
