@echo off
cd /d "%~dp0"
title L2D - Setup

set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo(
    echo   [ERROR] venv not found:
    echo   %PY%
    echo(
    echo   Create it first:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe setup_env.py
    echo(
    pause
    exit /b 1
)

echo ==========================================
echo   Setup (downloads several GB, be patient)
echo ==========================================
"%PY%" setup_env.py
echo(
echo   Finished. Press any key to close.
pause >nul
