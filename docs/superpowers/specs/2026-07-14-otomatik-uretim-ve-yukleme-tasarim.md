# Otomatik Üretim ve Yükleme (Autopilot) — Tasarım

Tarih: 2026-07-14
Dal: `feature/electron-installer` (yayınlanmayacak)

## 1. Sorun

Bugün üretim ve yükleme **birbirine kaynaklı**: `pipeline._maybe_auto_upload`
render biter bitmez videoyu yüklüyor. Yani **üretim saati = yükleme saati**.
Kanal cron'u 13:00'te ateşlerse video 13:15'te (üretim bittiğinde) yayına girer;
ertesi gün yine 13:15, öbür gün yine 13:15.

Bunun iki sonucu var:

- **Yayın saati üretim süresine bağlı.** Üretim 9 dakika sürerse 13:09, 16 dakika
  sürerse 13:16. Ritim tutarsız.
- **Otomasyon parmak izi.** Her gün aynı dakikada yükleyen bir hesap, insan gibi
  davranmıyor.

Ayrıca kanal başına **günde N video** diye bir kavram yok: bir cron = bir video.

## 2. Çözüm — üretimi yüklemeden AYIR

```
03:00  planlayıcı yarının slotlarını yazar    → 13:04, 17:11, 20:58
10:04  slot-1 için üretim başlar (3 saat önce)
10:19  üretim biter → GİZLİ yüklenir, publishAt = 13:04
13:04  YouTube yayınlar
```

Slot (yayın anı) **önceden** belirlenir; üretim ondan saatler önce başlar. Yayın
dakikası üretim süresinden bağımsızlaşır.

## 3. İnsan ritmi: rastgele DEĞİL, RASTGELE YÜRÜYÜŞ

Kullanıcının tarifi (13:00 → 13:10 → 13:04 → 13:00) düz rastgelelik değil, bir
**taban etrafında sürüklenme**. İnsan da böyle davranır: her gün aynı dakikada
değil, ama aynı saat civarında. Düz rastgelelik (her gün 10:00–22:00 arası rastgele
bir an) ise ritmi tamamen yok eder ve izleyici alışkanlık kuramaz.

```
# TABAN — aktif saatler N eşit bloğa bölünür, slot her bloğun ORTASINA oturur.
#   blok = (bitiş − başlangıç) / N
#   taban[i] = başlangıç + blok * (i + 0.5)
#   örn. 10–22, N=3 → blok 4sa → 12:00, 16:00, 20:00
#   (uçlara değil ortaya oturtmak, jitter'ın aktif saatlerden taşmasını da önler)

sapma[gün] = clamp(sapma[dün] + adım, −JITTER_MAX, +JITTER_MAX)
adım       ∈ [−JITTER_STEP, +JITTER_STEP],  sha1(kanal, slot_no, tarih)'ten türetilir

gün 0: sapma  0  → 13:00
gün 1: adım +10 → 13:10
gün 2: adım  −6 → 13:04
gün 3: adım  −4 → 13:00
```

**Deterministik** olması şart: aynı (kanal, slot, tarih) her zaman aynı sapmayı verir
→ test edilebilir, yeniden üretilebilir, ve uygulama yeniden başlarsa slot kaymaz.

`sapma[dün]` DB'den okunur (önceki günün slotu). Yoksa (ilk gün / boşluk) 0'dan başlar.

**İki koruma (aksi hâlde sessizce bozulur):**

1. **Aktif saatlerden taşma yok.** Sapmalı slot `[başlangıç, bitiş]` dışına çıkarsa
   sınıra sıkıştırılır. (Tabanlar blok ortasında olduğu için normalde imkânsız; ama
   `daily_count` büyük ve `jitter_minutes` büyükse olabilir.)
2. **Slotlar çakışmaz.** İki slot arası en az `MIN_SLOT_GAP_MIN` (30 dk) kalmalı;
   çakışırsa sonraki slot ileri itilir. Üst üste binen iki yayın "insan" değildir.

## 4. Veri modeli — `publish_slots`

Slot, sistemin **tek doğruluk kaynağıdır**. "Bugün ne üretilecek, ne zaman
yayınlanacak, hangisi patladı" sorularının tek cevabı burada.

| alan | tip | açıklama |
|---|---|---|
| `id` | int PK | |
| `channel` | str, index | |
| `slot_local_date` | str `YYYY-MM-DD` | kanalın YEREL günü (planlama birimi) |
| `slot_index` | int | o günün kaçıncı slotu (taban saatini belirler) |
| `slot_at_utc` | datetime | yayın anı (UTC) |
| `status` | str | `planned` → `producing` → `produced` → `scheduled` → `published` / `failed` / `skipped` |
| `short_id` | int FK | üretilen video |
| `run_id` | int FK | üretim koşusu |
| `attempts` | int | üretim denemesi sayısı |
| `produced_at` | datetime | |
| `uploaded_at` | datetime | |
| `error` | text | |
| `created_at` | datetime | |

UNIQUE `(channel, slot_local_date, slot_index)` — aynı slot iki kez planlanmasın
(uygulama yeniden başladığında planlayıcı yeniden koşar).

### Durum makinesi

```
planned ──(produce_at geçti)──► producing ──(başarılı)──► produced
   ▲                                │                        │
   │                                │(patladı, attempts<max) │
   └────────────────────────────────┘                        │
                                    │(attempts=max)          │
                                    ▼                        │
                                 failed                      │
                                                             │
              publish_mode=publish_at ──────────────────────►│
                    (gizli yükle + publishAt)                │
                                    ▼                        │
                                scheduled ──(slot geçti)──► published
                                                             ▲
              publish_mode=live_upload ──(slot anı)──────────┘
                    (o an yükle, public)
```

## 5. Modül — `autopilot.py` (saf, LLM'siz)

```python
@dataclass(frozen=True)
class Slot:
    slot_index: int
    slot_at_utc: datetime
    jitter_min: int          # tabandan sapma (dakika) — ertesi gün buradan yürür

def base_times(active_hours, daily_count) -> list[time]
    """Aktif saatleri N slota eşit böl. 3 slot / 10–22 → 12:00, 16:00, 20:00."""

def next_jitter(prev_jitter, *, channel, slot_index, date, step_max, jitter_max) -> int
    """Rastgele yürüyüş: prev ± step, [−max, +max] arasına sıkıştırılır. Deterministik."""

def plan_day(channel_slug, date_local, cfg, prev_jitters) -> list[Slot]
    """O günün slotları. prev_jitters: {slot_index: dünkü sapma}."""

def produce_at(slot_at_utc, lead_hours) -> datetime

def due_slots(slots, now_utc, lead_hours) -> list[Slot]
    """Üretimi ŞİMDİ başlaması gerekenler (planned + produce_at geçmiş)."""
```

Saf fonksiyonlar: DB'ye dokunmaz, saat okumaz (now dışarıdan verilir), LLM çağırmaz.
Bütün zamanlama mantığı burada ve tamamen test edilebilir.

## 6. Scheduler — iki yeni cron

### `_autopilot_plan`
- **Ne zaman:** her gece yerel 03:00 + **uygulama açılışında**.
- **Ne yapar:** otomasyon açık her kanal için bugünün eksik slotlarını ve yarının
  slotlarını yazar (idempotent — UNIQUE kısıt sayesinde tekrar yazmaz).
- **Neden açılışta da:** uygulama kapalıysa gece cron'u kaçar; açılışta bugünün
  slotları yoksa gün tamamen boş geçerdi.

### `_autopilot_tick` (5 dakikada bir)
1. **Üretim:** `produce_at` geçmiş `planned` slotlar → `run_pipeline(defer_upload=True)`
   → başarılıysa `produced`, patladıysa `attempts++`; `attempts == max_attempts`
   ise `failed`.
2. **Yükleme:**
   - `publish_mode = publish_at`: `produced` slot → **hemen** gizli yükle
     (`privacyStatus=private`, `publishAt=slot_at_utc`) → `scheduled`.
   - `publish_mode = live_upload`: `produced` slot → `slot_at_utc` gelene kadar
     bekle, sonra yükle (`public`) → `published`.
3. **Ark yenileme:** kanal `arc_mode=planned` ve **aktif ark yok** ve **taslak yok**
   ise → bankadan tohum al, ark planla, **oto-onayla**.
   (Kullanıcının bekleyen taslağı varsa DOKUNMA — onun incelemesini ezme.)

## 7. Çakışmalar — sessizce bozulmasın diye

Bu bölüm tasarımın en kritik yeri. Üçü de gerçek çifte-üretim / çifte-yükleme riski:

1. **Otomasyon açıkken kanalın `schedule_cron`'u KAYDEDİLMEZ.**
   `scheduler._reload_jobs` autopilot açık kanalları atlar. Yoksa hem cron hem
   autopilot üretir → günde 6 video.

2. **Otomasyon üretimlerinde `_maybe_auto_upload` ATLANIR.**
   `run_pipeline(..., defer_upload=True)`. Yoksa video iki kez yüklenir: biri
   pipeline tarafından anında (public), biri autopilot tarafından zamanlı.

3. **GEÇ YÜKLEME YOK.** 3 deneme tutmazsa slot boş geçer (`failed`), panel kırmızı
   gösterir. 22:00'de yayınlanan bir "gündüz videosu" hedefi zaten ıskalar ve
   ritmi bozar — video kaybetmek, ritim kaybetmekten iyidir.

## 8. Config — `ReelConfig`'e değil, kanal köküne

```yaml
autopilot:
  enabled: false              # TERCİHE BAĞLI, varsayılan KAPALI
  daily_count: 3
  active_hours: [10, 22]      # yerel saat aralığı
  timezone: Europe/Istanbul
  jitter_minutes: 15          # tabandan en fazla sapma
  jitter_step: 6              # günden güne en fazla kayma
  produce_lead_hours: 3
  publish_mode: publish_at    # publish_at | live_upload
  max_attempts: 3
```

`autopilot.enabled = false` iken **hiçbir davranış değişmez** (mevcut cron + anında
yükleme aynen sürer). Geriye tam uyum.

## 9. Panel

- **Kanal kartı:** bugünün slot özeti (`2/3 yayınlandı · 1 başarısız`).
- **Yeni sayfa `/channels/<slug>/autopilot`:** bugünün ve yarının slotları
  (saat · durum · videoya git · hata), otomasyonu aç/kapat, ayarlar.
- **Seri sayfası:** "Bu bölümü şimdi üret" düğmesi (slot beklemeden, elle).

## 10. Hata yönetimi

| durum | davranış |
|---|---|
| Üretim patladı | `attempts++`, lead süresi içinde tekrar (max 3), sonra `failed` |
| Slot anı geçti, hâlâ `planned` | `skipped` (uygulama kapalıydı) — panel gösterir |
| Yükleme patladı (`publish_at` modu) | `produced`ta kalır, sonraki tick tekrar dener. **Slot anı geçtiyse** artık `publishAt` geçersizdir → `failed` (geriye dönük yayın zamanlanamaz) |
| `live` modu, slot anı geldi | yükle. Uygulama o an kapalıysa: `LIVE_GRACE_MIN` (15 dk) içinde açılırsa yine yükle; sonrası `failed` (geç yükleme yok) |
| Konu bankası boş, ark yok | üretim yine koşar (LLM konu üretir) — mevcut davranış |
| Kanal `enabled: false` | slot planlanmaz |
| Aynı kanalda üretim zaten koşuyor | tick bekler (pipeline lock'u zaten seri kılar); slot `planned` kalır, sonraki tick dener |

## 11. Test planı

**Saf (autopilot.py):**
- `base_times`: N slot aktif saatlere eşit dağılır (blok ORTALARINA), sıralı
- `next_jitter`: deterministik; `[−max, +max]` dışına ÇIKMAZ; adım `step_max`'i aşmaz;
  ardışık günlerde GERÇEKTEN değişir (sabit kalmıyor — yoksa "insan ritmi" yok)
- `plan_day`: slotlar aktif saatler İÇİNDE kalır; aralarında en az `MIN_SLOT_GAP_MIN`
  boşluk var (çakışma yok)
- `plan_day`: aynı girdi → aynı çıktı (deterministik; uygulama yeniden başlayınca
  slot KAYMAZ)
- `produce_at` = slot − lead
- `due_slots`: yalnız `produce_at` geçmiş `planned` slotları döndürür

**DB:**
- Slot planlama idempotent (aynı gün iki kez planlanınca kopya oluşmaz)
- Durum geçişleri; `attempts` sayacı; `failed` eşiği

**Entegrasyon (pipeline/scheduler):**
- Otomasyon açıkken kanal cron'u KAYDEDİLMEZ (çifte üretim yok)
- `defer_upload=True` iken `_maybe_auto_upload` ÇAĞRILMAZ (çifte yükleme yok)
- `publish_at` modunda upload `private` + `publishAt` ile çağrılır
- `live` modunda slot saatinden ÖNCE yüklenmez
- Üretim 3 kez patlarsa slot `failed`, geç yükleme YAPILMAZ
- Ark bitince yeni ark oto-planlanıp oto-onaylanır
- Kullanıcının bekleyen taslağı varsa oto-onaylanmaz

**Panel:**
- Slotlar durumlarıyla listelenir; başarısız slot kırmızı
- Otomasyon aç/kapat YAML'a yazar
- "Bu bölümü şimdi üret" pipeline'ı başlatır

## 12. Kapsam dışı (bilerek)

- **Yedek stok (buffer).** Slot boş geçebilir; stok mantığı seri bölüm sırasını
  bozma riski taşıyor.
- **Gün atlama.** İnsanlar gün atlar ama bu büyümeye zarar verir; istenmedi.
- **Slot saatini elle düzenleme.** Panel şimdilik yalnız gösterir; ayarlar
  (aktif saatler, sayı) üzerinden dolaylı kontrol var.
