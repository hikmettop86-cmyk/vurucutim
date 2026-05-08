"""Channel DNA: Pydantic models for visual + content identity (archetype + palette + tone)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from short_bot.claude_cli import run_json
from short_bot.locale import LANGUAGE_NAMES


ARCHETYPES = [
    "newscast", "tabloid", "magazine", "kinetic", "dark-tech", "stadium", "meme",
    "politika", "ekonomi", "spor-haber", "tech-haber",
    "hava-durumu", "yerel", "gundem", "dosya",
]


# Default visual palette + fonts per archetype.
# Used by /api/dna/defaults when user changes archetype in the edit UI — palette
# auto-snaps to the new archetype's signature look so live-preview reflects it.
ARCHETYPE_DEFAULTS: dict[str, dict] = {
    "newscast": {
        "primary": "#bb1f1f", "accent": "#ffd54a",
        "bg_grad_1": "#0a0a0a", "bg_grad_2": "#1a1a1a",
        "body_bg_1": "#101010", "body_bg_2": "#1f1f1f",
        "text_main": "#ffffff", "text_muted": "#cccccc",
        "font_headline": "Inter", "font_body": "Inter",
    },
    "tabloid": {
        "primary": "#e8141a", "accent": "#fff100",
        "bg_grad_1": "#000000", "bg_grad_2": "#2a0000",
        "body_bg_1": "#0a0000", "body_bg_2": "#220000",
        "text_main": "#ffffff", "text_muted": "#ffd1d1",
        "font_headline": "Bebas Neue", "font_body": "Inter",
    },
    "magazine": {
        "primary": "#1a1a1a", "accent": "#c2185b",
        "bg_grad_1": "#f7f3ee", "bg_grad_2": "#e8e0d4",
        "body_bg_1": "#f7f3ee", "body_bg_2": "#ffffff",
        "text_main": "#1a1a1a", "text_muted": "#5b5249",
        "font_headline": "Playfair Display", "font_body": "Lora",
    },
    "kinetic": {
        "primary": "#ff3366", "accent": "#00f0ff",
        "bg_grad_1": "#1b1340", "bg_grad_2": "#0d0820",
        "body_bg_1": "#1b1340", "body_bg_2": "#0d0820",
        "text_main": "#ffffff", "text_muted": "#b8a8f0",
        "font_headline": "Anton", "font_body": "Inter",
    },
    "dark-tech": {
        "primary": "#00d4ff", "accent": "#7c4dff",
        "bg_grad_1": "#0a0e1a", "bg_grad_2": "#141a2e",
        "body_bg_1": "#0e1322", "body_bg_2": "#1a2138",
        "text_main": "#e6f0ff", "text_muted": "#7a8bb0",
        "font_headline": "JetBrains Mono", "font_body": "Inter",
    },
    "stadium": {
        "primary": "#a30d2d", "accent": "#ffb81c",
        "bg_grad_1": "#0a0a0a", "bg_grad_2": "#3d0712",
        "body_bg_1": "#12060a", "body_bg_2": "#1f0810",
        "text_main": "#fff8e7", "text_muted": "#e8c56a",
        "font_headline": "Oswald", "font_body": "Inter",
    },
    "meme": {
        "primary": "#ff4500", "accent": "#ffeb3b",
        "bg_grad_1": "#1a1a1a", "bg_grad_2": "#0a0a0a",
        "body_bg_1": "#ffffff", "body_bg_2": "#f0f0f0",
        "text_main": "#000000", "text_muted": "#444444",
        "font_headline": "Impact", "font_body": "Inter",
    },
    # ── New archetypes ──────────────────────────────────────────────────
    "politika": {
        "primary": "#0a1c4a", "accent": "#d4a937",
        "bg_grad_1": "#0a1c4a", "bg_grad_2": "#05102a",
        "body_bg_1": "#0a1c4a", "body_bg_2": "#0e2358",
        "text_main": "#f5ecd6", "text_muted": "#c9a850",
        "font_headline": "Source Serif 4", "font_body": "Source Serif 4",
    },
    "ekonomi": {
        "primary": "#003b2a", "accent": "#00c853",
        "bg_grad_1": "#001f17", "bg_grad_2": "#003b2a",
        "body_bg_1": "#001f17", "body_bg_2": "#002c1f",
        "text_main": "#ffffff", "text_muted": "#9ad9b5",
        "font_headline": "Inter", "font_body": "JetBrains Mono",
    },
    "spor-haber": {
        "primary": "#0a0a0a", "accent": "#39ff14",
        "bg_grad_1": "#0a0a0a", "bg_grad_2": "#1a0a0a",
        "body_bg_1": "#0a0a0a", "body_bg_2": "#141414",
        "text_main": "#ffffff", "text_muted": "#a8ffa8",
        "font_headline": "Oswald", "font_body": "Inter",
    },
    "tech-haber": {
        "primary": "#1d1d1f", "accent": "#0066cc",
        "bg_grad_1": "#fbfbfd", "bg_grad_2": "#f5f5f7",
        "body_bg_1": "#ffffff", "body_bg_2": "#f5f5f7",
        "text_main": "#1d1d1f", "text_muted": "#86868b",
        "font_headline": "Inter", "font_body": "Inter",
    },
    "hava-durumu": {
        "primary": "#3a7bd5", "accent": "#ffd23f",
        "bg_grad_1": "#3a7bd5", "bg_grad_2": "#00d2ff",
        "body_bg_1": "#3a7bd5", "body_bg_2": "#5dabec",
        "text_main": "#ffffff", "text_muted": "#e6f4ff",
        "font_headline": "Inter", "font_body": "Inter",
    },
    "yerel": {
        "primary": "#8b4513", "accent": "#d2691e",
        "bg_grad_1": "#faf0e0", "bg_grad_2": "#f0d9b5",
        "body_bg_1": "#faf0e0", "body_bg_2": "#fff8eb",
        "text_main": "#3a2810", "text_muted": "#7a5a35",
        "font_headline": "Playfair Display", "font_body": "Lora",
    },
    "gundem": {
        "primary": "#1e1645", "accent": "#ffeb3b",
        "bg_grad_1": "#1e1645", "bg_grad_2": "#0e0a25",
        "body_bg_1": "#1e1645", "body_bg_2": "#28194e",
        "text_main": "#ffffff", "text_muted": "#ffeb3b",
        "font_headline": "Anton", "font_body": "Inter",
    },
    "dosya": {
        "primary": "#5a3a20", "accent": "#a52a2a",
        "bg_grad_1": "#f4ecd8", "bg_grad_2": "#e8d8b0",
        "body_bg_1": "#f4ecd8", "body_bg_2": "#fff7e0",
        "text_main": "#2a1a08", "text_muted": "#6a4a25",
        "font_headline": "Source Serif 4", "font_body": "Source Serif 4",
    },
}


class DnaPalette(BaseModel):
    primary: str
    accent: str
    bg_gradient: list[str] = Field(min_length=2, max_length=2)
    body_bg: list[str] = Field(min_length=2, max_length=2)
    text_main: str = "#ffffff"
    text_muted: str = "#cccccc"
    # Optional explicit overrides for the headline. Empty string = inherit from
    # template (top → accent, bot → text_main). Non-empty must be #RRGGBB.
    header_top_color: str = ""
    header_bottom_color: str = ""

    @field_validator("primary", "accent", "text_main", "text_muted")
    @classmethod
    def _validate_hex(cls, v: str) -> str:
        if not (v.startswith("#") and len(v) == 7):
            raise ValueError(f"Invalid hex color: {v!r} (expected #RRGGBB)")
        try:
            int(v[1:], 16)
        except ValueError as e:
            raise ValueError(f"Invalid hex color: {v!r}") from e
        return v.lower()

    @field_validator("header_top_color", "header_bottom_color")
    @classmethod
    def _validate_optional_hex(cls, v: str) -> str:
        if v == "":
            return v
        if not (v.startswith("#") and len(v) == 7):
            raise ValueError(f"Invalid hex color: {v!r} (expected #RRGGBB or empty)")
        try:
            int(v[1:], 16)
        except ValueError as e:
            raise ValueError(f"Invalid hex color: {v!r}") from e
        return v.lower()


class DnaFonts(BaseModel):
    headline: str = "Inter"
    body: str = "Inter"
    google_imports: list[str] = Field(default_factory=list)


class DnaTone(BaseModel):
    voice: str = Field(min_length=1, max_length=200)
    style: str = Field(min_length=1, max_length=200)
    forbidden: list[str] = Field(default_factory=list, max_length=10)
    sentence_max_words: int = Field(ge=4, le=40, default=18)
    paragraph_sentences: tuple[int, int] = (3, 5)
    body_max_chars: int = Field(ge=50, le=800, default=350)
    headline_style_hint: str = Field(default="", max_length=200)


class DnaSpec(BaseModel):
    archetype: Literal[
        "newscast", "tabloid", "magazine", "kinetic", "dark-tech", "stadium", "meme",
        "politika", "ekonomi", "spor-haber", "tech-haber",
        "hava-durumu", "yerel", "gundem", "dosya",
    ]
    palette: DnaPalette
    fonts: DnaFonts
    tone: DnaTone
    banner_shape: Literal["flat", "ribbon", "slanted", "sharp"] = "flat"
    highlight_style: Literal["bg-flat", "underline", "marker", "neon"] = "bg-flat"
    chip_style: Literal["rounded", "sharp", "pill"] = "rounded"
    category_icon: str = ""
    search_query_template: str = "{header_top} {header_bottom} {category}"
    persona_summary: str = Field(max_length=400)
    custom_css: str = Field(default="", max_length=8000)
    ui_badge: str = Field(default="", max_length=24)


def build_dna_prompt(
    name: str,
    keywords: list[str],
    language: str,
    topic_hint: str = "",
    target_audience: str = "",
) -> str:
    lang_name = LANGUAGE_NAMES.get(language, language)
    return f"""Sen bir YouTube Shorts kanalının görsel/içerik kimliğini (DNA) tasarlıyorsun.

KANAL BİLGİLERİ:
- İsim: {name}
- Dil: {lang_name}
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
- politika → resmi siyaset, parlamento, hükümet açıklamaları (formal/oturmuş)
- ekonomi → borsa, döviz, zam, ekonomik göstergeler (sayısal callout)
- spor-haber → transfer/sakatlık/fikstür/taktik (jurnalistik, stadium'dan farklı)
- tech-haber → Apple/Google/AI/bilim haberleri (clean Apple-keynote, dark-tech'ten farklı)
- hava-durumu → günlük hava raporu (sıcaklık+emoji ön planda)
- yerel → şehir/mahalle haberleri (sıcak, küçük-ölçekli)
- gundem → günün top 3-4 haberi liste halinde
- dosya → soruşturma/araştırmacı gazetecilik (sepia eski-belge estetik)

DİL UYUMU:
- voice/style/forbidden alanlarını {lang_name} dilinde yaz
- headline_style_hint da o dilde
- persona_summary tamamen o dilde, MAX 400 karakter (1-2 kısa cümle)

PALETTE KARARLARI (archetype'a uygun ama kanala özgü override yapabilirsin):
- newscast: kırmızı/lacivert/altın
- tabloid: sarı/kırmızı/siyah, yüksek kontrast
- magazine: bej/krem/burgundy/altın, sıcak
- kinetic: tek vurgu rengi (neon yeşil/mor/mavi) + siyah
- dark-tech: cyan/magenta/yeşil neon + koyu mor/siyah
- stadium: takım/spor renkleri (yeşil/sarı, kırmızı/lacivert vb.)
- meme: parlak mavi/sarı/pembe, Impact-vibe
- politika: lacivert (#0a1c4a) + altın (#d4a937), formal
- ekonomi: koyu mavi-yeşil + market yeşili (#00c853) + market kırmızı (#d50000) + altın
- spor-haber: charcoal + soft-red (#e63946) + cool-gray (stadium'dan daha yumuşak)
- tech-haber: BEYAZ arkaplan + electric blue (#0066cc) + Apple charcoal (#1d1d1f)
- hava-durumu: gökyüzü mavi gradient (#3a7bd5 → #00d2ff) + güneş sarısı
- yerel: krem (#fef3e2) + terracotta (#c9663b) + zeytin (#6b7d3a)
- gundem: deep purple (#1e1645) + bright yellow (#ffeb3b)
- dosya: sepia paper (#f4ecd8) + rust red (#a52a2a) + ink black

FONT KARARLARI:
- headline: archetype'a uygun (newscast→Inter, tabloid→Bebas Neue,
  magazine→Playfair Display, kinetic→Anton, dark-tech→JetBrains Mono,
  stadium→Oswald, meme→Impact, politika→Source Serif 4, ekonomi→Inter,
  spor-haber→Oswald, tech-haber→Inter, hava-durumu→Inter Display,
  yerel→Playfair Display, gundem→Anton, dosya→Source Serif 4)
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

ARCHETYPE-SPESİFİK FORMAT KURALLARI:
- gundem: body_paragraph'ı şu formatta yaz: "1. <başlık>\n2. <başlık>\n3. <başlık>"
  (3-4 madde, her madde 8-15 kelime). \n karakteri gerçek satırbaşı (Python'da yeni
  satır), markup değil.
- hava-durumu: header_top = sıcaklık (örn. "23°"), header_bottom = hava emojisi
  veya kısa açıklama (örn. "GÜNEŞLİ"), photo_overlay = şehir adı (örn. "İSTANBUL"),
  body_paragraph = kısa hava özeti (50-100 karakter).

BANNER/HIGHLIGHT/CHIP:
- banner_shape: flat | ribbon | slanted | sharp
- highlight_style: bg-flat | underline | marker | neon
- chip_style: rounded | sharp | pill

CATEGORY_ICON:
- 1 emoji veya kısa unicode (örn. 💼 / 🎬 / ⚽ / 💻)

UI_BADGE (sahnenin tepesindeki kısa rozet metni — max 24 karakter):
- Kanalın temasına UYGUN kısa, çağrıştırıcı bir rozet yaz
- HABER kanalı DEĞİLSE "SON DAKİKA" / "BREAKING" yazma — anlamsız olur
- Örnekler:
  * Aşk/sevgi → "❀ AŞK SÖZLERİ ❀" / "GÜNÜN SÖZÜ"
  * Motivasyon → "GÜNÜN İLHAMI" / "▲ MOTİVASYON ▲"
  * Spor → "MAÇ HABERİ" / "⚽ SPOR ⚽"
  * Teknoloji → "TECH" / "▣ HABER ▣"
  * Tarih → "TARİHTE BUGÜN"
  * Mizah → "GÜNÜN MEMESİ"
  * Resmi haber → kanal dilindeki "SON DAKİKA" karşılığı
- Boş bırakma; en uygun olanı seç. Dil: {lang_name}

SEARCH_QUERY_TEMPLATE:
- DDG image search format string
- Default: "{{header_top}} {{header_bottom}} {{category}}"
- Spor için: "{{header_top}} {{category}} football match"
- Tech için: "{{header_top}} technology"

ÖZGÜR CSS (custom_css):
Yapısal alanları (palette, fonts, banner_shape, vb.) yukarıda doldurduktan sonra,
kanala özel görsel zenginlik için ek bir CSS bloğu yaz.

⚠️ OKUNABILIRLIK ZORUNLU KURALLARI (KESİNLİKLE UYULACAK — istisna yok):
1. BAŞLIK (.header .top, .header .bot) text rengi SOLİD olmalı:
   - YASAK: -webkit-text-fill-color: transparent + background-clip: text kombinasyonu
     (yani "gradient text" — harfler içi boş, koyu zeminde okunmaz)
   - YASAK: -webkit-text-stroke .header .top ve .header .bot selector'larında
     (stroke + transparent fill = bulanık başlık)
   - İZİNLİ: solid color + MAKS 1 adet basit text-shadow (örn. 0 2px 8px rgba(0,0,0,0.6))
2. BACKGROUND katmanı MAKS 2 (1 ana gradient + 1 dekoratif overlay).
   Birden fazla radial + repeating-linear + ::before + ::after kombinasyonu YASAK
   (görsel gürültü).
3. box-shadow per-element MAKS 2 katman (virgülle ayrılmış 2'yi geçmesin).
4. RENK PALETİ: custom_css içinde palette'de OLMAYAN yeni renk tanıtma. Sadece
   primary, accent, text_main, text_muted, body_bg ve bunların alpha varyasyonları.
5. .body arkaplanı solid veya ≥90% opaque (rgba(...,0.9) veya üstü) olmalı —
   yarı saydam zeminde gövde metni okunmuyor.

✓ İZİNLİ:
- background-image / pattern (body, .stage) — MAKS 1 katman, kuraldaki limitlere uy
- ::before / ::after dekoratif elementler (HER selector için)
- gradient text — YALNIZCA dekoratif elementlerde (.body::first-letter, ::before
  içeriği gibi). Başlık/gövde ana metninde ASLA.
- filter / mix-blend-mode / border-radius
- photo treatment (.photo border, mask, filter, MAKS 1 box-shadow)
- chip dekorasyonu (.persistent ::before/::after, decorative borders)
- Custom @keyframes (sadece YENİ dekoratif elementler için)

✗ YASAKLI (KESİNLİKLE DOKUNMA — render bozar):
- position / top / bottom / left / right / width / height değerleri
  .header, .body, .persistent, .progress, .handle, .stage selector'larında
- z-index 100'den büyük (CTA layer çakışmaması için)
- mevcut @keyframes'leri (fill, ken-burns vb) override etme

ÖRNEK:
- Magazine: bg radial-gradient + .photo polaroid frame + .body italic
- Tech: bg scanline pattern + .header text-stroke + .persistent neon glow
- Romance: bg pink gradient + heart pattern overlay + script font shadow

Çıktı: 1500-3000 karakter arası ham CSS, başka açıklama yazma. Boş bırakma.

ÇIKTI: SADECE aşağıdaki JSON formatında yanıtla, başka metin yazma:
{{
  "archetype": "...",
  "palette": {{"primary": "#...", "accent": "#...", "bg_gradient": ["#...","#..."],
              "body_bg": ["#...","#..."], "text_main": "#...", "text_muted": "#..."}},
  "fonts": {{"headline": "...", "body": "...", "google_imports": [...]}},
  "tone": {{"voice": "...", "style": "...", "forbidden": [...],
           "sentence_max_words": <int>, "paragraph_sentences": [<int>,<int>],
           "body_max_chars": <int>, "headline_style_hint": "..."}},
  "banner_shape": "...",
  "highlight_style": "...",
  "chip_style": "...",
  "category_icon": "...",
  "search_query_template": "...",
  "persona_summary": "<1-2 cümle, max 400 karakter>",
  "custom_css": "<1500-3000 karakter ham CSS>",
  "ui_badge": "<kısa rozet metni, max 24 char>"
}}
"""


def generate_dna(
    *,
    name: str,
    keywords: list[str],
    language: str,
    topic_hint: str = "",
    target_audience: str = "",
    claude_path: str = "claude",
    model: str = "opus",
) -> DnaSpec:
    prompt = build_dna_prompt(name, keywords, language, topic_hint, target_audience)
    return run_json(
        prompt, DnaSpec,
        claude_path=claude_path, model=model,
        retries=2, timeout_s=180,
    )


def _banner_shape_css(shape: str) -> str:
    """Return CSS rule string for the given banner shape."""
    return {
        "flat":    "border-radius: 0; clip-path: none;",
        "ribbon":  "clip-path: polygon(0 0, 100% 0, 100% 80%, 50% 100%, 0 80%);",
        "slanted": "transform: skewY(-1deg); transform-origin: top left;",
        "sharp":   "clip-path: polygon(0 0, 100% 0, 95% 100%, 5% 100%);",
    }.get(shape, "")


def _highlight_css(style: str, bg_color: str, fg_color: str) -> str:
    """Return CSS rule string for the given highlight style."""
    if style == "bg-flat":
        return f"background: {bg_color}; color: {fg_color}; padding: 2px 14px; border-radius: 6px; font-weight: 700;"
    if style == "underline":
        return f"color: {bg_color}; text-decoration: underline; text-decoration-thickness: 6px; text-underline-offset: 4px; font-weight: 700;"
    if style == "marker":
        return f"background: linear-gradient(180deg, transparent 50%, {bg_color} 50%); color: {fg_color}; padding: 0 8px; font-weight: 700;"
    if style == "neon":
        return f"color: {bg_color}; text-shadow: 0 0 8px {bg_color}, 0 0 16px {bg_color}; font-weight: 700;"
    return ""


def _chip_css(style: str) -> str:
    """Return CSS rule string for the given chip style (border-radius only)."""
    return {
        "rounded": "border-radius: 12px;",
        "sharp":   "border-radius: 2px;",
        "pill":    "border-radius: 999px;",
    }.get(style, "border-radius: 12px;")


_GOOGLE_FONT_PARAM: dict[str, str] = {
    # Sans-serif
    "Inter": "Inter:wght@400;500;600;700;900",
    "Roboto": "Roboto:wght@400;700;900",
    "Montserrat": "Montserrat:wght@400;700;900",
    "Lato": "Lato:wght@400;700;900",
    "Open Sans": "Open+Sans:wght@400;700",
    # Display / Headline
    "Bebas Neue": "Bebas+Neue",
    "Anton": "Anton",
    "Oswald": "Oswald:wght@400;600;700",
    "Impact": "",   # system font, no Google import needed
    # Serif
    "Playfair Display": "Playfair+Display:ital,wght@0,400;0,700;1,400;1,700",
    "Source Serif 4": "Source+Serif+4:wght@400;600;700",
    "Georgia": "",  # system font
    # Mono
    "JetBrains Mono": "JetBrains+Mono:wght@400;700",
}


def _sanitize_custom_css_colors(css: str, palette: DnaPalette) -> str:
    """Replace hardcoded hex/rgba colors in custom_css that match palette values
    with var(--xxx) references (rgba alpha preserved via color-mix), so live
    palette pickers actually take effect.

    Priority when multiple palette fields share the same hex:
    text-main > text-muted > primary > accent > bg-grad > body-bg.
    """
    import re

    hex_to_var: dict[str, str] = {}

    def add(hex_value: str, var_name: str) -> None:
        if hex_value and hex_value.startswith('#') and len(hex_value) == 7:
            hex_to_var.setdefault(hex_value.lower(), f'var(--{var_name})')

    # Highest priority first
    add(palette.text_main, 'text-main')
    add(palette.text_muted, 'text-muted')
    add(palette.primary, 'primary')
    add(palette.accent, 'accent')
    for i, v in enumerate(palette.bg_gradient, 1):
        add(v, f'bg-grad-{i}')
    for i, v in enumerate(palette.body_bg, 1):
        add(v, f'body-bg-{i}')

    if not hex_to_var:
        return css

    def replace_hex(m):
        return hex_to_var.get(m.group(0).lower(), m.group(0))

    css = re.sub(r'#[0-9a-fA-F]{6}\b', replace_hex, css)

    # rgba(R, G, B[, A]) → if RGB matches a palette hex, replace with var()
    # (preserve alpha via color-mix when alpha < 1).
    def replace_rgba(m):
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
            return m.group(0)
        hex_value = f'#{r:02x}{g:02x}{b:02x}'
        var_ref = hex_to_var.get(hex_value)
        if not var_ref:
            return m.group(0)
        alpha_str = m.group(4)
        if alpha_str is None:
            return var_ref
        try:
            alpha = float(alpha_str)
        except ValueError:
            return m.group(0)
        if alpha >= 0.999:
            return var_ref
        # color-mix is supported in Chromium 111+ which Playwright bundles.
        return f'color-mix(in srgb, {var_ref} {alpha * 100:.1f}%, transparent)'

    css = re.sub(
        r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)',
        replace_rgba, css,
    )
    return css


def build_css_override(dna: DnaSpec) -> str:
    """Generate templates/css/<slug>.css content from DNA. Pure Python, no LLM."""
    # Build Google Fonts @import — combine explicit google_imports with
    # auto-added fonts from headline/body picks (so picker dropdowns just work).
    auto_imports = []
    for font_name in (dna.fonts.headline, dna.fonts.body):
        param = _GOOGLE_FONT_PARAM.get(font_name)
        if param and param not in auto_imports:
            auto_imports.append(param)
    all_imports = list(dna.fonts.google_imports) + [
        x for x in auto_imports if x not in dna.fonts.google_imports
    ]
    google = ""
    if all_imports:
        google = (
            "@import url('https://fonts.googleapis.com/css2?"
            + "&".join(f"family={x}" for x in all_imports)
            + "&display=swap');\n"
        )
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
/* Override fonts directly (templates hardcode font-family; using !important for chip too) */
html, body, .body, .handle, .stage {{ font-family: '{dna.fonts.body}', sans-serif !important; }}
.header, .header .top, .header .bot, .stage-badge, h1, h2, h3 {{ font-family: '{dna.fonts.headline}', sans-serif !important; }}
.persistent {{ {_chip_css(dna.chip_style).replace(';', ' !important;')} }}
.persistent.like, .persistent.sub {{ {_chip_css(dna.chip_style).replace(';', ' !important;')} }}
"""
    if dna.custom_css.strip():
        # Sanitize: replace hardcoded hex colors that match palette values with
        # their var(--xxx) equivalents. Without this, Opus-generated custom_css
        # writes literal hex like `color: #0d1b2a` which beats the live palette
        # picker (DnaPalette overrides only flow through :root vars).
        sanitized = _sanitize_custom_css_colors(dna.custom_css, dna.palette)
        css += f"\n/* Channel custom_css (Opus-generated, color-sanitized) */\n{sanitized}\n"
    # Readability safety net — appended LAST so it overrides any custom_css
    # gradient-text or stroke trick on the headline. We let custom_css decorate
    # backgrounds, photos, chips freely, but force the headline to render with
    # solid fill + no stroke (the two patterns that destroy legibility on
    # dynamic backgrounds).
    css += (
        "\n/* === Readability safety net === */\n"
        ".header .top, .header .bot {\n"
        "  -webkit-text-fill-color: currentColor !important;\n"
        "  -webkit-background-clip: initial !important;\n"
        "  background-clip: initial !important;\n"
        "  -webkit-text-stroke: initial !important;\n"
        "}\n"
    )
    # Optional headline color overrides — empty string falls back to template
    # default (top → accent inheritance, bot → text_main).
    if p.header_top_color:
        css += f".header .top {{ color: {p.header_top_color} !important; }}\n"
    if p.header_bottom_color:
        css += f".header .bot {{ color: {p.header_bottom_color} !important; }}\n"
    return css
