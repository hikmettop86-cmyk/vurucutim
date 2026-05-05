# short-bot

RSS → YouTube Shorts (9:16, 30s, kinetic text + müzik).

## Kurulum

```bash
pip install -e ".[dev]"
playwright install chromium
```

## İlk Çalıştırma

### 1. Müzik dosyaları

Repo, `assets/music/` altında **YouTube Audio Library kaynaklı 4 telifsiz parçayla** birlikte gelir:

| Mood | Dosya |
|---|---|
| breaking | `Running - Nat Keefe.mp3`, `Sweaty Staredown - The Soundings.mp3` |
| neutral  | `Rain Over Kyoto Station - The Mini Vandals.mp3` |
| upbeat   | `Floating Lanterns - The Mini Vandals.mp3` |

Bot her koşumda `assets/music/<mood>/*.mp3` altından rastgele birini seçer. Yeni parça eklemek isterseniz YouTube Audio Library veya başka telifsiz kaynaktan indirip ilgili klasöre koyun — bot otomatik bulur, ek yapılandırma gerekmez.

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

## Web Panel (Phase 3)

```bash
python -m short_bot web
# → http://127.0.0.1:5005
```

Features:
- Dashboard with daily counters and recent shorts
- Shorts gallery (filter by channel/search) + detail player
- RSS scoring history (last 24h)
- Channel list + edit (DNA editor with color pickers, font dropdowns, segment pills)
- New-channel wizard (form → Opus DNA → live preview → save)
- Live template preview in iframe (instant updates as you tweak DNA)
- APScheduler runs cron jobs in-process (kanal config'lerinden okur)
- Logs tail with HTMX 2s polling

Default port: 5005. Override with `--port` flag.
