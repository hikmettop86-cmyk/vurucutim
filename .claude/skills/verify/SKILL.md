---
name: verify
description: D:\short web panelini scratch ortamda gerçek verilerle ayağa kaldırıp değişikliği HTTP üzerinden sürme reçetesi
---

# Web paneli E2E doğrulama (scratch ortam + gerçek YouTube kimlikleri)

Panel = Flask (`short_bot.web.create_app`). Elektron sadece bunu sarar; HTTP yüzeyi
gerçek yüzeydir.

## Reçete

1. Scratch dizinde minimal config kur (test fixture'ı `tests/test_web_youtube_stats_routes.py::_make_app`
   birebir kopyalanabilir: settings.yaml + channels/<slug>.yaml).
2. `SHORTBOT_YT_CREDS_DIR` **db_path.parent / "youtube_credentials"** olarak türetilir
   (web/__init__.py:96) — gerçek kimlikleri `D:\short\data\youtube_credentials\<slug>\`
   klasöründen scratch `data/youtube_credentials/<slug>/` altına KOPYALA (orijinale dokunma).
3. DB tohumu: `init_db` + `record_short` + `record_youtube_upload(video_id=<GERÇEK canlı id>)`.
   Canlı id bulmak için kanalın uploads playlist'i (Data API) — silinmiş id'ler Analytics'te
   boş döner (bu da iyi bir probe).
4. Sunucu: `app.run(host="127.0.0.1", port=5099, use_reloader=False)` arka planda;
   `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5099/` ile bekle.
5. Sür: `curl -X POST .../channels/<slug>/youtube/refresh-stats` (302 = handler koştu;
   `-L` KULLANMA — redirect zinciri exit 47 verir), sonra `curl .../shorts/<id> | grep ...`.
6. Kapat: `/shutdown` YOK — arka plan görevini TaskStop ile öldür.

## Tuzaklar

- Migration probe'u için DB'yi ESKİ şemayla elle CREATE TABLE et; `init_db` idempotent
  ALTER'ları koşar (`db.py::_migrate_add_columns`).
- Üretim örneği `C:\Users\Hiko\AppData\Local\VurucuTim\data\short_bot.sqlite` — ASLA ona
  karşı doğrulama yapma, scratch DB kullan.
- Windows konsolunda Türkçe çıktı için scriptlere `io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")`.
- CPU-ağır pytest ile eşzamanlı üretim/doğrulama koşturma — süreç öldürülür (exit 127).
