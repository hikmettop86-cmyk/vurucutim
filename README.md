# short-bot

RSS → YouTube Shorts (9:16, 30s, kinetic text + müzik).

## Kurulum

```bash
pip install -e ".[dev]"
playwright install chromium
```

## İlk Çalıştırma

```bash
python -m short_bot init                            # SQLite şemasını oluştur
python -m short_bot run --channel son-dakika --max 1
```

Çıktı: `output/son-dakika/<tarih>_<slug>.mp4`

Detay: `docs/superpowers/specs/2026-05-05-rss-news-shorts-design.md`
