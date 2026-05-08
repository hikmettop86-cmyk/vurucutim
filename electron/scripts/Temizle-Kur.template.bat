@echo off
chcp 65001 >nul
title VurucuTim - Temiz Kurulum
echo.
echo ============================================
echo   VurucuTim Temizle ve Yeniden Kur (v__VERSION__)
echo ============================================
echo.
echo Bu script su islemleri yapar:
echo   1. Acik VurucuTim'leri kapatir
echo   2. Eski kurulumu kaldirir
echo   3. Kalinti dosyalari siler (Python paketleri vb)
echo   4. v__VERSION__ indirir ve setup baslatilir (~155 MB)
echo.
echo Devam icin Enter'a basin (iptal: pencereyi kapatin)
pause >nul

set "PS=%TEMP%\vt_clean_install.ps1"
> "%PS%" echo $ErrorActionPreference = 'Continue'
>> "%PS%" echo Write-Host ''
>> "%PS%" echo Write-Host '[1/4] Acik VurucuTim kapatiliyor...' -ForegroundColor Cyan
>> "%PS%" echo Get-Process VurucuTim,electron,python -EA SilentlyContinue ^| Stop-Process -Force
>> "%PS%" echo Start-Sleep 2
>> "%PS%" echo Write-Host '[2/4] Eski kurulum kaldiriliyor...' -ForegroundColor Cyan
>> "%PS%" echo $un = Join-Path $env:LOCALAPPDATA 'Programs\VurucuTim\Uninstall VurucuTim.exe'
>> "%PS%" echo if (Test-Path $un) { ^& $un /S; Start-Sleep 10 } else { Write-Host '   (mevcut kurulum bulunamadi - skip)' -ForegroundColor Yellow }
>> "%PS%" echo Write-Host '[3/4] Kalinti dosyalar temizleniyor...' -ForegroundColor Cyan
>> "%PS%" echo Remove-Item (Join-Path $env:LOCALAPPDATA 'VurucuTim') -Recurse -Force -EA SilentlyContinue
>> "%PS%" echo Remove-Item (Join-Path $env:LOCALAPPDATA 'Programs\VurucuTim') -Recurse -Force -EA SilentlyContinue
>> "%PS%" echo Write-Host '[4/4] v__VERSION__ indiriliyor (~155 MB, biraz surer)...' -ForegroundColor Cyan
>> "%PS%" echo $url = 'https://github.com/hikmettop86-cmyk/vurucutim/releases/download/v__VERSION__/VurucuTim-Setup-__VERSION__.exe'
>> "%PS%" echo $out = Join-Path $env:TEMP 'VurucuTim-Setup-__VERSION__.exe'
>> "%PS%" echo [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
>> "%PS%" echo try { Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -TimeoutSec 600 } catch { Write-Host ('HATA: indirme basarisiz - ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }
>> "%PS%" echo $sizeMB = [math]::Round((Get-Item $out).Length / 1MB, 1)
>> "%PS%" echo Write-Host ('   Indirildi: ' + $sizeMB + ' MB') -ForegroundColor Gray
>> "%PS%" echo Write-Host ''
>> "%PS%" echo Write-Host 'Setup baslatiliyor — wizard penceresinde HEPSINI KUR tiklayin' -ForegroundColor Green
>> "%PS%" echo Start-Process $out

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS%"
del /F /Q "%PS%" 2>nul

echo.
echo ============================================
echo  Bitti. Wizard penceresi acilmali.
echo  Acilmadiysa: %TEMP%\VurucuTim-Setup-__VERSION__.exe
echo ============================================
pause
