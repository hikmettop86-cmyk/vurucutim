# Google Trends kanalı — ülkenin anlık gündemini 6 saniyelik karta çevir

Tarih: 2026-08-20
Kanal: yeni `gundem` (Türkiye). Bölge kanal ayarı; yarın `language: de` +
`trends_region: DE` ile Almanya kanalı aynı kodla açılır.

## İstek

Kullanıcı Google Trends "Trendler" sayfasının (Türkiye · Son 24 saat · Tüm
kategoriler · alaka düzeyine göre) ekran görüntüsünü verdi: `şener üşümezsoy
50B+ %1000`, `ajet 20B+`, `demirovic 20B+`, `asgari ücrete ara zam 10B+`… Bu
listedeki haberlerden Galatasaray kanalının formatında (6 sn: manşet + gövde +
fotoğraf + arka plan video, `stadium`/`broadcast` türü kart) short üretilsin.

Kullanıcı kararları (sorulup onaylandı):

| soru | karar |
|---|---|
| Kapsam | **Tüm gündem** — kategori filtresi yok, hacim ne diyorsa o |
| Seçim | **Hacim sıralı + AI kapısı** — sırayı arama hacmi belirler, AI yalnız hikâyesiz trendleri eler |
| Tempo | **Her 2 saatte 1** (`0 */2 * * *`), günde 12 video |
| Kimlik | **Yeni tarafsız gündem kanalı** — GS klonu değil, nötr palet, "son dakika" tonu |
| Bölge | **Kanal ayarı** — bugün TR, yarın DE; dil ile bölge bağımsız |

## Veri kaynağı — ölçüldü

Mevcut `trends/google_daily.py` RSS ucu (`trending/rss?geo=TR`) yalnız **10
trend** veriyor ve hacmi `approx_traffic` ("200+") biçiminde kaba. Ekran
görüntüsündeki sayfa ise iç `batchexecute` API'sini kullanıyor; aynı uç
noktadan (trendspy kütüphanesinin de kullandığı) doğrudan çekildi:

- rpc `i0OFE`, yük `[null, null, "<GEO>", 0, "<lang>", 24, 1]` → **179 trend**
  (TR), her satırda: terim, başlangıç zamanı, arama hacmi (`50000`), artış
  yüzdesi (`1000`), kategori kimlikleri (`[17]`=spor, `[11]`=siyaset/hukuk…),
  arama dökümü (`["istanbul deprem", "adalar fayı", …]`), haber kimlikleri.
- rpc `w4opAf`, yük `[[[<id>, "<lang>", "<GEO>"], …]]` → haber başlığı, URL,
  kaynak, yayın zamanı, görsel. **Doğrudan yayıncı URL'si** — Google News
  yönlendirmesi yok, yani `galatasaray`'daki 3-5 sn'lik Playwright çözümleme
  adımı bu kanalda atlanır.
- DE 389, ES 295, US 474, JP 390 trend ile doğrulandı — bölge bağımsız.

Ekran görüntüsüyle birebir örtüştü (`şener üşümezsoy` 50.000 / %1000 /
"son dakika, istanbul deprem, adalar fayı").

Kısıt: API resmi değil. Biçim değişirse modül uyarı loglayıp RSS ucuna düşer
(10 trend, hacim `approx_traffic`'ten sayıya çevrilir); o da boşsa koşu
`no_candidates` ile biter. Hiçbir durumda hata fırlatmaz.

## Mimari — `content_source: "trends"`, mevcut RSS hattına takılır

Üç seçenek değerlendirildi:

- **A) Yeni kaynak, RSS hattı** (seçildi): trendler `NewsItem`'a çevrilip
  `_run_rss`'in `[2/8]`'den sonrasına verilir; dedup, puanlama, senaryo, görsel,
  render, yükleme ve öğrenme döngüsü değişmeden gelir.
- B) Trend terimlerini Google News'e anahtar kelime olarak sormak: 15 ayrı
  sorgu, her makale için gnews çözümleme, hacim kaybolur, `veyas hisse` gibi
  terimler arşiv döndürür. Daha yavaş ve daha kör.
- C) Sayfayı Playwright ile kazımak / "Dışa aktar" CSV: aynı veriyi 10 kat
  pahalıya alır, DOM'a bağımlı.

### 1. Modül `src/short_bot/trends/trending_now.py`

```python
@dataclass(frozen=True)
class TrendingEntry:
    term: str; volume: int; growth_pct: int; started_at: datetime | None
    category_ids: tuple[int, ...]; breakdown: tuple[str, ...]
    news_ids: tuple[int, ...]; active: bool

@dataclass(frozen=True)
class TrendingArticle:
    title: str; url: str; source: str
    published_at: datetime | None; image_url: str | None

def fetch_trending_now(region, *, language, hours=24, timeout_s=15) -> list[TrendingEntry]
def fetch_trending_articles(news_ids, *, language, region, timeout_s=15) -> list[TrendingArticle]
def parse_trending_response(text) -> list[TrendingEntry]      # saf, test edilebilir
def parse_articles_response(text) -> list[TrendingArticle]    # saf, test edilebilir
def trending_as_news_items(entries, articles_by_id, *, min_volume=1000, max_entries=40) -> list[NewsItem]
def fetch_trending_items(region, *, language, cache_dir, max_age_minutes=30, log) -> list[NewsItem]
```

`fetch_trending_items` dış yüz: önbellek taze ise oradan, değilse API'den;
API başarısızsa `fetch_google_daily_trends` ile RSS yedeği. Önbellek dosyası
`data/cache/trends/trending_now_<region>.json`, TTL 30 dk (2 saatlik cron
seyrek; TTL yalnız panelden art arda "Şimdi üret"te API'yi dövmemek için).

`trending_as_news_items` kuralları:

- Her trende **tek** `NewsItem`. Haberi olmayan trend elenir (hikâye yok).
- `guid` = ilk makalenin URL'si. Aynı makaleyi paylaşan iki trend satırı
  (`şener üşümezsoy` / `istanbul deprem`) GUID dedup'unda kendiliğinden birleşir.
- `title` = ilk makale başlığı (trend terimi değil — terim "ajet" gibi
  anlamsız olabilir). `link` = makale URL'si, `source` = yayıncı,
  `thumb_url` = makale görseli, `pub_date` = trendin başlangıcı.
- `description` = `"Google Trends: 50.000 arama, %1.000 artış · arama: şener
  üşümezsoy, istanbul deprem, adalar fayı · diğer başlıklar: …"`. Puanlayıcı
  ve senaryo yazarı bağlamı buradan görür.
- `trend_volume` = hacim. Sıra hacme göre azalan; `min_volume` altı atılır,
  ilk `max_entries` kalır.
- Yalnız ilk makale için `w4opAf` çağrılır; tek toplu istek (`max_entries`
  kimlik tek yükte).

### 2. Model ve config

- `NewsItem.trend_volume: int = 0` (varsayılanlı; repo'da 2 kurucu var, ikisi
  de anahtar-kelimeli — kırılmaz). Saga dersi: alanı **taşıyan** yerleri de
  ara; `ScoredItem` `item`'ı olduğu gibi taşıdığı için ek iş yok.
- `ChannelConfig.trends_region: str | None = None`. Boşsa
  `trend_region_for(language)` (tr→TR, de→DE, es→ES, en→US, fr→FR, ja→JP).
  Dolu ise ezer (`language: de` + `trends_region: AT` Avusturya gündemi).
- `content_source` izin listesine `"trends"` (Literal, `load_channel`,
  `save_channel`, `channel_edit.py:457`). `trends` kanalında `keywords` boş
  olabilir — `content_source == "rss" and not keywords` kontrolü zaten
  yalnız rss'e bakıyor.

### 3. Pipeline `_run_rss`

- `[1/8]`: `channel.content_source == "trends"` → `fetch_trending_items(
  channel.trends_region or trend_region_for(channel.language),
  language=channel.language, cache_dir=cache_dir/"trends", log=log)`;
  aksi hâlde `fetch_rss`. Yaş ve negatif-kelime filtreleri ortak.
- `[3/8]` aday kesimi `new_items[:max_candidates_per_run]` hacim sıralı
  listeyi kestiği için "en çok aranan ilk N" puanlanır.
- Seçim: trend kanalında `select_top` yerine `select_by_volume(scored,
  min_score, n)` (`scorer.py`): eşiği geçenler arasından `item.trend_volume`
  azalan, eşitlikte `score` azalan. Sonraki "görsel yoksa sıradaki aday"
  döngüsü aynı.
- Loglar: `[1/8] fetch_trending_now region=TR → 179 trend / 38 haberli /
  25 aday`, seçimde `picked volume=50000 score=8.5 | …`.
- `trend_boost` bu kanalda anlamsız; YAML'da `enabled: false`.

### 4. Puanlayıcı — trend kapısı

`build_scoring_prompt`, `channel.content_source == "trends"` ise
`_TREND_PROMPT_TEMPLATES[language]` (tr/en/de; yoksa en) kullanır. Farkı:

- **Merkez kuralı yok** — kanalın öznesi yok, her konu kanala uygun.
- Kapı ölçütü: **0-3 = hikâyesi olmayan fayda araması** (hava durumu, hisse
  fiyatı/grafik, "maç hangi kanalda", TV program/son bölüm, "ne kadar
  kazandı", sınav sonucu sorgusu, "kimdir" ama olay yok); **4-6 = olay var
  ama zayıf/yerel**; **7-10 = 6 saniyelik karta sığan net olay** (uyarı,
  teklif, zam, kaza, karar, açıklama, skor + sonuç).
- Listeye her satır için `description` eklenir (hacim + arama dökümü), böylece
  model "ajet" gibi terimi bağlamıyla görür.
- Kategori/saga ekleri aynen çalışır (kanal açarsa).

### 5. Kanal `config/channels/gundem.yaml`

```yaml
slug: gundem
name: Gündem
keywords: []            # trends kaynağında gereksiz; promptta "Türkiye gündemi"
language: tr
content_source: trends
trends_region: TR
schedule_cron: 0 */2 * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 25
max_age_hours: 24
template: broadcast
trend_boost: {enabled: false}
youtube: {auto_upload: false, min_score_for_upload: 6.0, cron_preset: every_2h}
```

Palet nötr (koyu lacivert zemin, kırmızı "SON DAKİKA" vurgusu, beyaz metin),
ton: "hızlı, net, tarafsız son dakika; abartı ve klişe yok" — `galatasaray`
DNA'sındaki yıpranmış manşet yasakları (`BOMBA`, her manşet ünlemli) aynen
taşınır. DNA bloğu panel sihirbazıyla zenginleştirilebilir; iskelet elle
yazılır (hafıza: klonlama `dataclasses.replace` ile, `create-channel` ile
değil — burada yeni kanal olduğu için YAML doğrudan).

Almanya kanalı için not (hafıza "çok dilli kanallar"): `language: de` dil
paketi var (`de.json`, `EILMELDUNG`); DNA/persona Almanca üretilmeli; panel
düzenleme POST'unun dili/paleti sıfırlama tuzaklarına dikkat. Bu spec'in kod
kapsamı değil, kanal açılış adımı.

### 6. Panel

`channels/edit.html.j2` kaynak radyo grubuna **Google Trends** seçeneği; yanında
`trends_region` açılır listesi (TR/DE/ES/US/FR/JP + "diğer" serbest ISO).
`channel_edit.py` izin listesi `("rss", "generator", "feed", "trends")`,
`trends_region` formdan okunup `ChannelConfig`'e taşınır (taşınmazsa panel
kaydı özelliği sessizce kapatır — hafızadaki DNA palet tuzağının aynısı).
Yeni-kanal sihirbazı kapsam dışı (YAGNI; kanal elle açılıyor).

### 7. Hata davranışı

| durum | davranış |
|---|---|
| `batchexecute` ağ hatası / HTTP≠200 | uyarı + RSS yedeği |
| yanıt biçimi değişti (JSON/indeks hatası) | uyarı (ilk 200 karakter) + RSS yedeği |
| RSS de boş | `no_candidates`, hata değil |
| makale çağrısı başarısız | o koşuda makalesiz trendler elenir; hepsi elenirse RSS yedeği |
| önbellek bozuk | yok sayılır, API çağrılır |
| `trends_region` geçersiz (2 harf değil) | `load_channel` `ValueError` |

### 8. Test

- `tests/test_trends_trending_now.py`: kaydedilmiş gerçek yanıt fikstürü
  (`tests/fixtures/trending_now_tr.txt`, `trending_articles_tr.txt`) ile
  `parse_*`; `trending_as_news_items` (GUID birleşme, haberi olmayan trend
  elenir, hacim sırası, `min_volume`, `description` içeriği); önbellek TTL;
  API hatasında RSS yedeği (monkeypatch).
- `tests/test_scorer_trends.py`: trend promptunda merkez kuralı yok, hacim
  satırda; `select_by_volume` sırası ve eşik.
- `tests/test_pipeline_trends.py`: `content_source=trends` kanalında
  `fetch_rss` çağrılmaz, `fetch_trending_items` çağrılır; seçim hacme göre.
- `tests/test_config_trends.py`: yükle/kaydet gidiş-dönüş, geçersiz bölge,
  keywords boş kabul.
- `tests/test_web_channel_edit_trends.py`: POST `content_source=trends` +
  `trends_region=DE` YAML'a yazılır.
- Son adım: gerçek API ile `python -m short_bot run --channel gundem` (yükleme
  kapalı), üretilen kartın ekran görüntüsü kontrol edilir.

## Kapsam dışı

- Kategori filtresi (kullanıcı "tüm gündem" dedi; `category_ids` modelde
  taşınır, filtre sonra bir satırla eklenebilir).
- Yeni-kanal sihirbazına trends seçeneği.
- Seslendirmeli (39-42 sn) varyant.
- Hacim × puan karışık sıralama (ölçüm olmadan ayar yok).
