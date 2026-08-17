# Saga sınırı — aynı hikâyenin tekrar tekrar video olmasını frenle

Tarih: 2026-08-18
Kanal: `galatasaray` (Aslan Gündem). Diğer kanallar varsayılan olarak etkilenmez.

## Sorun

Mevcut dedup **tek haber** düzeyinde çalışıyor ve iyi çalışıyor: son 30 koşuda
29'unda `embedding-dedup active`, gelen haberin **%53'ünü** eliyor (koşu başına
~45 haber). Ama aynı hikâyenin günler içindeki farklı gelişmelerini görmüyor:

| tarih | manşet |
|---|---|
| 01 Ağu | TERS KÖŞE — BATRAKOV'LA ANLAŞMA |
| 09 Ağu | B PLANI — BATRAKOV OLMAZSA MORA |
| 15 Ağu | ANLAŞMA — BATRAKOV TRANSFERİ |
| 16 Ağu | GELDİ — BATRAKOV GALATASARAY'DA |

1 ve 15 Ağustos ikisi de "anlaşma" diyor, **tam 14 gün arayla** — yani ikincisi
`filter_new`'ün `lookback_days=14` penceresinden yeni düşmüş. Aynı desen Gabriel
Sara'da daha keskin: 29 günde 14 yayınlanan video.

Dedup'ı sertleştirmek çözüm değil: eşik 0.68'e ölçümle indirildi ve
`dedup.py:72-74` daha aşağısının farklı haberleri eleyeceğini kayda geçiriyor.
Sorun eşikte değil, **eksende** — haber benzerliği değil, öznenin tekrarı.

## Karar

İki editoryal karar kullanıcı tarafından verildi:

1. **Saga anahtarı = özne** (kişi/kulüp), gelişme tipi değil. Batrakov örneğinde
   4 videonun 3'ü teknik olarak farklı gelişme ama izleyiciye aynı hikâye.
2. **Kademeli ceza, taban YOK.** Puan `min_score`'un altına inebilir ve aday
   elenir. Alternatif yoksa koşu `no_candidates` ile boş geçer.

İkinci kararın gerekçesi ölçüm: üretilen videonun **%42'si zaten yayına
çıkmıyor** (29 günde 292 üretim, 168 yükleme). Hiç üretmemek, yüklenmeyecek zayıf
bir video üretmekten ucuz. 17 Ağustos gecesi kota doymuş konuyu 6.0'a sabitleyince
geriye 2 aday kalmış ve tam eşikten 1973 kupa finali videosu üretilmiş — o da
yüklenmemiş.

## Mimari

`category_quota_per_day` ile birebir aynı iskelet, ayrı eksende. Akış:

```
puanlayıcı LLM  →  ScoredItem(score, category, subject)   ← subject YENİ
       ↓
_apply_category_quota      (mevcut; tabanlı, min_score altına inmez)
       ↓
_apply_saga_penalty        (YENİ; tabansız)
       ↓
select_top(min_score)      → eşiğin altına düşen elenir
       ↓
üretim → script_json["subject"] → sonraki koşuların sayacı
```

Sıra bilinçli: kota önce çalışıp puanı 6.0'a sabitler, saga cezası onu 6.0'ın
altına indirebilir. İstenen davranış budur — kota konu çeşitliliği içindir,
saga sınırı tekrar içindir ve tekrarın vetosu daha güçlü olmalıdır.

## Bileşenler

### 1. Özne ataması — `scorer.py`

Özne senaryo yazarına değil **puanlayıcıya** sorulur, çünkü karar seçim anında
verilmeli. `ScoredItem.category`'nin tam olarak bu sebeple eklendiği
`models.py:29-33`'te yazılı; aynı gerekçe geçerli.

- `ScoreOut` (Pydantic) → `subject: str = Field(default="", max_length=40)`,
  mevcut `category` alanıyla aynı kalıp (scorer.py:22).
- `ScoredItem` (frozen dataclass) → `subject: str = ""`.
- Prompt kuralı: haberin merkezindeki kişi/kulüp; **kanalın kendi adı hariç**
  (her haberde "Galatasaray" geçiyor, o anahtar olamaz). Kişide **yalnız
  soyadı**, kulüpte kısa ad, tek kelime tercih edilir. Özne yoksa boş bırakılır
  ve ceza uygulanmaz.

### 2. Normalizasyon — `topic_taxonomy.normalize_subject()`

`normalize_category` ile aynı katlama: `İ→i`, küçültme, boşluk sadeleştirme.
`I→ı` dönüşümü **yapılmaz** — kanallar çok dilli ve Türkçe kuralı İspanyolca
`INFORMACIÓN`u bozar (topic_taxonomy.py:31-32'de kayıtlı gerekçe). Boş girdi
boş döner (kategorinin `"?"` yer tutucusu burada kullanılmaz: bilinmeyen özne
"sayma" demek, "bilinmeyen kovasında topla" demek değil).

### 3. Sayım — `db.count_recent_subjects()`

`count_recent_categories`'ın birebir ikizi. Kritik olan aynı join'i
kullanması (db.py:534-550): **yüklenmeden silinmiş video sayılmaz**, yayınlanan
ve karar bekleyen sayılır. Operatörün akışı ölçülmüş — üret → incele → beğenirse
yükle ve listeden sil — bu yüzden yalnız `deleted_at`'e bakan bir filtre sayacı
öldürürdü.

Pencere `hours` değil `days` alır (varsayılan 14).

### 4. Eşleştirme — alt-dize toleransı

LLM bir gün `batrakov`, ertesi gün `aleksey batrakov` yazarsa iki ayrı kova
oluşur ve sınır hiç tetiklenmez. Bu, tasarımın **en büyük başarısızlık riski**.
Üç katmanlı önlem:

1. Prompt "yalnız soyadı" der (yukarıda),
2. `normalize_subject` biçim farklarını siler,
3. Sayarken bir anahtar diğerini **içeriyorsa** aynı sayılır.

(3) bilinçli bir tavizdir: nadiren yanlış birleştirebilir (`sara` ⊂ `sarabia`).
Kaçırmaktan iyidir çünkü kaçırma özelliği tamamen işlevsiz bırakır, yanlış
birleştirme yalnız bir videoyu geciktirir. Testle sabitlenir.

Alt-dize karşılaştırması en az 4 karakterlik anahtarlarda uygulanır; daha kısa
anahtarlar (örn. `ns`) rastgele eşleşme üretir.

### 5. Ceza — `scorer.apply_saga_penalty()`

```
ceza      = step × (son N günde o özneyle EŞLEŞEN üretilmiş video sayısı)
yeni_puan = max(0.0, puan − ceza)      # min_score tabanı YOK
```

Sayım **zaten üretilmiş** videoları sayar; değerlendirilen aday sayıya dahil
değildir. Yani ilk kez geçen özne cezasızdır (sayı 0). Alt-dize eşleşmesi
sayarken kayıt başına uygulanır: hem `batrakov` hem `aleksey batrakov` kaydı
varsa aday için sayı 2'dir.

`apply_category_quota`'nın yanında durur ama **taban parametresi almaz**. Bu
fark, dosyadaki en önemli ayrımdır ve yorumla belirtilir: kota sıralamayı
değiştirir, saga sınırı veto edebilir.

Boş özne (`""`) cezasızdır.

### 6. Saklama — `models.py` + `pipeline.py`

`Script` modeline `subject: str = ""` eklenir. Senaryo yazarı LLM'i bu alanı
üretmez; seçilen adayın öznesi kaydetmeden hemen önce taşınır:

```python
script = script.model_copy(update={"subject": picked.subject})
```

İki çağrı yeri var ve **ikisi de** güncellenmeli: `pipeline.py:908` (panelden
"şimdi üret" yolu) ve `pipeline.py:1304` (ana boru hattı). Birini atlamak,
manuel koşuların sayaçta kör satır bırakmasına yol açar — `pipeline.py:743-745`
aynı hatanın daha önce dedup'ta yaşandığını kaydediyor.

### 7. Config — `config.py`

```yaml
saga_penalty_per_repeat: 1.0   # 0.0 = kapalı (varsayılan)
saga_window_days: 14           # dedup lookback_days ile aynı
```

`ChannelConfig`'e iki alan, `load_channel`/`save_channel`'a okuma-yazma.
Varsayılan 0.0 olduğu için **kotası olmayan kanallarda hiçbir etkisi yoktur** —
`category_quota_per_day` ile aynı kalıp. Yalnız `galatasaray.yaml`'a yazılır.

### 8. Günlük

`_apply_saga_penalty` okunabilir tek satır yazar, kotanınkiyle aynı biçimde:

```
[saga] batrakov 3 kez geçti (14g) → -3.0, puan 9.0→6.0
```

Ceza uygulanmadıysa satır yazılmaz.

## Parametre gerekçesi ve belirsizlik

`step = 1.0` **ölçülmüş değil**, ilk tahmindir. Sara 29 günde 14 kez çıkmış;
14 günlük pencerede ~7 eder, yani 5. tekrardan sonra fiilen kapanır. Sertse
0.5'e çekilir. Bu, canlıda bir hafta izlenip ayarlanacak tek sayıdır ve config
alanı olmasının sebebi budur.

`saga_window_days = 14` dedup'ın `lookback_days` değeriyle hizalıdır; iki
pencerenin ayrışması "dedup'tan düştü ama saga sayacında hâlâ var" gibi
anlaşılması zor bir aralık yaratırdı.

## Geriye dönük uyum

Eski `script_json` kayıtlarında `subject` yok → sayım 0 → ceza yok. Sınır yeni
tekrarlarda hemen çalışır, 14 günde tam ısınır. Kategori backfill'i gerekmişti
çünkü kotanın hemen dolması isteniyordu; burada aciliyet yok ve LLM ile 292
kaydı yeniden etiketlemenin maliyeti kazancından büyük. Gerekirse ayrı iş
olarak eklenir.

## Test planı (TDD)

| test | doğruladığı |
|---|---|
| `normalize_subject`: `"İBRAHİM"`, boş, fazla boşluk | Türkçe İ katlanır, `I→ı` yapılmaz |
| alt-dize: `batrakov` vs `aleksey batrakov` | aynı sayılır |
| alt-dize: 3 harfli anahtar | rastgele eşleşme yok |
| `apply_saga_penalty` 0/1/2/3 tekrar | ceza = step × sayı |
| ceza puanı `min_score` altına iter | **taban olmadığı** |
| boş özne | cezasız |
| `step=0.0` | hiçbir puan değişmez (kapalı kanal) |
| `count_recent_subjects` | pencere dışı sayılmaz |
| `count_recent_subjects` | yüklenmeden silinmiş sayılmaz, yüklenmiş+silinmiş sayılır |
| kota + saga birlikte | kota tabanı saga'yı engellemez |
| `Script.subject` round-trip | `model_dump_json` → `script_json` → sayaç |

## Kapsam dışı

- Kategori kotasının gerekçesinin yeniden ölçülmesi (ayrı iş; 2026-08-18
  ölçümünde kategori farkları p=0,69 çıktı, kota artık zayıf temelde).
- `auto_upload` kararı (kullanıcının editoryal adımı).
- `max_candidates_per_run: 10` — dedup'tan ~41 haber çıkıyor, yalnız 10'u
  skorlanıyor. Hacim değil kalite kaybı, ayrı iş.
