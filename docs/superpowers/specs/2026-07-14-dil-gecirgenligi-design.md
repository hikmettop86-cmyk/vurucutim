# Dil Geçirgenliği — Tasarım

**Tarih:** 2026-07-14
**Dal:** `feature/electron-installer` (yayınlanmayacak)
**Alt proje:** 3'ün 1'i. Sıradakiler: (2) konu üretimi — referans kanalsız da kurumasın,
Sonnet 5'e taşı. (3) kanal kurma ajanı.

## Amaç

Türkçe dışında bir dilde kanal açıldığında sistem **gerçekten** o dilde çalışsın.
Bugün çalışmıyor — ama sessizce çalışmıyor, ki bu daha kötüsü.

## Neden şimdi

Kullanıcı yabancı dilli (Almanca gibi yüksek RPM'li) kanallar açmayı ciddi olarak
planlıyor. Kanal kurma ajanı (alt proje 3) "Almanca bahçecilik kanalı kur" dediğinde
kuracağı kanalın çalışması gerekiyor. Dil geçirgenliği o ajanın ön koşulu.

## Ölçülen bozukluklar

Hepsi gerçek kodda, gerçek çağrılarla doğrulandı.

### 1. Ekran rozeti Türkçe harf basıyor — GÖRÜNÜR

```
episode_badge("Bier Garten", 47)  →  "BİER GARTEN #47"
beklenen                          →  "BIER GARTEN #47"
```

`reel_series.py:101` `turkish_upper()` çağırıyor; o da `i → İ`, `ı → I` eşlemesi
yapıyor. Türkçe için doğru (`.upper()` "Bilim"i "BILIM" yapardı), Almanca için yanlış.

### 2. Abone çipi ve CTA Türkçe — GÖRÜNÜR

`reel_subscribe.CTA_TEXTS` (4 dizge) ve `reel_series.trade_cta()` sabit Türkçe:
"Her gün yeni — ABONE OL", "#48 yarın — ABONE OL". Almanca kanalın ekranına
Türkçe abone çipi basılır. Tek kaçış `reel.cta_text_custom` ile elle Almanca
girmek — yani sistem değil kullanıcı çözüyor.

**Sert kısıt:** `CTA_MAX_CHARS = 24`. Almanca'da "ABONNIEREN" tek başına 10 karakter;
"Täglich neu — ABONNIEREN" tam 24. Aşarsa `reel_subscribe.py:114-118` kırpıyor ve
ekranda "ABONNIE" yazıyor. Yani Almanca CTA metinleri **üretildikleri anda**
doğrulanmalı, çalışma anında değil.

### 3. Aşınmış-kalıp denetçisi hedef dilde HİÇBİR ŞEY yakalayamıyor — SESSİZ

İki kat sorun var ve ikincisi birincisini de öldürüyor.

**(a)** `reel_phrases.OVERUSED` + `OVERUSED_PATTERNS` tamamen Türkçe
(`\bbiliyor mu(ydunuz|ydun)\b` gibi). Almanca metinde eşleşme olmaz.

**(b)** Daha kötüsü: normalleştirici Türkçe'ye kilitli.

```python
_fold("Ich zeige euch")  →  "ıch zeige euch"      # I → ı
re.search(r"\bich\b", "ıch zeige euch")  →  None
```

`reel_phrases._norm` → `tts.fidelity._fold`, o da `text.replace("I", "ı")` yapıyor.
Yani **kusursuz bir Almanca yasaklı-kalıp listesi yazsak bile eşleşmez.**
Normalleştirme katmanı dile duyarlı olmadan dil paketinin denetçi bölümü ölü doğar.

Bu bozukluk sessiz: hata vermez, log basmaz. Denetçi çalışıyor görünür, sıfır şey bulur.

### 4. TTS sadakat karşılaştırması asimetrik — SESSİZ

Aynı `_fold`'dan geliyor. `normalize_tokens` senaryo metnini Whisper dökümüyle
karşılaştırıyor. Almanca'da büyük harfli "Ich" → "ıch", küçük harfli "ich" → "ich".
Büyük/küçük harf iki tarafta farklıysa kelime eşleşmez ve sadakat denetimi yanlış
alarm verir. Almanca'da "Ich/In/Ist/Immer" çok sık.

### 5. Seri yönergeleri Türkçe — YUMUŞAK

`reel_series.series_directive()` (~80 satır) LLM'e Türkçe talimat ve **Türkçe örnek
cümleler** veriyor ("✓ 'Ama o ışık balığın kendi değil — onu üreten bakteriyi 48.
bölümde anlatıyorum.'"). Anlatım prompt'u ayrıca "Almanca yaz" diyor. Güçlü model
muhtemelen Almanca yazar, ama Türkçe örnekleri kopyalama ve dil sızıntısı riski
ölçülmedi. `reel_phrases.CONNECTIVE_STYLES` ve `reel_subscribe.COMMENT_STYLES` de aynı
durumda.

### 6. `clean_open_loop` meta-dil temizleyicisi Türkçe — SESSİZ

`reel_series._META` regex'i "2. bölümde açıklıyoruz" gibi meta dili söküyor. Almanca
karşılığı ("erkläre ich in Folge 2") elenmez ve bir sonraki bölümün **üretim konusu
tohumu** olarak kullanılır. Senaryo yazıcısı yanılır.

## Ne değişmiyor

Dil altyapısının çoğu zaten doğru ve **dokunulmayacak**: `locale.py`
(`SUPPORTED_LANGUAGES = tr/en/de/es/fr`, `UI_LABELS`, `TREND_REGIONS`), DNA prompt'u,
`reel_narration.py`'nin hedef-dil talimatı, Whisper `language=` hizalaması, ai33 TTS
(dil `voice_id`'den geliyor, ayrı parametre yok), overlay `lang` attribute'u.

## Mimari

### Katman 1 — Dile duyarlı normalleştirme (ÖN KOŞUL)

`src/short_bot/text_normalize.py` iki fonksiyon kazanır:

```python
def locale_fold(text: str, lang: str = "tr") -> str:
    """Eşleştirme için küçültme. Türkçe: 'İ'.lower() birleşik nokta üretir, elle eşle."""
    if lang == "tr":
        return text.replace("İ", "i").replace("I", "ı").lower()
    return text.casefold()

def locale_upper(text: str, lang: str = "tr") -> str:
    if lang == "tr":
        return turkish_upper(text)
    return text.upper()
```

Türkçe davranışı **birebir** bugünküyle aynı — mevcut testler bunu kanıtlar.

Bağlantılar:
- `reel_phrases._norm(text, lang)` artık `tts.fidelity._fold`'u değil `locale_fold`'u
  çağırır. (Bugünkü import bir modülün özel fonksiyonuna uzanıyor — o bağ kopar.)
- `tts/fidelity.py`: `_fold(text, lang="tr")` → `locale_fold`'a devreder;
  `normalize_tokens(text, lang="tr")`. Çağıranlar `channel.language` geçirir.
- `reel_series.episode_badge(title, no, *, lang)` → `locale_upper`.
- Jinja `tr_upper` filtresi kalır (panel Türkçe).

### Katman 2 — `LangPack` veri modeli

Yeni: `src/short_bot/lang_pack.py` (model + yükleme + doğrulama).

```python
class OverusedPattern(BaseModel):
    label: str          # LLM'e geri bildirimde gösterilir
    pattern: str        # hedef dilde regex

class SeriesDirectives(BaseModel):
    header: str            # gerekli: {title} {no} {next_no}
    paying_promise: str    # gerekli: {promise}
    announce_arc: str      # gerekli: {arc_title} {arc_total}
    finale: str            # gerekli: {arc_title} {next_no}
    planned_loop: str      # gerekli: {next_no} {next_topic}
    chain_loop: str        # gerekli: {next_no}
    teaser_fallback: str   # gerekli: {title}

class LangPack(BaseModel):
    lang: str
    # EKRANA BASILAN
    cta_texts: list[str]           # tam 4
    trade_cta: str                 # "#{no} morgen — ABONNIEREN"
    default_series_title: str      # "Interessante Fakten"
    # LLM YÖNERGELERİ
    comment_styles: list[str]      # tam 4
    connective_styles: list[str]   # tam 8
    series: SeriesDirectives
    # DENETÇİ
    overused: list[str]            # en az 5
    overused_patterns: list[OverusedPattern]   # en az 4
    meta_tail_pattern: str         # clean_open_loop için
```

### Katman 3 — Paket nereden gelir

**Dosya:** `langpacks/<dil>.json`. İki konumda aranır, bu sırayla:

1. `SHORTBOT_CONFIG_DIR/langpacks/<dil>.json` — kullanıcının yazılabilir dizini
   (üretilen paketler buraya yazılır; kullanıcı elle düzenleyebilir)
2. `src/short_bot/langpacks/<dil>.json` — kodla gelen varsayılanlar (paket verisi)

İkinci konum şart: paketlenmiş Electron uygulamasında kurulum dizini salt-okunur
olabilir. `dna.py`'nin `config/archetypes.json`'u paket-göreli okuması aynı desen.

**Kodla gelen (elle yazılmış):**
- `tr.json` — bugünkü sabitlerin **birebir kopyası**. LLM üretmez, kopyala-yapıştır.
  Türkçe kanalların çıktısı zerre değişmeyecek; altın test bunu kanıtlar.
- `en.json` — elle yazılır. Bildiğimiz dil, LLM'e emanet etmeye gerek yok.

**Üretilen:** `de`, `es`, `fr` ve sonradan eklenecek her dil.

### Katman 4 — Üretim

Yeni: `src/short_bot/lang_pack_gen.py`.

```python
def generate_pack(lang: str, *, claude_path: str = "claude",
                  openrouter_model: str = "", openrouter_key: str | None = None,
                  invoke=None) -> LangPack
```

**Model:** Claude CLI + **Sonnet 5** (`backend="claude_cli", model="sonnet"`).
Aktif backend `openrouter` olduğu için `resolve_ai_call` baypas edilir — bu kod
tabanında kanıtlanmış desen, `niche_finder.py:158-179` aynısını yapıyor.
CLI yoksa/patlarsa OpenRouter'daki `anthropic/claude-sonnet-5`'e düşer
(`settings.openrouter_models["script"]`), yani model aynı kalır, yalnız yol değişir.

**Prompt:** Türkçe paket **referans** olarak verilir, hedef dil söylenir. Talimat
"çevir" değil, "bu dilin kendi muadilini yaz":
- CTA metinleri o dilin YouTube jargonunu kullansın ("ABONNIEREN", "SUBSCRIBE")
- Yasaklı kalıplar **o dilin gerçek Shorts klişeleri** olsun ("Wusstest du schon?",
  "Hallo Leute", "Heute zeige ich euch") — Türkçe listenin çevirisi değil
- Sert kısıtlar prompt'ta açıkça: CTA ≤ 24 karakter, rozet ≤ 28, sayılar (4/4/8)
- Seri yönergelerinin pedagojisi korunsun (ödenmiş tepe + açık kapı), örnek cümleler
  hedef dilde yeniden yazılsın

Çağrı: `claude_cli.run_json(prompt, schema=LangPack.model_json_schema(), ...)`.

**Doğrulama** (`lang_pack.validate_pack(pack) -> list[str]`):

| Kural | Neden |
|---|---|
| `lang` ∈ `SUPPORTED_LANGUAGES` | |
| `len(cta_texts) == 4`, her biri 1..24 karakter, tekrarsız | kırpılmış çip ekranda "ABONNIE" yazar |
| `trade_cta` `{no}` içerir; `no=48` ile render ≤ 24 karakter | aynı |
| `default_series_title` ≤ 24 karakter (rozette " #47" için yer) | |
| `len(comment_styles) == 4`, `len(connective_styles) == 8` | seed rotasyonu bu sayılara dayanıyor |
| `overused` ≥ 5; `overused_patterns` ≥ 4 | boş liste = denetçi yok |
| her `pattern` ve `meta_tail_pattern` `re.compile` edilebilir | bozuk regex çalışma anında patlar |
| her `series.*` şablonunun yer tutucuları: gerekli olanları **içerir**, izin verilenlerin **dışına çıkmaz** | eksik/fazla `{x}` → çalışma anında `KeyError` |

Doğrulama düşerse hatalar prompt'a geri verilip **bir kez** yeniden denenir. Yine
düşerse `RuntimeError` — sessiz kabul yok.

### Katman 5 — Kod bağlantıları

| Dosya | Değişiklik |
|---|---|
| `reel_subscribe.py` | `build_subscribe_bits(channel, seed, episode=None)` → içeride `pack = load_pack(channel.language)`. `COMMENT_STYLES`/`CTA_TEXTS` sabitleri **silinir** (tr.json'a taşındı). `CTA_MAX_CHARS` kod sabiti olarak kalır (paket ona uymak zorunda). |
| `reel_phrases.py` | `pick_styles(seed, n, *, pack)`, `find_overused(text, *, pack)`. `CONNECTIVE_STYLES`/`OVERUSED`/`OVERUSED_PATTERNS` **silinir**. |
| `reel_series.py` | `episode_badge(title, no, *, pack)`, `trade_cta(next_no, *, pack)`, `series_directive(plan, title, *, pack)`, `clean_open_loop(text, *, pack)`. |

Dile ihtiyaç duyan her fonksiyon **paketi** alır, ayrıca `lang` almaz — dil zaten
`pack.lang`. İki kanaldan aynı bilgiyi geçirmek, çağıranın onları çelişkili
verebilmesi demektir (Almanca paket + `lang="tr"`), ve o çelişki sessizce yanlış
sonuç üretir.
| `text_normalize.py` | `locale_fold`, `locale_upper` eklenir. |
| `tts/fidelity.py` | `_fold(text, lang="tr")`, `normalize_tokens(text, lang="tr")`. |
| Çağıranlar (`reel.py`, `reel_narration.py`) | `channel.language` geçirir. |

Paket **bir kez** yüklenip taşınır (her çağrıda dosya okumaz); `load_pack` `lru_cache`
ile önbelleklenir, panelden yeniden üretilince temizlenir.

### Katman 6 — Panel

- **Kanal sihirbazı** (`/channels/new-reel`): dil seçilip kaydedilirken paket yoksa
  üretilir. Görünür adım ("Almanca dil paketi hazırlanıyor…"), DNA üretimiyle aynı
  ekranda. Üretim düşerse **kanal kurulmaz** ve sebep söylenir.
- **Ayarlar → Dil paketleri**: mevcut paketleri listeler (dil, kaynak: kodla gelen /
  üretilmiş), paketi gösterir, ham JSON düzenlemeye izin verir (doğrulamadan geçer),
  "yeniden üret" düğmesi taşır.

## Hata hâlleri

| Durum | Davranış |
|---|---|
| Paket yok, üretim başarılı | Yazılır, kullanılır |
| Paket yok, üretim başarısız | `RuntimeError`. Kanal **kurulmaz**. Türkçe pakete **düşülmez** — bugün yaşanan sessiz bozulmanın ta kendisi o. |
| Paket var ama bozuk (regex derlenmiyor, alan eksik) | Yükleme hatası, net mesaj, panelde "yeniden üret" önerisi |
| Kullanıcı paketi elle bozdu | Kaydetmeden önce doğrulanır, reddedilir |
| Desteklenmeyen dil | `SUPPORTED_LANGUAGES` doğrulaması zaten `load_channel`'da var |

## Test

**Türkçe altın test (regresyon kalkanı — en önemlisi):**
- `tr.json` üzerinden koşan yeni kod, bugünkü sabitlerle **aynı** çıktıyı verir:
  `build_subscribe_bits`, `pick_styles`, `find_overused`, `episode_badge`,
  `trade_cta`, `series_directive`, `clean_open_loop` — seed 0..99 için birebir eşitlik.
- Mevcut 2033 testin tamamı değişmeden geçer.

**Almanca (elle yazılmış test fixture'ı, LLM çağırmaz):**
- `episode_badge("Bier Garten", 47, pack=de)` → `"BIER GARTEN #47"` (İ değil I)
- `find_overused("Wusstest du schon, dass...", pack=de)` → boş değil
- `locale_fold("Ich", "de")` → `"ich"`, `\bich\b` eşleşir
- `clean_open_loop("... erkläre ich in Folge 2.", pack=de)` → meta sökülür
- CTA'ların hepsi ≤ 24 karakter

**Doğrulama:**
- 25 karakterlik CTA reddedilir; 24 kabul edilir (sınır testi)
- derlenmeyen regex reddedilir
- `series.planned_loop` içinde `{next_no}` yoksa reddedilir
- `{bilinmeyen}` yer tutucusu reddedilir
- `comment_styles` 3 ya da 5 elemanlıysa reddedilir

**Üretim (sahte `invoke`, gerçek LLM yok):**
- geçersiz paket → hatalar geri bildirilir → ikinci deneme → başarı
- iki deneme de düşer → `RuntimeError` (sessiz düşme yok)
- Claude CLI patlar → OpenRouter'a düşer, aynı model
- üretilen paket `SHORTBOT_CONFIG_DIR/langpacks/` altına yazılır

**Sessiz-düşme yasağı:**
- `load_pack("de")` — dosya yok, LLM yok → `RuntimeError` fırlatır,
  **Türkçe paket döndürmez**. (Bu testin adı açıkça bunu söyler.)

## Kapsam dışı (bilerek)

- Panelin kendi arayüzü Türkçe kalır (kullanıcı Türk).
- `renderer.py`'nin `DEFAULT_UI_LABELS_TR`'ı (klasik/RSS yolu, reel değil) —
  `locale.UI_LABELS` zaten 5 dili taşıyor; reel yolu etkilenmiyor. Ayrı iş.
- Konu üretimi kalitesi ve referans-kanal zorunluluğu → **alt proje 2**.
- Kanal kurma ajanı → **alt proje 3**.
