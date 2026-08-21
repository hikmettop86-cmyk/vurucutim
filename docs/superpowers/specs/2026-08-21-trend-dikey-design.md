# Trend kanallarında DİKEY — "her şey" havuzundan tanımlı bir kimlik

Tarih: 2026-08-21
Bağlam: `content_source: trends` kanalları (`gundem-yorum`, `deutschland-klartext`,
`weltgeschehen-aktuell` ve dile göre kurulacak yenileri) ülkenin en çok aranan
konusunu alıyor. Kullanıcının teşhisi: "her şey geliyor, her şeyden atınca
YouTube Shorts algoritması kanalı anlamıyor."

## 1. Problem — ölçüldü

Shorts'ta tohumlama kanaldan başlar: yeni Short önce kanalın önceki Short'larını
izleyip beğenenlere gösterilir, sonra genişler. Konu her videoda değişince o
havuz her seferinde sıfırlanır. Dahası abone **zarara** döner: depremi izleyip
abone olan kişiye Survivor videosu düşer, kaydırıp geçer, bu da kanalın genel
puanını aşağı çeker.

Trends havuzunun bileşimi bu sonucu kaçınılmaz kılıyor. TR canlı havuzu
(2026-08-21). Aşağıdaki tablo boru hattının GERÇEKTEN gördüğü listedir: 212 ham
trendin hacim + haber süzgecinden geçen 55'i:

| Kategori | trend | **hacim payı** |
|---|---|---|
| Spor | 18 (%33) | **%64** |
| Ekonomi / cep | 10 (%18) | %16 |
| Deprem / afet | 4 (%7) | %8 |
| Siyaset / hukuk | 6 (%11) | %4 |
| Kalanı | 17 | %8 |

Sıralamayı puan değil **hacim** yapıyor (`pipeline.py:1196` → `select_by_volume`).
Hacmin %64'ü spor olduğuna göre kanal matematiksel olarak *futbol kanalı +
rastgele haber gürültüsü*. Algoritma kanalı anlamıyor değil — **yanlış anlıyor**,
çünkü onu futbol izleyicisine öğretip sonra o izleyiciye altın/deprem videosu
veriyoruz.

## 2. Ölçüm — hangi bölgede hangi dikey kaç video besler

Altı bölge canlı çekildi (`fetch_trending_now`, 24 saatlik pencere). Sayım
kuralı: **hacim ≥ taban VE haber makalesi olan** trendler — yani gerçekten
videoya dönebilecek olanlar.

Taban 2000:

| Dikey | TR | US | DE | ES | FR | JP |
|---|---|---|---|---|---|---|
| Spor | 26 | 104 | 37 | 21 | 34 | 36 |
| Diğer (yerel olay) | 11 | 13 | 27 | 12 | 37 | 20 |
| Eğlence | **0** | 46 | 20 | 11 | 10 | 32 |
| Hukuk & Devlet | 4 | 26 | 26 | 19 | 13 | 10 |
| İş & Finans | 9 | 16 | 9 | **2** | 8 | 11 |
| Hava / Afet | 3 | 7 | 8 | 4 | 8 | 6 |
| Siyaset | 8 | 8 | 11 | 2 | 2 | 1 |

Taban 1000 (dikey kapısı geldikten sonraki hedef ayar):

| Dikey | TR | US | DE | ES | FR | JP |
|---|---|---|---|---|---|---|
| Spor | 32 | 136 | 52 | 29 | 56 | 50 |
| Eğlence | 3 | 66 | 34 | 19 | 20 | 46 |
| Hukuk & Devlet | 5 | 32 | 38 | 23 | 19 | 14 |
| İş & Finans | 13 | 21 | 16 | 6 | 10 | 16 |

**Arz eşiği:** günde 2 video için ham arzın ~4 katı gerekir (dedup, kapı reddi,
görselsiz haber, kardeş kanal çakışması hepsi kesiyor) → **≈ 8 aday/gün**.

Okunanlar:
- **Spor tek evrensel dikey** — her bölgede 20+.
- **TR'de Eğlence sıfır**: Türkiye trendlerinde magazin ya yok ya `Diğer`'e
  düşüyor. TR için magazin dikeyi kurulamaz.
- **İş & Finans ES'te 2** — İspanya'da para kanalı kurulamaz.
- **Siyaset hiçbir yerde tek başına yetmiyor** (1-11) ve kutuplaştırıcı.

**Geçerlilik uyarısı:** bu tablo TEK GÜNLÜK kesittir. Ölçüm gününde TR'de Süper
Lig maçı vardı, spor şişkin olabilir. Kullanıcı kararı: "şimdi ata, sonra
düzelt" — atamalar bugünkü veriyle yapılır, arzı zayıf çıkan bölgede dikey
değiştirilir. Bu yüzden **dikey ayar olmalı, kod olmamalı**.

## 3. Bulgu — dikey sinyali zaten bedava geliyor, çöpe atılıyor

Google her trendi kendisi sınıflandırıyor: `TrendingEntry.category_ids`
(`trends/trending_now.py:50`). 212 TR trendinin 195'i tek kategorili, 17'si iki.
Ama `trending_as_news_items` (`trending_now.py:203`) bu alanı `NewsItem`'a
taşımıyor — ayrıştırılıp atılıyor.

Sonuç: dikey kapısı **sıfır AI maliyetiyle** kurulabilir.

Kategori haritası ampirik çıkarıldı (2090 trend, altı bölge, kategori başına en
yüksek hacimli terimlerden). Google'ın alfabetik 19'luk listesiyle birebir
DEĞİL — `20` (Hava/İklim) listede yok, `12` hiç görülmedi:

| ID | Anlam | Kanıt terimleri |
|---|---|---|
| 1 | Otomotiv | tesla autopilot, byd, akaryakıt fiyatları zam |
| 2 | Güzellik & Moda | naomi campbell, margaret qualley |
| 3 | **İş & Finans** | morgan stanley, heizöl, agriculteur, walmart tap to pay |
| 4 | **Eğlence** | sundance, taylor sheridan, the voice kids, verzuz |
| 5 | Yeme-İçme | publix blueberry recall, rappel de produit, chipotle |
| 6 | Oyun | activision, gta, nba 2k hq, fortnite codes |
| 7 | Sağlık | measles, ebola, immunizations, food poisoning |
| 8 | Hobi & Boş zaman | mount fuji, petanque, mevlid kandili |
| 9 | İş & Eğitim | aöf giriş, dadeschools, dgs tercihleri, sınav |
| 10 | **Hukuk & Devlet** | lindsay clancy trial, annalena baerbock, appel à témoins |
| 11 | **Diğer / yerel olay** | hofgeismar fußgängerzone, accident beauval zoo |
| 13 | Hayvan | rescue dog, hauskatze, bear gets stuck in vehicle |
| 14 | Siyaset | wahlumfrage sachsen-anhalt, voting, iran war trump |
| 15 | Bilim | blood moon total lunar eclipse, spacex |
| 16 | Alışveriş | michael kors, ticketmaster, olivia rodrigo tour |
| 17 | **Spor** | erzurumspor-galatasaray, ligue 1, raiders vs texans |
| 18 | Teknoloji | iphone 18, openai, apple tv |
| 19 | Seyahat | royal caribbean, rheinfall, portaventura |
| 20 | **Hava & Afet** | çankırı (deprem), tornado long island, chaleur, peru earthquakes |

## 4. Tasarım

### 4.1 Dikey = kanalın birinci sınıf ayarı

YAML'a `trends_vertical: para`. Takma ad, Google kategori kümesine çevrilir —
bir dikey birden fazla ID'ye yayıldığı için ham ID listesi YAZILMAZ (okunmaz ve
harita değişirse her kanal YAML'ı bozulur):

| takma ad | kategoriler | ne kapsar |
|---|---|---|
| `spor` | {17} | lig, maç, transfer, milli takım |
| `para` | {3} | ekonomi, şirket, zam, faiz |
| `magazin` | {4, 2} | ünlü, dizi, film, moda |
| `adalet` | {10} | dava, gözaltı, kurum, resmi karar |
| `olay` | {11, 20} | yerel olay, kaza, deprem, hava |
| `teknoloji` | {18, 15, 6} | teknoloji, bilim, oyun |

`trends_vertical: null` (varsayılan) = bugünkü davranış, hiçbir şey değişmez.
Mevcut kanallar bu spec dışında kırılmaz.

İki kategori BİLEREK hiçbir dikeyde yok:
- **14 Siyaset** — altı bölgede de günde 1-11 trend (eşik ~8) ve kutuplaştırıcı.
- **16 Alışveriş** — karışık torba (Michael Kors, Ticketmaster, konser bileti,
  PlayStation). Önce `para`ya kondu; canlı TR kuyruğunda kattığı TEK haber
  "erkek el çantaları" modası oldu, gerçek para haberlerinin hepsi kategori 3'tü.
  O haber zaten Güzellik&Moda (2) üzerinden `magazin`e düşüyor.

Çoklu kategorili trendlerde (212'de 17 tanesi) **herhangi bir** kategori dikeyle
kesişiyorsa trend girer. Tek kategori kuralı olsaydı `sucuk [3,5]` para
dikeyinden düşerdi.

### 4.2 Filtre 40'lık kesmeden ÖNCE

`fetch_trending_items(max_entries=40)` havuzu hacme göre kesiyor. Spor hacmin
%64'ü olduğu için dar dikey ilk 40'ta neredeyse hiç görünmez. Filtre kesmeden
önce uygulanır; hacim sıralaması dikey **içinde** çalışır.

### 4.3 Önbellek bölge başına paylaşılıyor — filtre çekimde OLMAZ

`data/cache/trends/trending_now_<region>.json` bölge başınadır, kanal başına
değil. Filtreyi çekim anında uygularsak spor kanalının doldurduğu önbelleği para
kanalı okur ve boş döner (30 dk boyunca).

Kural: **önbellek filtresiz dolar, dikey okuma anında uygulanır.** Bu, çekilen
havuzun büyütülmesini gerektirir (`max_entries` çekimde 40 → 200; kesme,
filtreden sonra `max_candidates_per_run` ile zaten yapılıyor).

Maliyet notu: `max_entries` aynı zamanda `fetch_trending_articles`'ın alt-çağrı
sayısıdır (trend başına bir rpc, hepsi tek HTTP isteğinde). 40 → 200 bu isteği
büyütür; önbellek 30 dk tuttuğu için bölge başına saatte ~2 çağrı demektir.
Karar: **200 ile başlanır**; uygulama sırasında istek 15 sn zaman aşımını
zorlarsa 100'e çekilir ve ölçüm koda yorum olarak yazılır.

### 4.4 `NewsItem.trend_categories` alanı

`tuple[int, ...] = ()`, RSS/feed kaynaklarında boş kalır. Taşınması gereken
yerler — biri atlanırsa alan sessizce düşer:

- `trending_as_news_items` (üretim)
- `_item_to_dict` / `_item_from_dict` (önbellek gidiş-dönüşü)
- `ScoredItem`'ı yeniden kuran her yer

Son madde ölçülmüş bir tuzaktır: saga sınırı işinde trend boost `ScoredItem`'ı
yeniden kurup yeni alanı düşürüyordu. Yeni alan eklerken **taşıyan** yerler de
aranmalı.

### 4.5 Kapı dikeyi öğrenir

`scorer.py:138` `_TREND_PROMPT_TEMPLATES` bugün tek soru soruyor: "olay mı,
arama mı?" ve "hisse fiyatı/grafik, döviz/altın kuru sorgusu"nu 0-3 verip eliyor.
Bir **para** kanalında bu tam da yaşadığı şeyi eler.

Prompt'a dikey başına bir blok eklenir: o dikeyde neyin hikâye sayıldığı, neyin
sayılmadığı. Örnek (`para`): "altının neden rekor kırdığı bir olaydır; altının
kaç TL olduğu değildir."

Dikey `null` iken prompt bugünkü hâliyle kalır.

### 4.5b Kategori kapısı KESİN DEĞİL — iki kademeli süzgeç

Ölçüldü (2026-08-22, DE/adalet 27 aday): Google'ın kategori 10 ("Hukuk &
Devlet") etiketi geniş bir torba ve yanılıyor — içine **Prinz Harry ve Meghan**
(magazin) ile **fırın tedarikçisi iflası** (para) da girdi. Elle tasnif: 15 net
adalet, 7 sınırda (itfaiye/kamu duyurusu — aslında `olay`), 5 açıkça alakasız.

`para` (TR, 5 aday) ve `magazin` (DE, 23 aday) aynı gün TEMİZ çıktı; sorun
kategori 10'a özgü.

Bu yüzden tasarım iki kademelidir: **kategori = ucuz ön süzgeç** (TR'de 52
konudan 47'sini kesiyor, AI maliyeti sıfır), **AI kapısı = hassas süzgeç**.
Prompt'un dikey bloğu modele filtreye GÜVENMESİNİ söylememeli — ilk yazımda
"havuz zaten süzüldü, sen yalnız olay var mı ona bak" diyordu ve bu gürültüyü
videoya taşırdı. Blok artık şunu der: *sınıflandırma yanılır, dikeye ait
olmayana 0-3 ver.*

Gerçek kapı bu 27 adaya koşuldu (gemini-3.5-flash-lite): **15/27 geçti** ve
elenenler elle yapılan tasnifle BİREBİR aynı çıktı — Harry & Meghan 1.0
("völlig außerhalb der Vertikale"), iflas 5.0, Baerbock 3.0, Rus tankeri 2.0.

### 4.6 Arz tabanı alarmı — sessiz genişleme YOK

Dikey filtresinden sonra aday sayısı `ChannelConfig.trends_min_candidates`
(yeni alan, varsayılan 4) altına düşerse koşu `no_candidates` ile biter ve
log/panelde "dikey aç kaldı" uyarısı görünür.

Sessizce tüm havuza dönmek YASAK: tam da bugünkü sorunu geri getirir ve üstelik
görünmez yapar.

## 5. Dile göre atama (bugünkü ölçüm)

| Bölge | Kanal | Dikey | Arz/gün (taban 2000) | Gerekçe |
|---|---|---|---|---|
| TR | `gundem-yorum` | `para` | 9 → taban 1000'de 13 | Eğlence 0; spor takım kanallarıyla (`galatasaray`, `fenerbahce`) bölünür; siyaset riskli |
| DE | `deutschland-klartext` | `adalet` | 26 | Eilmeldung tonu ve Pressekodex dili zaten oturmuş |
| DE | `weltgeschehen-aktuell` | `magazin` | 20 | Aynı bölgede ikinci kanal; ayrı dikey olmazsa iki kanal aynı olayı anlatır |
| ES | yeni | `adalet` | 19 | İş & Finans ES'te 2 (ölü); Latido Blanco sporu tutuyor |
| US | yeni | `magazin` | 46 | Spor 104 ama highlights kanallarıyla yarışamayız (görüntü hakkı yok); magazin kart+yorum formatına oturur |
| FR | yeni | `spor` | 34 | Mevcut FR kanalı yok; en temiz kimlik |
| JP | yeni | `magazin` | 32 | Japon trend havuzu talent/TV ağırlıklı |

Bu spec mevcut kanalların dikeyini ayarlar. ES/US/FR/JP satırları kayıt
içindir; o kanallar ayrı iştir — mekanizma hazır olduğunda Kanal Atölyesi'nden
kurulur.

**Uygulama notu (2026-08-21):** `weltgeschehen-aktuell.yaml` uygulama sırasında
diskten kayboldu (`aslangundem-plus` ve `real-madrid-en-espanol` ile birlikte;
üçü de gitignore'da olduğu için geri getirilemedi). Kullanıcı silmiş olabilir —
oturum başındaki `git status` zaten üç kanal YAML'ının silindiğini gösteriyordu
(`deutschland-kompakt`, `gundem`, `mahalle-vahsisi`), yani bir temizlik sürüyor
gibi. Bu yüzden magazin dikeyi UYGULANMADI; kanal yeniden kurulursa
`trends_vertical: magazin` + `trends_min_volume: 2000` verilmeli.

**Canlı arz doğrulaması (2026-08-21, gerçek API):** TR/para **11** aday,
DE/adalet **27**, DE/magazin **23** — üçü de `trends_min_candidates` eşiğinin
(4) çok üstünde. TR/para listesi içerik olarak da tutarlı çıktı: altın rekoru,
sucukta tağşiş, şirket satın alma, iflas, mevduat getirisi.

### 5.1 Hacim tabanı düzeltmeleri

Dikey kapısı geldikten sonra kaliteyi hacim değil dikey belirler:

| Kanal | bugün | yeni | neden |
|---|---|---|---|
| `gundem-yorum` | 5000 | 1000 | `para` dikeyinde 5000'de günde 4 aday kalıyor — eşiğin altı |
| `deutschland-klartext` | 10000 | 2000 | DE havuzu 5000'de bile ince; 10.000 kanalı aç bırakıyor |
| `weltgeschehen-aktuell` | 5000 | 2000 | `magazin` dikeyinde 5000'de 11, 2000'de 20 |

### 5.2 Persona düzeltmesi — `adalet` dikeyinde hüküm YOK

Yorumcu personası "adil ama net bir hüküm verirsin" diyor. Devam eden davada bu
hukuki risk taşır. `adalet` dikeyindeki kanallarda persona "aktarır + bağlam
verir + soru sorar"a çekilir; hüküm cümlesi kaldırılır.

Bu bir KOD değişikliği değil **yapılandırma** değişikliğidir: persona kanal
YAML'ında (`voice.persona`) duruyor, yalnız `adalet` dikeyli kanalların YAML'ı
düzenlenir. `narration_writer` içindeki varsayılan persona sabitine dokunulmaz.

`para` ve `magazin` dikeylerinde persona bugünkü hâliyle kalır.

### 4.7 Canlı Gündem masası dikeyi uygular

`/gundem` masası havuzu ham gösteriyordu (`DESK_MIN_VOLUME = 1000`, yorum:
"masa her şeyi görsün"). Dikeyle birlikte bu operatörü yanıltır: para kanalı
için futbol listesine bakar. Kuyruk artık **kanalın dikeyine** süzülür; seçici
ile tek dikey ya da "Tümü" seçilebilir, her satırda kategori rozeti durur ve
başlıkta kaç haberin elendiği yazar.

ÜRETİM yolu (`/gundem/produce`) süzgeçten ETKİLENMEZ: operatör dikey dışındaki
bir haberi hâlâ elle üretebilmeli.

**Masa önbelleği boru hattını aç bırakıyordu (bu spec'in soktuğu hata):** masa
`max_entries=60` ile çekiyor ve bu paylaşılan önbelleğe yazılıyordu; boru hattı
200 isterken 60'lık listeyi okuyordu. Çekim kapasitesi artık çağıranın ayarı
değil, modül sabiti (`_FETCH_MAX_ENTRIES = 200`); çağıran yalnız kaç satır
istediğini söyler (`limit=`) ve bu süzgeçten SONRA uygulanır.

### 5.3 Panel

Kanal düzenleme sayfasındaki kaynak bölümüne dikey açılır listesi eklenir.
Bilinen tuzak: `channel_edit.py` izin listesine yeni alan eklenmezse panel kaydı
dikeyi **sessizce düşürür** — `trends` kaynağı ve DNA paletinde bire bir aynı
tuzağa iki kez düşüldü. Kaydediciler `dataclasses.replace` kullanmalı.

## 6. Kapsam dışı

- Kanal ayrıştırması. `UCH7B92TIJ…` üç dikey (haber + mizah + sağlık),
  `UCH3PSl-Ps3…` dört dikey taşıyor. Kullanıcı bunu ayrı iş olarak bıraktı;
  bu spec dokunmuyor.
- Saga/dizi takibi (günler arası varlık hafızası). Dikey oturduktan sonra
  ayrı spec.
- Çok günlük arz ölçümü cron'u. Kullanıcı "şimdi ata sonra düzelt" dedi.
- Yeni ES/US/FR/JP kanallarının kurulumu.

## 7. Test

- `trends_vertical` ayrıştırma: geçersiz takma ad **sessizce null'a düşmez**,
  hata verir (`_trends_intent` ile aynı kural).
- Kategori filtresi: sabit fikstürden (`tests/fixtures/trending_*_tr.txt`)
  gelen havuzda `para` seçilince yalnız {3,16} ile kesişenler kalır.
- Çoklu kategori: `[3,5]` etiketli trend `para` dikeyinde KALIR.
- Önbellek gidiş-dönüşü: `trend_categories` `_item_to_dict` → `_item_from_dict`
  sonrası korunur.
- Önbellek paylaşımı: aynı bölgede iki farklı dikeyli kanal arka arkaya
  koştuğunda ikisi de kendi adaylarını görür (filtre önbelleğe sızmaz).
- Arz alarmı: dikey filtresi 4'ün altına indiğinde `no_candidates`, tüm havuza
  dönüş YOK.
- `trends_vertical: null` olan kanalda seçim bugünkü davranışla birebir aynı.
- Panel kaydı: dikey seçilip kaydedilince YAML'da kalır (izin listesi testi).
