@echo off
cd /d "%~dp0"
title vurucu-tim-update

echo.
echo === Vurucu TIM — Guncelleme ===
echo.
echo Bu script ZIP guncellemesinden sonra calistirilir.
echo Sadece Python paketlerini ve smoke testi kontrol eder.
echo Bilgisayara YENI bir kurulum yapiyorsan bootstrap.bat'i calistir.
echo.

rem 1. Stop panel if running (port 5005)
echo [1/3] Mevcut panel kapatiliyor (varsa)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5005" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

rem 2. Update Python deps (idempotent — fast if nothing changed)
echo [2/3] Python paketleri guncelleniyor...
pip install -e . --quiet --upgrade
if errorlevel 1 (
    echo.
    echo HATA: pip install basarisiz. Internet baglantisi var mi?
    echo Bilgisayar tamamen yeni ise bootstrap.bat calistir.
    pause
    exit /b 1
)

rem 3. Smoke test
echo [3/3] Smoke test...
python -c "from short_bot.web import create_app; create_app(scheduler=False); print('OK')" 2>&1
if errorlevel 1 (
    echo.
    echo HATA: Smoke test basarisiz. Bagimliliklar eksik olabilir.
    echo bootstrap.bat calistir.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo === Guncelleme tamam! ===
echo.
echo Paneli baslatmak icin: start.bat
echo ============================================================
echo.
timeout /t 3 /nobreak >nul
