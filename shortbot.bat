@echo off
chcp 65001 >nul
cd /d "%~dp0"
title short-bot — kontrol paneli

:menu
cls
echo.
echo  ╔════════════════════════════════════╗
echo  ║         SHORT-BOT KONTROL          ║
echo  ╚════════════════════════════════════╝
echo.

REM Durum tespiti
set STATUS=KAPALI
for /f "tokens=*" %%a in ('netstat -ano ^| findstr ":5005" ^| findstr "LISTENING"') do (
    set STATUS=ÇALIŞIYOR
)

echo  Durum: %STATUS%
echo  URL:   http://127.0.0.1:5005
echo.
echo  ────────────────────────────────────
echo   1. Başlat + tarayıcıyı aç
echo   2. Kapat
echo   3. Yalnızca tarayıcıyı aç
echo   4. CLI: yeni Short üret (son-dakika)
echo   5. CLI: yeni kanal yarat (interaktif)
echo   6. Kanal listesi
echo   7. Loglar (son üretim)
echo   0. Çıkış
echo  ────────────────────────────────────
echo.

set /p choice="  Seçim: "

if "%choice%"=="1" goto start
if "%choice%"=="2" goto stop
if "%choice%"=="3" goto open
if "%choice%"=="4" goto run_short
if "%choice%"=="5" goto new_channel
if "%choice%"=="6" goto list_channels
if "%choice%"=="7" goto logs
if "%choice%"=="0" exit /b 0
goto menu


:start
echo.
echo Sunucu başlatılıyor...
netstat -ano | findstr ":5005" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo Zaten çalışıyor.
) else (
    start "short-bot" /MIN cmd /k "cd /d %~dp0 && python -m short_bot web"
    timeout /t 4 /nobreak >nul
)
echo Tarayıcı açılıyor...
start "" "http://127.0.0.1:5005"
timeout /t 2 /nobreak >nul
goto menu


:stop
echo.
echo Sunucu kapatılıyor...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5005" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
taskkill /F /FI "WINDOWTITLE eq short-bot*" >nul 2>&1
echo Kapatıldı.
timeout /t 2 /nobreak >nul
goto menu


:open
start "" "http://127.0.0.1:5005"
timeout /t 1 /nobreak >nul
goto menu


:run_short
echo.
echo === Yeni Short üretiliyor (son-dakika kanalı) ===
echo Bu işlem 1-3 dakika sürebilir.
echo.
python -m short_bot run --channel son-dakika --max 1
echo.
pause
goto menu


:new_channel
echo.
echo === Yeni Kanal Yarat ===
echo.
set /p ch_name="Kanal adı: "
set /p ch_lang="Dil (tr/en/de/es/fr): "
set /p ch_keywords="Keywords (virgülle ayır): "
set /p ch_hint="Konu ipucu (opsiyonel, Enter geç): "
echo.
echo Opus DNA üretiliyor (~30-60s)...
python -m short_bot create-channel --name "%ch_name%" --language "%ch_lang%" --keywords "%ch_keywords%" --topic-hint "%ch_hint%"
echo.
pause
goto menu


:list_channels
echo.
echo === Kanal Listesi ===
echo.
python -m short_bot list-channels
echo.
pause
goto menu


:logs
echo.
echo === Son log dosyası ===
echo.
for /f "delims=" %%a in ('dir /b /o-d "logs\runs\*.log" 2^>nul') do (
    echo --- %%a ---
    type "logs\runs\%%a"
    goto :logs_done
)
echo Henüz log yok.
:logs_done
echo.
pause
goto menu
