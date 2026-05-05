# short-bot

RSS → YouTube Shorts (9:16, 30s, kinetic text + müzik).

## Kurulum

```bash
pip install -e ".[dev]"
playwright install chromium
```

## İlk Çalıştırma

### 1. Müzik dosyaları

`assets/music/{breaking,neutral,upbeat}/` klasörlerine **en az birer mp3** koyun.
Başlangıç için YouTube Audio Library'den 5-10 telifsiz parça indirin.

### 2. DB init

```bash
python -m short_bot init
```

### 3. Kanalları listele

```bash
python -m short_bot list-channels
```

### 4. İlk Short'u üret

```bash
python -m short_bot run --channel son-dakika --max 1
```

Çıktı: `output/son-dakika/<tarih>_<slug>.mp4`

Loglar: `logs/runs/<tarih>_<slug>.log`

### Sorun giderme

| Hata | Çözüm |
|---|---|
| `claude: command not found` | `config/settings.yaml` → `claude_cli_path: "C:\\path\\to\\claude.exe"` |
| `ffmpeg: command not found` | `ffmpeg`'i PATH'e ekleyin veya `ffmpeg_path` ayarlayın |
| `Mood 'breaking' için müzik bulunamadı` | `assets/music/breaking/` klasörüne mp3 koyun |
| `Playwright timeout` | `playwright install chromium` çalıştırın |
| Render uzun sürüyor | Normal: 30s short → 30-90s render (ilk koşumda Playwright cold-start) |

Detay: `docs/superpowers/specs/2026-05-05-rss-news-shorts-design.md`
