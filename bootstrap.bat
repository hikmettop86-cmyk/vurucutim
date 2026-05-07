@echo off
cd /d "%~dp0"
title vurucu-tim-bootstrap

echo.
echo === Vurucu TIM — Bootstrap Kurulum ===
echo.

:: ─── Python surumu kontrol ───────────────────────────────────────────────────
echo [1/7] Python surumu kontrol ediliyor...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo HATA: Python bulunamadi.
    echo       https://www.python.org/downloads/ adresinden Python 3.11+ yukle.
    echo       Kurulum sirasinda "Add python.exe to PATH" kutusunu isaretlemeyi unutma.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set PYMAJ=%%a
    set PYMIN=%%b
)
if %PYMAJ% LSS 3 (
    echo HATA: Python 3.11+ gerekli, bulunan: %PYVER%
    echo       https://www.python.org/downloads/ adresinden guncelleyin.
    pause
    exit /b 1
)
if %PYMAJ% EQU 3 if %PYMIN% LSS 11 (
    echo HATA: Python 3.11+ gerekli, bulunan: %PYVER%
    echo       https://www.python.org/downloads/ adresinden guncelleyin.
    pause
    exit /b 1
)
echo     OK: Python %PYVER%

:: ─── Bagimliliklar ───────────────────────────────────────────────────────────
echo.
echo [2/7] Bagimliliklar yukleniyor (pip install -e .) ...
python -m pip install -e . --quiet
if %errorlevel% neq 0 (
    echo HATA: pip install basarisiz. Yukaridaki ciktiyi inceleyin.
    pause
    exit /b 1
)
echo     OK: Bagimliliklar yuklendi.

:: ─── Playwright Chromium ─────────────────────────────────────────────────────
echo.
echo [3/7] Playwright Chromium indiriliyor/kontrol ediliyor...
python -m playwright install chromium
if %errorlevel% neq 0 (
    echo HATA: playwright install chromium basarisiz.
    pause
    exit /b 1
)
echo     OK: Playwright Chromium hazir.

:: ─── Claude CLI kontrol ──────────────────────────────────────────────────────
echo.
echo [4/7] Claude CLI kontrol ediliyor...
claude --version >nul 2>&1
if %errorlevel% neq 0 (
    echo UYARI: "claude" komutu bulunamadi.
    echo        https://claude.ai/claude-code adresinden Claude Code CLI'yi yukle,
    echo        ardindan "claude login" komutuyla giris yap.
    echo        Claude olmadan bot calisAmaz — kurulumdan sonra bootstrap.bat tekrar calistir.
    echo.
) else (
    echo     OK: Claude CLI mevcut.
)

:: ─── ffmpeg kontrol ──────────────────────────────────────────────────────────
echo.
echo [5/7] ffmpeg kontrol ediliyor...
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo UYARI: "ffmpeg" komutu bulunamadi.
    echo        https://www.gyan.dev/ffmpeg/builds/ adresinden indirip
    echo        C:\ffmpeg\bin\ klasorune cikart ve PATH'e ekle.
    echo        Alternatif: config\settings.yaml'da ffmpeg_path'i tam yol gir.
    echo.
) else (
    echo     OK: ffmpeg mevcut.
)

:: ─── Gerekli klasorler ───────────────────────────────────────────────────────
echo.
echo [6/7] Gerekli klasorler olusturuluyor...
for %%d in (
    "data"
    "data\locks"
    "data\cache"
    "data\youtube_credentials"
    "logs"
    "logs\runs"
    "output"
    "assets\music\breaking"
    "assets\music\neutral"
    "assets\music\upbeat"
) do (
    if not exist %%d (
        mkdir %%d >nul 2>&1
    )
)

:: .gitkeep dosyalari (bos klasorlerin git tarafindan izlenmesi icin)
for %%d in (
    "data\locks"
    "data\cache"
    "logs\runs"
    "output"
    "assets\music\breaking"
    "assets\music\neutral"
    "assets\music\upbeat"
) do (
    if not exist "%%~d\.gitkeep" (
        type nul > "%%~d\.gitkeep" 2>nul
    )
)
echo     OK: Klasorler hazir.

:: ─── settings.yaml yoksa ornekten kopyala ───────────────────────────────────
if not exist "config\settings.yaml" (
    if exist "config\settings.yaml.example" (
        copy "config\settings.yaml.example" "config\settings.yaml" >nul
        echo.
        echo UYARI: config\settings.yaml bulunamadi — ornek dosyadan kopyalandi.
        echo        Lutfen config\settings.yaml dosyasini acip ffmpeg ve claude yollarini duzenle.
        echo.
    )
)

:: ─── Smoke test ──────────────────────────────────────────────────────────────
echo.
echo [7/7] Smoke test calistiriliyor...
python -c "from short_bot.web import create_app; create_app(scheduler=False); print('OK')"
if %errorlevel% neq 0 (
    echo HATA: Smoke test basarisiz — yukaridaki hata mesajini inceleyin.
    pause
    exit /b 1
)
echo     OK: Smoke test gecti.

:: ─── Bitis ───────────────────────────────────────────────────────────────────
echo.
echo ============================================================
echo   Kurulum tamam!
echo.
echo   Sonraki adim:
echo     1. config\settings.yaml dosyasini kontrol et
echo        (ffmpeg_path, claude_cli_path, port)
echo     2. start.bat ile paneli baslat
echo        veya cift tiklayarak ac
echo ============================================================
echo.
pause
