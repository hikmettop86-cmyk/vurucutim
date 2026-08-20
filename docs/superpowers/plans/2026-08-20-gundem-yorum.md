# Gündem Yorum — uygulama planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Hedef:** Cartesia TTS sağlayıcısı + tarafsız-ama-görüşlü yorumcuyla seslendirilen "Gündem Yorum" formatı (kendi UI kurulumuyla) + günlük uzun-form derleme.

**Mimari:** Spec `docs/superpowers/specs/2026-08-20-gundem-yorum-design.md`. Üç alt proje sırayla: B (sağlayıcı) → C (format + UI) → D (derleme). Her görev TDD: test → kırmızı → kod → yeşil → commit. CRLF dosyalarda yamalar satır sonu koruyarak uygulanır (`patch_*.py` kalıbı).

**Teknoloji:** Python 3.14, requests (SSE `stream=True`), `wave`, pydantic config, Flask/Jinja panel, ffmpeg concat, pytest.

---

## Dosya haritası

| dosya | sorumluluk |
|---|---|
| `src/short_bot/tts/cartesia_client.py` (yeni) | SSE sentez + zaman damgası, ses listesi, sağlık, model sınama, klon, kredi sayacı |
| `src/short_bot/tts/providers.py` (yeni) | `resolve_tts(provider)` → (health_check, synthesize, api_key_resolver) |
| `src/short_bot/config.py` | `VoiceConfig.provider/model/volume/emotion` |
| `src/short_bot/voiced.py` | sağlayıcıya göre deps; dönen ses yolu; kelimeler varsa whisper atla; `ticker_items`; yorum anlatımı seçimi |
| `src/short_bot/narration_writer.py` | `build_yorum_prompt`, `write_yorum_narration`, varsayılan persona |
| `src/short_bot/models.py` | `NewsItem.extra_links` |
| `src/short_bot/trends/trending_now.py` | 2./3. makale → `extra_links` |
| `src/short_bot/formats.py` (yeni) | `channel_format(cfg)` |
| `src/short_bot/pipeline.py` | ek makale gövdeleri, yorum yolu, ticker voiced'a |
| `templates/flas-narrator.html.j2` (yeni) | Flaş kimliği + beat KJ kartları + `__seek` |
| `src/short_bot/web/routes/cartesia_api.py` (yeni) | `/api/cartesia/*` |
| `src/short_bot/web/routes/settings.py` + `templates/settings.html.j2` | anahtar alanı + kredi sayacı |
| `src/short_bot/web/routes/channel_edit.py` + `templates/channels/edit.html.j2` | ses kartında sağlayıcı + Cartesia kontrolleri |
| `src/short_bot/web/routes/yorum.py` (yeni) + `templates/channels/new_yorum.html.j2`, `edit_yorum.html.j2` | format sihirbazı/düzenleme |
| `templates/_partials/channel_row.html.j2`, `channel_card.html.j2`, `channels/list.html.j2` | rozet + yönlendirme + düğme |
| `config/channels/gundem-yorum.yaml` (yeni) | kanal |
| `src/short_bot/compilation.py` (yeni) + `templates/compilation_intro.html.j2`, `compilation_outro.html.j2` | derleme |
| `src/short_bot/youtube/metadata_writer.py` | `build_compilation_metadata` |
| `src/short_bot/web/scheduler.py` | gece derleme işi |

---

## B. Cartesia sağlayıcısı

### Task B1: `parse_sse` + `synthesize` (WAV + kelimeler)
- Test: `tests/test_cartesia_client.py::test_parse_sse_fixture` (8 kelime, 275184 bayt PCM, son `end`=3.0), `test_synthesize_writes_wav_and_words` (monkeypatch `requests.post` → fikstür metni; `.wav` yazıldı, `wave` ile 44100/1 kanal, `result.words[0].word == "Adalar"`, `chars_spent == len(text)`), `test_synthesize_clamps_speed_and_volume_and_logs`, `test_synthesize_sends_language_and_model`, `test_synthesize_rejects_tiny_audio`, `test_synthesize_retries_on_429_then_raises`.
- Kod: dataclass `SynthesisResult(path, words, duration_s, chars_spent)`; `_post_sse` (stream, `iter_lines`); 429/5xx → 3 deneme 2/4/8 sn (`sleep` enjekte); kelime → `TimedWord(word, start, end, seg=0)`; parçalama `_split_sentences(text, 3000)` + ofset.
- Commit: `feat(cartesia): SSE sentez — WAV + kelime zaman damgaları`

### Task B2: ses listesi, sağlık, model sınama, klon, kredi sayacı
- Test: `test_list_voices_maps_fields_and_requires_language_filter`, `test_health_check_states` (no-key/auth 401/no-voice 404/model_not_found→"model"/ok), `test_probe_models_classifies`, `test_clone_trims_long_clip` (ffprobe/ffmpeg monkeypatch), `test_usage_counter_monthly`.
- Commit: `feat(cartesia): ses listesi, kredisiz sağlık, model sınama, klon, aylık kredi sayacı`

### Task B3: `VoiceConfig` alanları + `providers.resolve_tts` + `voiced.py`
- Test: `tests/test_config_voice_provider.py` (yükle/kaydet; eski YAML → ai33; cartesia hız 0,6 altı ValueError), `tests/test_voiced_cartesia.py` (cartesia deps: `transcribe_words` çağrılmaz, timeline kelimelerden, dönen wav yolu compose'a; ai33 yolu eski testlerle aynı).
- Commit: `feat(voice): sağlayıcı seçimi (ai33|cartesia), Cartesia kelimeleriyle hizalama`

### Task B4: panel — ayarlar anahtarı, `/api/cartesia/*`, ses kartı kontrolleri
- Test: `tests/test_web_cartesia.py` (ayarlar POST anahtarı yazar/maskeler; `/api/cartesia/voices?language=tr` monkeypatch ile liste; ses kartı POST `voice_provider=cartesia, voice_model, voice_volume, voice_emotion` YAML'a).
- Commit: `feat(panel): Cartesia anahtarı, ses listesi/sağlık/model/klon uçları, ses kartı kontrolleri`

## C. Gündem Yorum formatı

### Task C1: `extra_links` + çok-kaynak gövde
- Test: `tests/test_trends_trending_now.py::test_as_news_items_carries_extra_links`; `tests/test_pipeline_extra_sources.py` (`_extra_source_bodies(item)` extract monkeypatch; başarısız atlanır; ≤1500 karakter).
- Commit: `feat(trends): trendin 2./3. makalesi ek kaynak olarak taşınıyor`

### Task C2: yorumcu anlatımı
- Test: `tests/test_narration_yorum.py` (prompt: persona, ≥2 kaynak adı kuralı, denge, hüküm, kapanış sorusu, Trends cümlesi, yasaklar, kelime bütçesi; `write_yorum_narration` JSON doğrulama + bütçe geri bildirimi mevcut `write_narration` makinesini kullanır).
- Commit: `feat(yorum): tarafsız-ama-görüşlü yorumcu anlatım yazarı`

### Task C3: `formats.channel_format` + `flas-narrator.html.j2` + voiced entegrasyonu
- Test: `tests/test_formats.py`; `tests/test_flas_narrator_template.py` (beat kartları `data-s/e`, `__seek`, ticker, kaynak); `tests/test_voiced_yorum.py` (format yorum → `write_yorum_narration` seçilir).
- Commit: `feat(yorum): flas-narrator şablonu ve format çözümleyici`

### Task C4: UI — `yorum.py` new/edit, liste rozeti, kanal YAML
- Test: `tests/test_web_yorum.py` (GET new/edit 200 + alanlar; POST new → YAML `content_source: trends`, `voice.provider: cartesia`, persona; edit POST günceller; liste `edit-yorum` bağlantısı; 6 sn kart `edit` bağlantısı değişmedi).
- `config/channels/gundem-yorum.yaml` + `test_repo_gundem_yorum_channel_loads`.
- Commit: `feat(yorum): kurulum sihirbazı, düzenleme sayfası, kanal listesi rozeti, gundem-yorum kanalı`

### Task C5: gerçek koşu
- `python -m short_bot run --channel gundem-yorum --max 1` → log: `cartesia`, kelime sayısı, şablon `flas-narrator`; kare + anlatım metni incelenir; düzeltmeler.

## D. Günlük derleme

### Task D1: `compilation.py` çekirdek
- Test: `tests/test_compilation.py` (gün seçimi TZ sınırı; <190 sn None; concat listesi sırası hacme göre; ffmpeg komutu monkeypatch; DB satırı + yeniden üretimde eski satır `deleted_at`).
- Commit: `feat(derleme): günün yorum kliplerinden ≥3 dk 10 sn uzun-form derleme`

### Task D2: intro/outro şablonları + metadata + cron + panel düğmesi
- Test: `tests/test_compilation_metadata.py` (başlık, bölüm zaman damgaları, `#shorts` yok), `tests/test_web_yorum.py::test_compile_button_posts`, scheduler kaydı testi.
- Commit: `feat(derleme): intro/outro, uzun-form metadata, gece cron'u, panel düğmesi`

### Task D3: gerçek derleme
- Günün klipleri yetmezse iki test klibiyle ffmpeg akışı doğrulanır; çıktı süresi ve bölüm zamanları kontrol edilir.

---

## Self-review
- Spec B → B1-B4; C → C1-C5; D → D1-D3; hata tablosu: retry (B1), no-key/auth (B2/B3), timestamps yok → orantılı (B3), ek makale hatası (C1), 190 sn (D1), kredi %90 uyarısı (B4).
- Tip tutarlılığı: `SynthesisResult` B1 ↔ B3; `channel_format` C3 ↔ C4; `extra_links` C1 ↔ C2 (prompt `ADDITIONAL SOURCES`).
