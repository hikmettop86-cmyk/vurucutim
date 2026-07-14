# Kanal Kurma Ajanı — Tasarım

**Tarih:** 2026-07-14
**Dal:** `feature/electron-installer` (yayınlanmayacak)
**Alt proje:** 3'ün 3'ü. Öncekiler: dil geçirgenliği (bitti), konu üretimi (bitti).

## Amaç

Kullanıcı bir cümle söylesin, sistem kanalı kursun:

> *"Almanca bir shorts kanalı istiyorum, bana niş bul"*
> *"Almanca bira bahçesi üzerine kanal"*

## Neden şimdi mümkün

İki ön koşul bu oturumda tamamlandı:

- **Dil geçirgenliği** — Almanca kanal artık gerçekten Almanca. (Öncesinde ekrana Türkçe
  "ABONE OL" çipi basıyor, rozette "BİER GARTEN" yazıyor ve anlatım metnindeki `ä`
  siliniyordu — üçü de sessizce.)
- **Konu üretimi** — banka artık YouTube API anahtarı ve referans kanal olmadan da
  doluyor. Yeni bir kanal, sıfırdan, kanıtsız da kaliteli konu üretebiliyor.

Bunlar olmadan ajanın kurduğu kanal bozuk çalışırdı ve bunu hiçbir şey söylemezdi.

## Mevcut parçalar — ajan bir ORKESTRATÖR

| Adım | Var mı? |
|---|---|
| Niş bul + YouTube outlier kanıtıyla ölç | `web/niche_finder.find_niches_data` — **VAR** |
| Dil paketi (yoksa üret) | `lang_pack` + `lang_pack_gen` — **VAR** |
| **Hedef dilde konuşan ses seç** | **YOK — tek gerçek yeni parça** |
| Kimlik: arketip, palet, font, ton | `dna.generate_dna` — **VAR** |
| Kanal adı | **YOK** (küçük, LLM) |
| Kanal YAML | `config.save_channel` — **VAR** |
| Konu bankası tohumlama | `topic_miner.refresh_topic_bank` — **VAR** |

## Ölçüm — ses kütüphanesi

ai33 `/v3/voices` gerçek çağrısı (5 sayfa, `provider=elevenlabs`):

```
605 ses
dil dağılımı: en=365, hi=38, es=34, vi=22, pt=20, de=18, ko=15, fr=15, ja=12, it=10, tr=8
```

Her kayıt: `voice_id, name, description, language, locale, gender, age, accent,
category, use_cases, descriptives, tags, preview_url`.

Almanca 18 ses **var** — ajanın en kritik bağımlılığı karşılanıyor. Ve seçim önemsiz
değil: seslerden biri *"Mark – Sales Executive"*, biri *"Daniel – Teacher,
explainer-in-chief"*. Faceless ilginç-bilgi kanalına ikincisi uyar; "ilk erkek sesi al"
gibi bir kural bunu bilemez.

## Mimari

### Katman 1 — Ses seçici (YENİ)

`src/short_bot/voice_picker.py`

```python
class VoiceChoice(BaseModel):
    voice_id: str
    name: str
    reason: str          # NEDEN bu ses (kullanıcı planda görecek)

def voices_for(language: str, *, api_key: str, session=None) -> list[dict]:
    """ai33 ses kütüphanesinden HEDEF DİLDE konuşan sesler.

    Sayfalama şart: kütüphane 605 ses ve varsayılan sayfa çoğunlukla İngilizce.
    """

def pick_voice(language: str, niche: str, *, voices: list[dict], llm) -> VoiceChoice:
    """Nişe en uygun ANLATICI sesi seç. LLM'e ad + açıklama + cinsiyet + aksan gider."""
```

**HEDEF DİLDE SES YOKSA `RuntimeError`.** İngilizce sese sessizce düşmek YASAK: Almanca
kanal İngiliz aksanıyla okur ve bunu hiçbir şey söylemez — düzeltmeye çalıştığımız
sessiz bozulmanın aynısı.

LLM yoksa: listenin ilk sesi + `reason="model seçemedi, ilk uygun ses"` (dürüst).
Ses seçimi kanalı bozmaz, yalnız iyileştirir — burada durmaya gerek yok.

### Katman 2 — Kanal planı (YENİ)

`src/short_bot/channel_agent.py`

```python
class ChannelPlan(BaseModel):
    language: str
    niche: str                  # generator.topic olacak
    evidence: str = ""          # "8 outlier; en iyi 2,1M izl / 12K abone (175x)"
    name: str
    slug: str
    voice: VoiceChoice
    dna: DnaSpec
    highlight_color: str
    sample_topics: list[str] = []   # GERÇEKTEN üretilmiş, doğrulama kapısından geçmiş

def build_plan(niche, *, language, cfg_dir, settings, secrets,
               llm=None, dna_call=None) -> ChannelPlan
def apply_plan(plan, *, cfg_dir, templates_dir, db_path, settings,
               secrets, llm=None) -> str      # slug döner
```

`build_plan` HİÇBİR ŞEY YAZMAZ (dil paketi hariç — o dil düzeyinde, kanala ait değil).
`apply_plan` YAML'ı yazar ve konu bankasını tohumlar.

**Niş bulma ajanın içinde DEĞİL:** `niche_finder` zaten var ve panelde kullanılıyor.
Ajan bir niş cümlesi ALIR. Belirsiz istekte panel önce niş bulucuyu koşturur, kullanıcı
seçer, sonra plan kurulur. (Ayrım net: niş bulmak bir ARAMA, plan kurmak bir İNŞA.)

### Katman 3 — Panel

`/channels/agent` (yeni rota + şablon):

1. Metin kutusu + dil seçici + iki düğme: **"Niş bul"** / **"Bu nişi kullan"**
2. "Niş bul" → `niche_finder.find_niches_data` (kanıt puanlı kartlar) → kullanıcı seçer
3. Seçim → `build_plan` → **Plan ekranı** (tek sayfa, aşağıdaki her şey görünür)
4. **"Kur"** → `apply_plan` → `/channels/<slug>`

Uzun sürüyor (~2-3 dk: dil paketi + ses + DNA + örnek konular) → daemon thread +
HTMX poll. `reel_new.py`'nin niş bulucu iş kuyruğu deseni AYNEN kullanılır
(`_niche_jobs` + `/niche-status/<job_id>`).

Plan ekranında görünenler: niş, kanıt (ya da "kanıt yok"), kanal adı, **seçilen ses ve
NEDEN**, arketip/palet/font, 3 örnek konu.

## Hata hâlleri

| Durum | Davranış |
|---|---|
| Dil paketi yok | **ÜRETİLİR** (Sonnet 5, ~2 dk). Üretilemezse plan kurulmaz, sebep söylenir. |
| Hedef dilde ses yok | **RuntimeError.** İngilizceye sessizce düşmek YASAK. |
| ai33 anahtarı yok | RuntimeError — ses olmadan reel kanalı kurulamaz (voice_id zorunlu). |
| YouTube anahtarı yok | Niş bulucu AI moduna düşer. Planda `evidence=""` → panel "kanıt yok" yazar. **Yalan söylemez.** |
| LLM ses seçemedi | İlk uygun ses + dürüst gerekçe. Kanal yine kurulur. |
| DNA üretilemedi | RuntimeError — kimlik olmadan kanal kurulmaz. |
| Örnek konu üretilemedi | Plan `sample_topics=[]` ile kurulur; panel uyarır. Banka sonra dolar. |
| Slug çakışması | `reel_new._unique_slug` zaten hallediyor — aynı yardımcı kullanılır. |

## Test

**Ses seçici:**
- `voices_for("de")` yalnız Almanca sesleri döndürür (sahte `list_voices`)
- sayfalama: 605 sesin hepsi taranır, ilk sayfada durulmaz
- hedef dilde ses YOK → `RuntimeError` (İngilizce sese DÜŞMEZ — testin adı bunu söyler)
- LLM nişe uygun anlatıcıyı seçer (sahte LLM, "Teacher" vs "Sales Executive")
- LLM yoksa ilk ses + dürüst gerekçe
- LLM geçersiz `voice_id` döndürürse listeden ilk ses (uydurma id kabul edilmez)

**Plan:**
- `build_plan` hiçbir dosya YAZMAZ (dil paketi hariç)
- dil paketi yoksa üretilir
- `sample_topics` gerçekten `propose_topics` + `verify_topics`ten geçer
- kanıt yoksa `evidence=""` (uydurma kanıt yazmaz)
- `apply_plan` YAML yazar, konu bankasını tohumlar, slug döndürür
- `apply_plan` autopilot'u AÇMAZ (spec: kullanıcı açar)
- `apply_plan` seri/ark KAPALI kurar

**Panel:**
- `/channels/agent` sayfası açılır
- plan ekranı ses gerekçesini GÖSTERİR
- "Kur" kanalı oluşturur ve `/channels/<slug>`e yönlendirir
- kanıt yoksa panel "kanıt yok" der

**Gerçek koşu (kalite kapısı, `@pytest.mark.slow`):**
- Almanca "bira bahçesi" için gerçek plan kurulur: ses Almanca mı, örnek konular
  Almanca ve somut mu, DNA üretildi mi?

## Kapsam dışı (bilerek)

- **Autopilot'u ajan AÇMAZ.** YouTube'a otomatik yükleme büyük bir taahhüt; kullanıcı
  bilinçli olarak açar.
- **Referans kanal önerisi YOK.** Ölçüldü: artık gerekmiyor (Sonnet kanıtsız iyi konu
  yazıyor) ve kullanıcının mevcut referansları zaten nişe uymuyordu (bir bilim-tarihi
  kanalının referansları "Uykuda AirPod Yutarsan Ne Olur?" getiriyordu).
- **Seri/ark KAPALI** gelir. Kullanıcı açar.
- **Mevcut `/channels/new-reel` sihirbazı DURUYOR** — elle tam kontrol isteyen için.
