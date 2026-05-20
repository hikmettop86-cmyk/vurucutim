# VurucuTim Şablon Otomasyon Şartnamesi

> 1080×1920 dikey YouTube Shorts şablonu üretmek için tüm alanlar, değişkenler, kurallar.

## 1. Teknik Temeller

- **Boyut**: tam 1080×1920 px (9:16) — şablon `html, body { width: 1080px; height: 1920px; overflow: hidden; }` ile başlamalı
- **Format**: Jinja2 template (`templates/<archetype>.html.j2`) → Playwright headless Chromium tek-frame PNG → ffmpeg ile mp4
- **Animasyon**: CSS keyframe + Playwright `set_content(html, wait_until="networkidle")`. Tek statik frame yakalanır, mp4 boyunca aynı kare gösterilir. Tek istisna: `.progress` barı 0% → 100% animate eder (`animation: fill {{ duration_s }}s linear forwards;`).
- **Font**: Google Fonts `@import url(...)` head'inde çağrılır. Otomatik yüklenenler: Inter, Roboto, Montserrat, Lato, Open Sans, Bebas Neue, Anton, Oswald, Playfair Display, Source Serif 4, JetBrains Mono. Sistem fontları (Impact, Georgia) de çalışır.
- **Karakter set**: UTF-8 Türkçe diakritikleri tam (ç ğ ı ö ş ü)

## 2. Pipeline (LLM içerik akışı)

```
RSS feed (Google News topic-locale-locked)
  ↓
Aday haber listesi (skor + dedup)
  ↓
Claude script_writer (per-channel archetype prompt)
  ↓ → Script (Pydantic) ↓
Pexels bg foto/video (archetype-specific query pool)
  ↓
Jinja2.render(template, **context) → HTML
  ↓
Playwright screenshot → JPEG
  ↓
ffmpeg loop + audio + handle stamp → mp4
```

## 3. Script Modeli — LLM Tarafından Üretilen Alanlar

`Script` Pydantic model'i her Short için doldurulur. Tüm string alanlar zorunlu:

| Alan | Tip | Karakter limiti | Kullanım amacı |
|------|-----|----------------|----------------|
| `header_top` | str | **1-25 char** | Manşet üst satırı (ALLCAPS dostu, ana başlık) |
| `header_bottom` | str | **1-35 char** | Manşet alt satırı (devam/altyazı) |
| `photo_overlay` | str | **1-60 char** | Foto üzerinde sarı bant / büyük stat / kicker |
| `body_paragraph` | str | **min 30**, soft max ~350 char | Gövde paragrafı (LLM tarafından archetype'a göre 1-5 cümle) |
| `category` | str | 1-30 char | Top-right rozet / kategori chip ("EKONOMİ", "SPOR") |
| `highlights` | list[Highlight] | 0-4 öğe | `body_paragraph` içindeki birebir alt-string'leri sarar |
| `mood` | Literal | — | `"breaking"` / `"neutral"` / `"upbeat"` |

**Highlight yapısı**:
```python
{"text": "<body_paragraph içinden birebir alt-string>", "color": "red" | "yellow"}
```
Renderer otomatik olarak `<span class="hl-r">` (kırmızı bg) veya `<span class="hl-y">` (sarı bg) ile sarar.

## 4. Channel Veri — Per-Kanal Statik

Şablona dict olarak akar:

```python
colors = {
    "primary":   "#c81e1e",                   # ana marka rengi
    "primary_light": "#e84e3e",               # auto-hesaplanır (header gradient için)
    "accent":    "#ffea3b",                   # vurgu rengi
    "bg_gradient": ["#1a3b6b", "#0a1a3b"],    # foto/üst zemin gradient
}
handle    = "@son-dakika"
duration_s = 6                                 # progress bar süresi
language  = "tr"                               # tr/en/de
```

UI label'lar `ui_labels_for(language)` ile gelir:
`{{ ui_breaking }}` = "SON DAKİKA" / "BREAKING" / "EILMELDUNG"
`{{ ui_source }}` = "Kaynak" / "Source" / "Quelle"
`{{ ui_like }}`, `{{ ui_subscribe }}`, `{{ ui_share }}`

## 5. DNA — Kanal Stil DNA'sı (önerilir)

`{{ dna_css|safe }}` şablonun `<style>` başına gömülür ve şunları sağlar:

```css
@import url('https://fonts.googleapis.com/css2?...');

:root {
  --primary:        <hex>;
  --accent:         <hex>;
  --bg-grad-1:      <hex>;       /* foto zemin gradyan 1 */
  --bg-grad-2:      <hex>;       /* foto zemin gradyan 2 */
  --body-bg-1:      <hex>;       /* body alanı gradyan 1 */
  --body-bg-2:      <hex>;       /* body alanı gradyan 2 */
  --text-main:      <hex>;       /* ana metin */
  --text-muted:     <hex>;       /* handle, alt yazı */
  --font-headline:  '<font>', sans-serif;
  --font-body:      '<font>', sans-serif;
  --size-headline-top: <px>;     /* OPSİYONEL — kullanıcı slider'dan */
  --size-headline-bot: <px>;     /* OPSİYONEL — aynı */
}

.header { transform: skewY(-1deg); ... }    /* banner shape */

.body .hl-r { background: #c81e1e; color: #fff; padding: 2px 14px; ... }
.body .hl-y { background: #ffea3b; color: #000; ... }

/* Font override !important — şablonun hardcoded font'larını ezer */
html, body, .body, .handle, .stage {
  font-family: '<body>', sans-serif !important;
}
.header, .header .top, .header .bot, .stage-badge, h1, h2, h3 {
  font-family: '<headline>', sans-serif !important;
}

.persistent { border-radius: 12px !important; }    /* chip shape */

/* Channel custom_css (Opus tarafından üretilmiş özel düzenlemeler) */
{custom_css}

/* Readability safety net */
.header .top, .header .bot { -webkit-text-fill-color: currentColor !important; ... }
```

**Şablon, `--text-main` / `--text-muted` / `--body-bg-1/2` vars'ını `var(..., fallback)` ile tüketmeli** — yoksa kanal renkleri uygulanmaz.

## 6. Şablona Akan Tüm Jinja Değişkenleri

```python
{
    "script": Script(...),                    # .header_top, .header_bottom, .photo_overlay,
                                              # .body_paragraph, .highlights, .category, .mood

    "body_html": "...<span class=\"hl-r\">vurgu</span>...",  # highlight-wrapped, |safe

    "colors": {"primary", "accent", "primary_light", "bg_gradient": [.., ..]},

    "bg_image_url": "data:image/jpeg;base64,..." | None,  # base64 data URL

    "handle": "@kanal-slug",
    "duration_s": 6,
    "language": "tr",

    "cta": {
        "enabled": False,
        "text": "BEĞEN · ABONE OL",
        "icons": ["❤️", "🔔", "↗️"],
        "duration_s": 4,
        "show_handle": False,
    },

    "ui_breaking":   "SON DAKİKA",
    "ui_source":     "Kaynak",
    "ui_like":       "BEĞEN",
    "ui_subscribe":  "ABONE OL",
    "ui_share":      "PAYLAŞ",

    "dna_css": "@import ...; :root {...}; ...",   # şablonun <style> içine basılır

    "category": "EKONOMİ",

    "rss_source": "Reuters" | None,               # opsiyonel alt-köşe credit

    "animation_style": "fade-up" | "slide-in" | "zoom-in" | "typewriter" | "none",
}
```

## 7. Şablon Zorunlu Yapı — Boilerplate

```jinja
<!DOCTYPE html>
<html lang="{{ language }}">
<head>
<meta charset="utf-8">
<title>Short — <ARCHETYPE_NAME></title>
<style>
  /* 1. Google Fonts import */
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');

  /* 2. DNA override (zorunlu) */
  {{ dna_css|safe }}

  /* 3. Reset + viewport (zorunlu) */
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { width: 1080px; height: 1920px; overflow: hidden;
    font-family: 'Inter', sans-serif;
    color: var(--text-main, #fff);
    background: linear-gradient(180deg, var(--body-bg-1, #1a1a2a), var(--body-bg-2, #0a0a1a)); }

  .stage { position: relative; width: 1080px; height: 1920px;
    display: flex; flex-direction: column; }

  /* 4. Şablonun kendi CSS'i */
  .header { ... }
  .photo  { ... }
  .body   { ... }

  /* 5. STANDART ALT ÖĞELER (zorunlu) */
  .progress { position: absolute; left: 0; right: 0; bottom: 84px; height: 6px;
              background: rgba(255,255,255,.18); z-index: 11; }
  .progress::after { content: ''; position: absolute; left: 0; top: 0; bottom: 0;
              background: var(--accent, #ffea3b);
              animation: fill {{ duration_s }}s linear forwards; }
  @keyframes fill { from { width: 0; } to { width: 100%; } }

  .handle { position: absolute; left: 0; right: 0; bottom: 30px;
            text-align: center; font-size: 32px; font-weight: 600;
            color: var(--text-muted, #fff); }

  .source-credit { position: absolute; bottom: 6px; left: 50%;
              transform: translateX(-50%);
              background: rgba(0,0,0,.6); color: rgba(255,255,255,.85);
              font-size: 14px; padding: 3px 10px; border-radius: 3px;
              z-index: 50; white-space: nowrap; }
</style>
</head>
<body>
<div class="stage dna-anim-{{ animation_style|default('none') }}">

  {% if script.category %}<div class="stage-badge">{{ ui_breaking }}</div>{% endif %}

  <div class="header">
    <span class="top">{{ script.header_top }}</span>
    <span class="bot">{{ script.header_bottom }}</span>
  </div>

  <div class="photo">
    <div class="bg-img" style="background-image: url('{{ bg_image_url|default("") }}');
         {% if not bg_image_url %}display: none;{% endif %}"></div>
    {% if script.photo_overlay %}<div class="yellow">{{ script.photo_overlay }}</div>{% endif %}
  </div>

  <div class="body">
    <div class="body-text" data-fit-min="36" data-fit-max="48" data-fit-pad="20">
      {{ body_html|safe }}
    </div>
  </div>

  <div class="progress"></div>
  <div class="handle">{{ handle }}</div>
  {% if rss_source %}<div class="source-credit">{{ ui_source }}: {{ rss_source }}</div>{% endif %}
</div>

{% include "_auto_fit.js.j2" %}
</body>
</html>
```

## 8. Auto-Fit JS (font-size auto-shrink)

`{% include "_auto_fit.js.j2" %}` 3 mode destekler:

### a) Body height-fit (zorunlu)
`.body-text` (veya `.body`) elementinde:
- `data-fit-min` (px) — minimum font-size
- `data-fit-max` (px) — maksimum font-size (başlangıç)
- `data-fit-pad` (px) — alt boşluk reserve

JS, fontlar yüklendikten sonra text container'ı geçtikçe font-size'ı 2px adımlarla küçültür.

### b) Width-fit (uzun manşet için)
- `data-fit-width="<pad-px>"` (mode aktif eder)
- `data-fit-min`, `data-fit-max` — sınırlar

Yatay overflow olunca shrinkler. Stadium'da uzun takım isimleri için kullanılır.

### c) List-fit (sıralı liste için)
`.list-container[data-fit-min]` ise içindeki tüm `.list-item .text` elemanları aynı font-size'a hizalanır.

## 9. Image Slot (`bg_image_url`)

- **Tip**: `data:image/jpeg;base64,...` (Playwright `about:blank` origin'de `file://` çalışmaz, inline base64 zorunlu)
- **Source**: Pexels API'den archetype-specific query pool ile çekilir, ya da kullanıcı UI'da yükler
- **Boş ise**: `bg_image_url = None`. Şablon `{% if not bg_image_url %}display: none;{% endif %}` ile gradient fallback gösterir.
- **Kullanım**:
  ```jinja
  <div class="bg-img" style="background-image: url('{{ bg_image_url|default("") }}');
       {% if not bg_image_url %}display: none;{% endif %}"></div>
  ```

## 10. Pydantic Validasyon

```python
class Script(BaseModel):
    header_top:     str = Field(min_length=1, max_length=25)
    header_bottom:  str = Field(min_length=1, max_length=35)
    photo_overlay:  str = Field(min_length=1, max_length=60)
    body_paragraph: str = Field(min_length=30, max_length=800)
    highlights:     list[Highlight] = Field(default_factory=list, max_length=4)
    category:       str = Field(min_length=1, max_length=30)
    mood:           Literal["breaking", "neutral", "upbeat"]

class Highlight(BaseModel):
    text:  str
    color: Literal["red", "yellow"]
```

LLM çıktısı bu schema'ya valide edilir, limitlere uymayan response retry ile yeniden istenir.

**Şablon farklı bir veri yapısı bekliyorsa** (örn. liste, karşılaştırma, çoklu öğe) → `body_paragraph` içine kuralcı format yerleştirip Jinja'da parse edilir (örn. `"ITEM A | ITEM B | ITEM C"` → `body_paragraph.split('|')`).

## 11. Yeni Şablon Eklendiğinde — Otomatik Pipeline Kaydı

Bir yeni `templates/<slug>.html.j2` eklediğinde **6 yerde** kayıt:

| Dosya | Değişiklik |
|-------|-----------|
| `src/short_bot/dna.py` | `ARCHETYPES` listesine `"<slug>"` ekle |
| `src/short_bot/dna.py` | `ARCHETYPE_DEFAULTS["<slug>"] = {...}` palette+fonts default |
| `src/short_bot/dna.py` | `DnaSpec.archetype` Literal'ına `"<slug>"` ekle |
| `src/short_bot/script_writer.py` | `ARCHETYPE_PROMPTS["<slug>"] = "..."` LLM prompt |
| `src/short_bot/templates_config.py` | `ARCHETYPE_OVERFLOW_FIELDS["<slug>"] = [...]` overflow check selectors |
| `src/short_bot/pexels.py` | `ARCHETYPE_BG_QUERIES["<slug>"] = [...]` Pexels query pool |

Test dosyaları (`tests/test_dna.py`, `tests/test_pexels.py`, `tests/test_script_writer.py`, `tests/test_overflow_config.py`) archetype sayısını da güncellemeli.

## 12. Mevcut 4 Şablon — Çalışan Referanslar

```
templates/newscast.html.j2    → Genel haber: kırmızı header + photo band + dark body
templates/stadium.html.j2     → Spor: büyük takım adı + sarı chip overlay + dark body
templates/stat-hero.html.j2   → İstatistik: dev sayı (auto-extracted) + caption
templates/bigquote.html.j2    → Tek alıntı: büyük tırnak işaretleri + attribution
```

Hepsi 1080×1920, DNA-aware CSS vars kullanıyor. Yeni şablon yazarken **bu 4'ünü örnek olarak incele**.

## 13. Claude Design'a Verilecek Prompt — Örnek

> "VurucuTim YouTube Shorts otomasyonu için 1080×1920 dikey Jinja2 şablonu tasarla.
>
> **Data slotları**:
> - `script.header_top` (max 25 char) — manşet üst
> - `script.header_bottom` (max 35 char) — manşet alt
> - `script.photo_overlay` (max 60 char) — vurgu/stat kicker
> - `script.body_paragraph` (max 300 char) — gövde
> - `script.category` (max 30 char) — kategori chip
> - `script.highlights` body içinde `<span class="hl-r">` veya `<span class="hl-y">` ile sarılı gelir
>
> **CSS değişkenleri** (zorunlu kullanım):
> `--primary`, `--accent`, `--text-main`, `--text-muted`, `--bg-grad-1/2`, `--body-bg-1/2`, `--font-headline`, `--font-body`, opsiyonel `--size-headline-top/bot`
>
> **Şablon stili**: <buraya istediğin görsel tema — örn. "magazine editorial light-mode", "viral neon dark", "60s tabloid">
>
> **Zorunlu öğeler**: `.progress` barı, `.handle` (alt orta), `.source-credit` (en alt), `dna_css` `<style>` içinde, `_auto_fit.js.j2` body sonunda
>
> **bg_image_url**: foto slot, boşken `display: none` ile gradient fallback
>
> **Auto-fit**: body-text'e `data-fit-min/max/pad` ekle (uzun başlıklar için `data-fit-width` de eklenebilir)
>
> Çıktı: tek `.html.j2` dosyası, 1080×1920 px sabit boyut, hardcoded font fallback'leri DNA override ile ezilebilir olacak."

---

## Yardımcı Dosyalar

- **Mevcut şablonlar**: `templates/newscast.html.j2`, `stadium.html.j2`, `stat-hero.html.j2`, `bigquote.html.j2`
- **Auto-fit JS**: `templates/_auto_fit.js.j2`
- **Animation CSS**: `templates/css/_animations.css`
- **Models**: `src/short_bot/models.py` (Script, Highlight)
- **DNA**: `src/short_bot/dna.py` (DnaSpec, DnaPalette, DnaFonts, build_css_override)
- **Renderer**: `src/short_bot/renderer.py` (`build_html(job, template_path, ...)`)
