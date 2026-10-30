@echo off
chcp 65001 >nul
cd /d "%~dp0"
cd ..
title Backup data

set "PYEXE="
if exist "%~dp0..\runtime\python.exe" set "PYEXE=%~dp0..\runtime\python.exe"
if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE (
    where py >nul 2>nul
    if not errorlevel 1 set "PYEXE=py"
)
if not defined PYEXE (
    echo   Python not found.
    pause
    exit /b 1
)

if /i "%PYEXE%"=="py" ( py -3 backup.py ) else ( "%PYEXE%" backup.py )
echo.
pause