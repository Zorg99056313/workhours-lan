@echo off
chcp 65001 >nul
title Allow LAN access (firewall)
cd /d "%~dp0"
cd ..

rem ASCII-only on purpose. Adds inbound rules for the bundled python + TCP port.
set "PORT=8000"
set "PY=%~dp0..\runtime\python.exe"
set "RULE=WorkHoursServer"

echo.
echo   Adding firewall rules for port %PORT% ...
echo   (This needs administrator rights.)
echo.

if exist "%PY%" (
    netsh advfirewall firewall delete rule name="%RULE%" >nul 2>nul
    netsh advfirewall firewall add rule name="%RULE%" dir=in action=allow program="%PY%" enable=yes profile=any
) else (
    echo   [note] runtime\python.exe not found, only the port rule is added.
    netsh advfirewall firewall delete rule name="%RULE%" >nul 2>nul
)

netsh advfirewall firewall delete rule name="%RULE% (port)" >nul 2>nul
netsh advfirewall firewall add rule name="%RULE% (port)" dir=in action=allow protocol=TCP localport=%PORT% enable=yes profile=any

echo.
if errorlevel 1 (
    echo   [X] Failed. Right-click this file, choose "Run as administrator", retry.
) else (
    echo   [OK] Done. Colleagues on the same LAN can now connect.
)
echo.
pause