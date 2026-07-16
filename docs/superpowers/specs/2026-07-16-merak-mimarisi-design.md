# Merak Mimarisi — Tasarım (2026-07-16)

## Problem

Kullanıcı teşhisi: videolar "daha sürükleyici, daha merak edilesi" olmalı — sorun
tek noktada değil, **hepsi**: hook durdurmuyor, orta kısımda "sonra ne olacak?"
çekişi yok, tepe "vay be" dedirtmiyor, genel yapıda gerilim eğrisi yok (sahne
sahne mizah var, hikâye yok). Mevcut senaryo TEK LLM çağrısıyla yazılıyor; kurgu
katmanı (kesim temposu, klip sırası) meraktan habersiz.

## Karar parametreleri (kullanıcıyla netleştirildi)

- **Tarz:** mizah kalır; her anın altında "dur, sonra ne oldu?" kancası (D)
- **Bütçe:** sınırsız — kalite neyi gerektiriyorsa (D)
- **Kapsam:** senaryo + kurgu birlikte; ses/TTS katmanı ikinci faza (B)
- **Yaklaşım:** Yarışma + Merak Yargıcı (3 aday → yargıç → doktor) — tek taslağı
  cilalamak yerine çeşitlilik + seçim; iskeletler formül-kırıcılığı da besler

## Mimari

### 1. Araştırma → Rubrik (bir kerelik; çıktı koda gömülür)

Referans kanalların en çok tutan shorts transkriptleri (repo YouTube Data API
altyapısı; erişilemezse DiscoverNow DNA belgesi + ilk-ilke analiz, kaynağı
işaretlenir) tersine mühendislikle incelenir: hook soru açma biçimleri, bilginin
hangi beat'te sızdığı, tepe ödeme zamanı, beat-sonu kancaları. Çıktı:
`reel_curiosity.py` içindeki YARGIÇ RUBRİĞİ (kanıta dayalı puanlama maddeleri).

### 2. Senaryo katmanı — yeni modül `src/short_bot/reel_curiosity.py`

- `CURIOSITY_SKELETONS` (3): gizem-önce / tırmanan bahis / sahte çözüm+twist.
  Her aday senaryoya BİR iskelet talimatı eklenir (persona/çeşitleme reçetesi
  korunur; iskelet üstüne biner).
- `write_candidates(...)`: mevcut görüntü-önce prompt + iskelet → **3 paralel**
  LLM çağrısı (ThreadPoolExecutor; duvar süresi ≈ 1 çağrı). Şema:
  `FDDraftNarration` + yeni merak alanları.
- `judge_scripts(...)`: 1 çağrı; rubrikle puanlar (merak eğrisi, erken-bilgi
  sızıntısı, beat-sonu kancası, mizah, görüntü-uyum) → kazanan indeksi +
  kriter puanları + SOMUT şikâyet listesi. Puanlar loglanır.
- `doctor_pass(...)`: 1 çağrı; kazananı YALNIZ yargıç şikâyetlerini düzelterek
  yeniden yazar (beat sayısı + klip bağı korunur).
- Zincir çökerse (yargıç/doktor hatası): eldeki en iyi aday ile devam
  (fail-open); adayların TÜMÜ çökerse mevcut tek-çağrı yola düşülür.

### 3. Şema değişiklikleri (`reel_models.py`) — hepsi varsayılan-boş, geriye uyumlu

- `open_question: str = ""` — hook'un açtığı merak sorusu (ekran çipi metni;
  ~45 karaktere kırpılır, reddedilmez)
- `reveal_beat: int = -1` — cevabın ödendiği beat (-1 → peak_beat kullanılır;
  validator aralığa kelepçeler)
- `clip_order: list[int] = []` — adayın klipleri dramaturjiye göre dizmesi
  (permütasyon değilse/boşsa kimlik sırası — fail-open)

### 4. Kurgu katmanı — 3 mekanizma

| Mekanizma | Davranış | Yer |
|---|---|---|
| Reveal saklama | `clip_order` uygulanır; payoff klibi (reveal_beat'in klibi) tepe segmentinden ÖNCE hiçbir segmentte görünmez. Deterministik korkuluk: payoff hook klibine (index 0) denk gelirse sıra döndürülür | `reel.py` `_footage_driven_seg_clip` + prep |
| Açık soru çipi | `open_question` küçük kart; hook'ta belirir, asılı kalır, reveal anında ✓/renk dönüşü + kaybolma. Güvenli bölge (y 90-1440) + `__sig` kare-dedup imzasına dahil | `reel_overlay.html.j2` + `reel_render.py` (`question_text`, `reveal_at_s`) |
| Tırmanan tempo | Alt-kesim hedef süresi hook→tepe arası kademeli kısalır (~1.25x→0.75x), tepe sonrası rahatlar; `MIN_SUBCUT_S` tabanı korunur | `reel_pacing.plan_subcuts(peak_s=...)` |

### 5. Anahtar ve geriye uyum

`ReelConfig.curiosity_pipeline: bool = True` — yalnız `footage_driven=True`
iken etkin. Kapatılırsa bugünkü tek-çağrı akış birebir (sıfır regresyon
disiplini: mevcut çağrılar `else` dalına dokunulmadan taşınır). Senaryo-önce
yola sıfır dokunuş.

### 6. Test planı

- Unit: iskelet ataması deterministik+çeşitli; yargıç şema ayrıştırma; doktor
  beat sayısı/klip bağını korur; `clip_order` permütasyon doğrulaması +
  kimlik fallback; payoff-hook çakışma korkuluğu; `open_question` kırpma;
  çip güvenli-bölge + `__sig`; tempo rampası (tepe-öncesi alt-kesimler
  hook-sonrasından kısa; taban ihlali yok).
- Entegrasyon: sahte deps ile produce zinciri — 3 aday, 1 yargıç, 1 doktor;
  kullanılan senaryo = doktor çıktısı; `curiosity_pipeline=False` → tek çağrı.
- Üretim doğrulaması: gerçek koşu + kare montajı — hook'ta payoff klibi yok,
  çip görünüyor ve tepe anında dönüyor, tempo rampası ölçülüyor.

### 7. Riskler / önlemler

- Adaylar birbirine benzer → iskelet talimatları zorunlu ayrışma; yargıç
  rubriği benzerliği cezalandırır.
- Çip ekran kalabalığı → sert karakter sınırı + güvenli-bölge testleri.
- `clip_order` hep kimlik dönerse → kabul (reveal korkuluğu yine çalışır).
- Maliyet: +4 LLM çağrısı ≈ +40-60sn/video — kullanıcı onayı var (sınırsız).
