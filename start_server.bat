@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Work Hours Server
cls

rem ASCII-only on purpose (cmd.exe mis-parses non-ASCII in .bat under chcp 65001).
rem All Chinese messages are printed by launcher.py.
rem Prefers the bundled runtime, so this works even with no Python installed.

set "PYEXE="
if exist "%~dp0runtime\python.exe" set "PYEXE=%~dp0runtime\python.exe"
if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE (
    where py >nul 2>nul
    if not errorlevel 1 set "PYEXE=py"
)

if not defined PYEXE goto :NOPYTHON

if /i "%PYEXE%"=="py" (
    py -3 launcher.py
) else (
    "%PYEXE%" launcher.py
)
set "EXITCODE=%errorlevel%"

if not "%EXITCODE%"=="0" (
    echo.
    echo   --------------------------------------------------------
    echo    Server exited with code %EXITCODE%
    echo.
    echo    For a detailed reason, run:  python diagnose.py
    echo    ^(or double-click the diagnose script in the "tools" folder^)
    echo   --------------------------------------------------------
)
echo.
pause
exit /b %EXITCODE%

:NOPYTHON
echo.
echo   ==========================================================
echo    Python was NOT found, and the bundled runtime is missing.
echo.
echo    If you installed with the setup package, the "runtime"
echo    folder is probably missing or was removed by antivirus.
echo    Re-run the setup package, or whitelist this folder.
echo   ==========================================================
echo.
pause
exit /b 1