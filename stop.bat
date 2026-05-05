@echo off
chcp 65001 >nul
cd /d "%~dp0"
title short-bot — stopper

echo.
echo === short-bot panel kapatılıyor ===
echo.

set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5005" ^| findstr "LISTENING"') do (
    set FOUND=1
    echo PID %%a sonlandırılıyor...
    taskkill /F /PID %%a >nul 2>&1
)

REM "short-bot" başlıklı pencereyi kapat (start.bat'in açtığı)
taskkill /F /FI "WINDOWTITLE eq short-bot*" >nul 2>&1

if %FOUND%==0 (
    echo Panel zaten çalışmıyor.
) else (
    echo Panel kapatıldı.
)

echo.
timeout /t 2 /nobreak >nul
