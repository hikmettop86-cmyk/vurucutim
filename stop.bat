@echo off
cd /d "%~dp0"
title short-bot stopper

echo.
echo === short-bot panel kapaniyor ===
echo.

set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5005" ^| findstr "LISTENING"') do (
    set FOUND=1
    echo PID %%a kapatiliyor...
    taskkill /F /PID %%a >nul 2>&1
)

taskkill /F /FI "WINDOWTITLE eq short-bot*" >nul 2>&1

if %FOUND%==0 (
    echo Panel zaten calismiyor.
) else (
    echo Panel kapatildi.
)

echo.
timeout /t 2 /nobreak >nul
