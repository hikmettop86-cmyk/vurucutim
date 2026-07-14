# Vahşi Mizah Arketipi — Tasarım Dokümanı

**Tarih:** 2026-07-15
**Durum:** Onaylandı (kullanıcı), implementasyona hazır
**Dal:** feature/electron-installer (yayınlanmayacak)

## Amaç

Hayvan/doğa konularını, hayvanı bir mahalle karakterine büründürerek **komik ama
gerçek bilgiye dayanan** bir tonda anlatan yeni bir reel arketipi (`vahsi-mizah`).
İlham: DiscoverNow'un "Bal Porsuğunun Aşk Hayatı" videosu (YouTube G-by1UTuo2o) —
Türk dizisi/pop-kültür referansları + sosyal medya dili + argo + gerçek biyoloji.

Sonuç: kullanıcı yeni bir kanal kurarken bu personayı seçebilsin ve sistem bu
tonda voiceover'lı shorts üretsin.

## Fizibilite (kanıtlandı)

Sonnet 5'e bal porsuğu transcript'i few-shot örnek olarak verilip KARGA için
senaryo yazdırıldı (OpenRouter, gerçek çağrı). Çıktı: "Karga Recep — mahallenin
unutmayan hafızası", Behzat Ç. / Kurtlar Vadisi / Çukur referansları (hepsi gerçek
ve tema-uyumlu), karganın yüz tanıma / kin tutma / alet kullanma / "karga cenazesi"
davranışları (hepsi bilimsel olarak doğru). **Referans bankası GEREKMİYOR** —
Sonnet gerçek referansları biliyor ve konuya doğru oturtuyor.

## Mimari bulgu (tasarımın temeli)

**Reel anlatım motoru (`reel_narration.py`) DNA tonunu HİÇ kullanmıyor.** Prompt
sabit "ilginç bilgiler / nasıl çalışır" tonunda. `bilim-tarihinin`'in DNA'sındaki
"mizah YASAK" kuralı bile reel'e ulaşmıyor (o kural yalnız kart-format `script_writer`'a
giriyor). Yani mizah tonu için reel motoruna YENİ bir persona katmanı eklenmeli —
şu an orada hiç yok.

## Yaklaşım: izole persona enjeksiyonu

İki seçenek vardı:
- **(A) İzole persona enjeksiyonu** — yalnız mizah personası olan kanallar yeni yola
  girer; mevcut reel kanalları (gartengeheimnisse, bilim-tarihinin) HİÇ etkilenmez.
- (B) reel_narration'ı tümden tona-duyarlı yap — daha genel ama her mevcut kanalı
  etkiler → regresyon riski.

**(A) seçildi.** Bu oturumun tekrarlanan dersi: izolasyon + sessiz-bozulmama.
Çalışan kanalları riske atmamak için mizah ayrı bir yol.

## Bileşenler

### 1. Persona işareti — `ReelConfig.persona`
`src/short_bot/config.py`, `ReelConfig`'e yeni alan:
```python
persona: str = ""   # "" = kişiliksiz (bugünkü davranış), "vahsi_mizah" = mizah modu
```
Boş varsayılan KRİTİK: mevcut tüm kanallar `persona=""` ile bugünkü prompt'u alır →
sıfır regresyon. `to_channel_data` sözlüğüne de eklenir (web/DNA katmanı için).

### 2. Persona metni — `src/short_bot/persona.py` (YENİ)
```python
class Persona(BaseModel):
    slug: str
    few_shot: str          # bal porsuğu örneği (dil paketinden gelir)
    rules: list[str]        # 6 mizah kuralı
    humor_check: bool = True

def load_persona(slug: str, *, language: str) -> Persona | None
    # slug == "" → None (kişiliksiz). Bilinmeyen slug → RuntimeError (sessiz
    #   kişiliksiz'e düşmek YASAK — kullanıcı mizah seçtiyse mizah almalı).
    # few_shot ve rules DİL PAKETİNDEN okunur (bkz. bileşen 4).

def persona_block(persona: Persona) -> str
    # reel_narration prompt'una eklenecek metin bloğu (few_shot + kurallar).
```
Neden dil paketinden: few-shot örneği ve kurallar Türkçe'ye özel; Almanca kanala
Türkçe "Aşk-ı Memnu" örneği vermek dil sızıntısıdır (multilingual-channels ilkesi).

### 3. Persona enjeksiyonu — `reel_narration.py`
`build_reel_prompt` sonuna, `write_reel_narration` içinde:
```python
persona = load_persona(getattr(channel.reel, "persona", ""), language=channel.language)
if persona:
    prompt = prompt + "\n\n" + persona_block(persona)
```
Persona `None` ise prompt bugünkü gibi kalır. Mizah senaryosu YİNE reel ARK yapısına
(hook→tırmanış→tepe→callback) uyar — persona_block tonu değiştirir, yapıyı değil.

### 4. Dil paketi mizah bloğu — `langpacks/tr.json`
Yeni anahtar `personas`:
```json
"personas": {
  "vahsi_mizah": {
    "few_shot": "<bal porsuğu örneği>",
    "rules": ["HAYVANI KARAKTERE BÜRÜNDÜR ...", "GERÇEK dizi referansı ...", ...]
  }
}
```
`lang_pack.py`'ye `LangPack.personas: dict = {}` alanı + `validate_pack` kontrolü
(mizah personası varsa few_shot ve rules dolu olmalı). Diğer diller (de, en) bu
anahtarı taşımaz → o dillerde `vahsi_mizah` personası `load_persona` ile RuntimeError
verir (Türkçe'ye özel olduğu açıkça belli olur, sessiz İngilizce'ye düşmez).

### 5. Mizah doğrulama kapısı — `src/short_bot/reel_humor_check.py` (YENİ)
`reel_factcheck.py`'nin kardeşi, aynı desen:
```python
class HumorIssue(BaseModel):
    problem: str            # ne zayıf
    kind: str = "humor"     # "humor" | "reference" | "biology"

def check_humor(topic, *, text, language, claude_path=..., model=..., backend=...,
                api_key=..., invoke=None) -> list[HumorIssue]
    # İkinci Sonnet çağrısı senaryoyu denetler:
    #   - KOMİK mi (zorlama/jenerik değil, gerçekten esprili mi)?
    #   - Referanslar GERÇEK mi (uydurma dizi/karakter var mı)?
    #   - Biyoloji DOĞRU mu (mizah, yanlış bilgiyi meşrulaştırmasın)?
    # Kapı ÇÖKERSE boş liste (üretim durmaz) + log — check_narration ile aynı ilke.

def humor_feedback(issues: list[HumorIssue]) -> str
    # yeniden yazım için prompt eki.
```

### 6. Kapı wiring — `reel_narration.py`
Persona varsa, MEVCUT olgu kapısının (`check_narration`) yanına mizah kapısı eklenir:
```python
if persona and persona.humor_check:
    mizah = check_humor(topic, text=n.full_text(), language=..., ...)
    if mizah:
        n = _budgeted(prompt + humor_feedback(mizah))   # bir kez yeniden yaz
        hala = check_humor(...)
        if hala:
            raise ValueError("senaryo mizah denetiminden geçemedi (2 deneme): ...")
```
**Olgu kapısı da açık kalır** — mizah, yanlış bilgiye izin vermez. İki kapı da geçilir.

### 7. Görsel arketip — `config/archetypes.json`
Yeni giriş `vahsi-mizah`: sıcak/enerjik palet (belgesel-üstü büyük altyazı için
yüksek kontrast), pexels_queries hayvan/doğa odaklı.

ÖNEMLİ: reel formatı görsel katmanı SABİT `reel_overlay.html.j2` kullanır (kod
keşfiyle doğrulandı: `reel_render.py` her zaman bu tek template'i yükler).
archetypes.json'daki arketipe-özel `.j2` dosyaları KART-format (`script_writer`)
içindir — reel için değil. Bu yüzden `vahsi-mizah` için YENİ bir `.j2` GEREKMEZ;
archetypes.json girişi yalnızca DNA renk/font defaults ve kanal-kurma-ajanının
personayı tanıması için. Mizah metinde, görselde değil.
Not: archetypes.json şeması bir arketip için `.j2` varlığını ZORUNLU kılıyorsa,
bu implementasyonda kod keşfiyle netleşir; zorunluysa mevcut bir reel-uyumlu
görsel arketibin defaults'ı yeniden kullanılır, yeni görsel dil icat edilmez.

### 8. Kanal kurma ajanı entegrasyonu
Arketip `archetypes.json`'a girince kanal kurma ajanı (`channel_agent.py`) onu
otomatik tanır. Ek: ajan bir mizah niyeti algılarsa (`_normalize_niche` veya plan
adımında) `reel.persona = "vahsi_mizah"` işaretler. Bu, ajanın DnaSpec kurulumuna
küçük bir dokunuş.

## Veri akışı

```
kanal (reel.persona="vahsi_mizah", language="tr")
  → write_reel_narration
      → build_reel_prompt (temel ARK prompt'u)
      → load_persona("vahsi_mizah", language="tr")  [dil paketinden few_shot+rules]
      → prompt += persona_block
      → Sonnet → ReelNarration (hook/beats/close, mizah tonunda)
      → check_narration (olgu kapısı)   ── mevcut
      → check_humor (mizah kapısı)       ── YENİ, persona varsa
      → geçerse üretime devam (TTS → footage → montaj)
```

## Hata yönetimi

- `load_persona` bilinmeyen slug → RuntimeError (sessiz kişiliksiz'e düşme YASAK).
- Türkçe-olmayan dilde `vahsi_mizah` → RuntimeError (dil paketinde persona yok).
- `check_humor` LLM çökerse → boş liste + log (tek arıza üretimi durdurmasın).
- Mizah kapısı 2 denemede geçemezse → ValueError (sessiz kalitesiz video YOK).
- `persona=""` (mevcut kanallar) → tüm mizah yolu atlanır, sıfır regresyon.

## Test

- **Regresyon:** `persona=""` olan kanal bugünkü prompt'u AYNEN alır (persona_block
  eklenmez). Mevcut reel testleri değişmeden geçer.
- **Enjeksiyon:** `persona="vahsi_mizah"` prompt'a few_shot + kuralları ekler.
- **Dil izolasyonu:** `vahsi_mizah` + `language="de"` → RuntimeError.
- **Mizah kapısı:** uydurma referanslı / zorlama / yanlış-biyolojili senaryo
  `check_humor` tarafından yakalanır (invoke enjeksiyonuyla, gerçek LLM'siz).
- **Kapı çökmesi:** `check_humor` exception → boş liste, üretim durmaz.
- **İki kapı birlikte:** olgu + mizah kapısı aynı üretimde çalışır.
- **Uçtan uca (gerçek Sonnet, işaretli/manuel):** bir mizah kanalı kurup gerçek
  bir video üret, kare kare incele (bu oturumun doğrulama disiplini).

## Kapsam dışı (YAGNI)

- Çok dilli mizah (Almanca/İngilizce personalar) — sonraya.
- Hayvan-dışı konular (bilim/tarih mizahı) — sonraya.
- Küratörlü referans bankası — fizibilite kanıtladı ki gerekmiyor.
- reel_narration'ı tümden tona-duyarlı yapmak (Yaklaşım B) — reddedildi.

## Dokunulacak dosyalar

- `src/short_bot/config.py` — `ReelConfig.persona` + `to_channel_data`
- `src/short_bot/persona.py` — YENİ
- `src/short_bot/reel_humor_check.py` — YENİ
- `src/short_bot/reel_narration.py` — persona enjeksiyonu + mizah kapısı wiring
- `src/short_bot/lang_pack.py` — `LangPack.personas` + validate
- `src/short_bot/langpacks/tr.json` — `personas.vahsi_mizah`
- `config/archetypes.json` + yeni `.j2` template
- `src/short_bot/channel_agent.py` — mizah niyeti → persona işareti
- `tests/` — yukarıdaki test listesi (git add -f)
