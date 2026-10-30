@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Uninstall Work Hours Server

rem ASCII-only on purpose. All Chinese messages printed by uninstall.py
rem Prefer bundled runtime, fall back to system python.

set "PYEXE="
if exist "runtime\python.exe" set "PYEXE=runtime\python.exe"
if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE (
    echo.
    echo   Python not found and runtime\python.exe is missing.
    echo   Please delete this folder manually:  %~dp0
    echo.
    pause
    exit /b 1
)

"%PYEXE%" uninstall.py