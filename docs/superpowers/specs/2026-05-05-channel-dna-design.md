# Channel DNA + Multi-Language Tasarım Belgesi

**Tarih:** 2026-05-05
**Konum:** `D:\short`
**Durum:** Brainstorm tamamlandı, implementasyon planı bekliyor
**Bağımlılık:** Phase 1 (RSS → Shorts pipeline) tamamlandı

## 1. Amaç

Mevcut sistemde tek `default.html.j2` template ve hardcoded Türkçe etiketler var. Birden fazla kanal eklenince hepsi aynı görünüyor. Bu spec, **her kanalın benzersiz görsel + içerik kimliğine ("DNA") ve kendi diline sahip olmasını** sağlayan altyapıyı tanımlar.

Çözüm:
- **7 hand-curated archetype template** (newscast, tabloid, magazine, kinetic, dark-tech, stadium, meme)
- **Per-channel CSS override** (kanal yaratılırken Claude Opus tarafından üretilen palette/font/style overrides)
- **Channel-specific tone of voice** (script_writer prompt'una inject edilen voice/style/forbidden/length kuralları)
- **5 dilde kanal desteği** (TR, EN, DE, ES, FR) — RSS locale, UI etiketleri, prompt dili, image search query

Sonuç: 7 archetype × ∞ override × 5 dil = pratik olarak her kanal kendine özgü, ama yeni HTML yazma derdi yok.

## 2. Kapsam

**Bu specte var:**
- DNA generation (Claude Opus, kanal yaratılırken bir kez)
- 7 archetype template (yeni hand-built Jinja dosyaları)
- CSS override mekanizması (deterministik Python ile DNA → CSS)
- Multi-language scaffolding (5 dil, RSS locale auto-derive, UI labels dictionary)
- CLI komutları: `create-channel`, `regenerate-dna`, `rebuild-css`, `migrate-channel`
- Script writer'ın archetype + tone + language inject etmesi
- Image picker'ın search query template'i kullanması
- Persistent chip etiketlerinin dile göre değişmesi
- Backward-compat: mevcut `son-dakika.yaml` çalışmaya devam etsin

**Bu spec dışı (ayrı specler):**
- Phase 2 web paneli (kanal yönetim arayüzü)
- Per-channel music pool (`assets/music/<slug>/<mood>/`) — şimdilik shared
- Per-channel SFX
- Yeni archetype eklenmesi (genişletme talimatı eklenebilir ama 7'lik set MVP için sabit)
- TTS / sesli anlatım
- RTL diller (Arapça, İbranice)
- Subscriber/audience analytics

## 3. Tasarım Kararları

### 3.1 Karar tablosu

| # | Karar | Seçilen | Gerekçe |
|---|---|---|---|
| 1 | DNA kapsamı | Görsel + content tone + behavior parametreleri | Sadece görsel yüzeysel; ses kanal-spesifik şimdilik gereksiz karmaşıklık |
| 2 | Görsel mekanizma | 7 hand-built archetype + LLM-generated CSS override (deterministik Python) | Curated template'ler kalite garantisi; override parmak izi yaratır; tek tek HTML yazma derdi yok |
| 3 | Archetype sayısı | 7 (newscast/tabloid/magazine/kinetic/dark-tech/stadium/meme) | Kullanıcı'nın belirttiği konu çeşitliliğini (politik/spor/finans/aşk/özlü söz/mizah/teknoloji) kapsar |
| 4 | Diller | TR, EN, DE, ES, FR (5 dil) | Kullanıcı'nın belirlediği başlangıç set; Inter font Latin Extended hepsini destekler |
| 5 | Opus üretim zamanı | Sadece kanal yaratılırken (deterministik) | Kanal "tanınabilir" kalsın; her Short'ta Opus pahalı + tutarsız |
| 6 | Script schema | Tek Pydantic Script + archetype-specific prompt instructions | 7 ayrı schema bakım derdi; tek schema esnek + maliyetsiz |
| 7 | Model split | Opus = DNA gen, Sonnet = scoring/script/image-verify | Opus yaratıcı tek-seferlik için ideal; Sonnet hızlı tekrarlı için yeterli |
| 8 | CSS override yöntemi | Deterministik Python (DNA → CSS), inline injection (`{{ dna_css\|safe }}`) | LLM CSS yazımı israf + tutarsız; inline injection Playwright base URL sorununu önler |
| 9 | Backward-compat | Mevcut son-dakika.yaml çalışmaya devam | language yoksa "tr", dna yoksa default fallback'ler |

### 3.2 Archetype taksonomisi

| Archetype | Hedef konular | Tipik palette | Tipik font |
|---|---|---|---|
| **newscast** | Politika, ekonomi, son dakika kritik (FİNANS = altın/gri override) | kırmızı/lacivert/altın | Inter Black |
| **tabloid** | Magazin, sansasyon, ünlü, skandal, viral dedikodu (AŞK-DEDİKODU = pembe override) | sarı/kırmızı/siyah, yüksek kontrast | Bebas Neue |
| **magazine** | Kültür, sanat, lifestyle, weekend, romantik (AŞK-ROMANTİK = pastel override) | bej/krem/burgundy/altın | Playfair Display |
| **kinetic** | İstatistik, alıntı, motivasyon, özlü söz, tek-vurgu | tek vurgu rengi (neon) + siyah | Anton / Inter Black |
| **dark-tech** | Teknoloji, AI, oyun, hacker, fütürist (RETRO-WAVE = 80s pembe override) | cyan/magenta/yeşil neon + koyu mor | JetBrains Mono |
| **stadium** | Spor (futbol/basketbol/F1) (FUTBOL-TR = sarı-kırmızı override) | takım/spor renkleri (yeşil/sarı vb.) | Oswald |
| **meme** | Mizah, komedi, troll, viral video (DARK-HUMOR = mor/siyah override) | parlak mavi/sarı/pembe | Impact |

## 4. Mimari

```
                                                      ┌──────────────────────────┐
[CLI] create-channel ──> [DNA Generator] ──opus──>    │ DnaSpec (Pydantic)       │
       --name, --keywords                              │ - archetype              │
       --language, --topic-hint                        │ - palette/fonts/tone     │
       --target-audience                               │ - banner_shape, etc.     │
                                                      └──────────────────────────┘
                                                                   │
                              ┌────────────────────────────────────┤
                              ↓                                    ↓
        config/channels/<slug>.yaml         templates/css/<slug>.css
        (mevcut alanlar + dna bloğu)        (build_css_override(dna), pure Python)


[Pipeline: Short üretimi — değişen yerler]

[fetcher]    rss_locale = RSS_LOCALES[channel.language]
[script_writer] prompt = base + archetype-specific + tone block + language ("{LANG}'da yaz")
[image_picker]  query  = channel.dna.search_query_template.format(...)
[renderer]   template_path = templates/<channel.template>.html.j2
             dna_css = read templates/css/<slug>.css (varsa)
             ui_labels = UI_LABELS[channel.language]
             html = build_html(job, template_path, ui_labels=..., dna_css=...)
```

### 4.1 Yeni modüller

| Dosya | Sorumluluk |
|---|---|
| `src/short_bot/dna.py` | `DnaSpec` Pydantic modeli, `generate_dna()` (Opus), `build_css_override()` (pure Python), `_banner_shape_css()`, `_highlight_css()`, `_chip_css()` helper'ları |
| `src/short_bot/locale.py` | `RSS_LOCALES`, `LANGUAGE_NAMES`, `UI_LABELS` sözlükleri |
| `templates/<archetype>.html.j2` × 7 | newscast, tabloid, magazine, kinetic, dark-tech, stadium, meme |
| `templates/_shared.html.j2` (opsiyonel) | Persistent chip + progress bar Jinja macro'ları |

### 4.2 Değişen modüller

- `src/short_bot/config.py` — `ChannelConfig` 'a `language`, `template`, `dna` (DnaSpec\|None) alanları; `rss_locale` deprecated/auto-derive; `Settings` 'a `claude_models: dict[str, str]` alanı
- `src/short_bot/script_writer.py` — `ARCHETYPE_PROMPTS` dict, `build_script_prompt(item, body, channel)` channel-aware; tone block + language inject
- `src/short_bot/image_picker.py` — `build_search_query(script, channel)` template-driven
- `src/short_bot/renderer.py` — `build_html(job, template_path, ui_labels, dna_css)`; `RenderJob` 'a `language` alanı
- `src/short_bot/fetcher.py` — `fetch_rss(keywords, language)` (locale auto-derive)
- `src/short_bot/claude_cli.py` — `run_json(..., model="default")` flag, `claude --model` arg
- `src/short_bot/cli.py` — yeni subcommand'lar: `create-channel`, `regenerate-dna`, `rebuild-css`, `migrate-channel`
- `src/short_bot/pipeline.py` — channel.language ve channel.dna pipeline'a iletilir

## 5. Veri Modeli

### 5.1 `DnaSpec` (Pydantic, persisted in channel YAML)

```python
ARCHETYPES = ["newscast", "tabloid", "magazine", "kinetic", "dark-tech", "stadium", "meme"]
LANGUAGES = ["tr", "en", "de", "es", "fr"]


class DnaPalette(BaseModel):
    primary: str          # hex "#RRGGBB"
    accent: str
    bg_gradient: list[str] = Field(min_length=2, max_length=2)
    body_bg: list[str] = Field(min_length=2, max_length=2)
    text_main: str = "#ffffff"
    text_muted: str = "#cccccc"

    @field_validator("primary", "accent", "text_main", "text_muted")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not (v.startswith("#") and len(v) == 7):
            raise ValueError(f"Invalid hex: {v}")
        return v.lower()


class DnaFonts(BaseModel):
    headline: str = "Inter"
    body: str = "Inter"
    google_imports: list[str] = Field(default_factory=list)
    # Examples: ["Inter:wght@400;700;900", "Bebas+Neue", "Playfair+Display:ital@1"]


class DnaTone(BaseModel):
    voice: str = Field(min_length=1, max_length=200)
    style: str = Field(min_length=1, max_length=200)
    forbidden: list[str] = Field(default_factory=list, max_length=10)
    sentence_max_words: int = Field(ge=4, le=40, default=18)
    paragraph_sentences: tuple[int, int] = (3, 5)
    body_max_chars: int = Field(ge=50, le=800, default=350)
    headline_style_hint: str = Field(default="", max_length=200)


class DnaSpec(BaseModel):
    archetype: Literal[*ARCHETYPES]
    palette: DnaPalette
    fonts: DnaFonts
    tone: DnaTone
    banner_shape: Literal["flat", "ribbon", "slanted", "sharp"] = "flat"
    highlight_style: Literal["bg-flat", "underline", "marker", "neon"] = "bg-flat"
    chip_style: Literal["rounded", "sharp", "pill"] = "rounded"
    category_icon: str = ""
    search_query_template: str = "{header_top} {header_bottom} {category}"
    persona_summary: str = Field(max_length=400)
```

### 5.2 `ChannelConfig` (frozen dataclass)

Yeni alanlar:
- `language: Literal["tr","en","de","es","fr"]` — eski `rss_locale` deprecated; backward-compat ile birlikte var olabilir
- `template: str = "newscast"` — archetype adı
- `dna: DnaSpec | None = None` — None = no DNA generated yet (default fallback'ler)

**Validator:** Eğer `dna` set edilmişse, `template == dna.archetype` olmak zorunda. `load_channel` bunu kontrol eder, uyumsuzsa `ValueError` raise eder. (CLI komutları aynı anda ikisini de yazdığı için pratikte hata oluşmaz, manuel YAML düzenlemede koruma sağlar.)

### 5.3 `locale.py` sözlükleri

```python
RSS_LOCALES: dict[str, str] = {
    "tr": "hl=tr&gl=TR&ceid=TR:tr",
    "en": "hl=en-US&gl=US&ceid=US:en",
    "de": "hl=de&gl=DE&ceid=DE:de",
    "es": "hl=es&gl=ES&ceid=ES:es",
    "fr": "hl=fr&gl=FR&ceid=FR:fr",
}

LANGUAGE_NAMES: dict[str, str] = {
    "tr": "Türkçe", "en": "English", "de": "Deutsch", "es": "Español", "fr": "Français",
}

UI_LABELS: dict[str, dict[str, str]] = {
    "tr": {"like": "BEĞEN",       "subscribe": "ABONE OL",   "share": "PAYLAŞ",   "breaking": "SON DAKİKA"},
    "en": {"like": "LIKE",        "subscribe": "SUBSCRIBE",  "share": "SHARE",    "breaking": "BREAKING"},
    "de": {"like": "GEFÄLLT MIR", "subscribe": "ABONNIEREN", "share": "TEILEN",   "breaking": "EILMELDUNG"},
    "es": {"like": "ME GUSTA",    "subscribe": "SUSCRIBIRSE","share": "COMPARTIR","breaking": "ÚLTIMA HORA"},
    "fr": {"like": "J'AIME",      "subscribe": "S'ABONNER",  "share": "PARTAGER", "breaking": "DERNIÈRE MINUTE"},
}
```

### 5.4 Örnek tam kanal YAML (DNA üretildikten sonra)

```yaml
slug: spor-short
name: "Spor Short"
language: de
keywords: ["Bundesliga", "Bayern München", "Champions League"]
schedule_cron: "0 8,16,22 * * *"
duration_s: 6
min_score: 6.0
max_candidates_per_run: 10
template: stadium
handle: "@SportShortDE"
output_dir: output/spor-short
enabled: true

cta:
  enabled: false
  duration_s: 0
  show_handle: false
  # text/icons UI_LABELS[de]'den otomatik

dna:
  archetype: stadium
  palette:
    primary: "#0a4d2a"
    accent: "#ffd700"
    bg_gradient: ["#1a8b3a", "#0a4d1a"]
    body_bg: ["#0a1a0a", "#000000"]
    text_main: "#ffffff"
    text_muted: "#aaffaa"
  fonts:
    headline: "Bebas Neue"
    body: "Inter"
    google_imports: ["Bebas+Neue", "Inter:wght@400;700;900"]
  tone:
    voice: "leidenschaftlich, dynamisch, sportbegeistert"
    style: "schnell, kraftvoll, aktion-orientiert"
    forbidden: ["langweilig", "akademisch"]
    sentence_max_words: 14
    paragraph_sentences: [3, 4]
    body_max_chars: 280
    headline_style_hint: "Score format (Team A 2-1 Team B) oder kurzes Action-Wort"
  banner_shape: slanted
  highlight_style: marker
  chip_style: pill
  category_icon: "⚽"
  search_query_template: "{header_top} {category} bundesliga"
  persona_summary: "Energetischer Bundesliga-Kanal für hardcore Fans..."
```

### 5.5 `settings.yaml` ekleme

```yaml
claude_models:
  dna: opus
  default: sonnet
```

## 6. DNA Üretim Akışı

### 6.1 `generate_dna()` (Opus call)

```python
def generate_dna(
    *, name, keywords, language, topic_hint="", target_audience="",
    claude_path="claude", model="opus",
) -> DnaSpec:
    prompt = build_dna_prompt(name, keywords, language, topic_hint, target_audience)
    return run_json(prompt, DnaSpec, claude_path=claude_path, model=model,
                    retries=2, timeout_s=180)
```

### 6.2 Opus prompt yapısı

```
Sen bir YouTube Shorts kanalının görsel/içerik kimliğini (DNA) tasarlıyorsun.

KANAL BİLGİLERİ:
- İsim: {name}
- Dil: {LANGUAGE_NAMES[language]}
- Keyword'ler: {", ".join(keywords)}
- Konu ipucu: {topic_hint}
- Hedef kitle: {target_audience}

GÖREV: Bu kanal için bir DNA üret. Kararlarını kanalın konusuna ve dilin
kültürel bağlamına göre yap.

ARCHETYPE SEÇİMİ (1 tane seç):
- newscast → resmi haber, politika, ekonomi, son dakika kritik
- tabloid → magazin, sansasyon, ünlü, skandal, viral dedikodu
- magazine → kültür, sanat, lifestyle, weekend, romantik, zarif
- kinetic → istatistik, alıntı, motivasyon, tek-vurgu, özlü söz
- dark-tech → teknoloji, AI, oyun, hacker, fütürist, cyber
- stadium → spor (futbol/basketbol/F1/...), heyecan, dinamik
- meme → mizah, komedi, troll, viral video, gençlik

DİL UYUMU:
- voice/style/forbidden alanlarını {LANGUAGE_NAMES[language]} dilinde yaz
- headline_style_hint da o dilde
- persona_summary tamamen o dilde

PALETTE KARARLARI (archetype'a uygun, ama kanala özgü override yapabilirsin):
- newscast: kırmızı/lacivert/altın
- tabloid: sarı/kırmızı/siyah, yüksek kontrast
- magazine: bej/krem/burgundy/altın, sıcak
- kinetic: tek vurgu rengi (neon yeşil/mor/mavi) + siyah
- dark-tech: cyan/magenta/yeşil neon + koyu mor/siyah
- stadium: takım/spor renkleri (yeşil/sarı, kırmızı/lacivert vb.)
- meme: parlak mavi/sarı/pembe, Impact-vibe

FONT KARARLARI:
- headline: archetype'a uygun (newscast→Inter Black, tabloid→Bebas Neue,
  magazine→Playfair, kinetic→Anton, tech→JetBrains Mono, stadium→Oswald,
  meme→Impact)
- body: okunabilir genelci (Inter veya Roboto)
- google_imports: Google Fonts URL fragment formatında ("Inter:wght@400;700;900",
  "Bebas+Neue", "Playfair+Display:ital@1")

TONE KARARLARI:
- voice: 2-5 sıfat dizisi
- style: 2-4 sıfat dizisi
- forbidden: bu kanalda ASLA olmayacak 3-7 yaklaşım
- sentence_max_words: archetype'a göre 8-22 arası
- paragraph_sentences: [min, max], magazine için (5,7), tabloid için (2,3) gibi
- body_max_chars: 50 (kinetic) — 600 (magazine) arası
- headline_style_hint: bu kanalın tipik başlık formatı (1 cümle açıklama)

BANNER/HIGHLIGHT/CHIP:
- banner_shape: flat | ribbon | slanted | sharp (archetype'a en uygun)
- highlight_style: bg-flat | underline | marker | neon
- chip_style: rounded | sharp | pill

CATEGORY_ICON:
- 1 emoji veya kısa unicode (kanalın özünü temsil eden, örn. 💼 / 🎬 / ⚽ / 💻)

SEARCH_QUERY_TEMPLATE:
- DDG image search için, hangi field'ları kullanacağını belirtir
- Default: "{header_top} {header_bottom} {category}"
- Spor için: "{header_top} {category} football match"
- Tech için: "{header_top} technology"

ÇIKTI: SADECE aşağıdaki JSON formatında yanıtla, başka metin yazma:
{
  "archetype": "...",
  "palette": {"primary": "#...", "accent": "#...", "bg_gradient": ["#...","#..."],
              "body_bg": ["#...","#..."], "text_main": "#...", "text_muted": "#..."},
  "fonts": {"headline": "...", "body": "...", "google_imports": [...]},
  "tone": {"voice": "...", "style": "...", "forbidden": [...],
           "sentence_max_words": <int>, "paragraph_sentences": [<int>,<int>],
           "body_max_chars": <int>, "headline_style_hint": "..."},
  "banner_shape": "...",
  "highlight_style": "...",
  "chip_style": "...",
  "category_icon": "...",
  "search_query_template": "...",
  "persona_summary": "..."
}
```

### 6.3 CSS override (deterministik Python)

```python
def build_css_override(dna: DnaSpec) -> str:
    """Generate templates/css/<slug>.css. Pure Python, no LLM."""
    google = ""
    if dna.fonts.google_imports:
        google = "@import url('https://fonts.googleapis.com/css2?" + "&".join(
            f"family={x}" for x in dna.fonts.google_imports
        ) + "&display=swap');\n"
    
    p = dna.palette
    css = f"""{google}:root {{
  --primary: {p.primary};
  --accent: {p.accent};
  --bg-grad-1: {p.bg_gradient[0]};
  --bg-grad-2: {p.bg_gradient[1]};
  --body-bg-1: {p.body_bg[0]};
  --body-bg-2: {p.body_bg[1]};
  --text-main: {p.text_main};
  --text-muted: {p.text_muted};
  --font-headline: '{dna.fonts.headline}', sans-serif;
  --font-body: '{dna.fonts.body}', sans-serif;
}}
.header {{ {_banner_shape_css(dna.banner_shape)} }}
.body .hl-r {{ {_highlight_css(dna.highlight_style, p.primary, "#fff")} }}
.body .hl-y {{ {_highlight_css(dna.highlight_style, p.accent, "#000")} }}
.persistent {{ {_chip_css(dna.chip_style)} }}
"""
    return css
```

`_banner_shape_css`, `_highlight_css`, `_chip_css` helper'lar her stil seçeneği için CSS snippet döner.

### 6.4 CLI komutları

| Komut | Davranış |
|---|---|
| `short-bot create-channel --name "..." --language ... --keywords "..." --topic-hint "..." --target-audience "..."` | Opus DNA + CSS üretir, slug auto-derive (name'den), dosyaları yazar |
| `short-bot create-channel ... --force` | Var olan slug'ı üzerine yazar |
| `short-bot regenerate-dna --channel <slug>` | Aynı kanal için DNA + CSS yeniden üretir (yeni varyant) |
| `short-bot rebuild-css --channel <slug>` | YAML manuel düzenlendikten sonra CSS'i LLM'siz türetir |
| `short-bot migrate-channel --slug son-dakika [--with-dna]` | Eski schema'yı yeni schema'ya taşır; --with-dna ile DNA üretir |

## 7. Template + Render Entegrasyonu

### 7.1 Template iskeleti (her archetype)

```jinja
<!DOCTYPE html><html lang="{{ language }}">
<head><meta charset="utf-8">
<style>
  :root {
    /* fallback değişkenler — DNA override yoksa kullanılır */
    --primary: #c81e1e; --accent: #ffea3b; ...
  }
  /* archetype-specific layout (header/photo/body pozisyonları, animasyonlar) */
  .header { background: var(--primary); ... }
  .body { background: linear-gradient(180deg, var(--body-bg-1), var(--body-bg-2)); ... }
  ...

  /* === DNA OVERRIDE (varsa) === */
  {{ dna_css|safe }}
</style></head>
<body>
<div class="stage">
  <div class="stage-badge">{{ ui_breaking }}</div>
  
  {# archetype-specific markup #}
  ...
  
  <div class="persistent like"><span class="ic">❤️</span><span>{{ ui_like }}</span></div>
  <div class="persistent sub"><span class="ic">🔔</span><span>{{ ui_subscribe }}</span></div>
</div>
</body></html>
```

### 7.2 `RenderJob` güncellemesi

```python
@dataclass
class RenderJob:
    # mevcut alanlar +
    language: str
```

### 7.3 `build_html()` güncellemesi

```python
def build_html(job: RenderJob, template_path: Path, *,
               ui_labels: dict[str, str], dna_css: str = "") -> str:
    # ...
    return template.render(
        # mevcut context +
        language=job.language,
        ui_breaking=ui_labels["breaking"],
        ui_like=ui_labels["like"],
        ui_subscribe=ui_labels["subscribe"],
        ui_share=ui_labels["share"],
        dna_css=dna_css,
    )
```

### 7.4 7 archetype'ın layout farklılıkları

| Archetype | Header | Photo | Body | Highlight | Animasyon |
|---|---|---|---|---|---|
| newscast | Üstte kırmızı banner, 100px | 640px ortada, sarı bant | Dim koyu zemin, paragraph | bg-flat | Subtle |
| tabloid | Sarı zemin + kırmızı italic, eğri | Foto blur arka plan | Üst-orta'da büyük italic title | marker | Shake/jiggle |
| magazine | Beje zemin, serif başlık | Polaroid frame | Geniş margin, italic pull-quote | underline | Slow Ken Burns |
| kinetic | (yok) Dev rakam/kelime | Foto yok, solid bg | 1 kısa cümle altta | neon | Big number scale-in |
| dark-tech | `> ...` terminal-style | Foto blur + scanline | Monospace, code blocks | neon (cyan/magenta) | Type-on, glitch |
| stadium | Skor banner (GS 2-1 FB) | Stadyum/oyuncu foto | Score-cast kısa cümle | bg-flat | Slide-from-side |
| meme | Üst metin Impact | Karakter/foto | Alt metin Impact | (yok) | Bounce/zoom |

## 8. Script Writer Entegrasyonu

### 8.1 `ARCHETYPE_PROMPTS` (script_writer.py modül seviyesi)

```python
ARCHETYPE_PROMPTS = {
    "newscast": """
- header_top + header_bottom: 4-6 words total, formal, BIG capital news headline style
- photo_overlay: 2-5 words, key fact (number, decision, action)
- body_paragraph: 4-5 sentences, neutral journalistic tone
- highlights: red=warning/risk/casualty, yellow=stat/decision/key actor
- mood: breaking for crisis, neutral default, upbeat for positive resolution
""",
    "tabloid": """
- header_top: provocative question or exclamation (e.g., "REZALET!", "KİM YAPTI?", "SCHOCK!")
- header_bottom: short follow-up phrase
- photo_overlay: gossip-style claim ("İFŞA OLDU!" / "EXPOSED!")
- body_paragraph: 2-3 punchy sentences, sensational tone, "according to sources" style
- highlights: red=scandal, yellow=name/place
- mood: usually breaking
""",
    "magazine": """
- header_top: poetic 2-4 word title
- header_bottom: subtitle phrase or attribution
- photo_overlay: thoughtful sub-tagline
- body_paragraph: 5-7 sentences, elegant, descriptive, longer-form
- highlights: yellow=key idea, red sparingly
- mood: usually neutral or upbeat
""",
    "kinetic": """
- header_top: 1-2 PUNCHY words OR a number ("%47", "1 MİLYON", "ZERO")
- header_bottom: 1 short phrase OR empty
- photo_overlay: brief context (≤5 words)
- body_paragraph: 1-2 short sentences (max 80 chars total)
- highlights: 0-1, neon style
- mood: any, often upbeat for stat/insight
""",
    "dark-tech": """
- header_top: codified-style "> NEWS_DROP" or "[ALERT]"
- header_bottom: tech topic descriptor
- photo_overlay: 3-6 words technical claim
- body_paragraph: 3-4 sentences, factual, can include code/syntax-flavored terms
- highlights: green/cyan=key tech, red=vulnerability/risk
- mood: usually breaking for vulnerabilities, upbeat for releases
""",
    "stadium": """
- header_top: SCORE format ("GS 2-1 FB") OR action word ("GOL!", "BÜYÜK ZAFER")
- header_bottom: event/stage ("90+3", "FİNAL", "DERBİ")
- photo_overlay: dramatic moment description
- body_paragraph: 3-4 sentences, energetic sports-broadcast tone
- highlights: red=goal/wicket/critical event, yellow=player name/stat
- mood: breaking for last-minute, upbeat for victory
""",
    "meme": """
- header_top: TOP TEXT (Impact-meme style, ALL CAPS, ≤5 words)
- header_bottom: BOTTOM TEXT (≤5 words, punchline)
- photo_overlay: empty OR a short tag
- body_paragraph: 1 short caption (≤60 chars)
- highlights: 0-1, edgy
- mood: usually upbeat
""",
}
```

### 8.2 `build_script_prompt(item, body, channel)`

- Archetype-specific instruction inject
- `channel.dna.tone` varsa tone block inject (voice/style/forbidden/length)
- Language flag: "Output language: {LANGUAGE_NAMES[channel.language]}"
- Pydantic Script schema bound'ları korunur (defense-in-depth)

### 8.3 Image picker güncellemesi

```python
def build_search_query(script: Script, channel: ChannelConfig) -> str:
    template = (channel.dna.search_query_template if channel.dna
                else "{header_top} {header_bottom} {category}")
    return template.format(
        header_top=script.header_top,
        header_bottom=script.header_bottom,
        category=script.category,
        photo_overlay=script.photo_overlay,
    ).strip()
```

Search target dilde otomatik olur (script zaten o dilde üretildi).

## 9. Hata Yönetimi

### 9.1 Strateji

- **Create-channel:** fail-loud, partial state bırakma. Hata → kullanıcı düzeltir.
- **Runtime (Short koşumu):** fail-soft + log-loud (mevcut Phase 1 davranışı korunur).

### 9.2 Hata tablosu

| Yer | Hata | Davranış |
|---|---|---|
| `create-channel` | `--language` listede yok | CLI hata mesajı, çıkış |
| `create-channel` | `--slug` mevcut, `--force` yok | Hata, `--force` öner |
| `generate_dna` | Opus timeout | 2 retry (4s/8s backoff), sonra hata |
| `generate_dna` | Pydantic validation fail | 2 retry (önceki yanıtın hatasını prompt'a ekleyerek), sonra hata |
| `build_css_override` | Python exception | DNA YAML yazılmadan hata raporla |
| Disk write fail | OSError | Atomic temp+rename ile partial state önlenir |
| Runtime: template dosyası yok | FileNotFoundError | Run 'failed', açık raporla |
| Runtime: `templates/css/<slug>.css` yok | (DNA üretilmemiş) | Sessiz: `dna_css=""`, fallback'ler |
| Runtime: `UI_LABELS[language]` yok | KeyError | Run 'failed', "language not in UI_LABELS map" |
| Runtime: Script writer LLM bound aşımı | Pydantic ValidationError | retry (2x), sonra failed |

### 9.3 Migration (mevcut son-dakika)

- `language` alanı yoksa → varsayılan `tr`
- `dna` alanı yoksa → `template` neyse onu kullan, default fallback değerler
- `rss_locale` alanı varsa hâlâ desteklenir (backward-compat) ama `language` öncelikli
- `templates/default.html.j2` → `templates/newscast.html.j2` rename + loader'da `template: default` → `newscast` map
- `migrate-channel` komutu YAML schema'sını günceller, opsiyonel `--with-dna` ile Opus DNA üretir

## 10. Test Stratejisi

| Test dosyası | Kapsam | # test |
|---|---|---|
| `test_dna.py` | DnaSpec validation, prompt builder içeriği, `build_css_override` pure logic, `_banner_shape_css`/`_highlight_css`/`_chip_css` per-style coverage | ~10 |
| `test_locale.py` | RSS_LOCALES coverage, UI_LABELS keys eksiksiz mi (her dil için 4 key) | 3 |
| `test_config.py` (genişler) | language ↔ rss_locale auto-derive, DnaSpec yükleme, backward-compat (eski schema), language Literal validation | +5 |
| `test_script_writer.py` (genişler) | Archetype-specific prompt instruction inject, tone block inject, language inject, channel.dna=None davranışı | +6 |
| `test_image_picker.py` (genişler) | Search query template kullanımı, channel.dna varsa override | +2 |
| `test_renderer.py` (genişler) | Her archetype için 1 build_html testi (DNA varlığında doğru CSS inject) + 1 multi-language testi | +8 |
| `test_renderer_snapshot.py` (yeni, slow) | 7 archetype × 1 deterministic Script → PNG snapshot, < %5 diff | +7 |
| `test_cli_create_channel.py` | `create-channel` happy path (mock Opus), hata caseleri, `--force` flag, slug derivation | ~6 |
| `test_pipeline.py` (genişler) | Pipeline'a language ve dna geçiyor mu | +2 |
| `test_claude_cli.py` (genişler) | `--model` flag inject olur mu | +1 |

Yeni test toplamı: **~50** (mevcut 86 + yeni ≈ 135).

**Snapshot testleri:** `tests/fixtures/snapshots/<archetype>.png` altında commit'lenir (~50KB her biri = ~350KB toplam).

**Manuel kabul:**
- 3-4 kanal yarat (farklı archetype + dil), her birinden Short üret, yan yana izle
- Görsel açıdan kanallar ayırt edilebilmeli
- Her kanal kendi dilinde yazıyor olmalı
- Persistent chip etiketleri kanal diline uymalı

## 11. Bağımlılıklar

`pyproject.toml`'a yeni paket eklenmiyor. Sadece `claude_cli.run_json` `--model` flag desteği eklenir (subprocess argv'e bir parametre).

Sistem bağımlılıkları değişmiyor: ffmpeg, claude CLI, Playwright Chromium.

## 12. Çıkar Listesi (Out of Scope)

Bu spec tamamlandığında **dahil edilmeyen ama gelecekte eklenebilecek** özellikler:
- Yeni archetype eklenmesi (8., 9. archetype) — şu an hard-coded 7
- Per-channel music pool
- Per-channel SFX kit
- TTS / sesli anlatım
- RTL diller
- Audience analytics / engagement tracking
- Phase 2 web paneli (kanal yaratma formu, görsel preview, override fine-tuning) — ayrı spec

## 13. İlk Çalıştırma (Beklenen User Flow)

```bash
# Mevcut kanal aynen çalışır (backward-compat)
python -m short_bot run --channel son-dakika --max 1

# Yeni kanal yaratma
python -m short_bot create-channel \
    --name "Spor Short DE" \
    --language de \
    --keywords "Bundesliga,Bayern München,Champions League" \
    --topic-hint "Almanca futbol kanalı, hardcore taraftar"

# Output:
# ▸ Generating DNA via opus... (this takes ~30s)
# ▸ Selected archetype: stadium
# ▸ Palette: primary=#0a4d2a accent=#ffd700
# ▸ Fonts: headline=Bebas Neue body=Inter
# ▸ Wrote: config/channels/spor-short-de.yaml
# ▸ Wrote: templates/css/spor-short-de.css
# Channel 'spor-short-de' created. Try:
#   python -m short_bot run --channel spor-short-de --max 1

# İlk Short üret
python -m short_bot run --channel spor-short-de --max 1

# Beğenmediyseniz DNA'yı yeniden üret
python -m short_bot regenerate-dna --channel spor-short-de

# Manuel YAML düzenleme + sadece CSS rebuild
vim config/channels/spor-short-de.yaml   # palette.primary değiştir
python -m short_bot rebuild-css --channel spor-short-de

# Mevcut son-dakika'yı yeni schema'ya migrate
python -m short_bot migrate-channel --slug son-dakika --with-dna
```
