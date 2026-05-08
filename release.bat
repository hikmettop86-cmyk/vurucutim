@echo off
rem VurucuTim release wrapper.
rem
rem Kullanim:
rem   release.bat 0.1.14
rem   release.bat 0.1.14 "yeni archetype + bug fix"
rem   release.bat 0.1.14 -DryRun

setlocal

if "%~1"=="" (
    echo.
    echo Kullanim: release.bat ^<version^> [^"notlar^"] [-DryRun]
    echo.
    echo Ornekler:
    echo   release.bat 0.1.14
    echo   release.bat 0.1.14 "yeni archetype + bug fix"
    echo   release.bat 0.1.14 -DryRun
    echo.
    exit /b 1
)

set "VERSION=%~1"

rem Notes ve DryRun parse
set "NOTES="
set "DRYRUN="
shift
:parse_args
if "%~1"=="" goto :run
if /i "%~1"=="-DryRun" (
    set "DRYRUN=-DryRun"
) else (
    set "NOTES=%~1"
)
shift
goto :parse_args

:run
if defined NOTES (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0electron\scripts\release.ps1" -NewVersion "%VERSION%" -Notes "%NOTES%" %DRYRUN%
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0electron\scripts\release.ps1" -NewVersion "%VERSION%" %DRYRUN%
)

set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
    echo.
    echo ! Release basarisiz oldu - exit code %EXITCODE%
    pause
)
endlocal & exit /b %EXITCODE%
