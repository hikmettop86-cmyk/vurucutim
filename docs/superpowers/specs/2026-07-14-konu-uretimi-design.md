# Konu Üretimi — Tasarım

**Tarih:** 2026-07-14
**Dal:** `feature/electron-installer` (yayınlanmayacak)
**Alt proje:** 3'ün 2'si. Önceki: dil geçirgenliği (bitti). Sonraki: kanal kurma ajanı.

## Amaç

Konu bankası **kaliteli** konu üretsin, ve bunu YouTube API anahtarı ya da referans
kanal olmadan da yapabilsin.

## Ölçüm — sorun sandığımız yerde değildi

Kullanıcının tezi: *"Referans kanal eklemek şart olmamalı; arka planda güçlü model
kullanıyoruz, o her kategoriye göre iyi konu bulabilir."* Ölçtüm — **haklıydı**, ve
ölçüm benim önceki teşhisimi (bkz. `topic-bank-quotas` hafızası: "referans kanal en
güçlü kaldıraç") çürüttü.

### 1. Damıtma sistemin EN UCUZ modelinde koşuyor

`config/settings.yaml`:
```
ai_backend: openrouter
openrouter_models:
  dna:     anthropic/claude-opus-4.8
  default: google/gemini-3.1-flash-lite   ← KONU DAMITMASI + ARAMA SORGUSU
  script:  anthropic/claude-sonnet-5
```
`topic_bank.py:68` ve `autopilot_deps.py`, damıtma için `resolve_ai_call(..., "default")`
çağırıyor. Yani nişteki konuları seçen ve yazan model, sistemdeki en ucuz model.

### 2. Bankanın %85'i çöp

Sonnet 5 ile denetledim (iki kural: *gerçeği içer/vaat etme*, *içi boş genelleme değil*):

| Kanal | Aktif konu | Çöp | Referans kanal |
|---|---|---|---|
| vucudun-gizli-onarim-gucu | 27 | **23 (%85)** | 0 |
| bilim-tarihinin-sok-anlari | 21 | 5 (%23) | 4 |

Örnekler (hepsi bankada, üretilmeyi bekliyor):

- *"Vücudumuzdaki her organ, hayatta kalmak için kusursuz bir uyum içinde çalışır."*
  — Bu, damıtma prompt'unun **YASAK örneği olarak birebir verdiği cümle**. Model,
  prompt'un "bunu yazma" dediği cümleyi kelimesi kelimesine yazmış.
- *"Vücudunuz, yediğiniz bir muzu sindirim sistemi boyunca **saniyeler içinde**…"*
  — **BİLİMSEL OLARAK YANLIŞ.** Sindirim saatler sürer.
- *"Kanser, aslında bağışıklık sisteminin kendi hücrelerini tanıyamaması…"*
  — **Nedensellik ters.**

Kanalın otoritesi onun ürünüdür; bir tek yanlış video onu yakar.

### 3. Kanıt kaynak VİDEOYA ait, konu CÜMLESİNE değil

En yüksek patlama katsayılı konular en kötü yazılmış olanlar:

```
 871x  "Vücudumuzda, düşüncelerimizi ... kontrol eden inanılmaz ..."   ← içi boş
 713x  "Gerçek bir sinir sistemi, ... karmaşık bir otoyol"             ← hiçbir şey demiyor
 634x  "İnsan vücudu, evrimin kalıntılarıyla dolu şaşırtıcı bir sistemdir." ← boş
 513x  "Vücudumuzdaki her organ kusursuz bir uyum içinde çalışır."     ← prompt'un yasak örneği
```

Outlier videonun 871 kat patlaması, ondan damıtılan cümlenin iyi olduğunu göstermez.
Damıtıcı kanıtı alıp içi boş cümleye çeviriyor.

### 4. Sonnet 5, hiçbir YouTube verisi görmeden daha iyi konu yazıyor

Aynı niş, kanıt YOK:

```
"Mide iç zarı kendi asidiyle sindirilmemek için hücrelerini her 3-4 günde bir yeniler."
"Bir hücrenin DNA'sı her gün ~10 bin kez hasar görür; onarım enzimleri neredeyse
 tamamını anında düzeltir."
"Periferik sinirler kesildiğinde günde ~1 mm hızla yeniden uzar."
"25 yaşındaki bir kalpte hücrelerin yılda ~%1'i yenilenir — karbon-14 tarihlemesiyle
 ölçüldü."
```

Hepsi somut, doğrulanabilir, şaşırtıcı. Kullanıcının tezi ölçümle doğrulandı.

### 5. Referans kanal işe yarıyor — ama sandığım sebepten değil

bilim-tarihinin'in 4 referans kanalı var ve çöp oranı %23; vucudun'un 0 ve oranı %85.
Referans kanallar `channel_outlier_shorts` ile geliyor: format-kanıtlı videoların
başlıkları daha iyi yazılmış, o yüzden zayıf damıtıcı onları daha az bozabiliyor.
Yani referans kanal, kötü damıtıcıyı **maskeliyordu**. Damıtıcı düzelince gerekliliği
düşer.

### 6. İki gizli daraltıcı

- **`keywords` kısa devresi** (`topic_miner._search_queries:169`): kanalın `keywords`i
  doluysa fonksiyon **tek** sorgu döndürüyor (`" ".join(kw[:3])`) ve LLM'e HİÇ gitmiyor.
  Arama havuzu tek sorguya iniyor.
- **Taze outlier yoksa ÇÖKME** (`mine_topics_via_api:326`): havuzdaki her video bankada
  varsa `ValueError` fırlıyor. Banka kurumuyor — madencilik TAMAMEN duruyor.

## Mimari

### Katman 1 — Ortak Sonnet çağırıcısı

Yeni: `src/short_bot/llm_sonnet.py`.

Dil paketinde (`lang_pack_gen`) kurduğumuz desen tek yere çıkar: önce **Claude CLI +
Sonnet 5** (abonelik, marjinal maliyet yok), patlarsa **OpenRouter'daki
`anthropic/claude-sonnet-5`** (AYNI model, farklı yol).

```python
def sonnet_json(prompt: str, schema: type[T], *, claude_path: str = "claude",
                openrouter_model: str = "", openrouter_key: str | None = None,
                timeout_s: int = 600, retries: int = 2, invoke=None) -> T
```

`lang_pack_gen` bu yardımcıya devreder (davranışı aynı kalır; testleri kanıtlar).

**Neden `resolve_ai_call` değil:** aktif backend `openrouter`; `resolve_ai_call` her rol
için OpenRouter döndürür ve Claude CLI aboneliğini kullanamayız. `niche_finder` da aynı
sebeple onu baypas ediyor — kod tabanında kanıtlanmış desen.

### Katman 2 — Damıtma ve üretim BİRLEŞİR

Yeni: `src/short_bot/topic_propose.py`.

Bugün iki ayrı dünya var: `_distill(rows, ...)` outlier başlıklarını konuya çeviriyor;
konu ÜRETEN bir yol yok. Birleştiriyoruz:

```python
class ProposedTopic(BaseModel):
    topic: str
    source_title: str = ""      # kanıt kullanıldıysa
    views: int = 0
    subs: int = 0
    hook_pattern: str = ""
    source: str = "llm"         # "reference" | "search" | "llm"

def propose_topics(niche: str, *, language: str, evidence: list[dict],
                   existing: list[str], count: int, llm) -> list[ProposedTopic]
```

**Prompt'un çekirdek cümlesi:** kanıt başlıkları verilir ve şöyle denir —
*"Bunlar bu nişte PATLAMIŞ videolar; izleyicinin neye tepki verdiğini gösteriyorlar.
İlham al, ama KOPYALAMAK ZORUNDA DEĞİLSİN. Bir başlıktan somut bir olgu çıkaramıyorsan
onu ATLA ve kendi bildiğin daha iyi bir olguyu yaz."*

`evidence` boşsa saf üretim: **banka asla kurumaz, referans kanal ve API anahtarı asla
şart değildir.**

Mevcut damıtma prompt'unun birikmiş bilgeliği AYNEN taşınır (sözde-bilim yasağı,
meta-tarif yasağı, format uyumu, "gerçeği içer vaat etme", içi boş genelleme yasağı) —
o kurallar ölçümle kazanıldı, atılmaz.

### Katman 3 — DOĞRULAMA KAPISI (yeni, ve şart)

```python
class Verdict(BaseModel):
    index: int
    solid: bool
    reason: str = ""

def verify_topics(topics: list[str], *, language: str, llm) -> list[Verdict]
```

**Neden şart:** ölçüldü — model, prompt'un "bunu yazma" dediği cümleyi (birebir yasak
örneği) yine yazdı. Prompt'a güvenmek YETMİYOR. Denetim ikinci bir çağrıdır ve iki
kurala bakar:

1. **GERÇEĞİ İÇER, VAAT ETME** — "şaşırtıcı rakamlarla ifade edilebilir" = VAAT
2. **İÇİ BOŞ GENELLEME DEĞİL** — "her organ kusursuz uyum içinde çalışır" = ÇÖP

Düşen konular ELENİR ve **loglanır** (kaç konu neden düştü). Hepsi düşerse 0 eklenir ve
loga geçer — sessiz değil.

Bu, gerçek banka üzerinde koşturulup doğrulandı: 27 konudan 23'ünü, 21 konudan 5'ini
doğru şekilde çöp saydı (bilimsel hataları da yakaladı).

### Katman 4 — Kaynak etiketi

`topic_bank` tablosuna `source` sütunu (`TEXT DEFAULT 'search' NOT NULL`; migrations
listesine eklenir — mevcut kayıtlar `search` olur).

Değerler: `reference` (referans kanal outlier'ı) | `search` (arama outlier'ı) |
`llm` (kanıtsız, Sonnet üretimi).

Panelde görünür. Kullanıcı neyin kanıtlı neyin üretilmiş olduğunu bilmeli — bu, tüm
projenin "sessiz bozulma olmasın" ilkesinin gereği.

### Katman 5 — Madenci sadeleşir

`topic_miner.py`:
- `_distill` ve `_distill_prompt` **silinir** (işi `topic_propose` devraldı).
- `mine_topics_via_api` artık konu değil **KANIT** döndürür: outlier satır listesi.
  Taze outlier yoksa `ValueError` FIRLATMAZ → boş liste döner.
- `refresh_topic_bank` akışı:
  ```
  kanıt = madencilik (API anahtarı varsa; yoksa [])
  konular = propose_topics(niş, kanıt=kanıt, mevcut=banka, adet=12)
  yargılar = verify_topics(konular)
  taze = fuzzy-dedup(yargıyı geçenler)
  insert
  ```
- `_search_queries`: `keywords` artık kısa devre yapmaz — LLM'e **ipucu** olarak verilir,
  sorguları yine LLM üretir (6 üret, 3'ünü dönüşümlü ara).
- `api_keys` yoksa **RuntimeError YOK**: madencilik atlanır, üretim koşar.

### Katman 6 — Banka denetimi (mevcut çöpü temizle)

Yeni: `audit_bank(eng, channel, *, language, llm) -> dict`
`verify_topics`'i bankadaki AKTİF konulara uygular; düşenleri `rejected` işaretler.
`{"checked": N, "rejected": M}` döner.

Panelde Konu Bankası sayfasına **"Bankayı denetle"** düğmesi (onay diyaloğu: kaç konu
elenebileceğini söyler). Cron DEĞİL — yeni konular zaten üretim anında doğrulanıyor;
bu, eski kayıtlar için tek seferlik/talep üzerine bir araç.

## Hata hâlleri

| Durum | Eski | Yeni |
|---|---|---|
| YouTube API anahtarı yok | `RuntimeError`, banka hiç dolmaz | Madencilik atlanır, **LLM üretimi koşar** |
| Taze outlier yok | `ValueError` | `kanıt=[]` ile üretim koşar |
| Referans kanal yok | Zayıf başlık → çöp konu | Fark etmez (damıtıcı güçlü) |
| YouTube kotası doldu | Hata yüzeye çıkar | Madencilik atlanır, üretim koşar; **loglanır** |
| Claude CLI yok | — | OpenRouter'daki aynı Sonnet'e düşer |
| Doğrulama hepsini eler | — | 0 eklenir, **loglanır** ("hiçbir konu doğrulamayı geçmedi") |
| LLM tamamen çalışmıyor | Mekanik fallback (başlık = konu) | **RuntimeError.** Mekanik fallback ham başlığı konu yapıyordu — ölçülen çöpün bir kaynağı da o. Konu üretemiyorsak sessizce çöp üretmektense durmak yeğdir. |

## Test

**Ölçüme dayalı (gerçek çöp örnekleriyle):**
- `verify_topics`, ölçülen gerçek çöpleri eler:
  "Vücudumuzdaki her organ kusursuz bir uyum içinde çalışır" → `solid=False`
  "Vücuttaki kemik sayısı şaşırtıcı rakamlarla ifade edilebilir" → `solid=False`
- ve sağlamları geçirir:
  "Bebekler 300 kemikle doğar; yetişkinlikte bu sayı 206'ya iner" → `solid=True`
  (Bunlar sahte `llm` ile değil, GERÇEK Sonnet ile koşan bir kalite kapısı testidir —
  `test_topic_propose_real.py`, dil paketindeki `de_real` deseninin aynısı.)

**Sahte LLM ile (hızlı, deterministik):**
- `evidence=[]` → üretim koşar, konu döner (banka kurumaz)
- `api_keys=[]` → `refresh_topic_bank` çalışır, madencilik atlanır (RuntimeError YOK)
- outlier bulunamaz → üretim yine koşar
- doğrulamadan düşen konular bankaya GİRMEZ
- doğrulama hepsini elerse `added=0` ve UYARI loglanır
- `source` etiketi doğru yazılır (reference/search/llm)
- `keywords` dolu → yine 3 sorgu üretilir (kısa devre yok)
- LLM yok → `RuntimeError` (mekanik fallback YOK)

**Regresyon:**
- fuzzy-dedup hâlâ çalışıyor (aynı olgu iki kez girmiyor)
- `_drop_known` hâlâ kanıt havuzunu temizliyor
- `topic_autofill` su seviyesi mantığı değişmiyor
- 2159 testin tamamı geçer

**Denetim:**
- `audit_bank` çöp konuları `rejected` işaretler, sağlamlara dokunmaz
- panel düğmesi çalışır ve kaç konunun elendiğini söyler

## Kapsam dışı (bilerek)

- **Kanal kurma ajanı** → alt proje 3.
- **`settings.yaml`'a yeni rol eklemek**: `sonnet_json` doğrudan Claude CLI kullanıyor
  (kullanıcının açık tercihi). Rol tablosuna dokunmuyoruz; `default` rolü başka
  yerlerde (vision, dedup) kullanılmaya devam ediyor.
- **Üretilen konuları YouTube'da DOĞRULAMAK** (niche_finder'ın "Veri-Destekli" modu gibi
  her adayı ölçmek): aday başına ~102 birim kota. Doğrulama kapısı zaten kaliteyi
  sağlıyor; kanıt istenirse referans kanal/arama zaten kanıt taşıyor. YAGNI.
