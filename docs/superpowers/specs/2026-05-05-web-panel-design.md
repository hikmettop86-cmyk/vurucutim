# Phase 3: Web Panel Tasarım Belgesi

**Tarih:** 2026-05-05
**Konum:** `D:\short`
**Durum:** Brainstorm tamamlandı, implementasyon planı bekliyor
**Bağımlılıklar:** Phase 1 (RSS → Shorts pipeline) ve Phase 2 (Channel DNA + Multi-Language) tamamlandı

## 1. Amaç

Phase 1+2 ile çalışan sistemin (RSS pipeline + 7 archetype + DNA generation + 5 dil) üstüne **yerel web yönetim paneli** ekler. Şu anda her şey CLI üzerinden — paneli ile:

- Yeni kanal yaratma sihirbazla yapılır (Opus DNA üretimi loading state + canlı preview)
- DNA görsel olarak düzenlenir (color pickers, font dropdowns, segment pills)
- Üretilen Short'lar galerilenir, oynatılır, silinir, yeniden üretilir
- RSS taraması şeffaflaşır (her item'ın skoru görünür, eşik altı manuel zorlanabilir)
- Cron çalışır, yeni Short üretildiğinde dashboard'da görünür
- Loglar canlı izlenir

CLI komutları aynen çalışmaya devam eder; panel onun "GUI'si" gibi davranır.

## 2. Kapsam

**Bu specte var:**
- Flask + Jinja2 + HTMX + Tailwind (CDN) + Alpine.js (CDN) stack
- 6 ana sayfa + 1 yeni kanal yaratma sihirbazı + iframe preview endpoint
- DNA editörü (palette/font/banner-shape/highlight/chip/tone) + canlı preview
- APScheduler in-process (BackgroundScheduler) — kanal cron'larını otomatik tetikler
- "Şimdi üret" buton (manuel pipeline tetikleme, threading)
- HTMX polling ile run status, log tail, RSS tablosu
- Localhost-only (varsayılan port 5005), auth yok

**Bu spec dışı (gelecek faz):**
- Auth (basic auth / OAuth)
- Multi-user
- WebSocket (HTMX polling yeterli)
- Mobile responsive
- Headless scheduler mode (web'siz)
- YouTube auto-upload
- Backup/restore
- i18n (panel UI Türkçe sabit)

## 3. Tasarım Kararları

| # | Karar | Seçilen | Gerekçe |
|---|---|---|---|
| 1 | Sayfa kapsamı | 6 ana sayfa + kanal yaratma sihirbazı + DNA editör | Tam yönetim, CLI'siz UX |
| 2 | Stack | Flask + HTMX + Tailwind CDN + Alpine.js CDN | Build adımı yok, Phase 1+2 Python ile devam |
| 3 | Channel creation UX | Form + yan canlı preview iframe | Beğenmedin → "Yeniden Üret" form veri kaybetmeden, en hızlı iterasyon |
| 4 | DNA editör | Görsel inline (color pickers, font dropdown, segment pills) | Color picker + dropdown ile 5 dakikada tweak; YAML editor over-engineering |
| 5 | Live preview | Real-time HTML render endpoint (`/preview/<slug>`) | Server zaten `build_html` üretir, browser tarafında render = ~50ms latency, Playwright gereksiz |
| 6 | Scheduler | APScheduler `BackgroundScheduler` Flask process içinde | Yerel kullanım için tek başlatma, tek kapatma |
| 7 | Erişim + auth | 127.0.0.1 only, auth yok | Yerel, tek-kullanıcı; ileride flask-login eklenir |
| 8 | Default port | 5005 (was 5000) | Kullanıcının makinesinde 5000 dolu |
| 9 | ORM | SQLAlchemy ORM (Flask-SQLAlchemy) | Web'de `query.filter` daha rahat; Phase 1 Core tabloları üstüne map |
| 10 | Pipeline runner | `threading.Thread` + per-channel filelock | Phase 1+2'deki filelock zaten conflict önler |

## 4. Mimari

```
[Flask App Factory: src/short_bot/web/__init__.py]
       │
       ├── Blueprints (7)
       │   ├── dashboard.py    → /
       │   ├── shorts.py       → /shorts, /shorts/<id>, +HTMX
       │   ├── rss.py          → /rss, /rss/<id>/produce
       │   ├── channels.py     → /channels (list)
       │   ├── channel_new.py  → /channels/new (wizard)
       │   ├── channel_edit.py → /channels/<slug>/edit (DNA editor)
       │   ├── preview.py      → /preview/<slug> (iframe HTML)
       │   └── logs.py         → /logs, /logs/tail
       │
       ├── APScheduler (BackgroundScheduler)
       │   Startup: enabled kanallar için cron job register
       │   Job: pipeline.run_pipeline(channel, trigger="cron")
       │   Reload: 5 dakikada bir kanal config'lerini tarar
       │
       ├── Pipeline integration
       │   Imports pipeline.run_pipeline (Phase 1+2)
       │   "Şimdi üret" → threading.Thread → run_pipeline
       │   HTMX polling → /runs/<run_id>/status
       │
       ├── Static + Templates
       │   templates/web/      (Jinja for panel pages)
       │   static/             (Tailwind CDN, Alpine CDN, custom.css)
       │   templates/<arch>.html.j2 unchanged (preview iframe kullanır)
       │
       └── Threading + Locks
           filelock per-channel (Phase 1+2)
           SQLAlchemy session (Flask-SQLAlchemy default)
```

### 4.1 Yeni dosyalar

```
src/short_bot/web/
├── __init__.py              # Flask app factory + scheduler init
├── extensions.py            # SQLAlchemy db = SQLAlchemy()
├── models.py                # ORM models (Short, Run, RssItem, ProcessedItem)
├── routes/
│   ├── __init__.py          # Blueprint registration
│   ├── dashboard.py
│   ├── shorts.py
│   ├── rss.py
│   ├── channels.py
│   ├── channel_new.py       # /channels/new wizard
│   ├── channel_edit.py      # /channels/<slug>/edit + DNA editor
│   ├── preview.py           # /preview/<slug> iframe HTML
│   └── logs.py
├── scheduler.py             # APScheduler wiring
├── runs.py                  # Threaded pipeline runner + status helpers
└── templates/
    ├── base.html.j2         # nav + Tailwind CDN
    ├── dashboard.html.j2
    ├── shorts/
    │   ├── list.html.j2
    │   └── detail.html.j2
    ├── channels/
    │   ├── list.html.j2
    │   ├── new.html.j2      # form + iframe preview
    │   └── edit.html.j2     # DNA editor + iframe preview
    ├── rss.html.j2
    ├── logs.html.j2
    └── _partials/
        ├── shorts_grid.html.j2
        ├── run_status.html.j2
        ├── dna_preview.html.j2
        └── log_tail.html.j2

config/settings.yaml         # web.port: 5000 → 5005

src/short_bot/cli.py         # +'web' subcommand → starts Flask + scheduler
```

### 4.2 Pages + routes

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Dashboard: 4 sayaç (bugün/toplam/RSS/hata), son 4 short kart, sonraki cron |
| `/shorts` | GET | Galeri: filtre (kanal/tarih/arama), grid 9:16 kart, "Şimdi üret" buton |
| `/shorts/grid` | GET | HTMX partial: filter sonucu grid swap |
| `/shorts/<id>` | GET | Detay: video player, RSS item, LLM script JSON, render süresi |
| `/shorts/<id>/delete` | POST | Soft delete: dosya silinir, deleted_at set |
| `/shorts/<id>/regenerate` | POST | Aynı RSS item ile pipeline tekrar (yeni Short id) |
| `/rss` | GET | Tablo: bugünkü item'lar, skor, durum (selected/below_threshold/duplicate) |
| `/rss/<id>/produce` | POST | Eşik altı item için pipeline tetikle (skor bypass) |
| `/channels` | GET | Liste: archetype/dil/son üretim/sonraki cron + DNA badge |
| `/channels/new` | GET | Wizard: form (sol) + boş preview (sağ) |
| `/channels/new/generate` | POST | Form'dan Opus DNA üret, dna_preview partial swap |
| `/channels/new/save` | POST | DNA + form → save_channel + build_css_override → redirect |
| `/channels/<slug>/edit` | GET | Form + DNA editör + preview iframe |
| `/channels/<slug>/edit` | POST | Save changes, rebuild CSS |
| `/channels/<slug>/regenerate-dna` | POST | Opus tekrar çağır (run_status polling) |
| `/channels/<slug>/delete` | POST | YAML + CSS sil + onay modal |
| `/preview/<slug>` | GET | iframe içeriği: `build_html()` doğrudan, query param ile DNA tweak |
| `/logs` | GET | Log tail, son 200 satır, run filter |
| `/logs/tail` | GET | HTMX polling 2s interval |
| `/runs/<run_id>/status` | GET | Run status JSON + status partial |

### 4.3 Frontend stack

- **Tailwind CDN:** `<script src="https://cdn.tailwindcss.com"></script>` — build adımı yok
- **HTMX 2.x CDN:** partial swaps, polling, form submission
- **Alpine.js CDN:** color pickers, modal state, segment pills (HTMX'in yetersiz kaldığı reactive yerlerde)
- **Native HTML5 `<input type="color">`:** palette renk seçici
- **`<select>`:** Google Fonts'tan 30 popüler font dropdown

## 5. Veri Modeli (SQLAlchemy ORM)

`src/short_bot/web/models.py`:

```python
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class ProcessedItem(db.Model):
    __tablename__ = "processed_items"
    guid = db.Column(db.String, primary_key=True)
    title = db.Column(db.Text, nullable=False)
    channel = db.Column(db.String, nullable=False)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)


class RssItem(db.Model):
    __tablename__ = "rss_items"
    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String, nullable=False)
    channel = db.Column(db.String, nullable=False)
    title = db.Column(db.Text, nullable=False)
    link = db.Column(db.Text, nullable=False)
    source = db.Column(db.String)
    pub_date = db.Column(db.DateTime)
    thumb_url = db.Column(db.Text)
    score = db.Column(db.Float)
    status = db.Column(db.String)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)
    short_id = db.Column(db.Integer, db.ForeignKey("shorts.id"))


class Short(db.Model):
    __tablename__ = "shorts"
    id = db.Column(db.Integer, primary_key=True)
    channel = db.Column(db.String, nullable=False)
    rss_item_guid = db.Column(db.String)
    title = db.Column(db.Text, nullable=False)
    file_path = db.Column(db.Text, nullable=False)
    duration_s = db.Column(db.Integer)
    script_json = db.Column(db.Text)
    render_ms = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    deleted_at = db.Column(db.DateTime)

    @property
    def file_url(self):
        from pathlib import Path
        return f"/output/{self.channel}/{Path(self.file_path).name}"


class Run(db.Model):
    __tablename__ = "runs"
    id = db.Column(db.Integer, primary_key=True)
    channel = db.Column(db.String, nullable=False)
    trigger = db.Column(db.String, nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)
    status = db.Column(db.String)
    short_id = db.Column(db.Integer, db.ForeignKey("shorts.id"))
    error = db.Column(db.Text)
    log_path = db.Column(db.Text)
```

Tablo isimleri Phase 1 schema'sıyla aynı. `db.create_all()` mevcut SQLite dosyasında değişiklik yapmaz, sadece map eder.

## 6. Kanal Yaratma Sihirbazı

### 6.1 UX akışı

```
┌────────────── /channels/new ─────────────┬──────────────────────────────┐
│ TEMEL                                    │  CANLI ÖNİZLEME              │
│ Kanal adı: [Spor Short DE___]            │                              │
│ Dil:       [🇩🇪 Deutsch ▾]               │  ┌──────────────────────┐    │
│ Keywords:  [Bundesliga, Bayern_]         │  │  (boş — DNA üretene  │    │
│ Konu ipucu: [Hardcore taraftar]          │  │   kadar)             │    │
│ Hedef kitle: [...]                       │  │                      │    │
│                                          │  └──────────────────────┘    │
│ ┌─ ⚡ DNA Üret (Opus, ~30-60s) ──────┐  │                              │
│ └────────────────────────────────────┘  │                              │
└──────────────────────────────────────────┴──────────────────────────────┘
```

### 6.2 "DNA Üret" tıklanınca

1. HTMX `POST /channels/new/generate` (form data)
2. Sağ panel "Opus düşünüyor..." spinner ile swap olur
3. `dna.generate_dna(name, keywords, language, topic_hint, audience)` çağrılır (~30-60s)
4. Cevap geldiğinde `_partials/dna_preview.html.j2` partial render:
   - Archetype + palette + fonts metin özeti
   - iframe `src="/preview/__tmp__?session=<uuid>"` — DNA in-memory session'da
   - **[↻ Yeniden Üret]** ve **[Kaydet]** butonları
5. **Yeniden Üret** → tekrar `POST /generate` (Opus farklı varyant)
6. **Kaydet** → `POST /save` → `save_channel(...)` + `build_css_override(...)` → redirect to `/channels/<slug>/edit`

### 6.3 In-memory session

Wizard sırasında DNA henüz YAML'a yazılmadı. Flask `session` objesinde geçici olarak saklanır:

```python
session["wizard_dna_<uuid>"] = dna.model_dump_json()
```

`/preview/__tmp__?session=<uuid>` route bu session'dan DNA'yı okur, `build_html` ile render eder. Save anında session temizlenir.

## 7. DNA Editörü (`/channels/<slug>/edit`)

### 7.1 Layout

```
┌─────────── /channels/spor-short-de/edit ──────────┬───────────────────┐
│ Spor Short DE  (de · stadium)         [Sil] [×]   │                   │
├───────────────────────────────────────────────────┤  ┌─────────────┐  │
│ TEMEL                                             │  │ iframe      │  │
│ Keywords [Bundesliga, Bayern___________________]  │  │ canlı       │  │
│ Cron     [0 8,16,22 * * *_____________________]   │  │ preview     │  │
│ Handle   [@SportShortDE_______________________]   │  │             │  │
│ Süre [6] sn   Min skor [6.0]   ☑ Enabled          │  │ BAYERN      │  │
│                                                   │  │ DREHT       │  │
│ ─── DNA EDİTÖR ───                                │  │ 90+4        │  │
│ Archetype: ⚽ stadium (kilitli, regenerate ile     │  │             │  │
│             değişir)                              │  │ TORSCHUSS   │  │
│                                                   │  │ NACHSPIEL.  │  │
│ Palette:                                          │  │             │  │
│  Primary  [▮ #dc052d] picker                      │  │ [body...]   │  │
│  Accent   [▮ #ffd700] picker                      │  │             │  │
│  BG grad  [▮ #1a8b3a] [▮ #0a4d1a] picker          │  │ ❤️ GEFÄLLT  │  │
│  Body bg  [▮ #0a1a0a] [▮ #000000] picker          │  │ 🔔 ABO.     │  │
│                                                   │  └─────────────┘  │
│ Fonts:                                            │                   │
│  Headline [Oswald ▾]  Body [Inter ▾]              │  ↻ otomatik       │
│                                                   │     güncellenir   │
│ Banner shape:  [flat·ribbon·● slanted·sharp]      │                   │
│ Highlight:     [● bg-flat·underline·marker·neon]  │                   │
│ Chip style:    [rounded·sharp·● pill]             │                   │
│ Category icon: [⚽] (emoji)                       │                   │
│ Search query:  [{header_top} {category} bundesliga│                   │
│                                                   │                   │
│ Tone of voice (textarea):                         │                   │
│  voice: leidenschaftlich, dynamisch               │                   │
│  forbidden: langweilig, akademisch                │                   │
│  body_max_chars: 280                              │                   │
│                                                   │                   │
│ [↻ Regenerate via Opus]  [💾 Kaydet]              │                   │
└───────────────────────────────────────────────────┴───────────────────┘
```

### 7.2 Reactive davranış

- Color picker `oninput` → Alpine state update → iframe `src` query param güncellenir → 50ms preview swap
- Font dropdown change → aynı şekilde iframe update
- Segment pills: tıkla → aktif state → iframe update
- Tone textarea: 300ms debounced → iframe update (paragraph length visualization)
- **Kaydet** → form submit → `save_channel()` + `build_css_override()` (LLM yok, instant)
- **Regenerate via Opus** → `POST /channels/<slug>/regenerate-dna` → run_status polling, ~30-60s, sonra page reload
- **Sil** → modal confirm + `POST /channels/<slug>/delete` → YAML+CSS silinir → redirect

## 8. Preview Endpoint (`/preview/<slug>`)

```python
@bp.route("/preview/<slug>")
def preview(slug):
    cfg = load_channel(...)  # disk veya session-cache (wizard için)

    # Override DNA fields from query params (color picker tweaks)
    primary = request.args.get("primary", cfg.dna.palette.primary if cfg.dna else cfg.colors["primary"])
    accent = request.args.get("accent", ...)
    # ... similar for fonts, banner_shape, etc.

    # Build a sample Script for the channel's language
    script = SAMPLE_SCRIPTS[cfg.language]  # tests/fixtures/sample_script_<lang>.json

    job = RenderJob(
        script=script, bg_image_path=None,
        music_path=Path("dummy.mp3"),
        channel_colors={"primary": primary, "accent": accent, "bg_gradient": cfg.colors["bg_gradient"]},
        handle=cfg.handle, duration_s=cfg.duration_s,
        language=cfg.language, cta_enabled=False,
    )

    # Build dna_css with overrides applied
    dna = cfg.dna or _default_dna(cfg.template)
    if primary: dna.palette.primary = primary
    # ... apply all overrides
    dna_css = build_css_override(dna)

    template_path = Path(f"templates/{cfg.template}.html.j2")
    html = build_html(job, template_path,
                      ui_labels=ui_labels_for(cfg.language), dna_css=dna_css)
    return Response(html, mimetype="text/html")
```

Sample scripts: `tests/fixtures/sample_script_<lang>.json` (5 dosya, generic news, archetype-bağımsız).

## 9. Pipeline Threading + Run Status

### 9.1 "Şimdi üret" akışı

```python
@channels_bp.route("/<slug>/run-now", methods=["POST"])
def run_now(slug):
    cfg = load_channel(...)
    settings = load_settings(...)

    # Threaded pipeline launch
    def _runner():
        run_pipeline(channel=cfg, settings=settings, db_path=DB_PATH,
                     music_root=MUSIC_ROOT, templates_dir=TEMPLATES_DIR,
                     cache_dir=CACHE_DIR, lock_dir=LOCK_DIR, logs_dir=LOGS_DIR,
                     trigger="manual")

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()

    # Find the run_id (it was just created by start_run)
    # Return run_status partial
    run_id = _find_latest_run_id_for_channel(cfg.slug)
    return render_template("_partials/run_status.html.j2", run_id=run_id)
```

### 9.2 HTMX polling

```jinja
<div id="run-status" hx-get="/runs/{{ run_id }}/status"
     hx-trigger="every 2s"
     hx-swap="outerHTML">
  <div class="status status-{{ status }}">
    <span class="dot"></span> {{ status }}
    {% if short_id %}
    <a href="/shorts/{{ short_id }}">→ Yeni short</a>
    {% endif %}
  </div>
</div>
```

`/runs/<run_id>/status` endpoint çalışan run için aynı partial'i döner. Status `success`/`failed`/`no_candidates` olduğunda HTMX `hx-swap-oob` ile başka modal/toast tetiklenir veya polling durur.

## 10. APScheduler Entegrasyonu

`src/short_bot/web/scheduler.py`:

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


def init_scheduler(app):
    scheduler = BackgroundScheduler()
    scheduler.start()

    def reload_jobs():
        scheduler.remove_all_jobs()
        for cfg in list_channels(CHANNELS_DIR, enabled_only=True):
            trigger = CronTrigger.from_crontab(cfg.schedule_cron)
            scheduler.add_job(
                _run_for_channel, trigger,
                args=[cfg.slug], id=cfg.slug,
                max_instances=1, replace_existing=True,
            )

    def _run_for_channel(slug):
        cfg = load_channel(...)
        settings = load_settings(...)
        run_pipeline(channel=cfg, settings=settings, ..., trigger="cron")

    # Initial register
    reload_jobs()

    # Watcher: 5 dakikada bir kanal config klasörünü tara, değişiklik varsa reload
    scheduler.add_job(reload_jobs, "interval", minutes=5, id="_reload_jobs")

    app.scheduler = scheduler
    return scheduler
```

Stdout log:
```
Web panel: http://127.0.0.1:5005
Scheduler: 2 channels active
  son-dakika    cron='0 2,6,10,14,18,22 * * *'  next: 14:00
  spor-short-de cron='0 8,16,22 * * *'           next: 16:00
```

## 11. Hata Yönetimi

| Yer | Durum | Davranış |
|---|---|---|
| `/preview/<slug>` | kanal yok | 404 + "Channel not found" |
| `/preview/<slug>` | geçersiz query param | Default DNA değerlerine düş, sessizce render |
| `/channels/new/generate` | Opus timeout | Toast (kırmızı) + "Tekrar dene" |
| `/channels/<slug>/run-now` | filelock busy | 400 + toast "zaten çalışıyor" |
| Pipeline disk dolu | OSError | Banner: "Disk dolu, eski mp4'leri silin" |
| APScheduler cron parse hatası | startup | Stdout error, o kanal disabled flag set, paneldeki "Kanallar" sayfasında uyarı badge |
| `/shorts/<id>` | dosya silinmiş | 410 Gone + "Dosya bulunamadı" |
| Channel YAML schema hatası | startup load | Stdout error, o kanal disabled, paneldeki Kanallar listesinde "❌ schema error" badge |

## 12. Test Stratejisi

| Test dosyası | Kapsam | # test |
|---|---|---|
| `test_web_app_factory.py` | App oluşur, scheduler register, blueprints yüklenir | 3 |
| `test_web_dashboard.py` | `/` GET, sayaçlar | 3 |
| `test_web_shorts.py` | Liste + detay + delete + regenerate + filter HTMX | 6 |
| `test_web_rss.py` | Tablo + produce action | 3 |
| `test_web_channels.py` | Liste + edit (form-only) | 5 |
| `test_web_channel_new.py` | Wizard form, generate (mock Opus), save | 6 |
| `test_web_preview.py` | HTML render, query param overrides | 5 |
| `test_web_logs.py` | Tail polling | 2 |
| `test_web_runs.py` | Threaded runner + status polling | 3 |
| `test_web_scheduler.py` | APScheduler register + reload | 3 |
| `test_web_models.py` | ORM map mevcut schema | 2 |

**Toplam: ~41 yeni test.** Web testleri Flask `app.test_client()` kullanır. APScheduler mock'lanır. Pipeline thread testleri `run_pipeline` mock'lanır.

**Manuel kabul:**
1. `python -m short_bot web` çalıştır → http://127.0.0.1:5005 açılır
2. Dashboard'da 2 kanal (TR + DE)
3. "Yeni Kanal" → EN tabloid magazin yarat → wizard → DNA üret → preview → kaydet
4. spor-short-de'yi edit'le: primary tweak → preview anında değişir → kaydet
5. Cron set et 1 dakika sonraya → o saatte mp4 üretilir, dashboard'da görünür
6. "Şimdi üret" → run_status polling → success → modal'da yeni mp4 oynat

## 13. Bağımlılıklar

`pyproject.toml` `[project] dependencies` bloğuna eklenecekler:

```python
"flask>=3.0",
"flask-sqlalchemy>=3.1",
"apscheduler>=3.10",
"flask-wtf>=1.2",       # CSRF + form handling
```

Sistem bağımlılıkları değişmedi (ffmpeg, claude CLI, Playwright zaten var).

`config/settings.yaml` güncellemesi:

```yaml
web:
  host: "127.0.0.1"
  port: 5005             # was 5000 — port conflict avoidance
```

`Settings.web_port` default'u `5005` olur.

Yeni CLI subcommand:

```bash
python -m short_bot web    # Flask + APScheduler birlikte başlar
```

## 14. İlk Çalıştırma (User Flow)

```bash
# Phase 1+2 çalışır halde (DB init edilmiş, 2 kanal var)
python -m short_bot web

# Çıktı:
# Web panel: http://127.0.0.1:5005
# Scheduler: 2 channels active
#   son-dakika    cron='0 2,6,10,14,18,22 * * *'  next: 14:00
#   spor-short-de cron='0 8,16,22 * * *'           next: 16:00
# Press Ctrl+C to stop.
```

Tarayıcıda `http://127.0.0.1:5005` aç:
- Dashboard'da bugünkü üretim sayacı, son 4 short kart, sonraki cron
- Sol nav: Dashboard / Shorts / RSS / Kanallar / Loglar
- Yeni kanal: "+ Yeni Kanal" → wizard → name+language+keywords doldur → "DNA Üret" tıkla → 30-60s sonra preview → "Kaydet"
- Kanal düzenle: Kanallar listesinden tıkla → DNA editör → palette tweak → preview update → "Kaydet"
- Şimdi üret: Shorts sayfasında butonla manuel tetikle → run_status polling → mp4 hazır

## 15. Implementation Sıralaması (Plan Sketch)

Plan'da fazlar:
1. **Foundation** (~5 task): App factory + base template + SQLAlchemy models + Dashboard sayfası + CLI `web` komutu
2. **Read-only sayfalar** (~6 task): Shorts listesi/detay + RSS tablosu + Kanallar listesi + Logs
3. **Channel CRUD** (~5 task): Edit (form-only) + delete + Şimdi üret button + threaded runner
4. **Wizard + DNA Editör** (~8 task): New channel wizard + DNA editör + preview endpoint + color pickers + sample scripts
5. **Scheduler + e2e** (~3 task): APScheduler register + reload + manual smoke

Tahmin: ~27-30 task.
