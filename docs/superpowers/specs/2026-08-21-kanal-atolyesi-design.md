# Kanal Atölyesi — formata göre ayrılmış kurulum + karar veren sohbet

Tarih: 2026-08-21
Dal: `feature/electron-installer`
Mockup: https://claude.ai/code/artifact/3d91558b-ebff-4bd6-9d35-544b5e00087b

Bağlam: kullanıcı yeni kanal kurarken 6 sn kart ile Gündem Yorum'un "hep aynı yapıdan
üretiliyormuş gibi" olduğunu, kürate kanalın ayrı ele alındığını, ortak olan şeylerin
(YouTube bağlantısı, aktif/pasif) her formatta ayrı ayrı çözüldüğünü bildirdi. İsteği:
yapıyı formata göre baştan ayırmak, gereksizi çıkarmak, ve manuel form doldurmayı
UI'den Claude CLI ile **konuşarak** yapılan bir akışla değiştirmek.

---

## Teşhis (ölçüldü, 2026-08-21)

**Beş format, beş ayrı çağ.** Ortak çekirdek yok; onun yerine tek dev form var ve her
format ondan parça gizliyor.

| Format | Canlı kanal | "Yeni" formu | "Düzenle" | Boyut |
|---|---|---|---|---|
| card (6 sn) | 5 | `/channels/new` (DNA sihirbazı) | `edit.html.j2` | **92 KB / 94 alan** |
| voiced | 2 | **yok** (card kur → ses aç) | aynı sayfa | — |
| yorum | 2 | `/channels/new-yorum` | `edit_yorum.html.j2` | 13 KB |
| curated | 1 | `/channels/new-curated` | `edit_curated.html.j2` | 18 KB |
| reel | **0** | `/channels/new-reel` (menüde yok) | `edit_reel.html.j2` | 33 KB |

- `edit.html.j2`'de **94 form alanı** var ve içinde `reel_*`, `voice_*`, `trends_*`, `tb_*`
  hepsi birden duruyor. "Card editörü" aslında bütün formatların editörü; format ayrımı
  kodda yok, sadece hangi alanın gösterildiğine dair `if`'ler var.
- `/channels/agent` — **"bir cümle → çalışan kanal" ajanı zaten yazılmış** (niş bulucu +
  YouTube outlier doğrulaması + ses seçici + DNA + konu bankası tohumu, iki aşamalı
  `build_plan`/`apply_plan`). Menüden erişilemiyor ve kurduğu format **reel**.
- Reel formatında canlı kanal **yok**. `dayidiyorki`'de `reel:` bloğu açık ama
  `content_source: curated` olduğu için `channel_format()` "curated" döndürüyor.

**Aynı özelliğin dört yarım kopyası.** Düzenle ekranlarındaki YouTube alanları:

| YouTube ayarı | card/voiced | yorum | curated | reel |
|---|---|---|---|---|
| otomatik yükleme | ✔ | ✔ | ✔ | ✔ |
| gizlilik | ✔ | ✖ | ✖ | ✔ |
| yükleme puan eşiği | ✔ | ✖ | ✖ | ✔ |
| kategori · AI etiketi | ✔ | ✖ | ✖ | kısmi |
| `credentials_from` | **✖** | ✔ | ✖ | ✖ |

Sonucu: kürate kanalda gizlilik ve yükleme eşiği UI'den ayarlanamıyor; kart kanalında
bağlantı paylaştırılamıyor — oysa `gundem` ile `gundem-yorum` aynı YouTube kanalına
üretiyor ve o alan yalnız yorum ekranında var.

**Arketip havuzu kullanılmıyor.** 40 `.j2` şablonu var, 10 kanal topu topu 4'ünü
kullanıyor: `stadium` 5, `flas` 2, `eilmeldung` 2, `newscast` 1.

**Şablonlarda tutarsızlığın kaynağı CSS, HTML değil:**

| Şablon | Toplam | HTML gövdesi | CSS | CSS payı |
|---|---|---|---|---|
| stadium | 194 | 26 | 168 | %87 |
| newscast | 179 | 30 | 149 | %83 |
| flas | 254 | 51 | 203 | %80 |
| eilmeldung | 298 | 68 | 230 | %77 |

HTML gövdesi zaten sabit sayılır — `_auto_fit.js`'in bağlı olduğu slot ağacı
(`.header > .top/.bot`, `.photo > .bg-img`, `.body > .body-text`, `.progress`, `.handle`).

---

## Karar özeti

| # | konu | karar |
|---|---|---|
| 1 | Sohbetin kapsamı | **Kurma + ayar değiştirme.** Üretim komutları ("video üret", "yayına al") kapsam dışı — düğme olarak kalır |
| 2 | Manuel formlar | **Sohbet ön planda, formata özgü sade form arkada.** Elle düzeltme yolu kapanmaz |
| 3 | Reel formatı | **Silinir.** Ajan kürate + card'a bağlanır; kullanılan montaj alanları Kürate'ye taşınır |
| 4 | Sohbetin üslubu | **Soru sormaz, karar verir.** Gerekçesini yazar, değiştirilecek yer tıklanabilir |
| 5 | Arketip tasarımı | **Claude yeni şablon yazar** — serbest HTML+CSS, yapı kapısı + render + vision kapısıyla denetlenir |
| 6 | Reçete/şema mimarisi | **Reddedildi.** Render deterministik olduğu için çıktı görülerek denetlenebilir; şema tasarım özgürlüğünü öldürür |

## Üç alt proje

Her biri kendi başına çalışır ve kendi başına teslim edilebilir; sırayla uygulanır, aynı
dal (`feature/electron-installer`), ayrı commit dizileri.

- **I. Format ayrımı** (A + B + F) — ortak çekirdek partial'ları, formata özgü düzenleme
  sayfaları, reel'in kaldırılması. Sohbetten bağımsız: bittiğinde panel bugünkü gibi
  formla çalışmaya devam eder, ama dört formatta da eksiksiz.
- **II. Sohbet** (C + D) — format seçimi, kurma sohbeti, kanal sayfası, fark/onay akışı.
  I'in ürettiği formata özgü alan listelerine dayanır.
- **III. Arketip tasarımı** (E) — yapı kapısı + üç uç metinle render + vision kapısı.
  I ve II'den bağımsız; tek başına da uygulanabilir.

Bağımlılık yalnız **I → II** yönünde. III her an araya girebilir.

---

## A. Format ayrımı — ortak çekirdek + format katmanı

**`ChannelConfig` bölünmez.** Dataclass'ı parçalamak (`ChannelCore` + `CardConfig` + …)
tüm YAML'ları, `load_channel`/`save_channel`'ı ve pipeline'ı kırar; kazancı yok. Ayrım
**sunum katmanında** yapılır: aynı alanlar, tek bileşenden çizilir.

**Yeni: `web/templates/_partials/core/`**

| Parça | İçerik |
|---|---|
| `identity.html.j2` | ad, dil (kilitli), slug (salt-okunur), handle |
| `schedule.html.j2` | cron + `cron_human`, "Cron çalışsın" (`enabled`), "Kokpit'te görünsün" (`archived`) |
| `youtube.html.j2` | bağlantı durumu + bağla/değiştir, `auto_upload`, `privacy_status`, `category_id`, `ai_content`, `min_score_for_upload`, `credentials_from` |
| `autopilot.html.j2` | otomasyon ayarları |

Dört format düzenleme sayfası da bu dört parçayı `include` eder. **`credentials_from`,
gizlilik, kategori ve eşik böylece her formatta belirir** — yukarıdaki dört-yarım-kopya
tablosunun tek sebebi bu parçaların olmamasıydı.

**Formata özgü kısımlar** kendi partial'larında kalır:

- `card`: kaynak (rss/generator/feed/trends), anahtar kelimeler, `min_score`,
  `max_age_hours`, `max_candidates_per_run`, DNA/görsel kimlik, `bg_video`, `bg_image_blur`,
  `trend_boost`, `categories`, `category_quota_per_day`, `saga_*`
- `voiced`: card'ın hepsi + `voice` (persona, hız, süre aralığı, müzik seviyesi)
- `yorum`: `trends_region`, `trends_min_volume`, `trends_intent`, `voice`, günlük derleme
- `curated`: subreddit'ler, temizlik filtresi, persona/maskot, mizah tonu, montaj
  (vurgu rengi, süre, kesme temposu, ok, zoom, whoosh, müzik/efekt)

**`formats.py` genişler:** her format için hangi partial'ların çizileceğini ve hangi
sohbet aracının açılacağını taşıyan bir `FormatSpec` kaydı. `channel_format()` ve
`FORMAT_LABELS` aynı kalır — tek karar noktası korunur.

---

## B. Reel'in kaldırılması

Silinir:

- `src/short_bot/web/templates/channels/edit_reel.html.j2` (33 KB)
- `src/short_bot/web/routes/reel_new.py` (177 satır), `reel_edit.py` (216 satır)
- `_partials/channel_card_reel.html.j2`
- `channel_format()` içindeki `reel` dalı, `FORMAT_EDIT_SUFFIX["reel"]`

**Taşınır (silinmez):** `dayidiyorki`'nin kullandığı montaj alanları — `highlight_color`,
`target_duration_s`, `cut_pacing`, `arrows_enabled`, `arrow_color`, `zoom`, `whoosh`,
`flash`, `music_mood`, `transition_vary`, `accent_vary`, `hook_angle_vary`,
`series_enabled`, `series_title`, `voice_id` — Kürate formatının kendi alanları olur.

**`ReelConfig` dataclass'ı yerinde kalır.** YAML uyumluluğu için gerekli
(`dayidiyorki.yaml` onu yazıyor); yalnız UI ve format kararı ondan kopar. Kürate düzenleme
sayfası bu alanları `cfg.reel` üzerinden okumaya devam eder.

**Ajan:** `channel_agent.apply_plan` artık `reel_edit.edit_reel`'e değil, planın formatına
göre ilgili düzenleme sayfasına yönlendirir.

---

## C. Kurma sohbeti

### Giriş

Kanallar sayfasındaki üç düğme (`+ Yeni Kanal`, `+ Kürate Kanal`, `+ Gündem Yorum`) tek
`+ Yeni kanal` düğmesine iner → `/channels/new` **format seçimi** ekranı: dört kart
(Kart / Sesli / Gündem Yorum / Kürate), her biri ne olduğunu **ve o formatta çalışan
kanalların slug'larını** gösterir.

Format önce seçilir, çünkü format hangi kararların verileceğini belirler.

### Üslup kuralı — soru sormaz, karar verir

> "Tonu ne olsun? Sesi ne olsun? YouTube ne olsun?" diye soran bir sohbet, 94 alanlık formu
> 94 soruya çevirmekten başka bir şey değildir ve kullanıcıyı ne diyeceğini bilmek zorunda
> bırakır.

Claude **kararı verir**, **gerekçesini yazar**, kullanıcı yalnız beğenmediği satıra
dokunur. Kullanıcı **hiçbir şey yazmadan "Kanalı kur"a basabilmelidir.**

Bilinmesi şart olan şeyler (fatura etkisi, ayrı YouTube kanalı gibi) `attn` işaretli
satır olur: karar yine verilmiştir, ama gözden kaçmaz.

**Öneri çipleri:** composer'ın üstünde 3–4 tıklanabilir öneri ("günde 3 olsun", "daha sert
bir ton", "başka arketip dene"). Boş kutuya bakıp donmayı önler.

### Ekran

İki sütun: solda konuşma, sağda **canlı taslak**. Kullanıcının cümlesinden gelen alanlar
sarı vurgulanır (`.fresh`). Sağ sütunun altında "Kanalı kur" + "Vazgeç".

### LLM sözleşmesi

Claude CLI bugün tek atış çağrılıyor (`-p --output-format text --strict-mcp-config
--setting-sources "" --tools ""`) ve patlarsa OpenRouter'daki aynı modele düşüyor
(`llm_sonnet.sonnet_json`).

**Sohbet hafızası prompt'a gömülür**, CLI oturumuna bağlanılmaz. Gerekçe: CLI oturumu
`--output-format json` + `--resume` gerektirir ve OpenRouter fallback'inde karşılığı
yoktur; düşme yolunda sohbet bozulur.

Çıktı şeması (Pydantic, `sonnet_json` ile zorlanır):

```python
class Karar(BaseModel):
    alan: str                 # "trends_region", "voice.persona", ...
    deger: object
    ozet: str                 # "Bölge AT, dil Almanca kaldı"
    gerekce: str              # neden böyle seçildi
    dikkat: bool = False      # attn satırı mı
    alternatif_etiket: str = ""   # "başka ses", "3 isim gör"

class SohbetCevabi(BaseModel):
    mesaj: str
    kararlar: list[Karar]
    oneriler: list[str]       # öneri çipleri
```

> **Uygulamada düştü:** `kurmaya_hazir: bool` yazıldı ama hiçbir yerde okunmadı —
> "Kanalı kur" düğmesi kurma sohbetinde zaten hep görünür, kapı yok. Okunmayan alan
> bedava değil: her prompt'ta şemayla modele gider, her cevapta doldurulur. Kaldırıldı.

**Hiçbir şey yazılmaz** — mevcut `build_plan`/`apply_plan` ayrımı korunur. "Kanalı kur"a
basılana kadar ne YAML, ne CSS, ne konu bankası.

---

## D. Ayar sohbeti — kurulu kanalda

### Yeni rota: `GET /channels/<slug>`

Bugün böyle bir rota **yok** (`channel_agent.py` içindeki yorum bunu belgeliyor: ajan
oraya yönlendirdiğinde 404 alınıyordu). Kanal sayfası bu spec'le doğar: solda sohbet,
sağda kanal özeti + "Ayarları elle düzenle" + "Şimdi bir video üret".

### Açılış teşhisi LLM'e sorulmaz

Sayfa açıldığında Claude'un ilk mesajı bir **ölçüm raporu**dur ve LLM çağrısı gerektirmez:

| Bulgu | Kaynak |
|---|---|
| kaç manşet kesildi | `dna.sentence_max_words` aşımı + üretilen başlık uzunlukları |
| kaç koşu üretmeden bitti | `runs.short_id IS NULL` oranı |
| otomatik yükleme kapalıyken kaç video birikti | `shorts` − başarılı `youtube_uploads` |
| kaç gündür yayın yok | `youtube_uploads` son başarılı kayıt |

Bunlar `dashboard_stats.py` tarzı düz SQL ile bulunur. **LLM yalnız kullanıcı bir şey
yazınca devreye girer.** Her kanal sayfası açılışında LLM çağırmak hem yavaş hem gereksiz
masraf.

**ÖLÇÜLEMEYEN, dolayısıyla ÜRETİLMEYEN bulgu** (uygulama sırasında ortaya çıktı,
2026-08-21): mockup'ta "elenenlerin 4'ü yükleme eşiğinin hemen altında" diye bir öneri
gösterilmişti. `shorts` tablosunda ve `script_json` içinde **puan alanı yok** — bu soru
mevcut şemadan cevaplanamıyor. Uydurma sayı üretmektense bulguyu hiç üretmemek doğrudur;
`test_esik_alti_bulgusu_URETILMEZ` bunu sabitler. Şemaya puan eklenirse bulgu eklenir.

Çözümü olmayan bulgu **düzeltilmez, bildirilir**: "11 gündür yayın yok" bir ayar hatası
değil, operatör kararıdır. Her şeye çözüm üreten bir asistan, çözümü olmayanı da
çözülmüş gösterir.

### Fark (diff) ve onay

Her öneri `{alan, eski, yeni, gerekçe}` olarak gösterilir:

```
dna.sentence_max_words          22 → 14
dna.size_headline_top         76px → 68px
youtube.min_score_for_upload   8.0 → 7.5
```

Butonlar: "Üçünü de uygula" / kısmi uygula / "Vazgeç". Farkı göstermeden uygulamak,
94 alanlık formu *görünmez* bir forma çevirir — daha kötüsü.

**Bağlı alan uyarısı:** `archived` istenip `enabled` açıkken Claude ikisini birlikte
önerir ve sebebini yazar (pasif kanal cron çalışmaya devam ederse görülmeyen video üretir).

Uygulama `save_channel` ile YAML'a yazar; her uygulama tek bir git farkı bırakır.

---

## E. Arketip tasarımı — vision kapısı

Claude bugün DNA üretiyor (palet, font, punto, banner/vurgu/çip stili, 8000 karaktere
kadar `custom_css`) ama **arketipi 40 hazır `.j2`'den seçiyor**. Bu spec ile **yeni şablon
da yazabilir.**

Tutarsızlık korkusunun cevabı şema değil, **denetim**: render deterministik (Playwright
chromium, aynı HTML → aynı kare), dolayısıyla üretilen şey görülerek yargılanabilir.
Desen projede kanıtlanmış — `footage_matcher.py` (`MAX_GATE_CHECKS = 24`) ve
`image_picker._verify_with_claude()` aynısını yapıyor.

### Döngü

1. **Claude şablonu yazar** — serbest HTML + CSS. Prompt'ta `TEMPLATE-SPEC.md` sözleşmesi
   ve iki çalışan şablon örnek olarak verilir.
2. **Yapı kapısı** (vision yok, bedava): zorunlu sınıflar (`.header .top .bot`,
   `.photo .bg-img`, `.body-text`, `.progress`, `.handle`) var mı; `data-fit-*` nitelikleri
   duruyor mu; beklenen Jinja değişkenleri eksiksiz mi. Geçersizse sebep LLM'e yazılır.
3. **Render** — `renderer.render_frames`, chromium, **üç uç metinle**: en uzun manşet, en
   çok satırlı gövde, en uzun kaynak adı.
4. **Vision kapısı** — üç kareye bakar: manşet kutuya sığıyor mu, metin zeminden okunuyor
   mu, fotoğraf yazıyı yutuyor mu, kesilmiş/taşmış öğe var mı.
5. **Geçerse kaydet** (`templates/<slug>.html.j2` + `config/archetypes.json` girişi);
   geçmezse en fazla 3 tur düzelttir, hâlâ geçmezse **kaydetme**, kullanıcıya göster.

### Bağlanacak parçalar (hepsi mevcut)

```python
claude_cli._invoke_raw(prompt, ..., image_path=Path)   # PNG'yi vision'a yollar
dna_smoke.smoke_render_dna(dna, ...)                   # PNG üretir (fps=1)
google_studio  # 38 anahtarlık ücretsiz havuz, data/google_pool
renderer.render_frames(job, template_path, ...)        # chromium, deterministik
```

Eksik olan tek şey bunları birbirine bağlayan kapı fonksiyonu.

### Tek metinle test etmek yanıltıyor

Bugünkü `smoke_render_dna` **tek örnek metinle** (`_SMOKE_SCRIPT`) render ediyor ve yalnız
"kare düz renk mi" diye bakıyor (piksel stddev > 5). Kısa manşetle geçen şablon uzun
manşette taşar. Üç uç metin bu tuzağı kapatır; maliyeti üç vision çağrısı ve havuz
ücretsiz.

### Kabul edilen riskler

- Vision **gördüğünü** yargılar; "bir sonraki uzun manşette taşar mı" sorusunu uç metinler
  daraltır, tamamen kapatmaz.
- Geçen her şablon **diskte kalıcı dosya** olur → panelde silme yolu şart.
- Üç tur düzeltme 3× süre; yeni arketip nadir üretildiği için kabul edilebilir.
- Arketipe özel senaryo yazarı davranışı hâlâ **elle** bağlanıyor (`script_writer`).

### Reddedilen alternatif

LLM'e HTML/CSS yerine kapalı listelerden seçim yaptıran "reçete" şeması
(`düzen: band-top | split | full-bleed` gibi). Tutarlılığı şemayla garantiler ama tasarım
özgürlüğünü öldürür; render denetlenebilir olduğu için o güvenceye ihtiyaç yok.

---

## F. Formata özgü elle ayar

**Dört düzenleme rotası tek rotaya iner.** Bugün `FORMAT_EDIT_SUFFIX` dört ayrı yol
üretiyor (`edit`, `edit-yorum`, `edit-curated`, `edit-reel`). Bunun yerine tek
`GET/POST /channels/<slug>/edit` kalır; format içeride `channel_format(cfg)` ile
belirlenir ve hangi partial'ların çizileceğine `FormatSpec` karar verir.
`FORMAT_EDIT_SUFFIX` ve `edit_path()` kalkar — çağrıldığı yerler (`channel_row`,
`channel_card`, Kokpit başlatıcı) sabit `/channels/<slug>/edit` kullanır.

Eski yollar (`/channels/<slug>/edit-yorum`, `-curated`) **301 ile yeni rotaya
yönlendirilir**: kullanıcının kayıtlı sekmeleri ve tarayıcı geçmişi kırılmasın.

Sayfa ortak çekirdek partial'ları + o formatın kendi partial'ıyla çizilir. Gündem Yorum
kanalında ~16 alan görünür; subreddit, montaj temposu, arka plan videosu **hiç çizilmez**.

Sohbet ana yol olsa da bu ekran korunur: Claude CLI erişilemezse veya bir alanı yanlış
anlarsa kullanıcı YAML'ı elle açmak zorunda kalmamalı.

---

## G. Temizlik

| Ne | Kazanç | Neden |
|---|---|---|
| `channels/edit_reel.html.j2` | −33 KB | Reel formatı gidiyor |
| `routes/reel_new.py` + `reel_edit.py` | −393 satır | `/channels/new-reel` menüde yoktu |
| `channels/new.html.j2` + `new_yorum` + `new_curated` | −18 KB | Üç kurulum formu → format seçimi + sohbet |
| `routes/channel_new.py` (DNA sihirbazı) | −172 satır | Session'lı iki adımlı sihirbaz sohbette eriyor |
| `channels/edit.html.j2` | 92 KB → 4 sayfa | Ortak bloklar tek partial'a iner; toplam satır düşer |
| `channel_agent.py`, `voice_picker`, `niche_finder` | **kalır** | Sohbetin motoru; silinen tek şey "yalnız reel kurar" kısıtı |

---

## Açık kalan / sonraya bırakılan

- **Üretim komutları** ("şimdi video üret", "bunu yayına al") sohbete girmiyor; sağ panelde
  düğme. Onay akışı (hangi video, hangi karar) ayrı bir tasarım problemi.
- **Arketip havuzu ölçümü:** 36 şablonun hiç seçilmemesi LLM'in onları beğenmediğine mi
  işaret, yoksa listeye hiç bakmıyor mu — ölçülmedi. E maddesini etkilemez ama
  bilinmesi faydalı.
- **Üretilen şablonların silinmesi:** panelde arketip silme ekranı bu spec'in kapsamında
  değil, ama E maddesi kalıcı dosya ürettiği için kısa sürede gerekecek.

---

## Doğrulama ölçütleri

1. Dört formatın düzenleme sayfasında da gizlilik, kategori, yükleme eşiği ve
   `credentials_from` **görünür ve kaydedilir** (bugün dördü de eksik).
2. `/channels/new` → format seç → tek cümle yaz → **hiçbir şey yazmadan** "Kanalı kur"
   ile çalışan kanal kurulur.
3. `/channels/<slug>` açılışında **LLM çağrısı yapılmaz** (log ile doğrulanır), buna
   rağmen teşhis satırları dolu gelir.
4. Sohbetten yapılan her değişiklik önce fark olarak görünür, onaysız YAML'a yazılmaz.
5. Vision kapısı, manşeti kasten taşıran bir şablonu **reddeder** (negatif test).
6. `grep -r "reel_edit\|new-reel"` boş döner; `dayidiyorki` üretmeye devam eder.
7. `pytest tests/` — mevcut kanal/web testleri geçer.
