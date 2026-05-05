@echo off
chcp 65001 >nul
cd /d "%~dp0"
title short-bot — starter

echo.
echo === short-bot panel başlatılıyor ===
echo.

REM Eğer 5005 portu zaten dinleniyorsa zaten açık demektir
netstat -ano | findstr ":5005" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo Panel zaten çalışıyor. Tarayıcı açılıyor...
    start "" "http://127.0.0.1:5005"
    timeout /t 2 /nobreak >nul
    exit /b 0
)

REM Yeni cmd penceresinde, minimize ederek başlat
start "short-bot" /MIN cmd /k "cd /d %~dp0 && python -m short_bot web"

REM Server'ın ayağa kalkması için bekle
echo Sunucu başlıyor...
timeout /t 4 /nobreak >nul

REM Tarayıcıyı aç
echo Tarayıcı açılıyor: http://127.0.0.1:5005
start "" "http://127.0.0.1:5005"

echo.
echo Panel açıldı. Sunucu penceresi minimize.
echo Kapatmak için: stop.bat
echo.
timeout /t 3 /nobreak >nul
