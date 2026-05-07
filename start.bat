@echo off
cd /d "%~dp0"
title vurucu-tim-launcher

echo.
echo === Vurucu TIM panel basliyor (arka planda) ===
echo.

netstat -ano | findstr ":5005" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo Panel zaten calisiyor. Tarayici aciliyor...
    start "" "http://127.0.0.1:5005"
    timeout /t 2 /nobreak >nul
    exit /b 0
)

rem Hidden launch via VBS — no cmd window appears, logs go to panel_*.log
wscript "%~dp0start_silent.vbs"

echo Sunucu arka planda baslatildi (gizli).
echo Loglar: panel_stdout.log / panel_stderr.log
echo.

timeout /t 4 /nobreak >nul

start "" "http://127.0.0.1:5005"
echo Tarayici aciliyor: http://127.0.0.1:5005
echo Kapatmak icin: stop.bat
echo.
timeout /t 3 /nobreak >nul
