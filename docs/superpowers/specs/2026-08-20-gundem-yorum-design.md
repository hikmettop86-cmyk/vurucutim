# Gündem Yorum — Google Trends + Cartesia seslendirme + günlük derleme

Tarih: 2026-08-20
Bağlam: `gundem` kanalı (6 sn Flaş kartı, `2026-08-20-google-trends-kanali-design.md`)
bir politika değerlendirmesinden geçti: tam otomatik "manşet + özet" kartı,
YouTube'un 2025 "inauthentic content" tanımına yakın. Kullanıcı 1+3+4+5+6
maddelerini seçti ve tam otonom yetki verdi.

## Karar özeti

| # | madde | karar |
|---|---|---|
| 1 | Trend verisi gövdede | YAPILDI (`c50d4d3`): gövdenin son cümlesi "neden gündemde", KJ'de hacim |
| 3 | Tempo | YAPILDI: `trends_min_volume: 5000`, günde 6 koşu, yükleme elle |
| 4 | Bağlam cümlesi | YAPILDI: gövdede tek kıyas/sıra/büyüklük cümlesi, yorum değil |
| 5 | Seslendirmeli kardeş format | **BU SPEC — "Gündem Yorum"**: Cartesia TTS, tarafsız-ama-görüşlü yorumcu, 6 sn karttan AYRI format + UI |
| 6 | Uzun-form derleme | **BU SPEC**: "Türkiye bugün ne aradı" günlük derleme, ≥ 3 dk 10 sn (Shorts sayılmaz) |

Kullanıcının ek istekleri:
- TTS = **Cartesia** (`D:\dene\faceless-2` içindeki entegrasyonun tüm özellikleri UI'ya taşınsın).
- Yorumcu **gerçekten tarafsız**, ama **kendi yorumunu katar**; "çaktırmadan" sevilecek
  bir yorum dili.
- Bu format 6 saniyelik kartlardan **bağımsız kart yapısı ve kurulumla** UI'da ayrı dursun.

## Üç alt proje

Her biri kendi başına çalışır, sırayla uygulanır; hepsi aynı dal
(`feature/electron-installer`), ayrı commit dizileri.

- **B. Cartesia TTS sağlayıcısı** (altyapı): `tts/cartesia_client.py`, `VoiceConfig.provider`,
  gizli anahtar + ayarlar sayfası, ses listesi/klon/sağlık uçları, panel ses kartı.
- **C. Gündem Yorum formatı**: anlatım yazarı (yorumcu personası + çok-kaynak),
  `flas-narrator.html.j2`, kanal kurulum sihirbazı + düzenleme sayfası, kanal listesinde
  ayrı rozet/yönlendirme, `gundem-yorum` kanalı.
- **D. Günlük derleme**: `compilation.py`, intro/outro kartı, gece cron'u, panel düğmesi,
  uzun-form metadata (Shorts etiketi YOK).

---

## B. Cartesia TTS sağlayıcısı

### Doğrulanmış API gerçekleri (2026-08-20, canlı)

- Başlık `Cartesia-Version: 2026-08-14`, `Authorization: Bearer <key>`.
- Model: `sonic-3.5` kararlı varsayılan (faceless-2 ölçtü: `sonic-3.6` diye kimlik YOK →
  404; `sonic-2`/`sonic` emekli; `sonic-preview` = duyurudaki 3.6). Model listesi ucu
  yok; adaylar 2 karakterlik sentezle sınanır (kullanıcı düğmesiyle, otomatik değil).
- `POST /tts/bytes` → mp3 baytları; zaman damgası VERMEZ.
- `POST /tts/sse` + `add_timestamps: true` → **yalnız `raw` container** (ölçüldü: mp3
  isteyince 400). Olaylar: `chunk` (base64 PCM), `timestamps`
  (`word_timestamps: {words, start, end}`), `done`. `pcm_s16le` 44100 Hz ile
  doğrulandı; fikstür `tests/fixtures/cartesia_sse_tr.txt` (8 kelime, 3,1 sn).
- `generation_config.speed` ∈ [0,6 – 1,5], `volume` ∈ [0,5 – 2] (faceless-2 ölçtü;
  aralık dışı 400). `language` ile `locale` birlikte gönderilemez.
- `GET /voices?limit=100&language=tr&expand[]=preview_file_url` → 9 Türkçe ses
  (Leyla, Emre, Aylin, Taylan, Murat, Elif, Aykut, Azra + kullanıcının `TozluKaput`
  klonu); alanlar `id, name, description, language, gender, is_owner, is_pro,
  preview_file_url`; `is_pro` = 1,5 kredi/karakter. Kredi harcamaz.
- `GET /voices/<id>` sağlık yoklaması: kredi harcamaz. faceless-2 buna 2 karakterlik
  model sınaması ekledi (`model_not_found` yakalansın diye) — taşınır.
- `POST /voices/clone` multipart (`clip`, `name`, `language` zorunlu; ≤ 10 sn, uzun
  klip ffmpeg ile 9 sn'ye kırpılır ve kırpıldığı bildirilir).
- Kredi: **1 karakter = 1 kredi**, $5 plan = 100.000/ay, devretmez. 40 sn'lik yorum
  ≈ 100 kelime ≈ 650 karakter → günde 6 video ≈ 4.000 kredi ≈ ayda 120.000 →
  **$5 plan yetmez, bir üst plan gerekir**; modül her sentezde harcananı loglar ve
  `data/cache/cartesia_usage.json`'da aylık sayaç tutar (panelde gösterilir).

### Tasarım

`src/short_bot/tts/cartesia_client.py` — `ai33_client` ile aynı sözleşme, artı zaman damgası:

```python
BASE_URL = "https://api.cartesia.ai"; VERSION = "2026-08-14"; DEFAULT_MODEL = "sonic-3.5"
KNOWN_MODELS = ("sonic-3.5", "sonic-3", "sonic-preview")
SPEED_RANGE = (0.6, 1.5); VOLUME_RANGE = (0.5, 2.0)

class CartesiaError(RuntimeError); CartesiaAuthError; CartesiaRateLimitError; CartesiaTimeoutError

def resolve_cartesia_api_key(secrets) -> str            # secrets["cartesia_api_key"] | env CARTESIA_API_KEY
def synthesize(text, *, voice_id, api_key, out_path, speed=1.0, volume=1.0, language="tr",
               model=DEFAULT_MODEL, emotion="", session=None, timeout_s=180) -> SynthesisResult
    # SSE raw pcm_s16le 44100 → WAV (out_path uzantısı .wav'a çevrilir; dönen yolu kullan)
    # SynthesisResult(path, words: list[TimedWord], duration_s, chars_spent)
def parse_sse(text) -> tuple[bytes, list[TimedWord]]    # saf, fikstürle test edilir
def health_check(*, voice_id, api_key, model=DEFAULT_MODEL, probe_model=True) -> str  # "healthy"|"no-key"|"auth"|"no-voice"|"model"|"error"
def list_voices(*, api_key, language=None, q=None, limit=100) -> list[dict]
def probe_models(*, api_key, candidates=KNOWN_MODELS) -> list[dict]   # 2 kredi/aday, düğmeyle
def clone_voice(*, api_key, name, clip_path, language, description="") -> str  # ≤10 sn kırpma
def record_usage(chars, *, cache_dir) / month_usage(cache_dir) -> int
```

`TimedWord` (`short_bot.narration`) zaten var; `build_timeline(narration, words, duration_s)`
Cartesia kelimeleriyle doğrudan çalışır → **whisper yolu atlanır** (`transcribe_words`
çağrılmaz). Metin parçalama: anlatım ≤ 1.500 karakter, tek istek; 3.000'i aşarsa
cümle sınırından bölünür ve zaman damgaları ofsetlenir.

`VoiceConfig` yeni alanlar (varsayılanlar mevcut kanalları bozmaz):

```python
provider: Literal["ai33", "cartesia"] = "ai33"
model: str = ""            # cartesia: boşsa sonic-3.5
volume: float = 1.0        # cartesia 0.5-2.0
emotion: str = ""          # cartesia ses yönergesi (model destekliyorsa transcript önüne etiket)
```

`speed` sınırı cartesia'da 0,6-1,5'e kırpılır ve loglanır (ai33 aralığı 0,5-1,5 kalır).

`voiced.py`: `VoicedDeps` sağlayıcıya göre çözülür — `resolve_tts(provider)` →
(`health_check`, `synthesize`). Cartesia yolunda `SynthesisResult.words` varsa
`transcribe_words` atlanır; yoksa (eski ai33) mevcut whisper/orantılı yol aynen.
`voiced.py` artık `synthesize`'ın döndürdüğü yolu kullanır (ai33 mp3, cartesia wav).

Panel:
- Ayarlar → API anahtarları: `cartesia_api_key` alanı (maskeli, temizle), "Bağlantıyı
  sına" (kredi harcamaz), aylık kredi sayacı.
- Kanal ses kartı (`edit.html.j2` + `edit-yorum`): sağlayıcı seçici (ai33 | Cartesia);
  Cartesia seçilince: ses açılır listesi (dil süzgeçli, `is_pro` rozeti, önizleme
  `<audio>`), model seçici (bilinen 3 + "Modelleri sına" düğmesi), hız 0,6-1,5, ses
  seviyesi 0,5-2, duygu/yönerge metni, ses klonlama (dosya yükle → id). Rotalar
  `/api/cartesia/voices`, `/api/cartesia/models/probe` (POST), `/api/cartesia/clone` (POST),
  `/api/cartesia/health` (POST).
- `channel_edit.py` POST'u yeni alanları taşır (taşımazsa kayıt sessizce ai33'e döner —
  bilinen tuzak).

### faceless-2'den taşınanlar (ajan envanteri, `src/providers/cartesia-tts.js` + `ui/js/app.js`)

Taşınan davranışlar:
- Sürüm başlığı ve taban URL ayarlanabilir; ölçülmüş model beyaz listesi
  (`sonic-3.5 / sonic-3 / sonic-preview`), "Modelleri sına" (aday başına 2 kredi,
  yalnız düğmeyle; çalışmayan model listeden silinmez, sebebiyle devre dışı gösterilir).
- Hız [0,6-1,5] ve ses seviyesi [0,5-2] kırpma + uyarı logu; `generation_config`
  alan yoksa gövdeye yazılmaz; `language`/`locale` karşılıklı dışlama; resmî
  `voice: {mode: "id", id}` biçimi.
- Cümle sınırlı parçalama (paragraf > cümle > boşluk > sert kesme; hedef 3.000), sıralı
  gönderim, < 512 bayt yanıt = hata, geçici dosyalar `finally` ile temizlenir.
- Kredisiz sağlık yoklaması (`GET /voices/<id>`) + 2 kredilik model sınaması; 7 durumlu
  mesaj haritası (`ok / yetki / key-yok / ses-yok / ses-bulunamadi / model-yok / hata`).
- Ses kütüphanesi: **dil süzgeci şart** (süzgeçsiz ilk 100 seste Türkçe 0; `language=tr`
  ile tam liste), `is_pro` (1,5×) rozeti, "kendi klonun" etiketi; hata `{voices, error}`
  sözleşmesiyle UI'yı kırmaz.
- Instant clone: format beyaz listesi, 10 sn tavanı için ffprobe ölç + ffmpeg `-ss 0.5 -t 9`
  yeniden kodlayarak kırp, kırpıldığını bildir; sağlayıcı-namespace'li klon önbelleği.
- Sert-dur: Cartesia başarısızsa başka sağlayıcıya DÜŞÜLMEZ (ses evreni farklı — kanalın
  sesi sessizce değişmesin); sağlayıcıya göre doğru anahtar sorulur.
- Kredi logu: sentez öncesi "X karakter ≈ aylık bütçenin %Y'si"; UI'da motor seçici, ses
  listesi, ses dili süzgeci, model seçici, klon düğmesi, hız, "Test et (kredi harcamaz)".

faceless-2'de eksik/kusurlu olup short-bot'ta **doğru yapılacaklar**:
1. `volume` UI'da ve zincirde yoktu (sağlayıcıda hazırdı) → `VoiceConfig.volume` + panel.
2. `language` sentez gövdesine hiç gitmiyordu (Cartesia dili tahmin ediyordu) → kanal dili
   her istekte gönderilir.
3. Model seçimi build yoluna düşüyordu → `VoiceConfig.model` tek kaynak.
4. Retry yoktu → 429/5xx'te 3 deneme (2/4/8 sn).
5. Zaman damgası Whisper'dan geliyordu → SSE `add_timestamps` ile doğrudan.
6. `preview_file_url` çekilip kullanılmıyordu → ses listesinde `<audio>` önizleme.
7. Kredi muhasebesi yalnız konsoldaydı → `data/cache/cartesia_usage.json` aylık sayaç +
   panelde gösterim.
8. UI hız tabanı 0,5 iken API 0,6 → panel aralığı API'yle aynı.
"Nudge" (`.env.yedek-nis-nudge-*`) TTS değil, niş/dönem yönlendirmesi — kapsam dışı.
Sayı/tarih okunuşu ön işleme faceless-2'de de yok; Cartesia Türkçe sayıları doğru okuyor
(fikstürde "üç nokta bir" yazıldı; gerçek koşuda rakamla sınanacak, gerekirse
`text_normalize`'a okunuş katmanı eklenir).

---

## C. Gündem Yorum formatı

### Ne üretir

Dikey 35-50 sn video: Flaş kartının kimliği (kırmızı logo bandı, SON DAKİKA şeridi,
fotoğraf, manşet) aynen durur; üstüne **yorumcu anlatımı** gelir; beyaz KJ satırı
konuşulan beat'in `on_screen` kartına göre değişir (stadium-narrator deseni); karaoke
YOK (kullanıcının önceki kararı); SIRADA ticker'ı 6 sn karttaki gibi kalır.

### Yorumcu personası — "tarafsız ama görüşlü"

Persona metni `lang_pack` personaları gibi düzenlenebilir; varsayılan (tr):

> Sen Türkiye'nin gündemini yorumlayan, kimsenin adamı olmayan bir sokak bilgesisin.
> Taraf tutmazsın ama görüşsüz de değilsin: olayı sade anlatır, herkesin aklındaki
> soruyu sen sorar, kimsenin bağlamadığı bir noktayı bağlar, sonunda adil ama net bir
> hüküm verirsin. Vatandaşın tarafındasın — kurumların değil, partilerin değil. Hafif
> mizah olur, alay olmaz. Acı haberde saygılısın.

Prompt kuralları (`narration_writer.build_yorum_prompt`):
1. **Hook** = herkesin aklındaki soru (2 sn), tarih/“bugün” ile başlamaz.
2. **Olgu katmanı**: 2-3 cümle, her olgu kaynağa bağlı ("Milliyet'e göre", "Kandilli
   diyor ki") — en az 2 farklı kaynak adı geçer (trendin 3 haberi çekilir, bkz. çok-kaynak).
3. **Bağlantı cümlesi**: "kimsenin bağlamadığı nokta" — yalnız kaynaklardaki olgulardan.
4. **Denge cümlesi**: karşı tarafın/başka okumanın bir cümlesi.
5. **Hüküm**: net, adil, birinci tekil ("bence"), kimseye hakaret yok.
6. **Kapanış sorusu**: izleyiciye tek soru (yorum daveti; "abone ol" YOK).
7. **Neden gündemde**: Trends verisiyle tek cümle (hacim/ilişkili aramalar) — bu kanalın
   imzası.
8. Yasaklar: parti/lider adıyla taraf tutma, küfür, "şok/bomba", kesin olmayan iddiayı
   kesin söylemek, felakette espri, izleyiciyi aşağılama.
9. Kelime bütçesi sese göre (`WORDS_PER_SECOND_BY_LANG` + seçilen sese ölçüm), hedef
   35-50 sn.

"Çaktırmadan sevilecek" = 2-4-5-6 maddeleri: kaynağa bağlı dürüstlük + karşı tarafa
bir cümle + net hüküm + soru. Propaganda değil, güven.

### Çok-kaynak

`trending_now.trending_as_news_items` her trendin 3 haberini görüyor ama yalnız ilkini
taşıyordu. `NewsItem.extra_links: tuple[str, ...] = ()` eklenir (varsayılanlı); trend
kaynağı 2. ve 3. makale URL'lerini doldurur. Yorum üretiminde `extract_article` bu
bağlantılara da uygulanır (her biri ≤ 1.500 karakter, başarısız olan atlanır) ve
prompt'a `ADDITIONAL SOURCES` olarak girer (kaynak adıyla). 6 sn kart yolu değişmez.

### Şablon `templates/flas-narrator.html.j2`

`flas.html.j2`'nin kopyası + stadium-narrator'ın zamanlama katmanı: `.header .yellow`
yerine beat başına `<div class="yellow card" data-s data-e>` (aynı konum/stil), `__seek`
ile `on` sınıfı; ilerleme çubuğu `narration.duration_s`'e bağlı; FLAŞ şeridi ve ticker
animasyonları süreye göre ölçeklenir. `voiced.py`'nin arketip kademesi
(`<template>-narrator`) sayesinde ek kayıt gerekmez.

### Kanal modeli — bağımsız kurulum

Ayrı `content_source` YOK (kaynak yine `trends`); ayrım **format**: tek yerde tanımlı
`channel_format(cfg) -> "card" | "yorum" | "voiced" | "reel" | "curated"`
(`short_bot/formats.py`): `content_source == "trends" and voice.enabled` → `yorum`.
Kanal listesi partial'ları ve düzenle bağlantısı bu fonksiyonu kullanır; kanal kartında
"YORUM · Cartesia" rozeti.

Panel — `web/routes/yorum.py`:
- `GET/POST /channels/new-yorum`: ad, dil, bölge, min hacim, cron (günde N seçici),
  yorumcu personası (varsayılan metin düzenlenebilir), Cartesia ses (listeden, önizleme),
  hız/ses/model, hedef süre (35-50), müzik seviyesi. Kaydet → `slug-yorum.yaml`
  (`template: flas`, DNA = gundem'in flas DNA'sı kopyalanır, `voice.enabled: true,
  provider: cartesia`, `youtube.auto_upload: false`).
- `GET/POST /channels/<slug>/edit-yorum`: yalnız bu formatın alanları (6 sn kartın DNA/
  palet/overflow kartları YOK); üstte "Şimdi üret" ve "Günün derlemesini üret" düğmeleri;
  son 10 üretim + her biri için anlatım metni (`script.narration_text`) görünür — insan
  incelemesi kanıtı için operatör metni okuyup yükler.
- Kanal listesi "+ Gündem Yorum" düğmesi.

### `config/channels/gundem-yorum.yaml`

`gundem`'den türetilir: `slug: gundem-yorum`, `handle: '@gundem'` (aynı YouTube kanalı;
kullanıcı isterse ayırır), `content_source: trends`, `trends_region: TR`,
`trends_min_volume: 5000`, `schedule_cron: 30 8-20/3 * * *` (6 sn kartla çakışmasın
diye yarım saat kaydırılmış, günde 5), `voice: {enabled: true, provider: cartesia,
voice_id: <Taylan c1cfee3d…>, speed: 1.05, target_duration_s: [35, 50],
music_volume: 0.05, persona: <yukarıdaki>}`, `script_model: opus` (anlatım kalitesi —
Aslan Gündem+ ölçümü), `youtube.auto_upload: false`. Ses seçimi ilk koşudan sonra
kullanıcıya bırakılır (panelden değişir).

### Pipeline

`_run_rss` zaten `channel.voice.enabled` ise `_render_and_compose` → `produce_voiced_video`
çağırıyor. Değişenler: (a) `produce_voiced_video` sağlayıcıyı `voice.provider`'dan
çözer, (b) trend kanalında `write_narration` yerine `write_yorum_narration`
(persona + çok-kaynak + Trends bağlamı) — seçim `channel_format(channel) == "yorum"`,
(c) Cartesia kelimeleriyle `build_timeline`, (d) `ticker_items` voiced RenderJob'a da
taşınır.

---

## D. Günlük derleme

### Kural

Her gece 23:30 (`web/scheduler.py`'ye iş), o günün `gundem-yorum` üretimleri (silinmemiş,
`created_at` yerel gün içinde) hacme göre sıralanır; toplam süre **≥ 190 sn** ise
derleme üretilir (YouTube'da 3 dk altı dikey video Shorts sayılır; 190 sn pay bırakır).
Azsa o gün atlanır ve loglanır. Panel düğmesi aynı fonksiyonu elle çağırır (süre
yetmezse uyarı verir, zorlamaz).

### Üretim — `src/short_bot/compilation.py`

```python
def pick_day_clips(eng, channel_slug, day: date, *, tz="Europe/Istanbul") -> list[ShortRow]
def build_compilation(clips, *, channel, day, templates_dir, work_dir, out_path, ffmpeg_path, browser) -> Path
def produce_daily_compilation(channel, *, eng, day, settings, templates_dir, output_root, log) -> int | None  # short_id
```

- Intro kartı 4 sn: `templates/compilation_intro.html.j2` (Flaş kimliği: kırmızı bant,
  "TÜRKİYE BUGÜN NE ARADI" + tarih + o günün 5 manşeti listesi); outro 3 sn:
  "Yarın yine burada" + kanal adı. İkisi de mevcut `render_frames` ile çizilir.
- Klipler arası 0,4 sn siyah geçiş; ffmpeg `concat` demuxer'ı için her parça aynı
  kodek/çözünürlük/ses biçimine normalize edilir (libx264 1080×1920 30 fps, aac 44.1k
  stereo — voiced çıktılar zaten bu biçimde; intro/outro sessiz → `anullsrc`).
- Kayıt: `shorts` tablosuna satır (`rss_item_guid = "compilation:<slug>:<YYYY-MM-DD>"`,
  `title = "Türkiye bugün ne aradı? — 20 Ağustos 2026"`, `script_json` = klip kimlikleri
  ve manşetler, `duration_s`). Aynı gün ikinci kez üretilirse eski satır `deleted_at`
  alır, dosya üzerine yazılır.
- Çıktı `output/<slug>/derleme/<YYYY-MM-DD>.mp4`.

### Metadata (uzun-form)

`youtube/metadata_writer.py` `#shorts`'u zorunlu kılıyor; derleme için ayrı
`build_compilation_metadata(day, headlines, channel)`: başlık "Türkiye bugün ne aradı? —
20 Ağustos 2026 | 7 gündem", açıklama: manşet listesi + zaman damgaları (her klibin
başlangıç saniyesi → YouTube bölümleri) + kaynak adları, hashtag `#gündem #haber
#türkiye` (Shorts etiketi YOK). Yükleme: mevcut elle-yükle akışı; `auto_upload` kapalı.

---

## Hata davranışı

| durum | davranış |
|---|---|
| Cartesia anahtarı yok / 401 | voiced üretim HATA ile durur (sessizce sessiz karta düşmez — mevcut karar) |
| SSE'de `timestamps` gelmedi | kelime listesi boş → `build_timeline` orantılı dağıtım (mevcut yedek); log uyarısı |
| ses PCM < 512 bayt | hata, kredi zaten gitti — loglanır |
| 429 | 3 deneme, 2/4/8 sn bekleme; sonra hata |
| ek makale çekilemedi | atlanır; en az ana makale varsa devam |
| derleme süresi < 190 sn | atlanır (cron) / uyarı (panel) |
| aylık kredi sayacı ≥ %90 | panel sarı uyarı; üretim durmaz (kullanıcı kararı) |

## Test

- `test_cartesia_client.py`: `parse_sse` (fikstür: 8 kelime, 3,12 sn, PCM uzunluğu),
  `synthesize` (monkeypatch `requests.post` → WAV yazıldı, `words` dolu, `chars_spent`),
  hız/ses kırpma + uyarı, `health_check` durum kodları, `list_voices` eşlemesi (`is_pro`),
  `record_usage` aylık sayaç, 429 yeniden deneme.
- `test_config_voice_provider.py`: `provider/model/volume/emotion` yükle-kaydet; eski
  YAML'lar `ai33`.
- `test_voiced_cartesia.py`: `VoicedDeps` cartesia → `transcribe_words` ÇAĞRILMAZ,
  timeline Cartesia kelimelerinden; ai33 yolu değişmedi.
- `test_narration_yorum.py`: prompt kuralları (kaynak adları, denge, soru, Trends
  cümlesi), çok-kaynak bloğu, yasaklar listesi.
- `test_trends_extra_links.py`: 2./3. makale `extra_links`'e; 6 sn yol etkilenmez.
- `test_formats.py`: `channel_format` kararları.
- `test_web_yorum.py`: new/edit sayfaları render; POST → YAML (`provider: cartesia`,
  persona, cron); liste rozeti ve düzenle bağlantısı `edit-yorum`.
- `test_compilation.py`: gün seçimi (saat dilimi sınırı), 190 sn eşiği, concat komutu
  (ffmpeg monkeypatch), DB satırı/yeniden üretim, metadata (Shorts etiketi yok, bölüm
  zaman damgaları).
- Gerçek koşular: (B) Cartesia ile 1 sentez; (C) `gundem-yorum` 1 video, kare + anlatım
  metni kontrolü; (D) günün kliplerinden derleme (yetmezse test kliplerle).

## Kapsam dışı

- Karaoke altyazı (önceki kullanıcı kararı).
- Cartesia WebSocket/streaming (SSE yeterli).
- Otomatik yükleme (kullanıcı açar).
- Yatay (16:9) derleme — dikey ≥ 3 dk 10 sn uzun-form sayılıyor; ölçüm sonrası
  yeniden değerlendirilir.
