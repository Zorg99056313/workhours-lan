@echo off
chcp 65001 >nul
title Enable auto-start on logon
cd /d "%~dp0"
cd ..

rem ASCII-only on purpose. Runs the GUI launcher minimised at logon.
set "TASKNAME=WorkHoursServer"
set "TARGET=%~dp0..\WorkHours.exe"

if not exist "%TARGET%" (
    echo.
    echo   [X] WorkHours.exe not found next to this folder.
    echo       You can also use the "auto start" button inside the launcher.
    echo.
    pause
    exit /b 1
)

schtasks /query /tn "%TASKNAME%" >nul 2>nul
if not errorlevel 1 schtasks /delete /tn "%TASKNAME%" /f >nul 2>nul

schtasks /create /tn "%TASKNAME%" /tr "\"%TARGET%\" --autostart" /sc onlogon /f

echo.
if errorlevel 1 (
    echo   [X] Failed. Right-click this file, choose "Run as administrator", retry.
) else (
    echo   [OK] Auto-start enabled. The server will start at logon.
    echo.
    echo   To cancel:  schtasks /delete /tn "%TASKNAME%" /f
)
echo.
pause