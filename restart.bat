@echo off
cd /d "%~dp0"
title vurucu-tim-restart

echo.
echo === Vurucu TIM panel YENIDEN baslatiliyor (force) ===
echo.

rem 1) 5005'i dinleyen TUM PID'leri KESIN oldur (stop.bat bazen olduremiyordu)
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5005" ^| findstr "LISTENING"') do (
    set FOUND=1
    echo   Eski panel PID %%a oldurluyor...
    taskkill /F /PID %%a
)
if %FOUND%==0 echo   (Calisan panel yoktu.)

rem 2) portun tam bosalmasi icin bekle
timeout /t 3 /nobreak >nul

rem 3) stale bytecode temizle — kod degistiyse eski davranis kalmasin
for /d /r "src\short_bot" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul

rem 4) hala dinliyor mu kontrol
netstat -ano | findstr ":5005" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo.
    echo UYARI: 5005 hala mesgul — eski surec olmedi. Yonetici olarak calistir ya da
    echo        gorev yoneticisinden python.exe'yi kapat, sonra start.bat.
    pause
    exit /b 1
)

rem 5) TAZE baslat (gizli, loglar panel_*.log)
echo   Taze panel baslatiliyor...
wscript "%~dp0start_silent.vbs"

rem 6) yeni surec ayaga kalksin
timeout /t 6 /nobreak >nul
netstat -ano | findstr ":5005" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo   OK — panel ayakta. Tarayici aciliyor...
    start "" "http://127.0.0.1:5005"
) else (
    echo   Panel henuz cevap vermedi — birkac saniye sonra http://127.0.0.1:5005 dene.
    echo   Hata olursa panel_stderr.log'a bak.
)
echo.
