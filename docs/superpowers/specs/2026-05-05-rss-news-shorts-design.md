# RSS → YouTube Shorts Bot — Tasarım Belgesi

**Tarih:** 2026-05-05
**Konum:** `D:\short`
**Durum:** Brainstorm tamamlandı, implementasyon planı bekliyor

## 1. Amaç

Google News RSS akışlarından (örn. `https://news.google.com/rss/search?q=KEYWORD&hl=tr&gl=TR&ceid=TR:tr`) ilginç/önemli haberleri otomatik tespit edip, **3 katmanlı haber-infografik tarzında 30 saniyelik dikey (9:16) YouTube Shorts videoları üreten** standalone bir Python sistemi. Üretilen video dosyaları diske yazılır (otomatik upload yok, MVP'de). Üretim ve yönetim **yerel web paneli** üzerinden yapılır.

## 2. Kapsam (Scope)

**MVP'de var:**
- Tek aktif kanal (`son-dakika`), config-driven mimaride çoklu kanal hazır
- 30 saniye sabit süre, kinetic text + müzik formatı (TTS yok)
- 3-katmanlı şablon: kırmızı banner / fotoğraf+sarı vurgu / koyu zeminde paragraf+highlight'lar
- LLM (Claude CLI subprocess) ile ilginçlik skoru + script üretimi
- Dedup: SQLite'da `<guid>` + fuzzy başlık benzerliği
- Web paneli: Dashboard / Shorts galerisi / RSS tarama / Kanal düzenleme / Loglar / Short detay
- APScheduler cron (kanal başına yapılandırılabilir, varsayılan günde 6)
- Manuel "Şimdi üret" tetikleme + RSS sayfasından eşik altı item için zorlama

**MVP dışı (sonra):**
- YouTube Data API ile otomatik upload (mimari hazır, modül yok)
- Birden fazla aktif kanal (config destekler, MVP'de devre dışı)
- TTS / sesli anlatım
- AI sunucu / avatar
- Stok B-roll (Pexels API)

## 3. Tasarım Kararları

### 3.1 Karar tablosu

| # | Karar | Seçilen | Gerekçe |
|---|---|---|---|
| 1 | Stack | Standalone Python | `media-generator`'a bağımlılık yaratmamak |
| 2 | Format | Kinetic text + müzik | TTS bağımlılığı yok, hızlı üretim, telif kolay |
| 3 | Kanal stratejisi | Config-driven multi-channel + LLM skoru | Genişletilebilir kanal kimliği, kalite filtre |
| 4 | LLM | Claude CLI subprocess | API key yönetimi yok, mevcut login kullanılır |
| 5 | Arka plan | RSS thumbnail blur (D), fallback kanal gradient (A) | Görsel zenginlik + güvenli düşüş |
| 6 | Çıktı | Dosya, upload yok | MVP basit; günde 6, 1 kanal |
| 7 | Müzik | Yerel `assets/music/<mood>/*.mp3` havuzu | Telif kontrolü, mood bazlı seçim |
| 8 | Süre | 30s | Standart Shorts süresi |
| 9 | Dedup | guid + fuzzy başlık | Aynı haberin farklı kaynaklardan gelmesini yakalar |
| 10 | Render motoru | HTML/CSS + Playwright + FFmpeg | Mockup = render; kinetic text CSS'in güçlü alanı |
| 11 | UI Stack | Flask + SQLAlchemy + APScheduler + HTMX + Tailwind | `media-generator/youtube_panel` ile tutarlı |
| 12 | Layout | 3 katmanlı (banner/foto+overlay/paragraf+highlights) | Kullanıcının verdiği örnek (`Screenshot_1.png`) referans, üzerine geliştirildi |

### 3.2 Layout (v2)

Verdiğiniz örnek (`C:\Users\Hiko\Desktop\New folder\Screenshot_1.png`) baz alındı. v2 farkları:

- Üst banner: degrade kırmızı (`#c81e1e → #ff4040`) + sağ üstte siyah/sarı "SON DAKİKA" rozeti
- Fotoğraf alanı (200px): sol üstte kanal kategorisi rozeti (EKONOMİ/SPOR/...), sarı vurgu eğimli (skew -1.5°)
- Paragraf gövdesi: 2 farklı highlight rengi:
  - **Kırmızı** (`#c81e1e` bg, beyaz fg) → uyarı/sayı/tehlike
  - **Sarı** (`#ffea3b` bg, siyah fg) → vurgu/önemli ifade
- İlerleme çubuğu (sarı→kırmızı degrade) süre göstergesi olarak
- Body font: Inter (web font, Türkçe diakritik desteği), satır yüksekliği 1.55

### 3.3 CTA Overlay (son 4 saniye)

Video'nun son 4 saniyesinde (26.-30. sn) aşağıdan slide-in ile bir CTA bandı gelir, son anda da hafif scale-in ile büyür:

- **İçerik:** kanal handle'ı (örn. `@HaberShortsTR`) + 3 ikon + metin: `❤️ BEĞEN  🔔 ABONE OL  ↗️ PAYLAŞ`
- **Stil:** koyu yarı-saydam zemin (rgba(0,0,0,.85)) + degrade kırmızı şerit, ikon arkasında hafif pulse animasyonu (kalp atışı + zil sallanması)
- **Yer:** alt 1/3, paragraf ve progress bar üzerinde overlay olarak — body paragraf 26. sn'de hafif fade-out olur ki CTA okunabilsin
- **Animasyon süreleri:** 0.5s slide-in → 3s görünür → 0.5s fade-out (toplam 4s)
- **Per-kanal yapılandırılabilir** (bkz. §6.1 `cta` bloğu): metin, ikon emojileri, açma/kapama, süre

## 4. Mimari (Boru Hattı)

8 izole modül + 1 yardımcı + web katmanı. Sol→sağ akış:

```
[1 RSS Fetcher] → [2 Dedup Filter] → [3 LLM Scorer] →
[4 Article Extractor] → [5 Script Writer] → [6 Asset Resolver] →
[7 HTML Renderer] → [8 Video Composer] → [Output + DB Log]
```

### 4.1 Modül sözleşmeleri (input → output)

| # | Modül | Input | Output |
|---|---|---|---|
| 1 | `Fetcher.fetch(channel)` | Channel config | `list[NewsItem]` |
| 2 | `Dedup.filter(items, channel)` | Items + channel slug | `list[NewsItem]` (yeni olanlar) |
| 3 | `Scorer.score(items)` | Items (max N) | `list[ScoredItem]` (skor 0-10) → top-1 |
| 4 | `Extractor.extract(item)` | NewsItem (link var) | `str` (article body, ≤2000 char) veya `None` |
| 5 | `ScriptWriter.write(item, body)` | item + body | `Script` (Pydantic model) |
| 6 | `Assets.resolve(item, script, channel)` | item + script + channel | `RenderJob` (bg_path, music_path, script) |
| 7 | `Renderer.render(job, template)` | RenderJob + Jinja2 template | `Path` (frame klasörü PNG'ler) |
| 8 | `Composer.compose(frames, music, out)` | frames + music + output path | `Path` (mp4) |

### 4.2 Dataclass'lar (`models.py`)

```python
@dataclass(frozen=True)
class NewsItem:
    guid: str
    title: str
    link: str
    source: str | None
    pub_date: datetime | None
    thumb_url: str | None
    description: str | None  # RSS <description> fallback

@dataclass(frozen=True)
class ScoredItem:
    item: NewsItem
    score: float            # 0-10
    reasoning: str          # LLM'in kısa açıklaması (debug için)

class Highlight(BaseModel):
    text: str               # paragrafta birebir geçen ifade
    color: Literal["red", "yellow"]

class Script(BaseModel):
    header_top: str         # 1-2 kelime, örn "FAİZ ŞOKU"
    header_bottom: str      # 1-2 kelime, örn "BAŞLADI"
    photo_overlay: str      # sarı banttaki kısa metin, örn "250 BAZ PUAN İNDİRİM"
    body_paragraph: str     # 4-6 cümle haber özeti, ~250-400 kelime karakter
    highlights: list[Highlight]
    category: str           # "EKONOMİ" / "SPOR" / "SON DAKİKA" / ...
    mood: Literal["breaking", "neutral", "upbeat"]

@dataclass
class RenderJob:
    script: Script
    bg_image_path: Path | None  # blurred thumb path; None → gradient fallback
    music_path: Path
    channel_colors: dict        # {"primary": "#c81e1e", "accent": "#ffea3b", ...}
    handle: str
    duration_s: int
```

## 5. Proje Yapısı

```
D:\short\
├── .gitignore                    # output/, data/, logs/, .superpowers/, __pycache__/
├── README.md
├── pyproject.toml                # Python paketi, deps
├── config\
│   ├── channels\
│   │   └── son-dakika.yaml       # MVP kanalı
│   └── settings.yaml             # global (ffmpeg path, claude path, web port)
├── src\short_bot\
│   ├── __init__.py
│   ├── cli.py                    # `python -m short_bot run --channel son-dakika`
│   ├── pipeline.py               # 8 adımı sırayla çağıran orkestratör
│   ├── models.py                 # NewsItem, ScoredItem, Script, RenderJob
│   ├── fetcher.py
│   ├── dedup.py
│   ├── scorer.py
│   ├── extractor.py
│   ├── script_writer.py
│   ├── assets.py
│   ├── renderer.py
│   ├── composer.py
│   ├── claude_cli.py             # ortak: subprocess + JSON parse + retry
│   ├── db.py                     # SQLite schema + queries (SQLAlchemy)
│   └── web\
│       ├── __init__.py           # Flask app factory
│       ├── routes\
│       │   ├── dashboard.py
│       │   ├── shorts.py
│       │   ├── rss.py
│       │   ├── channels.py
│       │   ├── logs.py
│       │   └── short_detail.py
│       ├── scheduler.py          # APScheduler: cron → pipeline.run(channel)
│       ├── templates\            # Jinja2 (base, navbar, sayfalar)
│       └── static\               # Tailwind CDN, ufak custom CSS
├── templates\                    # Render şablonları (web template'lerinden ayrı)
│   └── default.html.j2           # 3-katmanlı şablon
├── assets\
│   ├── music\
│   │   ├── breaking\*.mp3
│   │   ├── neutral\*.mp3
│   │   └── upbeat\*.mp3
│   └── fonts\Inter-*.ttf
├── output\                       # üretilen mp4'ler (gitignore'da)
├── data\
│   ├── short_bot.sqlite
│   ├── cache\                    # indirilmiş thumb/article cache
│   └── locks\                    # per-channel file lock
├── logs\
│   ├── app.log                   # rotating
│   └── runs\<id>.log             # her pipeline koşumuna ayrı log
└── tests\
    ├── fixtures\                 # 3 RSS XML, 3 article HTML, 1 thumb, 1 mp3
    ├── test_fetcher.py
    ├── test_dedup.py
    ├── test_extractor.py
    ├── test_scorer.py
    ├── test_script_writer.py
    ├── test_assets.py
    ├── test_renderer.py          # snapshot test (PNG diff < %2)
    ├── test_composer.py          # küçük 3-frame test, ffprobe doğrulama
    ├── test_pipeline.py          # end-to-end mock'lu
    └── test_web\                 # route smoke test
```

## 6. Veri Modeli (SQLite)

```sql
-- Dedup
CREATE TABLE processed_items (
  guid TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  channel TEXT NOT NULL,
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_processed_channel_ts ON processed_items(channel, processed_at);

-- RSS tarama geçmişi (panel için)
CREATE TABLE rss_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guid TEXT NOT NULL,
  channel TEXT NOT NULL,
  title TEXT NOT NULL,
  link TEXT NOT NULL,
  source TEXT,
  pub_date TIMESTAMP,
  thumb_url TEXT,
  score REAL,                      -- NULL = skorlanmadı
  status TEXT,                     -- 'selected' | 'below_threshold' | 'duplicate' | 'extract_failed'
  fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  short_id INTEGER REFERENCES shorts(id)
);

-- Üretilen Shorts
CREATE TABLE shorts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT NOT NULL,
  rss_item_guid TEXT,
  title TEXT NOT NULL,
  file_path TEXT NOT NULL,
  duration_s INTEGER,
  script_json TEXT,                -- {header,paragraph,highlights[],...}
  render_ms INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP             -- soft delete
);
CREATE INDEX idx_shorts_channel_created ON shorts(channel, created_at DESC);

-- Pipeline koşum logu
CREATE TABLE runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT NOT NULL,
  trigger TEXT NOT NULL,           -- 'cron' | 'manual' | 'rss_force'
  started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  ended_at TIMESTAMP,
  status TEXT,                     -- 'running' | 'success' | 'failed' | 'no_candidates'
  short_id INTEGER REFERENCES shorts(id),
  error TEXT,
  log_path TEXT
);
```

### 6.1 Kanal config (YAML)

`config/channels/son-dakika.yaml`:

```yaml
slug: son-dakika
name: "Son Dakika"
keywords: ["son dakika", "deprem", "faiz", "dolar", "seçim", "asgari ücret"]
rss_locale: "hl=tr&gl=TR&ceid=TR:tr"
schedule_cron: "0 2,6,10,14,18,22 * * *"   # günde 6
duration_s: 30
min_score: 8.0
max_candidates_per_run: 30
template: "default"
colors:
  primary: "#c81e1e"
  accent:  "#ffea3b"
  bg_gradient: ["#1a3b6b", "#0a1a3b"]
handle: "@HaberShortsTR"
output_dir: "output/son-dakika"
enabled: true
cta:
  enabled: true
  text: "BEĞEN · ABONE OL · PAYLAŞ"
  icons: ["❤️", "🔔", "↗️"]
  duration_s: 4                    # video sonunda son 4 saniye
  show_handle: true                # handle satırını CTA üstünde göster
```

### 6.2 Global settings

`config/settings.yaml`:

```yaml
ffmpeg_path: "ffmpeg"              # PATH'te varsayılan
claude_cli_path: "claude"
playwright_browser: "chromium"
web:
  host: "127.0.0.1"
  port: 5000
fuzzy_dedup_threshold: 0.85         # difflib SequenceMatcher
log_level: "INFO"
```

## 7. Web Paneli

### 7.1 Sayfalar

| Route | Sayfa | İçerik |
|---|---|---|
| `/` | Dashboard | Bugün üretilen / toplam / RSS taranan / hata sayaçları + son 4 short kart |
| `/shorts` | Shorts galerisi | Filtre (kanal/tarih/arama), grid (9:16 kartlar), tıkla→modal player, indir/yeniden/sil, "Şimdi üret" butonu |
| `/shorts/<id>` | Short detay | Video + kullanılan RSS item + LLM cevapları (script JSON) + render süresi |
| `/rss` | RSS tarama | Bugünün taranan item tablosu (skor, başlık, kaynak, durum), eşik altı için manuel "Üret" |
| `/channels` | Kanal listesi | Aktif kanallar, son üretim, sonraki cron |
| `/channels/<slug>/edit` | Kanal düzenleme | Keyword/renk/süre/cron/handle, sağda canlı önizleme, "Önizleme üret" |
| `/logs` | Log akışı | HTMX polling ile son 200 satır, run filtresi |

### 7.2 Backend

- Flask app factory pattern
- SQLAlchemy modelleri `db.py`'de paylaşımlı (CLI ve web aynı schema)
- APScheduler `BlockingScheduler` web process içinde çalışır; her enabled kanal için `add_job(cron)`
- Pipeline web process içinde modül olarak çalışır (subprocess yok) — durum/log canlı görünür
- "Şimdi üret" → arka plan thread'inde `pipeline.run(channel, trigger='manual')`, web HTMX polling ile run status'unu çeker

### 7.3 Eşzamanlılık ve kilitleme

Her kanal için `data/locks/<slug>.lock` (filelock kütüphanesi). Aynı kanal için ikinci tetik beklemez, **400 + "zaten çalışıyor"** döner (panel'de toast). APScheduler max_instances=1 per job.

### 7.4 Erişim

Sadece `127.0.0.1:5000`. Auth yok (yerel kullanım). Production / uzak erişim MVP dışı.

## 8. Hata Yönetimi

**Strateji: fail-soft, log-loud.** Her pipeline run'ı `runs` tablosuna kayıt yapar; hata olursa `status='failed' + error + log_path` set edilir, panel'de kırmızı badge.

| Aşama | Hata türü | Davranış |
|---|---|---|
| Fetcher | network/timeout/HTTP 4xx | 3 deneme exponential backoff (1s, 2s, 4s); başarısızsa run 'failed' |
| Dedup | DB hata | run 'failed' (kritik) |
| Scorer (Claude CLI) | timeout / non-zero exit / invalid JSON | 2 retry; başarısızsa run 'failed' |
| Extractor (trafilatura) | boş döndü / paywall / timeout | RSS `<description>` fallback; ikisi de yoksa item skip → bir sonraki adaya geç |
| Script Writer (Claude CLI) | invalid JSON / Pydantic validation hatası | 2 retry; başarısızsa run 'failed' |
| Asset Resolver | thumb 404 / decode hatası | A fallback'e (kanal gradient) düş — sessizce |
| Asset Resolver | mood için müzik klasörü boş | "neutral" mood'a düş; o da boşsa run 'failed' |
| Renderer (Playwright) | browser crash / frame timeout (>30s) | Browser yeniden başlat + 1 retry; başarısızsa run 'failed' |
| Composer (FFmpeg) | exit code ≠ 0 | stderr loglanır, run 'failed' |
| Disk dolu | OSError | run 'failed', kritik alarm log + panel banner |

**"No candidates":** dedup sonrası 0 item kalırsa run `status='no_candidates'` olarak biter (hata değil, normal).

## 9. Kaynak Kullanımı ve Performans

- Playwright tek browser instance reuse, run sonunda kapatılır.
- FFmpeg single-pass H.264, CRF 23, preset `veryfast`, `-pix_fmt yuv420p`.
- Hedef: 30s short → 5-10s render (frame capture + compose toplam).
- Token bütçesi: scorer için max 30 başlık × ~50 token = ~1500 input; output JSON ~500 token. Script writer: ~600 input + ~500 output.
- Disk: bir short ~1-3 MB (1080×1920, 30fps, 30s). Günde 6 = ~12 MB/gün.

## 10. Güvenlik / Sağlamlık

- Claude CLI çıktısı her zaman `json.loads` + Pydantic validation. Schema'ya uymazsa retry.
- Trafilatura output'u sanitize: HTML tag strip, max 2000 karakter, kontrol karakterleri filtrele.
- Dosya yolları her zaman `pathlib.Path` üzerinden + slug regex (`^[a-z0-9\-]+$`).
- Web panel sadece localhost bind. CSRF token Flask-WTF ile (kanal düzenleme formları).
- Kullanıcı silme aksiyonu: dosya hard delete + `shorts.deleted_at` set (kayıt kalır audit için).

## 11. Test Stratejisi

Pyramid: çok unit, az integration, 1 end-to-end.

| Test | Kapsam | Yöntem |
|---|---|---|
| `test_fetcher.py` | RSS XML parse | Sabit fixture XML, network'siz |
| `test_dedup.py` | guid + fuzzy | In-memory SQLite, threshold edge case'leri |
| `test_extractor.py` | makale çıkarma | Sabit HTML fixture, requests mock |
| `test_scorer.py` | LLM skor parse + top-N | `claude_cli.run` monkeypatch → sabit JSON |
| `test_script_writer.py` | Script Pydantic validation | Mock claude_cli, geçerli/geçersiz JSON |
| `test_assets.py` | thumb indir+blur, müzik picker | requests mock, geçici dizin |
| `test_renderer.py` | HTML→frame | Gerçek Playwright, 1 frame snapshot karşılaştırma (PNG diff < %2) |
| `test_composer.py` | FFmpeg invoke | Gerçek ffmpeg, küçük 3-frame test, ffprobe ile çıktı doğrulama |
| `test_pipeline.py` | end-to-end | Modüller mock, sadece dosya I/O gerçek |
| `test_web_*.py` | route smoke | Flask test client, tüm sayfalar GET → 200 |

**Sabit fixture'lar:** `tests/fixtures/` altında 3 RSS XML + 3 article HTML + 1 thumb PNG + 1 short mp3. Tüm testler offline çalışmalı (CI dostu).

**Manuel kabul:** İlk MVP koşumdan sonra üretilen short tarayıcıda oynatılır. Kabul kriteri: *"Yazı okunabilir (Türkçe diakritik tam), müzik bitişik kesilmiyor, fotoğraf/gradient görünüyor, highlights doğru renklerde, son 4 saniyede CTA bandı (beğen/abone ol/paylaş) düzgün animasyonla görünür."*

## 12. Bağımlılıklar (`pyproject.toml`)

```
# Çekirdek
feedparser>=6.0          # RSS parse
trafilatura>=1.6         # makale gövdesi
requests>=2.31           # HTTP
pydantic>=2.5            # data validation

# Render
jinja2>=3.1
playwright>=1.40         # headless chromium
pillow>=10.1             # thumb blur

# Composition
ffmpeg-python>=0.2       # ffmpeg wrapper

# Web
flask>=3.0
flask-sqlalchemy>=3.1
flask-wtf>=1.2           # CSRF
apscheduler>=3.10
filelock>=3.13

# Util
pyyaml>=6.0
python-dateutil>=2.8

# Dev
pytest>=7.4
pytest-cov>=4.1
```

Sistem bağımlılıkları: **ffmpeg binary** (PATH'te), **Claude CLI** (PATH'te), **Chromium** (`playwright install chromium`).

## 13. İlk Çalıştırma (User Flow)

1. `pip install -e .` (dev)
2. `playwright install chromium`
3. `assets/music/breaking/` ve `assets/music/neutral/` klasörlerine en az birer mp3 koy
4. `python -m short_bot init` → SQLite şeması oluşturur, varsayılan kanal yaratır
5. `python -m short_bot web` → http://127.0.0.1:5000 açılır
6. Dashboard'da "Şimdi üret" → ilk short üretilir
7. Shorts sayfasında karta tıkla → modal player'da izle

CLI alternatifi (web olmadan):
```
python -m short_bot run --channel son-dakika --max 1
```

## 14. Açık Konular / Sonraki Sürümler

- YouTube Data API ile auto-upload (yarı/tam otomatik)
- Çoklu kanal aktif çalışma (UI'de "all channels" view)
- TTS opsiyonu (kanal config'inde aç/kapa)
- Stok B-roll (Pexels API) seçeneği
- Kanal-spesifik şablonlar (`templates/<slug>.html.j2`)
- Trend bazlı keyword öneri (LLM ile)
- Web panel auth (uzak erişim için)
