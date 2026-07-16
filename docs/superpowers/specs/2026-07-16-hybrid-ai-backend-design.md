# Hybrid AI Backend — Tasarım (2026-07-16)

## Karar (kullanıcı, mod A)

- **Tüm METİN çağrıları Claude CLI** (abonelik): senaryo/yargıç/doktor/keşif/
  kurgucu/skorlama/konu bankası/metadata → `sonnet`; DNA → `opus`.
- **Vision: Google AI Studio** `gemini-3.1-flash-lite` — faceless-2'den taşınan
  **38 anahtarlık rotasyon havuzu**, anahtar+model başına **500/gün** (Google'ın
  canlı 429 gövdesiyle ölçülmüş gerçek kota), 15 RPM, PT-geceyarısı sıfırlama.
- **Fallback'ler:** CLI çökerse/yoksa → OpenRouter **anthropic/claude-sonnet-5**
  (dna→opus-4.8). GS havuzu tükenirse/çökerse → OpenRouter
  **google/gemma-4-26b-a4b-it** (faceless-2 .env'inde çalışır ölçülmüş tam ID;
  aynı model Google'ın KENDİ sunumunda kırık — o yüzden GS tarafında değil,
  yalnız OR fallback olarak).

## Mimari (Yaklaşım 1: merkezî yönlendirme, zincir backend İÇİNDE)

### 1. `resolve_ai_call` — `ai_backend: "hybrid"` dalı (config.py)

- `vision` → `AICall(backend="google_studio", model=settings.google_studio_vision_model)`
- diğer roller → `AICall(backend="claude_cli", model=claude_models[role])`
- Her çözümde `claude_cli.register_fallback(backend, model, "openrouter",
  openrouter_models[role], or_key)` çağrılır (idempotent modül kaydı) —
  **36+ çağrı noktası değişmeden** fallback kazanır; `openrouter_models`
  haritası hybrid'de FALLBACK haritası görevi görür.

### 2. Dispatch fallback'i (claude_cli.py `_invoke_raw`)

Birincil backend hatasında (CLI: FileNotFoundError/exit≠0/Timeout;
google_studio: `GoogleStudioExhausted`/hata) kayıtlı fallback varsa **tek
deneme** OR'a düşülür, `log.warning("fallback: ...")` ile raporlanır. Kayıt
yoksa bugünkü davranış birebir (openrouter backend'inde fallback aranmaz).
Desen `llm_sonnet.sonnet_json`'ın kanıtlanmış CLI→OR düşüşünün merkezîleşmişi.

### 3. Yeni modül `google_studio.py`

- Havuz: `data/google_pool/google-keys.json` (faceless-2/agbey şeması:
  `{keys:[{id,key,label,enabled,addedAt}]}`; enabled filtreli). Anahtarlar
  kurulumda `C:\Users\Hiko\AppData\Roaming\agbey\google-pool\google-keys.json`'dan
  kopyalanır (38 anahtar; data/ gitignore'da — anahtar commit edilmez).
- Durum: `data/google_pool/state.json` — `{date_pt, used{keyid:model→n},
  banned[], cooldown{keyid→until_ts}}`; PT tarihi değişince used sıfırlanır
  (Google kota penceresi PT-geceyarısı — faceless-2 ölçümü).
- Seçim: aktif (banned/cooldown dışı, günlük<500, son 60sn'de <15 çağrı)
  anahtarlardan EN AZ kullanılanı; hiçbiri müsait değilse 20sn'ye kadar bekle,
  sonra `GoogleStudioExhausted`.
- Çağrı: REST `v1beta/models/{model}:generateContent`, kimlik `x-goog-api-key`
  başlığı (hem `AIza...` hem `AQ....` yeni-format için çalışır; faceless-2
  `?key=` kullanıyor ama header her iki formatta güvenli — Google'ın önerdiği
  yol). İstek gövdesi faceless-2 birebir: `contents:[{role:"user",parts:[{text},
  {inline_data:{mime_type,data}}]}], generationConfig:{maxOutputTokens}`. Yanıt:
  `candidates[0].content.parts` → `thought` olmayan son parçanın `.text`'i.
  BOŞ yanıt (güvenlik bloğu / MAX_TOKENS → '') = istek sayılır ama içerik yok →
  `GoogleStudioExhausted` fırlat → OR-gemma fallback'ine düş (sonsuz retry yok).
  429 sınıflandırma (faceless classify429 port): violations yok → `capacity`
  (havuz-geneli kısa duraklama, anahtara dokunma); `PerDay` → anahtar+model
  GÜN-BOYU kapalı; `PerMinute` → retryDelay kadar cooldown (yoksa 60sn);
  401/403 → 2 üst üste'de anahtar YASAK (kalıcı, state'te). İstek sayacı
  `acquire()` anında artar (sonuçtan bağımsız — Google isteği sayar, ölçülmüş).
  Thread-safe (tek RLock — vision 8 paralel işçiyle çağrılıyor).
- Havuz dizini: modül varsayılanı `data/google_pool`; `set_pool_dir()` ile
  web `create_app` ve pipeline başlangıcı db-yoluna göre ayarlar (paketli
  Electron'da data taşınabilir).

### 4. settings.yaml

```yaml
ai_backend: hybrid
claude_models: {dna: opus, default: sonnet, script: sonnet, vision: default}
openrouter_models:            # hybrid'de FALLBACK haritası
  dna: anthropic/claude-opus-4.8
  default: anthropic/claude-sonnet-5
  script: anthropic/claude-sonnet-5
  vision: google/gemma-4-26b-a4b-it
google_studio:
  vision_model: gemini-3.1-flash-lite
```
DAILY_CAP=500 / RPM=15 / WAIT_MS=20000 modül sabitleri (ölçülmüş değerler;
YAGNI: config'e açılmaz).

### 5. Dokunulmayanlar

- `llm_sonnet` zaten CLI→OR-sonnet yapıyor — olduğu gibi kalır.
- `openrouter` ve `claude_cli` ai_backend modları birebir korunur (hybrid
  ek mod; geri dönüş tek satır).
- Çağrı noktaları (reel/keşif/kurgucu/skorlama/metadata) değişmez.

### 6. Test + doğrulama

Unit (enjekte http/now/store): havuz rotasyonu, 500/gün + PT reset, RPM,
429-daily/rate/ban sınıfları, exhausted; dispatch: CLI-fail→OR-sonnet,
GS-exhausted→OR-gemma, kayıtsızken davranış birebir; resolve_ai_call hybrid
eşlemesi. Canlı smoke: CLI-sonnet tek prompt + GS vision tek describe.
Son adım: gerçek üretim koşusu — log'da backend izleri.

### 7. Riskler

- CLI subprocess ~1-3sn/çağrı (video ~5 metin çağrısı → +~10-15sn) — kabul.
- Yoğun günde Max plan pencere limiti → otomatik OR-sonnet düşüşü, üretim durmaz.
- `AQ.` anahtarların bir kısmı farklı yetkide olabilir → 401/403 ban sınıfı
  havuzu kendi temizler.
