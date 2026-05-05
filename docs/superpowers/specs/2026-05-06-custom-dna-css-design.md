# Custom DNA CSS — Design Doc

**Tarih:** 2026-05-06
**Durum:** Draft (kullanıcı onayı bekleniyor)
**Sahip:** short-bot
**Önceki spec'ler:** Phase 1 (RSS), Phase 2 (Channel DNA), Phase 3 (Web Panel), Phase 5 (Generator Mode)

---

## Problem

Mevcut DNA sistemi 7 sabit archetype + yapısal alanlar (palette, fonts, banner_shape, highlight_style, chip_style, category_icon) sunuyor. Bu, kanaldan kanala "boyalı versiyon" hissi veriyor — örneğin iki farklı `kinetic` kanal farklı renklere sahip ama görsel **dokuları** birbirine çok benziyor.

Kullanıcı: "Archetype Opus kendisi baştan DNA üret diyince şablon yerine mükemmel her şeyi bir tasarım yapamaz mı?"

## Hedef

Mevcut HTML iskeleti (1080×1920 layout, animasyon timing'leri, persistent chip pozisyonları, render kontratı) **dokunulmadan** korunacak. Opus, her kanal için ek bir **görsel zenginlik CSS bloğu** üretecek: arka plan desenleri, dekoratif SVG/CSS overlay'leri, tipografi efektleri, photo treatment, chip dekorasyonu, custom @keyframes (sadece dekoratif elementler için).

İki kanal artık aynı archetype'ta bile gerçekten **farklı görünecek**.

## Hedef Olmayan (Non-goals)

- Layout esnekliği (header position, body align, persistent chip yerleşimi) — Yaklaşım B/C scope dışı
- Tam serbest HTML template üretimi — Yaklaşım C scope dışı
- Per-short (her run'da farklı) görsel — DNA Yenile elle tetiklenir, persistent
- CSS validation/sanitization — kullanıcı sade yaklaşımı tercih etti, sadece smoke render ile yakalanır

## Mimari

DnaSpec'e tek yeni alan: `custom_css: str`. Opus, mevcut yapısal alanları doldurduktan sonra ayrıca bu alana özgürce CSS yazar. `build_css_override`, mevcut yapısal CSS'in sonuna `custom_css`'i ekler — override yetkisi var.

DNA üretildikten **hemen sonra** bir "smoke render" çalışır: 1080×1920 frame Playwright ile capture edilir, file size + pixel stddev kontrolü ile "render bozulmadı" doğrulanır. Smoke fail ederse DNA kaydedilmez, kullanıcıya tekrar üretmesi söylenir.

```
DNA Yenile (UI)
    ↓
generate_dna(name, keywords, language, ...)        # Opus call
    ↓ DnaSpec dönüş (custom_css dahil)
smoke_render_dna(dna, channel)                      # Playwright 1 frame
    ↓ pass
save_channel(...)                                   # YAML write
build_css_override(dna) → templates/css/<slug>.css  # CSS rebuild
```

Fail path: smoke False → flash error + redirect, eski DNA korunur.

## 1. Veri Modeli

`src/short_bot/dna.py` içindeki `DnaSpec`'e tek alan eklenir:

```python
class DnaSpec(BaseModel):
    # ... mevcut alanlar ...
    custom_css: str = Field(default="", max_length=8000)
```

**Backward compat:** mevcut DNA'lar `custom_css=""` defaulted, hiçbir mevcut kanal etkilenmez. YAML round-trip için sorun yok (boş string yazılmaz veya yazılır, fark etmez).

**Limit gerekçesi:** 8000 karakter ≈ ~150-200 satır CSS. Data URI background image (~3KB) + 5-10 dekoratif kural için yeterli. 16000'e çıkmak isterse Phase 7'de düşünülür.

## 2. Opus Prompt

`src/short_bot/dna.py:build_dna_prompt`'a yeni bölüm eklenir (mevcut prompt'un sonuna, `persona_summary` field tanımından önce):

```
ÖZGÜR CSS (custom_css):
Yapısal alanları (palette, fonts, banner_shape, vb.) yukarıda doldurduktan sonra,
kanala özel görsel zenginlik için ek bir CSS bloğu yaz. Bu CSS şunları yapabilir:

✓ İZİNLİ:
- background-image / repeating gradient / pattern (body, .stage, .stage::before)
- ::before / ::after dekoratif elementler (HER selector için)
- text-shadow, -webkit-text-stroke, gradient text (.header .top, .header .bot, .body)
- filter / mix-blend-mode (dekoratif overlay'ler için)
- photo treatment (.photo elementine border, mask, filter)
- chip dekorasyonu (.persistent ::before/::after, decorative borders)
- Custom @keyframes (sadece YENİ dekoratif elementler için)
- box-shadow, border-radius, background-blend-mode

✗ YASAKLI (KESINLIKLE DOKUNMA — render bozar):
- position / top / bottom / left / right / width / height değerleri
  .header, .body, .persistent, .progress, .handle, .stage selector'larında
- z-index 100'den büyük (CTA layer çakışmaması için)
- animation: süresi {duration_s}s'den uzun (frame timing korumalı)
- mevcut @keyframes'leri (fill, ken-burns vb) override etme

ÖRNEK YAKLAŞIM:
- Magazine kanalı için: bg radial-gradient + .photo polaroid frame + .body italic
- Tech kanalı için: bg scanline pattern + .header text-stroke + .persistent neon glow
- Romance kanalı için: bg pink gradient + heart pattern overlay + script font shadow

ÇIKTI: 1500-3000 karakter arası ham CSS, başka açıklama yazma.
Boş bırakma — kanalın kişiliğini görsel olarak ifade et.
```

JSON şeması güncellenir, `custom_css: "<CSS string>"` alanı eklenir.

## 3. CSS Injection

`src/short_bot/dna.py:build_css_override` fonksiyonunun en sonuna eklenir:

```python
def build_css_override(dna: DnaSpec) -> str:
    # ... mevcut yapısal CSS üretimi ...

    # Custom DNA-üretimi CSS (Opus tarafından) — son sırada, override yetkisi
    if dna.custom_css.strip():
        css += f"\n/* Channel custom_css (Opus-generated) */\n{dna.custom_css}\n"

    return css
```

Sıralama önemli: structural CSS önce, custom_css sonra → custom_css mevcut renkleri/fontları override edebilir (örn. text-shadow eklemek isterse mevcut color tanımına eklenebilir).

## 4. Smoke Render Test

Yeni modül: `src/short_bot/dna_smoke.py`

```python
"""Smoke-render a DNA preview frame to catch render-breaking custom_css."""
from pathlib import Path
import tempfile

from PIL import Image, ImageStat

from short_bot.config import ChannelConfig, Settings
from short_bot.dna import DnaSpec, build_css_override
from short_bot.locale import ui_labels_for
from short_bot.models import Highlight, RenderJob, Script
from short_bot.renderer import render_frames


_SAMPLE_SCRIPTS = {
    "tr": {"header_top": "TEST", "header_bottom": "DNA",
           "photo_overlay": "Smoke", "category": "test", "mood": "neutral",
           "body_paragraph": "Bu metin smoke render testi içindir. Layout korumalı mı kontrol ediyoruz.",
           "highlights": []},
    # diğer diller fallback olarak "tr"'den okur
}


def smoke_render_dna(
    dna: DnaSpec, *,
    channel_template: str,
    templates_dir: Path,
    settings: Settings,
    language: str = "tr",
) -> tuple[bool, str]:
    """Render 1 frame, return (success, reason).

    Checks:
    1. Frame file produced (PNG > 5KB)
    2. Pixel stddev > 5 (not solid black/white — layout broken would render blank)
    """
    sample = Script(**_SAMPLE_SCRIPTS.get(language, _SAMPLE_SCRIPTS["tr"]))
    job = RenderJob(
        script=sample, bg_image_path=None,
        music_path=Path("dummy.mp3"),  # never read in render
        channel_colors={
            "primary": dna.palette.primary, "accent": dna.palette.accent,
            "bg_gradient": dna.palette.bg_gradient,
        },
        handle="@smoke", duration_s=6, language=language, cta_enabled=False,
    )
    template_path = templates_dir / f"{channel_template}.html.j2"
    dna_css = build_css_override(dna)
    ui_labels = ui_labels_for(language)

    with tempfile.TemporaryDirectory() as tmpd:
        frames_dir = Path(tmpd) / "frames"
        try:
            # Render only 3 frames (mid + edge), capture middle one
            render_frames(job, template_path, frames_dir,
                          fps=1, browser=settings.playwright_browser,
                          ui_labels=ui_labels, dna_css=dna_css)
        except Exception as e:
            return (False, f"render exception: {e}")

        pngs = sorted(frames_dir.glob("*.png"))
        if not pngs:
            return (False, "no frames produced")
        mid = pngs[len(pngs) // 2]
        if mid.stat().st_size < 5000:
            return (False, f"frame too small: {mid.stat().st_size} bytes")
        try:
            img = Image.open(mid).convert("RGB")
            stats = ImageStat.Stat(img)
            if max(stats.stddev) < 5:
                return (False, f"frame appears blank/solid: stddev={stats.stddev}")
        except Exception as e:
            return (False, f"PIL inspect failed: {e}")

    return (True, "ok")
```

**Not:** `render_frames` fps=1 ile minimum frame üretir. Gerçekte 6 frame çıkar (duration_s=6). Orta frame seçilir, dolu görünüm + animasyonun çalıştığı doğrulanır.

**Maliyet:** Playwright headless start ~3s + render ~2s = ~5s. Kabul edilebilir (DNA üretimi zaten 30-60s Opus'la).

## 5. Wiring

### `channel_new.py:save()`

```python
# Mevcut: dna = generate_dna(...) → save_channel(...)
# Yeni: arada smoke render
dna = generate_dna(...)
ok, reason = smoke_render_dna(
    dna,
    channel_template=dna.archetype,
    templates_dir=current_app.config["SHORTBOT_TEMPLATES_DIR"],
    settings=settings,
    language=language,
)
if not ok:
    flash(f"DNA render testi başarısız: {reason}. 'DNA Yenile' ile tekrar dene.", "error")
    return redirect(url_for("channel_new.form"))
# ... mevcut save akışı ...
```

### `channel_edit.py:regenerate_dna()`

Aynı pattern:

```python
new_dna = generate_dna(...)
ok, reason = smoke_render_dna(new_dna, ...)
if not ok:
    flash(f"DNA render testi başarısız: {reason}. Mevcut DNA korundu, tekrar dene.", "error")
    return redirect(url_for("channel_edit.edit", slug=slug))
# eski DNA korunur, yeni asla yazılmaz
```

### Yeni archetype yok

Mevcut 7 archetype korunur. `custom_css` her archetype için ayrı zenginlik üretir, archetype seçimi tone+layout için, custom_css görsel doku için.

## 6. UI Değişikliği

**Yok.** Mevcut "DNA Yenile" butonu zaten regenerate_dna endpoint'ini çağırıyor (Phase 4'te eklendi). Smoke fail flash mesajı yeni — kullanıcı görür ama UI değişmez.

İsteğe bağlı: Edit sayfasında DNA Editör bölümünün altında collapsible bir "Custom CSS (read-only)" panel gösterilebilir, ama scope dışı.

## 7. Test Stratejisi

| Test | Konum |
|---|---|
| `DnaSpec.custom_css` default boş, max_length 8000 | `tests/test_dna.py` (genişletme) |
| `build_dna_prompt` çıktısı "ÖZGÜR CSS" ve YASAKLI bölümlerini içerir | `tests/test_dna.py` |
| `build_css_override(dna)` çıktısı `dna.custom_css`'i sonda içerir | `tests/test_dna.py` |
| `build_css_override(dna)` boş custom_css için ek satır eklemez | `tests/test_dna.py` |
| `smoke_render_dna` happy path: dummy CSS → True | `tests/test_dna_smoke.py` |
| `smoke_render_dna` blank CSS render → False ("blank") | `tests/test_dna_smoke.py` |
| `channel_edit.regenerate_dna` smoke fail → flash + eski DNA korunur | `tests/test_web_dna_smoke.py` |

Smoke render testleri Playwright kullanır → CI'da yavaş çalışır (~10s/test). Sayıyı 2-3'le sınırlı tut.

## 8. Geriye Uyumluluk

- Mevcut DNA'lar (`custom_css=""`) sorun yok — `build_css_override` boş string için ek satır yazmaz
- Mevcut YAML'lar etkilenmez (yeni alan opsiyonel default)
- 5 dilde de aynı çalışır (smoke render `language` parametresi alır)
- Generator mode (Phase 5) ile ortogonal — generator kanalları da custom_css alır (Opus DNA üretirken)

## 9. Açık Sorular / Phase 7

- Custom CSS önizlemesi: edit sayfasında textarea ile elle düzenleme imkanı?
- `custom_css` versiyonlama: bir sonraki Opus generation eski CSS'i base alıp iyileştirsin?
- Pre-curated CSS preset library (kullanıcı "Magazine + Polaroid" gibi prefab seçebilsin)
- Smoke render visual diff (eski DNA vs yeni DNA frame'ini yan yana göster)

## 10. Kabul Kriterleri

1. ✅ Mevcut bir kanal "DNA Yenile" yapınca yeni DNA `custom_css` alanına dolu CSS içerir
2. ✅ `templates/css/<slug>.css` dosyasında "Channel custom_css (Opus-generated)" yorumu altında o CSS bloğu görünür
3. ✅ Yeni shortlar bu CSS'le render edilir, görsel olarak eski versiyondan farklı
4. ✅ Mevcut RSS kanalları (custom_css boş) hiçbir değişiklik göstermez
5. ✅ Smoke render başarısız olursa kullanıcı net hata mesajı alır, eski DNA korunur
6. ✅ 1500+ char CSS üretildiği halde render bozulmuyorsa otomatik kabul

## 11. Implementation Notları

- `_SAMPLE_SCRIPTS` küçük; 5 dile genişletmek isteyene `tests/fixtures/sample_script_<lang>.json` dosyalarını okuyabilir (zaten var Phase 3'ten)
- Smoke render `pick_music` çağırmaz — RenderJob.music_path dummy
- `render_frames` zaten `bg_image_path=None` durumunu destekliyor
- Playwright headless = settings.playwright_browser (zaten chromium)
- Test edilebilirlik için `smoke_render_dna` için bir `_run_render` mock noktası ekle
