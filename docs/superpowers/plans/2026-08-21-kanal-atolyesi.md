# Kanal Atölyesi — Uygulama Planı

> **DURUM (2026-08-21): 18 görevin tamamı uygulandı ve commit'lendi.**
> Uygulama sırasında planı değiştiren üç bulgu — hepsi ilgili commit'te
> gerekçesiyle yazılı:
>
> 1. `channel_edit` POST'u kanalı `ChannelConfig(...)` ile SIFIRDAN kuruyordu:
>    tek Kaydet tıklaması saga sınırını, kategori kotasını, referans
>    kanalları ve pasifliği siliyordu. `dataclasses.replace`'e çevrildi.
> 2. `shorts` şemasında PUAN alanı yok — "elenenlerin kaçı eşiğin hemen
>    altındaydı" bulgusu ölçülemiyor ve üretilmiyor (mockup'ta temsilîydi).
> 3. Yapı kapısı ilk sürümde `comic` şablonunu reddediyordu; ölçüt
>    TEMPLATE-SPEC'in örnek iskeletinden `_auto_fit.js`'in GERÇEK
>    bağımlılıklarına indirildi.

> **Ajan işçiler için:** Bu plan `superpowers:executing-plans` ile görev görev uygulanır.
> Adımlar takip için `- [ ]` kutucuk sözdizimi kullanır.

**Amaç:** Kanal kurulumunu ve yönetimini formata göre ayırmak, manuel form doldurmayı
karar veren bir sohbetle değiştirmek, ve Claude'un yeni arketip tasarlamasını
denetlenebilir hâle getirmek.

**Mimari:** `ChannelConfig` bölünmez — ayrım sunum katmanında yapılır. Ortak alanlar
(`kimlik`, `zamanlama`, `youtube`, `otomasyon`) tek partial kümesinden çizilir; formata
özgü alanlar kendi partial'ında kalır. Sohbet, `sonnet_json` üzerinden şemalı karar
listesi üretir ve hiçbir şey onaysız yazılmaz. Arketip üretimi yapı kapısı → 3 uç metinle
render → vision kapısı zincirinden geçer.

**Teknoloji:** Flask + Jinja2 + HTMX + Alpine, SQLAlchemy Core, Pydantic, Playwright
(chromium), Claude CLI → OpenRouter düşme yolu, Google Studio vision havuzu.

**Spec:** `docs/superpowers/specs/2026-08-21-kanal-atolyesi-design.md`

---

## Dosya haritası

### Faz I — Format ayrımı

| Dosya | Sorumluluk |
|---|---|
| `src/short_bot/formats.py` (değişir) | `FormatSpec` kaydı: her formatın etiketi, glifi, hangi partial'ları çizdiği |
| `web/templates/_partials/core/identity.html.j2` (yeni) | ad, dil (kilitli), slug, handle |
| `web/templates/_partials/core/schedule.html.j2` (yeni) | cron, `enabled`, `archived` |
| `web/templates/_partials/core/youtube.html.j2` (yeni) | bağlantı + `auto_upload`, `privacy_status`, `category_id`, `ai_content`, `min_score_for_upload`, `credentials_from` |
| `web/routes/channel_edit.py` (değişir) | tek `/channels/<slug>/edit`, formata göre şablon; ortak alanların tek okuyucusu |
| `web/routes/reel_new.py`, `reel_edit.py` (silinir) | — |
| `web/templates/channels/edit_reel.html.j2` (silinir) | — |

### Faz II — Sohbet

| Dosya | Sorumluluk |
|---|---|
| `src/short_bot/channel_chat.py` (yeni) | Sohbet motoru: geçmiş → prompt, `SohbetCevabi` şeması, karar→YAML uygulayıcı |
| `src/short_bot/channel_diag.py` (yeni) | LLM'siz teşhis: kesik manşet, eşik altı eleme, yayın durgunluğu (düz SQL) |
| `web/routes/channel_chat.py` (yeni) | `/channels/new` (format seçimi), `/channels/new/<format>` (kurma sohbeti), `/channels/<slug>` (kanal sayfası), `/channels/<slug>/chat` (POST) |
| `web/templates/channels/pick_format.html.j2` (yeni) | Dört format kartı |
| `web/templates/channels/chat.html.j2` (yeni) | İki sütun: sohbet + taslak/kanal |
| `web/templates/_partials/chat_turn.html.j2` (yeni) | Tek konuşma turu: mesaj + karar listesi + fark + çipler |

### Faz III — Vision kapısı

| Dosya | Sorumluluk |
|---|---|
| `src/short_bot/archetype_gate.py` (yeni) | Yapı kapısı (düz kontrol) + 3 uç metin + vision kapısı |
| `src/short_bot/archetype_design.py` (yeni) | LLM → şablon üret → kapılardan geçir → kaydet |
| `src/short_bot/dna_smoke.py` (değişir) | `render_with_script()` ayrılır; kapı onu 3 metinle çağırır |

---

# FAZ I — Format ayrımı

### Task 1: `FormatSpec` kaydı

**Dosyalar:**
- Değiştir: `src/short_bot/formats.py`
- Test: `tests/test_formats_and_flas_narrator.py`

- [x] **Adım 1: Başarısız testi yaz**

```python
def test_format_spec_her_format_icin_var():
    from short_bot.formats import FORMATS, FormatSpec
    for k in ("card", "voiced", "yorum", "curated"):
        assert isinstance(FORMATS[k], FormatSpec)
    assert "reel" not in FORMATS

def test_format_spec_alanlari():
    from short_bot.formats import FORMATS
    yorum = FORMATS["yorum"]
    assert yorum.label == "Gündem Yorum"
    assert yorum.glyph == "❝"
    assert yorum.body_template == "channels/_body_yorum.html.j2"
    # ortak çekirdek HER formatta aynı
    assert FORMATS["card"].core == FORMATS["curated"].core
```

- [x] **Adım 2: Testi çalıştır, düşmesini doğrula**

`pytest tests/test_formats_and_flas_narrator.py -k format_spec -v` → `ImportError: FORMATS`

- [x] **Adım 3: Asgari kodu yaz**

```python
from dataclasses import dataclass, field

CORE_PARTIALS = ("core/identity", "core/schedule", "core/youtube", "core/autopilot")

@dataclass(frozen=True)
class FormatSpec:
    key: str
    label: str
    glyph: str
    subtitle: str
    body_template: str
    core: tuple[str, ...] = CORE_PARTIALS

FORMATS: dict[str, FormatSpec] = {
    "card":    FormatSpec("card", "Kart", "▭", "6 saniye, sessiz",
                          "channels/_body_card.html.j2"),
    "voiced":  FormatSpec("voiced", "Sesli", "♪", "6 sn kart + anlatım",
                          "channels/_body_voiced.html.j2"),
    "yorum":   FormatSpec("yorum", "Gündem Yorum", "❝", "Trends + yorumcu",
                          "channels/_body_yorum.html.j2"),
    "curated": FormatSpec("curated", "Kürate", "✂", "Reddit klip + persona",
                          "channels/_body_curated.html.j2"),
}
```

`FORMAT_LABELS` geriye dönük uyum için `{k: v.label for k, v in FORMATS.items()}`
olarak türetilir. `channel_format()` içindeki reel dalı **bu görevde kaldırılmaz**
(Task 8'de) — şimdilik `channel_format` "reel" döndürebilir, `FORMATS` içinde yoktur.

- [x] **Adım 4: Testi çalıştır, geçmesini doğrula**
- [x] **Adım 5: Commit** — `refactor(formats): FormatSpec kaydı — format başına partial listesi`

---

### Task 2: Ortak çekirdek partial'ları

**Dosyalar:**
- Oluştur: `web/templates/_partials/core/identity.html.j2`, `schedule.html.j2`,
  `youtube.html.j2`, `autopilot.html.j2`
- Test: `tests/test_web_core_partials.py` (yeni)

Partial'lar `cfg` (ChannelConfig) ve `yt_connected` (bool) alır. Alan adları **mevcut
`channel_edit.py` POST okuyucusuyla aynı kalır**: `name`, `handle`, `schedule_cron`,
`enabled`, `yt_auto_upload`, `yt_privacy_status`, `yt_category_id`, `yt_ai_content`,
`yt_min_score_for_upload`, `yt_cron_preset`, `yt_proxy_url` — **artı yeni**
`yt_credentials_from`.

- [x] **Adım 1: Başarısız testi yaz**

```python
import pytest
from short_bot.formats import FORMATS

@pytest.mark.parametrize("slug", ["galatasaray", "gundem-yorum", "dayidiyorki"])
def test_dort_ortak_alan_her_formatta_cizilir(client, slug):
    html = client.get(f"/channels/{slug}/edit").get_data(as_text=True)
    for alan in ("yt_privacy_status", "yt_min_score_for_upload",
                 "yt_category_id", "yt_credentials_from"):
        assert f'name="{alan}"' in html, f"{slug} sayfasında {alan} yok"
```

- [x] **Adım 2: Testi çalıştır** → üç slug için de FAIL (bugün hiçbirinde dördü birden yok)
- [x] **Adım 3: Partial'ları yaz** — mevcut `edit.html.j2`'deki YouTube bloğu kaynak alınır,
      `credentials_from` `edit_yorum.html.j2`'den alınır (tek yerde doğru yazılmış).
- [x] **Adım 4: Testi çalıştır** — Task 3–5 bitene kadar kısmi geçer; tam yeşil Task 5'te.
- [x] **Adım 5: Commit** — `feat(panel): ortak çekirdek partial'ları (kimlik/zamanlama/youtube/otomasyon)`

---

### Task 3: card/voiced sayfasını ortak partial'lara geçir

**Dosyalar:**
- Değiştir: `web/templates/channels/edit.html.j2`
- Oluştur: `web/templates/channels/_body_card.html.j2`, `_body_voiced.html.j2`
- Test: mevcut `tests/test_web_channel_edit_*.py` (7 dosya) geçmeye devam etmeli

- [x] **Adım 1: Mevcut testleri çalıştır, yeşil olduklarını gör (regresyon tabanı)**

`pytest tests/test_web_channel_edit_bg.py tests/test_web_channel_edit_feed.py
tests/test_web_channel_edit_generator.py tests/test_web_channel_edit_proxy.py
tests/test_web_channel_edit_trend_boost.py tests/test_web_channel_edit_trends.py
tests/test_web_channel_edit_voice.py tests/test_web_channel_edit_youtube.py -q`

- [x] **Adım 2: `edit.html.j2`'nin ortak bloklarını partial `include`'larıyla değiştir**
- [x] **Adım 3: `reel_*` alanlarını `edit.html.j2`'den çıkar** (card/voiced'de anlamsız)
- [x] **Adım 4: Aynı testleri tekrar çalıştır** — hepsi yeşil kalmalı
- [x] **Adım 5: Commit** — `refactor(panel): kart/sesli editörü ortak çekirdeği kullanıyor`

---

### Task 4: yorum sayfasını ortak partial'lara geçir

**Dosyalar:**
- Değiştir: `web/templates/channels/edit_yorum.html.j2` → `_body_yorum.html.j2`
- Değiştir: `web/routes/yorum.py` (POST okuyucusu ortak alanları da okur)
- Test: `tests/test_web_yorum.py`

- [x] **Adım 1: Başarısız testi yaz**

```python
def test_yorum_kanalinda_gizlilik_kaydedilir(client, tmp_channels):
    client.post("/channels/gundem-yorum/edit", data={
        "name": "Gündem Yorum", "schedule_cron": "0 9 * * *",
        "yt_privacy_status": "unlisted", "yt_min_score_for_upload": "7.5",
    })
    cfg = load_channel(tmp_channels / "gundem-yorum.yaml")
    assert cfg.youtube.privacy_status == "unlisted"
    assert cfg.youtube.min_score_for_upload == 7.5
```

- [x] **Adım 2: Çalıştır** → FAIL (`yorum.py` bu alanları okumuyor)
- [x] **Adım 3: Ortak alan okuyucusunu `channel_edit.py`'de tek fonksiyona çıkar
      (`_read_core(form, cfg)`) ve `yorum.py` ondan çağırsın**
- [x] **Adım 4: Çalıştır** → PASS
- [x] **Adım 5: Commit** — `fix(panel): gündem yorum kanalı gizlilik ve yükleme eşiği kazandı`

---

### Task 5: curated sayfasını ortak partial'lara geçir

Task 4'ün birebir aynısı, `curated.py` / `edit_curated.html.j2` için.
Test: `tests/test_web_curated.py`'a `test_kurate_kanalinda_gizlilik_kaydedilir` eklenir.

- [x] **Adım 1–5:** Task 4 ile aynı akış
- [x] **Commit** — `fix(panel): kürate kanalı gizlilik, kategori ve yükleme eşiği kazandı`

---

### Task 6: Reel montaj alanlarını kürate sayfasına taşı

**Ölçüm:** `edit_curated` zaten 30 alan taşıyor (`zoom`, `whoosh`, `flash`,
`highlight_color`, `music_mood`, oklar, varyasyonlar). Eksik olan **18 alan**:
`arc_mode`, `color_grade`, `comment_question`, `cut_pacing`, `font`, `identity_lock`,
`interrupts`, `layout`, `music_duck`, `music_volume`, `number_pop`, `series_enabled`,
`series_title`, `series_arc_length`, `sting_enabled`, `subject_framing`, `tempo_zones`,
`target_min`/`target_max`, `verify_footage`, `visual_loop`.

`generator_topic` ve `topic` **taşınmaz** — kürate konusunu Reddit'ten alır.

- [x] **Adım 1: Başarısız testi yaz**

```python
def test_kurate_sayfasi_montaj_alanlarini_tasiyor(client):
    html = client.get("/channels/dayidiyorki/edit").get_data(as_text=True)
    for alan in ("cut_pacing", "target_min", "target_max", "music_volume",
                 "series_enabled", "verify_footage", "subject_framing"):
        assert f'name="{alan}"' in html
```

- [x] **Adım 2: Çalıştır** → FAIL
- [x] **Adım 3: Alanları `edit_reel.html.j2`'den `_body_curated.html.j2`'ye taşı**
      (`reel_` öneki düşer; `curated.py` POST okuyucusu `cfg.reel`'e yazmaya devam eder)
- [x] **Adım 4: Çalıştır** → PASS
- [x] **Adım 5: `dayidiyorki` ile uçtan uca kaydet-oku testi**
- [x] **Adım 6: Commit** — `feat(panel): reel montaj ayarları kürate formatına taşındı`

---

### Task 7: Tek `/edit` rotası + 301 yönlendirmeler

**Dosyalar:**
- Değiştir: `src/short_bot/formats.py` (`FORMAT_EDIT_SUFFIX`, `edit_path` kalkar)
- Değiştir: `web/routes/channel_edit.py` (formata göre şablon seçer)
- Değiştir: `web/routes/yorum.py`, `curated.py` (edit rotaları 301'e iner)
- Değiştir: `dashboard.html.j2`, `_partials/channel_row.html.j2`, `channel_card.html.j2`
- Test: `tests/test_web_channels.py`

- [x] **Adım 1: Başarısız testi yaz**

```python
@pytest.mark.parametrize("slug", ["galatasaray", "gundem-yorum", "dayidiyorki"])
def test_tek_edit_rotasi(client, slug):
    assert client.get(f"/channels/{slug}/edit").status_code == 200

def test_eski_yollar_301(client):
    r = client.get("/channels/gundem-yorum/edit-yorum")
    assert r.status_code == 301
    assert r.headers["Location"].endswith("/channels/gundem-yorum/edit")
```

- [x] **Adım 2: Çalıştır** → FAIL
- [x] **Adım 3: `channel_edit.edit()` içinde `FORMATS[channel_format(cfg)]` ile şablon seç;
      eski rotalar `redirect(..., code=301)` döndürsün; şablonlarda `edit_path(c)` →
      `/channels/{{ c.slug }}/edit`**
- [x] **Adım 4: Çalıştır** → PASS
- [x] **Adım 5: `grep -rn "edit_path\|FORMAT_EDIT_SUFFIX" src/` boş dönmeli**
- [x] **Adım 6: Commit** — `refactor(panel): dört düzenleme rotası tek /edit'e indi`

---

### Task 8: Reel formatını kaldır

**DİKKAT:** Reel **pipeline'ı** silinmiyor — `reel.py`, `reel_narration.py`,
`reel_assembler.py` ve ~70 `test_reel_*.py` dosyası **kürate üretimi tarafından
kullanılıyor**. Silinen yalnız kanal-formatı yüzeyi.

**Dosyalar:**
- Sil: `web/routes/reel_new.py`, `web/routes/reel_edit.py`,
  `web/templates/channels/edit_reel.html.j2`,
  `web/templates/_partials/channel_card_reel.html.j2`
- Değiştir: `web/routes/__init__.py` (iki blueprint kaydı çıkar)
- Değiştir: `src/short_bot/formats.py` (`channel_format` reel dalı çıkar)
- Değiştir: `src/short_bot/channel_agent.py` (`apply_plan` sonrası yönlendirme)
- Sil/taşı: `tests/test_web_reel_new.py`, `test_web_reel_edit.py`,
  `test_web_reel_subscribe.py`, `test_web_reel_variation.py` → kürate rotasına uyarla

- [x] **Adım 1: `dayidiyorki` regresyon testi yaz (silmeden ÖNCE)**

```python
def test_dayidiyorki_kurate_olarak_yuklenir_ve_montaj_ayarlari_durur():
    cfg = load_channel(Path("config/channels/dayidiyorki.yaml"))
    assert channel_format(cfg) == "curated"
    assert cfg.reel is not None and cfg.reel.enabled       # montaj bloğu duruyor
    assert cfg.reel.highlight_color                         # alan kaybı yok
```

- [x] **Adım 2: Çalıştır** → PASS (mevcut davranış korunmalı)
- [x] **Adım 3: Dosyaları sil, blueprint kayıtlarını çıkar, `channel_format`'tan reel dalını al**
- [x] **Adım 4: `test_web_reel_*` testlerini kürate rotasına uyarla** (yolları `/edit`'e çevir)
- [x] **Adım 5: `pytest tests/ -q -k "reel or curated or channel or format or web"` — tümü yeşil**
- [x] **Adım 6: `grep -rn "edit-reel\|new-reel\|reel_edit\|reel_new" src/ tests/` boş**
- [x] **Adım 7: Commit** — `refactor(panel): reel kanal formatı kaldırıldı (pipeline duruyor)`

---

### Task 9: Faz I bütün doğrulaması

- [x] **Adım 1:** `pytest tests/ -q` — tam koşu, düşen test yok (spec öncesi bilinen iki
      düşen test hariç: `test_repo_gundem_yorum_channel_loads`,
      `test_curated_prompt_carries_the_rule_for_japanese`)
- [x] **Adım 2:** `verify` skill'iyle scratch panel ayağa kalksın; dört formatın
      `/edit` sayfası HTTP 200 dönsün ve dördünde de `yt_privacy_status` görünsün
- [x] **Adım 3:** Commit — `test: faz I doğrulaması`

---

# FAZ II — Sohbet

### Task 10: Teşhis motoru (LLM'siz)

**Dosyalar:**
- Oluştur: `src/short_bot/channel_diag.py`
- Test: `tests/test_channel_diag.py`

Üç bulgu, üçü de düz SQL + config karşılaştırması:

```python
@dataclass(frozen=True)
class Bulgu:
    kod: str                    # "kesik_manset" | "esik_alti" | "yayin_durgun"
    ozet: str
    gerekce: str
    duzeltme: list[tuple[str, object, object]]   # (alan, eski, yeni); boş = çözümü yok
```

- [x] **Adım 1: Testi yaz** — üç bulgu için ayrı test; `yayin_durgun` için
      `duzeltme == []` (operatör kararı, otomatik düzeltilmez)
- [x] **Adım 2: Çalıştır** → FAIL
- [x] **Adım 3: `channel_diag.py` yaz** — `dashboard_stats.py` desenini izle (saf sorgu
      katmanı, Flask'tan bağımsız)
- [x] **Adım 4: Çalıştır** → PASS
- [x] **Adım 5: Commit** — `feat(panel): kanal teşhis motoru (LLM'siz, düz SQL)`

---

### Task 11: Sohbet motoru

**Dosyalar:**
- Oluştur: `src/short_bot/channel_chat.py`
- Test: `tests/test_channel_chat.py`

```python
class Karar(BaseModel):
    alan: str
    deger: object
    ozet: str
    gerekce: str
    dikkat: bool = False
    alternatif_etiket: str = ""

class SohbetCevabi(BaseModel):
    mesaj: str
    kararlar: list[Karar] = []
    oneriler: list[str] = []
    kurmaya_hazir: bool = False
```

Sistem prompt'unun taşıması gereken **üslup kuralı** (spec C):
soru sorma, karar ver, gerekçe yaz, kullanıcı hiçbir şey yazmadan kurabilsin.

- [x] **Adım 1: Testi yaz** — sahte `llm` enjekte edilir (`sonnet_json` imzası),
      geçmişin prompt'a gömüldüğü ve kararların şemayla doğrulandığı test edilir
- [x] **Adım 2: Çalıştır** → FAIL
- [x] **Adım 3: Yaz** — geçmiş prompt'a gömülür, CLI oturumu kullanılmaz
- [x] **Adım 4: `uygula(kararlar, cfg)` → yeni `ChannelConfig`** (yazmaz, döndürür)
- [x] **Adım 5: Çalıştır** → PASS
- [x] **Adım 6: Commit** — `feat(panel): sohbet motoru — şemalı karar listesi`

---

### Task 12: Format seçimi ekranı

**Dosyalar:**
- Oluştur: `web/templates/channels/pick_format.html.j2`
- Değiştir: `web/routes/channel_new.py` → `/channels/new` format seçimi döndürür
- Test: `tests/test_web_channel_new.py`

- [x] **Adım 1: Testi yaz** — dört format kartı ve o formattaki canlı kanal slug'ları
- [x] **Adım 2–4:** kırmızı → yeşil
- [x] **Adım 5: Commit** — `feat(panel): yeni kanal format seçimi ekranı`

---

### Task 13: Kurma sohbeti ekranı

**Dosyalar:**
- Oluştur: `web/routes/channel_chat.py`, `web/templates/channels/chat.html.j2`,
  `_partials/chat_turn.html.j2`
- Test: `tests/test_web_channel_chat.py`

- [x] **Adım 1: Testi yaz** — POST `/channels/new/yorum/chat` sahte LLM ile karar listesi
      döndürür; **hiçbir YAML yazılmaz** (dizin sayısı değişmez)
- [x] **Adım 2–4:** kırmızı → yeşil
- [x] **Adım 5: "Kanalı kur" `apply_plan` benzeri yol — YAML + CSS + konu bankası**
      — **YANLIŞ İŞARETLENMİŞTİ.** 2026-08-21'de canlıda görüldü: yalnız YAML
      yazılıyordu. DNA üretimi, render kapısı ve CSS hiç bağlanmamıştı; sohbetle
      kurulan ilk kanal (`besiktas-gundem`) taslağın sabit `flas` şablonu ve
      kırmızı/sarı paletiyle kaydedildi. Konu bankası tohumu HÂLÂ bağlı değil
      (otomatik doldurma 4 saatte bir dolduruyor, bilinçli bırakıldı).
- [x] **Adım 6: Commit** — `feat(panel): kurma sohbeti`

---

### Task 14: Kanal sayfası + ayar sohbeti

**Dosyalar:**
- Değiştir: `web/routes/channel_chat.py` (`GET /channels/<slug>`)
- Test: `tests/test_web_channel_chat.py`

- [x] **Adım 1: Testi yaz** — sayfa açılışında **LLM çağrılmadığı** doğrulanır
      (sahte llm çağrı sayacı 0), teşhis satırları dolu gelir
- [x] **Adım 2–4:** kırmızı → yeşil
- [x] **Adım 5: Fark/onay akışı** — `POST /channels/<slug>/chat/apply` seçili kararları yazar
- [x] **Adım 6: `archived` + `enabled` bağlı alan uyarısı testi**
- [x] **Adım 7: Commit** — `feat(panel): kanal sayfası — teşhis + ayar sohbeti`

---

# FAZ III — Arketip tasarımı

### Task 15: Yapı kapısı

**Dosyalar:**
- Oluştur: `src/short_bot/archetype_gate.py`
- Test: `tests/test_archetype_gate.py`

```python
ZORUNLU_SECICILER = (".header", ".top", ".bot", ".photo", ".bg-img",
                     ".body-text", ".progress", ".handle")
ZORUNLU_DEGISKENLER = ("script.header_top", "script.header_bottom",
                       "body_html", "handle", "dna_css")

def yapi_kapisi(html: str) -> tuple[bool, str]: ...
```

- [x] **Adım 1: Testi yaz** — eksik `.body-text` reddedilir; sebep metni o seçiciyi içerir
- [x] **Adım 2–4:** kırmızı → yeşil
- [x] **Adım 5: Commit** — `feat(arketip): yapı kapısı — zorunlu slot ve değişken kontrolü`

---

### Task 16: Üç uç metinle render

**Dosyalar:**
- Değiştir: `src/short_bot/dna_smoke.py` (`render_with_script()` ayrılır)
- Test: `tests/test_dna_smoke.py`

Üç uç metin: en uzun manşet (kanal geçmişindeki en uzunu + %20), en çok satırlı gövde,
en uzun kaynak adı.

- [x] **Adım 1: Testi yaz** — `render_with_script` üç farklı metin için üç ayrı PNG üretir
- [x] **Adım 2–4:** kırmızı → yeşil
- [x] **Adım 5: Commit** — `feat(arketip): uç metinlerle render — tek örnek yanıltıyordu`

---

### Task 17: Vision kapısı

**Dosyalar:**
- Değiştir: `src/short_bot/archetype_gate.py`
- Test: `tests/test_archetype_gate.py`

`footage_matcher._judge_image_file` deseni izlenir: `vision_call` enjekte edilir,
vision yoksa **fail-open değil fail-closed** — arketip kaydedilmez (footage'tan farklı:
orada üretim durmamalı, burada bozuk şablon diske yazılmamalı).

- [x] **Adım 1: Testi yaz** — sahte vision "manşet kesilmiş" derse kapı reddeder
- [x] **Adım 2–4:** kırmızı → yeşil
- [x] **Adım 5: Commit** — `feat(arketip): vision kapısı — render karesine bakan denetim`

---

### Task 18: Arketip tasarım akışı

**Dosyalar:**
- Oluştur: `src/short_bot/archetype_design.py`
- Test: `tests/test_archetype_design.py`

- [x] **Adım 1: Testi yaz** — üç turda geçemezse **kaydedilmez**; dosya oluşmaz
- [x] **Adım 2–4:** kırmızı → yeşil
- [x] **Adım 5: `TEMPLATE-SPEC.md` + iki örnek şablon prompt'a girer**
- [x] **Adım 6: Commit** — `feat(arketip): Claude yeni şablon tasarlıyor (kapılı)`
- [x] **Adım 7 (EKSİKTİ): akışı panele bağla.** `tasarla` hiçbir yerden
      çağrılmıyordu — Faz III ölü koddu. Artık kanal sayfasında "yeni arketip":
      arka plan işi + HTMX durum yoklaması (`_partials/arketip_durum.html.j2`).
- [x] **Adım 8 (EKSİKTİ): render include hatası.** Aday şablon boş bir temp
      dizininde render ediliyordu; `renderer.py` Jinja arama yolunu şablonun
      dizini yapıyor ve `_auto_fit.js.j2` orada yok → akış HER denemede
      patlıyordu. İlk gerçek koşuda görüldü; paylaşılan `_*.j2` parçalar artık
      temp dizine kopyalanıyor.

---

### Task 19: Bütün doğrulama

- [x] **Adım 1:** `pytest tests/ -q` tam koşu
- [x] **Adım 2:** `verify` skill'iyle scratch panelde uçtan uca: format seç → sohbet →
      kanal kur → kanal sayfası → ayar değiştir
- [x] **Adım 3:** Negatif test: kasten taşan şablon vision kapısından geçmemeli
- [x] **Adım 4:** Commit — `test: kanal atölyesi bütün doğrulaması`
