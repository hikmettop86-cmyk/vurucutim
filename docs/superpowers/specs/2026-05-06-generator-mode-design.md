# Generator Mode — Design Doc

**Tarih:** 2026-05-06
**Durum:** Draft (kullanıcı onayı bekleniyor)
**Sahip:** short-bot
**Önceki spec'ler:** Phase 1 (RSS pipeline), Phase 2 (Channel DNA), Phase 3 (Web Panel)

---

## Problem

Mevcut sistem (RSS akışı) sadece Google News RSS'inden beslenir. Bir kullanıcı "Sevgi Sözleri", "Mizah", "Motivasyon" gibi haber-dışı bir konuda short üretmek istediğinde Google News'da o konuya ait *haberler* döner — sözün/mizahın *kendisi* dönmez. Bu da bot'u bu içerik tipi için kullanılamaz hale getirir.

## Hedef

Aynı kanal mimarisi içinde, ikinci bir içerik kaynağı tipi olan **"generator"** modunu eklemek. Bu modda:

- Pipeline RSS yerine doğrudan Claude Sonnet'i çağırır.
- Sonnet her run'da sıfırdan yeni bir içerik (söz/alıntı/mizah cümlesi) üretir.
- Üretim DB'ye kaydedilir, sonraki run'larda **bir daha aynı/benzer içerik üretilmesi engellenir**.
- Tema rotasyonu sayesinde aynı kanal aylarca dönmesine rağmen çeşitlilik korunur.
- Mevcut RSS kanalları **hiçbir değişikliğe maruz kalmaz** — yan yana yaşar.

## Hedef Olmayan (Non-goals)

- Embedding-tabanlı semantic dedup (ek API bağımlılığı yaratır, scope dışı).
- Kullanıcı tarafından elle havuz besleme (manual pool source) — Phase 5'te düşünülebilir.
- Reddit/Wikipedia gibi başka kaynak tipleri — Phase 5'te.
- Kanal türünün sonradan değiştirilmesi (RSS ↔ generator) — yeni kanal aç önerilir.

## Mimari Genel Bakış

İki paralel akış, ortak `run_pipeline` dispatcher'ı:

```
ChannelConfig.content_source
   ├─ "rss"       → _run_rss(...)         (mevcut, dokunulmuyor)
   └─ "generator" → _run_generator(...)   (yeni)
```

Her iki path da aynı `start_run` / `FileLock` / log setup / `runs` tablo kayıt iskeletini paylaşır.

---

## 1. Konfigürasyon

### 1.1 ChannelConfig genişletme

`src/short_bot/config.py`'a iki yeni alan:

```python
@dataclass(frozen=True)
class GeneratorConfig:
    topic: str                          # zorunlu, doğal dil tanımı
    forbidden_lookback: int = 50        # Sonnet'e gönderilecek son N üretim
    max_retries: int = 3                # dedup başarısızsa kaç kez denesin
    fuzzy_threshold: float | None = None  # None → Settings.fuzzy_dedup_threshold

@dataclass(frozen=True)
class ChannelConfig:
    # ... mevcut alanlar ...
    content_source: Literal["rss", "generator"] = "rss"  # default geriye uyumlu
    generator: GeneratorConfig | None = None             # sadece content_source="generator"
```

### 1.2 YAML şeması

**RSS kanalı (mevcut, hiç değişmez):**

```yaml
slug: son-dakika
keywords: [Türkiye, ekonomi]
# content_source default 'rss', yazılması gerekmez
```

**Generator kanalı (yeni):**

```yaml
slug: sevgi-sozleri
name: Sevgi Sözleri
language: tr
content_source: generator
generator:
  topic: "Sevgi ve aşk üzerine kısa, vurucu sözler — günlük instagram alıntısı tarzında"
  forbidden_lookback: 50
  max_retries: 3
  # fuzzy_threshold opsiyonel — yoksa Settings.fuzzy_dedup_threshold kullanılır
schedule_cron: "0 9,15,21 * * *"
duration_s: 7
template: kinetic
script_model: sonnet
# colors, dna, cta normal akış
```

### 1.3 Validasyon kuralları

- `content_source == "generator"` ise `generator` bloğu zorunlu, `keywords` boş olabilir.
- `content_source == "rss"` ise `keywords` zorunlu (mevcut davranış).
- `generator.topic` en az 10 karakter (kısa konu Sonnet'i yönlendirmez).

### 1.4 Sub-theme stratejisi

YAML'da `sub_themes` listesi **tutulmaz**. Sonnet her run'da kendi `topic_tag`'ini atar (TR lowercase, tek kelime). DB'deki son 7 günün dağılımı tema rotasyonu için Sonnet'e gösterilir; az kullanılanı seçmesi istenir.

---

## 2. Veritabanı Şeması

### 2.1 Yeni tablo: `generated_items`

```sql
CREATE TABLE IF NOT EXISTS generated_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel       TEXT     NOT NULL,
    text          TEXT     NOT NULL,
    text_hash     CHAR(64) NOT NULL,
    topic_tag     TEXT     NOT NULL,
    language      TEXT     NOT NULL,
    created_at    DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    short_id      INTEGER  REFERENCES shorts(id),
    status        TEXT     NOT NULL DEFAULT 'used'    -- 'used' | 'discarded'
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_generated_unique_hash
    ON generated_items(channel, text_hash);
CREATE INDEX IF NOT EXISTS ix_generated_recent
    ON generated_items(channel, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_generated_topic
    ON generated_items(channel, topic_tag, created_at DESC);
```

### 2.2 Hash normalize

```python
def normalize_for_hash(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)  # noktalama → boşluk
    text = re.sub(r"\s+", " ", text).strip()
    return text

def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()
```

Bu sayede yüzeysel paraphrase yakalanır:
- `"Aşk, sabırla başlar."` → `ask sabirla baslar`
- `"aşk sabırla başlar"` → `ask sabirla baslar` (aynı hash)

### 2.3 Diğer tablolarda değişiklik

- `processed_items`: dokunulmuyor (RSS dedup'una özel).
- `shorts`: `rss_item_guid` NULL bırakılır generator için, ek kolon yok.
- `runs`: dokunulmuyor.

### 2.4 Migrasyon

`src/short_bot/db.py:init_db()` idempotent — yeni `CREATE TABLE IF NOT EXISTS` satırları eklenir, ilk açılışta tablo oluşur. Mevcut SQLite dosyaları için manuel migration gerekmez.

### 2.5 Sorgu örnekleri

```sql
-- Forbidden list (Sonnet'e gidecek)
SELECT text FROM generated_items
WHERE channel = ? AND status = 'used'
ORDER BY created_at DESC LIMIT ?;

-- Topic distribution (son 7 gün)
SELECT topic_tag, COUNT(*) AS n FROM generated_items
WHERE channel = ? AND created_at > datetime('now','-7 days')
GROUP BY topic_tag ORDER BY n ASC;

-- Hash collision check
SELECT 1 FROM generated_items
WHERE channel = ? AND text_hash = ? LIMIT 1;

-- Same-tag fuzzy candidates
SELECT text FROM generated_items
WHERE channel = ? AND topic_tag = ?
  AND created_at > datetime('now','-7 days')
ORDER BY created_at DESC LIMIT 20;
```

---

## 3. Pipeline Akışı

### 3.1 Dispatcher

`src/short_bot/pipeline.py`'da:

```python
def run_pipeline(*, channel, settings, db_path, ...):
    eng = init_db(db_path)
    log = _setup_logger(...)
    run_id = start_run(eng, channel.slug, trigger=trigger, ...)
    lock = FileLock(...)
    try:
        with lock:
            if channel.content_source == "generator":
                return _run_generator(channel, run_id, log, eng, settings, ...)
            return _run_rss(channel, run_id, log, eng, settings, ...)
    except Exception as e:
        end_run(eng, run_id, status="failed", error=str(e))
        raise
```

### 3.2 Generator akışı (6 faz)

```
[1/6] prepare       — DB'den forbidden list (limit=N) + topic distribution (last 7d)
[2/6] generate      — Sonnet çağrısı, GeneratorResult döner
[3/6] dedup-check   — 3 katman (hash → fuzzy → tag+fuzzy); fail → retry
[4/6] image         — result.image_keywords ile DDG/Wiki ara
[5/6] render-html   — mevcut renderer (build_html aynen)
[6/6] render-video  — mevcut FFmpeg pipeline aynen
```

### 3.3 RSS akışı

Hiçbir değişiklik yok. Mevcut 8 fazlı akış (`fetch_rss → score → select → fetch_article → script → image → render-html → render-video`) `_run_rss(...)` fonksiyonuna sarılır, dispatcher tarafından çağrılır.

### 3.4 Image picker entegrasyonu

Mevcut `image_picker.pick_image_for_script(script, cache_dir, channel=...)` fonksiyonu `Script`'ten ve `dna.search_query_template`'den arama sorgusu üretir. Generator yolu için **küçük refactor**:

- `pick_image_for_script`'in iç akışı (DDG ara → Wikimedia fallback → download → Claude verify) korunur
- Query üretimi parametre olarak dışarı çıkarılır (yeni internal helper `_run_image_search(query, ...)`)
- Generator için yeni public helper:
  ```python
  def pick_image_for_generator(
      keywords: list[str], script: Script, cache_dir: Path, *,
      claude_path: str, max_candidates: int = 3,
  ) -> Path | None:
      query = " ".join(keywords)
      return _run_image_search(query, script, cache_dir, ...)
  ```
- `dna.search_query_template` generator'da kullanılmaz (no-op).

---

## 4. Sonnet Prompt'u

### 4.1 Pydantic model

```python
from pydantic import BaseModel, Field
from short_bot.models import Script

class GeneratorResult(BaseModel):
    text: str = Field(min_length=10, max_length=200)
    topic_tag: str = Field(min_length=2, max_length=20,
                           pattern=r"^[a-zçğıöşü]+$")  # TR lowercase tek kelime
    script: Script
    image_keywords: list[str] = Field(min_length=2, max_length=8)
```

### 4.2 Prompt builder

`src/short_bot/generator.py` (yeni dosya):

```python
def build_generator_prompt(
    *,
    channel: ChannelConfig,
    dna: DnaSpec,
    forbidden_texts: list[str],
    topic_distribution: dict[str, int],
) -> str:
    ...
```

Prompt iskeleti (TR örneği):

```
Sen "{channel.name}" kanalı için kısa, vurucu içerik üreten bir yazarsın.

KANAL KİMLİĞİ:
- Konu: {channel.generator.topic}
- Dil: Türkçe
- Persona: {dna.persona_summary}
- Voice: {dna.tone.voice}
- Style: {dna.tone.style}
- ASLA yapma: {dna.tone.forbidden | join}
- Cümle başı kelime sınırı: {dna.tone.sentence_max_words}
- Body uzunluk: {dna.tone.body_max_chars} karakter

GÖREV: 1 yeni içerik üret.

ASLA AŞAĞIDAKİ METİNLERE BENZER ÜRETME:
─── son N üretim ───
1. ...
N. ...
─── liste sonu ───

TEMA ROTASYONU (son 7 gün):
- tanisma: 12 ← çok kullanıldı
- sabir: 8
- ayrilik: 3 ← AZ
- umut: 1 ← AZ
- ozlem: 0 ← HİÇ

Bu tur az kullanılan/hiç kullanılmamış temalardan birini seç.
topic_tag: tek kelime, lowercase, Türkçe (sabir/umut/...).

ÇIKTI (sadece bu JSON):
{
  "text": "<max 120 karakter, ekranda kalacak ana söz>",
  "topic_tag": "<lowercase tr tek kelime>",
  "script": {
    "header_top": "<3-5 kelime, BÜYÜK HARF>",
    "header_bottom": "<3-5 kelime, BÜYÜK HARF>",
    "body": "<text'i içersin, {body_max_chars} kar.'a kadar>",
    "highlights": [{"text": "<1-3 kelime>", "color": "yellow"}]
  },
  "image_keywords": ["<3-5 İngilizce arama kelimesi>"]
}
```

### 4.3 Diğer diller

5 dil için (`tr`, `en`, `de`, `es`, `fr`) sabit ifadeler (`"ASLA yapma:"`, `"GÖREV:"` vb.) **yeni** `src/short_bot/prompt_phrases.py` modülünde dict olarak tutulur. İskelet aynı kalır, sadece dil etiketleri değişir. (Bu modül şu an mevcut değil; spec gereği oluşturulacak.)

### 4.4 Çağrı

```python
from short_bot.claude_cli import run_json

result = run_json(
    prompt, GeneratorResult,
    claude_path=settings.claude_cli_path,
    model=channel.script_model or settings.claude_models.get("default", "sonnet"),
    retries=2, timeout_s=180,
)
```

### 4.5 Maliyet beklentisi

- Forbidden list 50 metin × ~30 kelime ≈ 1500 input token
- DNA + topic + format ≈ 500 input token
- Output (JSON) ≈ 300-400 token
- Sonnet maliyeti: ~$0.005-0.01 per run

---

## 5. Retry & 3 Katmanlı Dedup

> **Not — iki farklı retry seviyesi:**
> - `run_json` içindeki `retries=2` → Sonnet **çağrı seviyesi** (network/JSON parse hatası gibi düşük seviye sorunlar için).
> - `channel.generator.max_retries=3` → **Dedup seviyesi** (Sonnet başarılı yanıt verdi ama içerik duplicate çıktıysa).
>
> İki sayı bağımsızdır. En kötü senaryo: 3 dedup × 2 cli = 6 Sonnet çağrısı (~$0.03). Pratikte çok ender.

### 5.1 Akış

```python
def _run_generator(channel, run_id, log, eng, settings, ...):
    forbidden = db_recent_generated_texts(eng, channel.slug,
                                           limit=channel.generator.forbidden_lookback)
    topic_dist = db_topic_distribution(eng, channel.slug, days=7)

    fuzzy_threshold = (channel.generator.fuzzy_threshold
                       or settings.fuzzy_dedup_threshold)

    last_result = None
    for attempt in range(1, channel.generator.max_retries + 1):
        log.info(f"[2/6] generate attempt {attempt}/{channel.generator.max_retries}")
        result = generate_quote(channel, dna, forbidden, topic_dist, model="sonnet")

        log.info(f"[3/6] dedup-check")
        verdict = check_duplicate(eng, channel.slug, result, forbidden,
                                  fuzzy_threshold)

        if verdict.is_duplicate:
            log.warning(f"  duplicate ({verdict.reason}): {result.text[:60]!r}")
            db_insert_generated(eng, channel.slug, result, status="discarded")
            last_result = result
            continue

        log.info(f"  novel: tag={result.topic_tag!r}")
        # 4-6. fazlar (image, render) BURADAN sonra
        return _finalize_generator_run(channel, run_id, result, log, ...)

    raise GeneratorRetryExhausted(
        f"{channel.slug}: {channel.generator.max_retries} deneme sonrası "
        f"tüm üretimler duplicate. Son deneme: {last_result.text[:80]!r}. "
        f"Konu tükenmiş olabilir — generator.topic'i genişletmeyi düşün."
    )
```

### 5.2 `check_duplicate` (3 katman)

```python
@dataclass
class DupVerdict:
    is_duplicate: bool
    reason: str = ""

def check_duplicate(eng, slug, result, forbidden, fuzzy_threshold) -> DupVerdict:
    # Katman 1: exact hash (DB)
    new_hash = text_hash(result.text)
    if db_exists_hash(eng, slug, new_hash):
        return DupVerdict(True, "exact_hash")

    # Katman 2: fuzzy text vs forbidden list (in-memory)
    from rapidfuzz import fuzz
    for prev in forbidden:
        ratio = fuzz.ratio(result.text.lower(), prev.lower()) / 100
        if ratio >= fuzzy_threshold:    # default 0.85
            return DupVerdict(True, f"fuzzy_text({ratio:.2f})")

    # Katman 3: same-tag + medium fuzzy
    same_tag = db_recent_by_tag(eng, slug, result.topic_tag, days=7, limit=20)
    for prev in same_tag:
        ratio = fuzz.ratio(result.text.lower(), prev.lower()) / 100
        if ratio >= 0.70:               # sabit, daha katı
            return DupVerdict(True, f"tag_overlap({result.topic_tag},{ratio:.2f})")

    return DupVerdict(False)
```

### 5.3 Insert atomikliği

Yukarıdaki Section 5.1 akışını netleştirme:

| Durum | DB davranışı |
|---|---|
| Dedup duplicate (retry tetikler) | `INSERT ... status='discarded', short_id=NULL` (5.1 loop içinde) |
| Dedup novel + render başarılı | `INSERT ... status='used', short_id=<short.id>` (`_finalize_generator_run` içinde) |
| Dedup novel + render başarısız | `INSERT ... status='discarded', short_id=NULL` + run failed (try/except ile finalize aşamasında) |

Bu sayede DB'deki `used` kayıtları = gerçekten yayınlanmış shorts; `discarded` kayıtları telemetri (kanal "ne kadar zorlanıyor") için kullanılır.

**Önemli:** Forbidden listesi sorgusunda `WHERE status = 'used'` filtresi var (Section 2.5), discarded kayıtlar Sonnet'e gönderilmez — bu sayede kanal yeni denemelerinde discarded içerik tekrar üretilebilir (engellemek mantıksız, zaten üretilmemişti).

### 5.4 Edge case'ler

| Durum | Davranış |
|---|---|
| İlk run (DB boş) | Forbidden boş, topic_dist boş → Sonnet özgürce üretir, dedup hep "novel" |
| Concurrent run | Mevcut `FileLock` kanal başına tek run → güvenli |
| Hash collision (UNIQUE conflict) | INSERT exception → retry tetiklenir (defensive try/except) |
| Sonnet boş yanıt | `run_json` 2 kez retry, sonra exception → run failed |
| Tüm retry'lar duplicate | `GeneratorRetryExhausted` → run failed, log'da net mesaj |
| `forbidden_lookback=0` | Forbidden listesi boş gönderilir, sadece DB-side dedup koruma yapar |

### 5.5 Sabitler vs config

- `fuzzy_threshold` (text düzeyi): config'lenebilir, default `0.85`
- Tag-overlap threshold (`0.70`): **sabit kod** (kullanıcı detayını bilmek istemez)
- `recent_by_tag` window (`7 gün`, `limit 20`): **sabit kod**
- `max_retries`: config'lenebilir, default `3`

---

## 6. UI Değişiklikleri

### 6.1 Yeni Kanal Wizard (`channels/new.html.j2`)

Formun en üstüne radio grup eklenir:

```html
<fieldset>
  <legend>Kanal Türü</legend>
  <label><input type="radio" name="content_source" value="rss" checked> 📰 Haber (RSS)</label>
  <label><input type="radio" name="content_source" value="generator"> ✨ Üretici (Sonnet)</label>
</fieldset>
```

Alpine ile dinamik form:

- `content_source == "rss"` (default): `keywords` zorunlu, mevcut akış
- `content_source == "generator"`: `keywords` gizlenir, `generator_topic` (textarea) zorunlu görünür

`/channels/new/generate` endpoint'i `content_source`'a göre dallanır:
- RSS → mevcut DNA üretimi (Opus, keyword-based)
- Generator → DNA üretimi (Opus, `generator.topic` keyword analoğu olarak verilir)

`/channels/new/save` endpoint'i:
- RSS → mevcut ChannelConfig
- Generator → ChannelConfig + GeneratorConfig

### 6.2 Edit Sayfası (`channels/edit.html.j2`)

Alpine `x-show` ile koşullu alanlar:

**Sadece RSS kanalları için görünür:**
- `keywords`
- `min_score`
- `max_candidates_per_run`

**Sadece generator kanalları için görünür (yeni grup):**
- `generator.topic` (textarea)
- `generator.forbidden_lookback` (number, default 50)
- `generator.max_retries` (number, default 3)
- `generator.fuzzy_threshold` (number, opsiyonel)

**İki türde de ortak:** schedule_cron, duration_s, handle, enabled, DNA editör, CTA, Run history, sil butonu, DNA Yenile, Şimdi üret.

`channel_edit.save()` POST handler'ı `content_source`'a göre yeni `GeneratorConfig` örneği oluşturur ve `ChannelConfig.generator`'a yazar.

**Kanal türü değiştirilemez** — edit sayfasında "Tür: ✨ Üretici (değiştirilemez)" şeklinde read-only gösterilir. Tür değiştirmek isteyen yeni kanal açar.

### 6.3 Kanal Listesi (`channels/list.html.j2` + `channel_row.html.j2`)

Slug sütununa kanal türü badge'i eklenir:

```html
<td>
  {{ c.slug }}
  {% if c.content_source == 'generator' %}
    <span title="Generator (Sonnet)" class="text-claude-accent">✨</span>
  {% else %}
    <span title="RSS" class="text-claude-muted">📰</span>
  {% endif %}
</td>
```

### 6.4 "Test Üret" Butonu (Bonus)

Generator kanallarının edit sayfasında, "Şimdi üret" / "DNA Yenile" yanına yeni buton:

```
[▶ Şimdi üret]   [🧪 Test örnek üret]   [↻ DNA Yenile]   [Sil]
```

**Davranış:**
- POST `/channels/<slug>/generator-test` endpoint'i
- Sonnet çağrısı yapılır (forbidden + topic_dist DB'den)
- Dedup kontrolü **yapılmaz**, DB'ye **yazılmaz**
- HTMX ile inline panel'de sonuç gösterilir: text, topic_tag, script JSON, image_keywords
- Kullanıcı `generator.topic` cümlesini iterasyonla iyileştirir

Sadece generator kanallarında görünür.

---

## 7. Test Stratejisi

### 7.1 Birim testler

| Test | Konum |
|---|---|
| `text_hash` normalize edilmiş hash döndürür (paraphrase yakalar) | `tests/test_generator_hash.py` |
| `check_duplicate` exact hash → True | `tests/test_generator_dedup.py` |
| `check_duplicate` fuzzy >= threshold → True | `tests/test_generator_dedup.py` |
| `check_duplicate` same-tag + medium fuzzy → True | `tests/test_generator_dedup.py` |
| `check_duplicate` farklı tema, düşük benzerlik → False | `tests/test_generator_dedup.py` |
| `build_generator_prompt` forbidden list dahil eder | `tests/test_generator_prompt.py` |
| `build_generator_prompt` topic distribution dahil eder | `tests/test_generator_prompt.py` |
| `build_generator_prompt` tüm 5 dilde sabit ifade üretir | `tests/test_generator_prompt.py` |
| `GeneratorResult` validasyon (topic_tag regex, length sınırları) | `tests/test_generator_result.py` |
| `ChannelConfig` `content_source` Literal validasyonu | `tests/test_config_generator.py` |
| `ChannelConfig` `content_source=generator` ise `generator` zorunlu | `tests/test_config_generator.py` |

### 7.2 Entegrasyon testleri

| Test | Konum |
|---|---|
| `_run_generator` mock Sonnet ile uçtan uca (1 başarılı + DB kayıt + render hint) | `tests/test_pipeline_generator.py` |
| Retry exhaustion: 3 deneme de duplicate → `GeneratorRetryExhausted` | `tests/test_pipeline_generator.py` |
| Mevcut RSS testleri **bozulmadan** geçer | (regresyon kontrolü) |

### 7.3 Web UI testleri

| Test | Konum |
|---|---|
| `/channels/new` content_source radio render eder | `tests/test_web_channel_new_generator.py` |
| `/channels/new/save` generator kanalı yaratır (yaml + dna + css) | `tests/test_web_channel_new_generator.py` |
| `/channels/<slug>/edit` generator alanlarını gösterir | `tests/test_web_channel_edit_generator.py` |
| `/channels/<slug>/generator-test` Sonnet'i çağırır, DB'ye yazmaz | `tests/test_web_generator_test_endpoint.py` |
| `/channels` listesinde ✨ badge görünür | `tests/test_web_channels_list.py` |

---

## 8. Geriye Uyumluluk

| Senaryo | Davranış |
|---|---|
| Mevcut RSS YAML'ları (`content_source` yok) | Default `"rss"` atanır, hiçbir şey değişmez |
| Mevcut DB (generated_items yok) | İlk açılışta `init_db` tabloyu yaratır |
| Mevcut `Settings.fuzzy_dedup_threshold` | Generator'da fallback olarak kullanılır |
| Mevcut testler (183 adet) | Hiçbiri bozulmamalı (regresyon koruması) |

## 9. Açık Sorular / Phase 5

- Manuel havuz besleme (kullanıcı söz listesi yapıştırır → bot havuzdan seçer)
- Reddit / Wikipedia / Quote API'leri
- Embedding-tabanlı semantic dedup (büyük DB'lerde fuzzy yetmez olursa)
- Kanal tür dönüşümü (RSS → generator data migration)
- "Konu tükendi" UI alarmı (sürekli `GeneratorRetryExhausted` alan kanallara dashboard uyarısı)
- Multi-output run: 1 run'da 3 short üretmek (`max_candidates_per_run` analoğu)

## 10. Kabul Kriterleri

✅ Spec, **şu kriterler** sağlandığında tamamlanmış sayılır:

1. Yeni "sevgi-sozleri" kanalı UI'dan oluşturulabilir, generator modu seçilebilir.
2. "▶ Şimdi üret" butonuyla Sonnet'ten yeni içerik üretilir, DB'ye `generated_items` olarak düşer.
3. İkinci run'da farklı bir içerik üretilir (forbidden list işliyor).
4. Aynı `text_hash`'i Sonnet ikinci kez üretirse retry tetiklenir, sonunda farklı içerik döner.
5. `tests/` altındaki yeni testlerin tamamı yeşil, mevcut 183 test bozulmamış.
6. RSS kanalları (`son-dakika`, `spor-short-de`) hiçbir değişiklik göstermez, eskisi gibi çalışır.
7. Render edilen short'larda görsel + metin tutarlı (Sonnet'in `image_keywords`'i metinle uyumlu).
8. UI'da generator kanalları `✨` badge ile ayırt edilir; "Test Üret" butonu çalışır.

## 11. Implementation Notları

- Yeni dosyalar: `src/short_bot/generator.py`, `src/short_bot/web/routes/generator_test.py` (yeni endpoint için)
- Genişletilecek dosyalar: `src/short_bot/config.py`, `src/short_bot/db.py`, `src/short_bot/pipeline.py`, `src/short_bot/web/routes/channel_new.py`, `channel_edit.py`, `channels.py`
- Genişletilecek template'ler: `channels/new.html.j2`, `channels/edit.html.j2`, `_partials/channel_row.html.j2`
- 5 dil için `prompt_phrases.py` (yoksa yeni dosya)
- 0 dış dependency eklenir (rapidfuzz + sha256 zaten mevcut)
