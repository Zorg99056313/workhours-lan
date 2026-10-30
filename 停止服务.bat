@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Stop Work Hours Server

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
if not defined PYEXE (
    echo   Python not found. Close the server window manually.
    pause
    exit /b 1
)

if /i "%PYEXE%"=="py" ( py -3 stop.py ) else ( "%PYEXE%" stop.py )
echo.
pause