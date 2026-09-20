@echo off
cd /d "%~dp0"
title L2D - Run

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
echo   Live2D AI Generator v2
echo ==========================================
echo   Browser will open http://127.0.0.1:7800
echo   Close this window to stop the service.
echo(
"%PY%" run.py %*

if errorlevel 1 (
    echo(
    echo   [ERROR] Service exited abnormally.
    pause
)
