@echo off
setlocal enabledelayedexpansion
title VurucuTim Lisans Uretici

cd /d "%~dp0"

echo.
echo ================================================
echo   VurucuTim Lisans Anahtari Uretici
echo ================================================
echo.
echo Kullanici makine ID'sini girip Enter'a basin.
echo Cikmak icin bos birakip Enter'a basin.
echo.

:loop
set "MID="
set /p "MID=Makine ID (12 karakter): "
if "!MID!"=="" goto :end

rem 12 karakter kontrolu (basit)
set "len=0"
for /l %%i in (0,1,11) do (
    if not "!MID:~%%i,1!"=="" set /a len+=1
)
if not "!len!"=="12" (
    echo   ! HATA: Makine ID 12 karakter olmali, !len! karakter girildi.
    echo.
    goto :loop
)

rem Python script'i cagir
for /f "delims=" %%S in ('python "%~dp0make-license.py" --machine-id "!MID!" 2^>nul') do set "SERIAL=%%S"

if "!SERIAL!"=="" (
    echo   ! HATA: Serial uretilemedi. Python yuklu mu?
    echo.
    goto :loop
)

echo.
echo   Makine ID : !MID!
echo   Lisans    : !SERIAL!

rem Panoya kopyala
echo|set /p="!SERIAL!"|clip
if not errorlevel 1 echo   ^(panoya kopyalandi^)

echo.
echo   ------------------------------------------------
echo.
goto :loop

:end
echo.
echo Cikiliyor...
timeout /t 1 /nobreak >nul
endlocal
