# Vurucu TIM — Windows Kurulum Kılavuzu

> **Hedef kitle:** Sıfırdan kurulum yapacak herkes.  
> Komutlar **Komut İstemi (cmd)** veya **PowerShell** ile aynı şekilde çalışır.

---

## Önkoşullar

### Windows 10 / 11

64-bit Windows 10 veya Windows 11 gereklidir.

### Python 3.11+

1. [python.org/downloads](https://www.python.org/downloads/) adresinden en son Python 3.11+ sürümünü indir.
2. Kurulum sihirbazında **"Add python.exe to PATH"** kutusunu işaretle — bu adımı atlama.
3. Kurulumu doğrula:

```
python --version
```

`Python 3.11.x` (veya daha yüksek) görmüyorsan kurulumu tekrar yap.

### ffmpeg

ffmpeg, video renderlamak için zorunludur.

1. [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/) adresinden **"ffmpeg-release-essentials.zip"** indir.
2. ZIP'i `C:\ffmpeg\` klasörüne çıkart (içinde `bin\ffmpeg.exe` olmalı).
3. `C:\ffmpeg\bin` yolunu sistem PATH'ine ekle:
   - `Win+R` → `sysdm.cpl` → Gelişmiş → Ortam Değişkenleri
   - `Path` → Düzenle → Yeni → `C:\ffmpeg\bin`
4. Yeni bir terminal aç, doğrula:

```
ffmpeg -version
```

**Alternatif:** PATH'e eklemek istemiyorsan `config\settings.yaml` içinde tam yolu ver:

```yaml
ffmpeg_path: C:\ffmpeg\bin\ffmpeg.exe
```

### Claude Code CLI

Bot, metin oluşturmak için Claude'u kullanır.

1. [claude.ai/claude-code](https://claude.ai/claude-code) adresine git ve kurulum talimatlarını izle.
2. Kurulumdan sonra giriş yap:

```
claude login
```

3. Doğrula:

```
claude --version
```

Komut bulunamazsa `config\settings.yaml` içinde tam yolu gir:

```yaml
claude_cli_path: C:\Users\KULLANICI\AppData\Roaming\npm\claude.cmd
```

### Git (opsiyonel)

Sadece `git clone` ile indirmek istiyorsan gerekli.  
[git-scm.com/download/win](https://git-scm.com/download/win) adresinden indir.

---

## Kurulum (5 Adım)

### 1. Repo'yu İndir

**Git ile:**

```
git clone https://github.com/KULLANICI/vurucu-tim.git
cd vurucu-tim
```

**ZIP ile:**

GitHub sayfasında **Code → Download ZIP** → ZIP'i bir klasöre çıkart → proje klasörüne gir.

### 2. Proje Klasörüne Gir

```
cd C:\Users\KULLANICI\Desktop\vurucu-tim
```

Gerçek yolu kullan — `vurucu-tim` nerede çıkarttıysan oraya gir.

### 3. `bootstrap.bat` Çalıştır

```
bootstrap.bat
```

Bu script:
- Python sürümünü kontrol eder
- Tüm bağımlılıkları kurar (`pip install -e .`)
- Playwright Chromium tarayıcısını indirir
- Claude CLI ve ffmpeg varlığını kontrol eder
- Gerekli klasörleri oluşturur (`data/`, `output/`, `logs/`, `assets/music/` vb.)
- `config\settings.yaml` yoksa şablon dosyasından kopyalar
- Kurulum smoke testi çalıştırır

Hata oluşursa ekranda açıklama yazar — düzeltip tekrar çalıştırabilirsin.

### 4. `config\settings.yaml` Düzenle

```
notepad config\settings.yaml
```

Minimum kontrol edilecek ayarlar:

```yaml
ffmpeg_path: ffmpeg          # PATH'deyse "ffmpeg" yeter, değilse tam yol gir
claude_cli_path: claude      # PATH'deyse "claude" yeter, değilse tam yol gir
web:
  host: 127.0.0.1
  port: 5005                 # Başka program 5005'i kullanıyorsa değiştir
```

### 5. Paneli Başlat

`start.bat` dosyasına **çift tıkla** (ya da terminalden çalıştır):

```
start.bat
```

Birkaç saniye sonra tarayıcı otomatik açılır: [http://127.0.0.1:5005](http://127.0.0.1:5005)

---

## İlk Kullanım

### Kanal Oluşturma

1. Tarayıcıda `http://127.0.0.1:5005` aç.
2. Sol menüden **"Kanallar" → "Yeni kanal"** tıkla.
3. Kanal ismi, dil ve keywords gir.
4. **"DNA Üret"** butonuna bas → Claude Opus kanal DNA'sını oluşturur (~30-60 saniye).
5. DNA önizlemesi gözüktükten sonra **"Kaydet"**.

### İlk Short'u Üret

1. Kanal listesinden kanalın adına tıkla (edit sayfası açılır).
2. **"▶ Şimdi üret"** butonuna bas.
3. İlk short yaklaşık 3-5 dakika sürer (Playwright cold-start dahil).
4. Tamamlandığında "Son Üretimler" bölümünde görünür.

### Otomatik Zamanlama

Kanal oluştururken ya da düzenlerken **cron takvimi** ayarlanabilir (örn. her 4 saatte bir).  
Panel çalışırken scheduler arka planda otomatik çalışır.

---

## YouTube Entegrasyonu (Opsiyonel, Kanal Başına)

Her kanal için YouTube yüklemesi ayrı ayrı yapılandırılır.

### Adım 1 — Google Cloud Projesi

1. [console.cloud.google.com](https://console.cloud.google.com) adresi.
2. Yeni proje oluştur (örn. `vurucu-tim`).
3. Soldaki menüden **"APIs & Services" → "Library"** → aşağıdaki iki API'yi etkinleştir:
   - **YouTube Data API v3**
   - **YouTube Analytics API**

### Adım 2 — OAuth Onay Ekranı

1. **"APIs & Services" → "OAuth consent screen"**.
2. **External** seç → ilerle.
3. App name gir (örn. `Vurucu TIM`), kaydet.
4. **"Test users"** bölümüne kendi Gmail adresini ekle.

### Adım 3 — OAuth İstemci Kimliği

1. **"APIs & Services" → "Credentials" → "Create Credentials" → "OAuth client ID"**.
2. Application type: **Web application**.
3. Authorized redirect URIs: `http://127.0.0.1:5005/oauth/callback`
4. Oluştur → **"Download JSON"** (credentials JSON dosyasını indir).

### Adım 4 — Panelden Bağla

1. Panel'de kanalın edit sayfasını aç.
2. **"↑ Yükle"** butonu ile indirdiğin JSON'u yükle.
3. **"▶ YouTube Bağla"** butonuna bas → Google izin ekranı açılır.
4. Hesabı seç → izin ver → yönlendirilirsin → "Bağlandı" mesajı görünür.

---

## Otomatik Başlatma (Bilgisayar Açıldığında)

1. `Win+R` → `shell:startup` yaz → Enter.
2. Açılan Başlangıç klasöründe `start_silent.vbs` dosyasının **kısayolunu** oluştur:
   - `start_silent.vbs` dosyasına sağ tıkla → "Kısayol oluştur".
   - Kısayolu kut → Başlangıç klasörüne yapıştır.
3. Artık bilgisayar her açıldığında panel arka planda sessizce başlar.

Paneli durdurmak için: `stop.bat` çalıştır ya da çift tıkla.

Loglar: proje kökündeki `panel_stdout.log` ve `panel_stderr.log`.

---

## Sorun Giderme (SSS)

| Sorun | Çözüm |
|---|---|
| **"Port 5005 already in use"** | `stop.bat` çalıştır, ardından `start.bat` tekrar. |
| **"claude binary not found"** | `claude` PATH'de değil — `config\settings.yaml`'da `claude_cli_path` için tam yol gir. |
| **"ffmpeg not found"** | `ffmpeg` PATH'de değil — `config\settings.yaml`'da `ffmpeg_path` için tam yol gir (örn. `C:\ffmpeg\bin\ffmpeg.exe`). |
| **"Pipeline failed: keywords boş olamaz"** | Kanal RSS-mode'da keywords girilmemiş. Edit sayfasından keywords ekle veya generator-mode'a geç. |
| **"503 from YouTube"** | Token süresi dolmuş. Kanal edit → "Tümünü sıfırla" → tekrar "YouTube Bağla". |
| **Playwright timeout** | `playwright install chromium` komutunu çalıştır (bootstrap.bat zaten çalıştırmış olmalı). |
| **Tarayıcı açılmıyor** | `http://127.0.0.1:5005` adresini manuel aç. `panel_stderr.log` dosyasını kontrol et. |
| **"Python 3.11+ gerekli"** | `python --version` çalıştır — eski sürüm varsa python.org'dan yenisini kur. |
