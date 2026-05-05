@echo off
cd /d "%~dp0"
title short-bot starter

echo.
echo === short-bot panel basliyor ===
echo.

netstat -ano | findstr ":5005" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo Panel zaten calisiyor. Tarayici aciliyor...
    start "" "http://127.0.0.1:5005"
    timeout /t 2 /nobreak >nul
    exit /b 0
)

start "short-bot" /MIN cmd /k "cd /d %~dp0 && python -m short_bot web"

echo Sunucu basliyor...
timeout /t 4 /nobreak >nul

echo Tarayici aciliyor: http://127.0.0.1:5005
start "" "http://127.0.0.1:5005"

echo.
echo Panel acildi. Sunucu penceresi minimize.
echo Kapatmak icin: stop.bat
echo.
timeout /t 3 /nobreak >nul
