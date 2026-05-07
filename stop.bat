@echo off
cd /d "%~dp0"
title vurucu-tim-stopper

echo.
echo === Vurucu TIM panel kapaniyor ===
echo.

set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5005" ^| findstr "LISTENING"') do (
    set FOUND=1
    echo PID %%a kapatiliyor...
    taskkill /F /PID %%a >nul 2>&1
)

rem No window-title filter here — start.bat uses cmd /c so the panel cmd
rem closes automatically when python exits. A wildcard title filter would
rem also kill unrelated terminal windows the user has open.

if %FOUND%==0 (
    echo Panel zaten calismiyor.
) else (
    echo Panel kapatildi.
)

echo.
timeout /t 2 /nobreak >nul
